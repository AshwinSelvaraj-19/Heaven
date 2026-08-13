"""Dynamic status manager for the permanent Heaven voice channel."""

from __future__ import annotations

import logging

import aiohttp
import discord

from bot.config import config
from bot.utils.permanent_voice import get_permanent_channel_id

logger = logging.getLogger("bot.voice_status")

DISCORD_API_BASE = "https://discord.com/api/v10"


def get_voice_user_count(guild: discord.Guild) -> int:
    """Return the number of human users currently connected to voice/stage channels."""
    members: set[int] = set()

    for channel in guild.voice_channels:
        for member in channel.members:
            if not member.bot:
                members.add(member.id)

    for channel in guild.stage_channels:
        for member in channel.members:
            if not member.bot:
                members.add(member.id)

    return len(members)


async def update_voice_status(guild: discord.Guild) -> None:
    """Update the permanent Heaven VC status with current server statistics."""
    channel_id = get_permanent_channel_id()

    if channel_id is None:
        return

    channel = guild.get_channel(channel_id)

    if not isinstance(channel, discord.VoiceChannel):
        logger.warning(
            "Permanent voice channel %s was not found or is not a voice channel.",
            channel_id,
        )
        return

    member_count = guild.member_count or len(guild.members)
    voice_count = get_voice_user_count(guild)

    status = (
    f"<a:members:1484600884926349402> Members: {member_count} • "
    f"<a:voice:1502983156687437884> Voice Chat: {voice_count}"
    )

    url = f"{DISCORD_API_BASE}/channels/{channel_id}/voice-status"

    headers = {
        "Authorization": f"Bot {config.DISCORD_TOKEN}",
        "Content-Type": "application/json",
    }

    try:
        timeout = aiohttp.ClientTimeout(total=10)

        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.put(
                url,
                headers=headers,
                json={"status": status},
            ) as response:

                if response.status in (200, 204):
                    logger.debug(
                        "Updated permanent VC status: %s",
                        status,
                    )
                    return

                body = await response.text()

                logger.warning(
                    "Failed to update permanent VC status. "
                    "HTTP %s: %s",
                    response.status,
                    body[:500],
                )

    except aiohttp.ClientError as exc:
        logger.warning(
            "Network error while updating permanent VC status: %s",
            exc,
        )

    except Exception:
        logger.exception(
            "Unexpected error while updating permanent VC status."
        )