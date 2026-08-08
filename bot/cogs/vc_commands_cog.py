"""``?vc`` prefix command group — voice channel controls for all voice channels.

Commands are invoked by mentioning the bot followed by ``?``::

    @Bot ?vc lock
    @Bot ?vc unlock
    @Bot ?vc hide
    @Bot ?vc unhide
    @Bot ?vc muteall
    @Bot ?vc movall <target>
    @Bot ?vc rename <name>

Works on both temporary Heaven VCs and normal server VCs with appropriate
permission checks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bot.constants import COMMAND_COOLDOWN, TEMP_CHANNEL_PREFIX
from bot.utils.channel_utils import resolve_voice_channel, validate_voice_channel
from bot.utils.logging_utils import log_action
from bot.utils.ownership import get_ownership
from bot.utils.permissions import PermissionLevel, can_control_voice_channel

if TYPE_CHECKING:
    from bot.utils.ownership import ChannelOwnership

logger = logging.getLogger("bot.vc")

MAX_NAME_LENGTH: int = 100

# Track Heaven-managed permission overwrites for unlock/unhide
# channel_id -> {"connect": original_value, "view_channel": original_value}
_heaven_overwrites: dict[int, dict[str, bool | None]] = {}

# Command cooldowns: user_id -> timestamp
_command_cooldowns: dict[int, float] = {}


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _existing_overwrite(
    channel: discord.VoiceChannel, target: discord.Role | discord.Member
) -> discord.PermissionOverwrite:
    """Return the current overwrite for ``target`` (or a fresh empty one)."""
    ow = channel.overwrites_for(target)
    if ow is None:
        return discord.PermissionOverwrite()
    return ow


async def _send(ctx: commands.Context, content: str) -> None:
    """Send a normal message response (prefix commands cannot be ephemeral)."""
    await ctx.send(content)


def _check_command_cooldown(user_id: int) -> bool:
    """Check if user is on command cooldown. Returns True if on cooldown."""
    import time
    last = _command_cooldowns.get(user_id)
    if last is None:
        return False
    return (time.monotonic() - last) < COMMAND_COOLDOWN


def _mark_command_cooldown(user_id: int) -> None:
    """Mark user as having used a command."""
    import time
    _command_cooldowns[user_id] = time.monotonic()


def _save_heaven_overwrite(channel_id: int, perm: str, value: bool | None) -> None:
    """Save the original value of a permission before Heaven modifies it."""
    if channel_id not in _heaven_overwrites:
        _heaven_overwrites[channel_id] = {}
    _heaven_overwrites[channel_id][perm] = value


def _get_heaven_overwrite(channel_id: int, perm: str) -> bool | None:
    """Get the original value of a permission before Heaven modified it."""
    return _heaven_overwrites.get(channel_id, {}).get(perm)


def _clear_heaven_overwrites(channel_id: int) -> None:
    """Clear Heaven's overwrite tracking for a channel."""
    _heaven_overwrites.pop(channel_id, None)


# ------------------------------------------------------------------ #
# Validation
# ------------------------------------------------------------------ #


async def _validate_voice_channel(
    ctx: commands.Context,
) -> discord.VoiceChannel | None:
    """Validate that the caller is connected to a voice channel.

    Returns the channel on success, otherwise sends an error message and returns None.
    """
    member = ctx.author
    if not isinstance(member, discord.Member):
        await _send(ctx, "This command can only be used in a server.")
        return None

    state = member.voice
    if state is None or state.channel is None:
        await _send(ctx, "You are not connected to a voice channel.")
        return None

    channel = state.channel
    if not isinstance(channel, discord.VoiceChannel):
        await _send(ctx, "You must be in a voice channel to use this command.")
        return None

    return channel


async def _check_bot_permission(
    ctx: commands.Context,
    channel: discord.VoiceChannel,
    permission: str,
) -> bool:
    """Check if the bot has a specific permission in the channel.

    Returns True if the bot has the permission, False otherwise.
    Sends an error message if permission is missing.
    """
    me = ctx.guild.me
    if me is None:
        await _send(ctx, "I am not in this server.")
        return False

    perms = channel.permissions_for(me)
    if not getattr(perms, permission, False):
        perm_name = permission.replace("_", " ").title()
        await _send(ctx, f"I don't have **{perm_name}** permission in this channel.")
        return False

    return True


async def _handle_error(
    ctx: commands.Context,
    channel: discord.VoiceChannel,
    action: str,
    exc: Exception,
) -> None:
    """Send a friendly error message and log the underlying exception."""
    if isinstance(exc, discord.Forbidden):
        msg = "I don't have permission to manage this channel."
        log_action(
            "PERMISSION_ERROR",
            guild=ctx.guild,
            user=ctx.author,
            channel=channel,
            detail=f"{action} failed — forbidden",
        )
    elif isinstance(exc, discord.HTTPException):
        msg = "Something went wrong while updating the channel. Please try again."
        log_action(
            "CONFIG_ERROR",
            guild=ctx.guild,
            user=ctx.author,
            channel=channel,
            detail=f"{action} failed: {exc}",
        )
    else:
        msg = "An unexpected error occurred. Please try again."
        log_action(
            "CONFIG_ERROR",
            guild=ctx.guild,
            user=ctx.author,
            channel=channel,
            detail=f"{action} unexpected error: {exc}",
        )

    await _send(ctx, msg)


# ------------------------------------------------------------------ #
# Command group
# ------------------------------------------------------------------ #


class VcCommandsCog(commands.Cog):
    """``?vc`` prefix command group — lock / unlock / hide / muteall / movall / rename."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(name="vc", invoke_without_command=True)
    async def vc(self, ctx: commands.Context) -> None:
        """Manage voice channels."""
        await ctx.send(
            "Available commands: `?vc lock`, `?vc unlock`, `?vc hide`, "
            "`?vc unhide`, `?vc muteall`, `?vc movall <target>`, `?vc rename <name>`."
        )

    # ------------------------------------------------------------------ #
    # ?vc lock
    # ------------------------------------------------------------------ #

    @vc.command(name="lock", description="Lock the voice channel so new members cannot join.")
    async def lock(self, ctx: commands.Context) -> None:
        channel = await _validate_voice_channel(ctx)
        if channel is None:
            return

        # Check authorization
        has_perm, perm_level = can_control_voice_channel(ctx.author, channel, "manage_channels")
        if not has_perm:
            await _send(ctx, "You don't have permission to control this channel.")
            return

        # Check bot permission
        if not await _check_bot_permission(ctx, channel, "manage_channels"):
            return

        try:
            ow = _existing_overwrite(channel, ctx.guild.default_role)
            # Save original value before modifying
            _save_heaven_overwrite(channel.id, "connect", ow.connect)
            ow.connect = False

            # Ensure bot retains required permissions
            me = ctx.guild.me
            if me:
                bot_overwrite = _existing_overwrite(channel, me)
                bot_overwrite.update(
                    view_channel=True,
                    connect=True,
                    manage_channels=True,
                    move_members=True,
                )
                await channel.set_permissions(
                    me,
                    overwrite=bot_overwrite,
                    reason="Ensure bot permissions for locked channel",
                )

            await channel.set_permissions(
                ctx.guild.default_role,
                overwrite=ow,
                reason="Voice channel locked",
            )
        except Exception as exc:
            await _handle_error(ctx, channel, "lock", exc)
            return

        log_action("VC_LOCKED", guild=ctx.guild, user=ctx.author, channel=channel)
        await _send(
            ctx,
            "Channel is now **locked**. New members cannot join, "
            "but everyone already inside stays.",
        )

    # ------------------------------------------------------------------ #
    # ?vc unlock
    # ------------------------------------------------------------------ #

    @vc.command(name="unlock", description="Unlock the voice channel so members can join again.")
    async def unlock(self, ctx: commands.Context) -> None:
        channel = await _validate_voice_channel(ctx)
        if channel is None:
            return

        # Check authorization
        has_perm, perm_level = can_control_voice_channel(ctx.author, channel, "manage_channels")
        if not has_perm:
            await _send(ctx, "You don't have permission to control this channel.")
            return

        # Check bot permission
        if not await _check_bot_permission(ctx, channel, "manage_channels"):
            return

        try:
            ow = _existing_overwrite(channel, ctx.guild.default_role)
            # Restore original value if Heaven tracked it, otherwise set to True
            original = _get_heaven_overwrite(channel.id, "connect")
            ow.connect = original if original is not None else True
            await channel.set_permissions(
                ctx.guild.default_role,
                overwrite=ow,
                reason="Voice channel unlocked",
            )
            # Clear the tracked overwrite since we restored it
            _save_heaven_overwrite(channel.id, "connect", None)
        except Exception as exc:
            await _handle_error(ctx, channel, "unlock", exc)
            return

        log_action("VC_UNLOCKED", guild=ctx.guild, user=ctx.author, channel=channel)
        await _send(ctx, "Channel is now **unlocked**. Members can join again.")

    # ------------------------------------------------------------------ #
    # ?vc hide
    # ------------------------------------------------------------------ #

    @vc.command(name="hide", description="Hide the voice channel so non-members cannot see it.")
    async def hide(self, ctx: commands.Context) -> None:
        channel = await _validate_voice_channel(ctx)
        if channel is None:
            return

        # Check authorization
        has_perm, perm_level = can_control_voice_channel(ctx.author, channel, "manage_channels")
        if not has_perm:
            await _send(ctx, "You don't have permission to control this channel.")
            return

        # Check bot permission
        if not await _check_bot_permission(ctx, channel, "manage_channels"):
            return

        guild = ctx.guild
        member = ctx.author

        try:
            ow = _existing_overwrite(channel, guild.default_role)
            # Save original value before modifying
            _save_heaven_overwrite(channel.id, "view_channel", ow.view_channel)
            ow.view_channel = False

            # Ensure bot retains required permissions
            me = guild.me
            if me:
                bot_overwrite = _existing_overwrite(channel, me)
                bot_overwrite.update(
                    view_channel=True,
                    connect=True,
                    manage_channels=True,
                    move_members=True,
                )
                await channel.set_permissions(
                    me,
                    overwrite=bot_overwrite,
                    reason="Ensure bot permissions for hidden channel",
                )

            await channel.set_permissions(
                guild.default_role,
                overwrite=ow,
                reason="Voice channel hidden",
            )

            # Ensure executor has access
            owner_ow = channel.overwrites_for(member)
            if owner_ow is None:
                owner_ow = discord.PermissionOverwrite()
            owner_ow.view_channel = True
            owner_ow.connect = True
            await channel.set_permissions(
                member,
                overwrite=owner_ow,
                reason="Guarantee executor access to hidden channel",
            )
        except Exception as exc:
            await _handle_error(ctx, channel, "hide", exc)
            return

        log_action("VC_HIDDEN", guild=guild, user=member, channel=channel)
        await _send(ctx, "Voice channel is now hidden.")

    # ------------------------------------------------------------------ #
    # ?vc unhide
    # ------------------------------------------------------------------ #

    @vc.command(name="unhide", description="Unhide the voice channel so non-members can see it again.")
    async def unhide(self, ctx: commands.Context) -> None:
        channel = await _validate_voice_channel(ctx)
        if channel is None:
            return

        # Check authorization
        has_perm, perm_level = can_control_voice_channel(ctx.author, channel, "manage_channels")
        if not has_perm:
            await _send(ctx, "You don't have permission to control this channel.")
            return

        # Check bot permission
        if not await _check_bot_permission(ctx, channel, "manage_channels"):
            return

        try:
            ow = _existing_overwrite(channel, ctx.guild.default_role)
            # Restore original value if Heaven tracked it, otherwise set to True
            original = _get_heaven_overwrite(channel.id, "view_channel")
            ow.view_channel = original if original is not None else True
            await channel.set_permissions(
                ctx.guild.default_role,
                overwrite=ow,
                reason="Voice channel unhidden",
            )
            # Clear the tracked overwrite since we restored it
            _save_heaven_overwrite(channel.id, "view_channel", None)
        except Exception as exc:
            await _handle_error(ctx, channel, "unhide", exc)
            return

        log_action("VC_UNHIDDEN", guild=ctx.guild, user=ctx.author, channel=channel)
        await _send(ctx, "Voice channel is now visible again.")

    # ------------------------------------------------------------------ #
    # ?vc muteall
    # ------------------------------------------------------------------ #

    @vc.command(name="muteall", description="Server-mute everyone in the voice channel.")
    async def muteall(self, ctx: commands.Context) -> None:
        channel = await _validate_voice_channel(ctx)
        if channel is None:
            return

        # Check authorization (requires mute_members permission)
        has_perm, perm_level = can_control_voice_channel(ctx.author, channel, "mute_members")
        if not has_perm:
            await _send(ctx, "You don't have permission to mute members in this channel.")
            return

        # Check cooldown
        if _check_command_cooldown(ctx.author.id):
            await _send(ctx, f"Please wait {COMMAND_COOLDOWN} seconds before using this command again.")
            return

        # Check bot permission
        if not await _check_bot_permission(ctx, channel, "mute_members"):
            return

        me = ctx.guild.me
        me_id = me.id if me is not None else 0

        muted = 0
        skipped = 0

        try:
            for member in channel.members:
                if member.id == me_id:
                    continue
                try:
                    await member.edit(mute=True, reason="Voice channel muteall")
                    muted += 1
                except discord.Forbidden:
                    skipped += 1
                except discord.HTTPException:
                    skipped += 1
        except Exception as exc:
            await _handle_error(ctx, channel, "muteall", exc)
            return

        _mark_command_cooldown(ctx.author.id)
        log_action(
            "VC_MUTEALL",
            guild=ctx.guild,
            user=ctx.author,
            channel=channel,
            detail=f"muted={muted} skipped={skipped}",
        )

        msg = f"Muted {muted} member{'s' if muted != 1 else ''}."
        if skipped:
            msg += f"\nSkipped {skipped} member{'s' if skipped != 1 else ''} due to permissions."
        await _send(ctx, msg)

    # ------------------------------------------------------------------ #
    # ?vc movall <target>
    # ------------------------------------------------------------------ #

    @vc.command(name="movall", description="Move all members from the voice channel to another voice channel.")
    async def movall(self, ctx: commands.Context, *, target: str) -> None:
        source = await _validate_voice_channel(ctx)
        if source is None:
            return

        # Check authorization (requires move_members permission)
        has_perm, perm_level = can_control_voice_channel(ctx.author, source, "move_members")
        if not has_perm:
            await _send(ctx, "You don't have permission to move members in this channel.")
            return

        # Check cooldown
        if _check_command_cooldown(ctx.author.id):
            await _send(ctx, f"Please wait {COMMAND_COOLDOWN} seconds before using this command again.")
            return

        # Resolve and validate target channel
        target_channel = resolve_voice_channel(ctx.guild, target)
        if target_channel is None:
            await _send(ctx, "I couldn't find that voice channel.")
            return

        is_valid, error_msg = validate_voice_channel(target_channel)
        if not is_valid:
            await _send(ctx, error_msg)
            return

        if target_channel.id == source.id:
            await _send(ctx, "The target channel is the same as the current channel.")
            return

        # Check bot permissions
        me = ctx.guild.me
        if me is None:
            await _send(ctx, "I am not in this server.")
            return

        if not me.guild_permissions.move_members:
            await _send(ctx, "I don't have Move Members permission in this server.")
            return

        # Check bot can access target channel
        target_perms = target_channel.permissions_for(me)
        if not target_perms.view_channel or not target_perms.connect:
            await _send(ctx, "I don't have permission to access the target channel.")
            return

        # Check bot can access source channel
        source_perms = source.permissions_for(me)
        if not source_perms.view_channel:
            await _send(ctx, "I don't have permission to access the source channel.")
            return

        me_id = me.id
        moved = 0
        skipped = 0

        try:
            for member in source.members:
                if member.id == me_id:
                    continue
                try:
                    await member.move_to(target_channel, reason="Voice channel movall")
                    moved += 1
                except discord.Forbidden:
                    skipped += 1
                except discord.HTTPException:
                    skipped += 1
        except Exception as exc:
            await _handle_error(ctx, source, "movall", exc)
            return

        _mark_command_cooldown(ctx.author.id)
        log_action(
            "VC_MOVALL",
            guild=ctx.guild,
            user=ctx.author,
            channel=source,
            detail=f"target_id={target_channel.id} moved={moved} skipped={skipped}",
        )

        msg = f"Moved {moved} member{'s' if moved != 1 else ''} to {target_channel.name}."
        if skipped:
            msg += f"\nSkipped {skipped} member{'s' if skipped != 1 else ''}."
        await _send(ctx, msg)

    # ------------------------------------------------------------------ #
    # ?vc rename <name>
    # ------------------------------------------------------------------ #

    @vc.command(name="rename", description="Rename the voice channel.")
    async def rename(self, ctx: commands.Context, *, name: str) -> None:
        stripped = name.strip()
        if not stripped:
            await _send(ctx, "The new name cannot be empty.")
            return
        if len(stripped) > MAX_NAME_LENGTH:
            await _send(ctx, f"The name is too long. Maximum is {MAX_NAME_LENGTH} characters.")
            return

        channel = await _validate_voice_channel(ctx)
        if channel is None:
            return

        # Check authorization
        has_perm, perm_level = can_control_voice_channel(ctx.author, channel, "manage_channels")
        if not has_perm:
            await _send(ctx, "You don't have permission to control this channel.")
            return

        # Check cooldown
        if _check_command_cooldown(ctx.author.id):
            await _send(ctx, f"Please wait {COMMAND_COOLDOWN} seconds before using this command again.")
            return

        # Check bot permission
        if not await _check_bot_permission(ctx, channel, "manage_channels"):
            return

        old_name = channel.name
        # Only add prefix if it's a temp channel
        ownership = get_ownership(channel.id)
        if ownership is not None:
            new_name = f"{TEMP_CHANNEL_PREFIX}{stripped}"
        else:
            new_name = stripped

        try:
            await channel.edit(name=new_name, reason="Voice channel renamed")
        except Exception as exc:
            await _handle_error(ctx, channel, "rename", exc)
            return

        _mark_command_cooldown(ctx.author.id)
        log_action(
            "VC_RENAMED",
            guild=ctx.guild,
            user=ctx.author,
            channel=channel,
            detail=f"old_name={old_name!r} new_name={new_name!r}",
        )
        await _send(ctx, f"Channel renamed from **{old_name}** to **{new_name}**.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VcCommandsCog(bot))
