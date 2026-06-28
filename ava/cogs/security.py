"""/security — apply a bundle of auto-mod & anti-raid settings by level."""

from __future__ import annotations

import logging

import discord
from discord import app_commands
from discord.ext import commands

from .. import store

log = logging.getLogger("ava.security")

# Each level is a full set of automod values plus a Discord verification level.
LEVELS: dict[str, dict] = {
    "easy": {
        "label": "Easy",
        "verification": discord.VerificationLevel.low,
        "automod": {
            "enabled": 1, "block_invites": 0, "block_mass_mentions": 1, "mention_limit": 8,
            "block_spam": 1, "spam_count": 7, "spam_seconds": 5, "block_caps": 0,
            "escalate_strikes": 5, "escalate_minutes": 5,
            "raid_enabled": 1, "raid_joins": 15, "raid_seconds": 10, "min_account_age_days": 0,
        },
    },
    "medium": {
        "label": "Medium",
        "verification": discord.VerificationLevel.medium,
        "automod": {
            "enabled": 1, "block_invites": 1, "block_mass_mentions": 1, "mention_limit": 5,
            "block_spam": 1, "spam_count": 5, "spam_seconds": 5, "block_caps": 1,
            "escalate_strikes": 3, "escalate_minutes": 10,
            "raid_enabled": 1, "raid_joins": 10, "raid_seconds": 10, "min_account_age_days": 1,
        },
    },
    "hard": {
        "label": "Hard",
        "verification": discord.VerificationLevel.high,
        "automod": {
            "enabled": 1, "block_invites": 1, "block_mass_mentions": 1, "mention_limit": 4,
            "block_spam": 1, "spam_count": 4, "spam_seconds": 6, "block_caps": 1,
            "escalate_strikes": 2, "escalate_minutes": 30,
            "raid_enabled": 1, "raid_joins": 6, "raid_seconds": 12, "min_account_age_days": 7,
        },
    },
    "strict": {
        "label": "Strict",
        "verification": discord.VerificationLevel.highest,
        "automod": {
            "enabled": 1, "block_invites": 1, "block_mass_mentions": 1, "mention_limit": 3,
            "block_spam": 1, "spam_count": 3, "spam_seconds": 8, "block_caps": 1,
            "escalate_strikes": 2, "escalate_minutes": 60,
            "raid_enabled": 1, "raid_joins": 4, "raid_seconds": 15, "min_account_age_days": 14,
        },
    },
}


class Security(commands.Cog):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def cog_load(self) -> None:
        store.init()

    @app_commands.command(name="security", description="Apply a security preset to this server.")
    @app_commands.default_permissions(manage_guild=True)
    @app_commands.describe(level="How strict to be.")
    @app_commands.choices(
        level=[
            app_commands.Choice(name="Easy — light touch", value="easy"),
            app_commands.Choice(name="Medium — balanced (recommended)", value="medium"),
            app_commands.Choice(name="Hard — locked down", value="hard"),
            app_commands.Choice(name="Strict — maximum protection", value="strict"),
        ]
    )
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(manage_guild=True)
    async def security(
        self, interaction: discord.Interaction, level: app_commands.Choice[str]
    ) -> None:
        assert interaction.guild is not None
        preset = LEVELS[level.value]
        for key, value in preset["automod"].items():
            store.set_automod(interaction.guild.id, key, value)

        verify_note = ""
        try:
            await interaction.guild.edit(
                verification_level=preset["verification"],
                reason=f"/security {level.value} by {interaction.user}",
            )
        except discord.HTTPException:
            verify_note = "\n(Couldn't change the server verification level — check my permissions.)"

        a = preset["automod"]
        await interaction.response.send_message(
            f"🛡️ **{preset['label']}** security applied.\n"
            f"• Verification: **{preset['verification'].name}**\n"
            f"• Spam limit: {a['spam_count']}/{a['spam_seconds']}s · mentions > {a['mention_limit']}\n"
            f"• Escalate: {a['escalate_strikes']} hits → mute {a['escalate_minutes']}m\n"
            f"• Raid: {a['raid_joins']} joins/{a['raid_seconds']}s · min account age "
            f"{a['min_account_age_days']}d\n"
            f"Fine-tune with `/automod status`.{verify_note}",
            ephemeral=True,
        )

    @security.error
    async def security_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 You need **Manage Server** for that."
        else:
            log.exception("security error: %s", error)
            msg = "❌ Something went wrong."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Security(bot))
