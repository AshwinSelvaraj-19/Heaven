"""Permission helpers for gating commands to server admins/owners."""

from __future__ import annotations

import discord


def is_admin(member: discord.Member) -> bool:
    """Return True if the member is the guild owner or has administrator permission."""
    if member.guild.owner_id == member.id:
        return True
    return member.guild_permissions.administrator
