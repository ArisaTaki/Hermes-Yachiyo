"""Approval resume copy-on-write and event atomicity regressions."""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from types import SimpleNamespace
from typing import Any

import pytest

from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.approval_lifecycle import ApprovalCoordinator
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_projections import (
    ApprovalResumeProjectionCoordinator,
)
from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext


def _timeline(event: str, detail: str = "", **payload: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **payload}


def _context(*, approval_id: str = "approval-resume") -> ToolApprovalResumeContext:
    return ToolApprovalResumeContext(
        run_id="run-resume-copy-on-write",
        timeline=[_timeline("agent.run.resumed", "baseline")],
        artifacts=[{"kind": "file", "path": "baseline.txt"}],
        broker=SimpleNamespace(),
        allowed_tools=["terminal.run"],
        budget=SimpleNamespace(),
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={"tool": "terminal.run", "input": {"command": "printf ok"}},
        tool_name="terminal.run",
        input_preview={"command": "printf ok"},
        remaining_requests=[],
        next_iteration=2,
        approval_id=approval_id,
    )


def _materialized_context(
    *,
    text: str,
    expected_sha256: str | None = None,
    tool: str = "clipboard.write",
) -> ToolApprovalResumeContext:
    content_sha256 = expected_sha256 or hashlib.sha256(text.encode("utf-8")).hexdigest()
    request_input = {"text": text} if tool == "clipboard.write" else {"action": "send"}
    return ToolApprovalResumeContext(
        run_id="run-materialized-approval",
        timeline=[_timeline("agent.run.resumed", "baseline")],
        artifacts=[],
        broker=SimpleNamespace(),
        allowed_tools=[tool],
        budget=SimpleNamespace(),
        messages=[{"role": "assistant", "content": "materialized privately"}],
        tool_request={
            "tool": tool,
            "input": request_input,
            "request_id": "fresh-materialized-request",
            "decision_id": "decision-materialized",
            "plan_id": "plan-materialized",
            "tool_plan_id": "tool-plan-materialized",
            "step_id": "write-materialized-content",
            "tool_call_id": "call-write-materialized-content",
            "materialization_binding_id": "materialization-binding-test",
            "materialized_content_sha256": content_sha256,
            **(
                {"depends_on": ["draft-materialized-content"]}
                if tool == "desktop.submit_foreground"
                else {}
            ),
        },
        tool_name=tool,
        input_preview=request_input,
        remaining_requests=[],
        next_iteration=1,
        approval_id="approval-materialized",
    )


def _approval_resume_coordinator(*, calls: list[dict[str, Any]]) -> ApprovalResumeCoordinator:
    return ApprovalResumeCoordinator(
        call_agent_tool=lambda request, *_args, **_kwargs: calls.append(dict(request))
        or {"ok": True},
        fatal_tool_failure_detail=lambda *_args, **_kwargs: "",
        append_tool_result_message=lambda *_args, **_kwargs: None,
        run_tool_requests=lambda *_args, **_kwargs: None,
        timeline_factory=_timeline,
    )


def test_materialized_approval_resume_rejects_changed_bytes_before_tool_call() -> None:
    calls: list[dict[str, Any]] = []
    context = _materialized_context(
        text="changed content",
        expected_sha256=hashlib.sha256("approved content".encode("utf-8")).hexdigest(),
    )

    with pytest.raises(AgentRuntimeError, match="materialization_hash_mismatch"):
        _approval_resume_coordinator(calls=calls).execute_approved_tool(context)

    assert calls == []


def test_materialized_send_approval_requires_same_binding_dependency_receipt() -> None:
    calls: list[dict[str, Any]] = []
    context = _materialized_context(
        text="message body",
        tool="desktop.submit_foreground",
    )

    with pytest.raises(AgentRuntimeError, match="materialization_source_missing"):
        _approval_resume_coordinator(calls=calls).execute_approved_tool(context)

    assert calls == []


def test_materialized_approval_resume_replays_canonical_result_at_most_once() -> None:
    calls: list[dict[str, Any]] = []
    context = _materialized_context(text="\n精确剪贴板内容 🌙\n")
    coordinator = _approval_resume_coordinator(calls=calls)

    coordinator.execute_approved_tool(context)
    coordinator.execute_approved_tool(context)

    assert len(calls) == 1
    canonical = [
        event
        for event in context.timeline
        if event.get("approval_resume_result_canonical") is True
    ]
    assert len(canonical) == 1
    assert canonical[0]["materialization_binding_id"] == (
        "materialization-binding-test"
    )
    assert canonical[0]["materialized_content_sha256"] == hashlib.sha256(
        "\n精确剪贴板内容 🌙\n".encode("utf-8")
    ).hexdigest()
    assert canonical[0]["tool_plan_id"] == "tool-plan-materialized"
    assert canonical[0]["tool_call_id"] == "call-write-materialized-content"


def test_materialized_send_approval_accepts_same_scope_dependency_once() -> None:
    calls: list[dict[str, Any]] = []
    context = _materialized_context(
        text="message body",
        tool="desktop.submit_foreground",
    )
    context.timeline.append(
        _timeline(
            "agent.tool.call",
            "desktop.safe_type_text",
            run_id=context.run_id,
            decision_id="decision-materialized",
            plan_id="plan-materialized",
            step_id="draft-materialized-content",
            materialization_binding_id="materialization-binding-test",
            materialized_content_sha256=hashlib.sha256(
                "message body".encode("utf-8")
            ).hexdigest(),
            result={"ok": True, "action": "desktop.safe_type_text"},
        )
    )

    _approval_resume_coordinator(calls=calls).execute_approved_tool(context)

    assert len(calls) == 1


@pytest.mark.parametrize("mismatch", ["run", "decision", "plan", "dependency"])
def test_materialized_send_approval_rejects_wrong_dependency_scope(
    mismatch: str,
) -> None:
    calls: list[dict[str, Any]] = []
    context = _materialized_context(
        text="message body",
        tool="desktop.submit_foreground",
    )
    event = _timeline(
        "agent.tool.call",
        "desktop.safe_type_text",
        run_id=("wrong-run" if mismatch == "run" else context.run_id),
        decision_id=(
            "wrong-decision" if mismatch == "decision" else "decision-materialized"
        ),
        plan_id=("wrong-plan" if mismatch == "plan" else "plan-materialized"),
        step_id=(
            "wrong-dependency"
            if mismatch == "dependency"
            else "draft-materialized-content"
        ),
        materialization_binding_id="materialization-binding-test",
        materialized_content_sha256=hashlib.sha256(
            "message body".encode("utf-8")
        ).hexdigest(),
        result={"ok": True, "action": "desktop.safe_type_text"},
    )
    context.timeline.append(event)

    with pytest.raises(AgentRuntimeError, match="materialization_source_missing"):
        _approval_resume_coordinator(calls=calls).execute_approved_tool(context)

    assert calls == []


def test_next_approval_cas_loser_does_not_mutate_caller_timeline_or_artifacts() -> None:
    current = {
        "run_id": "run-resume-copy-on-write",
        "status": "cancelled",
        "result": "cancelled by user",
        "pending_approval": {},
        "updated_at": "winner-version",
    }
    events: list[tuple[str, str, dict[str, Any]]] = []
    context = _context()
    initial_timeline = list(context.timeline)
    initial_artifacts = list(context.artifacts)
    coordinator = ApprovalResumeProjectionCoordinator(
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        update_run=lambda *_args, **_kwargs: None,
        update_agent_run_group_if_root=lambda _run: None,
        mark_parent_workflows_child_running=lambda _run: None,
        get_run=lambda _run_id: dict(current),
    )

    result = coordinator.project_required(
        context,
        {
            "approval_id": "approval-next",
            "tool": "desktop.verify",
            "input_preview": {"app": "Notes"},
        },
    )

    assert result == current
    assert context.timeline == initial_timeline
    assert context.artifacts == initial_artifacts
    assert events == []


def test_approval_claim_cas_loser_does_not_mutate_caller_context() -> None:
    context = _context()
    initial_timeline = deepcopy(context.timeline)
    initial_artifacts = deepcopy(context.artifacts)

    def approve_tool_run(
        _run_id: str,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        timeline.append(_timeline("agent.tool.approval_approved", "ghost"))
        artifacts.append({"kind": "file", "path": "ghost.txt"})
        return None

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {},
        fatal_tool_failure_detail=lambda *_args, **_kwargs: "",
        append_tool_result_message=lambda *_args, **_kwargs: None,
        run_tool_requests=lambda *_args, **_kwargs: None,
        timeline_factory=_timeline,
        claim_pending_approval=lambda *_args, **_kwargs: True,
        approve_tool_run=approve_tool_run,
        get_current_run=lambda _run_id: {
            "run_id": context.run_id,
            "status": "cancelled",
            "updated_at": "winner-version",
        },
    )

    result = coordinator.claim_and_project_approved_tool(
        context.run_id,
        {"approval_id": context.approval_id},
        context,
        resumed_detail="Approval accepted",
        running_result="Continuing",
        expected_approval_id=context.approval_id,
    )

    assert result is None
    assert context.timeline == initial_timeline
    assert context.artifacts == initial_artifacts


def test_approval_running_projection_cas_loser_has_no_ghost_timeline_or_event() -> None:
    timeline = [_timeline("agent.tool.approval_required", "terminal.run")]
    artifacts = [{"kind": "file", "path": "baseline.txt"}]
    initial_timeline = deepcopy(timeline)
    events: list[tuple[str, str, dict[str, Any]]] = []
    coordinator = ApprovalCoordinator(
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        update_run=lambda *_args, **_kwargs: None,
    )

    result = coordinator.approve_tool_run(
        "run-resume-copy-on-write",
        timeline=timeline,
        artifacts=artifacts,
        tool_name="terminal.run",
        input_preview={"command": "printf ok"},
        resumed_detail="Approval accepted",
        running_result="Continuing",
        expected_approval_id="approval-resume",
    )

    assert result is None
    assert timeline == initial_timeline
    assert artifacts == [{"kind": "file", "path": "baseline.txt"}]
    assert events == []


def test_continuation_cas_loser_discards_local_tool_mutations_and_events() -> None:
    context = _context()
    initial_timeline = deepcopy(context.timeline)
    initial_artifacts = deepcopy(context.artifacts)
    initial_messages = deepcopy(context.messages)
    events: list[tuple[str, str, dict[str, Any]]] = []

    def call_agent_tool(
        _request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        timeline.append(_timeline("agent.tool.call", "terminal.run", attempt=True))
        artifacts.append({"kind": "file", "path": "ghost-result.txt"})
        return {"ok": True, "stdout": "ok"}

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=call_agent_tool,
        fatal_tool_failure_detail=lambda *_args, **_kwargs: "",
        append_tool_result_message=lambda messages, *_args, **_kwargs: messages.append(
            {"role": "tool", "content": "ok"}
        ),
        run_tool_requests=lambda *_args, **_kwargs: None,
        timeline_factory=_timeline,
        continue_custom_api_agent=lambda *_args, **_kwargs: "done",
        append_run_event=lambda run_id, event_type, payload, **_kwargs: events.append(
            (run_id, event_type, deepcopy(payload))
        ),
    )
    winner = {
        "run_id": context.run_id,
        "status": "cancelled",
        "result": "cancelled by another connection",
    }

    def project_completed(
        projected_context: ToolApprovalResumeContext,
        _result_text: str,
    ) -> dict[str, Any]:
        setattr(projected_context, "_approval_resume_projection_state", "cas_lost")
        return winner

    result = coordinator.continue_and_project_after_approved_tool(
        agent={"agent_id": "agent-1"},
        context=context,
        project_completed=project_completed,
        project_required=lambda *_args: {"status": "approval_required"},
        project_failed=lambda *_args: {"status": "failed"},
    )

    assert result == winner
    assert context.timeline == initial_timeline
    assert context.artifacts == initial_artifacts
    assert context.messages == initial_messages
    assert events == []


def test_durable_executed_receipt_redacts_secrets_and_is_not_goal_evidence() -> None:
    context = _context()
    secret = "sk-super-secret-value-123456789"
    events: list[tuple[str, dict[str, Any], dict[str, Any]]] = []

    def append_run_event(
        _run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **event_fields: Any,
    ) -> dict[str, Any]:
        events.append((event_type, deepcopy(payload), dict(event_fields)))
        return {"event_type": event_type}

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "action": "terminal.run",
            "api_key": secret,
            "stderr": f"Authorization: Bearer {secret}",
            "effects": ["file.changed"],
        },
        fatal_tool_failure_detail=lambda *_args, **_kwargs: "",
        append_tool_result_message=lambda *_args, **_kwargs: None,
        run_tool_requests=lambda *_args, **_kwargs: None,
        timeline_factory=_timeline,
        continue_custom_api_agent=lambda *_args, **_kwargs: "done",
        append_run_event=append_run_event,
        get_current_run=lambda _run_id: {
            "run_id": context.run_id,
            "status": "running",
            "updated_at": "running-version",
        },
    )

    result = coordinator.continue_and_project_after_approved_tool(
        agent={"agent_id": "agent-1"},
        context=context,
        project_completed=lambda *_args: {
            "run_id": context.run_id,
            "status": "completed",
            "updated_at": "completed-version",
        },
        project_required=lambda *_args: {"status": "approval_required"},
        project_failed=lambda *_args: {"status": "failed"},
    )

    assert result["status"] == "completed"
    receipts = [payload for event_type, payload, _scope in events if event_type == "agent.tool.executed_after_claim"]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["completion_evidence"] is False
    assert receipt["goal_evidence"] is False
    assert receipt["external_effect_possible"] is True
    serialized = json.dumps(receipt, ensure_ascii=False)
    assert secret not in serialized
    assert "[redacted]" in serialized
