"""Moderation commands, including deleting all messages from a user."""

from __future__ import annotations

import logging
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from ..purge import PurgeSummary, purge_user_in_channel, purge_user_in_guild

log = logging.getLogger("ava.moderation")


def _summary_lines(summary: PurgeSummary) -> str:
    parts = [
        f"Deleted **{summary.total_deleted}** message(s) "
        f"across **{summary.channels_touched}** channel(s)."
    ]
    if summary.total_failed:
        parts.append(f"⚠️ Failed to delete {summary.total_failed} message(s).")
    return "\n".join(parts)


class Moderation(commands.Cog):
    """Commands for cleaning up after a user."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    # ------------------------------------------------------------------ #
    # Slash command
    # ------------------------------------------------------------------ #
    @app_commands.command(
        name="purge_user",
        description="Delete messages from a specific user.",
    )
    @app_commands.describe(
        user="The user whose messages should be deleted.",
        channel="Limit deletion to this channel. Omit to scan every text channel.",
        limit="Max messages to delete per channel. Omit to delete all.",
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge_user(
        self,
        interaction: discord.Interaction,
        user: discord.User,
        channel: Optional[discord.TextChannel] = None,
        limit: Optional[app_commands.Range[int, 1, 10000]] = None,
    ) -> None:
        assert interaction.guild is not None

        # This can take a while; defer so we don't hit the 3s response window.
        await interaction.response.defer(ephemeral=True, thinking=True)

        if channel is not None:
            result = await purge_user_in_channel(channel, user, limit=limit)
            summary = PurgeSummary(user_id=user.id, results=[result])
        else:
            channels = _purgeable_channels(interaction.guild, interaction.client.user)
            summary = await purge_user_in_guild(channels, user, limit_per_channel=limit)

        log.info(
            "purge_user by %s targeting %s: deleted=%d failed=%d",
            interaction.user,
            user,
            summary.total_deleted,
            summary.total_failed,
        )
        await interaction.followup.send(
            f"🧹 Purge of {user.mention} complete.\n{_summary_lines(summary)}",
            ephemeral=True,
        )

    @purge_user.error
    async def purge_user_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        message = _friendly_error(error)
        if interaction.response.is_done():
            await interaction.followup.send(message, ephemeral=True)
        else:
            await interaction.response.send_message(message, ephemeral=True)

    # ------------------------------------------------------------------ #
    # Classic prefix command (e.g. "!purgeuser @user 50")
    # ------------------------------------------------------------------ #
    @commands.command(name="purgeuser", aliases=["purge_user"])
    @commands.guild_only()
    @commands.has_permissions(manage_messages=True)
    @commands.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purgeuser_prefix(
        self,
        ctx: commands.Context,
        user: discord.User,
        limit: Optional[int] = None,
    ) -> None:
        """Delete messages from a user in the current channel.

        Usage: ``!purgeuser @user [limit]``
        """
        assert isinstance(ctx.channel, (discord.TextChannel, discord.Thread))
        async with ctx.typing():
            result = await purge_user_in_channel(ctx.channel, user, limit=limit)
        summary = PurgeSummary(user_id=user.id, results=[result])
        log.info(
            "purgeuser by %s targeting %s in #%s: deleted=%d failed=%d",
            ctx.author,
            user,
            getattr(ctx.channel, "name", ctx.channel.id),
            summary.total_deleted,
            summary.total_failed,
        )
        await ctx.send(f"🧹 {_summary_lines(summary)}", delete_after=15)

    @purgeuser_prefix.error
    async def purgeuser_prefix_error(
        self, ctx: commands.Context, error: commands.CommandError
    ) -> None:
        await ctx.send(_friendly_error(error), delete_after=15)


def _purgeable_channels(
    guild: discord.Guild, me: Optional[discord.abc.Snowflake]
) -> list[discord.abc.Messageable]:
    """Text channels (and their threads) the bot can read and delete in."""
    member = guild.me
    channels: list[discord.abc.Messageable] = []
    for channel in guild.text_channels:
        perms = channel.permissions_for(member)
        if perms.read_message_history and perms.manage_messages:
            channels.append(channel)
    return channels


def _friendly_error(error: Exception) -> str:
    if isinstance(error, (app_commands.MissingPermissions, commands.MissingPermissions)):
        return "🚫 You need the **Manage Messages** permission to do that."
    if isinstance(error, (app_commands.BotMissingPermissions, commands.BotMissingPermissions)):
        return "🚫 I'm missing permissions (need **Manage Messages** and **Read Message History**)."
    if isinstance(error, commands.BadArgument):
        return "🚫 I couldn't find that user. Mention them or use their ID."
    if isinstance(error, commands.MissingRequiredArgument):
        return "Usage: `!purgeuser @user [limit]`"
    if isinstance(error, (app_commands.NoPrivateMessage, commands.NoPrivateMessage)):
        return "🚫 This command only works in a server."
    log.exception("Unhandled command error: %s", error)
    return "❌ Something went wrong while purging messages."


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
