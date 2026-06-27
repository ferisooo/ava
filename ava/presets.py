"""Themed presets for /build_server.

Each preset is a *theme prompt* (not a hand-written layout). When chosen, the
prompt is sent to DeepSeek's reasoning model, which designs the full server.
This keeps the actual layouts AI-generated and easy to expand — add a new
entry here and it shows up in the dropdown automatically.

Order is preserved in the slash-command dropdown. Discord allows up to 25
choices per option, so keep this list at 25 or fewer.
"""

from __future__ import annotations

PRESETS: dict[str, dict[str, str]] = {
    "gaming_hub": {
        "label": "Gaming Hub",
        "prompt": "A general gaming hub for a community of gamers. Info, rules and "
        "announcements; community chat (general, memes, media, clips); game "
        "discussion and looking-for-group channels; and several party voice "
        "channels. Roles for Admin, Moderator, and Members.",
    },
    "study_lounge": {
        "label": "Study Lounge",
        "prompt": "A calm study lounge for students to focus and help each other. "
        "Info and rules; study chat, homework help, resources; subject channels "
        "(math, science, languages); and quiet study voice rooms. Roles for "
        "Tutors/Moderators and Students.",
    },
    "creator_community": {
        "label": "Creator Community",
        "prompt": "A community server for a content creator or streamer. Info, "
        "announcements, socials; community chat, fan-art, clips; a go-live and "
        "stream section; and voice hangouts. Roles for Creator, Moderator, "
        "Subscriber, VIP, and Member.",
    },
    "anime_club": {
        "label": "Anime Club",
        "prompt": "An anime fan club. Info and rules; general anime discussion, "
        "seasonal anime, recommendations, manga, fan-art, and AMV/clips; "
        "spoiler-tagged channels; and watch-party voice rooms. Roles for Admin, "
        "Moderator, and activity-based member ranks.",
    },
    "music_den": {
        "label": "Music Den",
        "prompt": "A music community for sharing and discovering music. Info; "
        "general; genre channels; music-sharing; production and feedback; a "
        "bot-commands channel; and listening-party voice channels. Roles for "
        "Admin, Moderator, Artist, and Member.",
    },
    "movie_night": {
        "label": "Movie Night",
        "prompt": "A server for hosting movie nights and discussing films. Info; "
        "announcements and schedule; general film chat, recommendations, "
        "reviews; what-to-watch polls; and watch-party voice/stream rooms. Roles "
        "for Host, Moderator, and Member.",
    },
    "roleplay_realm": {
        "label": "Roleplay Realm",
        "prompt": "A roleplay server. Info and rules; lore; character creation and "
        "sheets; out-of-character chat; several in-character roleplay channels "
        "for different locations; and voice rooms. Roles for Game Master, "
        "Moderator, and Player.",
    },
    "tech_support": {
        "label": "Tech Support",
        "prompt": "A tech support and help community. Info and rules; "
        "announcements; general tech chat; categorized help channels (hardware, "
        "software, networking, coding); a solved/archive channel; and voice for "
        "screen-share help. Roles for Admin, Helper/Expert, and Member.",
    },
    "art_studio": {
        "label": "Art Studio",
        "prompt": "An art community for artists to share and improve. Info; "
        "general; art showcase; works-in-progress; critique and feedback; "
        "references and resources; commissions; challenges; and a voice room for "
        "drawing together. Roles for Admin, Moderator, Artist, and Commissioner.",
    },
    "fitness_crew": {
        "label": "Fitness Crew",
        "prompt": "A fitness and health community. Info and rules; general; "
        "workout logs; nutrition; progress pics; accountability; challenges; and "
        "voice for group sessions. Roles for Coach, Moderator, and Member.",
    },
    "crypto_corner": {
        "label": "Crypto Corner",
        "prompt": "A crypto and trading discussion server. Info, rules, and "
        "disclaimers; announcements; general crypto chat; market talk; charts "
        "and analysis; news; altcoins; NFTs; and voice rooms. Roles for Admin, "
        "Moderator, Trader, and Member.",
    },
    "book_club": {
        "label": "Book Club",
        "prompt": "A book club community. Info; current read; general book chat; "
        "recommendations; genre channels; reviews; quotes; and a voice room for "
        "discussions. Roles for Admin, Moderator, and Member.",
    },
    "friend_hangout": {
        "label": "Friend Hangout",
        "prompt": "A small, casual private hangout for a friend group. A welcome "
        "and info area; general chat, memes, media, music, and gaming; and a "
        "couple of voice channels. Keep it relaxed with a few fun roles.",
    },
    "school_server": {
        "label": "School Server",
        "prompt": "A school or class server for students. Info, rules, and "
        "announcements; general; homework help; resources; subject channels; "
        "club channels; and study voice rooms. Roles for Teacher, Moderator, "
        "and Student.",
    },
    "business_network": {
        "label": "Business Network",
        "prompt": "A professional business or team networking server. "
        "Announcements; general; introductions; projects; resources; a job "
        "board; networking; and meeting voice rooms. Roles for Admin, Manager, "
        "Team, and Guest.",
    },
    "minecraft_smp": {
        "label": "Minecraft SMP",
        "prompt": "A Minecraft SMP community. Info and rules; server info and IP; "
        "announcements; general; builds and screenshots; redstone; trading; "
        "suggestions; and voice channels for playing together. Roles for Admin, "
        "Moderator, Member, and Whitelisted.",
    },
    "roblox_squad": {
        "label": "Roblox Squad",
        "prompt": "A Roblox community or group server. Info and rules; "
        "announcements; general; game chat; clips and screenshots; "
        "looking-for-group; trading; and voice channels. Roles for Admin, "
        "Moderator, and Member.",
    },
    "esports_team": {
        "label": "Esports Team",
        "prompt": "An esports team or org server. Info; announcements; general; "
        "team strategy; scrims and schedule; VODs and review; recruitment; and "
        "team voice rooms. Roles for Owner, Coach, Player, Sub, and Fan.",
    },
    "podcast_community": {
        "label": "Podcast Community",
        "prompt": "A podcast community server. Info; announcements; episode "
        "discussion; general; topic suggestions; guest suggestions; feedback; "
        "and a recording/voice room. Roles for Host, Moderator, Listener, and "
        "Patron.",
    },
    "meme_central": {
        "label": "Meme Central",
        "prompt": "A meme and fun community. Info and rules; general; memes; "
        "dank memes; media; shitposting; reactions; and casual voice channels. "
        "Roles for Admin, Moderator, and fun member ranks.",
    },
}
