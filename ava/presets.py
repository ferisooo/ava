"""Ready-made server layouts for /build_server (no AI call needed).

Each preset uses the same plan shape the DeepSeek planner produces, so the
builder cog can treat presets and AI plans identically.
"""

from __future__ import annotations

from typing import Any

PRESETS: dict[str, dict[str, Any]] = {
    "gaming": {
        "label": "Gaming",
        "plan": {
            "server_name": "Gaming Server",
            "roles": [
                {"name": "Admin", "color": "#e74c3c", "hoist": True},
                {"name": "Moderator", "color": "#e67e22", "hoist": True},
                {"name": "Member", "color": "#3498db", "hoist": False},
            ],
            "categories": [
                {
                    "name": "📋 INFORMATION",
                    "channels": [
                        {"name": "welcome", "type": "text", "topic": "Welcome new members!"},
                        {"name": "rules", "type": "text"},
                        {"name": "announcements", "type": "text"},
                    ],
                },
                {
                    "name": "💬 COMMUNITY",
                    "channels": [
                        {"name": "general", "type": "text"},
                        {"name": "memes", "type": "text"},
                        {"name": "media", "type": "text"},
                        {"name": "off-topic", "type": "text"},
                    ],
                },
                {
                    "name": "🎮 GAMING",
                    "channels": [
                        {"name": "looking-for-group", "type": "text"},
                        {"name": "clips", "type": "text"},
                        {"name": "game-chat", "type": "text"},
                    ],
                },
                {
                    "name": "🔊 VOICE",
                    "channels": [
                        {"name": "General", "type": "voice"},
                        {"name": "Game Night", "type": "voice"},
                        {"name": "AFK", "type": "voice"},
                    ],
                },
            ],
        },
    },
    "community": {
        "label": "Community",
        "plan": {
            "server_name": "Community Server",
            "roles": [
                {"name": "Admin", "color": "#e74c3c", "hoist": True},
                {"name": "Moderator", "color": "#e67e22", "hoist": True},
                {"name": "Member", "color": "#2ecc71", "hoist": False},
            ],
            "categories": [
                {
                    "name": "📋 INFORMATION",
                    "channels": [
                        {"name": "welcome", "type": "text"},
                        {"name": "announcements", "type": "text"},
                        {"name": "rules", "type": "text"},
                    ],
                },
                {
                    "name": "💬 GENERAL",
                    "channels": [
                        {"name": "general", "type": "text"},
                        {"name": "introductions", "type": "text"},
                        {"name": "off-topic", "type": "text"},
                        {"name": "media", "type": "text"},
                    ],
                },
                {
                    "name": "🎉 FUN",
                    "channels": [
                        {"name": "memes", "type": "text"},
                        {"name": "polls", "type": "text"},
                        {"name": "suggestions", "type": "text"},
                    ],
                },
                {
                    "name": "🔊 VOICE CHANNELS",
                    "channels": [
                        {"name": "Lounge", "type": "voice"},
                        {"name": "Music", "type": "voice"},
                    ],
                },
            ],
        },
    },
    "creator": {
        "label": "Content Creator / Streamer",
        "plan": {
            "server_name": "Creator Server",
            "roles": [
                {"name": "Creator", "color": "#9b59b6", "hoist": True},
                {"name": "Moderator", "color": "#e67e22", "hoist": True},
                {"name": "Subscriber", "color": "#f1c40f", "hoist": True},
                {"name": "VIP", "color": "#e91e63", "hoist": False},
                {"name": "Member", "color": "#3498db", "hoist": False},
            ],
            "categories": [
                {
                    "name": "📢 INFO",
                    "channels": [
                        {"name": "welcome", "type": "text"},
                        {"name": "announcements", "type": "text"},
                        {"name": "rules", "type": "text"},
                        {"name": "socials", "type": "text"},
                    ],
                },
                {
                    "name": "💬 COMMUNITY",
                    "channels": [
                        {"name": "general", "type": "text"},
                        {"name": "clips", "type": "text"},
                        {"name": "fan-art", "type": "text"},
                        {"name": "off-topic", "type": "text"},
                    ],
                },
                {
                    "name": "🔴 STREAM",
                    "channels": [
                        {"name": "go-live", "type": "text"},
                        {"name": "stream-chat", "type": "text"},
                        {"name": "schedule", "type": "text"},
                    ],
                },
                {
                    "name": "🔊 VOICE",
                    "channels": [
                        {"name": "Hangout", "type": "voice"},
                        {"name": "Watch Party", "type": "voice"},
                    ],
                },
            ],
        },
    },
    "study": {
        "label": "Study / School",
        "plan": {
            "server_name": "Study Server",
            "roles": [
                {"name": "Teacher", "color": "#e74c3c", "hoist": True},
                {"name": "Moderator", "color": "#e67e22", "hoist": True},
                {"name": "Student", "color": "#3498db", "hoist": False},
            ],
            "categories": [
                {
                    "name": "📋 INFO",
                    "channels": [
                        {"name": "welcome", "type": "text"},
                        {"name": "rules", "type": "text"},
                        {"name": "announcements", "type": "text"},
                    ],
                },
                {
                    "name": "📚 STUDY",
                    "channels": [
                        {"name": "general", "type": "text"},
                        {"name": "homework-help", "type": "text"},
                        {"name": "resources", "type": "text"},
                        {"name": "questions", "type": "text"},
                    ],
                },
                {
                    "name": "🧪 SUBJECTS",
                    "channels": [
                        {"name": "math", "type": "text"},
                        {"name": "science", "type": "text"},
                        {"name": "languages", "type": "text"},
                        {"name": "history", "type": "text"},
                    ],
                },
                {
                    "name": "🔊 STUDY ROOMS",
                    "channels": [
                        {"name": "Study Room 1", "type": "voice"},
                        {"name": "Study Room 2", "type": "voice"},
                        {"name": "Focus", "type": "voice"},
                    ],
                },
            ],
        },
    },
    "business": {
        "label": "Business / Team",
        "plan": {
            "server_name": "Team Server",
            "roles": [
                {"name": "Admin", "color": "#e74c3c", "hoist": True},
                {"name": "Manager", "color": "#e67e22", "hoist": True},
                {"name": "Team", "color": "#3498db", "hoist": False},
                {"name": "Guest", "color": "#95a5a6", "hoist": False},
            ],
            "categories": [
                {
                    "name": "📋 GENERAL",
                    "channels": [
                        {"name": "announcements", "type": "text"},
                        {"name": "general", "type": "text"},
                        {"name": "introductions", "type": "text"},
                    ],
                },
                {
                    "name": "💼 WORK",
                    "channels": [
                        {"name": "projects", "type": "text"},
                        {"name": "tasks", "type": "text"},
                        {"name": "resources", "type": "text"},
                        {"name": "standup", "type": "text"},
                    ],
                },
                {
                    "name": "🛠️ DEV",
                    "channels": [
                        {"name": "dev-chat", "type": "text"},
                        {"name": "deployments", "type": "text"},
                        {"name": "bugs", "type": "text"},
                    ],
                },
                {
                    "name": "🔊 MEETINGS",
                    "channels": [
                        {"name": "Meeting Room", "type": "voice"},
                        {"name": "Daily Standup", "type": "voice"},
                    ],
                },
            ],
        },
    },
}
