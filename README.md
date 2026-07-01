# Ava — Discord Bot

An all-in-one Discord bot: moderation, automod, reaction roles, welcome messages, temp voice channels, sticky messages, a diary, an AI server-builder, and an optional web dashboard.

## Quick start

```bash
pip install -r requirements.txt
cp .env.example .env      # add your DISCORD_TOKEN
python bot.py
```

## Config

Set these in `.env` (see `.env.example` for the full list):

| Variable | Required | Purpose |
|----------|----------|---------|
| `DISCORD_TOKEN` | ✅ | Bot token from the [Discord dev portal](https://discord.com/developers/applications) |
| `DEV_GUILD_IDS` | — | Comma-separated server IDs for instant slash-command sync |
| `DEEPSEEK_API_KEY` | — | Enables AI features (`/build_server`, natural-language agent) |
| `DASHBOARD_PORT` / `DASHBOARD_KEY` | — | Serve + secure the web dashboard |

## Features

Moderation · AutoMod · Reaction roles · Welcome · Temp voice · Sticky messages · Diary · Security · AI server builder · Web dashboard

## License

See repo for details.
