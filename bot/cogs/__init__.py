"""Cog registry — imports all cog modules so they register with the bot."""

from .create_commands_cog import CreateCommandsCog
from .settings_cog import SettingsCog
from .voice_listener_cog import VoiceListenerCog
from .vc_commands_cog import VcCommandsCog
from .help_cog import HelpCog

__all__ = ["CreateCommandsCog", "SettingsCog", "VoiceListenerCog", "VcCommandsCog", "HelpCog"]
