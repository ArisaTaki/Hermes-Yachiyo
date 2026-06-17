"""ToolCall RunEvent replay helper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import PublicRunEvent
from apps.shell.yachiyo_agent.tool_call_event_snapshots import (
    tool_call_payload_from_event,
    tool_status_from_event_type,
)


def test_tool_call_payload_from_event_preserves_approval_trace_context() -> None:
    payload = tool_call_payload_from_event(
        PublicRunEvent(
            run_id="run-tool-context",
            sequence=7,
            event_type="tool.approval_required",
            detail="terminal.run",
            created_at="2026-06-17T00:00:00Z",
            payload={
                "tool_call_id": "call-1",
                "input_preview": {"command": "npm test"},
                "pending_approval": {
                    "approval_id": "approval-1",
                    "risk_level": "high",
                    "policy_reason": "terminal command requires approval",
                },
                "group_id": "group-1",
                "group_run_id": "group-run-1",
                "member_agent_id": "agent-1",
                "member_agent_name": "Planner",
                "workflow_id": "workflow-1",
                "workflow_run_id": "workflow-run-1",
                "workflow_node_id": "test",
                "workflow_node_label": "Run Tests",
            },
        )
    )

    assert payload["tool_name"] == "terminal.run"
    assert payload["status"] == "waiting_approval"
    assert payload["approval_id"] == "approval-1"
    assert payload["risk_level"] == "high"
    assert payload["source_runnable_id"] == "agent-1"
    assert payload["source_runnable_name"] == "Planner"
    assert payload["input_preview"] == {
        "command": "npm test",
        "approval_id": "approval-1",
        "risk_level": "high",
        "policy_reason": "terminal command requires approval",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "member_agent_id": "agent-1",
        "member_agent_name": "Planner",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "test",
        "workflow_node_label": "Run Tests",
    }


def test_tool_call_status_from_event_type_covers_terminal_approval_aliases() -> None:
    assert tool_status_from_event_type("tool.approval_timeout") == "expired"
    assert tool_status_from_event_type("agent.tool.approval_cancelled") == "cancelled"
    assert tool_status_from_event_type("agent.tool.denied") == "denied"
    assert tool_status_from_event_type("agent.tool.completed") == "completed"
