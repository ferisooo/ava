"""Reaction-role panel logic shared by the web API and the cog.

A "panel" is one message per channel listing roles grouped by category. Each
category is either exclusive (pick one) or open (pick any). Reacting grants the
role; for exclusive categories, reacting also removes the member's other roles
and reactions in that category.
"""

from __future__ import annotations

import discord

from . import store


def _norm(value: str) -> str:
    return "".join(c for c in value.lower() if c.isalnum())


async def ensure_role(guild: discord.Guild, name: str) -> discord.Role:
    """Find a role by name (case-insensitive) or create it."""
    name = name.strip()
    for role in guild.roles:
        if role.name != "@everyone" and role.name.lower() == name.lower():
            return role
    return await guild.create_role(name=name[:100], reason="Ava reaction role")


def resolve_channel(guild: discord.Guild, query: str) -> discord.TextChannel | None:
    q = str(query).strip().lstrip("#")
    if q.startswith("<#") and q.endswith(">"):
        q = q[2:-1]
    if q.isdigit():
        ch = guild.get_channel(int(q))
        return ch if isinstance(ch, discord.TextChannel) else None
    qn = _norm(q)
    if not qn:
        return None
    for ch in guild.text_channels:
        if _norm(ch.name) == qn:
            return ch
    for ch in guild.text_channels:
        if qn in _norm(ch.name):
            return ch
    return None


def render_panel(entries: list[dict]) -> str:
    """Render the panel message body, grouped by category."""
    cats: dict[str, list[dict]] = {}
    order: list[str] = []
    for e in entries:
        cat = e["category"] or "Roles"
        if cat not in cats:
            cats[cat] = []
            order.append(cat)
        cats[cat].append(e)

    lines = ["# 🎭 Reaction Roles", "React below to get a role."]
    for cat in order:
        exclusive = any(x["exclusive"] for x in cats[cat])
        tag = "pick one" if exclusive else "pick any"
        lines.append(f"\n**{cat}** · *{tag}*")
        for e in cats[cat]:
            lines.append(f"{e['emoji']} — <@&{e['role_id']}>")
    return "\n".join(lines)[:2000]


async def add_role_entry(
    guild: discord.Guild,
    channel: discord.TextChannel,
    role_name: str,
    category: str,
    emoji: str,
    exclusive: bool,
) -> tuple[discord.Message, discord.Role]:
    """Create the role if needed, add it to the channel's panel, and react."""
    role = await ensure_role(guild, role_name)
    category = category.strip() or "Roles"
    emoji = emoji.strip()

    panel = store.get_rr_panel(channel.id)
    message: discord.Message | None = None
    if panel:
        try:
            message = await channel.fetch_message(panel["message_id"])
        except discord.NotFound:
            message = None
    if message is None:
        message = await channel.send("Setting up reaction roles…")
        store.set_rr_panel(channel.id, guild.id, message.id)

    store.add_reaction_role(
        guild.id, message.id, emoji, role.id, channel.id, category, 1 if exclusive else 0
    )
    # Keep the whole category consistent (one/many applies category-wide).
    store.set_category_exclusive(message.id, category, 1 if exclusive else 0)

    entries = store.list_message_reaction_roles(message.id)
    await message.edit(content=render_panel(entries))
    try:
        await message.add_reaction(emoji)
    except discord.HTTPException:
        pass
    return message, role
