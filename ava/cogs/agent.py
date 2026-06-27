"""Listen for @mentions and act on natural-language requests via the agent."""

from __future__ import annotations

import logging

import discord
from discord.ext import commands

from ..agent import AgentError, run_agent

log = logging.getLogger("ava.agent.cog")


class Agent(commands.Cog):
    """Talk to Ava in plain English; she performs the matching server action."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Guild IDs with an agent run in progress, so requests don't overlap.
        self._busy: set[int] = set()

    def _strip_mention(self, message: discord.Message) -> str:
        content = message.content
        for token in (f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"):
            content = content.replace(token, " ")
        return content.strip()

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None or self.bot.user is None:
            return
        if self.bot.user not in message.mentions:
            return

        if not self.bot.config.deepseek_api_key:
            await message.reply(
                "🚫 DeepSeek isn't configured — add `DEEPSEEK_API_KEY` to the `.env`.",
                mention_author=False,
            )
            return

        perms = message.author.guild_permissions
        if not (perms.administrator or perms.manage_guild):
            await message.reply(
                "🚫 You need the **Manage Server** permission to ask me to change things.",
                mention_author=False,
            )
            return

        request = self._strip_mention(message)
        if not request:
            await message.reply(
                "Tell me what to do, e.g. `@Ava add a 🎮 emoji to #general` or "
                "`@Ava make a voice channel called Lounge`.",
                mention_author=False,
            )
            return

        if message.guild.id in self._busy:
            await message.reply(
                "⏳ I'm still working on your last request — give me a moment.",
                mention_author=False,
            )
            return

        cfg = self.bot.config
        self._busy.add(message.guild.id)
        try:
            async with message.channel.typing():
                reply = await run_agent(
                    message.guild,
                    request,
                    api_key=cfg.deepseek_api_key,
                    model=cfg.deepseek_agent_model,
                    base_url=cfg.deepseek_base_url,
                )
        except AgentError as exc:
            reply = f"❌ {exc}"
        except Exception:  # noqa: BLE001 - surface anything else cleanly
            log.exception("agent run failed")
            reply = "❌ Something went wrong handling that."
        finally:
            self._busy.discard(message.guild.id)

        await message.reply(reply[:2000], mention_author=False)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Agent(bot))
