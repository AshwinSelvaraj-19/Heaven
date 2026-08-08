"""``?settings vc`` prefix command group — admin-only VC configuration.

Commands are invoked by mentioning the bot followed by ``?``::

    @Bot ?settings vc category <category>
    @Bot ?settings vc lobby <voice_channel>
    @Bot ?settings vc limit <number>
    @Bot ?settings vc bitrate <kbps>
    @Bot ?settings vc autodelete <seconds>
"""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.settings_store import update_settings
from bot.utils.channel_utils import resolve_voice_channel, resolve_category
from bot.utils.permissions import is_admin
from bot.constants import (
    MIN_BITRATE,
    MAX_BITRATE,
    MIN_LIMIT,
    MAX_LIMIT,
    MIN_DELETE_DELAY,
    MAX_DELETE_DELAY,
)


async def _admin_check(ctx: commands.Context) -> bool:
    """Return True if the author is a server admin; send a denial if not."""
    member = ctx.author
    if not isinstance(member, discord.Member):
        await ctx.send("This command can only be used in a server.")
        return False
    if not is_admin(member):
        await ctx.send("You need **Administrator** permissions to use this command.")
        return False
    return True




class SettingsCog(commands.Cog):
    """``?settings`` prefix command group — server configuration."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(name="settings", invoke_without_command=True)
    async def settings(self, ctx: commands.Context) -> None:
        """Server settings."""
        await ctx.send(
            "Available settings: `?settings vc category`, `?settings vc lobby`, "
            "`?settings vc limit`, `?settings vc bitrate`, `?settings vc autodelete`."
        )

    @settings.group(name="vc", invoke_without_command=True)
    async def vc_settings(self, ctx: commands.Context) -> None:
        """Configure temporary voice channels."""
        await ctx.send(
            "Available VC settings: `?settings vc category`, `?settings vc lobby`, "
            "`?settings vc limit`, `?settings vc bitrate`, `?settings vc autodelete`."
        )

    # ------------------------------------------------------------------ #
    # ?settings vc category <category>
    # ------------------------------------------------------------------ #

    @vc_settings.command(name="category", description="Set the category for temp VCs.")
    async def category(self, ctx: commands.Context, *, category_query: str) -> None:
        if not await _admin_check(ctx):
            return

        category = resolve_category(ctx.guild, category_query)
        if category is None:
            await ctx.send("I couldn't find that category.")
            return

        update_settings(ctx.guild.id, {"category_id": category.id})
        await ctx.send(f"Temp channels will be created in **{category.name}**.")

    # ------------------------------------------------------------------ #
    # ?settings vc lobby <voice_channel>
    # ------------------------------------------------------------------ #

    @vc_settings.command(name="lobby", description="Set the lobby channel.")
    async def lobby(self, ctx: commands.Context, *, voice_channel: str) -> None:
        if not await _admin_check(ctx):
            return

        channel = resolve_voice_channel(ctx.guild, voice_channel)
        if channel is None:
            await ctx.send("I couldn't find that voice channel.")
            return

        update_settings(ctx.guild.id, {"lobby_id": channel.id})
        await ctx.send(f"Lobby channel set to **{channel.name}**.")

    # ------------------------------------------------------------------ #
    # ?settings vc limit <number>
    # ------------------------------------------------------------------ #

    @vc_settings.command(name="limit", description="Set the user limit for temp VCs (0 = unlimited).")
    async def limit(self, ctx: commands.Context, *, number: str) -> None:
        if not await _admin_check(ctx):
            return

        try:
            value = int(number.strip())
        except ValueError:
            await ctx.send("Please provide a valid number (0–99).")
            return

        if not (MIN_LIMIT <= value <= MAX_LIMIT):
            await ctx.send(f"The limit must be between {MIN_LIMIT} and {MAX_LIMIT}.")
            return

        update_settings(ctx.guild.id, {"user_limit": value})
        label = "unlimited" if value == 0 else str(value)
        await ctx.send(f"Temp channel user limit set to **{label}**.")

    # ------------------------------------------------------------------ #
    # ?settings vc bitrate <kbps>
    # ------------------------------------------------------------------ #

    @vc_settings.command(name="bitrate", description="Set the bitrate (kbps) for temp VCs.")
    async def bitrate(self, ctx: commands.Context, *, kbps: str) -> None:
        if not await _admin_check(ctx):
            return

        try:
            value = int(kbps.strip())
        except ValueError:
            await ctx.send("Please provide a valid number (8–384).")
            return

        if not (MIN_BITRATE <= value <= MAX_BITRATE):
            await ctx.send(f"The bitrate must be between {MIN_BITRATE} and {MAX_BITRATE} kbps.")
            return

        update_settings(ctx.guild.id, {"bitrate": value * 1000})
        await ctx.send(f"Temp channel bitrate set to **{value} kbps**.")

    # ------------------------------------------------------------------ #
    # ?settings vc autodelete <seconds>
    # ------------------------------------------------------------------ #

    @vc_settings.command(name="autodelete", description="Set the autodelete delay (seconds) for temp VCs.")
    async def autodelete(self, ctx: commands.Context, *, seconds: str) -> None:
        if not await _admin_check(ctx):
            return

        try:
            value = int(seconds.strip())
        except ValueError:
            await ctx.send("Please provide a valid number (0–3600).")
            return

        if not (MIN_DELETE_DELAY <= value <= MAX_DELETE_DELAY):
            await ctx.send(f"The delay must be between {MIN_DELETE_DELAY} and {MAX_DELETE_DELAY} seconds.")
            return

        update_settings(ctx.guild.id, {"autodelete_seconds": value})
        await ctx.send(f"Autodelete delay set to **{value} seconds**.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(SettingsCog(bot))
