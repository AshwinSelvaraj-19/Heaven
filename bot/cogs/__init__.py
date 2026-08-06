"""Cog registry — imports all cog modules so they register with the bot."""

from .settings_cog import SettingsCog
from .voice_listener_cog import VoiceListenerCog

__all__ = ["SettingsCog", "VoiceListenerCog"]
