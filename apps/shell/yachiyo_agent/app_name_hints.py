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


def legacy_app_name_hint(value: str) -> str:
    app_name = str(value or "").strip()
    if not app_name:
        return ""
    compact = _legacy_app_name_compact(app_name)
    return APP_ALIASES.get(compact, app_name)


def is_legacy_app_name_hint(value: str) -> bool:
    app_name = str(value or "").strip()
    if not app_name:
        return False
    return _legacy_app_name_compact(app_name) in APP_ALIASES


def compact_app_name_hint(value: str) -> str:
    return compact_app_alias(value)


def supports_new_message_app_hint(value: str) -> bool:
    return str(value or "").strip() in (COMMUNICATION_APP_NAMES | EMAIL_APP_NAMES)


def legacy_music_app_name_hint(value: str) -> str:
    return music_app_name_from_text(value)
