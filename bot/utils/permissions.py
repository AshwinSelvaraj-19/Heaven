"""Permission helpers for gating commands to server admins/owners."""

from __future__ import annotations

from enum import Enum

import discord

from bot.utils.ownership import get_ownership


class PermissionLevel(Enum):
    """Permission levels for VC commands."""
    OWNER = "owner"  # Temp VC owner
    ADMIN = "admin"  # Server owner or Administrator permission
    MOD = "mod"  # Specific moderation permissions
    NONE = "none"  # No permission


def is_admin(member: discord.Member) -> bool:
    """Return True if the member is the guild owner or has administrator permission."""
    if member.guild.owner_id == member.id:
        return True
    return member.guild_permissions.administrator


def can_control_voice_channel(
    member: discord.Member,
    channel: discord.VoiceChannel,
    required_permission: str | None = None,
) -> tuple[bool, PermissionLevel]:
    """Determine if a member can control a voice channel.

    Permission model:
    1. Server owner → allow
    2. Administrator → allow
    3. If channel is a temporary Heaven VC and member is its owner → allow
    4. If member has the required moderation permission → allow
    5. Otherwise deny

    Parameters
    ----------
    member:
        The member attempting to control the channel.
    channel:
        The voice channel being controlled.
    required_permission:
        Optional specific permission to check (e.g., "mute_members", "move_members").
        If None, only checks admin/owner status.

    Returns
    -------
    tuple[bool, PermissionLevel]
        (has_permission, permission_level)
    """
    # 1. Server owner
    if member.guild.owner_id == member.id:
        return True, PermissionLevel.ADMIN

    # 2. Administrator permission
    if member.guild_permissions.administrator:
        return True, PermissionLevel.ADMIN

    # 3. Temporary VC owner
    ownership = get_ownership(channel.id)
    if ownership is not None and ownership.owner == member.id:
        return True, PermissionLevel.OWNER

    # 4. Specific moderation permission
    if required_permission is not None:
        if hasattr(member.guild_permissions, required_permission):
            if getattr(member.guild_permissions, required_permission):
                return True, PermissionLevel.MOD

    # 5. No permission
    return False, PermissionLevel.NONE
