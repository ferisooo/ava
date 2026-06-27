"""DeepSeek reasoning-model client for designing Discord server layouts.

DeepSeek exposes an OpenAI-compatible HTTP API, so we call it directly with
aiohttp (which ships with discord.py) — no extra dependency to install on the
host. We use the ``deepseek-reasoner`` thinking model and ask it to return a
plain JSON plan that the builder cog turns into real channels and roles.
"""

from __future__ import annotations

import json
from typing import Any

import aiohttp

# Hard caps so a runaway plan can't try to create hundreds of channels.
MAX_ROLES = 25
MAX_CATEGORIES = 12
MAX_CHANNELS_PER_CATEGORY = 25
MAX_TOTAL_CHANNELS = 80

SYSTEM_PROMPT = """You are an expert Discord server architect.

Given a description of what a server is for, design a complete, well-organized
structure: categories, the channels inside each, and a set of roles.

Respond with ONLY a single JSON object — no markdown fences, no commentary
before or after. Use exactly this shape:

{
  "server_name": "a fitting name",
  "roles": [
    {"name": "Moderator", "color": "#e74c3c", "hoist": true, "mentionable": false}
  ],
  "categories": [
    {
      "name": "INFORMATION",
      "channels": [
        {"name": "welcome", "type": "text", "topic": "short channel topic"},
        {"name": "general-voice", "type": "voice"}
      ]
    }
  ]
}

Rules:
- Channel names: lowercase, words separated by hyphens, no spaces or emojis.
- "type" is either "text" or "voice". "topic" is optional and only for text.
- Colors are hex strings like "#3498db".
- Keep it sensible: at most 8 categories, at most 8 channels per category,
  at most 10 roles. Quality over quantity.
- Order categories from most important (info/rules) to least.
"""


class DeepSeekError(RuntimeError):
    """Raised when the DeepSeek API call or its response can't be used."""


async def plan_server(
    description: str,
    *,
    api_key: str,
    model: str,
    base_url: str,
) -> dict[str, Any]:
    """Ask DeepSeek to design a server and return the parsed, trimmed plan."""
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": f"Design a Discord server for this:\n\n{description}",
            },
        ],
        "stream": False,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    # The reasoner model thinks before answering, so allow a generous timeout.
    timeout = aiohttp.ClientTimeout(total=180)

    try:
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.post(
                f"{base_url}/chat/completions", json=payload, headers=headers
            ) as resp:
                body = await resp.text()
                if resp.status != 200:
                    raise DeepSeekError(
                        f"DeepSeek returned HTTP {resp.status}: {body[:200]}"
                    )
                data = json.loads(body)
    except aiohttp.ClientError as exc:
        raise DeepSeekError(f"Could not reach DeepSeek: {exc}") from exc

    try:
        content = data["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        raise DeepSeekError("DeepSeek response was not in the expected format.") from exc

    plan = _parse_plan(content)
    return _trim_plan(plan)


def _parse_plan(content: str) -> dict[str, Any]:
    """Extract a JSON object from the model's reply, tolerating stray text."""
    text = (content or "").strip()
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1 or end < start:
        raise DeepSeekError("DeepSeek did not return a JSON object.")
    snippet = text[start : end + 1]
    try:
        plan = json.loads(snippet)
    except json.JSONDecodeError as exc:
        raise DeepSeekError(f"DeepSeek returned invalid JSON: {exc}") from exc
    if not isinstance(plan, dict):
        raise DeepSeekError("DeepSeek returned JSON that wasn't an object.")
    return plan


def _trim_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Clamp the plan to safe sizes so a build can't run away."""
    roles = [r for r in plan.get("roles", []) if isinstance(r, dict) and r.get("name")]
    plan["roles"] = roles[:MAX_ROLES]

    total_channels = 0
    trimmed_categories = []
    for category in plan.get("categories", [])[:MAX_CATEGORIES]:
        if not isinstance(category, dict) or not category.get("name"):
            continue
        channels = [
            c
            for c in category.get("channels", [])
            if isinstance(c, dict) and c.get("name")
        ][:MAX_CHANNELS_PER_CATEGORY]

        room = MAX_TOTAL_CHANNELS - total_channels
        if room <= 0:
            channels = []
        else:
            channels = channels[:room]
        total_channels += len(channels)

        category["channels"] = channels
        trimmed_categories.append(category)

    plan["categories"] = trimmed_categories
    return plan
