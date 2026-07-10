"""Compatibility app-name hints for planner execution.

The planner should prefer desktop discovery when available. This module keeps
legacy alias normalization behind a single boundary until app-name resolution
can be replaced by discovered app metadata.
"""

from __future__ import annotations

import re

from apps.shell.agent.runtime.app_aliases import (
    APP_ALIASES,
    COMMUNICATION_APP_NAMES,
    EMAIL_APP_NAMES,
    compact_app_alias,
)
from apps.shell.agent.runtime.media_apps import music_app_name_from_text

GENERIC_APP_ALIAS_COMPACTS = frozenset(
    {
        "browser",
        "defaultbrowser",
        "systemdefaultbrowser",
        "defaultwebbrowser",
        "webbrowser",
        "浏览器",
        "默认浏览器",
        "系统默认浏览器",
        "默认网页浏览器",
        "文件管理器",
        "文件浏览器",
        "terminal",
        "终端",
        "命令行",
        "musicplayer",
        "音乐播放器",
        "播放器",
    }
)


def _legacy_app_name_compact(value: str) -> str:
    app_name = str(value or "").strip()
    if not app_name:
        return ""
    app_name = re.sub(r"\s*(?:for\s+me)$", "", app_name, flags=re.IGNORECASE).strip()
    app_name = re.sub(
        r"\s*(?:客户端|桌面客户端|桌面版|desktop\s+client|client)$",
        "",
        app_name,
        flags=re.IGNORECASE,
    ).strip()
    compact = compact_app_alias(app_name)
    if compact not in APP_ALIASES:
        without_article = re.sub(
            r"^(?:a|an|the)\s+",
            "",
            app_name,
            flags=re.IGNORECASE,
        ).strip()
        compact = compact_app_alias(without_article)
    if compact in {"webbrowser", "webpage", "webpages", "web"}:
        compact = "browser"
    return compact


def _legacy_alias_lookup(compact: str, app_name: str) -> str:
    return APP_ALIASES.get(compact, app_name)


def legacy_app_name_hint(value: str) -> str:
    app_name = str(value or "").strip()
    if not app_name:
        return ""
    compact = _legacy_app_name_compact(app_name)
    if compact in GENERIC_APP_ALIAS_COMPACTS:
        return app_name
    return _legacy_alias_lookup(compact, app_name)


def is_legacy_app_name_hint(value: str) -> bool:
    app_name = str(value or "").strip()
    if not app_name:
        return False
    compact = _legacy_app_name_compact(app_name)
    if compact in GENERIC_APP_ALIAS_COMPACTS:
        return False
    return compact in APP_ALIASES


def compact_app_name_hint(value: str) -> str:
    return compact_app_alias(value)


def supports_new_message_app_hint(value: str) -> bool:
    return str(value or "").strip() in (COMMUNICATION_APP_NAMES | EMAIL_APP_NAMES)


def explicit_app_action_target_hint(value: str) -> str:
    text = str(value or "").strip()
    patterns = (
        r"^(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?"
        r"(?:直接)?(?:把|将)?\s*(?P<app_postposed>[^。！？!?，,\n]{1,60}?)\s*"
        r"(?:打开起来|启动起来|运行起来|拉起来|拉起|开启起来|开起来|打开|启动|运行|开启|开)"
        r"\s*(?:了|一下|下|起来)?(?:吧|吗|嘛|呢|么)?[?？。！!]*$",
        r"^(?:你)?(?:可不可以帮我|可以帮我|能帮我|能不能帮我|帮我|请|麻烦|能否|能不能|能(?!不能|否)|可以)?"
        r"(?:直接)?(?:打开起来|启动起来|运行起来|拉起来|拉起|开启起来|开起来|开了|打开|启动|运行|开启|开)"
        r"(?:一下|下)?\s*"
        r"(?P<app_prefixed>[^。！？!?，,\n]{1,60}?)\s*(?:起来)?"
        r"(?:吧|吗|嘛|呢|么)?[?？。！!]*$",
        r"^(?:(?:can|could|would)\s+you\s+)?(?:please\s+)?"
        r"(?:open|launch|start(?:\s+up)?|focus|activate)\s+"
        r"(?P<app_en>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)"
        r"(?:\s+for\s+me)?(?:\s+please)?[.!?]*$",
        r"^bring\s+(?P<app_bring_up>[A-Za-z][A-Za-z0-9 ._-]{1,60}?)\s+up"
        r"(?=\s*(?:\b(?:and|then)\b|[.!?]|$))",
    )
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if not match:
            continue
        return str(
            next(
                (
                    item
                    for item in match.groupdict().values()
                    if item is not None and str(item).strip()
                ),
                "",
            )
        ).strip()
    return ""


def explicit_known_app_action_target_hint(value: str) -> str:
    app_name = explicit_app_action_target_hint(value)
    if app_name and is_legacy_app_name_hint(app_name):
        return legacy_app_name_hint(app_name)
    return ""


def legacy_music_app_name_hint(value: str) -> str:
    return music_app_name_from_text(value)
