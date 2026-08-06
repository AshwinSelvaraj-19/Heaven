"""Bot entry point — loads cogs and starts the bot."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.config import config
from bot.utils.temp_channels import cleanup_orphans

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("bot")


intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True


class VCBot(commands.Bot):
    """Bot subclass with cogs auto-loaded on startup."""

    async def setup_hook(self) -> None:
        from bot.cogs import SettingsCog, VoiceListenerCog

        await self.add_cog(SettingsCog(self))
        await self.add_cog(VoiceListenerCog(self))
        await self.tree.sync()
        logger.info("Slash commands synced.")

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await cleanup_orphans(self)
        logger.info("Orphan cleanup complete.")


async def main() -> None:
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is not set. Add it to your .env file.")
        return

    bot = VCBot(
        command_prefix="!",
        intents=intents,
        help_command=None,
    )

    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
