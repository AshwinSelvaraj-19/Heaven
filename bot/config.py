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
    SUPABASE_URL: str = os.getenv("SUPABASE_URL", "")
    SUPABASE_KEY: str = os.getenv("SUPABASE_KEY", "")
    PERMANENT_VOICE_CHANNEL_ID: str = os.getenv("PERMANENT_VOICE_CHANNEL_ID", "")

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
