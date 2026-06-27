"""Compatibility app-name hints for planner execution.

The planner should prefer desktop discovery when available. This module keeps
legacy alias normalization behind a single boundary until app-name resolution
can be replaced by discovered app metadata.
"""

from __future__ import annotations

from apps.shell.agent.runtime.app_aliases import APP_ALIASES, compact_app_alias


def legacy_app_name_hint(value: str) -> str:
    app_name = str(value or "").strip()
    if not app_name:
        return ""
    return APP_ALIASES.get(compact_app_alias(app_name), app_name)
