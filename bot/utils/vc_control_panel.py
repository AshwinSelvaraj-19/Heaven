"""Interactive Heaven VC control panel."""

from __future__ import annotations

import discord
from discord.ui import (
    Button,
    ChannelSelect,
    Modal,
    Select,
    TextInput,
    UserSelect,
    View,
)

from bot.utils.permissions import can_control_voice_channel
from bot.utils.ownership import get_ownership


MAX_NAME_LENGTH = 100


# =====================================================================
# Helpers
# =====================================================================


def _get_control_channel(
    interaction: discord.Interaction,
) -> discord.VoiceChannel | None:
    """Return the voice channel the interacting member is currently in."""

    if not isinstance(interaction.user, discord.Member):
        return None

    voice_state = interaction.user.voice

    if voice_state is None:
        return None

    channel = voice_state.channel

    if not isinstance(channel, discord.VoiceChannel):
        return None

    return channel


async def _require_control(
    interaction: discord.Interaction,
    required_permission: str = "manage_channels",
) -> discord.VoiceChannel | None:
    """Validate channel and user authorization."""

    channel = _get_control_channel(interaction)

    if channel is None:
        await interaction.response.send_message(
            "❌ You must be connected to a voice channel.",
            ephemeral=True,
        )
        return None

    if not isinstance(interaction.user, discord.Member):
        return None

    allowed, _ = can_control_voice_channel(
        interaction.user,
        channel,
        required_permission,
    )

    if not allowed:
        await interaction.response.send_message(
            "❌ You don't have permission to control this voice channel.",
            ephemeral=True,
        )
        return None

    me = channel.guild.me

    if me is None:
        await interaction.response.send_message(
            "❌ I am not available in this server.",
            ephemeral=True,
        )
        return None

    return channel


def _bot_can(
    channel: discord.VoiceChannel,
    permission: str,
) -> bool:
    """Check whether the bot has a channel permission."""

    me = channel.guild.me

    if me is None:
        return False

    return bool(
        getattr(
            channel.permissions_for(me),
            permission,
            False,
        )
    )


# =====================================================================
# Rename modal
# =====================================================================


class RenameModal(Modal, title="Rename Voice Channel"):

    name = TextInput(
        label="New channel name",
        placeholder="Enter the new channel name",
        min_length=1,
        max_length=MAX_NAME_LENGTH,
        required=True,
    )

    def __init__(self, view: "VCControlPanelView") -> None:
        super().__init__()
        self.panel = view

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        new_name = str(self.name.value).strip()

        if not new_name:
            await interaction.response.send_message(
                "❌ Channel name cannot be empty.",
                ephemeral=True,
            )
            return

        if not _bot_can(channel, "manage_channels"):
            await interaction.response.send_message(
                "❌ I don't have **Manage Channels** permission.",
                ephemeral=True,
            )
            return

        ownership = get_ownership(channel.id)

        if ownership is not None:
            new_name = f"︱{new_name}"

        try:
            old_name = channel.name

            await channel.edit(
                name=new_name,
                reason="Heaven VC Control Panel — rename",
            )

            await interaction.response.send_message(
                f"✏️ Renamed **{old_name}** → **{new_name}**.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to rename this channel.",
                ephemeral=True,
            )

        except discord.HTTPException:
            await interaction.response.send_message(
                "❌ Discord rejected the channel rename.",
                ephemeral=True,
            )


# =====================================================================
# Limit modal
# =====================================================================


class LimitModal(Modal, title="Voice Channel Limit"):

    limit = TextInput(
        label="Member limit",
        placeholder="0 = unlimited, maximum 99",
        min_length=1,
        max_length=2,
        required=True,
    )

    def __init__(self, view: "VCControlPanelView") -> None:
        super().__init__()
        self.panel = view

    async def on_submit(
        self,
        interaction: discord.Interaction,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        try:
            value = int(str(self.limit.value).strip())
        except ValueError:
            await interaction.response.send_message(
                "❌ Enter a valid number between **0 and 99**.",
                ephemeral=True,
            )
            return

        if value < 0 or value > 99:
            await interaction.response.send_message(
                "❌ Limit must be between **0 and 99**.",
                ephemeral=True,
            )
            return

        if not _bot_can(channel, "manage_channels"):
            await interaction.response.send_message(
                "❌ I don't have **Manage Channels** permission.",
                ephemeral=True,
            )
            return

        try:
            await channel.edit(
                user_limit=value,
                reason="Heaven VC Control Panel — user limit",
            )

            display = "Unlimited" if value == 0 else str(value)

            await interaction.response.send_message(
                f"👥 Voice limit set to **{display}**.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I don't have permission to change the limit.",
                ephemeral=True,
            )


# =====================================================================
# Member selector
# =====================================================================


class MemberActionView(View):

    def __init__(
        self,
        panel: "VCControlPanelView",
        action: str,
    ) -> None:
        super().__init__(timeout=60)

        self.panel = panel
        self.action = action

        self.selector = UserSelect(
            placeholder="Select a member...",
            min_values=1,
            max_values=1,
        )

        self.selector.callback = self._selected
        self.add_item(self.selector)

    async def _selected(
        self,
        interaction: discord.Interaction,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        member = self.selector.values[0]

        if not isinstance(member, discord.Member):
            await interaction.response.send_message(
                "❌ Invalid member.",
                ephemeral=True,
            )
            return

        if self.action == "allow":

            try:
                overwrite = channel.overwrites_for(member)
                overwrite.view_channel = True
                overwrite.connect = True

                await channel.set_permissions(
                    member,
                    overwrite=overwrite,
                    reason="Heaven VC Control Panel — allow member",
                )

                await interaction.response.send_message(
                    f"👤 Allowed {member.mention} to access **{channel.name}**.",
                    ephemeral=True,
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I don't have permission to change member access.",
                    ephemeral=True,
                )

            return

        if self.action == "reject":

            try:
                overwrite = channel.overwrites_for(member)
                overwrite.connect = False

                await channel.set_permissions(
                    member,
                    overwrite=overwrite,
                    reason="Heaven VC Control Panel — reject member",
                )

                await interaction.response.send_message(
                    f"🚫 Rejected {member.mention} from **{channel.name}**.",
                    ephemeral=True,
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I don't have permission to change member access.",
                    ephemeral=True,
                )

            return

        if self.action == "kick":

            if not _bot_can(channel, "move_members"):
                await interaction.response.send_message(
                    "❌ I don't have **Move Members** permission.",
                    ephemeral=True,
                )
                return

            if member not in channel.members:
                await interaction.response.send_message(
                    "❌ That member is not in your voice channel.",
                    ephemeral=True,
                )
                return

            try:
                await member.move_to(
                    None,
                    reason="Heaven VC Control Panel — kick",
                )

                await interaction.response.send_message(
                    f"🎙️ Kicked {member.mention} from **{channel.name}**.",
                    ephemeral=True,
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I cannot move that member.",
                    ephemeral=True,
                )

            return

        if self.action == "pull":

            if not _bot_can(channel, "move_members"):
                await interaction.response.send_message(
                    "❌ I don't have **Move Members** permission.",
                    ephemeral=True,
                )
                return

            if member.voice is None:
                await interaction.response.send_message(
                    "❌ That member is not connected to voice.",
                    ephemeral=True,
                )
                return

            try:
                await member.move_to(
                    channel,
                    reason="Heaven VC Control Panel — pull",
                )

                await interaction.response.send_message(
                    f"⬇️ Pulled {member.mention} into **{channel.name}**.",
                    ephemeral=True,
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I cannot move that member.",
                    ephemeral=True,
                )

            return

        if self.action == "mute":

            if not _bot_can(channel, "mute_members"):
                await interaction.response.send_message(
                    "❌ I don't have **Mute Members** permission.",
                    ephemeral=True,
                )
                return

            if member not in channel.members:
                await interaction.response.send_message(
                    "❌ That member is not in your voice channel.",
                    ephemeral=True,
                )
                return

            try:
                # Toggle the Discord server-mute state.
                new_mute_state = not member.voice.mute

                await member.edit(
                    mute=new_mute_state,
                    reason="Heaven VC Control Panel — mute toggle",
                )

                status = "muted" if new_mute_state else "unmuted"

                await interaction.response.send_message(
                    f"🔇 {member.mention} has been **{status}**.",
                    ephemeral=True,
                )

            except discord.Forbidden:
                await interaction.response.send_message(
                    "❌ I cannot mute/unmute that member. Check my role hierarchy and **Mute Members** permission.",
                    ephemeral=True,
                )

            except discord.HTTPException:
                await interaction.response.send_message(
                    "❌ Discord rejected the mute operation.",
                    ephemeral=True,
                )


# =====================================================================
# Target channel selector
# =====================================================================


class MoveChannelView(View):

    def __init__(
        self,
        panel: "VCControlPanelView",
    ) -> None:
        super().__init__(timeout=60)

        self.panel = panel

        self.selector = ChannelSelect(
            placeholder="Select destination voice channel...",
            channel_types=[discord.ChannelType.voice],
            min_values=1,
            max_values=1,
        )

        self.selector.callback = self._selected

        self.add_item(self.selector)

    async def _selected(
        self,
        interaction: discord.Interaction,
    ) -> None:

        source = await _require_control(
            interaction,
            "move_members",
        )

        if source is None:
            return

        target = self.selector.values[0]

        if not isinstance(target, discord.VoiceChannel):
            await interaction.response.send_message(
                "❌ Invalid target channel.",
                ephemeral=True,
            )
            return

        if target.id == source.id:
            await interaction.response.send_message(
                "❌ The target is already your current channel.",
                ephemeral=True,
            )
            return

        me = source.guild.me

        if me is None:
            await interaction.response.send_message(
                "❌ I am not available in this server.",
                ephemeral=True,
            )
            return

        if not me.guild_permissions.move_members:
            await interaction.response.send_message(
                "❌ I don't have **Move Members** permission.",
                ephemeral=True,
            )
            return

        moved = 0
        skipped = 0

        for member in list(source.members):

            if member.id == me.id:
                continue

            try:
                await member.move_to(
                    target,
                    reason="Heaven VC Control Panel — move all",
                )
                moved += 1

            except (discord.Forbidden, discord.HTTPException):
                skipped += 1

        message = (
            f"🔀 Moved **{moved}** member"
            f"{'' if moved == 1 else 's'} to {target.mention}."
        )

        if skipped:
            message += (
                f"\n⚠️ Skipped **{skipped}** member"
                f"{'' if skipped == 1 else 's'}."
            )

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


# =====================================================================
# Main control panel
# =====================================================================


class VCControlPanelView(View):
    """Interactive Heaven VC management panel."""

    def __init__(
        self,
        bot: discord.Client,
    ) -> None:
        super().__init__(timeout=900)
        self.bot = bot

    async def _refresh(
        self,
        interaction: discord.Interaction,
    ) -> None:
        """Refresh the panel message."""

        try:
            channel = _get_control_channel(interaction)

            if channel is None:
                return

            embed = create_control_embed(channel)

            await interaction.message.edit(
                embed=embed,
                view=self,
            )

        except Exception:
            pass

    # -----------------------------------------------------------------
    # Lock
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="LOCK",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def lock(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        if not _bot_can(channel, "manage_channels"):
            await interaction.response.send_message(
                "❌ I don't have **Manage Channels** permission.",
                ephemeral=True,
            )
            return

        try:
            overwrite = channel.overwrites_for(
                channel.guild.default_role
            )

            overwrite.connect = False

            await channel.set_permissions(
                channel.guild.default_role,
                overwrite=overwrite,
                reason="Heaven VC Control Panel — lock",
            )

            await interaction.response.send_message(
                "🔒 Channel locked.",
                ephemeral=True,
            )

            await self._refresh(interaction)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I cannot lock this channel.",
                ephemeral=True,
            )

    # -----------------------------------------------------------------
    # Unlock
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="UNLOCK",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def unlock(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        if not _bot_can(channel, "manage_channels"):
            await interaction.response.send_message(
                "❌ I don't have **Manage Channels** permission.",
                ephemeral=True,
            )
            return

        try:
            overwrite = channel.overwrites_for(
                channel.guild.default_role
            )

            overwrite.connect = None

            await channel.set_permissions(
                channel.guild.default_role,
                overwrite=overwrite,
                reason="Heaven VC Control Panel — unlock",
            )

            await interaction.response.send_message(
                "🔓 Channel unlocked.",
                ephemeral=True,
            )

            await self._refresh(interaction)

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I cannot unlock this channel.",
                ephemeral=True,
            )

    # -----------------------------------------------------------------
    # Hide
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="HIDE",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def hide(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        if not _bot_can(channel, "manage_channels"):
            await interaction.response.send_message(
                "❌ I don't have **Manage Channels** permission.",
                ephemeral=True,
            )
            return

        try:
            overwrite = channel.overwrites_for(
                channel.guild.default_role
            )

            overwrite.view_channel = False

            await channel.set_permissions(
                channel.guild.default_role,
                overwrite=overwrite,
                reason="Heaven VC Control Panel — hide",
            )

            owner = interaction.user

            if isinstance(owner, discord.Member):
                owner_overwrite = channel.overwrites_for(owner)
                owner_overwrite.view_channel = True
                owner_overwrite.connect = True

                await channel.set_permissions(
                    owner,
                    overwrite=owner_overwrite,
                    reason="Heaven VC Control Panel — owner access",
                )

            await interaction.response.send_message(
                "👁️ Channel hidden.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I cannot hide this channel.",
                ephemeral=True,
            )

    # -----------------------------------------------------------------
    # Show
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="SHOW",
        style=discord.ButtonStyle.secondary,
        row=0,
    )
    async def show(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        if not _bot_can(channel, "manage_channels"):
            await interaction.response.send_message(
                "❌ I don't have **Manage Channels** permission.",
                ephemeral=True,
            )
            return

        try:
            overwrite = channel.overwrites_for(
                channel.guild.default_role
            )

            overwrite.view_channel = None

            await channel.set_permissions(
                channel.guild.default_role,
                overwrite=overwrite,
                reason="Heaven VC Control Panel — show",
            )

            await interaction.response.send_message(
                "👁️ Channel visible.",
                ephemeral=True,
            )

        except discord.Forbidden:
            await interaction.response.send_message(
                "❌ I cannot show this channel.",
                ephemeral=True,
            )

    # -----------------------------------------------------------------
    # Allow
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="ALLOW",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def allow(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        await interaction.response.send_message(
            "👤 Select the member you want to allow:",
            view=MemberActionView(self, "allow"),
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # Reject
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="REJECT",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def reject(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        await interaction.response.send_message(
            "🚫 Select the member you want to reject:",
            view=MemberActionView(self, "reject"),
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # Rename
    # -----------------------------------------------------------------

    @discord.ui.button(
    label="RENAME",
    style=discord.ButtonStyle.secondary,
    row=2,
)
    async def rename(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        await interaction.response.send_modal(
            RenameModal(self)
        )

    # -----------------------------------------------------------------
    # Limit
    # -----------------------------------------------------------------

    @discord.ui.button(
    label="LIMIT",
    style=discord.ButtonStyle.secondary,
    row=2,
)
    async def limit(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(interaction)

        if channel is None:
            return

        await interaction.response.send_modal(
            LimitModal(self)
        )

    # -----------------------------------------------------------------
    # Kick
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="KICK",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def kick(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        await interaction.response.send_message(
            "🎙️ Select the member to kick:",
            view=MemberActionView(self, "kick"),
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # Move
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="MOVE",
        style=discord.ButtonStyle.secondary,
        row=1,
    )
    async def move(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        await interaction.response.send_message(
            "🔀 Select the destination voice channel:",
            view=MoveChannelView(self),
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # Pull
    # -----------------------------------------------------------------

    @discord.ui.button(
    label="PULL",
    style=discord.ButtonStyle.secondary,
    row=1,
)
    async def pull(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        await interaction.response.send_message(
            "⬇️ Select the member to pull:",
            view=MemberActionView(self, "pull"),
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # Mute
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="MUTE",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def mute(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        await interaction.response.send_message(
            "🔇 Select the member to mute/unmute:",
            view=MemberActionView(self, "mute"),
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # Kick all
    # -----------------------------------------------------------------

    @discord.ui.button(
    label="KICK ALL",
    style=discord.ButtonStyle.secondary,
    row=2,
)
    async def kick_all(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(
            interaction,
            "move_members",
        )

        if channel is None:
            return

        if not _bot_can(channel, "move_members"):
            await interaction.response.send_message(
                "❌ I don't have **Move Members** permission.",
                ephemeral=True,
            )
            return

        me = channel.guild.me

        if me is None:
            await interaction.response.send_message(
                "❌ I am not available in this server.",
                ephemeral=True,
            )
            return

        kicked = 0
        skipped = 0

        for member in list(channel.members):

            if member.id == me.id:
                continue

            try:
                await member.move_to(
                    None,
                    reason="Heaven VC Control Panel — kick all",
                )
                kicked += 1

            except (discord.Forbidden, discord.HTTPException):
                skipped += 1

        message = (
            f"👥 Kicked **{kicked}** member"
            f"{'' if kicked == 1 else 's'}."
        )

        if skipped:
            message += (
                f"\n⚠️ Skipped **{skipped}** member"
                f"{'' if skipped == 1 else 's'}."
            )

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )

    # -----------------------------------------------------------------
    # Mute all
    # -----------------------------------------------------------------

    @discord.ui.button(
        label="MUTE ALL",
        style=discord.ButtonStyle.secondary,
        row=2,
    )
    async def mute_all(
        self,
        interaction: discord.Interaction,
        button: Button,
    ) -> None:

        channel = await _require_control(
            interaction,
            "mute_members",
        )

        if channel is None:
            return

        if not _bot_can(channel, "mute_members"):
            await interaction.response.send_message(
                "❌ I don't have **Mute Members** permission.",
                ephemeral=True,
            )
            return

        me = channel.guild.me

        if me is None:
            await interaction.response.send_message(
                "❌ I am not available in this server.",
                ephemeral=True,
            )
            return

        muted = 0
        skipped = 0

        for member in list(channel.members):

            if member.id == me.id:
                continue

            if member.voice is None or member.voice.mute:
                continue

            try:
                await member.edit(
                    mute=True,
                    reason="Heaven VC Control Panel — mute all",
                )
                muted += 1

            except (discord.Forbidden, discord.HTTPException):
                skipped += 1

        message = (
            f"🔇 Muted **{muted}** member"
            f"{'' if muted == 1 else 's'}."
        )

        if skipped:
            message += (
                f"\n⚠️ Skipped **{skipped}** member"
                f"{'' if skipped == 1 else 's'}."
            )

        await interaction.response.send_message(
            message,
            ephemeral=True,
        )


# =====================================================================
# Embed
# =====================================================================


def create_control_embed(
    channel: discord.VoiceChannel,
) -> discord.Embed:
    """Create the Heaven voice command console."""

    member_limit = channel.user_limit
    limit_text = "∞" if member_limit == 0 else str(member_limit)

    ownership = get_ownership(channel.id)

    owner_text = (
        f"<@{ownership.owner}>"
        if ownership is not None
        else "Server Controlled"
    )

    default_role = channel.guild.default_role
    overwrite = channel.overwrites_for(default_role)

    locked = overwrite.connect is False
    hidden = overwrite.view_channel is False

    access_text = "LOCKED" if locked else "OPEN"
    visibility_text = "HIDDEN" if hidden else "VISIBLE"

    embed = discord.Embed(
        title="𝐇𝐄𝐀𝐕𝐄𝐍 ・𝐕𝐎𝐈𝐂𝐄 𝐂𝐎𝐍𝐒𝐎𝐋𝐄",
        description=(
            "Private voice management interface\n"
            "Select an operation below to modify this channel."
        ),
        color=discord.Color.from_rgb(42, 42, 48),
    )

    embed.add_field(
        name="CHANNEL",
        value=(
            "```text\n"
            f"NAME       {channel.name}\n"
            f"MEMBERS    {len(channel.members)} / {limit_text}\n"
            f"OWNER      {owner_text}\n"
            "```"
        ),
        inline=False,
    )

    embed.add_field(
        name="ACCESS STATE",
        value=(
            f"`{access_text}`   ·   `{visibility_text}`"
        ),
        inline=True,
    )

    embed.add_field(
        name="CONTROL",
        value="`VOICE / OWNER`",
        inline=True,
    )

    embed.add_field(
        name="ACCESS OPERATIONS",
        value="`LOCK`  `UNLOCK`  `HIDE`  `SHOW`",
        inline=False,
    )

    embed.add_field(
        name="MEMBER OPERATIONS",
        value=(
            "`ALLOW`  `REJECT`  `KICK`  `MOVE`  `PULL`  "
            "`MUTE`  `KICK ALL`  `MUTE ALL`"
        ),
        inline=False,
    )

    embed.add_field(
        name="CHANNEL OPERATIONS",
        value="`RENAME`  `LIMIT`",
        inline=False,
    )

    embed.set_footer(
        text="𝑯𝑬𝑨𝑽𝑬𝑵 𝑺𝒀𝑺𝑻𝑬𝑴𝑺  ・  𝑽𝑶𝑰𝑪𝑬 𝑴𝑨𝑵𝑨𝑮𝑬𝑴𝑬𝑵𝑻"
    )

    return embed
