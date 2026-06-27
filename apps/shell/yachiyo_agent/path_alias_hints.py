"""Compatibility path-alias hints for planner file access.

The planner should prefer discovered file context and explicit paths when
available. This module keeps legacy common desktop path aliases behind a
single boundary until file-target resolution can be replaced by workspace and
desktop discovery.
"""

from __future__ import annotations

from apps.shell.agent.runtime.path_aliases import common_desktop_path_marker


def legacy_common_desktop_path_hint(value: str) -> str:
    return common_desktop_path_marker(value)
