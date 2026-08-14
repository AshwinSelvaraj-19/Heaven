"""Dynamic status manager for the public Heaven voice channel."""

from __future__ import annotations

import logging

import aiohttp
import discord

from bot.config import config

logger = logging.getLogger("bot.voice_status")

DISCORD_API_BASE = "https://discord.com/api/v10"

# ------------------------------------------------------------------ #
# Public VC where the dynamic channel status is displayed.
# ------------------------------------------------------------------ #
STATUS_CHANNEL_ID = 1522597888528617625


def get_voice_user_count(guild: discord.Guild) -> int:
    """Return the number of members currently connected to voice/stage channels.

    Bots are included in the count.
    """

    members: set[int] = set()

    for channel in guild.voice_channels:
        for member in channel.members:
            members.add(member.id)

    for channel in guild.stage_channels:
        for member in channel.members:
            members.add(member.id)

    return len(members)


async def update_voice_status(guild: discord.Guild) -> None:
    """Update the public VC with current server statistics."""

    # -------------------------------------------------------------- #
    # Get the dedicated public status VC.
    # -------------------------------------------------------------- #
    channel = guild.get_channel(STATUS_CHANNEL_ID)

    if channel is None:
        logger.warning(
            "Status VC %s was not found in guild %s.",
            STATUS_CHANNEL_ID,
            guild.id,
        )
        return

    if not isinstance(channel, discord.VoiceChannel):
        logger.warning(
            "Status channel %s is not a voice channel.",
            STATUS_CHANNEL_ID,
        )
        return

    # -------------------------------------------------------------- #
    # Server member count.
    # -------------------------------------------------------------- #
    member_count = (
        guild.member_count
        or len(guild.members)
    )

    # -------------------------------------------------------------- #
    # Current voice count.
    # Bots are intentionally included.
    # -------------------------------------------------------------- #
    voice_count = get_voice_user_count(guild)

    # -------------------------------------------------------------- #
    # Dynamic status text.
    # -------------------------------------------------------------- #
    status = (
        f"<a:members:1484600884926349402> "
        f"Members: {member_count} • "
        f"<a:voice:1502983156687437884> "
        f"Voice Chat: {voice_count}"
    )

    # -------------------------------------------------------------- #
    # Discord Voice Status API endpoint.
    # -------------------------------------------------------------- #
    url = (
        f"{DISCORD_API_BASE}"
        f"/channels/{STATUS_CHANNEL_ID}/voice-status"
    )

    headers = {
        "Authorization": f"Bot {config.DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(
            timeout=timeout
        ) as session:

            async with session.put(
                url,
                headers=headers,
                json={"status": status},
            ) as response:

                body = await response.text()

                # -------------------------------------------------- #
                # Success
                # -------------------------------------------------- #
                if response.status in (200, 204):
                    logger.info(
                        "Public VC status updated successfully: %s",
                        status,
                    )
                    return

                # -------------------------------------------------- #
                # Discord API failure
                # -------------------------------------------------- #
                logger.error(
                    "Public VC status update failed. "
                    "HTTP %s: %s",
                    response.status,
                    body[:500],
                )

    except aiohttp.ClientError as exc:
        logger.error(
            "Network error while updating public VC status: %s",
            exc,
        )

    except Exception:
        logger.exception(
            "Unexpected error while updating public VC status."
        )