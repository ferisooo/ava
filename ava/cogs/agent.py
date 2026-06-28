"""Listen for @mentions and act on natural-language requests via the agent."""

from __future__ import annotations

import logging
import re

import discord
from discord.ext import commands

from ..agent import AgentError, run_agent

log = logging.getLogger("ava.agent.cog")


class Agent(commands.Cog):
    """Talk to Ava in plain English; she performs the matching server action."""

    # Keep the last few exchanges per channel so follow-ups like "yes" keep
    # their context. (text only — tool calls aren't replayed.)
    HISTORY_TURNS = 6

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        # Guild IDs with an agent run in progress, so requests don't overlap.
        self._busy: set[int] = set()
        # channel id -> recent [{role, content}] turns.
        self._history: dict[int, list[dict[str, str]]] = {}

    def _strip_mention(self, message: discord.Message) -> str:
        content = message.content
        for token in (f"<@{self.bot.user.id}>", f"<@!{self.bot.user.id}>"):
            content = content.replace(token, " ")
        return self._humanize(message.guild, content).strip()

    def _humanize(self, guild: discord.Guild, text: str) -> str:
        """Turn raw mentions (<#id>, <@&id>, <@id>) into readable names so the
        model understands which channel/role/member the user meant."""

        def channel(m: re.Match) -> str:
            ch = guild.get_channel(int(m.group(1)))
            return f"#{ch.name}" if ch else m.group(0)

        def role(m: re.Match) -> str:
            r = guild.get_role(int(m.group(1)))
            return f"@{r.name}" if r else m.group(0)

        def member(m: re.Match) -> str:
            mem = guild.get_member(int(m.group(1)))
            return f"@{mem.display_name}" if mem else m.group(0)

        text = re.sub(r"<#(\d+)>", channel, text)
        text = re.sub(r"<@&(\d+)>", role, text)
        text = re.sub(r"<@!?(\d+)>", member, text)
        return text

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
        history = self._history.get(message.channel.id, [])
        self._busy.add(message.guild.id)
        try:
            async with message.channel.typing():
                reply = await run_agent(
                    message.guild,
                    request,
                    api_key=cfg.deepseek_api_key,
                    model=cfg.deepseek_agent_model,
                    base_url=cfg.deepseek_base_url,
                    history=history,
                )
        except AgentError as exc:
            reply = f"❌ {exc}"
        except Exception:  # noqa: BLE001 - surface anything else cleanly
            log.exception("agent run failed")
            reply = "❌ Something went wrong handling that."
        finally:
            self._busy.discard(message.guild.id)

        self._remember(message.channel.id, request, reply)
        await message.reply(reply[:2000], mention_author=False)

    def _remember(self, channel_id: int, request: str, reply: str) -> None:
        turns = self._history.setdefault(channel_id, [])
        turns.append({"role": "user", "content": request})
        turns.append({"role": "assistant", "content": reply})
        # Keep only the most recent N turns to bound context and memory.
        del turns[: -self.HISTORY_TURNS]


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Agent(bot))
