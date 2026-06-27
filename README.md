# Ava

A small Discord moderation bot. Its headline feature: **delete all messages from
a specific user** — in one channel or across an entire server.

## Features

- `/purge_user` (slash command) — delete a user's messages in a chosen channel,
  or every text channel the bot can moderate.
- `!purgeuser @user [limit]` (classic command) — delete a user's messages in the
  current channel.
- Handles Discord's quirks for you: bulk-deletes recent messages (faster) and
  falls back to one-by-one deletion for messages older than 14 days, which the
  bulk API refuses.
- Permission-gated: callers need **Manage Messages**, and so does the bot.

## Requirements

- Python 3.10+
- A Discord bot application and token

## Setup

1. Install dependencies:

   ```bash
   pip install -r requirements.txt
   ```

2. Configure your token:

   ```bash
   cp .env.example .env
   # edit .env and set DISCORD_TOKEN
   ```

3. In the [Discord Developer Portal](https://discord.com/developers/applications),
   enable the **Message Content Intent** and **Server Members Intent** for your
   bot, and invite it with the `bot` and `applications.commands` scopes plus the
   **Manage Messages** and **Read Message History** permissions.

4. Run it:

   ```bash
   python bot.py
   ```

## Usage

**Slash command** (recommended):

```
/purge_user user:@SomeUser
/purge_user user:@SomeUser channel:#general
/purge_user user:@SomeUser limit:100
```

Omitting `channel` scans every text channel the bot has permission to moderate.
`limit` caps how many of that user's messages are deleted per channel.

**Classic command** (current channel only):

```
!purgeuser @SomeUser
!purgeuser @SomeUser 50
```

## Notes & caveats

- Deleting a user's entire history in a busy server can take a while because
  Discord rate-limits message deletion (especially for messages older than 14
  days, which must be deleted individually). The slash command runs in the
  background and reports a summary when finished.
- The bot only deletes in channels where it has both **Read Message History**
  and **Manage Messages**.

## Configuration

All configuration is via environment variables (or a `.env` file):

| Variable          | Required | Description                                                       |
| ----------------- | -------- | ----------------------------------------------------------------- |
| `DISCORD_TOKEN`   | yes      | Your bot token.                                                   |
| `COMMAND_PREFIX`  | no       | Prefix for classic commands. Defaults to `!`.                     |
| `DEV_GUILD_IDS`   | no       | Comma-separated guild IDs to sync slash commands to instantly.    |

## Project layout

```
bot.py                  # entry point
ava/
  bot.py                # AvaBot subclass + startup wiring
  config.py             # env/.env configuration
  purge.py              # core message-deletion logic
  cogs/
    moderation.py       # /purge_user and !purgeuser commands
```
