"""Runtime configuration, loaded from environment variables / a .env file.

We parse the .env file ourselves with a tiny loader so the bot has no
third-party dependency just for configuration (some hosts only auto-install
discord.py and not python-dotenv).
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _load_env_file(path: str = ".env") -> None:
    """Load KEY=VALUE pairs from a .env file into os.environ (if present).

    Existing environment variables win, so a value set in the hosting panel
    overrides the file.
    """
    env_path = Path(path)
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            os.environ.setdefault(key, value)


@dataclass(frozen=True)
class Config:
    token: str
    command_prefix: str = "!"
    dev_guild_ids: tuple[int, ...] = field(default_factory=tuple)

    @classmethod
    def from_env(cls) -> "Config":
        """Build a Config from the environment, loading a .env file if present."""
        _load_env_file()

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
