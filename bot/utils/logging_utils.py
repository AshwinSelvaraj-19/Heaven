"""Structured logging helpers for the VC control module.

Every important action is logged with a consistent set of contextual fields so
that logs are greppable and machine-parseable.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Literal

import discord

logger = logging.getLogger("bot.vc")

Action = Literal[
    "VC_CREATED",
    "VC_DELETED",
    "VC_LOCKED",
    "VC_UNLOCKED",
    "VC_RENAMED",
    "USER_MOVED",
    "DELETE_CANCELLED",
    "CONFIG_ERROR",
    "PERMISSION_ERROR",
]


def log_action(
    action: Action,
    *,
    guild: discord.Guild | None = None,
    user: discord.Member | discord.User | None = None,
    channel: discord.abc.GuildChannel | None = None,
    detail: str = "",
) -> None:
    """Log a structured VC lifecycle event.

    Parameters
    ----------
    action:
        One of ``VC_CREATED``, ``VC_DELETED``, ``USER_MOVED``,
        ``DELETE_CANCELLED``, ``CONFIG_ERROR``, ``PERMISSION_ERROR``.
    guild, user, channel:
        Optional Discord objects whose name/id are extracted safely.
    detail:
        Free-text context appended to the message.
    """
    parts: list[str] = [f"action={action}"]

    if guild is not None:
        parts.append(f"guild_name={guild.name!r}")
        parts.append(f"guild_id={guild.id}")

    if user is not None:
        parts.append(f"user_name={user!s}")
        parts.append(f"user_id={user.id}")

    if channel is not None:
        parts.append(f"channel_name={channel.name!r}")
        parts.append(f"channel_id={channel.id}")

    parts.append(f"timestamp={datetime.now(timezone.utc).isoformat()}")

    if detail:
        parts.append(f"detail={detail}")

    message = " | ".join(parts)

    if action in ("CONFIG_ERROR", "PERMISSION_ERROR"):
        logger.error(message)
    else:
        logger.info(message)
