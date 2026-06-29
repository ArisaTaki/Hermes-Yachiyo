"""Shared media app name normalization for agent entrypoints."""

from __future__ import annotations

import re


MUSIC_APP_ALIASES: dict[str, str] = {
    "applemusic": "Music",
    "music": "Music",
    "musicapp": "Music",
    "musicplayer": "Music",
    "youtubemusic": "YouTube Music",
    "qqmusic": "QQ音乐",
    "qq音乐": "QQ音乐",
    "spotify": "Spotify",
    "网易云": "网易云音乐",
    "网易云音乐": "网易云音乐",
    "netease": "网易云音乐",
    "neteasecloud": "网易云音乐",
    "neteasecloudmusic": "网易云音乐",
    "neteasemusic": "网易云音乐",
    "cloudmusic": "网易云音乐",
    "苹果音乐": "Music",
    "音乐": "Music",
    "音乐app": "Music",
    "音乐应用": "Music",
    "音乐软件": "Music",
    "音乐播放器": "Music",
    "播放器": "Music",
}

MUSIC_APP_COMPACTS = frozenset(MUSIC_APP_ALIASES)


def music_app_name_from_text(text: str) -> str:
    lowered = str(text or "").lower()
    if re.search(r"spotify", lowered):
        return "Spotify"
    if re.search(r"youtube\s*music", lowered):
        return "YouTube Music"
    if re.search(r"网易云|netease", lowered):
        return "网易云音乐"
    if re.search(r"qq\s*音乐|qq\s*music", lowered):
        return "QQ音乐"
    if re.search(r"apple\s*music|苹果音乐|音乐(?:应用|app|软件|播放器)|\bmusic\s+(?:app|player)\b", lowered):
        return "Music"
    return ""


def known_music_app_name(value: str) -> str:
    return MUSIC_APP_ALIASES.get(compact_music_app_name(value), "")


def is_known_music_app_compact(compact: str) -> bool:
    return str(compact or "").strip().lower() in MUSIC_APP_COMPACTS


def compact_music_app_name(value: str) -> str:
    return re.sub(r"[\s._-]+", "", str(value or "").strip().lower())
