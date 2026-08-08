"""Centralized constants for the VC control module.

All magic numbers live here so they can be referenced from a single source of
truth and tuned without touching business logic.
"""

from __future__ import annotations

# ------------------------------------------------------------------ #
# Bitrate (kbps input → stored as bps)
# ------------------------------------------------------------------ #
MIN_BITRATE: int = 8
MAX_BITRATE: int = 384
DEFAULT_BITRATE: int = 64_000  # bps

# ------------------------------------------------------------------ #
# User limit
# ------------------------------------------------------------------ #
MIN_LIMIT: int = 0  # 0 = unlimited
MAX_LIMIT: int = 99
DEFAULT_LIMIT: int = 5

# ------------------------------------------------------------------ #
# Autodelete delay (seconds)
# ------------------------------------------------------------------ #
MIN_DELETE_DELAY: int = 0
MAX_DELETE_DELAY: int = 3600
DEFAULT_AUTODELETE_SECONDS: int = 60  # 60 seconds

# ------------------------------------------------------------------ #
# Rate limiting
# ------------------------------------------------------------------ #
USER_CREATE_COOLDOWN: int = 5  # seconds between temp channel creations per user
COMMAND_COOLDOWN: int = 3  # seconds between VC commands (rename, muteall, movall)

# ------------------------------------------------------------------ #
# Temp channel naming
# ------------------------------------------------------------------ #
TEMP_CHANNEL_PREFIX: str = "\N{STUDIO MICROPHONE} "  # "🎤 "

# ------------------------------------------------------------------ #
# Required bot permissions for temp channel creation
# ------------------------------------------------------------------ #
REQUIRED_PERMISSIONS: tuple[str, ...] = (
    "manage_channels",
    "move_members",
    "view_channel",
    "connect",
)
