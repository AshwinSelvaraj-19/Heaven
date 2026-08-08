"""Cog registry — imports all cog modules so they register with the bot."""

from .settings_cog import SettingsCog
from .voice_listener_cog import VoiceListenerCog
from .vc_commands_cog import VcCommandsCog

__all__ = ["SettingsCog", "VoiceListenerCog", "VcCommandsCog"]
