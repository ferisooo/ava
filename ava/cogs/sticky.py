"""Sticky messages: keep a message pinned to the bottom of a channel."""

from __future__ import annotations

import asyncio
import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import store

log = logging.getLogger("ava.sticky")


class Sticky(commands.Cog):
    group = app_commands.Group(
        name="sticky", description="Keep a message at the bottom of a channel.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._locks: dict[int, asyncio.Lock] = {}

    def _lock(self, channel_id: int) -> asyncio.Lock:
        return self._locks.setdefault(channel_id, asyncio.Lock())

    async def _repost(self, channel: discord.TextChannel, record: dict) -> None:
        async with self._lock(channel.id):
            # Re-read in case it changed while we waited for the lock.
            record = store.get_sticky(channel.id) or record
            old_id = int(record["last_message_id"])
            if old_id:
                try:
                    old = await channel.fetch_message(old_id)
                    await old.delete()
                except discord.HTTPException:
                    pass
            embed = discord.Embed(
                description=record["content"], colour=discord.Colour.gold()
            )
            embed.set_footer(text="📌 Sticky")
            try:
                sent = await channel.send(embed=embed)
            except discord.HTTPException:
                return
            store.update_sticky_message(channel.id, sent.id)

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.id == self.bot.user.id or message.guild is None:
            return
        record = store.get_sticky(message.channel.id)
        if record is None:
            return
        if isinstance(message.channel, discord.TextChannel):
            await self._repost(message.channel, record)

    @group.command(name="set", description="Set (or replace) the sticky message here.")
    @app_commands.describe(text="The message text to keep at the bottom.")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True)
    async def set_sticky(self, interaction: discord.Interaction, text: str) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("🚫 Use this in a text channel.", ephemeral=True)
            return
        store.set_sticky(channel.id, interaction.guild.id, text[:2000])  # type: ignore[union-attr]
        await interaction.response.send_message("📌 Sticky set.", ephemeral=True)
        await self._repost(channel, store.get_sticky(channel.id))  # type: ignore[arg-type]

    @group.command(name="remove", description="Remove the sticky message from this channel.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def remove(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        assert channel is not None
        record = store.get_sticky(channel.id)
        if record and int(record["last_message_id"]) and isinstance(channel, discord.TextChannel):
            try:
                msg = await channel.fetch_message(int(record["last_message_id"]))
                await msg.delete()
            except discord.HTTPException:
                pass
        ok = store.remove_sticky(channel.id)
        await interaction.response.send_message(
            "🗑️ Sticky removed." if ok else "🚫 No sticky here.", ephemeral=True
        )

    @group.command(name="list", description="List channels with a sticky.")
    @app_commands.checks.has_permissions(manage_messages=True)
    async def list_stickies(self, interaction: discord.Interaction) -> None:
        rows = store.list_stickies(interaction.guild.id)  # type: ignore[union-attr]
        if not rows:
            await interaction.response.send_message("No stickies set.", ephemeral=True)
            return
        await interaction.response.send_message(
            "\n".join(f"<#{r['channel_id']}>: {r['content'][:60]}" for r in rows)[:2000],
            ephemeral=True,
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Sticky(bot))
