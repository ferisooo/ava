"""Moderation suite: grouped purge/warn commands, kick/mute/tempban, channel
control, warning thresholds with auto-mute/kick, and persistent infraction logs.
"""

from __future__ import annotations

import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands, tasks

from .. import store
from ..purge import PurgeSummary, purge_user_in_channel

log = logging.getLogger("ava.moderation")

_DURATION_RE = re.compile(r"(\d+)\s*([smhdw])", re.IGNORECASE)
_UNIT_SECONDS = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
MAX_TIMEOUT = timedelta(days=28)  # Discord's hard cap for member timeouts


def parse_duration(text: str) -> Optional[timedelta]:
    """Parse strings like '10m', '2h30m', '7d' into a timedelta (None if empty)."""
    matches = _DURATION_RE.findall(text or "")
    if not matches:
        return None
    total = sum(int(n) * _UNIT_SECONDS[u.lower()] for n, u in matches)
    return timedelta(seconds=total) if total > 0 else None


def _hierarchy_error(interaction: discord.Interaction, member: discord.Member) -> Optional[str]:
    guild = interaction.guild
    assert guild is not None
    if member == guild.owner:
        return "I can't action the server owner."
    if member.id == interaction.client.user.id:  # type: ignore[union-attr]
        return "I'm not going to action myself. 🙂"
    if member.top_role >= guild.me.top_role:
        return "That member's highest role is above mine — move my role higher in Server Settings → Roles."
    actor = interaction.user
    if actor != guild.owner and isinstance(actor, discord.Member) and member.top_role >= actor.top_role:
        return "You can only moderate members below your own highest role."
    return None


def _summary_lines(summary: PurgeSummary) -> str:
    parts = [
        f"Deleted **{summary.total_deleted}** message(s) across "
        f"**{summary.channels_touched}** channel(s)."
    ]
    if summary.total_failed:
        parts.append(f"⚠️ Failed to delete {summary.total_failed} message(s).")
    return "\n".join(parts)


class _ConfirmNuke(discord.ui.View):
    def __init__(self, channel: discord.TextChannel, author_id: int) -> None:
        super().__init__(timeout=30)
        self.channel = channel
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message("Not your command.", ephemeral=True)
            return False
        return True

    @discord.ui.button(label="Nuke it", style=discord.ButtonStyle.danger, emoji="💣")
    async def confirm(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="💥 Nuking…", view=None)
        try:
            new_channel = await self.channel.clone(reason=f"Nuke by {interaction.user}")
            await new_channel.edit(position=self.channel.position)
            await self.channel.delete(reason=f"Nuke by {interaction.user}")
        except discord.HTTPException as exc:
            await interaction.followup.send(f"❌ Nuke failed: {exc}", ephemeral=True)
            return
        try:
            await new_channel.send("💥 Channel nuked — fresh start!")
        except discord.HTTPException:
            pass

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary)
    async def cancel(self, interaction: discord.Interaction, button: discord.ui.Button) -> None:
        await interaction.response.edit_message(content="Cancelled.", view=None)


class Moderation(commands.Cog):
    """Server moderation tools."""

    # Grouped command sets — typing /purge or /warn reveals the subcommands.
    purge_group = app_commands.Group(
        name="purge", description="Delete messages.", guild_only=True
    )
    warn_group = app_commands.Group(
        name="warn", description="Warnings and infraction logs.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        store.init()
        self._tempban_loop.start()

    async def cog_unload(self) -> None:
        self._tempban_loop.cancel()

    # ------------------------------------------------------------------ #
    # Logging helpers
    # ------------------------------------------------------------------ #
    async def _record(
        self,
        guild: discord.Guild,
        target: discord.abc.Snowflake,
        moderator: discord.abc.User,
        action: str,
        reason: Optional[str],
        expires_at: Optional[str] = None,
    ) -> int:
        infraction_id = store.add_infraction(
            guild.id, target.id, moderator.id, action, reason, expires_at
        )
        settings = store.get_settings(guild.id)
        channel_id = settings["log_channel_id"]
        if channel_id:
            channel = guild.get_channel(channel_id)
            if isinstance(channel, discord.TextChannel):
                embed = discord.Embed(
                    title=f"{action.title()} · case #{infraction_id}",
                    colour=discord.Colour.orange(),
                    timestamp=datetime.now(timezone.utc),
                )
                embed.add_field(name="User", value=f"<@{target.id}> (`{target.id}`)", inline=True)
                embed.add_field(name="Moderator", value=f"{moderator.mention}", inline=True)
                if expires_at:
                    embed.add_field(name="Until", value=expires_at, inline=True)
                embed.add_field(name="Reason", value=reason or "—", inline=False)
                try:
                    await channel.send(embed=embed)
                except discord.HTTPException:
                    pass
        return infraction_id

    # ------------------------------------------------------------------ #
    # Tempban expiry loop
    # ------------------------------------------------------------------ #
    @tasks.loop(minutes=1)
    async def _tempban_loop(self) -> None:
        for row in store.due_tempbans():
            guild = self.bot.get_guild(row["guild_id"])
            if guild is not None:
                try:
                    await guild.unban(
                        discord.Object(id=row["user_id"]), reason="Tempban expired"
                    )
                except discord.HTTPException:
                    pass
            store.remove_tempban(row["guild_id"], row["user_id"])

    @_tempban_loop.before_loop
    async def _before_tempban_loop(self) -> None:
        await self.bot.wait_until_ready()

    # ------------------------------------------------------------------ #
    # /purge group
    # ------------------------------------------------------------------ #
    @purge_group.command(name="all", description="Delete the most recent messages here (up to 1000).")
    @app_commands.describe(count="How many recent messages to delete (1–1000).")
    @app_commands.checks.has_permissions(manage_messages=True)
    @app_commands.checks.bot_has_permissions(manage_messages=True, read_message_history=True)
    async def purge_all(
        self, interaction: discord.Interaction, count: app_commands.Range[int, 1, 1000]
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, (discord.TextChannel, discord.Thread)):
            await interaction.response.send_message(
                "🚫 I can only purge in a text channel.", ephemeral=True
            )
            return
        await interaction.response.defer(ephemeral=True, thinking=True)
        deleted = await channel.purge(limit=count, reason=f"/purge all by {interaction.user}")
        note = "" if len(deleted) >= count else " (some may be older than 14 days)."
        await interaction.followup.send(
            f"🧹 Deleted **{len(deleted)}** message(s).{note}", ephemeral=True
        )

    @purge_group.command(name="user", description="Delete a specific user's messages.")
    @app_commands.describe(
        user="Whose messages to delete.",
        channel="Limit to this channel (default: every channel I can moderate).",
        limit="Max messages to delete per channel.",
    )
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
        await interaction.response.defer(ephemeral=True, thinking=True)
        if channel is not None:
            result = await purge_user_in_channel(channel, user, limit=limit)
            summary = PurgeSummary(user_id=user.id, results=[result])
        else:
            member = interaction.guild.me
            channels = [
                c
                for c in interaction.guild.text_channels
                if c.permissions_for(member).read_message_history
                and c.permissions_for(member).manage_messages
            ]
            results = [await purge_user_in_channel(c, user, limit=limit) for c in channels]
            summary = PurgeSummary(user_id=user.id, results=results)
        await interaction.followup.send(
            f"🧹 Purge of {user.mention} complete.\n{_summary_lines(summary)}", ephemeral=True
        )

    # ------------------------------------------------------------------ #
    # Member punishments
    # ------------------------------------------------------------------ #
    @app_commands.command(name="kick", description="Kick a member.")
    @app_commands.describe(member="Member to kick.", reason="Why (optional).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(kick_members=True)
    @app_commands.checks.bot_has_permissions(kick_members=True)
    async def kick(
        self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = None
    ) -> None:
        err = _hierarchy_error(interaction, member)
        if err:
            await interaction.response.send_message(f"🚫 {err}", ephemeral=True)
            return
        await member.kick(reason=reason or f"By {interaction.user}")
        assert interaction.guild is not None
        case = await self._record(interaction.guild, member, interaction.user, "kick", reason)
        await interaction.response.send_message(
            f"👢 Kicked **{member}** · case #{case}" + (f"\nReason: {reason}" if reason else "")
        )

    @app_commands.command(name="mute", description="Timeout a member for a duration (e.g. 10m, 1h, 1d).")
    @app_commands.describe(member="Member to mute.", duration="e.g. 30m, 2h, 1d (max 28d).", reason="Why (optional).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def mute(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: Optional[str] = None,
    ) -> None:
        err = _hierarchy_error(interaction, member)
        if err:
            await interaction.response.send_message(f"🚫 {err}", ephemeral=True)
            return
        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message(
                "🚫 Invalid duration. Use formats like `30m`, `2h`, `1d`.", ephemeral=True
            )
            return
        if delta > MAX_TIMEOUT:
            delta = MAX_TIMEOUT
        until = datetime.now(timezone.utc) + delta
        await member.timeout(until, reason=reason or f"By {interaction.user}")
        assert interaction.guild is not None
        case = await self._record(
            interaction.guild, member, interaction.user, "mute", reason,
            expires_at=until.isoformat(timespec="seconds"),
        )
        await interaction.response.send_message(
            f"🔇 Muted **{member}** for **{duration}** · case #{case}"
        )

    @app_commands.command(name="unmute", description="Remove a member's timeout.")
    @app_commands.describe(member="Member to unmute.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(moderate_members=True)
    @app_commands.checks.bot_has_permissions(moderate_members=True)
    async def unmute(self, interaction: discord.Interaction, member: discord.Member) -> None:
        await member.timeout(None, reason=f"Unmute by {interaction.user}")
        await interaction.response.send_message(f"🔊 Unmuted **{member}**.")

    @app_commands.command(name="tempban", description="Ban a member for a duration, then auto-unban.")
    @app_commands.describe(member="Member to ban.", duration="e.g. 1d, 7d, 2w.", reason="Why (optional).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def tempban(
        self,
        interaction: discord.Interaction,
        member: discord.Member,
        duration: str,
        reason: Optional[str] = None,
    ) -> None:
        err = _hierarchy_error(interaction, member)
        if err:
            await interaction.response.send_message(f"🚫 {err}", ephemeral=True)
            return
        delta = parse_duration(duration)
        if delta is None:
            await interaction.response.send_message(
                "🚫 Invalid duration. Use formats like `1d`, `7d`, `2w`.", ephemeral=True
            )
            return
        assert interaction.guild is not None
        unban_ts = time.time() + delta.total_seconds()
        until = datetime.now(timezone.utc) + delta
        await member.ban(reason=reason or f"Tempban by {interaction.user}", delete_message_days=0)
        store.add_tempban(interaction.guild.id, member.id, unban_ts)
        case = await self._record(
            interaction.guild, member, interaction.user, "tempban", reason,
            expires_at=until.isoformat(timespec="seconds"),
        )
        await interaction.response.send_message(
            f"🔨 Temp-banned **{member}** for **{duration}** · case #{case}"
        )

    @app_commands.command(name="unban", description="Unban a user by their ID.")
    @app_commands.describe(user_id="The banned user's ID.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(ban_members=True)
    @app_commands.checks.bot_has_permissions(ban_members=True)
    async def unban(self, interaction: discord.Interaction, user_id: str) -> None:
        assert interaction.guild is not None
        try:
            uid = int(user_id)
        except ValueError:
            await interaction.response.send_message("🚫 That isn't a valid user ID.", ephemeral=True)
            return
        try:
            await interaction.guild.unban(discord.Object(id=uid), reason=f"By {interaction.user}")
        except discord.NotFound:
            await interaction.response.send_message("🚫 That user isn't banned.", ephemeral=True)
            return
        store.remove_tempban(interaction.guild.id, uid)
        await interaction.response.send_message(f"♻️ Unbanned `<@{uid}>` (`{uid}`).")

    # ------------------------------------------------------------------ #
    # Channel control
    # ------------------------------------------------------------------ #
    @app_commands.command(name="slowmode", description="Set this channel's slowmode (seconds; 0 to clear).")
    @app_commands.describe(seconds="Seconds between messages (0–21600).")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def slowmode(
        self, interaction: discord.Interaction, seconds: app_commands.Range[int, 0, 21600]
    ) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("🚫 Not a text channel.", ephemeral=True)
            return
        await channel.edit(slowmode_delay=seconds, reason=f"By {interaction.user}")
        msg = "cleared slowmode" if seconds == 0 else f"set slowmode to **{seconds}s**"
        await interaction.response.send_message(f"🐌 {msg.capitalize()} in {channel.mention}.")

    @app_commands.command(name="lock", description="Stop @everyone from sending in this channel.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def lock(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        assert interaction.guild is not None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("🚫 Not a text channel.", ephemeral=True)
            return
        await channel.set_permissions(
            interaction.guild.default_role, send_messages=False, reason=f"Lock by {interaction.user}"
        )
        await interaction.response.send_message(f"🔒 Locked {channel.mention}.")

    @app_commands.command(name="unlock", description="Allow @everyone to send in this channel again.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_roles=True)
    async def unlock(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        assert interaction.guild is not None
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("🚫 Not a text channel.", ephemeral=True)
            return
        await channel.set_permissions(
            interaction.guild.default_role, send_messages=None, reason=f"Unlock by {interaction.user}"
        )
        await interaction.response.send_message(f"🔓 Unlocked {channel.mention}.")

    @app_commands.command(name="nuke", description="Wipe this channel by cloning it and deleting the old one.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_channels=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True)
    async def nuke(self, interaction: discord.Interaction) -> None:
        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            await interaction.response.send_message("🚫 Not a text channel.", ephemeral=True)
            return
        view = _ConfirmNuke(channel, interaction.user.id)
        await interaction.response.send_message(
            f"💣 This deletes **all messages** in {channel.mention} by recreating it "
            "(settings and permissions are kept). Confirm?",
            view=view,
            ephemeral=True,
        )

    # ------------------------------------------------------------------ #
    # /warn group + infraction logs
    # ------------------------------------------------------------------ #
    @warn_group.command(name="add", description="Warn a member (may auto-mute/kick at thresholds).")
    @app_commands.describe(member="Member to warn.", reason="Why (optional).")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn_add(
        self, interaction: discord.Interaction, member: discord.Member, reason: Optional[str] = None
    ) -> None:
        assert interaction.guild is not None
        err = _hierarchy_error(interaction, member)
        if err:
            await interaction.response.send_message(f"🚫 {err}", ephemeral=True)
            return
        case = await self._record(interaction.guild, member, interaction.user, "warn", reason)
        count = store.warn_count(interaction.guild.id, member.id)
        settings = store.get_settings(interaction.guild.id)

        auto = ""
        try:
            if count >= settings["warn_kick_threshold"]:
                await member.kick(reason=f"Reached {count} warnings")
                await self._record(interaction.guild, member, self.bot.user, "auto-kick", f"{count} warnings")
                auto = f"\n⚠️ Reached **{count}** warnings — **auto-kicked**."
            elif count >= settings["warn_mute_threshold"]:
                minutes = settings["warn_mute_minutes"]
                until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
                await member.timeout(until, reason=f"Reached {count} warnings")
                await self._record(
                    interaction.guild, member, self.bot.user, "auto-mute", f"{count} warnings",
                    expires_at=until.isoformat(timespec="seconds"),
                )
                auto = f"\n⚠️ Reached **{count}** warnings — **auto-muted for {minutes}m**."
        except discord.HTTPException:
            auto = "\n(Could not apply the automatic action — check my permissions/role position.)"

        await interaction.response.send_message(
            f"⚠️ Warned **{member}** · case #{case} · they now have **{count}** warning(s)."
            + (f"\nReason: {reason}" if reason else "")
            + auto
        )

    @warn_group.command(name="list", description="List a member's warnings.")
    @app_commands.describe(member="Member to look up.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn_list(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild is not None
        warnings = store.get_infractions(interaction.guild.id, member.id, action="warn")
        if not warnings:
            await interaction.response.send_message(f"**{member}** has no warnings.", ephemeral=True)
            return
        lines = [
            f"`#{w['id']}` · {w['created_at'][:10]} · <@{w['moderator_id']}> · {w['reason'] or '—'}"
            for w in warnings[:15]
        ]
        embed = discord.Embed(
            title=f"Warnings for {member} ({len(warnings)})",
            description="\n".join(lines),
            colour=discord.Colour.orange(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @warn_group.command(name="remove", description="Remove one warning/infraction by its case number.")
    @app_commands.describe(case_id="The case number shown in the logs.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn_remove(self, interaction: discord.Interaction, case_id: int) -> None:
        assert interaction.guild is not None
        ok = store.remove_infraction(interaction.guild.id, case_id)
        msg = f"🗑️ Removed case #{case_id}." if ok else f"🚫 No case #{case_id} here."
        await interaction.response.send_message(msg, ephemeral=True)

    @warn_group.command(name="clear", description="Clear all of a member's warnings.")
    @app_commands.describe(member="Member to clear.")
    @app_commands.checks.has_permissions(kick_members=True)
    async def warn_clear(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild is not None
        removed = store.clear_warnings(interaction.guild.id, member.id)
        await interaction.response.send_message(
            f"🧹 Cleared **{removed}** warning(s) from **{member}**.", ephemeral=True
        )

    @warn_group.command(name="config", description="Set warning thresholds and the mod-log channel.")
    @app_commands.describe(
        mute_threshold="Warnings before an auto-mute.",
        mute_minutes="How long the auto-mute lasts.",
        kick_threshold="Warnings before an auto-kick.",
        log_channel="Channel to post infraction logs in.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def warn_config(
        self,
        interaction: discord.Interaction,
        mute_threshold: Optional[app_commands.Range[int, 1, 50]] = None,
        mute_minutes: Optional[app_commands.Range[int, 1, 40320]] = None,
        kick_threshold: Optional[app_commands.Range[int, 1, 50]] = None,
        log_channel: Optional[discord.TextChannel] = None,
    ) -> None:
        assert interaction.guild is not None
        gid = interaction.guild.id
        if mute_threshold is not None:
            store.set_setting(gid, "warn_mute_threshold", mute_threshold)
        if mute_minutes is not None:
            store.set_setting(gid, "warn_mute_minutes", mute_minutes)
        if kick_threshold is not None:
            store.set_setting(gid, "warn_kick_threshold", kick_threshold)
        if log_channel is not None:
            store.set_setting(gid, "log_channel_id", log_channel.id)
        s = store.get_settings(gid)
        ch = f"<#{s['log_channel_id']}>" if s["log_channel_id"] else "none"
        await interaction.response.send_message(
            "⚙️ **Warning settings**\n"
            f"• Auto-mute at **{s['warn_mute_threshold']}** warnings for **{s['warn_mute_minutes']}m**\n"
            f"• Auto-kick at **{s['warn_kick_threshold']}** warnings\n"
            f"• Mod-log channel: {ch}",
            ephemeral=True,
        )

    @app_commands.command(name="infractions", description="Show a member's full infraction history.")
    @app_commands.describe(member="Member to look up.")
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(kick_members=True)
    async def infractions(self, interaction: discord.Interaction, member: discord.Member) -> None:
        assert interaction.guild is not None
        records = store.get_infractions(interaction.guild.id, member.id)
        if not records:
            await interaction.response.send_message(f"**{member}** has a clean record.", ephemeral=True)
            return
        lines = [
            f"`#{r['id']}` · **{r['action']}** · {r['created_at'][:10]} · {r['reason'] or '—'}"
            for r in records[:20]
        ]
        embed = discord.Embed(
            title=f"Infractions for {member} ({len(records)})",
            description="\n".join(lines),
            colour=discord.Colour.red(),
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    # ------------------------------------------------------------------ #
    # Shared error handling for every app command in this cog
    # ------------------------------------------------------------------ #
    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 You don't have permission to do that."
        elif isinstance(error, app_commands.BotMissingPermissions):
            missing = ", ".join(error.missing_permissions)
            msg = f"🚫 I'm missing permissions: **{missing}**."
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "🚫 This only works inside a server."
        elif isinstance(error, app_commands.TransformerError):
            msg = "🚫 I couldn't find that user/channel."
        else:
            log.exception("moderation command error: %s", error)
            msg = "❌ Something went wrong running that command."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Moderation(bot))
