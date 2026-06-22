"""ToolCall public snapshot mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import PublicRunEvent, ToolCallSnapshot
from apps.shell.yachiyo_agent.tool_call_snapshots import (
    tool_call_snapshot_from_payload,
    tool_call_snapshots_from_events,
    tool_call_snapshots_from_payloads,
)


def test_tool_call_snapshots_from_events_merge_lifecycle_and_trace_context() -> None:
    events = [
        PublicRunEvent(
            event_id="evt-1",
            run_id="run-tools",
            sequence=1,
            event_type="tool.requested",
            detail="workspace.write",
            payload={
                "tool_call_id": "call-write",
                "input_preview": {"path": "README.md"},
                "source_runnable_id": "agent-1",
                "source_runnable_name": "Planner",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "write",
                "workflow_node_label": "Write README",
                "group_id": "group-1",
                "group_run_id": "group-run-1",
            },
            created_at="2026-06-17T00:00:00Z",
        ),
        PublicRunEvent(
            event_id="evt-secret",
            run_id="run-tools",
            sequence=2,
            event_type="tool.completed",
            sensitivity="secret",
            payload={
                "tool_call_id": "call-secret",
                "tool_name": "terminal.run",
                "result": {"content": "secret"},
            },
        ),
        PublicRunEvent(
            event_id="evt-3",
            run_id="run-tools",
            sequence=3,
            event_type="tool.approval_required",
            detail="workspace.write",
            payload={
                "tool_call_id": "call-write",
                "pending_approval": {
                    "approval_id": "approval-write",
                    "risk_level": "high",
                    "policy_reason": "writes workspace files",
                },
                "input_preview": {"path": "README.md"},
                "group_id": "group-1",
                "group_run_id": "group-run-1",
                "member_agent_id": "agent-1",
                "member_agent_name": "Planner",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "write",
                "workflow_node_label": "Write README",
            },
            created_at="2026-06-17T00:00:01Z",
        ),
        PublicRunEvent(
            event_id="evt-4",
            run_id="run-tools",
            sequence=4,
            event_type="tool.completed",
            detail="workspace.write",
            payload={
                "tool_call_id": "call-write",
                "result": {"ok": True},
            },
            created_at="2026-06-17T00:00:02Z",
        ),
    ]

    snapshots = tool_call_snapshots_from_events(events)

    assert len(snapshots) == 1
    call = snapshots[0]
    assert call.tool_call_id == "call-write"
    assert call.run_id == "run-tools"
    assert call.tool_name == "workspace.write"
    assert call.status == "completed"
    assert call.approval_id == "approval-write"
    assert call.risk_level == "high"
    assert call.source_runnable_id == "agent-1"
    assert call.source_runnable_name == "Planner"
    assert call.workflow_id == "workflow-1"
    assert call.workflow_run_id == "workflow-run-1"
    assert call.workflow_node_id == "write"
    assert call.workflow_node_label == "Write README"
    assert call.group_id == "group-1"
    assert call.group_run_id == "group-run-1"
    assert call.input_preview == {
        "path": "README.md",
        "approval_id": "approval-write",
        "risk_level": "high",
        "policy_reason": "writes workspace files",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "member_agent_id": "agent-1",
        "member_agent_name": "Planner",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "write",
        "workflow_node_label": "Write README",
    }
    assert call.output_preview == {"ok": True}
    assert call.completed_at == "2026-06-17T00:00:02Z"


def test_tool_call_snapshot_from_payload_redacts_sensitive_previews() -> None:
    direct = tool_call_snapshot_from_payload(
        {
            "tool_call_id": "call-sk-sensitive-value",
            "run_id": "run-1",
            "tool_name": "terminal.run",
            "input_preview": {
                "command": "printf sk-sensitive-value",
                "api_key": "secret-api-key-value",
                "api_key_configured": True,
            },
            "error": "bearer sensitive-token-value",
        }
    )
    existing = tool_call_snapshot_from_payload(
        ToolCallSnapshot(
            tool_call_id="call-2",
            run_id="run-1",
            tool_name="workspace.read",
            status="completed",
            input_preview={"path": "sk-sensitive-value.md"},
            output_preview={"content": "token sk-sensitive-value"},
        )
    )

    rendered = str({
        "direct": direct.model_dump(mode="json"),
        "existing": existing.model_dump(mode="json"),
    })

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert direct.input_preview["api_key"] == "[redacted]"
    assert direct.input_preview["api_key_configured"] is True
    assert "[redacted]" in rendered


def test_tool_call_snapshot_from_payload_marks_foreground_lock_busy_as_blocked() -> None:
    snapshot = tool_call_snapshot_from_payload(
        {
            "tool_call_id": "call-foreground-lock",
            "run_id": "run-desktop",
            "tool_name": "desktop.type_text",
            "result": {
                "ok": False,
                "action": "foreground_lock",
                "foreground_lock_busy": True,
                "locked_by": "group-run-1:run-planner",
                "summary": "Foreground control is already held by Planner.",
            },
            "created_at": "2026-06-22T00:00:00Z",
        }
    )

    assert snapshot.status == "blocked"
    assert snapshot.completed_at == "2026-06-22T00:00:00Z"
    assert snapshot.output_preview["foreground_lock_busy"] is True
    assert snapshot.output_preview["locked_by"] == "group-run-1:run-planner"


def test_tool_call_snapshots_from_events_marks_foreground_lock_busy_as_blocked() -> None:
    snapshots = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-lock",
                run_id="run-desktop",
                sequence=1,
                event_type="agent.tool.call",
                detail="desktop.type_text",
                payload={
                    "tool_call_id": "call-foreground-lock",
                    "result": {
                        "ok": False,
                        "action": "foreground_lock",
                        "foreground_lock_busy": True,
                        "locked_by": "group-run-1:run-planner",
                        "summary": "Foreground control is already held by Planner.",
                    },
                },
                created_at="2026-06-22T00:00:01Z",
            )
        ]
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_name == "desktop.type_text"
    assert snapshots[0].status == "blocked"
    assert snapshots[0].completed_at == "2026-06-22T00:00:01Z"
    assert snapshots[0].output_preview["foreground_lock_busy"] is True


def test_tool_call_snapshots_from_payloads_prefers_payload_list_over_event_fallback() -> None:
    snapshots = tool_call_snapshots_from_payloads(
        [
            {
                "id": "payload-call",
                "tool": "workspace.read",
                "input": {"path": "README.md"},
                "output": {"ok": True},
            }
        ],
        run_id="run-payload",
        events=[
            PublicRunEvent(
                run_id="run-events",
                sequence=1,
                event_type="tool.completed",
                payload={"tool_call_id": "event-call", "tool_name": "terminal.run"},
            )
        ],
    )

    assert len(snapshots) == 1
    assert snapshots[0].tool_call_id == "payload-call"
    assert snapshots[0].run_id == "run-payload"
    assert snapshots[0].tool_name == "workspace.read"
    assert snapshots[0].input_preview == {"path": "README.md"}
    assert snapshots[0].output_preview == {"ok": True}
