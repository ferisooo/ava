"""Reaction roles: react to a message to self-assign a role."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import store

log = logging.getLogger("ava.reactionroles")


class ReactionRoles(commands.Cog):
    group = app_commands.Group(
        name="reactionrole", description="Self-assign roles by reacting.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    @group.command(name="add", description="Link an emoji on a message to a role.")
    @app_commands.describe(
        message_id="ID of the message (in this channel) to add the reaction to.",
        emoji="The emoji members react with.",
        role="The role they get.",
    )
    @app_commands.checks.has_permissions(manage_roles=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True, add_reactions=True)
    async def add(
        self,
        interaction: discord.Interaction,
        message_id: str,
        emoji: str,
        role: discord.Role,
    ) -> None:
        assert interaction.guild is not None
        if role >= interaction.guild.me.top_role:
            await interaction.response.send_message(
                "🚫 That role is above mine — move my role higher.", ephemeral=True
            )
            return
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message("🚫 Use this in a text channel.", ephemeral=True)
            return
        try:
            message = await channel.fetch_message(int(message_id))
        except (ValueError, discord.NotFound):
            await interaction.response.send_message(
                "🚫 Couldn't find that message in this channel.", ephemeral=True
            )
            return
        try:
            await message.add_reaction(emoji)
        except discord.HTTPException:
            await interaction.response.send_message(
                "🚫 I couldn't react with that emoji (custom emoji from other servers won't work).",
                ephemeral=True,
            )
            return
        store.add_reaction_role(interaction.guild.id, message.id, emoji, role.id)
        await interaction.response.send_message(
            f"✅ Reacting with {emoji} on that message now gives {role.mention}.",
            ephemeral=True,
        )

    @group.command(name="remove", description="Unlink an emoji from its role.")
    @app_commands.describe(message_id="The message ID.", emoji="The emoji to unlink.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def remove(self, interaction: discord.Interaction, message_id: str, emoji: str) -> None:
        try:
            mid = int(message_id)
        except ValueError:
            await interaction.response.send_message("🚫 Invalid message ID.", ephemeral=True)
            return
        ok = store.remove_reaction_role(mid, emoji)
        await interaction.response.send_message(
            "✅ Unlinked." if ok else "🚫 No such reaction role.", ephemeral=True
        )

    @group.command(name="list", description="List this server's reaction roles.")
    @app_commands.checks.has_permissions(manage_roles=True)
    async def list_roles(self, interaction: discord.Interaction) -> None:
        assert interaction.guild is not None
        rows = store.list_reaction_roles(interaction.guild.id)
        if not rows:
            await interaction.response.send_message("No reaction roles set up.", ephemeral=True)
            return
        lines = [f"{r['emoji']} → <@&{r['role_id']}> (msg `{r['message_id']}`)" for r in rows]
        await interaction.response.send_message("\n".join(lines)[:2000], ephemeral=True)

    @commands.Cog.listener()
    async def on_raw_reaction_add(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None or payload.member is None or payload.member.bot:
            return
        role_id = store.get_reaction_role(payload.message_id, str(payload.emoji))
        if role_id is None:
            return
        role = payload.member.guild.get_role(role_id)
        if role is not None:
            try:
                await payload.member.add_roles(role, reason="Reaction role")
            except discord.HTTPException:
                pass

    @commands.Cog.listener()
    async def on_raw_reaction_remove(self, payload: discord.RawReactionActionEvent) -> None:
        if payload.guild_id is None:
            return
        role_id = store.get_reaction_role(payload.message_id, str(payload.emoji))
        if role_id is None:
            return
        guild = self.bot.get_guild(payload.guild_id)
        if guild is None:
            return
        member = guild.get_member(payload.user_id)
        role = guild.get_role(role_id)
        if member and role:
            try:
                await member.remove_roles(role, reason="Reaction role removed")
            except discord.HTTPException:
                pass


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(ReactionRoles(bot))
