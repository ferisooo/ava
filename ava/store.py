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
