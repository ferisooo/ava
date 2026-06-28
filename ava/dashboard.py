"""Serves the Ava control dashboard and a small API to apply live settings.

aiohttp ships with discord.py, so there's no extra dependency. Opt-in via
DASHBOARD_PORT. Writes require a shared admin key (DASHBOARD_KEY) so the public
URL can't be used by anyone to change the server. Only safe *settings* are
exposed (auto-mod, anti-raid, security preset, warning thresholds) — never
destructive per-action commands like kick/ban/nuke.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path

import discord
from aiohttp import web

from . import store

log = logging.getLogger("ava.dashboard")

_HTML_PATH = Path(__file__).parent / "web" / "dashboard.html"


def _key_configured() -> bool:
    return bool(os.getenv("DASHBOARD_KEY", "").strip())


def _check_key(request: web.Request) -> bool:
    key = os.getenv("DASHBOARD_KEY", "").strip()
    return bool(key) and request.headers.get("X-Ava-Key", "") == key


def _target_guild(bot) -> discord.Guild | None:
    return bot.guilds[0] if bot.guilds else None


async def _index(_request: web.Request) -> web.StreamResponse:
    return web.Response(
        text=_HTML_PATH.read_text(encoding="utf-8"),
        content_type="text/html",
        headers={"Cache-Control": "no-store, max-age=0"},
    )


async def _health(_request: web.Request) -> web.StreamResponse:
    return web.Response(text="ok")


async def _state(request: web.Request) -> web.StreamResponse:
    bot = request.app["bot"]
    guild = _target_guild(bot)
    if guild is None:
        return web.json_response({"guild": None, "key_required": _key_configured()})
    return web.json_response(
        {
            "guild": {"id": str(guild.id), "name": guild.name},
            "key_required": _key_configured(),
            "automod": store.get_automod(guild.id),
            "warn": store.get_settings(guild.id),
            "channels": [
                {"id": str(c.id), "name": c.name} for c in guild.text_channels
            ],
            "emojis": [
                {"label": e.name, "value": str(e)} for e in guild.emojis
            ],
        }
    )


async def _rr_list(request: web.Request) -> web.StreamResponse:
    bot = request.app["bot"]
    guild = _target_guild(bot)
    ch_id = request.query.get("channel", "")
    if guild is None or not ch_id.isdigit():
        return web.json_response({"entries": []})
    panel = store.get_rr_panel(int(ch_id))
    if not panel:
        return web.json_response({"entries": []})
    out = []
    for e in store.list_message_reaction_roles(panel["message_id"]):
        role = guild.get_role(e["role_id"])
        out.append(
            {
                "emoji": e["emoji"],
                "role_name": role.name if role else "deleted role",
                "category": e["category"] or "Roles",
                "exclusive": e["exclusive"],
            }
        )
    return web.json_response({"entries": out})


async def _apply(request: web.Request) -> web.StreamResponse:
    if not _key_configured():
        return web.json_response(
            {"ok": False, "error": "Writes are disabled — set DASHBOARD_KEY in the .env."},
            status=403,
        )
    if not _check_key(request):
        return web.json_response(
            {"ok": False, "error": "Wrong admin key."}, status=401
        )
    bot = request.app["bot"]
    guild = _target_guild(bot)
    if guild is None:
        return web.json_response(
            {"ok": False, "error": "Ava isn't in a server yet."}, status=400
        )
    try:
        data = await request.json()
    except Exception:
        return web.json_response({"ok": False, "error": "Bad request."}, status=400)
    section = data.get("section", "")
    values = data.get("values", {}) or {}
    try:
        message = await _apply_section(guild, section, values)
    except ValueError as exc:
        return web.json_response({"ok": False, "error": str(exc)}, status=400)
    except discord.HTTPException as exc:
        return web.json_response({"ok": False, "error": f"Discord error: {exc}"}, status=400)
    return web.json_response({"ok": True, "message": message})


async def _apply_section(guild: discord.Guild, section: str, values: dict) -> str:
    if section == "automod":
        for key, val in values.items():
            if key in store.AUTOMOD_DEFAULTS:
                store.set_automod(guild.id, key, int(val))
        return "Auto-mod settings applied."

    if section == "warn":
        for key, val in values.items():
            if key in store.DEFAULT_SETTINGS:
                store.set_setting(guild.id, key, int(val))
        return "Warning thresholds applied."

    if section == "security":
        from .cogs.security import LEVELS

        level = str(values.get("level", "medium")).lower()
        preset = LEVELS.get(level)
        if preset is None:
            raise ValueError("Unknown security level.")
        for key, val in preset["automod"].items():
            store.set_automod(guild.id, key, int(val))
        await guild.edit(
            verification_level=preset["verification"], reason="Dashboard security preset"
        )
        return f"Security set to {preset['label']} (verification: {preset['verification'].name})."

    if section == "reactionrole":
        from . import rroles

        channel = rroles.resolve_channel(guild, values.get("channel", ""))
        if channel is None:
            raise ValueError("Couldn't find that channel.")
        role_name = str(values.get("role_name", "")).strip()
        emoji = str(values.get("emoji", "")).strip()
        category = str(values.get("category", "")).strip() or "Roles"
        if not role_name or not emoji:
            raise ValueError("Role name and emoji are both required.")
        exclusive = bool(int(values.get("exclusive", 0) or 0))
        try:
            _msg, role = await rroles.add_role_entry(
                guild, channel, role_name, category, emoji, exclusive
            )
        except discord.Forbidden:
            raise ValueError(
                "I need Manage Roles + Manage Messages, and my role must be above the new role."
            )
        mode = "pick one" if exclusive else "pick any"
        return f"Added {role.name} ({emoji}) to #{channel.name} under “{category}” ({mode})."

    if section in ("rr_delete_role", "rr_delete_category", "rr_edit_category"):
        from . import rroles

        channel = rroles.resolve_channel(guild, values.get("channel", ""))
        if channel is None:
            raise ValueError("Couldn't find that channel.")
        try:
            if section == "rr_delete_role":
                await rroles.remove_role_entry(channel, str(values.get("emoji", "")))
                return "Removed that role from the panel."
            if section == "rr_delete_category":
                await rroles.remove_category(channel, str(values.get("category", "")))
                return "Removed that category."
            await rroles.edit_category(
                channel,
                str(values.get("category", "")),
                str(values.get("new_category", "")),
                bool(int(values.get("exclusive", 0) or 0)),
            )
            return "Category updated."
        except discord.Forbidden:
            raise ValueError("I need Manage Roles + Manage Messages for that.")

    raise ValueError("This control isn't wired to live settings yet.")


def create_app(bot) -> web.Application:
    app = web.Application()
    app["bot"] = bot
    app.router.add_get("/", _index)
    app.router.add_get("/health", _health)
    app.router.add_get("/api/state", _state)
    app.router.add_get("/api/rr", _rr_list)
    app.router.add_post("/api/apply", _apply)
    return app


async def start(port: int, bot) -> web.AppRunner:
    """Start the dashboard server and return its runner (for cleanup)."""
    runner = web.AppRunner(create_app(bot))
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", port)
    await site.start()
    log.info("Dashboard listening on 0.0.0.0:%s", port)
    return runner
