"""Tracks temporary channel ownership and rate-limit state.

Two parallel mappings are maintained:

- ``temp_channels``: channel_id → ownership metadata
- ``user_channels``: user_id → channel_id (fast lookup)

This module is deliberately self-contained so that future per-channel commands
(`/vc lock`, `/vc rename`, `/vc transfer`, `/vc kick`, …) can query and mutate
ownership without touching the voice listener or settings store.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any

# ------------------------------------------------------------------ #
# Data structures
# ------------------------------------------------------------------ #


@dataclass
class ChannelOwnership:
    """Metadata for a single temporary voice channel."""

    owner: int
    guild: int
    created_at: float = field(default_factory=time.time)
    delete_task: asyncio.Task[None] | None = None

    def as_dict(self) -> dict[str, Any]:
        """Return a serialisable view (useful for debugging / future APIs)."""
        return {
            "owner": self.owner,
            "guild": self.guild,
            "created_at": self.created_at,
            "delete_task": self.delete_task,
        }


# channel_id -> ChannelOwnership
temp_channels: dict[int, ChannelOwnership] = {}

# user_id -> channel_id (fast reverse lookup)
user_channels: dict[int, int] = {}

# user_id -> monotonic timestamp of last temp channel creation
_cooldowns: dict[int, float] = {}


# ------------------------------------------------------------------ #
# Ownership
# ------------------------------------------------------------------ #


def register_channel(channel_id: int, owner_id: int, guild_id: int) -> ChannelOwnership:
    """Record a new temp channel and its owner."""
    ownership = ChannelOwnership(owner=owner_id, guild=guild_id)
    temp_channels[channel_id] = ownership
    user_channels[owner_id] = channel_id
    return ownership


def unregister_channel(channel_id: int) -> ChannelOwnership | None:
    """Remove a temp channel from tracking. Returns the removed record, if any."""
    ownership = temp_channels.pop(channel_id, None)
    if ownership is not None:
        user_channels.pop(ownership.owner, None)
    return ownership


def get_ownership(channel_id: int) -> ChannelOwnership | None:
    """Return the ownership record for a channel, or None."""
    return temp_channels.get(channel_id)


def get_channel_for_user(user_id: int) -> int | None:
    """Return the channel id owned by ``user_id``, or None."""
    return user_channels.get(user_id)


def set_delete_task(channel_id: int, task: asyncio.Task[None]) -> None:
    """Attach (or replace) the pending deletion task for a channel."""
    ownership = temp_channels.get(channel_id)
    if ownership is not None:
        ownership.delete_task = task


def clear_delete_task(channel_id: int) -> asyncio.Task[None] | None:
    """Remove and return the pending deletion task for a channel, if any."""
    ownership = temp_channels.get(channel_id)
    if ownership is None:
        return None
    task = ownership.delete_task
    ownership.delete_task = None
    return task


# ------------------------------------------------------------------ #
# Rate limiting
# ------------------------------------------------------------------ #


def is_on_cooldown(user_id: int, cooldown: int) -> bool:
    """Return True if ``user_id`` created a channel within the last ``cooldown`` seconds."""
    last = _cooldowns.get(user_id)
    if last is None:
        return False
    return (time.monotonic() - last) < cooldown


def mark_cooldown(user_id: int) -> None:
    """Record that ``user_id`` just created a temp channel."""
    _cooldowns[user_id] = time.monotonic()
