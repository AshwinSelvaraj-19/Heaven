"""``?create`` prefix command group — explicit temporary VC creation."""

from __future__ import annotations

import discord
from discord.ext import commands

from bot.constants import DEFAULT_BITRATE, DEFAULT_LIMIT, REQUIRED_PERMISSIONS
from bot.settings_store import get_settings
from bot.utils.logging_utils import log_action
from bot.utils.ownership import get_channel_for_user, register_channel
from bot.utils.temp_channels import validate_config


class CreateCommandsCog(commands.Cog):
    """``?create`` prefix command group — explicit temporary VC creation."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.group(name="create", invoke_without_command=True)
    async def create(self, ctx: commands.Context) -> None:
        """Create temporary voice channels."""
        await ctx.send(
            "Available commands: `?create vc <name>` — Create your own temporary voice channel."
        )

    @create.command(name="vc", description="Create your own temporary voice channel.")
    async def vc(self, ctx: commands.Context, *, name: str) -> None:
        """Create a temporary voice channel with the specified name.

        The user must be connected to the configured Join to Create lobby.
        """
        member = ctx.author
        if not isinstance(member, discord.Member):
            await ctx.send("This command can only be used in a server.")
            return

        # Check if user is in a voice channel
        if member.voice is None or member.voice.channel is None:
            await ctx.send("You must be connected to the Join to Create lobby first.")
            return

        # Check if user is in the configured lobby
        settings = get_settings(ctx.guild.id)
        lobby_id = settings.get("lobby_id")
        if not lobby_id:
            await ctx.send("Join to Create lobby is not configured.")
            return

        if member.voice.channel.id != lobby_id:
            await ctx.send("You must be connected to the Join to Create lobby first.")
            return

        # Check if user already owns a temporary VC
        existing_channel_id = get_channel_for_user(member.id)
        if existing_channel_id:
            existing_channel = ctx.guild.get_channel(existing_channel_id)
            if existing_channel:
                await ctx.send(
                    f"You already own an active temporary VC: **{existing_channel.name}**."
                )
                return

        # Validate name
        if not name or not name.strip():
            await ctx.send("Please provide a valid VC name.")
            return

        stripped_name = name.strip()
        if len(stripped_name) > 100:
            await ctx.send("VC name is too long. Maximum is 100 characters.")
            return

        # Validate configuration
        ok, msg = validate_config(ctx.guild)
        if not ok:
            await ctx.send(msg)
            return

        # Get category
        category_id = settings.get("category_id")
        category = ctx.guild.get_channel(category_id)
        if not isinstance(category, discord.CategoryChannel):
            await ctx.send("Temporary VC category is not configured.")
            return

        # Check bot permissions
        me = ctx.guild.me
        if me is None:
            await ctx.send("I am not in this server.")
            return

        missing = []
        for perm in REQUIRED_PERMISSIONS:
            if not getattr(me.guild_permissions, perm, False):
                missing.append(perm)
        if missing:
            human = ", ".join(missing).replace("_", " ").title()
            await ctx.send(f"I don't have permission to create or manage temporary voice channels: {human}.")
            return

        # Create channel with owner overwrites
        user_limit = settings.get("user_limit") or DEFAULT_LIMIT
        bitrate = settings.get("bitrate") or DEFAULT_BITRATE

        overwrites = {
            ctx.guild.default_role: discord.PermissionOverwrite(view_channel=True),
            member: discord.PermissionOverwrite(
                view_channel=True,
                manage_channels=True,
                move_members=True,
                mute_members=True,
                deafen_members=True,
            ),
        }

        try:
            channel = await ctx.guild.create_voice_channel(
                name=stripped_name,
                category=category,
                user_limit=user_limit,
                bitrate=bitrate,
                overwrites=overwrites,
                reason=f"Temp channel created by {member}",
            )
        except discord.Forbidden:
            log_action("PERMISSION_ERROR", guild=ctx.guild, user=member, detail="create_voice_channel forbidden")
            await ctx.send("I don't have permission to create or manage temporary voice channels.")
            return
        except discord.HTTPException as exc:
            log_action("CONFIG_ERROR", guild=ctx.guild, user=member, detail=f"create failed: {exc}")
            await ctx.send("Failed to create the temporary voice channel.")
            return

        # Register ownership
        register_channel(channel.id, member.id, ctx.guild.id)
        log_action("VC_CREATED", guild=ctx.guild, user=member, channel=channel, detail="explicit creation")

        # Move user to new channel
        try:
            await member.move_to(channel, reason="Moved to newly created temp channel")
            log_action("USER_MOVED", guild=ctx.guild, user=member, channel=channel, detail="create command")
        except discord.HTTPException as exc:
            log_action("CONFIG_ERROR", guild=ctx.guild, user=member, channel=channel, detail=f"move failed: {exc}")
            await ctx.send("Failed to move you to the new channel.")
            return

        await ctx.send(f"Created **{channel.name}** and moved you into it.")


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(CreateCommandsCog(bot))
