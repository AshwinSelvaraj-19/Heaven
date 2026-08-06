"""``/settings vc`` slash command group — admin-only VC configuration."""

from __future__ import annotations

import discord
from discord import app_commands
from discord.ext import commands

from bot.settings_store import get_settings, update_settings
from bot.utils.permissions import is_admin
from bot.constants import (
    MIN_BITRATE,
    MAX_BITRATE,
    MIN_LIMIT,
    MAX_LIMIT,
    MIN_DELETE_DELAY,
    MAX_DELETE_DELAY,
)


class VcSettingsGroup(app_commands.Group):
    """``/settings vc <subcommand>`` group."""

    def __init__(self) -> None:
        super().__init__(name="vc", description="Configure temporary voice channels")

    # ------------------------------------------------------------------ #
    # Helper
    # ------------------------------------------------------------------ #
    @staticmethod
    def _admin_check(interaction: discord.Interaction) -> bool:
        member = interaction.user
        if not isinstance(member, discord.Member):
            # In DMs the member object isn't available — deny by default.
            return False
        return is_admin(member)

    async def _deny(self, interaction: discord.Interaction) -> None:
        await interaction.response.send_message(
            "You need **Administrator** permissions to use this command.",
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # /settings vc category <voice_channel>
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="category",
        description="Set the category where temporary voice channels are created.",
    )
    @app_commands.describe(
        voice_channel="A channel in the category to use (any voice channel works)"
    )
    async def category(
        self, interaction: discord.Interaction, voice_channel: discord.VoiceChannel
    ) -> None:
        if not self._admin_check(interaction):
            return await self._deny(interaction)

        category = voice_channel.category
        if category is None:
            await interaction.response.send_message(
                "That voice channel is not inside a category. "
                "Please move it into a category first, or pick a channel that is in one.",
                ephemeral=True,
            )
            return

        update_settings(interaction.guild_id, {"category_id": category.id})
        await interaction.response.send_message(
            f"Temp channels will be created in **{category.name}**.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /settings vc lobby <voice_channel>
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="lobby",
        description="Set the lobby channel users join to trigger temp channel creation.",
    )
    @app_commands.describe(voice_channel="The voice channel to use as the lobby")
    async def lobby(
        self, interaction: discord.Interaction, voice_channel: discord.VoiceChannel
    ) -> None:
        if not self._admin_check(interaction):
            return await self._deny(interaction)

        update_settings(interaction.guild_id, {"lobby_id": voice_channel.id})
        await interaction.response.send_message(
            f"Lobby channel set to **{voice_channel.name}**.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /settings vc limit <integer>
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="limit", description="Set the user limit for temporary channels (0 = unlimited)."
    )
    @app_commands.describe(integer="Max users (0–99, 0 means no limit)")
    async def limit(self, interaction: discord.Interaction, integer: app_commands.Range[int, MIN_LIMIT, MAX_LIMIT]) -> None:
        if not self._admin_check(interaction):
            return await self._deny(interaction)

        update_settings(interaction.guild_id, {"user_limit": integer})
        label = "unlimited" if integer == 0 else str(integer)
        await interaction.response.send_message(
            f"Temp channel user limit set to **{label}**.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /settings vc bitrate <integer>
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="bitrate", description="Set the bitrate (kbps) for temporary channels."
    )
    @app_commands.describe(integer="Bitrate in kbps (8–384)")
    async def bitrate(
        self, interaction: discord.Interaction, integer: app_commands.Range[int, MIN_BITRATE, MAX_BITRATE]
    ) -> None:
        if not self._admin_check(interaction):
            return await self._deny(interaction)

        update_settings(interaction.guild_id, {"bitrate": integer * 1000})
        await interaction.response.send_message(
            f"Temp channel bitrate set to **{integer} kbps**.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # /settings vc autodelete <integer>
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="autodelete",
        description="Set how long (seconds) before an empty temp channel is deleted.",
    )
    @app_commands.describe(integer="Seconds to wait before deletion (0–3600)")
    async def autodelete(
        self, interaction: discord.Interaction, integer: app_commands.Range[int, MIN_DELETE_DELAY, MAX_DELETE_DELAY]
    ) -> None:
        if not self._admin_check(interaction):
            return await self._deny(interaction)

        update_settings(interaction.guild_id, {"autodelete_seconds": integer})
        await interaction.response.send_message(
            f"Autodelete delay set to **{integer} seconds**.", ephemeral=True
        )


class SettingsCog(commands.Cog):
    """Registers the ``/settings`` command tree."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        settings_group = app_commands.Group(
            name="settings",
            description="Server settings",
        )
        settings_group.add_command(VcSettingsGroup())
        bot.tree.add_command(settings_group)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
