"""Centralized configuration loaded from environment variables."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


class Config:
    """Immutable config sourced from environment variables."""

    DISCORD_TOKEN: str = os.getenv("DISCORD_TOKEN", "")


config = Config()
