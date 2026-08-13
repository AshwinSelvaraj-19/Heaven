"""Manages permanent voice channel connection for the bot.

The permanent voice channel is separate from the temporary VC system.
The bot joins this channel on startup and maintains the connection with
safe automatic reconnection.
"""

from __future__ import annotations

import asyncio
import logging

import discord

from bot.config import config

logger = logging.getLogger("bot.permanent_voice")

# ------------------------------------------------------------------ #
# Permanent channel
# ------------------------------------------------------------------ #

_PERMANENT_CHANNEL_ID: int | None = None

# ------------------------------------------------------------------ #
# Reconnection configuration
# ------------------------------------------------------------------ #

_MAX_RETRIES = 5
_INITIAL_BACKOFF = 3.0
_MAX_BACKOFF = 60.0

# Wait before custom reconnect.
#
# discord.py already has its own voice reconnection mechanism.
# We wait first so we don't race against it.
_RECONNECT_DELAY = 8.0

# Background reconnect task.
_reconnect_task: asyncio.Task[None] | None = None


def get_permanent_channel_id() -> int | None:
    """Return the configured permanent voice channel ID."""
    return _PERMANENT_CHANNEL_ID


def _parse_channel_id() -> int | None:
    """Parse PERMANENT_VOICE_CHANNEL_ID from configuration."""

    channel_id_str = config.PERMANENT_VOICE_CHANNEL_ID

    if not channel_id_str:
        return None

    try:
        return int(channel_id_str)

    except (ValueError, TypeError):
        logger.error(
            "Invalid PERMANENT_VOICE_CHANNEL_ID: %r "
            "(must be an integer)",
            channel_id_str,
        )
        return None


def _find_permanent_channel(
    bot: discord.Client,
) -> discord.VoiceChannel | None:
    """Find the configured permanent voice channel."""

    channel_id = get_permanent_channel_id()

    if channel_id is None:
        return None

    for guild in bot.guilds:
        channel = guild.get_channel(channel_id)

        if isinstance(channel, discord.VoiceChannel):
            return channel

    return None


def _is_connected_to_permanent_channel(
    channel: discord.VoiceChannel,
) -> bool:
    """Return True only when the bot has a healthy voice connection."""

    voice_client = channel.guild.voice_client

    if voice_client is None:
        return False

    if not voice_client.is_connected():
        return False

    if voice_client.channel is None:
        return False

    return voice_client.channel.id == channel.id


async def connect_to_permanent_voice(
    bot: discord.Client,
) -> None:
    """Connect the bot to the permanent voice channel on startup."""

    global _PERMANENT_CHANNEL_ID

    channel_id = _parse_channel_id()

    if channel_id is None:
        logger.info(
            "No permanent voice channel configured "
            "(PERMANENT_VOICE_CHANNEL_ID not set)"
        )
        return

    _PERMANENT_CHANNEL_ID = channel_id

    channel = _find_permanent_channel(bot)

    if channel is None:
        logger.error(
            "Permanent voice channel %s was not found "
            "in any guild.",
            channel_id,
        )
        return

    # Already connected correctly.
    if _is_connected_to_permanent_channel(channel):
        logger.info(
            "Already connected to permanent voice channel: %s",
            channel.name,
        )
        return

    logger.info(
        "Connecting to permanent voice channel: %s (ID: %s)",
        channel.name,
        channel.id,
    )

    try:
        await channel.connect()

        logger.info(
            "Connected to permanent voice channel: %s",
            channel.name,
        )

    except discord.ClientException as exc:
        # This can happen when discord.py is already attempting
        # to establish/reconnect a voice connection.
        logger.warning(
            "Voice connection is already being handled by "
            "discord.py for %s: %s",
            channel.name,
            exc,
        )

    except discord.Forbidden:
        logger.error(
            "Permission denied connecting to permanent "
            "voice channel: %s",
            channel.name,
        )

    except discord.HTTPException as exc:
        logger.error(
            "HTTP error connecting to permanent voice channel "
            "%s: %s",
            channel.name,
            exc,
        )

    except Exception:
        logger.exception(
            "Unexpected error connecting to permanent "
            "voice channel: %s",
            channel.name,
        )


async def ensure_permanent_connection(
    bot: discord.Client,
) -> None:
    """Ensure the bot is connected to the permanent voice channel.

    The function waits before attempting a custom reconnect so that
    discord.py's own voice reconnection has priority.
    """

    channel = _find_permanent_channel(bot)

    if channel is None:
        logger.warning(
            "Permanent voice channel could not be found."
        )
        return

    # -------------------------------------------------------------- #
    # Give discord.py time to recover first.
    # -------------------------------------------------------------- #

    logger.info(
        "Waiting %.1f seconds before checking permanent "
        "voice connection.",
        _RECONNECT_DELAY,
    )

    await asyncio.sleep(_RECONNECT_DELAY)

    # discord.py may already have recovered.
    if _is_connected_to_permanent_channel(channel):
        logger.info(
            "discord.py successfully restored permanent "
            "voice connection."
        )
        return

    # -------------------------------------------------------------- #
    # Custom fallback reconnection.
    # -------------------------------------------------------------- #

    backoff = _INITIAL_BACKOFF

    for attempt in range(1, _MAX_RETRIES + 1):

        # Check again before every attempt.
        if _is_connected_to_permanent_channel(channel):
            logger.info(
                "Permanent voice connection restored."
            )
            return

        try:
            logger.info(
                "Permanent VC fallback reconnect "
                "attempt %d/%d: %s",
                attempt,
                _MAX_RETRIES,
                channel.name,
            )

            # If a stale voice client exists, disconnect it first.
            voice_client = channel.guild.voice_client

            if voice_client is not None:

                if voice_client.is_connected():

                    if (
                        voice_client.channel is not None
                        and voice_client.channel.id == channel.id
                    ):
                        logger.info(
                            "Permanent VC is already connected."
                        )
                        return

                try:
                    await voice_client.disconnect(
                        force=True
                    )

                except Exception:
                    logger.debug(
                        "Ignoring error while cleaning "
                        "stale voice connection.",
                        exc_info=True,
                    )

                # Give Discord a moment to release the old session.
                await asyncio.sleep(1.5)

            # ------------------------------------------------------ #
            # Connect.
            # ------------------------------------------------------ #

            await channel.connect()

            # Verify the connection.
            await asyncio.sleep(1.0)

            if _is_connected_to_permanent_channel(channel):
                logger.info(
                    "Successfully reconnected to permanent "
                    "voice channel: %s",
                    channel.name,
                )
                return

            logger.warning(
                "Voice connect completed but the permanent "
                "voice connection could not be verified."
            )

        except discord.ClientException as exc:

            logger.warning(
                "Discord client rejected permanent VC "
                "reconnection attempt %d/%d: %s",
                attempt,
                _MAX_RETRIES,
                exc,
            )

        except discord.Forbidden:

            logger.error(
                "Permission denied reconnecting to "
                "permanent voice channel: %s",
                channel.name,
            )
            return

        except discord.HTTPException as exc:

            logger.warning(
                "HTTP error on permanent VC reconnect "
                "attempt %d/%d: %s",
                attempt,
                _MAX_RETRIES,
                exc,
            )

        except Exception:

            logger.exception(
                "Unexpected error on permanent VC "
                "reconnect attempt %d/%d.",
                attempt,
                _MAX_RETRIES,
            )

        # ---------------------------------------------------------- #
        # Backoff before the next attempt.
        # ---------------------------------------------------------- #

        if attempt < _MAX_RETRIES:

            logger.info(
                "Waiting %.1f seconds before next "
                "permanent VC reconnect attempt.",
                backoff,
            )

            await asyncio.sleep(backoff)

            backoff = min(
                backoff * 2,
                _MAX_BACKOFF,
            )

    logger.error(
        "Failed to reconnect to permanent voice channel "
        "after %d attempts.",
        _MAX_RETRIES,
    )


def _is_bot_disconnected_from_permanent(
    bot: discord.Client,
) -> bool:
    """Check whether the bot is actually disconnected."""

    channel = _find_permanent_channel(bot)

    if channel is None:
        return False

    return not _is_connected_to_permanent_channel(channel)


def schedule_reconnection(
    bot: discord.Client,
) -> None:
    """Schedule a delayed fallback reconnection.

    This deliberately does not reconnect immediately because
    discord.py has its own automatic voice reconnection logic.
    """

    global _reconnect_task

    # -------------------------------------------------------------- #
    # Don't create duplicate reconnect tasks.
    # -------------------------------------------------------------- #

    if (
        _reconnect_task is not None
        and not _reconnect_task.done()
    ):
        return

    # -------------------------------------------------------------- #
    # Only schedule when actually disconnected.
    # -------------------------------------------------------------- #

    if not _is_bot_disconnected_from_permanent(bot):
        return

    logger.info(
        "Permanent voice connection lost. "
        "Scheduling delayed fallback reconnect."
    )

    _reconnect_task = asyncio.create_task(
        ensure_permanent_connection(bot),
        name="permanent-vc-reconnect",
    )

    def _cleanup_task(
        task: asyncio.Task[None],
    ) -> None:

        global _reconnect_task

        if task is _reconnect_task:
            _reconnect_task = None

        if task.cancelled():
            return

        try:
            task.exception()

        except Exception:
            logger.exception(
                "Permanent VC reconnect task failed."
            )

    _reconnect_task.add_done_callback(
        _cleanup_task
    )


def on_bot_voice_state_update(
    bot: discord.Client,
    member: discord.Member,
    before: discord.VoiceState,
    after: discord.VoiceState,
) -> None:
    """Handle the bot's own voice state changes.

    Only the bot's own voice state triggers the fallback reconnect.
    """

    if bot.user is None:
        return

    # Ignore all other members.
    if member.id != bot.user.id:
        return

    # If the bot has just joined/moved into the permanent channel,
    # no reconnect is necessary.
    channel = _find_permanent_channel(bot)

    if (
        channel is not None
        and after.channel is not None
        and after.channel.id == channel.id
    ):
        return

    # Schedule a delayed fallback check.
    schedule_reconnection(bot)