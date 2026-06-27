"""The Ava bot subclass and its startup wiring."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from .config import Config

log = logging.getLogger("ava")


def _intents() -> discord.Intents:
    intents = discord.Intents.default()
    # Required to read message content for classic prefix commands and to be
    # able to fetch/inspect message history authors reliably.
    intents.message_content = True
    intents.members = True
    return intents


class AvaBot(commands.Bot):
    def __init__(self, config: Config) -> None:
        super().__init__(
            command_prefix=commands.when_mentioned_or(config.command_prefix),
            intents=_intents(),
            help_command=commands.DefaultHelpCommand(),
            description="Ava — a small moderation bot.",
        )
        self.config = config

    async def setup_hook(self) -> None:
        # Load extensions (cogs).
        await self.load_extension("ava.cogs.moderation")

        # Sync application (slash) commands. Syncing to specific guilds is
        # instant and ideal for development; a global sync can take up to an
        # hour to propagate.
        if self.config.dev_guild_ids:
            for guild_id in self.config.dev_guild_ids:
                guild = discord.Object(id=guild_id)
                self.tree.copy_global_to(guild=guild)
                await self.tree.sync(guild=guild)
                log.info("Synced slash commands to guild %s", guild_id)
        else:
            await self.tree.sync()
            log.info("Synced slash commands globally")

    async def on_ready(self) -> None:
        assert self.user is not None
        log.info("Logged in as %s (id=%s)", self.user, self.user.id)


def run(config: Config | None = None) -> None:
    """Entry point: build the bot from config and run it."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
    )
    config = config or Config.from_env()
    bot = AvaBot(config)
    bot.run(config.token, log_handler=None)
