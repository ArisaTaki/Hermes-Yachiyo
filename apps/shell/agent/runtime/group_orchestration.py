"""Pure orchestration helpers shared by native GroupRun entry points."""

from __future__ import annotations

from typing import Any


def group_orchestration_plan(
    group: dict[str, Any],
    members: list[dict[str, Any]],
) -> dict[str, Any]:
    mode = normalized_group_mode(group.get("mode"))
    moderator_agent_id = str(group.get("moderator_agent_id") or "").strip()
    ordered_members = list(members)
    if mode == "moderated" and moderator_agent_id:
        ordered_members.sort(
            key=lambda member: (
                str(member.get("agent_id") or "") != moderator_agent_id,
                member_sort_order(member),
            )
        )
    elif mode == "debate" and moderator_agent_id:
        ordered_members.sort(
            key=lambda member: (
                str(member.get("agent_id") or "") == moderator_agent_id,
                member_sort_order(member),
            )
        )
    else:
        ordered_members.sort(key=member_sort_order)
    return {
        "mode": mode,
        "members": ordered_members,
        "moderator_agent_id": moderator_agent_id,
        "member_order": [
            str(member.get("agent_id") or "")
            for member in ordered_members
            if str(member.get("agent_id") or "")
        ],
        "parallel": mode == "parallel",
        "strategy": group_orchestration_strategy(mode),
    }


def group_run_orchestration_context(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "group_execution_mode": plan["mode"],
        "group_execution_strategy": plan["strategy"],
        "group_member_order": plan["member_order"],
        "group_parallel": bool(plan["parallel"]),
        "group_moderator_agent_id": plan["moderator_agent_id"],
    }


def group_member_orchestration_context(
    plan: dict[str, Any],
    member: dict[str, Any],
    member_index: int,
) -> dict[str, Any]:
    agent_id = str(member.get("agent_id") or "").strip()
    is_moderator = bool(plan["moderator_agent_id"] and agent_id == plan["moderator_agent_id"])
    return {
        "group_execution_mode": plan["mode"],
        "group_execution_strategy": plan["strategy"],
        "group_member_phase": group_member_phase(plan["mode"], is_moderator),
        "group_member_turn": member_index + 1,
        "group_member_parallel": bool(plan["parallel"]),
        "group_member_is_moderator": is_moderator,
    }


def active_speaker_agent_id(
    plan: dict[str, Any],
    child_runs: list[dict[str, Any]],
) -> str:
    running_run = next(
        (
            run
            for run in child_runs
            if str(run.get("status") or "") in {"queued", "running", "processing"}
        ),
        None,
    )
    if running_run:
        return str(
            running_run.get("runnable_id") or running_run.get("agent_id") or ""
        ).strip()
    return str((plan.get("member_order") or [""])[0] or "")


def normalized_group_mode(value: Any) -> str:
    mode = str(value or "").strip()
    return mode if mode in {"moderated", "round_robin", "debate", "pipeline", "parallel"} else "custom"


def group_orchestration_strategy(mode: str) -> str:
    return {
        "debate": "participants_then_moderator",
        "moderated": "moderator_first",
        "parallel": "fan_out",
        "pipeline": "ordered_pipeline",
        "round_robin": "ordered_turns",
    }.get(mode, "custom")


def group_member_phase(mode: str, is_moderator: bool) -> str:
    if mode == "debate":
        return "moderator_summary" if is_moderator else "debate_argument"
    if mode == "moderated":
        return "moderator" if is_moderator else "member"
    if mode == "parallel":
        return "parallel_branch"
    if mode == "pipeline":
        return "pipeline_step"
    if mode == "round_robin":
        return "round_robin_turn"
    return "member"


def member_sort_order(member: dict[str, Any]) -> int:
    try:
        return int(member.get("sort_order") or 0)
    except (TypeError, ValueError):
        return 0


def group_run_status_from_child_runs(child_runs: list[dict[str, Any]]) -> str:
    statuses = {
        str(run.get("status") or "").strip()
        for run in child_runs
        if str(run.get("status") or "").strip()
    }
    if not statuses:
        return ""
    if statuses & {"approval_required", "waiting_approval"}:
        return "approval_required"
    if statuses & {"queued", "running", "processing"}:
        return ""
    if "failed" in statuses:
        return "failed"
    if "cancelled" in statuses:
        return "cancelled"
    if statuses == {"completed"}:
        return "completed"
    return ""


def group_run_summary_from_child_runs(child_runs: list[dict[str, Any]]) -> str | None:
    lines: list[str] = []
    for run in child_runs:
        result = str(run.get("result") or "").strip()
        if not result:
            continue
        label = str(run.get("runnable_name") or run.get("runnable_id") or "").strip()
        lines.append(f"{label}: {result}" if label else result)
    return "\n".join(lines) if lines else None


__all__ = [
    "active_speaker_agent_id",
    "group_member_orchestration_context",
    "group_member_phase",
    "group_orchestration_plan",
    "group_orchestration_strategy",
    "group_run_orchestration_context",
    "group_run_status_from_child_runs",
    "group_run_summary_from_child_runs",
    "member_sort_order",
    "normalized_group_mode",
]
