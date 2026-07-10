"""Compatibility adapter for the native GroupRun coordinator."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.group_runs import (
    _group_run_planner_event_type,
    active_speaker_agent_id,
    append_group_member_planner_events,
    append_group_run_planner_events,
    group_member_orchestration_context,
    group_member_phase,
    group_member_terminal_event_type,
    group_orchestration_plan,
    group_orchestration_strategy,
    group_run_orchestration_context,
    group_run_status_from_child_runs,
    group_run_summary_from_child_runs,
    member_sort_order,
    normalized_group_mode,
    start_agent_group_run,
)
from apps.shell.yachiyo_agent.legacy_runs import LegacyRunPayloadProjector


def start_legacy_group_run(
    runtime: Any,
    request: dict[str, Any],
    *,
    get_group: Callable[[str], dict[str, Any]],
    projector: LegacyRunPayloadProjector | None = None,
) -> dict[str, Any]:
    """Preserve old adapters while delegating execution to the native coordinator."""

    group_id = str(request.get("group_id") or "").strip()
    if not group_id:
        raise ValueError("缺少 group_id")
    if not str(request.get("objective") or request.get("goal") or "").strip():
        raise ValueError("群组运行目标不能为空")
    return start_agent_group_run(
        runtime,
        request,
        group=get_group(group_id),
        projector=projector,
    )


__all__ = [
    "active_speaker_agent_id",
    "append_group_member_planner_events",
    "append_group_run_planner_events",
    "group_member_orchestration_context",
    "group_member_phase",
    "group_member_terminal_event_type",
    "group_orchestration_plan",
    "group_orchestration_strategy",
    "group_run_orchestration_context",
    "group_run_status_from_child_runs",
    "group_run_summary_from_child_runs",
    "member_sort_order",
    "normalized_group_mode",
    "start_legacy_group_run",
]
