"""Runtime configuration, loaded from environment variables / a .env file."""

from __future__ import annotations

import os
from dataclasses import dataclass, field

from dotenv import load_dotenv


@dataclass(frozen=True)
class Config:
    token: str
    command_prefix: str = "!"
    dev_guild_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from the environment, loading a .env file if present."""
        load_dotenv()

        token = os.getenv("DISCORD_TOKEN", "").strip()
        if not token:
            raise RuntimeError(
                "DISCORD_TOKEN is not set. Copy .env.example to .env and add your "
                "bot token (or export DISCORD_TOKEN)."
            )

        prefix = os.getenv("COMMAND_PREFIX", "!").strip() or "!"

        raw_guilds = os.getenv("DEV_GUILD_IDS", "")
        guild_ids = tuple(
            int(part) for part in raw_guilds.replace(",", " ").split() if part.strip()
        )

        return cls(token=token, command_prefix=prefix, dev_guild_ids=guild_ids)
