"""Shared utilities for resolving and validating Discord voice channels."""

from __future__ import annotations

import discord


def resolve_voice_channel(
    guild: discord.Guild, query: str
) -> discord.VoiceChannel | None:
    """Resolve a voice channel from a name, ID, or mention string.

    Resolution order:
    1. Channel mention (<#123456>)
    2. Raw numeric ID
    3. Exact name match (case-insensitive)

    Parameters
    ----------
    guild:
        The guild to search in.
    query:
        The channel mention, ID, or name.

    Returns
    -------
    discord.VoiceChannel | None
        The resolved voice channel, or None if not found.
    """
    if not query:
        return None

    # Try ID mention: <#123456>
    if query.startswith("<#") and query.endswith(">"):
        try:
            cid = int(query[2:-1])
        except ValueError:
            cid = None
        if cid is not None:
            ch = guild.get_channel(cid)
            if isinstance(ch, discord.VoiceChannel):
                return ch

    # Try raw ID
    try:
        cid = int(query)
    except ValueError:
        cid = None
    if cid is not None:
        ch = guild.get_channel(cid)
        if isinstance(ch, discord.VoiceChannel):
            return ch

    # Try name match (case-insensitive)
    lowered = query.lower()
    for ch in guild.voice_channels:
        if ch.name.lower() == lowered:
            return ch

    return None


def validate_voice_channel(channel: discord.abc.GuildChannel | None) -> tuple[bool, str]:
    """Validate that a channel is a suitable voice channel target.

    Parameters
    ----------
    channel:
        The channel to validate.

    Returns
    -------
    tuple[bool, str]
        (is_valid, error_message)
    """
    if channel is None:
        return False, "Channel not found."

    if not isinstance(channel, discord.VoiceChannel):
        return False, "Target must be a voice channel."

    return True, ""


def resolve_category(
    guild: discord.Guild, query: str
) -> discord.CategoryChannel | None:
    """Resolve a category channel from a name, ID, or mention string.

    Resolution order:
    1. Channel mention (<#123456>)
    2. Raw numeric ID
    3. Exact name match (case-insensitive)

    Parameters
    ----------
    guild:
        The guild to search in.
    query:
        The category mention, ID, or name.

    Returns
    -------
    discord.CategoryChannel | None
        The resolved category channel, or None if not found.
    """
    if not query:
        return None

    # Try ID mention: <#123456>
    if query.startswith("<#") and query.endswith(">"):
        try:
            cid = int(query[2:-1])
        except ValueError:
            cid = None
        if cid is not None:
            ch = guild.get_channel(cid)
            if isinstance(ch, discord.CategoryChannel):
                return ch

    # Try raw ID
    try:
        cid = int(query)
    except ValueError:
        cid = None
    if cid is not None:
        ch = guild.get_channel(cid)
        if isinstance(ch, discord.CategoryChannel):
            return ch

    # Try name match (case-insensitive)
    lowered = query.lower()
    for ch in guild.categories:
        if ch.name.lower() == lowered:
            return ch

    return None
