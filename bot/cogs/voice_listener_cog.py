"""Listens for voice state updates to create and delete temporary channels."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from bot.constants import USER_CREATE_COOLDOWN
from bot.settings_store import get_settings
from bot.utils.logging_utils import log_action
from bot.utils.ownership import (
    get_channel_for_user,
    is_on_cooldown,
    mark_cooldown,
)
from bot.utils.temp_channels import (
    cancel_deletion,
    create_temp_channel,
    maybe_schedule_deletion,
    reuse_existing_channel,
)

logger = logging.getLogger("bot.vc")


class VoiceListenerCog(commands.Cog):
    """Handles ``on_voice_state_update`` events for temp channel lifecycle."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # --- Joining a channel ------------------------------------------------ #
        if after.channel is not None and after.channel != before.channel:
            await self._handle_join(member, after.channel)

        # --- Leaving a channel ------------------------------------------------ #
        if before.channel is not None and before.channel != after.channel:
            await self._handle_leave(before.channel)

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #
    async def _handle_join(
        self, member: discord.Member, channel: discord.abc.VoiceChannel
    ) -> None:
        """If the member joined the lobby, create or reuse a temp channel."""
        settings = get_settings(member.guild.id)
        lobby_id = settings.get("lobby_id")

        if not lobby_id or channel.id != lobby_id:
            return

        # The lobby itself should never be auto-deleted.
        cancel_deletion(channel.id)

        # --- Duplicate prevention: reuse existing channel -------------------- #
        existing_id = get_channel_for_user(member.id)
        if existing_id is not None:
            reused = await reuse_existing_channel(member.guild, member, existing_id)
            if reused is not None:
                return
            # If reuse returned None the channel was deleted externally —
            # fall through to create a new one.

        # --- Rate limiting --------------------------------------------------- #
        if is_on_cooldown(member.id, USER_CREATE_COOLDOWN):
            log_action(
                "CONFIG_ERROR",
                guild=member.guild,
                user=member,
                detail=f"create blocked — cooldown ({USER_CREATE_COOLDOWN}s)",
            )
            return

        created = await create_temp_channel(member.guild, member)
        if created is not None:
            mark_cooldown(member.id)
        else:
            # Settings incomplete or creation failed — notify the admin.
            try:
                await member.send(
                    "I couldn't create a temporary channel for you. "
                    "Ask a server admin to configure the VC category with "
                    "`/settings vc category`."
                )
            except discord.Forbidden:
                pass

    async def _handle_leave(self, channel: discord.abc.VoiceChannel) -> None:
        """If a temp channel is now empty, schedule its deletion."""
        if not isinstance(channel, discord.VoiceChannel):
            return

        if channel.members:
            return

        # Skip the lobby channel — it should never be auto-deleted.
        settings = get_settings(channel.guild.id)
        if channel.id == settings.get("lobby_id"):
            return

        maybe_schedule_deletion(channel)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(VoiceListenerCog(bot))
