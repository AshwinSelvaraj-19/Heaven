"""In-memory VC settings store, keyed by guild ID.

This module is the ONLY place that knows how settings are persisted. The rest of
the bot talks to ``get_settings`` / ``update_settings`` / ``clear_settings``,
so swapping the in-memory dict for a database later means changing this file
alone — command interfaces stay identical.
"""

from __future__ import annotations

from typing import Any

from bot.constants import DEFAULT_BITRATE, DEFAULT_LIMIT, DEFAULT_AUTODELETE_SECONDS

# guild_id -> {category_id, lobby_id, user_limit, bitrate, autodelete_seconds}
_store: dict[int, dict[str, Any]] = {}


def _defaults() -> dict[str, Any]:
    """Return the default settings record for a new guild."""
    return {
        "category_id": None,
        "lobby_id": None,
        "user_limit": DEFAULT_LIMIT,
        "bitrate": DEFAULT_BITRATE,
        "autodelete_seconds": DEFAULT_AUTODELETE_SECONDS,
    }


def get_settings(guild_id: int) -> dict[str, Any]:
    """Return the VC settings for a guild, creating defaults if absent."""
    if guild_id not in _store:
        _store[guild_id] = _defaults()
    return _store[guild_id]


def update_settings(guild_id: int, updates: dict[str, Any]) -> dict[str, Any]:
    """Merge ``updates`` into a guild's settings and return the full record."""
    settings = get_settings(guild_id)
    settings.update(updates)
    return settings


def clear_settings(guild_id: int) -> None:
    """Remove a guild's settings entry entirely."""
    _store.pop(guild_id, None)


def all_settings() -> dict[int, dict[str, Any]]:
    """Return a shallow copy of all guild settings (used for orphan cleanup)."""
    return dict(_store)
