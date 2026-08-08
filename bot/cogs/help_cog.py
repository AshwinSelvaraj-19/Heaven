"""``?help`` prefix command — lists all available commands."""

from __future__ import annotations

import discord
from discord.ext import commands

HELP_TEXT = """\
**Voice Channel Commands**
`?vc lock` — Lock your temp VC so new members cannot join.
`?vc unlock` — Unlock your temp VC so members can join again.
`?vc hide` — Hide your temp VC from non-members.
`?vc muteall` — Server-mute everyone in your temp VC.
`?vc movall <target>` — Move everyone from your temp VC to another voice channel.
`?vc rename <name>` — Rename your temp VC.

**Settings Commands** (admin only)
`?settings vc category <voice_channel>` — Set the category for temp VCs.
`?settings vc lobby <voice_channel>` — Set the lobby channel.
`?settings vc limit <number>` — Set the user limit (0 = unlimited).
`?settings vc bitrate <kbps>` — Set the bitrate (8–384 kbps).
`?settings vc autodelete <seconds>` — Set the autodelete delay (0–3600 seconds).

**Usage**
Mention the bot followed by `?` before any command, e.g.:
`@{bot} ?vc lock`
"""


class HelpCog(commands.Cog):
    """Registers the ``?help`` command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help", description="Show available commands.")
    async def help(self, ctx: commands.Context) -> None:
        bot_name = self.bot.user.display_name if self.bot.user else "Bot"
        await ctx.send(HELP_TEXT.format(bot=bot_name))


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
