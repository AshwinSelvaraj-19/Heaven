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
from bot.utils.permanent_voice import (
    connect_to_permanent_voice,
    get_permanent_channel_id,
)
from bot.utils.temp_channels import cleanup_orphans
from bot.utils.voice_status import (
    get_voice_user_count,
    update_voice_status,
)


# ------------------------------------------------------------------
# Logging
# ------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("bot")


# ------------------------------------------------------------------
# Discord intents
# ------------------------------------------------------------------

intents = discord.Intents.default()

intents.voice_states = True
intents.guilds = True
intents.members = True
intents.message_content = True


# ------------------------------------------------------------------
# Mention-only command prefix
# ------------------------------------------------------------------

def _mention_prefix(
    bot: commands.Bot,
    _message: discord.Message,
) -> list[str]:
    """Return the only accepted command prefixes."""

    if bot.user is None:
        return []

    return [
        f"<@{bot.user.id}> ?",
        f"<@!{bot.user.id}> ?",
    ]


# ------------------------------------------------------------------
# Bot
# ------------------------------------------------------------------

class VCBot(commands.Bot):
    """Bot subclass with cogs auto-loaded on startup."""

    def __init__(self) -> None:
        super().__init__(
            command_prefix=_mention_prefix,
            intents=intents,
            help_command=None,
            strip_after_prefix=True,
        )

        # Single background task for activity rotation.
        self._activity_task: asyncio.Task[None] | None = None

        # Current activity position.
        self._activity_index = 0

    # ------------------------------------------------------------------
    # Cog loading
    # ------------------------------------------------------------------

    async def setup_hook(self) -> None:
        """Load production cogs."""

        # AntiSpamCog is intentionally NOT loaded here.
        # It is local/unreleased work and must not affect production.

        from bot.cogs import (
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

        logger.info("Production cogs loaded successfully.")

    # ------------------------------------------------------------------
    # Discord ready event
    # ------------------------------------------------------------------

    async def on_ready(self) -> None:
        """Initialize Heaven after connecting to Discord."""

        if self.user is None:
            return

        logger.info(
            "Logged in as %s (ID: %s)",
            self.user,
            self.user.id,
        )

        # Load saved settings.
        await asyncio.to_thread(
            preload_all_settings
        )

        # Clean up orphaned temporary channels.
        await cleanup_orphans(self)

        logger.info(
            "Orphan cleanup complete."
        )

        # Connect to Heaven's permanent VC.
        await connect_to_permanent_voice(self)

        # --------------------------------------------------------------
        # Initialize VC status
        # --------------------------------------------------------------

        for guild in self.guilds:
            try:
                await update_voice_status(guild)

            except Exception:
                logger.exception(
                    "Failed to initialize voice status "
                    "for guild %s.",
                    guild.id,
                )

        # --------------------------------------------------------------
        # Start activity rotation once
        # --------------------------------------------------------------

        if (
            self._activity_task is None
            or self._activity_task.done()
        ):
            self._activity_task = asyncio.create_task(
                self._rotate_activity(),
                name="heaven-activity-rotation",
            )

            logger.info(
                "Heaven activity rotation started."
            )

    # ------------------------------------------------------------------
    # Activity rotation
    # ------------------------------------------------------------------

    async def _rotate_activity(self) -> None:
        """Rotate Heaven's Discord activity every 60 seconds."""

        try:
            while not self.is_closed():

                # ------------------------------------------------------
                # Find guild containing permanent Heaven VC
                # ------------------------------------------------------

                target_guild: discord.Guild | None = None

                permanent_channel_id = (
                    get_permanent_channel_id()
                )

                if permanent_channel_id is not None:

                    for guild in self.guilds:

                        channel = guild.get_channel(
                            permanent_channel_id
                        )

                        if isinstance(
                            channel,
                            discord.VoiceChannel,
                        ):
                            target_guild = guild
                            break

                # ------------------------------------------------------
                # Fallback to first guild
                # ------------------------------------------------------

                if (
                    target_guild is None
                    and self.guilds
                ):
                    target_guild = self.guilds[0]

                # ------------------------------------------------------
                # No guild available
                # ------------------------------------------------------

                if target_guild is None:

                    await self.change_presence(
                        activity=discord.Activity(
                            type=discord.ActivityType.watching,
                            name="over Heaven",
                        )
                    )

                    await asyncio.sleep(60)
                    continue

                # ------------------------------------------------------
                # Get current statistics
                # ------------------------------------------------------

                voice_count = get_voice_user_count(
                    target_guild
                )

                member_count = (
                    target_guild.member_count
                    or len(target_guild.members)
                )

                # ------------------------------------------------------
                # Nobody in VC
                # ------------------------------------------------------

                if voice_count == 0:

                    activity_text = (
                        "☾ Heaven is quiet"
                    )

                # ------------------------------------------------------
                # Users are in VC
                # ------------------------------------------------------

                else:

                    activities = [
                        "𖤐 Watching over Heaven",
                        (
                            f"𖦹 {member_count} "
                            "souls in Heaven"
                        ),
                        (
                            f"◈ {voice_count} "
                            "souls in voice"
                        ),
                        "⛧ Protecting the Society",
                    ]

                    activity_text = activities[
                        self._activity_index
                        % len(activities)
                    ]

                    self._activity_index += 1

                # ------------------------------------------------------
                # Update Discord presence
                # ------------------------------------------------------

                await self.change_presence(
                    activity=discord.Activity(
                        type=discord.ActivityType.watching,
                        name=activity_text,
                    )
                )

                logger.debug(
                    "Discord activity updated: %s",
                    activity_text,
                )

                # Rotate every 60 seconds.
                await asyncio.sleep(60)

        except asyncio.CancelledError:

            logger.debug(
                "Heaven activity rotation stopped."
            )

            raise

        except Exception:

            logger.exception(
                "Unexpected error in Heaven activity rotation."
            )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def close(self) -> None:
        """Cleanly stop background tasks before shutdown."""

        if (
            self._activity_task is not None
            and not self._activity_task.done()
        ):

            self._activity_task.cancel()

            try:
                await self._activity_task

            except asyncio.CancelledError:
                pass

        await super().close()


# ------------------------------------------------------------------
# Main
# ------------------------------------------------------------------

async def main() -> None:
    """Start the Discord bot."""

    if not config.DISCORD_TOKEN:

        logger.error(
            "DISCORD_TOKEN is not set. "
            "Add it to your environment variables."
        )

        return

    bot = VCBot()

    async with bot:
        await bot.start(
            config.DISCORD_TOKEN
        )


# ------------------------------------------------------------------
# Entry point
# ------------------------------------------------------------------

if __name__ == "__main__":
    asyncio.run(main())