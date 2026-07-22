"""Native GroupRun orchestration over child Agent runs and runtime events."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.yachiyo_agent.planner_projection import (
    planner_run_event_payloads,
    runtime_planner_decision,
    runtime_planner_metadata,
)
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_envelope_payload_with_request_context,
    runtime_execution_requests_from_envelope_payload,
    runtime_execution_requests_from_metadata,
)

from .errors import AgentRuntimeError
from .group_orchestration import (
    active_speaker_agent_id,
    group_member_orchestration_context,
    group_member_phase,
    group_orchestration_plan,
    group_orchestration_strategy,
    group_run_orchestration_context,
    group_run_status_from_child_runs,
    group_run_summary_from_child_runs,
    member_sort_order,
    normalized_group_mode,
)
from .group_projection import GroupRunProjector, RuntimeGroupRunProjector
from .group_run_support import (
    append_group_member_event,
    append_group_run_event,
    create_runnable_run,
    group_member_agent_override,
    group_member_with_inherited_policy,
)
from .run_group_attachments import (
    issue_run_group_child_attachment,
    normalize_run_group_child_identity,
)

_GROUP_CLEANUP_REQUESTED_EVENT_TYPE = "group.cleanup.requested"
_GROUP_PARTIAL_START_FAILURE_SUMMARY = "群组启动失败。"
_GROUP_PARTIAL_START_CLEANUP_SUMMARY = "群组启动失败，正在停止已启动成员。"


def start_agent_group_run(
    runtime: Any,
    request: dict[str, Any],
    *,
    group: dict[str, Any],
    projector: GroupRunProjector | None = None,
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

    run_projector = projector or RuntimeGroupRunProjector()
    resolved_group_id = str(group.get("group_id") or group.get("id") or "").strip()
    if resolved_group_id and resolved_group_id != group_id:
        raise ValueError("群组定义与 group_id 不匹配")
    members = [item for item in group.get("members") or [] if isinstance(item, dict)]
    if not members:
        raise NotImplementedError("这个群组没有可复用的成员定义")
    orchestration_plan = group_orchestration_plan(group, members)
    members = [
        group_member_with_inherited_policy(runtime, member, group)
        for member in orchestration_plan["members"]
    ]
    _preflight_group_members(runtime, members)

    child_runs: list[dict[str, Any]] = []
    deferred_execution_starts: list[Any] = []
    run_group_id = ""
    for index, member in enumerate(members):
        agent_id = str(member.get("agent_id") or "").strip()
        if not agent_id:
            continue
        child_client_run_id = (
            normalize_run_group_child_identity(
                f"{client_run_id}:{index}:{agent_id}"
            )
            if client_run_id
            else ""
        )
        if run_group_id and not child_client_run_id:
            child_client_run_id = normalize_run_group_child_identity(
                f"group-member:{run_group_id}:{index}:{agent_id}"
            )

        def on_member_complete(
            completed_run: dict[str, Any],
            *,
            current_member: dict[str, Any] = member,
            current_index: int = index,
            current_child_client_run_id: str = child_client_run_id,
        ) -> None:
            completed_status = str(completed_run.get("status") or "").strip().lower()
            if completed_status not in {
                "completed",
                "failed",
                "cancelled",
                "canceled",
                "approval_required",
                "waiting_approval",
            }:
                return
            if completed_status in {"approval_required", "waiting_approval"}:
                append_group_member_event(
                    runtime,
                    completed_run,
                    "group.member.approval_required",
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
                return
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
            project_group_terminal_after_member(
                runtime,
                completed_run,
                expected_member_count=len(members),
            )

        member_direct_tool_requests = (
            _member_runtime_execution_requests(request, member, index)
            if index == 0
            else []
        )
        run_group_attachment = (
            issue_run_group_child_attachment(
                run_group_id=run_group_id,
                parent_run_id=str(child_runs[0].get("run_id") or ""),
                child_kind="agent_run",
                child_runnable_id=agent_id,
                child_identity=child_client_run_id,
            )
            if run_group_id and child_runs
            else None
        )
        provisional_child_run: dict[str, Any] | None = None
        try:
            child_run = create_runnable_run(
                runtime,
                runnable_id=agent_id,
                user_goal=objective,
                run_group_id=run_group_id,
                client_run_id=child_client_run_id,
                on_complete=on_member_complete,
                agent_override=group_member_agent_override(runtime, member, group),
                daily_desktop_policy_overlay=True,
                runtime_planner_entrypoint=True,
                runtime_execution_envelope=(
                    dict(request.get("runtime_execution_envelope"))
                    if isinstance(request.get("runtime_execution_envelope"), Mapping)
                    else None
                ),
                metadata=(
                    dict(request.get("metadata"))
                    if isinstance(request.get("metadata"), Mapping)
                    else None
                ),
                direct_tool_requests=(
                    member_direct_tool_requests if member_direct_tool_requests else None
                ),
                daily_desktop_planning_context=_group_planning_context(request, objective),
                project_root_group=False,
                run_group_attachment=run_group_attachment,
                deferred_execution_start_sink=deferred_execution_starts.append,
            )
            provisional_child_run = child_run
            first_child = not bool(run_group_id)
            if first_child:
                run_group_id = str(child_run.get("run_group_id") or "").strip()
            _publish_group_child_start(
                runtime,
                child_run,
                first_child=first_child,
                group_id=group_id,
                group=group,
                run_group_id=run_group_id,
                objective=objective,
                member=member,
                member_index=index,
                members=members,
                client_run_id=client_run_id,
                child_client_run_id=child_client_run_id,
                orchestration_plan=orchestration_plan,
            )
        except Exception:
            claimed_runs = list(child_runs)
            if provisional_child_run is not None and all(
                str(run.get("run_id") or "")
                != str(provisional_child_run.get("run_id") or "")
                for run in claimed_runs
            ):
                claimed_runs.append(provisional_child_run)
            cleanup_group_id = run_group_id or str(
                (provisional_child_run or {}).get("run_group_id") or ""
            ).strip()
            if not claimed_runs or not cleanup_group_id:
                raise
            return _failed_group_start_after_partial_claim(
                runtime,
                group_id=group_id,
                group=group,
                objective=objective,
                run_group_id=cleanup_group_id,
                child_runs=claimed_runs,
                members=members,
                client_run_id=client_run_id,
                projector=run_projector,
            )
        child_runs.append(child_run)

    if not child_runs:
        raise NotImplementedError("这个群组没有可运行的成员")

    try:
        for activate in deferred_execution_starts:
            activate()
    except Exception:
        return _failed_group_start_after_partial_claim(
            runtime,
            group_id=group_id,
            group=group,
            objective=objective,
            run_group_id=run_group_id,
            child_runs=child_runs,
            members=members,
            client_run_id=client_run_id,
            projector=run_projector,
        )

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
    projected_child_runs = [
        run_projector.child_run_payload(run, runtime)
        for run in child_runs
    ]
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
            projected_child_runs,
        ),
        "runs": projected_child_runs,
        "child_run_ids": run_group.get("child_run_ids")
        or [run.get("run_id") for run in projected_child_runs if run.get("run_id")],
        "events": run_projector.group_events_from_child_runs(projected_child_runs, runtime),
        "shared_artifacts": run_projector.group_artifacts(projected_child_runs),
        "pending_approvals": [
            run.get("pending_approval")
            for run in projected_child_runs
            if run.get("pending_approval")
        ],
        "final_answer": run_group.get("summary") or "",
        "created_at": run_group.get("created_at") or "",
        "updated_at": run_group.get("updated_at") or "",
    }


def project_group_terminal_after_member(
    runtime: Any,
    completed_run: dict[str, Any],
    *,
    expected_member_count: int,
) -> None:
    """Let the GroupRun owner terminate a fully settled member set exactly once."""

    run_group_id = str(completed_run.get("run_group_id") or "").strip()
    get_run_group = getattr(runtime, "get_run_group", None)
    get_run = getattr(runtime, "get_run", None)
    update_run_group = getattr(runtime, "_update_run_group", None)
    if not run_group_id or not all(
        callable(callback)
        for callback in (get_run_group, get_run, update_run_group)
    ):
        return
    try:
        group = get_run_group(run_group_id)
    except KeyError:
        return
    if not isinstance(group, dict):
        return
    current_status = str(group.get("status") or "").strip().lower()
    if current_status in {"completed", "failed", "cancelled", "canceled"}:
        return
    child_run_ids = [
        str(run_id)
        for run_id in group.get("child_run_ids") or []
        if str(run_id)
    ]
    if len(child_run_ids) < max(1, int(expected_member_count or 0)):
        return
    child_runs: list[dict[str, Any]] = []
    for child_run_id in child_run_ids:
        try:
            child_run = get_run(child_run_id)
        except KeyError:
            return
        if not isinstance(child_run, dict):
            return
        child_runs.append(child_run)
    projected_status = group_run_status_from_child_runs(child_runs)
    if projected_status not in {"completed", "failed", "cancelled"}:
        return
    summary = group_run_summary_from_child_runs(child_runs) or ""
    cas: dict[str, str] = {}
    current_updated_at = str(group.get("updated_at") or "")
    if current_status and current_updated_at:
        cas = {
            "expected_status": str(group.get("status") or ""),
            "expected_updated_at": current_updated_at,
        }
    updated = update_run_group(
        run_group_id,
        status=projected_status,
        summary=summary,
        **cas,
    )
    if not cas or updated is not None:
        return
    try:
        winner = get_run_group(run_group_id)
    except KeyError as exc:
        raise AgentRuntimeError("group_run_terminal_projection_cas_lost") from exc
    if (
        str(winner.get("status") or "").strip().lower() == projected_status
        and str(winner.get("summary") or "") == summary
    ):
        return
    raise AgentRuntimeError("group_run_terminal_projection_conflict")


def _publish_group_child_start(
    runtime: Any,
    child_run: dict[str, Any],
    *,
    first_child: bool,
    group_id: str,
    group: dict[str, Any],
    run_group_id: str,
    objective: str,
    member: dict[str, Any],
    member_index: int,
    members: list[dict[str, Any]],
    client_run_id: str,
    child_client_run_id: str,
    orchestration_plan: dict[str, Any],
) -> None:
    """Publish every durable start fact before any prepared child activates."""

    child_run_id = str(child_run.get("run_id") or "").strip()
    if not child_run_id or not run_group_id:
        raise AgentRuntimeError("group_run_child_start_identity_missing")
    if first_child:
        group_context = group_run_orchestration_context(orchestration_plan)
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
            child_run_ids=[child_run_id],
            client_run_id=client_run_id,
            orchestration=group_context,
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
            child_run_ids=[child_run_id],
            client_run_id=client_run_id,
            orchestration=group_context,
        )
        append_group_run_planner_events(
            runtime,
            child_run,
            objective,
            group_id=group_id,
            group=group,
            run_group_id=run_group_id,
            members=members,
            child_run_ids=[child_run_id],
            client_run_id=client_run_id,
            orchestration=group_context,
        )
    member_context = group_member_orchestration_context(
        orchestration_plan,
        member,
        member_index,
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
        member_index=member_index,
        client_run_id=client_run_id,
        child_client_run_id=child_client_run_id,
        orchestration=member_context,
    )
    append_group_member_planner_events(
        runtime,
        child_run,
        objective,
        member,
    )
    child_status = str(child_run.get("status") or "").strip().lower()
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
            member_index=member_index,
            client_run_id=client_run_id,
            child_client_run_id=child_client_run_id,
            orchestration=member_context,
        )
    elif child_status in {"completed", "failed", "cancelled", "canceled"}:
        append_group_member_event(
            runtime,
            child_run,
            group_member_terminal_event_type(child_run),
            group_id=group_id,
            group=group,
            run_group_id=run_group_id,
            objective=objective,
            member=member,
            member_index=member_index,
            client_run_id=client_run_id,
            child_client_run_id=child_client_run_id,
            orchestration=member_context,
        )


def _preflight_group_members(runtime: Any, members: list[dict[str, Any]]) -> None:
    resolve_runnable = getattr(runtime, "resolve_runnable", None)
    for member in members:
        agent_id = str(member.get("agent_id") or "").strip()
        if not agent_id:
            raise ValueError("群组成员缺少 agent_id")
        if not callable(resolve_runnable):
            continue
        resolved = resolve_runnable(runnable_id=agent_id)
        if not isinstance(resolved, dict):
            raise ValueError(f"群组成员不可运行：{agent_id}")


def _append_partial_group_cleanup_intent(
    runtime: Any,
    *,
    group_id: str,
    group: dict[str, Any],
    objective: str,
    run_group_id: str,
    child_runs: list[dict[str, Any]],
    members: list[dict[str, Any]],
    client_run_id: str,
    current_status: str,
) -> None:
    child_run_ids = [
        str(run.get("run_id") or "").strip()
        for run in child_runs
        if str(run.get("run_id") or "").strip()
    ]
    if not child_run_ids:
        raise AgentRuntimeError("group_run_partial_start_cleanup_owner_missing")
    if _group_cleanup_intent_recorded(runtime, child_run_ids, run_group_id):
        return
    append_run_event = getattr(runtime, "append_run_event", None)
    if not callable(append_run_event):
        raise AgentRuntimeError("group_run_partial_start_cleanup_event_unavailable")
    payload = {
        "child_run_ids": child_run_ids,
        "cleanup_status": "requested",
        "group_id": group_id,
        "group_run_id": run_group_id,
        "intended_terminal_status": "failed",
        "objective": objective,
        "participant_count": len(members),
        "run_group_id": run_group_id,
        "status": current_status or "running",
        "summary": _GROUP_PARTIAL_START_FAILURE_SUMMARY,
    }
    group_name = str(group.get("name") or "").strip()
    if group_name:
        payload["group_name"] = group_name
    if client_run_id:
        payload["client_run_id"] = client_run_id
    appended = append_run_event(
        child_run_ids[0],
        _GROUP_CLEANUP_REQUESTED_EVENT_TYPE,
        payload,
    )
    if appended is None:
        raise AgentRuntimeError("group_run_partial_start_cleanup_event_fence_mismatch")


def _group_cleanup_intent_recorded(
    runtime: Any,
    child_run_ids: list[str],
    run_group_id: str,
) -> bool:
    checker = getattr(runtime, "_run_group_event_recorded", None)
    if callable(checker):
        return bool(
            checker(
                child_run_ids,
                event_type=_GROUP_CLEANUP_REQUESTED_EVENT_TYPE,
                run_group_id=run_group_id,
            )
        )
    list_run_events = getattr(runtime, "list_run_events", None)
    if not callable(list_run_events):
        return False
    for run_id in child_run_ids:
        try:
            listed = list_run_events(
                run_id,
                include_internal=True,
                limit=1000,
            )
        except TypeError:
            listed = list_run_events(run_id)
        events = listed.get("events") if isinstance(listed, dict) else []
        for event in events or []:
            if not isinstance(event, dict) or str(event.get("event_type") or "") != (
                _GROUP_CLEANUP_REQUESTED_EVENT_TYPE
            ):
                continue
            payload = event.get("payload")
            if isinstance(payload, dict) and str(
                payload.get("run_group_id") or payload.get("group_run_id") or ""
            ) == run_group_id:
                return True
    return False


def _failed_group_start_after_partial_claim(
    runtime: Any,
    *,
    group_id: str,
    group: dict[str, Any],
    objective: str,
    run_group_id: str,
    child_runs: list[dict[str, Any]],
    members: list[dict[str, Any]],
    client_run_id: str,
    projector: GroupRunProjector,
) -> dict[str, Any]:
    # Keep the authoritative terminal outcome stable across cleanup retries.
    # Per-child cleanup truth is returned separately below; it must not make a
    # same-winner retry look like a conflicting terminal GroupRun outcome.
    summary = _GROUP_PARTIAL_START_FAILURE_SUMMARY
    update_run_group = getattr(runtime, "_update_run_group", None)
    get_run_group = getattr(runtime, "get_run_group", None)
    if (
        not run_group_id
        or not callable(update_run_group)
        or not callable(get_run_group)
    ):
        raise AgentRuntimeError(
            "group_run_partial_start_terminal_projector_unavailable"
        )
    current_group = get_run_group(run_group_id)
    if not isinstance(current_group, dict):
        raise AgentRuntimeError("group_run_partial_start_terminal_group_invalid")
    cas: dict[str, str] = {}
    current_status = str(current_group.get("status") or "")
    current_updated_at = str(current_group.get("updated_at") or "")
    if current_status and current_updated_at:
        cas = {
            "expected_status": current_status,
            "expected_updated_at": current_updated_at,
        }
    terminal_group: dict[str, Any] | None = None
    if current_status.strip().lower() in {
        "completed",
        "failed",
        "cancelled",
        "canceled",
    }:
        # Let the shared terminal projector enforce same-winner idempotency and
        # reject a different terminal owner before cleanup mutates any child.
        projected = update_run_group(
            run_group_id,
            status="failed",
            summary=summary,
            **cas,
        )
        if isinstance(projected, dict):
            terminal_group = projected

    if terminal_group is None:
        _append_partial_group_cleanup_intent(
            runtime,
            group_id=group_id,
            group=group,
            objective=objective,
            run_group_id=run_group_id,
            child_runs=child_runs,
            members=members,
            client_run_id=client_run_id,
            current_status=current_status,
        )

    stopped_runs: list[dict[str, Any]] = []
    attempted_run_ids: list[str] = []
    stopped_run_ids: list[str] = []
    unconfirmed_run_ids: list[str] = []
    cancel_run = getattr(runtime, "cancel_run", None)
    get_run = getattr(runtime, "get_run", None)
    for child_run in child_runs:
        run_id = str(child_run.get("run_id") or "").strip()
        if run_id:
            attempted_run_ids.append(run_id)
        stopped = dict(child_run)
        if run_id and callable(cancel_run):
            try:
                cancelled = cancel_run(run_id)
            except Exception:
                cancelled = None
            if isinstance(cancelled, dict):
                stopped = dict(cancelled)
            elif callable(get_run):
                try:
                    fresh_run = get_run(run_id)
                except (KeyError, RuntimeError):
                    fresh_run = None
                if isinstance(fresh_run, dict):
                    stopped = dict(fresh_run)
        stopped_status = str(stopped.get("status") or "").strip().lower()
        if run_id and stopped_status in {
            "completed",
            "failed",
            "cancelled",
            "canceled",
        }:
            stopped_run_ids.append(run_id)
        elif run_id:
            unconfirmed_run_ids.append(run_id)
        stopped_runs.append(stopped)

    cleanup_complete = not unconfirmed_run_ids
    if terminal_group is None and cleanup_complete:
        terminal_group = update_run_group(
            run_group_id,
            status="failed",
            summary=summary,
            **cas,
        )
        if terminal_group is None:
            raise AgentRuntimeError("group_run_partial_start_terminal_cas_lost")
    if terminal_group is None:
        current_group = get_run_group(run_group_id)
        if not isinstance(current_group, dict):
            raise AgentRuntimeError("group_run_partial_start_terminal_group_invalid")
        if str(current_group.get("status") or "").strip().lower() in {
            "completed",
            "failed",
            "cancelled",
            "canceled",
        }:
            # Reuse the central guard to distinguish the same intended winner
            # from a competing terminal owner, but never report a terminal
            # Group while one of its claimed children is still active.
            update_run_group(
                run_group_id,
                status="failed",
                summary=summary,
            )
            raise AgentRuntimeError(
                "group_run_partial_start_cleanup_incomplete_terminal_projection"
            )
        response_group = current_group
        response_summary = _GROUP_PARTIAL_START_CLEANUP_SUMMARY
    else:
        if not cleanup_complete:
            raise AgentRuntimeError(
                "group_run_partial_start_cleanup_incomplete_terminal_projection"
            )
        if not isinstance(terminal_group, dict):
            raise AgentRuntimeError("group_run_partial_start_terminal_group_invalid")
        if (
            str(terminal_group.get("status") or "").strip().lower() != "failed"
            or str(terminal_group.get("summary") or "") != summary
        ):
            raise AgentRuntimeError(
                "group_run_partial_start_terminal_projection_mismatch"
            )
        response_group = terminal_group
        response_summary = str(terminal_group.get("summary") or summary)

    projected_runs = [
        projector.child_run_payload(run, runtime)
        for run in stopped_runs
    ]
    return {
        "run_group_id": run_group_id,
        "group_run_id": run_group_id,
        "group_id": group_id,
        "title": group.get("name") or "Group run",
        "status": str(response_group.get("status") or "running"),
        "objective": objective,
        "participants": members,
        "active_speaker_agent_id": "",
        "runs": projected_runs,
        "child_run_ids": [
            str(run.get("run_id") or "")
            for run in projected_runs
            if str(run.get("run_id") or "")
        ],
        "events": projector.group_events_from_child_runs(projected_runs, runtime),
        "shared_artifacts": projector.group_artifacts(projected_runs),
        "pending_approvals": [
            run.get("pending_approval")
            for run in projected_runs
            if run.get("pending_approval")
        ],
        "cleanup": {
            "attempted_run_ids": attempted_run_ids,
            "stopped_run_ids": stopped_run_ids,
            "unconfirmed_run_ids": unconfirmed_run_ids,
            "complete": cleanup_complete,
        },
        "final_answer": response_summary,
        "summary": response_summary,
        "created_at": str(response_group.get("created_at") or ""),
        "updated_at": str(response_group.get("updated_at") or ""),
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
        append_run_event(run_id, event_type, payload)


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
    event_context = {
        "group_id": group_id,
        "group_run_id": run_group_id,
        "run_group_id": run_group_id,
    }
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
                **_planner_event_payload_with_context(payload, event_context),
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
    if event_type == "agent.plan.selection":
        return "group.run.plan.selection"
    if event_type == "agent.replan.requested":
        return "group.run.replan.requested"
    if event_type == "agent.replan.recovery.updated":
        return "group.run.replan.recovery.updated"
    if event_type == "agent.desktop.intent_planned":
        return "group.run.desktop.intent_planned"
    if event_type == "agent.desktop.intent_approval_required":
        return "group.run.desktop.intent_approval_required"
    if event_type == "agent.desktop.intent_completed":
        return "group.run.desktop.intent_completed"
    if event_type == "agent.desktop.intent_unavailable":
        return "group.run.desktop.intent_unavailable"
    if event_type == "agent.desktop.intent_unverified":
        return "group.run.desktop.intent_unverified"
    if event_type == "agent.desktop.permission_recovery":
        return "group.run.desktop.permission_recovery"
    if event_type == "agent.desktop.readiness_recovered":
        return "group.run.desktop.readiness_recovered"
    if event_type == "agent.task.workspace_item.updated":
        return "group.run.task.workspace_item.updated"
    if event_type == "agent.task.todo.updated":
        return "group.run.task.todo.updated"
    if event_type == "agent.task.checkpoint.updated":
        return "group.run.task.checkpoint.updated"
    return "group.run.planner_event"


def _planner_event_payload_with_context(
    payload: dict[str, Any],
    event_context: Mapping[str, Any],
) -> dict[str, Any]:
    enriched = dict(payload)
    clean_context = {
        str(key): str(value).strip()
        for key, value in event_context.items()
        if str(key or "").strip() and str(value or "").strip()
    }
    for key, value in clean_context.items():
        enriched.setdefault(key, value)
    envelope = enriched.get("runtime_execution_envelope")
    if isinstance(envelope, Mapping):
        enriched["runtime_execution_envelope"] = (
            runtime_execution_envelope_payload_with_request_context(
                envelope,
                clean_context,
            )
        )
    return enriched


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


def _member_runtime_execution_requests(
    request: Mapping[str, Any],
    member: dict[str, Any],
    member_index: int,
) -> list[dict[str, Any]]:
    for requests in _runtime_execution_request_candidates(request, member):
        if not requests:
            continue
        return [
            _runtime_execution_request_with_group_context(
                tool_request,
                request,
                member,
                member_index,
            )
            for tool_request in requests
        ]
    return []


def _runtime_execution_request_candidates(
    request: Mapping[str, Any],
    member: dict[str, Any],
) -> list[list[dict[str, Any]]]:
    allowed_tools = _member_allowed_tools(member)
    metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
    candidates: list[list[dict[str, Any]]] = []
    direct_requests = _allowed_direct_tool_requests(
        request.get("direct_tool_requests"),
        allowed_tools=allowed_tools,
    )
    if direct_requests:
        candidates.append(direct_requests)
    top_level_requests = runtime_execution_requests_from_envelope_payload(
        request.get("runtime_execution_envelope"),
        allowed_tools=allowed_tools,
    )
    if top_level_requests:
        candidates.append(top_level_requests)
    metadata_requests = runtime_execution_requests_from_metadata(
        metadata,
        allowed_tools=allowed_tools,
    )
    if metadata_requests:
        candidates.append(metadata_requests)
    planner_requests = _runtime_planner_direct_requests(
        request,
        allowed_tools=allowed_tools,
    )
    if planner_requests:
        candidates.append(planner_requests)
    return candidates


def _runtime_planner_direct_requests(
    request: Mapping[str, Any],
    *,
    allowed_tools: list[str] | None,
) -> list[dict[str, Any]]:
    objective = _group_planning_context(
        request,
        str(request.get("objective") or request.get("goal") or "").strip(),
    )
    if not objective:
        return []
    metadata = request.get("metadata") if isinstance(request.get("metadata"), Mapping) else {}
    decision = runtime_planner_decision(
        objective,
        allowed_tools=allowed_tools,
        metadata=metadata,
    )
    planner_metadata = runtime_planner_metadata(
        decision,
        allowed_tools=allowed_tools,
        metadata=metadata,
    )
    return runtime_execution_requests_from_metadata(
        planner_metadata,
        allowed_tools=allowed_tools,
    )


def _allowed_direct_tool_requests(
    direct_tool_requests: Any,
    *,
    allowed_tools: list[str] | None,
) -> list[dict[str, Any]]:
    if not isinstance(direct_tool_requests, list):
        return []
    allowed = {
        str(tool or "").strip()
        for tool in allowed_tools or []
        if str(tool or "").strip()
    }
    requests: list[dict[str, Any]] = []
    for request in direct_tool_requests:
        if not isinstance(request, Mapping):
            continue
        tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
        if not tool_name:
            continue
        if allowed and tool_name not in allowed:
            continue
        copied = dict(request)
        copied["tool"] = tool_name
        requests.append(copied)
    return requests


def _runtime_execution_request_with_group_context(
    tool_request: dict[str, Any],
    request: Mapping[str, Any],
    member: Mapping[str, Any],
    member_index: int,
) -> dict[str, Any]:
    enriched = dict(tool_request)
    for key, value in {
        "group_id": request.get("group_id"),
        "agent_id": member.get("agent_id"),
        "group_member_index": member_index,
    }.items():
        if value is None:
            continue
        if not str(value).strip():
            continue
        enriched.setdefault(key, value)
    return enriched


def _group_planning_context(request: Mapping[str, Any], objective: str) -> str:
    return str(request.get("daily_desktop_planning_context") or objective or "").strip()


def group_member_terminal_event_type(run: dict[str, Any]) -> str:
    status = str(run.get("status") or "").strip()
    if status == "failed":
        return "group.member.failed"
    if status == "cancelled":
        return "group.member.cancelled"
    return "group.member.completed"
