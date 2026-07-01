"""Approved-tool resume orchestration."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from typing import Any

from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalClaimProjection,
    ToolApprovalContinuationHandoff,
    ToolApprovalContinuationOutcome,
    ToolApprovalCustomApiContinuationRequest,
    ToolApprovalExecutionFailureProjection,
    ToolApprovalExecutionFollowup,
    ToolApprovalExecutionRequest,
    ToolApprovalResumeContext,
)
from packages.security import redact_api_error_text


class ApprovalResumeCoordinator:
    """Executes the approved tool portion of a paused run resume."""

    def __init__(
        self,
        *,
        call_agent_tool: Any,
        fatal_tool_failure_detail: Any,
        append_tool_result_message: Any,
        run_tool_requests: Any,
        timeline_factory: Any,
        claim_pending_approval: Any | None = None,
        approve_tool_run: Any | None = None,
        continue_custom_api_agent: Any | None = None,
        append_run_event: Any | None = None,
    ) -> None:
        self._call_agent_tool = call_agent_tool
        self._fatal_tool_failure_detail = fatal_tool_failure_detail
        self._append_tool_result_message = append_tool_result_message
        self._run_tool_requests = run_tool_requests
        self._timeline = timeline_factory
        self._claim_pending_approval = claim_pending_approval
        self._approve_tool_run = approve_tool_run
        self._continue_custom_api_agent = continue_custom_api_agent
        self._append_run_event = append_run_event

    def claim_and_project_approved_tool(
        self,
        run_id: str,
        pending: dict[str, Any],
        context: ToolApprovalResumeContext,
        *,
        resumed_detail: str,
        running_result: str,
    ) -> dict[str, Any] | None:
        if self._claim_pending_approval is None or self._approve_tool_run is None:
            raise AgentRuntimeError(
                "Approval resume coordinator is missing approval projection callbacks"
            )
        if not self._claim_pending_approval(run_id, pending):
            return None
        projection = ToolApprovalClaimProjection.from_context(
            run_id,
            context,
            resumed_detail=resumed_detail,
            running_result=running_result,
        )
        return projection.project(self._approve_tool_run)

    def execute_approved_tool(self, context: ToolApprovalResumeContext) -> None:
        task_progress_start = len(context.timeline)
        request = ToolApprovalExecutionRequest.from_context(context)
        tool_result = request.execute(self._call_agent_tool)
        fatal_failure = self._fatal_tool_failure_detail(
            context.tool_name,
            context.tool_request,
            tool_result,
        )
        if fatal_failure:
            failure = ToolApprovalExecutionFailureProjection.from_context(
                context,
                tool_result,
                fatal_failure,
            )
            context.timeline.append(failure.timeline_event(self._timeline))
            raise AgentRuntimeError(failure.detail)
        context.remaining_requests = _approval_resume_remaining_requests_after_tool(
            context,
            tool_result,
        )
        followup = ToolApprovalExecutionFollowup.from_context(
            context,
            tool_result,
        )
        try:
            followup.apply(
                self._append_tool_result_message,
                self._run_tool_requests,
            )
        finally:
            self._record_task_progress_after_resume(
                context,
                tool_timeline_start=task_progress_start,
            )

    def _record_task_progress_after_resume(
        self,
        context: ToolApprovalResumeContext,
        *,
        tool_timeline_start: int,
    ) -> None:
        for event_type, detail, payload in _approval_resume_task_progress_events(
            context.timeline,
            tool_timeline_start=tool_timeline_start,
        ):
            context.timeline.append(self._timeline(event_type, detail, **payload))
            if self._append_run_event is not None:
                self._append_run_event(context.run_id, event_type, payload)

    def continue_custom_api_agent_after_approved_tool(
        self,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
    ) -> str:
        if self._continue_custom_api_agent is None:
            raise AgentRuntimeError(
                "Approval resume coordinator is missing custom API continuation"
            )
        handoff = self.continuation_handoff_after_approved_tool(agent, context)
        request = ToolApprovalCustomApiContinuationRequest.from_handoff(handoff)
        return request.execute(self._continue_custom_api_agent)

    def continuation_handoff_after_approved_tool(
        self,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
    ) -> ToolApprovalContinuationHandoff:
        self.execute_approved_tool(context)
        return ToolApprovalContinuationHandoff.from_context(agent, context)

    def continue_and_project_after_approved_tool(
        self,
        *,
        agent: dict[str, Any],
        context: ToolApprovalResumeContext,
        project_completed: Any,
        project_required: Any,
        project_failed: Any,
        prepare_required: Any | None = None,
        redact_error: Any = redact_api_error_text,
    ) -> dict[str, Any]:
        try:
            result_text = self.continue_custom_api_agent_after_approved_tool(
                agent,
                context,
            )
            outcome = ToolApprovalContinuationOutcome.completed(result_text)
        except AgentApprovalRequired as exc:
            outcome = ToolApprovalContinuationOutcome.approval_required(
                exc.pending_approval,
                prepare_required=prepare_required,
            )
        except Exception as exc:
            outcome = ToolApprovalContinuationOutcome.failed(
                exc,
                redact_error=redact_error,
            )
        return outcome.project(
            context,
            project_completed=project_completed,
            project_required=project_required,
            project_failed=project_failed,
        )

    def resume_approved_tool_run(
        self,
        *,
        run_id: str,
        pending: dict[str, Any],
        context: ToolApprovalResumeContext,
        agent: dict[str, Any],
        resumed_detail: str,
        running_result: str,
        project_completed: Any,
        project_required: Any,
        project_failed: Any,
        get_current_run: Any,
        project_running: Any | None = None,
        prepare_required: Any | None = None,
        project_result: Any | None = None,
        redact_error: Any = redact_api_error_text,
    ) -> dict[str, Any]:
        running = self.claim_and_project_approved_tool(
            run_id,
            pending,
            context,
            resumed_detail=resumed_detail,
            running_result=running_result,
        )
        if running is None:
            return get_current_run(run_id)
        if project_running is not None:
            running = project_running(running)
        result = self.continue_and_project_after_approved_tool(
            agent=agent,
            context=context,
            project_completed=project_completed,
            project_required=project_required,
            project_failed=project_failed,
            prepare_required=prepare_required,
            redact_error=redact_error,
        )
        return project_result(result) if project_result is not None else result


def _approval_resume_task_progress_events(
    timeline: list[dict[str, Any]],
    *,
    tool_timeline_start: int,
) -> list[tuple[str, str, dict[str, Any]]]:
    task_context = _latest_task_core_context(timeline)
    task_core = task_context.get("task_core")
    if not isinstance(task_core, Mapping):
        return []
    todos = [
        todo
        for todo in task_core.get("todos", [])
        if isinstance(todo, Mapping) and str(todo.get("step_id") or "").strip()
    ]
    if not todos:
        return []
    checkpoints = [
        checkpoint
        for checkpoint in task_core.get("checkpoints", [])
        if isinstance(checkpoint, Mapping)
    ]
    plan_steps = _latest_plan_steps(
        timeline,
        decision_id=str(task_context.get("decision_id") or "").strip(),
        plan_id=str(task_context.get("plan_id") or "").strip(),
    )
    checkpoints_by_step: dict[str, list[Mapping[str, Any]]] = {}
    for checkpoint in checkpoints:
        step_id = str(checkpoint.get("after_step_id") or "").strip()
        if step_id:
            checkpoints_by_step.setdefault(step_id, []).append(checkpoint)
    tool_events = [
        event
        for event in timeline[tool_timeline_start:]
        if isinstance(event, dict)
        and str(event.get("event") or "").strip()
        in {"agent.tool.call", "agent.tool.skipped"}
    ]
    if not tool_events:
        return []

    event_index = 0
    events: list[tuple[str, str, dict[str, Any]]] = []
    for todo in todos:
        step_id = str(todo.get("step_id") or "").strip()
        if _latest_task_update_status(
            timeline,
            "agent.task.todo.updated",
            "step_id",
            step_id,
            decision_id=str(task_context.get("decision_id") or "").strip(),
        ) in {"completed", "skipped"}:
            continue
        step = plan_steps.get(step_id, {})
        tool_name = str(step.get("tool_name") or todo.get("tool_name") or "").strip()
        if not tool_name:
            continue
        tool_event: dict[str, Any] | None = None
        while event_index < len(tool_events):
            candidate = tool_events[event_index]
            event_index += 1
            if str(candidate.get("detail") or "").strip() == tool_name:
                tool_event = candidate
                break
        if tool_event is None:
            continue
        result = tool_event.get("result") if isinstance(tool_event.get("result"), Mapping) else {}
        todo_status = _task_todo_status_for_tool_result(
            str(tool_event.get("event") or ""),
            result,
        )
        checkpoint_status = _task_checkpoint_status_for_todo_status(
            todo_status,
            result,
        )
        source_event = {
            "event": str(tool_event.get("event") or "").strip(),
            "detail": str(tool_event.get("detail") or "").strip(),
        }
        base_payload = {
            "source": "runtime_planner",
            "core_id": str(task_context.get("core_id") or "").strip(),
            "workspace_id": str(task_context.get("workspace_id") or "").strip(),
            "decision_id": str(task_context.get("decision_id") or "").strip(),
            "plan_id": str(task_context.get("plan_id") or "").strip(),
            "step_id": step_id,
            "tool": tool_name,
            "source_event": source_event,
            "result_preview": _task_progress_result_preview(result),
        }
        events.append(_todo_progress_event(timeline, todo, base_payload, todo_status))
        for checkpoint in checkpoints_by_step.get(step_id, []):
            events.append(
                _checkpoint_progress_event(
                    timeline,
                    checkpoint,
                    base_payload,
                    checkpoint_status,
                )
            )
    return events


def _approval_resume_remaining_requests_after_tool(
    context: ToolApprovalResumeContext,
    tool_result: Any,
) -> list[dict[str, Any]]:
    existing = [
        dict(request)
        for request in context.remaining_requests
        if isinstance(request, Mapping)
    ]
    if existing:
        return existing
    if not _approved_workspace_patch_step(context, tool_result):
        return []
    verification = _pending_verification_request_after_patch(
        context.timeline,
        allowed_tools=context.allowed_tools,
    )
    return [verification] if verification else []


def _approved_workspace_patch_step(
    context: ToolApprovalResumeContext,
    tool_result: Any,
) -> bool:
    if str(context.tool_name or "").strip() != "workspace.write_patch":
        return False
    result = tool_result if isinstance(tool_result, Mapping) else {}
    if result.get("ok") is not True:
        return False
    step_id = str(context.tool_request.get("step_id") or "").strip()
    capability_id = str(context.tool_request.get("capability_id") or "").strip()
    return step_id == "apply-code-changes" or capability_id == "file.workspace_write"


def _pending_verification_request_after_patch(
    timeline: list[dict[str, Any]],
    *,
    allowed_tools: list[str],
) -> dict[str, Any]:
    if "terminal.run" not in {str(tool or "").strip() for tool in allowed_tools}:
        return {}
    for event in reversed(timeline):
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or "").strip() != "agent.model.followup_context":
            continue
        payload = _timeline_payload(event)
        steps = payload.get("pending_plan_steps")
        if not isinstance(steps, list):
            continue
        for step in steps:
            if not isinstance(step, Mapping):
                continue
            if str(step.get("step_id") or "").strip() != "verify-code-changes":
                continue
            if str(step.get("tool_name") or "").strip() != "terminal.run":
                continue
            depends_on = [
                str(item or "").strip()
                for item in step.get("depends_on", [])
                if str(item or "").strip()
            ] if isinstance(step.get("depends_on"), list) else []
            if "apply-code-changes" not in depends_on:
                continue
            raw_input = (
                step.get("input_preview")
                if isinstance(step.get("input_preview"), Mapping)
                else {}
            )
            command = str(raw_input.get("command") or "").strip()
            if not command:
                continue
            request = {
                "protocol": "json_fallback",
                "tool": "terminal.run",
                "input": {"command": command},
                "source": "runtime_planner",
                "planning_reason": "planner_followup_verify_code_changes",
                "continue_to_model": True,
                "step_id": "verify-code-changes",
                "capability_id": "terminal.execution",
            }
            return request
    return {}


def _latest_task_core_context(timeline: list[dict[str, Any]]) -> dict[str, Any]:
    for event in reversed(timeline):
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or "").strip() != "agent.task_core.created":
            continue
        payload = _timeline_payload(event)
        task_core = (
            payload.get("task_core")
            if isinstance(payload.get("task_core"), Mapping)
            else {}
        )
        workspace = (
            task_core.get("workspace")
            if isinstance(task_core.get("workspace"), Mapping)
            else {}
        )
        return {
            "task_core": task_core,
            "decision_id": str(payload.get("decision_id") or "").strip(),
            "plan_id": str(payload.get("plan_id") or "").strip(),
            "core_id": str(payload.get("core_id") or task_core.get("core_id") or "").strip(),
            "workspace_id": str(workspace.get("workspace_id") or "").strip(),
        }
    return {}


def _latest_plan_steps(
    timeline: list[dict[str, Any]],
    *,
    decision_id: str,
    plan_id: str,
) -> dict[str, Mapping[str, Any]]:
    steps: dict[str, Mapping[str, Any]] = {}
    for event in timeline:
        if not isinstance(event, Mapping):
            continue
        event_name = str(event.get("event") or "").strip()
        payload = _timeline_payload(event)
        if not _same_plan(payload, decision_id=decision_id, plan_id=plan_id):
            continue
        if event_name == "agent.plan.created":
            plan = payload.get("plan") if isinstance(payload.get("plan"), Mapping) else {}
            tool_plan = (
                plan.get("tool_plan")
                if isinstance(plan.get("tool_plan"), Mapping)
                else {}
            )
            for step in tool_plan.get("steps", []):
                if not isinstance(step, Mapping):
                    continue
                step_id = str(step.get("step_id") or "").strip()
                if step_id:
                    steps[step_id] = step
        elif event_name == "agent.plan.step":
            step = payload.get("step") if isinstance(payload.get("step"), Mapping) else {}
            step_id = str(step.get("step_id") or "").strip()
            if step_id:
                steps[step_id] = step
    return steps


def _todo_progress_event(
    timeline: list[dict[str, Any]],
    todo: Mapping[str, Any],
    base_payload: Mapping[str, Any],
    status: str,
) -> tuple[str, str, dict[str, Any]]:
    step_id = str(base_payload.get("step_id") or "").strip()
    previous_status = _latest_task_update_status(
        timeline,
        "agent.task.todo.updated",
        "step_id",
        step_id,
        decision_id=str(base_payload.get("decision_id") or "").strip(),
    ) or str(todo.get("status") or "pending")
    todo_payload = deepcopy(dict(todo))
    todo_payload["status"] = status
    payload = {
        **dict(base_payload),
        "todo_id": str(todo.get("todo_id") or "").strip(),
        "status": status,
        "previous_status": previous_status,
        "todo": todo_payload,
    }
    return (
        "agent.task.todo.updated",
        str(todo.get("title") or step_id),
        payload,
    )


def _checkpoint_progress_event(
    timeline: list[dict[str, Any]],
    checkpoint: Mapping[str, Any],
    base_payload: Mapping[str, Any],
    status: str,
) -> tuple[str, str, dict[str, Any]]:
    step_id = str(base_payload.get("step_id") or "").strip()
    checkpoint_id = str(checkpoint.get("checkpoint_id") or "").strip()
    previous_status = _latest_task_update_status(
        timeline,
        "agent.task.checkpoint.updated",
        "checkpoint_id",
        checkpoint_id,
        decision_id=str(base_payload.get("decision_id") or "").strip(),
    ) or str(checkpoint.get("status") or "planned")
    checkpoint_payload = deepcopy(dict(checkpoint))
    checkpoint_payload["status"] = status
    payload = {
        **dict(base_payload),
        "checkpoint_id": checkpoint_id,
        "status": status,
        "previous_status": previous_status,
        "checkpoint": checkpoint_payload,
    }
    return (
        "agent.task.checkpoint.updated",
        str(checkpoint.get("title") or step_id),
        payload,
    )


def _latest_task_update_status(
    timeline: list[dict[str, Any]],
    event_type: str,
    identity_key: str,
    identity: str,
    *,
    decision_id: str,
) -> str:
    clean_identity = str(identity or "").strip()
    if not clean_identity:
        return ""
    for event in reversed(timeline):
        if not isinstance(event, Mapping):
            continue
        if str(event.get("event") or "").strip() != event_type:
            continue
        payload = _timeline_payload(event)
        if (
            decision_id
            and str(payload.get("decision_id") or "").strip() != decision_id
        ):
            continue
        if str(payload.get(identity_key) or "").strip() != clean_identity:
            continue
        return str(payload.get("status") or "").strip()
    return ""


def _same_plan(
    payload: Mapping[str, Any],
    *,
    decision_id: str,
    plan_id: str,
) -> bool:
    if decision_id and str(payload.get("decision_id") or "").strip() != decision_id:
        return False
    if plan_id and str(payload.get("plan_id") or "").strip() != plan_id:
        return False
    return True


def _timeline_payload(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event.get("payload"), Mapping) else {}
    return {**dict(event), **dict(payload)}


def _task_todo_status_for_tool_result(
    event_type: str,
    result: Mapping[str, Any],
) -> str:
    if result.get("approval_required"):
        return "blocked"
    if str(event_type or "").strip() == "agent.tool.skipped":
        return "skipped" if result.get("blocked_by_user_goal") else "blocked"
    if result.get("ok") is False or result.get("error"):
        return "blocked"
    for key in ("returncode", "exit_code"):
        if key not in result:
            continue
        try:
            if int(result.get(key) or 0) != 0:
                return "blocked"
        except (TypeError, ValueError):
            return "blocked"
    return "completed"


def _task_checkpoint_status_for_todo_status(
    todo_status: str,
    result: Mapping[str, Any],
) -> str:
    if result.get("approval_required"):
        return "waiting_approval"
    if todo_status == "completed":
        return "completed"
    return "blocked"


def _task_progress_result_preview(result: Mapping[str, Any]) -> dict[str, Any]:
    preview: dict[str, Any] = {}
    for key in (
        "ok",
        "action",
        "summary",
        "error",
        "hint",
        "returncode",
        "exit_code",
        "blocked_by_user_goal",
        "approval_required",
    ):
        if key in result:
            preview[key] = result.get(key)
    stderr = str(result.get("stderr") or "").strip()
    if stderr:
        preview["stderr"] = stderr[:500]
    return preview
