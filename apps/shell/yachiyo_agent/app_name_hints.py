"""Compatibility app-name hints for planner execution.

The planner should prefer desktop discovery when available. This module keeps
legacy alias normalization behind a single boundary until app-name resolution
can be replaced by discovered app metadata.
"""

from __future__ import annotations

from apps.shell.agent.runtime.app_aliases import (
    APP_ALIASES,
    COMMUNICATION_APP_NAMES,
    EMAIL_APP_NAMES,
    compact_app_alias,
)
from apps.shell.agent.runtime.media_apps import music_app_name_from_text


def legacy_app_name_hint(value: str) -> str:
    app_name = str(value or "").strip()
    if not app_name:
        return ""
    return APP_ALIASES.get(compact_app_alias(app_name), app_name)


def compact_app_name_hint(value: str) -> str:
    return compact_app_alias(value)


def supports_new_message_app_hint(value: str) -> bool:
    return str(value or "").strip() in (COMMUNICATION_APP_NAMES | EMAIL_APP_NAMES)


def legacy_music_app_name_hint(value: str) -> str:
    return music_app_name_from_text(value)
