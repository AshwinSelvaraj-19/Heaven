"""``?vc`` prefix command group — owner & moderator controls for temporary voice channels.

Commands are invoked by mentioning the bot followed by ``?``::

    @Bot ?vc lock
    @Bot ?vc hide
    @Bot ?vc muteall
    @Bot ?vc movall <target>
    @Bot ?vc rename <name>

All VC logic, ownership tracking, validation, and logging are preserved from
the slash-command implementation — only the command interface changed.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord.ext import commands

from bot.constants import TEMP_CHANNEL_PREFIX
from bot.utils.logging_utils import log_action
from bot.utils.ownership import get_ownership

if TYPE_CHECKING:
    from bot.utils.ownership import ChannelOwnership

logger = logging.getLogger("bot.vc")

MAX_NAME_LENGTH: int = 100


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #


def _has_mod_permission(member: discord.Member) -> bool:
    """Return True if the member has moderation-level voice permissions.

    Checks the minimum appropriate permissions (not Administrator alone):
    mute/deafen/move members, or manage channels.
    """
    perms = member.guild_permissions
    return perms.administrator or perms.mute_members or perms.move_members or perms.manage_channels


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


async def _resolve_voice_channel(
    guild: discord.Guild, query: str
) -> discord.VoiceChannel | None:
    """Resolve a voice channel from a name, ID, or mention string."""
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


# ------------------------------------------------------------------ #
# Validation
# ------------------------------------------------------------------ #


async def _validate_owner(
    ctx: commands.Context,
) -> tuple[discord.VoiceChannel, ChannelOwnership] | None:
    """Validate that the caller owns the temp VC they are connected to.

    Returns ``(channel, ownership)`` on success, otherwise sends an error
    message and returns ``None``.
    """
    member = ctx.author
    if not isinstance(member, discord.Member):
        await _send(ctx, "This command can only be used in a server.")
        return None

    # 1. Connected to a voice channel?
    state = member.voice
    if state is None or state.channel is None:
        await _send(ctx, "You are not connected to a voice channel.")
        return None

    channel = state.channel

    # 2. Channel still exists and is a voice channel.
    if not isinstance(channel, discord.VoiceChannel):
        await _send(ctx, "This is not a temporary voice channel.")
        return None

    # 3. Is it one of our temp channels?
    ownership = get_ownership(channel.id)
    if ownership is None:
        await _send(ctx, "This is not a temporary voice channel.")
        return None

    # 4. Is the caller the owner?
    if member.id != ownership.owner:
        await _send(ctx, "You are not the owner of this voice channel.")
        return None

    return channel, ownership


async def _validate_owner_or_mod(
    ctx: commands.Context,
) -> tuple[discord.VoiceChannel, ChannelOwnership, bool] | None:
    """Validate the caller owns the temp VC OR has moderation permissions.

    Returns ``(channel, ownership, is_owner)`` on success, otherwise sends an
    error message and returns ``None``.
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
        await _send(ctx, "This is not a temporary voice channel.")
        return None

    ownership = get_ownership(channel.id)
    if ownership is None:
        await _send(ctx, "This is not a temporary voice channel.")
        return None

    is_owner = member.id == ownership.owner
    if not is_owner and not _has_mod_permission(member):
        await _send(ctx, "You are not the owner of this voice channel.")
        return None

    return channel, ownership, is_owner


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
        """Manage your temporary voice channel."""
        await ctx.send(
            "Available commands: `?vc lock`, `?vc unlock`, `?vc hide`, "
            "`?vc muteall`, `?vc movall <target>`, `?vc rename <name>`."
        )

    # ------------------------------------------------------------------ #
    # ?vc lock
    # ------------------------------------------------------------------ #

    @vc.command(name="lock", description="Lock your temp VC so new members cannot join.")
    async def lock(self, ctx: commands.Context) -> None:
        validated = await _validate_owner(ctx)
        if validated is None:
            return

        channel, _ = validated

        try:
            ow = _existing_overwrite(channel, ctx.guild.default_role)
            ow.connect = False
            await channel.set_permissions(
                ctx.guild.default_role,
                overwrite=ow,
                reason="Temp channel locked by owner",
            )
        except Exception as exc:
            await _handle_error(ctx, channel, "lock", exc)
            return

        log_action("VC_LOCKED", guild=ctx.guild, user=ctx.author, channel=channel)
        await _send(
            ctx,
            "Your channel is now **locked**. New members cannot join, "
            "but everyone already inside stays.",
        )

    # ------------------------------------------------------------------ #
    # ?vc unlock
    # ------------------------------------------------------------------ #

    @vc.command(name="unlock", description="Unlock your temp VC so members can join again.")
    async def unlock(self, ctx: commands.Context) -> None:
        validated = await _validate_owner(ctx)
        if validated is None:
            return

        channel, _ = validated

        try:
            ow = _existing_overwrite(channel, ctx.guild.default_role)
            ow.connect = True
            await channel.set_permissions(
                ctx.guild.default_role,
                overwrite=ow,
                reason="Temp channel unlocked by owner",
            )
        except Exception as exc:
            await _handle_error(ctx, channel, "unlock", exc)
            return

        log_action("VC_UNLOCKED", guild=ctx.guild, user=ctx.author, channel=channel)
        await _send(ctx, "Your channel is now **unlocked**. Members can join again.")

    # ------------------------------------------------------------------ #
    # ?vc hide
    # ------------------------------------------------------------------ #

    @vc.command(name="hide", description="Hide your temp VC so non-members cannot see it.")
    async def hide(self, ctx: commands.Context) -> None:
        validated = await _validate_owner(ctx)
        if validated is None:
            return

        channel, _ = validated
        guild = ctx.guild
        member = ctx.author

        try:
            ow = _existing_overwrite(channel, guild.default_role)
            ow.view_channel = False
            await channel.set_permissions(
                guild.default_role,
                overwrite=ow,
                reason="Temp channel hidden by owner",
            )

            owner_ow = channel.overwrites_for(member)
            if owner_ow is None:
                owner_ow = discord.PermissionOverwrite()
            owner_ow.view_channel = True
            owner_ow.connect = True
            await channel.set_permissions(
                member,
                overwrite=owner_ow,
                reason="Guarantee owner access to hidden temp channel",
            )

            me = guild.me
            if me is not None:
                bot_ow = channel.overwrites_for(me)
                if bot_ow is None:
                    bot_ow = discord.PermissionOverwrite()
                bot_ow.view_channel = True
                bot_ow.connect = True
                await channel.set_permissions(
                    me,
                    overwrite=bot_ow,
                    reason="Guarantee bot access to hidden temp channel",
                )
        except Exception as exc:
            await _handle_error(ctx, channel, "hide", exc)
            return

        log_action("VC_HIDDEN", guild=guild, user=member, channel=channel)
        await _send(ctx, "Your voice channel is now hidden.")

    # ------------------------------------------------------------------ #
    # ?vc muteall
    # ------------------------------------------------------------------ #

    @vc.command(name="muteall", description="Server-mute everyone in your temp VC.")
    async def muteall(self, ctx: commands.Context) -> None:
        validated = await _validate_owner_or_mod(ctx)
        if validated is None:
            return

        channel, _, _ = validated
        me = ctx.guild.me
        me_id = me.id if me is not None else 0

        muted = 0
        skipped = 0

        try:
            for member in channel.members:
                if member.id == me_id:
                    continue
                try:
                    await member.edit(mute=True, reason="Temp channel muteall")
                    muted += 1
                except discord.Forbidden:
                    skipped += 1
                except discord.HTTPException:
                    skipped += 1
        except Exception as exc:
            await _handle_error(ctx, channel, "muteall", exc)
            return

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

    @vc.command(name="movall", description="Move all members from your temp VC to another voice channel.")
    async def movall(self, ctx: commands.Context, *, target: str) -> None:
        validated = await _validate_owner_or_mod(ctx)
        if validated is None:
            return

        source, _, _ = validated

        target_channel = await _resolve_voice_channel(ctx.guild, target)
        if target_channel is None:
            await _send(ctx, "I couldn't find that voice channel.")
            return

        if target_channel.id == source.id:
            await _send(ctx, "The target channel is the same as the current channel.")
            return

        me = ctx.guild.me
        if me is None or not me.guild_permissions.move_members:
            await _send(ctx, "I don't have Move Members permission in this server.")
            return

        me_id = me.id
        moved = 0
        skipped = 0

        try:
            for member in source.members:
                if member.id == me_id:
                    continue
                try:
                    await member.move_to(target_channel, reason="Temp channel movall")
                    moved += 1
                except discord.Forbidden:
                    skipped += 1
                except discord.HTTPException:
                    skipped += 1
        except Exception as exc:
            await _handle_error(ctx, source, "movall", exc)
            return

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

    @vc.command(name="rename", description="Rename your temp VC.")
    async def rename(self, ctx: commands.Context, *, name: str) -> None:
        stripped = name.strip()
        if not stripped:
            await _send(ctx, "The new name cannot be empty.")
            return
        if len(stripped) > MAX_NAME_LENGTH:
            await _send(ctx, f"The name is too long. Maximum is {MAX_NAME_LENGTH} characters.")
            return

        validated = await _validate_owner(ctx)
        if validated is None:
            return

        channel, _ = validated
        old_name = channel.name
        new_name = f"{TEMP_CHANNEL_PREFIX}{stripped}"

        try:
            await channel.edit(name=new_name, reason="Temp channel renamed by owner")
        except Exception as exc:
            await _handle_error(ctx, channel, "rename", exc)
            return

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
