"""``/vc`` slash command group — owner & moderator controls for temporary voice channels."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import discord
from discord import app_commands
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


async def _send_ephemeral(interaction: discord.Interaction, content: str) -> None:
    """Send an ephemeral message, using followup if the response is already done."""
    if interaction.response.is_done():
        await interaction.followup.send(content, ephemeral=True)
    else:
        await interaction.response.send_message(content, ephemeral=True)


# ------------------------------------------------------------------ #
# Command group
# ------------------------------------------------------------------ #


class VcGroup(app_commands.Group):
    """``/vc <subcommand>`` group — lock / unlock / hide / muteall / movall / rename."""

    def __init__(self) -> None:
        super().__init__(name="vc", description="Manage your temporary voice channel")

    # ------------------------------------------------------------------ #
    # Shared validation
    # ------------------------------------------------------------------ #

    @staticmethod
    async def _validate_owner(
        interaction: discord.Interaction,
    ) -> tuple[discord.VoiceChannel, ChannelOwnership] | None:
        """Validate that the caller owns the temp VC they are connected to.

        Returns ``(channel, ownership)`` on success, otherwise sends an
        ephemeral error to the user and returns ``None``.
        """
        # 1. Connected to a voice channel?
        state = interaction.user.voice
        if state is None or state.channel is None:
            await interaction.response.send_message(
                "You are not connected to a voice channel.", ephemeral=True
            )
            return None

        channel = state.channel

        # 4. Channel still exists and is a voice channel.
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "This is not a temporary voice channel.", ephemeral=True
            )
            return None

        # 2. Is it one of our temp channels?
        ownership = get_ownership(channel.id)
        if ownership is None:
            await interaction.response.send_message(
                "This is not a temporary voice channel.", ephemeral=True
            )
            return None

        # 3. Is the caller the owner?
        if interaction.user.id != ownership.owner:
            await interaction.response.send_message(
                "You are not the owner of this voice channel.", ephemeral=True
            )
            return None

        return channel, ownership

    @staticmethod
    async def _validate_owner_or_mod(
        interaction: discord.Interaction,
    ) -> tuple[discord.VoiceChannel, ChannelOwnership, bool] | None:
        """Validate the caller owns the temp VC OR has moderation permissions.

        Returns ``(channel, ownership, is_owner)`` on success, otherwise sends
        an ephemeral error and returns ``None``.
        """
        state = interaction.user.voice
        if state is None or state.channel is None:
            await interaction.response.send_message(
                "You are not connected to a voice channel.", ephemeral=True
            )
            return None

        channel = state.channel
        if not isinstance(channel, discord.VoiceChannel):
            await interaction.response.send_message(
                "This is not a temporary voice channel.", ephemeral=True
            )
            return None

        ownership = get_ownership(channel.id)
        if ownership is None:
            await interaction.response.send_message(
                "This is not a temporary voice channel.", ephemeral=True
            )
            return None

        is_owner = interaction.user.id == ownership.owner
        if not is_owner and not _has_mod_permission(interaction.user):
            await interaction.response.send_message(
                "You are not the owner of this voice channel.", ephemeral=True
            )
            return None

        return channel, ownership, is_owner

    @staticmethod
    async def _handle_error(
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        action: str,
        exc: Exception,
    ) -> None:
        """Send a friendly ephemeral error and log the underlying exception."""
        if isinstance(exc, discord.Forbidden):
            msg = "I don't have permission to manage this channel."
            log_action(
                "PERMISSION_ERROR",
                guild=interaction.guild,
                user=interaction.user,
                channel=channel,
                detail=f"{action} failed — forbidden",
            )
        elif isinstance(exc, discord.HTTPException):
            msg = "Something went wrong while updating the channel. Please try again."
            log_action(
                "CONFIG_ERROR",
                guild=interaction.guild,
                user=interaction.user,
                channel=channel,
                detail=f"{action} failed: {exc}",
            )
        else:
            msg = "An unexpected error occurred. Please try again."
            log_action(
                "CONFIG_ERROR",
                guild=interaction.guild,
                user=interaction.user,
                channel=channel,
                detail=f"{action} unexpected error: {exc}",
            )

        await _send_ephemeral(interaction, msg)

    # ------------------------------------------------------------------ #
    # /vc lock
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="lock",
        description="Lock your temporary voice channel so new members cannot join.",
    )
    async def lock(self, interaction: discord.Interaction) -> None:
        validated = await self._validate_owner(interaction)
        if validated is None:
            return

        channel, _ = validated

        try:
            # Preserve existing overwrites — only flip connect.
            ow = _existing_overwrite(channel, interaction.guild.default_role)
            ow.connect = False
            await channel.set_permissions(
                interaction.guild.default_role,
                overwrite=ow,
                reason="Temp channel locked by owner",
            )
        except Exception as exc:
            await self._handle_error(interaction, channel, "lock", exc)
            return

        log_action("VC_LOCKED", guild=interaction.guild, user=interaction.user, channel=channel)
        await interaction.response.send_message(
            "Your channel is now **locked**. New members cannot join, "
            "but everyone already inside stays.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # /vc unlock
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="unlock",
        description="Unlock your temporary voice channel so members can join again.",
    )
    async def unlock(self, interaction: discord.Interaction) -> None:
        validated = await self._validate_owner(interaction)
        if validated is None:
            return

        channel, _ = validated

        try:
            ow = _existing_overwrite(channel, interaction.guild.default_role)
            ow.connect = True
            await channel.set_permissions(
                interaction.guild.default_role,
                overwrite=ow,
                reason="Temp channel unlocked by owner",
            )
        except Exception as exc:
            await self._handle_error(interaction, channel, "unlock", exc)
            return

        log_action("VC_UNLOCKED", guild=interaction.guild, user=interaction.user, channel=channel)
        await interaction.response.send_message(
            "Your channel is now **unlocked**. Members can join again.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # /vc hide
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="hide",
        description="Hide your temporary voice channel so non-members cannot see it.",
    )
    async def hide(self, interaction: discord.Interaction) -> None:
        validated = await self._validate_owner(interaction)
        if validated is None:
            return

        channel, _ = validated
        guild = interaction.guild

        try:
            # Hide from @everyone — preserve other overwrites.
            ow = _existing_overwrite(channel, guild.default_role)
            ow.view_channel = False
            await channel.set_permissions(
                guild.default_role,
                overwrite=ow,
                reason="Temp channel hidden by owner",
            )

            # Ensure the owner can still view and connect.
            owner_ow = channel.overwrites_for(interaction.user)
            if owner_ow is None:
                owner_ow = discord.PermissionOverwrite()
            owner_ow.view_channel = True
            owner_ow.connect = True
            await channel.set_permissions(
                interaction.user,
                overwrite=owner_ow,
                reason="Guarantee owner access to hidden temp channel",
            )

            # Ensure the bot itself retains access.
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
            await self._handle_error(interaction, channel, "hide", exc)
            return

        log_action("VC_HIDDEN", guild=guild, user=interaction.user, channel=channel)
        await interaction.response.send_message(
            "Your voice channel is now hidden.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /vc muteall
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="muteall",
        description="Server-mute everyone in your temporary voice channel.",
    )
    async def muteall(self, interaction: discord.Interaction) -> None:
        validated = await self._validate_owner_or_mod(interaction)
        if validated is None:
            return

        channel, _, _ = validated
        me = interaction.guild.me
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
            await self._handle_error(interaction, channel, "muteall", exc)
            return

        log_action(
            "VC_MUTEALL",
            guild=interaction.guild,
            user=interaction.user,
            channel=channel,
            detail=f"muted={muted} skipped={skipped}",
        )

        msg = f"Muted {muted} member{'s' if muted != 1 else ''}."
        if skipped:
            msg += f"\nSkipped {skipped} member{'s' if skipped != 1 else ''} due to permissions."
        await interaction.response.send_message(msg, ephemeral=True)

    # ------------------------------------------------------------------ #
    # /vc movall
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="movall",
        description="Move all members from your temporary VC to another voice channel.",
    )
    @app_commands.describe(
        target="The voice channel to move everyone to"
    )
    async def movall(
        self,
        interaction: discord.Interaction,
        target: discord.VoiceChannel,
    ) -> None:
        validated = await self._validate_owner_or_mod(interaction)
        if validated is None:
            return

        source, _, _ = validated

        if target.id == source.id:
            await interaction.response.send_message(
                "The target channel is the same as the current channel.", ephemeral=True
            )
            return

        me = interaction.guild.me
        if me is None or not me.guild_permissions.move_members:
            await interaction.response.send_message(
                "I don't have Move Members permission in this server.", ephemeral=True
            )
            return

        me_id = me.id
        moved = 0
        skipped = 0

        try:
            for member in source.members:
                if member.id == me_id:
                    continue
                try:
                    await member.move_to(target, reason="Temp channel movall")
                    moved += 1
                except discord.Forbidden:
                    skipped += 1
                except discord.HTTPException:
                    skipped += 1
        except Exception as exc:
            await self._handle_error(interaction, source, "movall", exc)
            return

        log_action(
            "VC_MOVALL",
            guild=interaction.guild,
            user=interaction.user,
            channel=source,
            detail=f"target_id={target.id} moved={moved} skipped={skipped}",
        )

        msg = f"Moved {moved} member{'s' if moved != 1 else ''} to {target.name}."
        if skipped:
            msg += f"\nSkipped {skipped} member{'s' if skipped != 1 else ''}."
        await interaction.response.send_message(msg, ephemeral=True)

    # ------------------------------------------------------------------ #
    # /vc rename
    # ------------------------------------------------------------------ #

    @app_commands.command(
        name="rename", description="Rename your temporary voice channel."
    )
    @app_commands.describe(name="The new name for your channel (max 100 characters)")
    async def rename(self, interaction: discord.Interaction, name: str) -> None:
        stripped = name.strip()
        if not stripped:
            await interaction.response.send_message(
                "The new name cannot be empty.", ephemeral=True
            )
            return
        if len(stripped) > MAX_NAME_LENGTH:
            await interaction.response.send_message(
                f"The name is too long. Maximum is {MAX_NAME_LENGTH} characters.",
                ephemeral=True,
            )
            return

        validated = await self._validate_owner(interaction)
        if validated is None:
            return

        channel, _ = validated
        old_name = channel.name
        new_name = f"{TEMP_CHANNEL_PREFIX}{stripped}"

        try:
            await channel.edit(name=new_name, reason="Temp channel renamed by owner")
        except Exception as exc:
            await self._handle_error(interaction, channel, "rename", exc)
            return

        log_action(
            "VC_RENAMED",
            guild=interaction.guild,
            user=interaction.user,
            channel=channel,
            detail=f"old_name={old_name!r} new_name={new_name!r}",
        )
        await interaction.response.send_message(
            f"Channel renamed from **{old_name}** to **{new_name}**.",
            ephemeral=True,
        )


class VcCommandsCog(commands.Cog):
    """Registers the ``/vc`` command tree."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        bot.tree.add_command(VcGroup())


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VcCommandsCog(bot))
