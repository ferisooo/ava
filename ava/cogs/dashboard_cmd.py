"""/dashboard — share the link to Ava's web control dashboard."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

log = logging.getLogger("ava.dashboard_cmd")


class DashboardCommand(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @app_commands.command(name="dashboard", description="Open Ava's control dashboard.")
    async def dashboard(self, interaction: discord.Interaction) -> None:
        url = self.bot.config.dashboard_url
        if not url:
            await interaction.response.send_message(
                "🚫 The dashboard isn't configured yet — set `DASHBOARD_URL` in the "
                "`.env` to the public address (e.g. `http://your-ip:port`).",
                ephemeral=True,
            )
            return
        embed = discord.Embed(
            title="🌸 Ava · Control Core",
            description="Tap below to open the dashboard.",
            colour=discord.Colour.from_str("#ff1493"),
        )
        view = discord.ui.View()
        view.add_item(discord.ui.Button(label="Open Dashboard", url=url, emoji="🌸"))
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(DashboardCommand(bot))
