"""``?help`` prefix command — lists all available commands."""

from __future__ import annotations

import discord
from discord.ext import commands


class HelpCog(commands.Cog):
    """Registers the ``?help`` command."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.command(name="help", description="Show available commands.")
    async def help(self, ctx: commands.Context) -> None:
        """Display a clean help panel with all available commands."""
        bot_name = self.bot.user.display_name if self.bot.user else "Heaven"

        embed = discord.Embed(
            title="🎤 Heaven Voice Commands",
            description=f"Use `@{bot_name} ?` before any command.",
            color=discord.Color.blue(),
        )

        # Voice Commands
        voice_commands = (
            "`?create vc <name>` — Create your own temporary VC.\n"
            "`?vc lock` — Lock the current VC.\n"
            "`?vc unlock` — Unlock the current VC.\n"
            "`?vc hide` — Hide the current VC.\n"
            "`?vc unhide` — Unhide the current VC.\n"
            "`?vc muteall` — Mute everyone in the current VC.\n"
            "`?vc movall <target>` — Move everyone to another VC.\n"
            "`?vc rename <name>` — Rename the current VC."
        )
        embed.add_field(name="🎤 Voice Commands", value=voice_commands, inline=False)

        # Admin Settings
        admin_settings = (
            "`?settings vc category <category>` — Set where temporary VCs are created.\n"
            "`?settings vc lobby <voice_channel>` — Set the Join to Create lobby.\n"
            "`?settings vc limit <number>` — Set the temporary VC user limit.\n"
            "`?settings vc bitrate <kbps>` — Set temporary VC bitrate.\n"
            "`?settings vc autodelete <seconds>` — Set how long an empty temporary VC remains before deletion."
        )
        embed.add_field(name="⚙️ Admin Settings (🔒 Administrator Only)", value=admin_settings, inline=False)

        # How It Works
        how_it_works = (
            "1. Join the Join to Create voice channel.\n"
            "2. Type: `@Heaven ?create vc <name>`\n"
            "3. Heaven creates your VC.\n"
            "4. Heaven moves you into it.\n"
            "5. You control that VC only.\n"
            "6. When everyone leaves, it is deleted after the configured delay.\n\n"
            "**Example:** `@Heaven ?create vc 🎮・Phoenix Gaming`"
        )
        embed.add_field(name="📌 How It Works", value=how_it_works, inline=False)

        embed.set_footer(text=f"Prefix: @{bot_name} ?")
        await ctx.send(embed=embed)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(HelpCog(bot))
