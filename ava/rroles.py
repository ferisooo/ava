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
        # All roles in a category on one horizontal line.
        roles = "   ".join(f"{e['emoji']} <@&{e['role_id']}>" for e in cats[cat])
        lines.append(roles)
    return "\n".join(lines)[:2000]


def _panel_handle(guild: discord.Guild, channel: discord.TextChannel):
    """Return a (partial) message for the channel's panel — no fetch needed."""
    panel = store.get_rr_panel(channel.id)
    if panel:
        return channel.get_partial_message(panel["message_id"])
    return None


async def _render_or_recreate(guild, channel, message):
    """Edit the panel; if it was deleted, recreate it and re-key entries."""
    entries = store.list_message_reaction_roles(message.id)
    body = render_panel(entries)
    try:
        await message.edit(content=body)
        return message
    except discord.NotFound:
        pass
    new = await channel.send(body)
    for e in entries:
        store.add_reaction_role(
            e["guild_id"], new.id, e["emoji"], e["role_id"],
            channel.id, e["category"], e["exclusive"],
        )
        store.remove_reaction_role(message.id, e["emoji"])
    store.set_rr_panel(channel.id, guild.id, new.id)
    return new


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

    message = _panel_handle(guild, channel)
    if message is None:
        message = await channel.send("Setting up reaction roles…")
        store.set_rr_panel(channel.id, guild.id, message.id)

    store.add_reaction_role(
        guild.id, message.id, emoji, role.id, channel.id, category, 1 if exclusive else 0
    )
    # Keep the whole category consistent (one/many applies category-wide).
    store.set_category_exclusive(message.id, category, 1 if exclusive else 0)

    message = await _render_or_recreate(guild, channel, message)
    try:
        # PartialEmoji.from_str handles both unicode and custom <:name:id> forms.
        await message.add_reaction(discord.PartialEmoji.from_str(emoji))
    except discord.HTTPException:
        pass
    return message, role


async def _panel_message(channel: discord.TextChannel):
    panel = store.get_rr_panel(channel.id)
    if not panel:
        return None
    return channel.get_partial_message(panel["message_id"])


async def refresh_panel(channel: discord.TextChannel) -> None:
    """Re-render the panel message, or delete it if no entries remain."""
    message = await _panel_message(channel)
    if message is None:
        return
    entries = store.list_message_reaction_roles(message.id)
    if entries:
        try:
            await message.edit(content=render_panel(entries))
        except discord.NotFound:
            store.remove_rr_panel(channel.id)
    else:
        try:
            await message.delete()
        except discord.HTTPException:
            pass
        store.remove_rr_panel(channel.id)


async def remove_role_entry(channel: discord.TextChannel, emoji: str) -> None:
    message = await _panel_message(channel)
    if message is None:
        raise ValueError("No reaction-role panel in that channel.")
    store.remove_reaction_role(message.id, emoji)
    try:
        await message.clear_reaction(discord.PartialEmoji.from_str(emoji))
    except discord.HTTPException:
        pass
    await refresh_panel(channel)


async def remove_category(channel: discord.TextChannel, category: str) -> None:
    message = await _panel_message(channel)
    if message is None:
        raise ValueError("No reaction-role panel in that channel.")
    for e in store.list_category_reaction_roles(message.id, category):
        store.remove_reaction_role(message.id, e["emoji"])
        try:
            await message.clear_reaction(discord.PartialEmoji.from_str(e["emoji"]))
        except discord.HTTPException:
            pass
    await refresh_panel(channel)


async def edit_category(
    channel: discord.TextChannel,
    category: str,
    new_category: str,
    exclusive: bool,
) -> None:
    message = await _panel_message(channel)
    if message is None:
        raise ValueError("No reaction-role panel in that channel.")
    new_category = new_category.strip() or category
    for e in store.list_category_reaction_roles(message.id, category):
        # Same (message_id, emoji) primary key -> updates the row in place.
        store.add_reaction_role(
            e["guild_id"], message.id, e["emoji"], e["role_id"],
            channel.id, new_category, 1 if exclusive else 0,
        )
    await refresh_panel(channel)
