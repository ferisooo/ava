"""Auto-mod and anti-raid.

Watches messages for invites, mass mentions, spam, and excessive caps, and
watches joins for raids / brand-new accounts. Every action is logged as an
infraction (action prefixed "automod-"), and repeated hits escalate to a
timeout — so it plugs into the same record system as manual moderation.
"""

from __future__ import annotations

import logging
import re
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Optional

import discord
from discord import app_commands
from discord.ext import commands

from .. import store

log = logging.getLogger("ava.automod")

_INVITE_RE = re.compile(
    r"(?:discord(?:app)?\.com/invite|discord\.gg|discord\.me)/\S+", re.IGNORECASE
)
_ESCALATE_WINDOW = 60.0  # seconds over which auto-mod strikes accumulate
_RAID_ALERT_COOLDOWN = 60.0


class AutoMod(commands.Cog):
    """Automatic moderation and raid protection."""

    automod_group = app_commands.Group(
        name="automod", description="Auto-mod & anti-raid settings.", guild_only=True
    )

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot
        self._msg_times: dict[tuple[int, int], list[float]] = defaultdict(list)
        self._strikes: dict[tuple[int, int], list[float]] = defaultdict(list)
        self._joins: dict[int, list[float]] = defaultdict(list)
        self._last_raid_alert: dict[int, float] = {}

    async def cog_load(self) -> None:
        store.init()

    # ------------------------------------------------------------------ #
    # Message scanning
    # ------------------------------------------------------------------ #
    def _is_spam(self, key: tuple[int, int], cfg: dict[str, int]) -> bool:
        now = time.time()
        times = self._msg_times[key]
        times.append(now)
        cutoff = now - cfg["spam_seconds"]
        self._msg_times[key] = [t for t in times if t >= cutoff]
        return len(self._msg_times[key]) >= cfg["spam_count"]

    @staticmethod
    def _is_shouting(text: str, cfg: dict[str, int]) -> bool:
        letters = [c for c in text if c.isalpha()]
        if len(letters) < cfg["caps_min_len"]:
            return False
        upper = sum(1 for c in letters if c.isupper())
        return (upper / len(letters)) * 100 >= cfg["caps_percent"]

    def _violation(self, message: discord.Message, cfg: dict[str, int]) -> Optional[str]:
        content = message.content or ""
        if cfg["block_invites"] and _INVITE_RE.search(content):
            return "invite"
        if cfg["block_mass_mentions"] and (
            message.mention_everyone
            or (len(message.mentions) + len(message.role_mentions)) > cfg["mention_limit"]
        ):
            return "mass-mention"
        if cfg["block_caps"] and self._is_shouting(content, cfg):
            return "caps"
        if cfg["block_spam"] and self._is_spam((message.guild.id, message.author.id), cfg):  # type: ignore[union-attr]
            return "spam"
        return None

    @commands.Cog.listener()
    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot or message.guild is None:
            return
        member = message.author
        if not isinstance(member, discord.Member):
            return
        # Exempt staff.
        perms = member.guild_permissions
        if perms.administrator or perms.manage_messages or perms.moderate_members:
            return

        cfg = store.get_automod(message.guild.id)
        if not cfg["enabled"]:
            return

        vtype = self._violation(message, cfg)
        if vtype is None:
            return

        try:
            await message.delete()
        except discord.HTTPException:
            pass

        store.add_infraction(
            message.guild.id, member.id, self.bot.user.id, f"automod-{vtype}", "Auto-mod"
        )
        try:
            await message.channel.send(
                f"{member.mention} — that was auto-removed ({vtype.replace('-', ' ')}).",
                delete_after=5,
            )
        except discord.HTTPException:
            pass

        await self._escalate(message.guild, member, cfg)

    async def _escalate(
        self, guild: discord.Guild, member: discord.Member, cfg: dict[str, int]
    ) -> None:
        now = time.time()
        key = (guild.id, member.id)
        strikes = [t for t in self._strikes[key] if t >= now - _ESCALATE_WINDOW]
        strikes.append(now)
        self._strikes[key] = strikes
        if len(strikes) < cfg["escalate_strikes"]:
            return
        # Too many hits too fast — timeout and reset the counter.
        self._strikes[key] = []
        minutes = cfg["escalate_minutes"]
        until = datetime.now(timezone.utc) + timedelta(minutes=minutes)
        try:
            await member.timeout(until, reason="Auto-mod: repeated violations")
        except discord.HTTPException:
            return
        store.add_infraction(
            guild.id, member.id, self.bot.user.id, "automod-mute",
            f"{len(strikes)} violations in {int(_ESCALATE_WINDOW)}s",
            expires_at=until.isoformat(timespec="seconds"),
        )

    # ------------------------------------------------------------------ #
    # Join scanning (anti-raid + account age)
    # ------------------------------------------------------------------ #
    async def _alert_channel(self, guild: discord.Guild, cfg: dict[str, int]) -> Optional[discord.TextChannel]:
        if cfg["alert_channel_id"]:
            ch = guild.get_channel(cfg["alert_channel_id"])
            if isinstance(ch, discord.TextChannel):
                return ch
        return guild.system_channel

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member) -> None:
        guild = member.guild
        cfg = store.get_automod(guild.id)
        if not cfg["enabled"]:
            return

        # Brand-new account check.
        min_days = cfg["min_account_age_days"]
        if min_days > 0:
            age = datetime.now(timezone.utc) - member.created_at
            if age < timedelta(days=min_days):
                store.add_infraction(
                    guild.id, member.id, self.bot.user.id, "automod-newaccount",
                    f"Account younger than {min_days}d",
                )
                try:
                    await member.kick(reason=f"Auto-mod: account younger than {min_days} days")
                except discord.HTTPException:
                    pass
                channel = await self._alert_channel(guild, cfg)
                if channel:
                    try:
                        await channel.send(
                            f"🛡️ Kicked **{member}** — account is under {min_days} days old."
                        )
                    except discord.HTTPException:
                        pass
                return

        # Raid detection: too many joins too fast.
        if not cfg["raid_enabled"]:
            return
        now = time.time()
        joins = [t for t in self._joins[guild.id] if t >= now - cfg["raid_seconds"]]
        joins.append(now)
        self._joins[guild.id] = joins
        if len(joins) >= cfg["raid_joins"]:
            last = self._last_raid_alert.get(guild.id, 0.0)
            if now - last >= _RAID_ALERT_COOLDOWN:
                self._last_raid_alert[guild.id] = now
                channel = await self._alert_channel(guild, cfg)
                if channel:
                    try:
                        await channel.send(
                            f"🚨 **Possible raid** — **{len(joins)}** joins in "
                            f"~{cfg['raid_seconds']}s. Consider `/lock`, raising the "
                            "verification level, or setting `/automod raid "
                            "min_account_age_days:`."
                        )
                    except discord.HTTPException:
                        pass

    # ------------------------------------------------------------------ #
    # /automod group
    # ------------------------------------------------------------------ #
    @automod_group.command(name="enable", description="Turn auto-mod & anti-raid on.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def enable(self, interaction: discord.Interaction) -> None:
        store.set_automod(interaction.guild.id, "enabled", 1)  # type: ignore[union-attr]
        await interaction.response.send_message("🛡️ Auto-mod **enabled**.", ephemeral=True)

    @automod_group.command(name="disable", description="Turn auto-mod & anti-raid off.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def disable(self, interaction: discord.Interaction) -> None:
        store.set_automod(interaction.guild.id, "enabled", 0)  # type: ignore[union-attr]
        await interaction.response.send_message("🛑 Auto-mod **disabled**.", ephemeral=True)

    @automod_group.command(name="status", description="Show the current auto-mod settings.")
    @app_commands.checks.has_permissions(manage_guild=True)
    async def status(self, interaction: discord.Interaction) -> None:
        c = store.get_automod(interaction.guild.id)  # type: ignore[union-attr]
        on = "✅" if c["enabled"] else "❌"

        def yn(v: int) -> str:
            return "on" if v else "off"

        alert = f"<#{c['alert_channel_id']}>" if c["alert_channel_id"] else "system channel"
        embed = discord.Embed(title=f"{on} Auto-mod", colour=discord.Colour.blurple())
        embed.add_field(
            name="Message filters",
            value=(
                f"Invites: {yn(c['block_invites'])}\n"
                f"Mass mentions: {yn(c['block_mass_mentions'])} (> {c['mention_limit']})\n"
                f"Spam: {yn(c['block_spam'])} ({c['spam_count']}/{c['spam_seconds']}s)\n"
                f"Caps: {yn(c['block_caps'])} (≥ {c['caps_percent']}%)\n"
                f"Escalate: {c['escalate_strikes']} hits/60s → mute {c['escalate_minutes']}m"
            ),
            inline=False,
        )
        embed.add_field(
            name="Anti-raid",
            value=(
                f"Raid detect: {yn(c['raid_enabled'])} ({c['raid_joins']} joins/{c['raid_seconds']}s)\n"
                f"Min account age: {c['min_account_age_days']}d (0 = off)\n"
                f"Alerts: {alert}"
            ),
            inline=False,
        )
        await interaction.response.send_message(embed=embed, ephemeral=True)

    @automod_group.command(name="config", description="Tune the message filters.")
    @app_commands.describe(
        invites="Block invite links.",
        mass_mentions="Block mass mentions.",
        mention_limit="Mentions allowed before it's blocked.",
        spam="Block message-rate spam.",
        caps="Block excessive caps.",
        escalate_strikes="Auto-mod hits within 60s before a timeout.",
        escalate_minutes="How long the auto timeout lasts.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def config(
        self,
        interaction: discord.Interaction,
        invites: Optional[bool] = None,
        mass_mentions: Optional[bool] = None,
        mention_limit: Optional[app_commands.Range[int, 1, 50]] = None,
        spam: Optional[bool] = None,
        caps: Optional[bool] = None,
        escalate_strikes: Optional[app_commands.Range[int, 1, 20]] = None,
        escalate_minutes: Optional[app_commands.Range[int, 1, 40320]] = None,
    ) -> None:
        gid = interaction.guild.id  # type: ignore[union-attr]
        if invites is not None:
            store.set_automod(gid, "block_invites", int(invites))
        if mass_mentions is not None:
            store.set_automod(gid, "block_mass_mentions", int(mass_mentions))
        if mention_limit is not None:
            store.set_automod(gid, "mention_limit", mention_limit)
        if spam is not None:
            store.set_automod(gid, "block_spam", int(spam))
        if caps is not None:
            store.set_automod(gid, "block_caps", int(caps))
        if escalate_strikes is not None:
            store.set_automod(gid, "escalate_strikes", escalate_strikes)
        if escalate_minutes is not None:
            store.set_automod(gid, "escalate_minutes", escalate_minutes)
        await interaction.response.send_message(
            "✅ Updated message filters. Use `/automod status` to review.", ephemeral=True
        )

    @automod_group.command(name="raid", description="Tune anti-raid settings.")
    @app_commands.describe(
        enabled="Detect mass joins.",
        joins="Joins that trigger a raid alert.",
        seconds="…within this many seconds.",
        min_account_age_days="Kick accounts younger than this on join (0 = off).",
        alert_channel="Channel for raid alerts.",
    )
    @app_commands.checks.has_permissions(manage_guild=True)
    async def raid(
        self,
        interaction: discord.Interaction,
        enabled: Optional[bool] = None,
        joins: Optional[app_commands.Range[int, 2, 100]] = None,
        seconds: Optional[app_commands.Range[int, 1, 600]] = None,
        min_account_age_days: Optional[app_commands.Range[int, 0, 365]] = None,
        alert_channel: Optional[discord.TextChannel] = None,
    ) -> None:
        gid = interaction.guild.id  # type: ignore[union-attr]
        if enabled is not None:
            store.set_automod(gid, "raid_enabled", int(enabled))
        if joins is not None:
            store.set_automod(gid, "raid_joins", joins)
        if seconds is not None:
            store.set_automod(gid, "raid_seconds", seconds)
        if min_account_age_days is not None:
            store.set_automod(gid, "min_account_age_days", min_account_age_days)
        if alert_channel is not None:
            store.set_automod(gid, "alert_channel_id", alert_channel.id)
        await interaction.response.send_message(
            "✅ Updated anti-raid. Use `/automod status` to review.", ephemeral=True
        )

    async def cog_app_command_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 You need **Manage Server** for that."
        else:
            log.exception("automod command error: %s", error)
            msg = "❌ Something went wrong."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(AutoMod(bot))
