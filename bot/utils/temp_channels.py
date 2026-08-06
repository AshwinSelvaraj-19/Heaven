"""Manages creation and deletion of temporary voice channels."""

from __future__ import annotations

import asyncio
import logging

import discord

from bot.settings_store import get_settings
from bot.config import config

logger = logging.getLogger(__name__)

# Tracks scheduled deletion tasks per channel id so we can cancel if someone rejoins.
_deletion_tasks: dict[int, asyncio.Task[None]] = {}


async def create_temp_channel(
    guild: discord.Guild, member: discord.Member
) -> discord.VoiceChannel | None:
    """Create a temp voice channel under the configured category and move the member.

    Returns the created channel, or None if settings are incomplete or creation fails.
    """
    settings = get_settings(guild.id)

    category_id = settings.get("category_id")
    if not category_id:
        return None

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        return None

    user_limit = settings.get("user_limit") or config.DEFAULT_USER_LIMIT
    bitrate = settings.get("bitrate") or config.DEFAULT_BITRATE

    overwrites = {
        guild.default_role: discord.PermissionOverwrite(view_channel=True),
        member: discord.PermissionOverwrite(
            view_channel=True,
            manage_channels=True,
            move_members=True,
            mute_members=True,
            deafen_members=True,
        ),
    }

    try:
        channel = await guild.create_voice_channel(
            name=f"{member.display_name}'s Channel",
            category=category,
            user_limit=user_limit,
            bitrate=bitrate,
            overwrites=overwrites,
            reason=f"Temp channel created for {member} via lobby join",
        )
    except discord.Forbidden:
        logger.warning(
            "Missing permissions to create voice channel in guild %s", guild.id
        )
        return None
    except discord.HTTPException as exc:
        logger.error("Failed to create temp channel in guild %s: %s", guild.id, exc)
        return None

    try:
        await member.move_to(channel, reason="Moved to temp channel")
    except discord.HTTPException as exc:
        logger.warning("Failed to move %s to temp channel: %s", member, exc)

    return channel


def cancel_deletion(channel_id: int) -> None:
    """Cancel a pending deletion task for a channel (e.g. someone rejoined)."""
    task = _deletion_tasks.pop(channel_id, None)
    if task and not task.done():
        task.cancel()


async def schedule_deletion(channel: discord.VoiceChannel, delay: int) -> None:
    """Delete a voice channel after ``delay`` seconds if it is still empty."""
    await asyncio.sleep(delay)

    # Re-check emptiness after the wait.
    if channel.members:
        return

    try:
        await channel.delete(reason="Temp channel empty — autodelete")
    except discord.NotFound:
        pass  # Already deleted.
    except discord.Forbidden:
        logger.warning("Missing permissions to delete channel %s", channel.id)
    except discord.HTTPException as exc:
        logger.error("Failed to delete temp channel %s: %s", channel.id, exc)
    finally:
        _deletion_tasks.pop(channel.id, None)


def maybe_schedule_deletion(channel: discord.VoiceChannel) -> None:
    """If the channel is empty and autodelete is configured, schedule deletion."""
    if channel.members:
        return

    settings = get_settings(channel.guild.id)
    autodelete = settings.get("autodelete_seconds") or config.DEFAULT_AUTODELETE_SECONDS

    cancel_deletion(channel.id)
    task = asyncio.create_task(schedule_deletion(channel, autodelete))
    _deletion_tasks[channel.id] = task
