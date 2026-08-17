# Discord VC Control Bot

A Discord bot (discord.py 2.x) that lets server admins configure temporary voice channels. Users join a designated lobby channel and the bot creates a private voice channel for them under a configured category, applies a user limit and bitrate, and deletes the channel automatically once it's been empty for a configurable duration.

Has Live Channel status feature
## Features
         
- **Slash commands only** — no text commands.
- `/settings vc category <voice_channel>` — sets the category temp channels are created in.
- `/settings vc lobby <voice_channel>` — sets the lobby channel that triggers temp channel creation.
- `/settings vc limit <integer>` — sets the max users (0–99, 0 = unlimited).
- `/settings vc bitrate <integer>` — sets the bitrate in kbps (8–384).
- `/settings vc autodelete <integer>` — sets the delay in seconds before an empty temp channel is deleted (0–3600).
- **Admin-only** — only server administrators/owners can change settings.
- **Auto lifecycle** — temp channels are created on lobby join and deleted after being empty for the configured duration.

## Setup
      
### 1. Create your bot

1. Go to the [Discord Developer Portal](https://discord.com/developers/applications) and create a new application.
2. Under **Bot**, create a bot user and copy the **token**.
3. Enable the **Server Members Intent** and **Voice States Intent** under Privileged Gateway Intents.
4. Invite the bot to your server with the `applications.commands` and `bot` scopes plus permissions: `Manage Channels`, `Move Members`, `View Channels`, `Connect`.

### 2. Install dependencies

```bash
pip install -r requirements.txt
```

### 3. Configure

Copy `.env.example` to `.env` and fill in your bot token:

```
DISCORD_TOKEN=your_discord_bot_token_here
```

### 4. Run

```bash
python main.py
```

## Usage

1. As an admin, run `/settings vc category` and pass a voice channel that lives inside the category you want temp channels created in.
2. Run `/settings vc lobby` and pass the voice channel users should join to trigger creation.
3. Optionally set `/settings vc limit`, `/settings vc bitrate`, and `/settings vc autodelete`.
4. Users join the lobby — the bot creates a temp channel, moves them in, and cleans it up when empty.

## Project Structure

```
.
├── bot/
│   ├── __init__.py
│   ├── config.py              # Environment + default configuration
│   ├── main.py                # Bot entry point, loads cogs, starts bot
│   ├── settings_store.py      # In-memory settings store (swappable for a DB)
│   ├── cogs/
│   │   ├── __init__.py
│   │   ├── settings_cog.py    # /settings vc slash command group
│   │   └── voice_listener_cog.py  # on_voice_state_update listener
│   └── utils/
│       ├── __init__.py
│       ├── permissions.py     # Admin/owner check
│       └── temp_channels.py   # Temp channel create / move / delete logic
├── main.py                    # Convenience entry point
├── requirements.txt
├── .env.example
└── readme.md
```

## Architecture Notes

- **No external storage** — all settings live in an in-memory dictionary keyed by guild ID. The `settings_store.py` module is the only place that knows how settings are persisted, so swapping to a database later means changing that single file — command interfaces stay identical.
- **Modular cogs** — settings commands and the voice listener are separate cogs.
- **Slash commands only** — uses `app_commands.Group` and `app_commands.Range` for input validation.
