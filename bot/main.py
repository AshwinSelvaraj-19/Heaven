"""Bot entry point — loads cogs and starts the bot.

Commands are triggered by mentioning the bot followed by ``?``, e.g.::

    @Bot ?vc lock
    @Bot ?settings vc limit 5

The mention-plus-``?`` prefix is enforced by overriding
:meth:`commands.Bot.get_prefix` — a bare ``?`` prefix is never accepted.
"""

from __future__ import annotations

import asyncio
import logging

import discord
from discord.ext import commands

from bot.config import config
from bot.settings_store import preload_all_settings
from bot.utils.temp_channels import cleanup_orphans
from bot.utils.permanent_voice import connect_to_permanent_voice

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)
logger = logging.getLogger("bot")


intents = discord.Intents.default()
intents.voice_states = True
intents.guilds = True
intents.members = True
intents.message_content = True  # required for mention-prefixed commands


def _mention_prefix(bot: commands.Bot, _message: discord.Message) -> list[str]:
    """Return the only accepted prefixes: ``<@bot_id> ?`` and ``<@!bot_id> ?``.

    discord.py calls this function for every message. If the message does not
    start with one of these exact prefixes, the bot ignores it entirely.
    """
    if bot.user is None:
        return []
    return [f"<@{bot.user.id}> ?", f"<@!{bot.user.id}> ?"]


class VCBot(commands.Bot):
    """Bot subclass with cogs auto-loaded on startup."""

    def __init__(self) -> None:
        super().__init__(
            command_prefix=_mention_prefix,
            intents=intents,
            help_command=None,
            strip_after_prefix=True,
        )

    async def setup_hook(self) -> None:
        from bot.cogs import (
            AntiSpamCog,
            CreateCommandsCog,
            HelpCog,
            SettingsCog,
            VoiceListenerCog,
            VcCommandsCog,
        )

        await self.add_cog(SettingsCog(self))
        await self.add_cog(VoiceListenerCog(self))
        await self.add_cog(VcCommandsCog(self))
        await self.add_cog(CreateCommandsCog(self))
        await self.add_cog(HelpCog(self))
        

    async def on_ready(self) -> None:
        logger.info("Logged in as %s (ID: %s)", self.user, self.user.id)
        await asyncio.to_thread(preload_all_settings)
        await cleanup_orphans(self)
        logger.info("Orphan cleanup complete.")
        await connect_to_permanent_voice(self)


async def main() -> None:
    if not config.DISCORD_TOKEN:
        logger.error("DISCORD_TOKEN is not set. Add it to your .env file.")
        return

    bot = VCBot()

    async with bot:
        await bot.start(config.DISCORD_TOKEN)


if __name__ == "__main__":
    asyncio.run(main())
