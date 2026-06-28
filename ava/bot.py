"""The Ava bot subclass and its startup wiring."""

from __future__ import annotations

import logging
import os

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
            # Plain prefix only — mentions are reserved for the natural-language
            # agent (see ava/cogs/agent.py), not treated as command prefixes.
            command_prefix=config.command_prefix,
            intents=_intents(),
            # If an action hits a rate limit that would require waiting longer
            # than this, raise instead of blocking. Channel/category renames are
            # limited to ~2 per 10 min, which would otherwise hang the bot.
            max_ratelimit_timeout=60.0,
            help_command=commands.DefaultHelpCommand(),
            description="Ava — a small moderation bot.",
        )
        self.config = config

    async def setup_hook(self) -> None:
        # Load extensions (cogs).
        await self.load_extension("ava.cogs.moderation")
        await self.load_extension("ava.cogs.automod")
        await self.load_extension("ava.cogs.security")
        await self.load_extension("ava.cogs.reactionroles")
        await self.load_extension("ava.cogs.welcome")
        await self.load_extension("ava.cogs.sticky")
        await self.load_extension("ava.cogs.tempvoice")
        await self.load_extension("ava.cogs.diary")
        await self.load_extension("ava.cogs.builder")
        await self.load_extension("ava.cogs.agent")
        await self.load_extension("ava.cogs.dashboard_cmd")

        # Optional web dashboard (opt-in via DASHBOARD_PORT).
        port = int(os.getenv("DASHBOARD_PORT", "0") or 0)
        if port:
            from .dashboard import start as start_dashboard

            self._dashboard_runner = await start_dashboard(port)

    async def _sync_commands(self) -> None:
        """Instant per-guild sync so new commands appear immediately on restart.

        Copies the global commands into each guild Ava is in, clears the global
        set (so old global copies don't linger as duplicates), then syncs each
        guild — guild commands update instantly, unlike global ones.
        """
        guilds = self.guilds
        if not guilds:
            await self.tree.sync()
            log.info("Synced commands globally (not in any guild yet)")
            return
        for guild in guilds:
            self.tree.copy_global_to(guild=guild)
        self.tree.clear_commands(guild=None)
        await self.tree.sync()  # remove any stale global commands
        for guild in guilds:
            await self.tree.sync(guild=guild)
        log.info("Instantly synced commands to %d guild(s)", len(guilds))

    async def on_ready(self) -> None:
        assert self.user is not None
        if not getattr(self, "_synced", False):
            self._synced = True
            try:
                await self._sync_commands()
            except discord.HTTPException:
                log.exception("Command sync failed")
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
