"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Immutable config sourced from environment variables."""

    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")

    # Sensible defaults for temp channels when a guild hasn't configured them.
    DEFAULT_USER_LIMIT: int = 0  # 0 = unlimited
    DEFAULT_BITRATE: int = 64000  # 64 kbps
    DEFAULT_AUTODELETE_SECONDS: int = 300  # 5 minutes


config = Config()
