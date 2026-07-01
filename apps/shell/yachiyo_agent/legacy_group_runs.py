"""Legacy Agent Studio GroupRun orchestration fallback."""

from __future__ import annotations

from typing import Any, Callable

from .legacy_groups import (
    append_group_member_event,
    append_group_run_event,
    create_runnable_run,
    group_member_agent_override,
    group_member_with_inherited_policy,
)
from .legacy_group_orchestration import (
    active_speaker_agent_id as _active_speaker_agent_id,
    group_member_orchestration_context as _group_member_orchestration_context,
    group_member_phase as _group_member_phase,
    group_orchestration_plan as _group_orchestration_plan,
    group_orchestration_strategy as _group_orchestration_strategy,
    group_run_orchestration_context as _group_run_orchestration_context,
    group_run_status_from_child_runs as _group_run_status_from_child_runs,
    group_run_summary_from_child_runs as _group_run_summary_from_child_runs,
    member_sort_order as _member_sort_order,
    normalized_group_mode as _normalized_group_mode,
)
from .legacy_runs import LegacyRunPayloadProjector
from .planner_projection import planner_run_event_payloads, runtime_planner_decision


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
    members = [
        group_member_with_inherited_policy(runtime, member, group)
        for member in orchestration_plan["members"]
    ]

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
            agent_override=group_member_agent_override(runtime, member, group),
            runtime_planner_entrypoint=True,
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
            append_group_run_planner_events(
                runtime,
                child_run,
                objective,
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
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
        append_group_member_planner_events(
            runtime,
            child_run,
            objective,
            member,
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


def append_group_member_planner_events(
    runtime: Any,
    child_run: dict[str, Any],
    objective: str,
    member: dict[str, Any],
) -> None:
    append_run_event = getattr(runtime, "append_run_event", None)
    run_id = str(child_run.get("run_id") or "").strip()
    if not callable(append_run_event) or not run_id:
        return
    decision = runtime_planner_decision(
        objective,
        allowed_tools=_member_allowed_tools(member),
        metadata={"runnable_kind": "group", "agent_id": member.get("agent_id")},
    )
    for event_type, payload in planner_run_event_payloads(decision):
        try:
            append_run_event(run_id, event_type, payload)
        except Exception:
            continue


def append_group_run_planner_events(
    runtime: Any,
    run: dict[str, Any],
    objective: str,
    *,
    group_id: str,
    group: dict[str, Any],
    run_group_id: str,
    members: list[dict[str, Any]],
    child_run_ids: list[str],
    client_run_id: str = "",
    orchestration: dict[str, Any] | None = None,
) -> None:
    decision = runtime_planner_decision(
        objective,
        metadata={"runnable_kind": "group_run", "group_id": group_id},
    )
    for event_type, payload in planner_run_event_payloads(decision):
        append_group_run_event(
            runtime,
            run,
            _group_run_planner_event_type(event_type),
            group_id=group_id,
            group=group,
            run_group_id=run_group_id,
            objective=objective,
            status="running",
            members=members,
            child_run_ids=child_run_ids,
            client_run_id=client_run_id,
            orchestration={
                **dict(orchestration or {}),
                **dict(payload),
                "planner_event_type": event_type,
                "planner_scope": "group_run",
            },
        )


def _group_run_planner_event_type(event_type: str) -> str:
    if event_type == "agent.intent.selected":
        return "group.run.intent.selected"
    if event_type == "agent.plan.created":
        return "group.run.plan.created"
    if event_type == "agent.task_core.created":
        return "group.run.task_core.created"
    if event_type == "agent.plan.step":
        return "group.run.plan.step"
    if event_type == "agent.replan.requested":
        return "group.run.replan.requested"
    if event_type == "agent.task.workspace_item.updated":
        return "group.run.task.workspace_item.updated"
    if event_type == "agent.task.todo.updated":
        return "group.run.task.todo.updated"
    if event_type == "agent.task.checkpoint.updated":
        return "group.run.task.checkpoint.updated"
    return "group.run.planner_event"


def _member_allowed_tools(member: dict[str, Any]) -> list[str] | None:
    tool_policy = member.get("tool_policy") if isinstance(member.get("tool_policy"), dict) else {}
    allowed_tools = tool_policy.get("allowed_tools") if isinstance(tool_policy, dict) else None
    if not isinstance(allowed_tools, list):
        return None
    return [
        str(tool or "").strip()
        for tool in allowed_tools
        if str(tool or "").strip()
    ]


def group_orchestration_plan(
    group: dict[str, Any],
    members: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compatibility wrapper for "participants_then_moderator", "fan_out", "moderator_first"."""
    return _group_orchestration_plan(group, members)


def group_run_orchestration_context(plan: dict[str, Any]) -> dict[str, Any]:
    return _group_run_orchestration_context(plan)


def group_member_orchestration_context(
    plan: dict[str, Any],
    member: dict[str, Any],
    member_index: int,
) -> dict[str, Any]:
    """Compatibility wrapper retaining group_member_phase and group_member_parallel."""
    return _group_member_orchestration_context(plan, member, member_index)


def active_speaker_agent_id(
    plan: dict[str, Any],
    child_runs: list[dict[str, Any]],
) -> str:
    return _active_speaker_agent_id(plan, child_runs)


def normalized_group_mode(value: Any) -> str:
    return _normalized_group_mode(value)


def group_orchestration_strategy(mode: str) -> str:
    return _group_orchestration_strategy(mode)


def group_member_phase(mode: str, is_moderator: bool) -> str:
    return _group_member_phase(mode, is_moderator)


def member_sort_order(member: dict[str, Any]) -> int:
    return _member_sort_order(member)


def group_member_terminal_event_type(run: dict[str, Any]) -> str:
    status = str(run.get("status") or "").strip()
    if status == "failed":
        return "group.member.failed"
    if status == "cancelled":
        return "group.member.cancelled"
    return "group.member.completed"


def group_run_status_from_child_runs(child_runs: list[dict[str, Any]]) -> str:
    return _group_run_status_from_child_runs(child_runs)


def group_run_summary_from_child_runs(child_runs: list[dict[str, Any]]) -> str | None:
    return _group_run_summary_from_child_runs(child_runs)
