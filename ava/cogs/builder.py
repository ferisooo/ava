"""Server-builder command: design a server with DeepSeek, then build it."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

import discord
from discord import app_commands
from discord.ext import commands

from ..ai import DeepSeekError, plan_server
from ..presets import PRESETS

log = logging.getLogger("ava.builder")

# Built from the presets module so the dropdown stays in sync with PRESETS.
_PRESET_CHOICES = [
    app_commands.Choice(name=preset["label"], value=key)
    for key, preset in PRESETS.items()
]


def _preview_embed(plan: dict[str, Any], description: str) -> discord.Embed:
    name = plan.get("server_name") or "your server"
    roles = plan.get("roles", [])
    categories = plan.get("categories", [])
    channel_count = sum(len(c.get("channels", [])) for c in categories)

    embed = discord.Embed(
        title=f"🏗️ Plan for {name}",
        description=f"From: *{description[:200]}*",
        colour=discord.Colour.blurple(),
    )
    if roles:
        embed.add_field(
            name=f"Roles ({len(roles)})",
            value=", ".join(f"`{r['name']}`" for r in roles)[:1024] or "—",
            inline=False,
        )
    for category in categories[:10]:
        channels = category.get("channels", [])
        lines = []
        for ch in channels:
            icon = "🔊" if (ch.get("type") or "text").lower() in ("voice", "vc") else "#"
            lines.append(f"{icon} {ch['name']}")
        value = "\n".join(lines)[:1024] or "—"
        embed.add_field(name=category["name"], value=value, inline=True)

    embed.set_footer(
        text=f"{len(categories)} categories · {channel_count} channels · "
        f"{len(roles)} roles — click Build to create them."
    )
    return embed


async def build_from_plan(guild: discord.Guild, plan: dict[str, Any]) -> dict[str, int]:
    """Create the roles, categories, and channels described by the plan."""
    created = {"roles": 0, "categories": 0, "channels": 0}

    for role in plan.get("roles", []):
        kwargs: dict[str, Any] = {
            "name": str(role["name"])[:100],
            "hoist": bool(role.get("hoist", False)),
            "mentionable": bool(role.get("mentionable", False)),
            "reason": "Ava server builder",
        }
        colour = role.get("color") or role.get("colour")
        if colour:
            try:
                kwargs["colour"] = discord.Colour.from_str(str(colour))
            except ValueError:
                pass
        await guild.create_role(**kwargs)
        created["roles"] += 1
        await asyncio.sleep(0.3)  # stay friendly with the rate limiter

    for category in plan.get("categories", []):
        discord_category = await guild.create_category(
            str(category["name"])[:100], reason="Ava server builder"
        )
        created["categories"] += 1
        await asyncio.sleep(0.3)

        for ch in category.get("channels", []):
            ch_name = str(ch["name"])[:100]
            ch_type = (ch.get("type") or "text").lower()
            if ch_type in ("voice", "vc"):
                await guild.create_voice_channel(
                    ch_name, category=discord_category, reason="Ava server builder"
                )
            else:
                await guild.create_text_channel(
                    ch_name,
                    category=discord_category,
                    topic=(ch.get("topic") or None),
                    reason="Ava server builder",
                )
            created["channels"] += 1
            await asyncio.sleep(0.3)

    return created


class ConfirmBuild(discord.ui.View):
    """Two-button confirmation gate shown before anything is created."""

    def __init__(self, plan: dict[str, Any], author_id: int) -> None:
        super().__init__(timeout=180)
        self.plan = plan
        self.author_id = author_id

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "Only the person who ran the command can confirm this.", ephemeral=True
            )
            return False
        return True

    @discord.ui.button(label="Build it", style=discord.ButtonStyle.success, emoji="✅")
    async def confirm(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content="🔨 Building… this can take a minute for larger servers.",
            embed=None,
            view=None,
        )
        try:
            created = await build_from_plan(interaction.guild, self.plan)
        except discord.Forbidden:
            await interaction.followup.send(
                "❌ I don't have permission to create channels/roles here. "
                "Give me **Manage Channels** and **Manage Roles** (and make sure my "
                "role is high enough in the list)."
            )
            return
        except discord.HTTPException as exc:
            await interaction.followup.send(f"⚠️ Build stopped partway: {exc}")
            return
        await interaction.followup.send(
            f"✅ Done! Created **{created['categories']}** categories, "
            f"**{created['channels']}** channels, and **{created['roles']}** roles."
        )

    @discord.ui.button(label="Cancel", style=discord.ButtonStyle.secondary, emoji="✖️")
    async def cancel(
        self, interaction: discord.Interaction, button: discord.ui.Button
    ) -> None:
        await interaction.response.edit_message(
            content="Cancelled — nothing was created.", embed=None, view=None
        )


class Builder(commands.Cog):
    """Design and build out a server from a natural-language description."""

    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _make_plan(self, description: str) -> dict[str, Any]:
        cfg = self.bot.config
        return await plan_server(
            description,
            api_key=cfg.deepseek_api_key,
            model=cfg.deepseek_model,
            base_url=cfg.deepseek_base_url,
        )

    @app_commands.command(
        name="build_server",
        description="Build this server from a ready-made preset or a description.",
    )
    @app_commands.describe(
        preset="Pick a ready-made layout (instant, no AI).",
        description="Or describe a custom server for DeepSeek to design.",
    )
    @app_commands.choices(preset=_PRESET_CHOICES)
    @app_commands.guild_only()
    @app_commands.checks.has_permissions(administrator=True)
    @app_commands.checks.bot_has_permissions(manage_channels=True, manage_roles=True)
    async def build_server(
        self,
        interaction: discord.Interaction,
        preset: app_commands.Choice[str] | None = None,
        description: str | None = None,
    ) -> None:
        # Preset path — instant, no AI call needed.
        if preset is not None:
            plan = PRESETS[preset.value]["plan"]
            embed = _preview_embed(plan, f"{preset.name} preset")
            view = ConfirmBuild(plan, interaction.user.id)
            await interaction.response.send_message(
                content="Here's the layout — review it, then confirm:",
                embed=embed,
                view=view,
            )
            return

        # Custom path — needs a description and DeepSeek.
        if not description:
            await interaction.response.send_message(
                "Pick a **preset**, or give a **description** for me to design a "
                "custom server.",
                ephemeral=True,
            )
            return

        if not self.bot.config.deepseek_api_key:
            await interaction.response.send_message(
                "🚫 DeepSeek isn't configured. Add `DEEPSEEK_API_KEY` to the `.env` "
                "(or use a preset, which needs no AI).",
                ephemeral=True,
            )
            return

        await interaction.response.defer(thinking=True)
        try:
            plan = await self._make_plan(description)
        except DeepSeekError as exc:
            await interaction.followup.send(f"❌ Couldn't design the server: {exc}")
            return

        if not plan.get("categories") and not plan.get("roles"):
            await interaction.followup.send(
                "🤔 DeepSeek didn't return anything to build. Try describing the "
                "server in a bit more detail."
            )
            return

        embed = _preview_embed(plan, description)
        view = ConfirmBuild(plan, interaction.user.id)
        await interaction.followup.send(
            content="Here's what I'll build — review it, then confirm:",
            embed=embed,
            view=view,
        )

    @build_server.error
    async def build_server_error(
        self, interaction: discord.Interaction, error: app_commands.AppCommandError
    ) -> None:
        if isinstance(error, app_commands.MissingPermissions):
            msg = "🚫 You need to be an **Administrator** to build out the server."
        elif isinstance(error, app_commands.BotMissingPermissions):
            msg = "🚫 I need **Manage Channels** and **Manage Roles** to do that."
        elif isinstance(error, app_commands.NoPrivateMessage):
            msg = "🚫 This only works inside a server."
        else:
            log.exception("build_server failed: %s", error)
            msg = "❌ Something went wrong setting that up."
        if interaction.response.is_done():
            await interaction.followup.send(msg, ephemeral=True)
        else:
            await interaction.response.send_message(msg, ephemeral=True)


async def setup(bot: commands.Bot) -> None:
    await bot.add_cog(Builder(bot))
