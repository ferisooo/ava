"""Temporary voice channels: join a hub to spawn your own lockable channel."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .. import store

log = logging.getLogger("ava.tempvoice")


class TempVoice(commands.Cog):
    hub_group = app_commands.Group(
        name="tempvoice", description="Set up join-to-create voice hubs.", guild_only=True
    )
    voice_group = app_commands.Group(
        name="voice", description="Control your temporary voice channel.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        store.init()

    # ------------------------------------------------------------------ #
    # Create on join / clean up on empty
    # ------------------------------------------------------------------ #
    @commands.Cog.listener()
    async def on_voice_state_update(
        self,
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        # Joined a hub → spin up a personal channel.
        if after.channel is not None and store.get_voice_hub(after.channel.id):
            await self._create_for(member, after.channel)

        # Left a temp channel that's now empty → delete it.
        if before.channel is not None and store.get_temp_voice(before.channel.id):
            if len(before.channel.members) == 0:
                try:
                    await before.channel.delete(reason="Temp voice empty")
                except discord.HTTPException:
                    pass
                store.remove_temp_voice(before.channel.id)

    async def _create_for(self, member: discord.Member, hub: discord.VoiceChannel) -> None:
        hub_cfg = store.get_voice_hub(hub.id)
        guild = member.guild
        category = guild.get_channel(int(hub_cfg["category_id"])) if hub_cfg["category_id"] else hub.category
        overwrites = {
            member: discord.PermissionOverwrite(
                manage_channels=True, move_members=True, connect=True
            )
        }
        try:
            channel = await guild.create_voice_channel(
                name=f"{member.display_name}'s channel"[:100],
                category=category if isinstance(category, discord.CategoryChannel) else None,
                overwrites=overwrites,
                reason="Temp voice",
            )
            await member.move_to(channel)
        except discord.HTTPException:
            return
        store.add_temp_voice(channel.id, guild.id, member.id)

    # ------------------------------------------------------------------ #
    # Hub admin
    # ------------------------------------------------------------------ #
    @hub_group.command(name="sethub", description="Make a voice channel a join-to-create hub.")
    @app_commands.describe(
        channel="The voice channel members join to get their own.",
        category="Optional category to create the temp channels in.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True, move_members=True)
    async def sethub(
        self,
        interaction: discord.Interaction,
        channel: discord.VoiceChannel,
        category: Optional[discord.CategoryChannel] = None,
    ) -> None:
        store.add_voice_hub(channel.id, interaction.guild.id, category.id if category else 0)  # type: ignore[union-attr]
        await interaction.response.send_message(
            f"✅ {channel.mention} is now a join-to-create hub.", ephemeral=True
        )

    @hub_group.command(name="removehub", description="Stop a channel from being a hub.")
    @app_commands.describe(channel="The hub voice channel.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def removehub(self, interaction: discord.Interaction, channel: discord.VoiceChannel) -> None:
        ok = store.remove_voice_hub(channel.id)
        await interaction.response.send_message(
            "✅ Removed." if ok else "🚫 That isn't a hub.", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # Owner controls
    # ------------------------------------------------------------------ #
    async def _owned_channel(
        self, interaction: discord.Interaction
    ) -> Optional[discord.VoiceChannel]:
        member = interaction.user
        if not isinstance(member, discord.Member) or member.voice is None or member.voice.channel is None:
            await interaction.response.send_message(
                "🚫 Join your temp voice channel first.", ephemeral=True
            )
            return None
        channel = member.voice.channel
        record = store.get_temp_voice(channel.id)
        if record is None:
            await interaction.response.send_message(
                "🚫 This isn't a temporary voice channel.", ephemeral=True
            )
            return None
        if record["owner_id"] != member.id and not member.guild_permissions.manage_channels:
            await interaction.response.send_message(
                "🚫 Only the channel's owner can do that.", ephemeral=True
            )
            return None
        return channel if isinstance(channel, discord.VoiceChannel) else None

    @voice_group.command(name="lock", description="Lock your temp channel (no one new can join).")
    async def lock(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel(interaction)
        if channel is None:
            return
        await channel.set_permissions(interaction.guild.default_role, connect=False)  # type: ignore[union-attr]
        await interaction.response.send_message("🔒 Channel locked.", ephemeral=True)

    @voice_group.command(name="unlock", description="Unlock your temp channel.")
    async def unlock(self, interaction: discord.Interaction) -> None:
        channel = await self._owned_channel(interaction)
        if channel is None:
            return
        await channel.set_permissions(interaction.guild.default_role, connect=None)  # type: ignore[union-attr]
        await interaction.response.send_message("🔓 Channel unlocked.", ephemeral=True)

    @voice_group.command(name="limit", description="Set a user limit on your temp channel.")
    @app_commands.describe(limit="Max users (0 = unlimited).")
    async def limit(self, interaction: discord.Interaction, limit: app_commands.Range[int, 0, 99]) -> None:
        channel = await self._owned_channel(interaction)
        if channel is None:
            return
        await channel.edit(user_limit=limit)
        await interaction.response.send_message(
            f"👥 Limit set to {limit or 'unlimited'}.", ephemeral=True
        )

    @voice_group.command(name="rename", description="Rename your temp channel.")
    @app_commands.describe(name="New channel name.")
    async def rename(self, interaction: discord.Interaction, name: str) -> None:
        channel = await self._owned_channel(interaction)
        if channel is None:
            return
        await channel.edit(name=name[:100])
        await interaction.response.send_message("✏️ Renamed.", ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(TempVoice(bot))
