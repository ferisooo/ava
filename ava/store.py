"""Persistent storage for moderation: infractions, tempbans, and settings.

Uses a small SQLite database on disk (``data/ava.db``). The file is gitignored,
so it survives the host's git-pull-on-restart and keeps its history.
"""

from __future__ import annotations

import sqlite3
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DB_PATH = Path("data/ava.db")

DEFAULT_SETTINGS = {
    "warn_mute_threshold": 3,   # warnings before an auto-mute
    "warn_mute_minutes": 60,    # how long the auto-mute lasts
    "warn_kick_threshold": 5,   # warnings before an auto-kick
    "log_channel_id": 0,        # 0 = no mod-log channel
}

# Per-guild auto-mod / anti-raid config. All values are ints (bools as 0/1).
AUTOMOD_DEFAULTS = {
    "enabled": 0,                # master switch
    "block_invites": 1,         # delete Discord invite links
    "block_mass_mentions": 1,   # delete messages with too many mentions
    "mention_limit": 5,         # mentions allowed before it's "mass"
    "block_spam": 1,            # delete on message-rate spam
    "spam_count": 5,            # messages...
    "spam_seconds": 5,          # ...within this many seconds = spam
    "block_caps": 1,            # delete excessive-caps messages
    "caps_min_len": 10,         # only check messages at least this long
    "caps_percent": 70,         # % uppercase to count as shouting
    "escalate_strikes": 3,      # auto-mod hits...
    "escalate_minutes": 10,     # ...within 60s -> timeout this long
    "raid_enabled": 1,          # detect mass joins
    "raid_joins": 10,           # joins...
    "raid_seconds": 10,         # ...within this many seconds = raid
    "min_account_age_days": 0,  # kick accounts younger than this on join (0 = off)
    "alert_channel_id": 0,      # where to post raid alerts (0 = system channel)
}


def _conn() -> sqlite3.Connection:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init() -> None:
    with _conn() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS infractions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                moderator_id INTEGER NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                created_at TEXT NOT NULL,
                expires_at TEXT
            );
            CREATE TABLE IF NOT EXISTS tempbans (
                guild_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                unban_ts REAL NOT NULL,
                PRIMARY KEY (guild_id, user_id)
            );
            CREATE TABLE IF NOT EXISTS settings (
                guild_id INTEGER PRIMARY KEY,
                warn_mute_threshold INTEGER NOT NULL,
                warn_mute_minutes INTEGER NOT NULL,
                warn_kick_threshold INTEGER NOT NULL,
                log_channel_id INTEGER NOT NULL
            );
            """
        )
        automod_cols = ", ".join(f"{key} INTEGER NOT NULL" for key in AUTOMOD_DEFAULTS)
        conn.execute(
            f"CREATE TABLE IF NOT EXISTS automod (guild_id INTEGER PRIMARY KEY, {automod_cols})"
        )
        # Migrate older reaction_roles tables that predate the panel columns.
        for col, ddl in (
            ("channel_id", "INTEGER NOT NULL DEFAULT 0"),
            ("category", "TEXT NOT NULL DEFAULT ''"),
            ("exclusive", "INTEGER NOT NULL DEFAULT 0"),
        ):
            try:
                conn.execute(f"ALTER TABLE reaction_roles ADD COLUMN {col} {ddl}")
            except sqlite3.OperationalError:
                pass
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reaction_roles (
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL DEFAULT 0,
                message_id INTEGER NOT NULL,
                emoji TEXT NOT NULL,
                role_id INTEGER NOT NULL,
                category TEXT NOT NULL DEFAULT '',
                exclusive INTEGER NOT NULL DEFAULT 0,
                PRIMARY KEY (message_id, emoji)
            );
            CREATE TABLE IF NOT EXISTS rr_panels (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                message_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS welcome (
                guild_id INTEGER PRIMARY KEY,
                enabled INTEGER NOT NULL DEFAULT 0,
                channel_id INTEGER NOT NULL DEFAULT 0,
                title TEXT NOT NULL DEFAULT 'Welcome!',
                description TEXT NOT NULL DEFAULT 'Welcome {user} to {server}! You are member #{count}.',
                color INTEGER NOT NULL DEFAULT 5793266,
                image_url TEXT NOT NULL DEFAULT ''
            );
            CREATE TABLE IF NOT EXISTS stickies (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                last_message_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS voice_hubs (
                hub_channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                category_id INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS temp_voice (
                channel_id INTEGER PRIMARY KEY,
                guild_id INTEGER NOT NULL,
                owner_id INTEGER NOT NULL
            );
            CREATE TABLE IF NOT EXISTS diary (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ---- Infractions ------------------------------------------------------------

def add_infraction(
    guild_id: int,
    user_id: int,
    moderator_id: int,
    action: str,
    reason: str | None,
    expires_at: str | None = None,
) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO infractions "
            "(guild_id, user_id, moderator_id, action, reason, created_at, expires_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, user_id, moderator_id, action, reason, _now_iso(), expires_at),
        )
        return int(cur.lastrowid)


def get_infractions(
    guild_id: int, user_id: int, action: str | None = None
) -> list[dict[str, Any]]:
    query = "SELECT * FROM infractions WHERE guild_id = ? AND user_id = ?"
    params: list[Any] = [guild_id, user_id]
    if action is not None:
        query += " AND action = ?"
        params.append(action)
    query += " ORDER BY id DESC"
    with _conn() as conn:
        return [dict(row) for row in conn.execute(query, params).fetchall()]


def warn_count(guild_id: int, user_id: int) -> int:
    with _conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM infractions "
            "WHERE guild_id = ? AND user_id = ? AND action = 'warn'",
            (guild_id, user_id),
        ).fetchone()
        return int(row["n"])


def remove_infraction(guild_id: int, infraction_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM infractions WHERE guild_id = ? AND id = ?",
            (guild_id, infraction_id),
        )
        return cur.rowcount > 0


def clear_warnings(guild_id: int, user_id: int) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM infractions "
            "WHERE guild_id = ? AND user_id = ? AND action = 'warn'",
            (guild_id, user_id),
        )
        return cur.rowcount


# ---- Tempbans ---------------------------------------------------------------

def add_tempban(guild_id: int, user_id: int, unban_ts: float) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO tempbans (guild_id, user_id, unban_ts) "
            "VALUES (?, ?, ?)",
            (guild_id, user_id, unban_ts),
        )


def due_tempbans(now: float | None = None) -> list[dict[str, Any]]:
    now = time.time() if now is None else now
    with _conn() as conn:
        rows = conn.execute(
            "SELECT * FROM tempbans WHERE unban_ts <= ?", (now,)
        ).fetchall()
        return [dict(r) for r in rows]


def remove_tempban(guild_id: int, user_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "DELETE FROM tempbans WHERE guild_id = ? AND user_id = ?",
            (guild_id, user_id),
        )


# ---- Settings ---------------------------------------------------------------

def get_settings(guild_id: int) -> dict[str, int]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM settings WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return dict(DEFAULT_SETTINGS)
    return {key: int(row[key]) for key in DEFAULT_SETTINGS}


def set_setting(guild_id: int, key: str, value: int) -> None:
    if key not in DEFAULT_SETTINGS:
        raise KeyError(key)
    current = get_settings(guild_id)
    current[key] = value
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO settings "
            "(guild_id, warn_mute_threshold, warn_mute_minutes, warn_kick_threshold, log_channel_id) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                guild_id,
                current["warn_mute_threshold"],
                current["warn_mute_minutes"],
                current["warn_kick_threshold"],
                current["log_channel_id"],
            ),
        )


# ---- Auto-mod settings ------------------------------------------------------

def get_automod(guild_id: int) -> dict[str, int]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM automod WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return dict(AUTOMOD_DEFAULTS)
    return {key: int(row[key]) for key in AUTOMOD_DEFAULTS}


def set_automod(guild_id: int, key: str, value: int) -> None:
    if key not in AUTOMOD_DEFAULTS:
        raise KeyError(key)
    current = get_automod(guild_id)
    current[key] = value
    keys = list(AUTOMOD_DEFAULTS)
    columns = ", ".join(["guild_id"] + keys)
    placeholders = ", ".join("?" * (len(keys) + 1))
    with _conn() as conn:
        conn.execute(
            f"INSERT OR REPLACE INTO automod ({columns}) VALUES ({placeholders})",
            [guild_id] + [current[k] for k in keys],
        )


# ---- Reaction roles ---------------------------------------------------------

def add_reaction_role(
    guild_id: int,
    message_id: int,
    emoji: str,
    role_id: int,
    channel_id: int = 0,
    category: str = "",
    exclusive: int = 0,
) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO reaction_roles "
            "(guild_id, channel_id, message_id, emoji, role_id, category, exclusive) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, message_id, emoji, role_id, category, exclusive),
        )


def remove_reaction_role(message_id: int, emoji: str) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM reaction_roles WHERE message_id = ? AND emoji = ?",
            (message_id, emoji),
        )
        return cur.rowcount > 0


def get_reaction_role(message_id: int, emoji: str) -> Optional[int]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT role_id FROM reaction_roles WHERE message_id = ? AND emoji = ?",
            (message_id, emoji),
        ).fetchone()
        return int(row["role_id"]) if row else None


def get_reaction_role_full(message_id: int, emoji: str) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM reaction_roles WHERE message_id = ? AND emoji = ?",
            (message_id, emoji),
        ).fetchone()
        return dict(row) if row else None


def list_message_reaction_roles(message_id: int) -> list[dict[str, Any]]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM reaction_roles WHERE message_id = ? ORDER BY rowid",
                (message_id,),
            ).fetchall()
        ]


def list_category_reaction_roles(message_id: int, category: str) -> list[dict[str, Any]]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM reaction_roles WHERE message_id = ? AND category = ?",
                (message_id, category),
            ).fetchall()
        ]


def set_category_exclusive(message_id: int, category: str, exclusive: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE reaction_roles SET exclusive = ? WHERE message_id = ? AND category = ?",
            (exclusive, message_id, category),
        )


def set_rr_panel(channel_id: int, guild_id: int, message_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO rr_panels (channel_id, guild_id, message_id) "
            "VALUES (?, ?, ?)",
            (channel_id, guild_id, message_id),
        )


def get_rr_panel(channel_id: int) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM rr_panels WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None


def list_reaction_roles(guild_id: int) -> list[dict[str, Any]]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM reaction_roles WHERE guild_id = ?", (guild_id,)
            ).fetchall()
        ]


# ---- Welcome ----------------------------------------------------------------

WELCOME_DEFAULTS = {
    "enabled": 0,
    "channel_id": 0,
    "title": "Welcome!",
    "description": "Welcome {user} to {server}! You are member #{count}.",
    "color": 5793266,
    "image_url": "",
}


def get_welcome(guild_id: int) -> dict[str, Any]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM welcome WHERE guild_id = ?", (guild_id,)
        ).fetchone()
    if row is None:
        return dict(WELCOME_DEFAULTS)
    return {key: row[key] for key in WELCOME_DEFAULTS}


def set_welcome(guild_id: int, **fields: Any) -> None:
    current = get_welcome(guild_id)
    current.update({k: v for k, v in fields.items() if k in WELCOME_DEFAULTS})
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO welcome "
            "(guild_id, enabled, channel_id, title, description, color, image_url) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                guild_id,
                int(current["enabled"]),
                int(current["channel_id"]),
                current["title"],
                current["description"],
                int(current["color"]),
                current["image_url"],
            ),
        )


# ---- Sticky messages --------------------------------------------------------

def set_sticky(channel_id: int, guild_id: int, content: str) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO stickies (channel_id, guild_id, content, last_message_id) "
            "VALUES (?, ?, ?, COALESCE((SELECT last_message_id FROM stickies WHERE channel_id = ?), 0))",
            (channel_id, guild_id, content, channel_id),
        )


def get_sticky(channel_id: int) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM stickies WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None


def update_sticky_message(channel_id: int, message_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "UPDATE stickies SET last_message_id = ? WHERE channel_id = ?",
            (message_id, channel_id),
        )


def remove_sticky(channel_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute("DELETE FROM stickies WHERE channel_id = ?", (channel_id,))
        return cur.rowcount > 0


def list_stickies(guild_id: int) -> list[dict[str, Any]]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM stickies WHERE guild_id = ?", (guild_id,)
            ).fetchall()
        ]


def sticky_channel_ids() -> set[int]:
    with _conn() as conn:
        return {int(r["channel_id"]) for r in conn.execute("SELECT channel_id FROM stickies").fetchall()}


# ---- Temp voice -------------------------------------------------------------

def add_voice_hub(hub_channel_id: int, guild_id: int, category_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO voice_hubs (hub_channel_id, guild_id, category_id) "
            "VALUES (?, ?, ?)",
            (hub_channel_id, guild_id, category_id),
        )


def remove_voice_hub(hub_channel_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM voice_hubs WHERE hub_channel_id = ?", (hub_channel_id,)
        )
        return cur.rowcount > 0


def get_voice_hub(hub_channel_id: int) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM voice_hubs WHERE hub_channel_id = ?", (hub_channel_id,)
        ).fetchone()
        return dict(row) if row else None


def list_voice_hubs(guild_id: int) -> list[dict[str, Any]]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM voice_hubs WHERE guild_id = ?", (guild_id,)
            ).fetchall()
        ]


def add_temp_voice(channel_id: int, guild_id: int, owner_id: int) -> None:
    with _conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO temp_voice (channel_id, guild_id, owner_id) "
            "VALUES (?, ?, ?)",
            (channel_id, guild_id, owner_id),
        )


def remove_temp_voice(channel_id: int) -> None:
    with _conn() as conn:
        conn.execute("DELETE FROM temp_voice WHERE channel_id = ?", (channel_id,))


def get_temp_voice(channel_id: int) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM temp_voice WHERE channel_id = ?", (channel_id,)
        ).fetchone()
        return dict(row) if row else None


def all_temp_voice() -> list[dict[str, Any]]:
    with _conn() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM temp_voice").fetchall()]


# ---- Diary ------------------------------------------------------------------

def add_diary(user_id: int, content: str) -> int:
    with _conn() as conn:
        cur = conn.execute(
            "INSERT INTO diary (user_id, content, created_at) VALUES (?, ?, ?)",
            (user_id, content, _now_iso()),
        )
        return int(cur.lastrowid)


def list_diary(user_id: int) -> list[dict[str, Any]]:
    with _conn() as conn:
        return [
            dict(r)
            for r in conn.execute(
                "SELECT * FROM diary WHERE user_id = ? ORDER BY id DESC", (user_id,)
            ).fetchall()
        ]


def get_diary(user_id: int, entry_id: int) -> Optional[dict[str, Any]]:
    with _conn() as conn:
        row = conn.execute(
            "SELECT * FROM diary WHERE user_id = ? AND id = ?", (user_id, entry_id)
        ).fetchone()
        return dict(row) if row else None


def delete_diary(user_id: int, entry_id: int) -> bool:
    with _conn() as conn:
        cur = conn.execute(
            "DELETE FROM diary WHERE user_id = ? AND id = ?", (user_id, entry_id)
        )
        return cur.rowcount > 0
