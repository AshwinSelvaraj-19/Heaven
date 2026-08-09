"""Manages permanent voice channel connection for the bot.

This module handles connecting the bot to a permanent voice channel that
already exists in the Discord server. The bot will join this channel on
startup and maintain the connection with automatic reconnection on failure.

The permanent voice channel is completely separate from the temporary VC
system - it has no ownership tracking, no autodeletion, and is excluded
from all temporary VC cleanup operations.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from bot.config import config

logger = logging.getLogger("bot.permanent_voice")

# Track the permanent voice channel ID to exclude from cleanup
_PERMANENT_CHANNEL_ID: int | None = None

# Reconnection backoff settings
_MAX_RETRIES = 5
_INITIAL_BACKOFF = 2.0  # seconds
_MAX_BACKOFF = 60.0  # seconds

# Task guard to prevent duplicate reconnection attempts
_reconnect_task: asyncio.Task[None] | None = None


def get_permanent_channel_id() -> int | None:
    """Return the permanent voice channel ID, or None if not configured."""
    return _PERMANENT_CHANNEL_ID


def _parse_channel_id() -> int | None:
    """Parse PERMANENT_VOICE_CHANNEL_ID from config.

    Returns None if not configured or invalid.
    """
    channel_id_str = config.PERMANENT_VOICE_CHANNEL_ID
    if not channel_id_str:
        return None

    try:
        return int(channel_id_str)
    except (ValueError, TypeError):
        logger.error(
            "Invalid PERMANENT_VOICE_CHANNEL_ID: %r (must be an integer)",
            channel_id_str
        )
        return None


async def connect_to_permanent_voice(bot: discord.Client) -> None:
    """Connect the bot to the permanent voice channel.

    This function:
    - Resolves the channel ID from config
    - Verifies the channel exists and is a voice channel
    - Connects the bot to it
    - Handles connection failures gracefully
    - Does not block if the channel is not configured

    The connection is attempted once on startup. If it fails, an error
    is logged but the bot continues to function normally.
    """
    global _PERMANENT_CHANNEL_ID

    channel_id = _parse_channel_id()
    if not channel_id:
        logger.info("No permanent voice channel configured (PERMANENT_VOICE_CHANNEL_ID not set)")
        return

    _PERMANENT_CHANNEL_ID = channel_id

    # Find the channel across all guilds
    channel = None
    for guild in bot.guilds:
        found = guild.get_channel(channel_id)
        if found is not None:
            channel = found
            break

    if channel is None:
        logger.error(
            "Permanent voice channel %s not found in any guild",
            channel_id
        )
        return

    if not isinstance(channel, discord.VoiceChannel):
        logger.error(
            "Permanent voice channel %s is not a voice channel (type: %s)",
            channel_id,
            type(channel).__name__
        )
        return

    # Check if bot is already connected to this channel
    voice_client = channel.guild.voice_client
    if voice_client is not None and voice_client.channel.id == channel.id:
        logger.info(
            "Already connected to permanent voice channel: %s",
            channel.name
        )
        return

    # Connect to the channel
    logger.info(
        "Connecting to permanent voice channel: %s (ID: %s)",
        channel.name,
        channel.id
    )

    try:
        await channel.connect()
        logger.info(
            "Connected to permanent voice channel: %s",
            channel.name
        )
    except discord.Forbidden:
        logger.error(
            "Permission denied connecting to permanent voice channel %s",
            channel.name
        )
    except discord.HTTPException as exc:
        logger.error(
            "HTTP error connecting to permanent voice channel %s: %s",
            channel.name,
            exc
        )
    except Exception as exc:
        logger.error(
            "Unexpected error connecting to permanent voice channel %s: %s",
            channel.name,
            exc
        )


async def ensure_permanent_connection(bot: discord.Client) -> None:
    """Ensure the bot is connected to the permanent voice channel.

    This can be called periodically to reconnect if the bot was disconnected.
    Uses exponential backoff for retries.
    """
    channel_id = get_permanent_channel_id()
    if not channel_id:
        return

    # Find the channel
    channel = None
    for guild in bot.guilds:
        found = guild.get_channel(channel_id)
        if found is not None:
            channel = found
            break

    if channel is None or not isinstance(channel, discord.VoiceChannel):
        logger.warning("Permanent voice channel %s not found or invalid", channel_id)
        return

    # Check if already connected
    voice_client = channel.guild.voice_client
    if voice_client is not None and voice_client.channel.id == channel.id:
        return

    # Attempt reconnection with backoff
    backoff = _INITIAL_BACKOFF
    for attempt in range(1, _MAX_RETRIES + 1):
        try:
            logger.info(
                "Reconnection attempt %d/%d to permanent voice channel: %s",
                attempt,
                _MAX_RETRIES,
                channel.name
            )
            await channel.connect()
            logger.info(
                "Reconnected to permanent voice channel: %s",
                channel.name
            )
            return
        except discord.Forbidden:
            logger.error(
                "Permission denied reconnecting to permanent voice channel %s",
                channel.name
            )
            return
        except discord.HTTPException as exc:
            logger.warning(
                "HTTP error on reconnection attempt %d to %s: %s",
                attempt,
                channel.name,
                exc
            )
        except Exception as exc:
            logger.warning(
                "Unexpected error on reconnection attempt %d to %s: %s",
                attempt,
                channel.name,
                exc
            )

        if attempt < _MAX_RETRIES:
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, _MAX_BACKOFF)

    logger.error(
        "Failed to reconnect to permanent voice channel %s after %d attempts",
        channel.name,
        _MAX_RETRIES
    )


def _is_bot_disconnected_from_permanent(bot: discord.Client) -> bool:
    """Check if the bot is disconnected from the permanent voice channel.

    Returns True if:
    - Permanent channel is configured
    - Bot is not connected to any voice channel in that guild
    - OR bot is connected to a different channel in that guild

    Returns False if:
    - Permanent channel is not configured
    - Bot is already connected to the permanent channel
    """
    global _reconnect_task

    channel_id = get_permanent_channel_id()
    if not channel_id:
        return False

    # Check if a reconnection task is already running
    if _reconnect_task is not None and not _reconnect_task.done():
        return False  # Already attempting reconnection

    # Find the permanent channel
    channel = None
    for guild in bot.guilds:
        found = guild.get_channel(channel_id)
        if found is not None:
            channel = found
            break

    if channel is None or not isinstance(channel, discord.VoiceChannel):
        return False  # Channel not found or invalid

    # Check bot's current voice state in that guild
    voice_client = channel.guild.voice_client
    if voice_client is None:
        return True  # Bot is not connected to any VC in that guild

    if voice_client.channel.id != channel_id:
        return True  # Bot is connected to a different channel

    return False  # Bot is connected to the permanent channel


def schedule_reconnection(bot: discord.Client) -> None:
    """Schedule a reconnection task if the bot is disconnected from permanent VC.

    This function is non-blocking and creates a background task for reconnection.
    It checks if a reconnection is already in progress to prevent duplicates.
    """
    global _reconnect_task

    if not _is_bot_disconnected_from_permanent(bot):
        return

    # Cancel existing task if it's done
    if _reconnect_task is not None and _reconnect_task.done():
        _reconnect_task = None

    # Create new reconnection task if none exists
    if _reconnect_task is None:
        logger.info("Permanent voice channel disconnected; attempting reconnect.")
        _reconnect_task = asyncio.create_task(ensure_permanent_connection(bot))
        # Clean up task reference when done
        def _cleanup_task(task: asyncio.Task[None]) -> None:
            global _reconnect_task
            if task == _reconnect_task:
                _reconnect_task = None

        _reconnect_task.add_done_callback(_cleanup_task)


def on_bot_voice_state_update(
    bot: discord.Client,
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    """Handle bot voice state changes to trigger reconnection if needed.

    This function should be called from the bot's on_voice_state_update event.
    It only reacts to the bot's own voice state changes, not normal users.

    Parameters
    ----------
    bot:
        The Discord bot client.
    member:
        The member whose voice state changed.
    before:
        The voice state before the change.
    after:
        The voice state after the change.
    """
    # Only react to the bot's own voice state changes
    if member.id != bot.user.id:
        return

    # Schedule reconnection check (non-blocking)
    schedule_reconnection(bot)
