"""Listens for voice state updates to create and delete temporary channels."""

from __future__ import annotations

import asyncio
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
from bot.utils.permanent_voice import on_bot_voice_state_update
from bot.utils.temp_channels import (
    cancel_deletion,
    create_temp_channel,
    maybe_schedule_deletion,
    reuse_existing_channel,
)
from bot.utils.voice_status import update_voice_status

logger = logging.getLogger("bot.vc")


class VoiceListenerCog(commands.Cog):
    """Handles ``on_voice_state_update`` events for temp channel lifecycle."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._status_tasks: dict[int, asyncio.Task[None]] = {}

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

        # --- Permanent voice reconnection ------------------------------------- #
        # Check if the bot itself was disconnected and trigger reconnection if needed.
        on_bot_voice_state_update(self.bot, member, before, after)

        # --- Dynamic permanent VC status -------------------------------------- #
        await self._schedule_voice_status_update(member.guild)

    async def _schedule_voice_status_update(
        self,
        guild: discord.Guild,
    ) -> None:
        """Schedule a debounced permanent VC status update."""

        existing_task = self._status_tasks.get(guild.id)

        if existing_task is not None and not existing_task.done():
            existing_task.cancel()

        async def delayed_update() -> None:
            try:
                await asyncio.sleep(1.0)
                await update_voice_status(guild)

            except asyncio.CancelledError:
                raise

            except Exception:
                logger.exception(
                    "Failed to update voice status for guild %s.",
                    guild.id,
                )

            finally:
                current_task = self._status_tasks.get(guild.id)

                if current_task is asyncio.current_task():
                    self._status_tasks.pop(guild.id, None)

        self._status_tasks[guild.id] = asyncio.create_task(
            delayed_update()
        )

    # ------------------------------------------------------------------ #
    # Handlers
    # ------------------------------------------------------------------ #

    async def _handle_join(
        self,
        member: discord.Member,
        channel: discord.abc.VoiceChannel,
    ) -> None:
        """If the member joined the lobby, reuse their existing temp channel if any."""

        settings = get_settings(member.guild.id)
        lobby_id = settings.get("lobby_id")

        if not lobby_id or channel.id != lobby_id:
            return

        # The lobby itself should never be auto-deleted.
        cancel_deletion(channel.id)

        # --- Reuse existing channel if user has one ------------------------- #
        existing_id = get_channel_for_user(member.id)

        if existing_id is not None:
            reused = await reuse_existing_channel(
                member.guild,
                member,
                existing_id,
            )

            if reused is not None:
                return

            # If reuse returned None the channel was deleted externally —
            # user will need to create a new one with ?create vc.

    async def _handle_leave(
        self,
        channel: discord.abc.VoiceChannel,
    ) -> None:
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