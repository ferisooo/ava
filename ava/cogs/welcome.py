"""Custom welcome embeds for new members."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .. import store

log = logging.getLogger("ava.welcome")


def _render(text: str, member: discord.Member) -> str:
    return (
        text.replace("{user}", member.mention)
        .replace("{username}", member.display_name)
        .replace("{server}", member.guild.name)
        .replace("{count}", str(member.guild.member_count))
    )


def _build_embed(cfg: dict, member: discord.Member) -> discord.Embed:
    embed = discord.Embed(
        title=_render(cfg["title"], member),
        description=_render(cfg["description"], member),
        colour=discord.Colour(int(cfg["color"])),
    )
    embed.set_thumbnail(url=member.display_avatar.url)
    if cfg["image_url"]:
        embed.set_image(url=cfg["image_url"])
    return embed


class Welcome(commands.Cog):
    group = app_commands.Group(
        name="welcome", description="Welcome-message settings.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        cfg = store.get_welcome(member.guild.id)
        if not cfg["enabled"] or not cfg["channel_id"]:
            return
        channel = member.guild.get_channel(int(cfg["channel_id"]))
        if isinstance(channel, discord.TextChannel):
            try:
                await channel.send(embed=_build_embed(cfg, member))
            except discord.HTTPException:
                pass

    @group.command(name="channel", description="Set the welcome channel and turn welcomes on.")
    @app_commands.describe(channel="Where to post welcomes.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def channel(self, interaction: discord.Interaction, channel: discord.TextChannel) -> None:
        store.set_welcome(interaction.guild.id, channel_id=channel.id, enabled=1)  # type: ignore[union-attr]
        await interaction.response.send_message(
            f"✅ Welcomes will post in {channel.mention}.", ephemeral=True
        )

    @group.command(name="set", description="Customize the welcome embed.")
    @app_commands.describe(
        title="Embed title. Placeholders: {user} {username} {server} {count}.",
        description="Embed body. Same placeholders.",
        color="Hex color like #5865F2.",
        image_url="Optional banner image URL ('none' to clear).",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def set_embed(
        self,
        interaction: discord.Interaction,
        title: Optional[str] = None,
        description: Optional[str] = None,
        color: Optional[str] = None,
        image_url: Optional[str] = None,
    ) -> None:
        fields: dict = {}
        if title is not None:
            fields["title"] = title[:256]
        if description is not None:
            fields["description"] = description[:2000]
        if color is not None:
            try:
                fields["color"] = discord.Colour.from_str(color).value
            except ValueError:
                await interaction.response.send_message("🚫 Invalid hex color.", ephemeral=True)
                return
        if image_url is not None:
            fields["image_url"] = "" if image_url.lower() == "none" else image_url
        store.set_welcome(interaction.guild.id, **fields)  # type: ignore[union-attr]
        await interaction.response.send_message(
            "✅ Welcome embed updated. Use `/welcome test` to preview.", ephemeral=True
        )

    @group.command(name="test", description="Preview the welcome message for yourself.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def test(self, interaction: discord.Interaction) -> None:
        cfg = store.get_welcome(interaction.guild.id)  # type: ignore[union-attr]
        assert isinstance(interaction.user, discord.Member)
        await interaction.response.send_message(
            embed=_build_embed(cfg, interaction.user), ephemeral=True
        )

    @group.command(name="disable", description="Turn welcome messages off.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction) -> None:
        store.set_welcome(interaction.guild.id, enabled=0)  # type: ignore[union-attr]
        await interaction.response.send_message("🛑 Welcomes disabled.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Welcome(bot))
