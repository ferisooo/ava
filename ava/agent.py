"""Natural-language agent: turn a request into Discord actions via DeepSeek.

Uses DeepSeek's tool-calling model (``deepseek-chat`` — the reasoner doesn't
support tools) in an agentic loop: the model picks a tool, we execute it
against the guild, feed the result back, and repeat until it produces a final
reply. All tools are additive/editing (no deletions) to keep this safe to run
from chat.
"""

from __future__ import annotations

import json
import logging
from typing import Any

import aiohttp
import discord

log = logging.getLogger("ava.agent")

MAX_STEPS = 6


class AgentError(RuntimeError):
    pass


# ---- Tool schemas (OpenAI-compatible, which DeepSeek mirrors) ---------------

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "rename_channel",
            "description": "Rename an existing channel. Use this to add an emoji or "
            "change the name of a channel (e.g. 'general' -> '🎮│general').",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string", "description": "Current channel name or #mention."},
                    "new_name": {"type": "string", "description": "The new channel name."},
                },
                "required": ["channel", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_category",
            "description": "Rename an existing category in place (e.g. add an emoji "
            "to a category like 'INFO' -> '📌 INFO'). Use this instead of creating a "
            "new category when the user wants to change an existing one.",
            "parameters": {
                "type": "object",
                "properties": {
                    "category": {"type": "string", "description": "Current category name."},
                    "new_name": {"type": "string", "description": "The new category name."},
                },
                "required": ["category", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "move_channel",
            "description": "Move an existing channel into a category (or out of one).",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "category": {"type": "string", "description": "Target category name, or empty for none."},
                },
                "required": ["channel"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "delete_channel",
            "description": "Delete a channel OR a category by name. Only use this when "
            "the user explicitly asks to delete that specific thing.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string", "description": "Name of the channel or category to delete."}
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_channel_topic",
            "description": "Set or change the topic/description of a text channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "topic": {"type": "string"},
                },
                "required": ["channel", "topic"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_text_channel",
            "description": "Create a new text channel, optionally inside a category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string", "description": "Optional category name."},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_voice_channel",
            "description": "Create a new voice channel, optionally inside a category.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "category": {"type": "string"},
                },
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_category",
            "description": "Create a new category (channel group).",
            "parameters": {
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "send_message",
            "description": "Post a message in a channel.",
            "parameters": {
                "type": "object",
                "properties": {
                    "channel": {"type": "string"},
                    "content": {"type": "string"},
                },
                "required": ["channel", "content"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "create_role",
            "description": "Create a new role, optionally with a hex color.",
            "parameters": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "color": {"type": "string", "description": "Hex like #3498db (optional)."},
                    "hoist": {"type": "boolean", "description": "Show separately in the member list."},
                },
                "required": ["name"],
            },
        },
    },
]

SYSTEM_PROMPT = """You are Ava, a friendly assistant that manages THIS Discord server using the provided tools.

Current server layout:
{context}

When the user names a channel, category, or role, match it to the real name above (ignore leading emojis or symbols when matching). Use the tools to carry out the request, then reply with a short, friendly confirmation of what you did.

Be decisive — for a clear request, just do it and give a one-line confirmation. Only ask a clarifying question when the request is genuinely ambiguous or missing something you truly can't infer. Do not list multiple options and ask the user to choose unless they explicitly ask you to.

Interpreting common requests:
- "add an emoji/symbol to #channel" → rename that channel to put the emoji/symbol at the START of its name (e.g. "roles" → "🎭roles"). If the user did NOT specify which emoji, pick a fitting one for the channel's purpose and proceed (mention which you chose).
- "add an emoji/symbol to the categories" → rename each category to prefix it with the emoji/symbol.
Never claim a channel "already has" an emoji or guess its purpose from nothing — use the server layout above.

Important:
- To change an EXISTING channel or category, use rename_channel / rename_category — do NOT create a new one.
- Only delete something when the user explicitly asks to delete that specific thing. Never delete anything that wasn't requested, and never bulk-delete.
- Rename each channel or category at most ONCE per request. Discord blocks renaming the same channel/category more than twice per 10 minutes, so never re-rename the same one to "fix" it.
- "Symbols" and "emojis" are different. If the user asks for SYMBOLS, use plain typographic/Unicode symbol characters such as ✦ ➤ ✧ ◈ ⊹ ★ » │ ╎ ❘ ✿ — NOT colorful emoji. Only use emoji when the user explicitly says "emoji".
"""


# ---- Name resolution --------------------------------------------------------

def _norm(value: str) -> str:
    return "".join(ch for ch in value.lower() if ch.isalnum())


def _resolve_channel(guild: discord.Guild, query: str) -> discord.abc.GuildChannel | None:
    q = (query or "").strip()
    if q.startswith("<#") and q.endswith(">"):
        try:
            return guild.get_channel(int(q[2:-1].lstrip("!")))
        except ValueError:
            pass
    qn = _norm(q)
    if not qn:
        return None
    for ch in guild.channels:
        if _norm(ch.name) == qn:
            return ch
    for ch in guild.channels:
        if qn in _norm(ch.name):
            return ch
    return None


def _resolve_category(guild: discord.Guild, query: str | None) -> discord.CategoryChannel | None:
    if not query:
        return None
    qn = _norm(query)
    for cat in guild.categories:
        if _norm(cat.name) == qn:
            return cat
    for cat in guild.categories:
        if qn and qn in _norm(cat.name):
            return cat
    return None


def _guild_context(guild: discord.Guild) -> str:
    lines: list[str] = ["Categories and channels:"]
    for cat in guild.categories:
        lines.append(f"  [{cat.name}]")
        for ch in cat.channels:
            kind = "voice" if isinstance(ch, discord.VoiceChannel) else "text"
            lines.append(f"    - {ch.name} ({kind})")
    loose = [c for c in guild.channels if c.category is None and not isinstance(c, discord.CategoryChannel)]
    if loose:
        lines.append("  (no category)")
        for ch in loose:
            kind = "voice" if isinstance(ch, discord.VoiceChannel) else "text"
            lines.append(f"    - {ch.name} ({kind})")
    roles = [r.name for r in reversed(guild.roles) if r.name != "@everyone"]
    lines.append("Roles: " + (", ".join(roles) if roles else "(none)"))
    return "\n".join(lines)[:4000]


# ---- Tool execution ---------------------------------------------------------

async def _execute(guild: discord.Guild, name: str, args: dict[str, Any]) -> str:
    try:
        if name == "rename_channel":
            ch = _resolve_channel(guild, args.get("channel", ""))
            if ch is None:
                return f"No channel matching '{args.get('channel')}'."
            await ch.edit(name=str(args["new_name"])[:100], reason="Ava agent")
            return f"Renamed to '{args['new_name']}'."

        if name == "rename_category":
            cat = _resolve_category(guild, args.get("category", ""))
            if cat is None:
                return f"No category matching '{args.get('category')}'."
            await cat.edit(name=str(args["new_name"])[:100], reason="Ava agent")
            return f"Renamed category to '{args['new_name']}'."

        if name == "move_channel":
            ch = _resolve_channel(guild, args.get("channel", ""))
            if ch is None or isinstance(ch, discord.CategoryChannel):
                return f"No movable channel matching '{args.get('channel')}'."
            cat = _resolve_category(guild, args.get("category"))
            await ch.edit(category=cat, reason="Ava agent")
            where = f"into '{cat.name}'" if cat else "out of its category"
            return f"Moved #{ch.name} {where}."

        if name == "delete_channel":
            target = _resolve_category(guild, args.get("name", "")) or _resolve_channel(
                guild, args.get("name", "")
            )
            if target is None:
                return f"Nothing matching '{args.get('name')}'."
            label = target.name
            await target.delete(reason="Ava agent")
            return f"Deleted '{label}'."

        if name == "set_channel_topic":
            ch = _resolve_channel(guild, args.get("channel", ""))
            if not isinstance(ch, discord.TextChannel):
                return "That isn't a text channel."
            await ch.edit(topic=str(args.get("topic", ""))[:1024], reason="Ava agent")
            return "Topic updated."

        if name == "create_text_channel":
            cat = _resolve_category(guild, args.get("category"))
            ch = await guild.create_text_channel(
                str(args["name"])[:100], category=cat, reason="Ava agent"
            )
            return f"Created text channel #{ch.name}."

        if name == "create_voice_channel":
            cat = _resolve_category(guild, args.get("category"))
            ch = await guild.create_voice_channel(
                str(args["name"])[:100], category=cat, reason="Ava agent"
            )
            return f"Created voice channel '{ch.name}'."

        if name == "create_category":
            cat = await guild.create_category(str(args["name"])[:100], reason="Ava agent")
            return f"Created category '{cat.name}'."

        if name == "send_message":
            ch = _resolve_channel(guild, args.get("channel", ""))
            if not isinstance(ch, (discord.TextChannel, discord.Thread)):
                return "Can't send a message there."
            await ch.send(str(args.get("content", ""))[:2000])
            return f"Message sent in #{ch.name}."

        if name == "create_role":
            kwargs: dict[str, Any] = {
                "name": str(args["name"])[:100],
                "hoist": bool(args.get("hoist", False)),
                "reason": "Ava agent",
            }
            if args.get("color"):
                try:
                    kwargs["colour"] = discord.Colour.from_str(str(args["color"]))
                except ValueError:
                    pass
            role = await guild.create_role(**kwargs)
            return f"Created role '{role.name}'."

        return f"Unknown tool '{name}'."
    except discord.Forbidden:
        return "I don't have permission for that action."
    except discord.RateLimited as exc:
        # Discord caps renames at ~2 per 10 min per channel. Report and move on
        # instead of blocking — the bot is configured to raise rather than wait.
        return (
            f"Rate limited by Discord (retry in ~{int(exc.retry_after)}s). "
            "Renaming the same channel/category more than twice in 10 minutes is "
            "blocked — skip it for now."
        )
    except discord.HTTPException as exc:
        return f"Discord rejected that: {exc}"


# ---- The agent loop ---------------------------------------------------------

async def _chat(session, base_url, api_key, model, messages):
    payload = {"model": model, "messages": messages, "tools": TOOLS, "tool_choice": "auto"}
    headers = {"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"}
    async with session.post(f"{base_url}/chat/completions", json=payload, headers=headers) as resp:
        body = await resp.text()
        if resp.status != 200:
            raise AgentError(f"DeepSeek HTTP {resp.status}: {body[:200]}")
        return json.loads(body)


async def run_agent(
    guild: discord.Guild,
    request: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> str:
    """Run the tool-calling loop and return Ava's final reply text."""
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM_PROMPT.format(context=_guild_context(guild))},
        {"role": "user", "content": request},
    ]
    timeout = aiohttp.ClientTimeout(total=120)
    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for _ in range(MAX_STEPS):
                data = await _chat(session, base_url, api_key, model, messages)
                msg = data["choices"][0]["message"]
                tool_calls = msg.get("tool_calls")
                if not tool_calls:
                    return (msg.get("content") or "Done.").strip()

                messages.append(
                    {"role": "assistant", "content": msg.get("content"), "tool_calls": tool_calls}
                )
                for call in tool_calls:
                    fn = call["function"]
                    try:
                        args = json.loads(fn.get("arguments") or "{}")
                    except json.JSONDecodeError:
                        args = {}
                    result = await _execute(guild, fn["name"], args)
                    log.info("agent tool %s(%s) -> %s", fn["name"], args, result)
                    messages.append(
                        {"role": "tool", "tool_call_id": call["id"], "content": result}
                    )
    except aiohttp.ClientError as exc:
        raise AgentError(f"Could not reach DeepSeek: {exc}") from exc

    return "I took some steps but ran out of room to finish — check the result."
