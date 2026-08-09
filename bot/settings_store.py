"""Guild VC settings store backed by Supabase with a write-through in-memory cache.

The public surface (:func:`get_settings`, :func:`update_settings`,
:func:`clear_settings`, :func:`all_settings`) keeps the exact synchronous
signatures and semantics of the original in-memory implementation. Callers
do **not** need modification.

Persistence details
-------------------
All settings are written to ``public.guild_settings`` (Supabase / Postgres).
An in-memory dict is used as a write-through cache so that the hot path
(:func:`get_settings` inside ``on_voice_state_update``) never hits the
network.

On first access for a guild the cache is lazy-loaded from the database. To
ensure :func:`all_settings` reflects persisted data after process restart,
call :func:`preload_all_settings` once early during startup from an async
context (e.g. ``on_ready``) via ``asyncio.to_thread``.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional, Union

from postgrest import APIError as PostgrestAPIError

from bot.constants import DEFAULT_AUTODELETE_SECONDS, DEFAULT_BITRATE, DEFAULT_LIMIT
from bot.supabase_client import get_client

logger = logging.getLogger("bot.settings")

_TABLE: str = "guild_settings"

# guild_id -> {category_id, lobby_id, user_limit, bitrate, autodelete_seconds}
_store: dict[int, dict[str, Any]] = {}

# Tracks which guilds have been lazy-loaded from the database (even if the
# row did not exist in Supabase). This prevents us from re-querying the DB
# on every voice state event for an unconfigured guild.
_checked_guilds: set[int] = set()


# Sentinel returned by ``_select_row`` to signal a database-request failure
# (network, auth, client unavailable, postgrest error …). Distinct from
# ``None`` which means "row confirmed absent".
_DB_ERROR: Any = object()


# ------------------------------------------------------------------ #
# Defaults and row translation helpers
# ------------------------------------------------------------------ #


def _defaults() -> dict[str, Any]:
    """Return the default settings record for a new guild.

    These defaults are the *application* defaults. They are not written
    to the database unless :func:`update_settings` is subsequently called
    with at least one change — matching the original behaviour of never
    writing a "default-only" row.
    """
    return {
        "category_id": None,
        "lobby_id": None,
        "user_limit": DEFAULT_LIMIT,
        "bitrate": DEFAULT_BITRATE,
        "autodelete_seconds": DEFAULT_AUTODELETE_SECONDS,
    }


def _row_to_settings(row: dict[str, Any]) -> dict[str, Any]:
    """Translate a Supabase row into the settings dict expected by callers.

    Fields in the database that are not part of the VC-settings contract
    (``prefix``, ``created_at``, ``updated_at``) are preserved during
    writes but never returned through the public API.
    """
    return {
        "category_id": row.get("category_id"),
        "lobby_id": row.get("lobby_id"),
        "user_limit": _int_or_default(row.get("user_limit"), DEFAULT_LIMIT),
        "bitrate": _int_or_default(row.get("bitrate"), DEFAULT_BITRATE),
        "autodelete_seconds": _int_or_default(
            row.get("autodelete_seconds"), DEFAULT_AUTODELETE_SECONDS
        ),
    }


def _settings_to_row(guild_id: int, settings: dict[str, Any], *, is_new: bool) -> dict[str, Any]:
    """Translate a settings dict into a row payload for Supabase.

    ``is_new`` controls whether ``created_at`` is included alongside
    ``updated_at``.
    """
    now = datetime.now(timezone.utc).isoformat()
    row: dict[str, Any] = {
        "guild_id": guild_id,
        "category_id": settings.get("category_id"),
        "lobby_id": settings.get("lobby_id"),
        "user_limit": settings.get("user_limit"),
        "bitrate": settings.get("bitrate"),
        "autodelete_seconds": settings.get("autodelete_seconds"),
        "updated_at": now,
    }
    if is_new:
        row["created_at"] = now
    return row


def _int_or_default(value: Any, default: int) -> int:
    """Return ``value`` as ``int`` if numeric, else ``default``."""
    if value is None:
        return default
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


# ------------------------------------------------------------------ #
# Internal database helpers
# ------------------------------------------------------------------ #


def _select_row(guild_id: int) -> Union[dict[str, Any], None, Any]:
    """Fetch a single row from the settings table.

    Returns
    -------
    dict
        The row when one exists for ``guild_id``.
    None
        The query reached the database successfully but no row matched
        (confirmed "row not found").
    _DB_ERROR
        The database request failed (client unavailable, network error,
        Postgrest exception …). Callers MUST NOT permanently mark the
        guild as successfully checked; a later call should retry.
    """
    client = get_client()
    if client is None:
        return _DB_ERROR
    try:
        response = (
            client.table(_TABLE)
            .select("*")
            .eq("guild_id", guild_id)
            .limit(1)
            .execute()
        )
    except PostgrestAPIError as exc:
        logger.error(
            "Supabase settings read failed for guild %s: %s", guild_id, exc.message
        )
        return _DB_ERROR
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(
            "Supabase settings read failed for guild %s: %s", guild_id, exc
        )
        return _DB_ERROR

    data = getattr(response, "data", None) or []
    if not data:
        return None
    return data[0]


def _select_all_rows() -> list[dict[str, Any]]:
    """Fetch every row from the settings table. Returns ``[]`` on error."""
    client = get_client()
    if client is None:
        return []
    try:
        response = client.table(_TABLE).select("*").execute()
    except PostgrestAPIError as exc:
        logger.error("Supabase settings bulk read failed: %s", exc.message)
        return []
    except Exception as exc:  # pragma: no cover - defensive
        logger.error("Supabase settings bulk read failed: %s", exc)
        return []
    return list(getattr(response, "data", None) or [])


def _upsert_row(guild_id: int, merged: dict[str, Any], *, row_existed: bool) -> bool:
    """Upsert a full settings record. Returns ``True`` on success.

    A full upsert (not a partial patch) keeps the logic simple: the
    caller is responsible for merging with prior state before calling.
    """
    client = get_client()
    if client is None:
        logger.error(
            "Cannot persist settings for guild %s: Supabase client unavailable.",
            guild_id,
        )
        return False

    payload = _settings_to_row(guild_id, merged, is_new=not row_existed)

    try:
        client.table(_TABLE).upsert(payload, on_conflict="guild_id").execute()
    except PostgrestAPIError as exc:
        logger.error(
            "Supabase settings write failed for guild %s: %s", guild_id, exc.message
        )
        return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(
            "Supabase settings write failed for guild %s: %s", guild_id, exc
        )
        return False
    return True


def _delete_row(guild_id: int) -> bool:
    """Delete a row by PK. Returns ``True`` on success or row absent."""
    client = get_client()
    if client is None:
        logger.error(
            "Cannot clear settings for guild %s: Supabase client unavailable.",
            guild_id,
        )
        return False
    try:
        client.table(_TABLE).delete().eq("guild_id", guild_id).execute()
    except PostgrestAPIError as exc:
        logger.error(
            "Supabase settings delete failed for guild %s: %s",
            guild_id,
            exc.message,
        )
        return False
    except Exception as exc:  # pragma: no cover - defensive
        logger.error(
            "Supabase settings delete failed for guild %s: %s", guild_id, exc
        )
        return False
    return True


# ------------------------------------------------------------------ #
# Public API — identical signatures to the original in-memory store
# ------------------------------------------------------------------ #


def get_settings(guild_id: int) -> dict[str, Any]:
    """Return the VC settings for ``guild_id``, creating defaults if absent.

    Cache-happy: served from the in-memory dict on the hot path. On cache
    miss the database is consulted. If the database reports "no row", mark the
    guild checked so we don't re-query every voice event. If the *request
    itself fails, leave the guild UNCHECKED so a later call can retry.
    """
    if guild_id in _store:
        return _store[guild_id]

    # Lazy-load from Supabase on first access for this guild.
    if guild_id in _checked_guilds:
        settings = _defaults()
        _store[guild_id] = settings
        return _store[guild_id]

    result = _select_row(guild_id)

    if result is _DB_ERROR:
        # Safe fallback to defaults, but DO NOT mark checked — allow retries later.
        settings = _defaults()
        _store[guild_id] = settings
        return _store[guild_id]

    # DB query reached successfully (row found or confirmed absent — mark checked.
    _checked_guilds.add(guild_id)

    if isinstance(result, dict):
        settings = _row_to_settings(result)
    else:
        # result is None — row confirmed absent, not error.
        settings = _defaults()

    _store[guild_id] = settings
    return _store[guild_id]


def update_settings(guild_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into a guild's settings and return the full record.

    Only keys present in ``updates`` are overwritten; all other fields
    retain their previous value. The merge is performed against the
    cache first, falling back to a DB read and then defaults so that
    unspecified fields are never clobbered with ``None`` or default
    values.

    The merged record is persisted to Supabase via a safe upsert on
    conflict of ``guild_id``. If the persistence step fails, the cache
    is still updated so the running process observes the change; the
    failure is clearly logged so an operator can investigate.

    ``_checked_guilds`` is only updated when the DB is actually reached
    (either a successful read OR a successful write) so that a transient
    DB outage does not permanently disable retries.
    """
    # --- Merge on top of existing state ------------------------------ #
    if guild_id in _store:
        current = dict(_store[guild_id])
        row_existed = True
        db_read_reached = True  # cached, so we've previously synced
    elif guild_id in _checked_guilds:
        current = _defaults()
        row_existed = False
        db_read_reached = True
    else:
        result = _select_row(guild_id)
        if result is _DB_ERROR:
            # Read failed: merge against defaults. Don't mark checked — allow retry.
            current = _defaults()
            row_existed = False  # safest: upsert without created_at write
            db_read_reached = False
        else:
            db_read_reached = True
            row_existed = isinstance(result, dict)
            current = _row_to_settings(result) if row_existed else _defaults()

    merged = {**current, **updates}

    # --- Persist (safe upsert, never clobbers unspecified cols) ------ #
    write_ok = _upsert_row(guild_id, merged, row_existed=row_existed)
    if not write_ok:
        logger.warning(
            "Guild %s settings update not persisted — will be lost on restart.",
            guild_id,
        )

    # --- Update cache (write-through even on DB failure for session) - #
    _store[guild_id] = merged

    # Only mark the guild checked if we successfully talked to the DB
    # via read OR write — prevents transient outage from poisoning retries.
    if db_read_reached or write_ok:
        _checked_guilds.add(guild_id)

    return _store[guild_id]


def clear_settings(guild_id: int) -> None:
    """Remove a guild's settings entry entirely (cache + database)."""
    ok = _delete_row(guild_id)
    if not ok:
        logger.warning(
            "Guild %s settings clear not persisted — will reappear on restart.",
            guild_id,
        )
    _store.pop(guild_id, None)
    _checked_guilds.discard(guild_id)


def all_settings() -> dict[int, dict[str, Any]]:
    """Return a shallow copy of all cached guild settings.

    Used by the orphan-cleanup routine on startup. Callers MUST ensure
    :func:`preload_all_settings` runs before this function so that the
    cache represents persisted state and not a "whatever has been
    accessed so far" subset.
    """
    return dict(_store)


# ------------------------------------------------------------------ #
# Startup preload
# ------------------------------------------------------------------ #


def preload_all_settings() -> int:
    """Populate the in-memory cache from all rows in Supabase.

    Returns the number of guilds loaded. Safe to call multiple times
    (subsequent calls re-sync the cache from the database).

    This is a synchronous function; invoke it from the async bot
    startup hook via ``asyncio.to_thread(preload_all_settings)``.
    """
    rows = _select_all_rows()
    loaded = 0
    for row in rows:
        try:
            gid = int(row["guild_id"])
        except (KeyError, TypeError, ValueError):
            logger.warning("Skipping guild_settings row with invalid guild_id: %r", row)
            continue
        _store[gid] = _row_to_settings(row)
        _checked_guilds.add(gid)
        loaded += 1
    logger.info("Preloaded %d guild settings from Supabase.", loaded)
    return loaded
