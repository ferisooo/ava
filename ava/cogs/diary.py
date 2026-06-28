"""Personal diary: private per-user journal entries."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import store

log = logging.getLogger("ava.diary")


class Diary(commands.Cog):
    group = app_commands.Group(name="diary", description="Your private diary.")

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @group.command(name="write", description="Add a private diary entry.")
    @app_commands.describe(entry="What's on your mind?")
    async def write(self, interaction: discord.Interaction, entry: str) -> None:
        entry_id = store.add_diary(interaction.user.id, entry[:2000])
        await interaction.response.send_message(
            f"📓 Saved entry **#{entry_id}**. Only you can see your diary.", ephemeral=True
        )

    @group.command(name="list", description="List your diary entries.")
    async def list_entries(self, interaction: discord.Interaction) -> None:
        entries = store.list_diary(interaction.user.id)
        if not entries:
            await interaction.response.send_message(
                "Your diary is empty. Use `/diary write`.", ephemeral=True
            )
            return
        lines = [
            f"`#{e['id']}` · {e['created_at'][:10]} · {e['content'][:60]}"
            for e in entries[:20]
        ]
        embed = discord.Embed(
            title="📓 Your diary", description="\n".join(lines), colour=discord.Colour.purple()
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="read", description="Read one of your diary entries in full.")
    @app_commands.describe(entry_id="The entry number from /diary list.")
    async def read(self, interaction: discord.Interaction, entry_id: int) -> None:
        entry = store.get_diary(interaction.user.id, entry_id)
        if entry is None:
            await interaction.response.send_message("🚫 No such entry.", ephemeral=True)
            return
        embed = discord.Embed(
            title=f"📓 Entry #{entry['id']}",
            description=entry["content"],
            colour=discord.Colour.purple(),
        )
        embed.set_footer(text=entry["created_at"])
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @group.command(name="delete", description="Delete one of your diary entries.")
    @app_commands.describe(entry_id="The entry number to delete.")
    async def delete(self, interaction: discord.Interaction, entry_id: int) -> None:
        ok = store.delete_diary(interaction.user.id, entry_id)
        await interaction.response.send_message(
            "🗑️ Deleted." if ok else "🚫 No such entry.", ephemeral=True
        )


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Diary(bot))
