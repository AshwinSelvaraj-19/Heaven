"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger("bot.config")


class Config:
    """Immutable config sourced from environment variables."""

    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")
    SUPABASE_URL: str = os.getenv("SUPABASE_URL") or os.getenv("VITE_SUPABASE_URL", "")
    SUPABASE_KEY: str = (
        os.getenv("SUPABASE_KEY")
        or os.getenv("SUPABASE_ANON_KEY")
        or os.getenv("SUPABASE_SERVICE_ROLE_KEY")
        or os.getenv("VITE_SUPABASE_ANON_KEY")
        or os.getenv("VITE_SUPABASE_SERVICE_ROLE_KEY", "")
    )

    def validate_supabase(self) -> bool:
        """Return True if both Supabase variables are present.

        Logs a clear error if either variable is missing. Never logs the
        actual value of SUPABASE_KEY.
        """
        if not self.SUPABASE_URL:
            logger.error("SUPABASE_URL is not set. Add it to your .env file or environment variables.")
            return False
        if not self.SUPABASE_KEY:
            logger.error("SUPABASE_KEY is not set. Add it to your .env file or environment variables.")
            return False
        return True


config = Config()
