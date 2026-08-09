"""Singleton Supabase client module.

Creates a single shared synchronous Supabase client on first access. The
client is reused across the entire application instead of being
re-created for every database operation.

Configuration is sourced from :mod:`bot.config`. If Supabase environment
variables are missing, :func:`get_client` returns ``None`` and the
configuration error is logged exactly once (the key is never logged).
"""

from __future__ import annotations

import logging
from typing import Optional

from supabase import Client, SupabaseException, create_client

from bot.config import config

logger = logging.getLogger("bot.supabase")

_client: Optional[Client] = None
_initialized: bool = False


def get_client() -> Optional[Client]:
    """Return the singleton Supabase client, or ``None`` if unavailable.

    The client is created once on the first call. Subsequent calls return
    the same instance. If configuration is invalid or client creation
    fails, ``None`` is returned and the failure is logged (without
    exposing the key).
    """
    global _client, _initialized

    if _initialized:
        return _client

    _initialized = True

    if not config.validate_supabase():
        return None

    try:
        _client = create_client(config.SUPABASE_URL, config.SUPABASE_KEY)
        logger.info("Supabase client initialized successfully.")
        return _client
    except SupabaseException as exc:
        logger.error("Failed to initialize Supabase client: %s", exc.message)
        _client = None
        return None
    except Exception as exc:  # pragma: no cover - defensive catch-all
        logger.error("Unexpected error initializing Supabase client: %s", exc)
        _client = None
        return None
