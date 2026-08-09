"""Manages creation, validation, and deletion of temporary voice channels."""

from __future__ import annotations

import asyncio
import logging

import discord

from bot.constants import (
    DEFAULT_AUTODELETE_SECONDS,
    DEFAULT_BITRATE,
    DEFAULT_LIMIT,
    REQUIRED_PERMISSIONS,
    TEMP_CHANNEL_PREFIX,
)
from bot.settings_store import all_settings, get_settings
from bot.utils.logging_utils import log_action
from bot.utils.ownership import (
    clear_delete_task,
    get_channel_for_user,
    register_channel,
    set_delete_task,
    unregister_channel,
)
from bot.utils.permanent_voice import get_permanent_channel_id

logger = logging.getLogger("bot.vc")


# ------------------------------------------------------------------ #
# Validation
# ------------------------------------------------------------------ #


def _check_permissions(guild: discord.Guild) -> list[str]:
    """Return a list of missing required permission names for the bot."""
    me = guild.me
    if me is None:
        return list(REQUIRED_PERMISSIONS)

    missing: list[str] = []
    for perm in REQUIRED_PERMISSIONS:
        if not getattr(me.guild_permissions, perm, False):
            missing.append(perm)
    return missing


def validate_config(guild: discord.Guild) -> tuple[bool, str]:
    """Validate that the guild is ready for temp channel creation.

    Returns ``(ok, message)``. When ``ok`` is False, ``message`` describes the
    exact problem.
    """
    settings = get_settings(guild.id)

    lobby_id = settings.get("lobby_id")
    if not lobby_id:
        msg = "Lobby channel is not configured."
        log_action("CONFIG_ERROR", guild=guild, detail=msg)
        return False, msg

    lobby = guild.get_channel(lobby_id)
    if lobby is None:
        msg = f"Lobby channel {lobby_id} not found."
        log_action("CONFIG_ERROR", guild=guild, detail=msg)
        return False, msg

    category_id = settings.get("category_id")
    if not category_id:
        msg = "Category is not configured."
        log_action("CONFIG_ERROR", guild=guild, detail=msg)
        return False, msg

    category = guild.get_channel(category_id)
    if not isinstance(category, discord.CategoryChannel):
        msg = f"Category {category_id} not found or is not a category."
        log_action("CONFIG_ERROR", guild=guild, detail=msg)
        return False, msg

    missing = _check_permissions(guild)
    if missing:
        human = ", ".join(missing).replace("_", " ").title()
        msg = f"Bot is missing permissions: {human}."
        log_action("PERMISSION_ERROR", guild=guild, detail=msg)
        return False, msg

    return True, ""


# ------------------------------------------------------------------ #
# Creation
# ------------------------------------------------------------------ #


def _channel_name(member: discord.Member) -> str:
    """Return the display-name-based temp channel name."""
    return f"{TEMP_CHANNEL_PREFIX}{member.display_name}"


async def create_temp_channel(
    guild: discord.Guild, member: discord.Member
) -> discord.VoiceChannel | None:
    """Create a temp voice channel under the configured category and move the member.

    Returns the created channel, or None if validation fails or creation errors.
    """
    ok, msg = validate_config(guild)
    if not ok:
        return None

    settings = get_settings(guild.id)
    category = guild.get_channel(settings["category_id"])
    assert isinstance(category, discord.CategoryChannel)  # validated above

    user_limit = settings.get("user_limit") or DEFAULT_LIMIT
    bitrate = settings.get("bitrate") or DEFAULT_BITRATE

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
            name=_channel_name(member),
            category=category,
            user_limit=user_limit,
            bitrate=bitrate,
            overwrites=overwrites,
            reason=f"Temp channel created for {member} via lobby join",
        )
    except discord.Forbidden:
        log_action("PERMISSION_ERROR", guild=guild, user=member, detail="create_voice_channel forbidden")
        return None
    except discord.HTTPException as exc:
        log_action("CONFIG_ERROR", guild=guild, user=member, detail=f"create failed: {exc}")
        return None

    register_channel(channel.id, member.id, guild.id)
    log_action("VC_CREATED", guild=guild, user=member, channel=channel)

    try:
        await member.move_to(channel, reason="Moved to temp channel")
        log_action("USER_MOVED", guild=guild, user=member, channel=channel)
    except discord.HTTPException as exc:
        log_action("CONFIG_ERROR", guild=guild, user=member, channel=channel, detail=f"move failed: {exc}")

    return channel


async def reuse_existing_channel(
    guild: discord.Guild, member: discord.Member, channel_id: int
) -> discord.VoiceChannel | None:
    """Move a member back into their existing temp channel and cancel its deletion."""
    channel = guild.get_channel(channel_id)
    if not isinstance(channel, discord.VoiceChannel):
        # Channel was deleted externally — caller should create a new one.
        unregister_channel(channel_id)
        return None

    cancel_deletion(channel_id)

    try:
        await member.move_to(channel, reason="Rejoined lobby — moved to existing temp channel")
        log_action("USER_MOVED", guild=guild, user=member, channel=channel, detail="reused existing")
    except discord.HTTPException as exc:
        log_action("CONFIG_ERROR", guild=guild, user=member, channel=channel, detail=f"move failed: {exc}")

    return channel


# ------------------------------------------------------------------ #
# Deletion
# ------------------------------------------------------------------ #


def cancel_deletion(channel_id: int) -> None:
    """Cancel a pending deletion task for a channel (e.g. someone rejoined)."""
    task = clear_delete_task(channel_id)
    if task and not task.done():
        task.cancel()
        log_action("DELETE_CANCELLED", channel=None, detail=f"channel_id={channel_id}")


async def schedule_deletion(channel: discord.VoiceChannel, delay: int) -> None:
    """Delete a voice channel after ``delay`` seconds if it is still empty."""
    if delay <= 0:
        # Immediate deletion path.
        await _delete_channel(channel)
        return

    await asyncio.sleep(delay)

    # Re-check emptiness after the wait.
    if channel.members:
        return

    await _delete_channel(channel)


async def _delete_channel(channel: discord.VoiceChannel) -> None:
    """Delete a temp channel and clean up ownership tracking."""
    try:
        await channel.delete(reason="Temp channel empty — autodelete")
        log_action("VC_DELETED", guild=channel.guild, channel=channel)
    except discord.NotFound:
        pass  # Already deleted.
    except discord.Forbidden:
        log_action("PERMISSION_ERROR", guild=channel.guild, channel=channel, detail="delete forbidden")
    except discord.HTTPException as exc:
        log_action("CONFIG_ERROR", guild=channel.guild, channel=channel, detail=f"delete failed: {exc}")
    finally:
        unregister_channel(channel.id)


def maybe_schedule_deletion(channel: discord.VoiceChannel) -> None:
    """If the channel is an empty temp channel, schedule its deletion."""
    if channel.members:
        return

    # Only manage channels we own.
    from bot.utils.ownership import get_ownership

    if get_ownership(channel.id) is None:
        return

    settings = get_settings(channel.guild.id)
    autodelete = settings.get("autodelete_seconds") or DEFAULT_AUTODELETE_SECONDS

    cancel_deletion(channel.id)
    task = asyncio.create_task(schedule_deletion(channel, autodelete))
    set_delete_task(channel.id, task)


# ------------------------------------------------------------------ #
# Orphan cleanup (called on startup)
# ------------------------------------------------------------------ #


async def cleanup_orphans(bot: discord.Client) -> None:
    """Delete empty temp channels left over from a previous bot session.

    Scans every configured category and removes empty voice channels that
    were created by this module. Normal voice channels are never touched.
    """
    for guild in bot.guilds:
        settings = all_settings().get(guild.id)
        if not settings:
            continue

        category_id = settings.get("category_id")
        if not category_id:
            continue

        category = guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            continue

        for channel in category.voice_channels:
            # Skip non-empty channels
            if channel.members:
                continue
            # Skip the permanent voice channel
            permanent_id = get_permanent_channel_id()
            if permanent_id is not None and channel.id == permanent_id:
                continue
            # Only delete channels whose name matches our naming pattern
            if not channel.name.startswith(TEMP_CHANNEL_PREFIX):
                continue

            try:
                await channel.delete(reason="Orphan temp channel cleanup on startup")
                log_action("VC_DELETED", guild=guild, channel=channel, detail="orphan cleanup")
            except discord.NotFound:
                pass
            except discord.HTTPException as exc:
                log_action("CONFIG_ERROR", guild=guild, channel=channel, detail=f"orphan delete failed: {exc}")
