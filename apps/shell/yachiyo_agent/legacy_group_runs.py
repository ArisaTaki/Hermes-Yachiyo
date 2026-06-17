"""Legacy Agent Studio GroupRun orchestration fallback."""

from __future__ import annotations

from typing import Any, Callable

from .legacy_groups import (
    append_group_member_event,
    append_group_run_event,
    create_runnable_run,
)
from .legacy_runs import LegacyRunPayloadProjector


def start_legacy_group_run(
    runtime: Any,
    request: dict[str, Any],
    *,
    get_group: Callable[[str], dict[str, Any]],
    projector: LegacyRunPayloadProjector | None = None,
) -> dict[str, Any]:
    group_id = str(request.get("group_id") or "").strip()
    objective = str(request.get("objective") or request.get("goal") or "").strip()
    client_run_id = str(
        request.get("client_run_id") or request.get("client_request_id") or ""
    ).strip()
    if not group_id:
        raise ValueError("缺少 group_id")
    if not objective:
        raise ValueError("群组运行目标不能为空")

    run_projector = projector or LegacyRunPayloadProjector()
    group = get_group(group_id)
    members = [item for item in group.get("members") or [] if isinstance(item, dict)]
    if not members:
        raise NotImplementedError("这个 legacy run group 没有可复用的成员定义")
    orchestration_plan = group_orchestration_plan(group, members)
    members = orchestration_plan["members"]

    child_runs: list[dict[str, Any]] = []
    run_group_id = ""
    for index, member in enumerate(members):
        agent_id = str(member.get("agent_id") or "").strip()
        if not agent_id:
            continue
        child_client_run_id = (
            f"{client_run_id}:{index}:{agent_id}" if client_run_id else ""
        )

        def on_member_complete(
            completed_run: dict[str, Any],
            *,
            current_member: dict[str, Any] = member,
            current_index: int = index,
            current_child_client_run_id: str = child_client_run_id,
        ) -> None:
            append_group_member_event(
                runtime,
                completed_run,
                group_member_terminal_event_type(completed_run),
                group_id=group_id,
                group=group,
                run_group_id="",
                objective=objective,
                member=current_member,
                member_index=current_index,
                client_run_id=client_run_id,
                child_client_run_id=current_child_client_run_id,
                orchestration=group_member_orchestration_context(
                    orchestration_plan,
                    current_member,
                    current_index,
                ),
            )

        child_run = create_runnable_run(
            runtime,
            runnable_id=agent_id,
            user_goal=objective,
            run_group_id=run_group_id,
            client_run_id=child_client_run_id,
            on_complete=on_member_complete,
        )
        if not run_group_id:
            run_group_id = str(child_run.get("run_group_id") or "")
            append_group_run_event(
                runtime,
                child_run,
                "group.run.started",
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
                objective=objective,
                status="running",
                members=members,
                child_run_ids=[str(child_run.get("run_id") or "")],
                client_run_id=client_run_id,
                orchestration=group_run_orchestration_context(orchestration_plan),
            )
            append_group_run_event(
                runtime,
                child_run,
                "group.run.plan",
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
                objective=objective,
                status="running",
                members=members,
                child_run_ids=[str(child_run.get("run_id") or "")],
                client_run_id=client_run_id,
                orchestration=group_run_orchestration_context(orchestration_plan),
            )
        append_group_member_event(
            runtime,
            child_run,
            "group.member.started",
            group_id=group_id,
            group=group,
            run_group_id=run_group_id,
            objective=objective,
            member=member,
            member_index=index,
            client_run_id=client_run_id,
            child_client_run_id=child_client_run_id,
            orchestration=group_member_orchestration_context(
                orchestration_plan,
                member,
                index,
            ),
        )
        child_status = str(child_run.get("status") or "").strip()
        if child_status in {"approval_required", "waiting_approval"}:
            append_group_member_event(
                runtime,
                child_run,
                "group.member.approval_required",
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
                objective=objective,
                member=member,
                member_index=index,
                client_run_id=client_run_id,
                child_client_run_id=child_client_run_id,
                orchestration=group_member_orchestration_context(
                    orchestration_plan,
                    member,
                    index,
                ),
            )
        elif child_status in {"completed", "failed", "cancelled"}:
            append_group_member_event(
                runtime,
                child_run,
                group_member_terminal_event_type(child_run),
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
                objective=objective,
                member=member,
                member_index=index,
                client_run_id=client_run_id,
                child_client_run_id=child_client_run_id,
                orchestration=group_member_orchestration_context(
                    orchestration_plan,
                    member,
                    index,
                ),
            )
        child_runs.append(child_run)

    if not child_runs:
        raise NotImplementedError("这个 legacy run group 没有可运行的成员")

    projected_status = group_run_status_from_child_runs(child_runs)
    if projected_status and run_group_id:
        update_run_group = getattr(runtime, "_update_run_group", None)
        if callable(update_run_group):
            update_run_group(
                run_group_id,
                status=projected_status,
                summary=(
                    group_run_summary_from_child_runs(child_runs)
                    if projected_status in {"completed", "failed", "cancelled"}
                    else None
                ),
            )
        if projected_status == "approval_required" and child_runs:
            append_group_run_event(
                runtime,
                child_runs[0],
                "group.run.approval_required",
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
                objective=objective,
                status=projected_status,
                members=members,
                child_run_ids=[
                    str(run.get("run_id") or "")
                    for run in child_runs
                    if str(run.get("run_id") or "")
                ],
                client_run_id=client_run_id,
                orchestration=group_run_orchestration_context(orchestration_plan),
            )

    run_group = runtime.get_run_group(run_group_id) if run_group_id else {}
    return {
        "run_group_id": run_group_id,
        "group_run_id": run_group_id,
        "group_id": group_id,
        "title": (
            request.get("title")
            or run_group.get("title")
            or group.get("name")
            or "Group run"
        ),
        "status": run_group.get("status") or "running",
        "objective": objective,
        "participants": members,
        "active_speaker_agent_id": active_speaker_agent_id(
            orchestration_plan,
            child_runs,
        ),
        "runs": child_runs,
        "child_run_ids": run_group.get("child_run_ids")
        or [run.get("run_id") for run in child_runs if run.get("run_id")],
        "events": run_projector.group_events_from_child_runs(child_runs, runtime),
        "shared_artifacts": run_projector.group_artifacts(child_runs),
        "pending_approvals": [
            run.get("pending_approval")
            for run in child_runs
            if run.get("pending_approval")
        ],
        "final_answer": run_group.get("summary") or "",
        "created_at": run_group.get("created_at") or "",
        "updated_at": run_group.get("updated_at") or "",
    }


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


def group_member_terminal_event_type(run: dict[str, Any]) -> str:
    status = str(run.get("status") or "").strip()
    if status == "failed":
        return "group.member.failed"
    if status == "cancelled":
        return "group.member.cancelled"
    return "group.member.completed"


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
