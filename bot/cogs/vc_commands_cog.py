"""``/vc`` slash command group — owner-only controls for temporary voice channels."""

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


class VcGroup(app_commands.Group):
    """``/vc <subcommand>`` group — lock / unlock / rename."""

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

        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)

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
            await channel.set_permissions(
                interaction.guild.default_role,
                connect=False,
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
            await channel.set_permissions(
                interaction.guild.default_role,
                connect=True,
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
