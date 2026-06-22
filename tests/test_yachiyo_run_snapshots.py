"""Tests for shared Chat/Studio run snapshot projection."""

from __future__ import annotations

from typing import Any

from apps.shell.yachiyo_agent.artifacts import (
    artifact_content_snapshot_from_payload,
    artifact_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.run_snapshots import (
    RunSnapshotProjector,
    agent_task_snapshot_from_payload,
    memory_trace_snapshots_from_events,
    run_timeline_snapshot_from_payload,
    skill_trace_snapshots_from_events,
    tool_call_snapshot_from_payload,
)
from apps.shell.yachiyo_agent import PublicRunEvent, ToolCallSnapshot
from apps.shell.yachiyo_agent.approvals import approval_card_from_payload
from apps.shell.yachiyo_agent.events import public_run_event_from_payload
from apps.shell.yachiyo_agent.groups import group_run_snapshot_from_payload
from apps.shell.yachiyo_agent.legacy_runs import LegacyRunPayloadProjector
from apps.shell.yachiyo_agent.links import studio_run_url
from apps.shell.yachiyo_agent.task_cards import (
    agent_task_snapshot_from_payload as legacy_task_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.timelines import (
    run_timeline_snapshot_from_payload as legacy_timeline_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.workflows import workflow_run_snapshot_from_payload


def _run_payload() -> dict:
    return {
        "task_id": "task-1",
        "run_id": "run-1",
        "session_id": "chat-1",
        "kind": "agent_run",
        "runnable_id": "agent-1",
        "user_goal": "Patch README",
        "status": "approval_required",
        "pending_approval": {
            "approval_id": "approval-1",
            "tool": "workspace.write_patch",
            "input_preview": {"path": "README.md"},
        },
        "timeline": [
            {
                "event": "agent.tool.call",
                "detail": "workspace.read",
                "input_preview": {"path": "README.md"},
                "result": {"ok": True},
            },
            {
                "event": "agent.tool.approval_required",
                "detail": "workspace.write_patch",
            },
        ],
        "artifacts": [
            {
                "kind": "markdown",
                "path": "reports/final.md",
                "bytes": 42,
            }
        ],
        "child_run_ids": ["child-1"],
        "run_group_id": "group-1",
        "created_at": "2026-06-14T00:00:00Z",
        "updated_at": "2026-06-14T00:00:01Z",
    }


def test_run_snapshot_projector_drives_chat_task_and_studio_timeline_shapes() -> None:
    projector = RunSnapshotProjector()
    payload = _run_payload()

    task = projector.task_snapshot_from_payload(payload)
    timeline = projector.timeline_snapshot_from_payload(payload)

    assert task.task_id == "task-1"
    assert task.status == "waiting_approval"
    assert task.needs_user_action is True
    assert task.pending_approvals[0].approval_id == "approval-1"
    assert task.pending_approvals[0].open_in_studio_url == "#/agents?run_id=run-1&group_run=group-1"
    assert task.recent_events[0].event_type == "agent.tool.call"
    assert task.artifacts[0].source_run_id == "run-1"
    assert task.open_in_studio_url == "#/agents?run_id=run-1&group_run=group-1"

    assert timeline.run_id == "run-1"
    assert timeline.agent_id == "agent-1"
    assert timeline.run_group_id == "group-1"
    assert timeline.pending_approval is not None
    assert timeline.pending_approval.approval_id == "approval-1"
    assert timeline.tool_calls[0].tool_name == "workspace.read"
    assert timeline.tool_calls[0].input_preview == {"path": "README.md"}
    assert timeline.tool_calls[0].output_preview == {"ok": True}
    assert timeline.artifacts[0].path == "reports/final.md"
    assert timeline.children[0].run_id == "child-1"


def test_run_timeline_tool_calls_merge_replay_aliases_with_stable_ids() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-tool-replay",
            "status": "completed",
            "events": [
                {
                    "event_id": "event-tool-1",
                    "event_type": "tool.requested",
                    "created_at": "2026-06-14T00:00:00Z",
                    "payload": {
                        "tool_call_id": "call-write",
                        "tool": "workspace.write_patch",
                        "arguments": {"path": "README.md"},
                        "risk": "high",
                    },
                },
                {
                    "event_id": "event-tool-2",
                    "event_type": "tool.approval_approved",
                    "created_at": "2026-06-14T00:00:01Z",
                    "payload": {
                        "tool_call_id": "call-write",
                        "tool": "workspace.write_patch",
                        "approval_id": "approval-write",
                    },
                },
                {
                    "event_id": "event-tool-3",
                    "event_type": "tool.completed",
                    "created_at": "2026-06-14T00:00:02Z",
                    "payload": {
                        "tool_call_id": "call-write",
                        "tool": "workspace.write_patch",
                        "output": {"path": "README.md", "ok": True},
                    },
                },
                {
                    "event_id": "event-tool-4",
                    "event_type": "tool.cancelled",
                    "created_at": "2026-06-14T00:00:03Z",
                    "payload": {
                        "tool_call_id": "call-cancelled",
                        "tool": "terminal.run",
                        "args": {"command": "sleep 10"},
                    },
                },
            ],
        }
    )

    assert len(timeline.tool_calls) == 2
    write_call = timeline.tool_calls[0]
    assert write_call.tool_call_id == "call-write"
    assert write_call.tool_name == "workspace.write_patch"
    assert write_call.status == "completed"
    assert write_call.risk_level == "high"
    assert write_call.input_preview == {
        "path": "README.md",
        "approval_id": "approval-write",
        "risk_level": "high",
    }
    assert write_call.output_preview == {"path": "README.md", "ok": True}
    assert write_call.approval_id == "approval-write"
    assert write_call.started_at == "2026-06-14T00:00:00Z"
    assert write_call.completed_at == "2026-06-14T00:00:02Z"

    cancelled_call = timeline.tool_calls[1]
    assert cancelled_call.tool_call_id == "call-cancelled"
    assert cancelled_call.status == "cancelled"
    assert cancelled_call.input_preview == {"command": "sleep 10"}
    assert cancelled_call.completed_at == "2026-06-14T00:00:03Z"


def test_agent_task_snapshot_filters_secret_and_internal_recent_events() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-visible-events",
            "run_id": "run-visible-events",
            "status": "running",
            "events": [
                {"event_type": "task.started", "payload": {"step": "visible"}},
                {
                    "event_type": "tool.approval_required",
                    "sensitivity": "secret",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf sk-secret-value"},
                    },
                },
                {
                    "event_type": "artifact.created",
                    "visibility": "internal",
                    "payload": {"path": "internal-report.md"},
                },
            ],
        }
    )

    assert [event.event_type for event in task.recent_events] == ["task.started"]
    assert task.recent_events[0].payload == {"step": "visible"}
    assert task.pending_approvals == []
    assert task.artifacts == []


def test_public_run_event_redacts_secret_payload_and_sensitive_public_text() -> None:
    secret_event = public_run_event_from_payload(
        {
            "event_type": "agent.tool.call",
            "run_id": "run-secret",
            "sequence": 7,
            "title": "terminal command",
            "detail": "printf sk-secret-value",
            "sensitivity": "secret",
            "payload": {
                "tool": "terminal.run",
                "input_preview": {"command": "printf sk-secret-value"},
            },
        }
    )

    assert secret_event.sensitivity == "secret"
    assert secret_event.title == "Secret event"
    assert secret_event.detail is None
    assert secret_event.payload == {"redacted": True, "reason": "secret_event"}

    public_event = public_run_event_from_payload(
        {
            "event_type": "model.request.failed",
            "run_id": "run-public",
            "detail": "provider returned sk-public-secret-value",
            "payload": {"error": "token sk-public-secret-value failed"},
        }
    )

    assert public_event.sensitivity == "public"
    assert "sk-public-secret-value" not in str(public_event.detail)
    assert "sk-public-secret-value" not in str(public_event.payload)


def test_run_timeline_snapshot_redacts_secret_run_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-secret-timeline",
            "status": "running",
            "events": [
                {"event_type": "task.started", "payload": {"step": "visible"}},
                {
                    "event_type": "agent.tool.call",
                    "sensitivity": "secret",
                    "detail": "printf sk-secret-value",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf sk-secret-value"},
                    },
                },
            ],
        }
    )

    assert [event.event_type for event in timeline.events] == ["task.started", "agent.tool.call"]
    assert timeline.events[0].payload == {"step": "visible"}
    assert timeline.events[1].sensitivity == "secret"
    assert timeline.events[1].detail is None
    assert timeline.events[1].payload == {"redacted": True, "reason": "secret_event"}


def test_approval_card_redacts_sensitive_public_preview_and_text() -> None:
    approval = approval_card_from_payload(
        {
            "tool": "workspace.write",
            "title": "Approve command sk-sensitive-value",
            "description": "Needs token sk-sensitive-value",
            "input_preview": {
                "command": "printf sk-sensitive-value",
                "api_key": "secret-api-key-value",
            },
            "policy_reason": "bearer sensitive-token-value",
        },
        run_id="run-approval-redaction",
    )

    rendered = str(approval.model_dump(mode="json"))

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert approval.input_preview["api_key"] == "[redacted]"
    assert "[redacted]" in rendered


def test_artifact_public_snapshots_redact_sensitive_preview_and_content() -> None:
    artifact = artifact_snapshot_from_payload(
        {
            "artifact_id": "artifact-sk-sensitive-value",
            "title": "Report sk-sensitive-value",
            "path": "reports/sk-sensitive-value.md",
            "preview_text": "token sk-sensitive-value",
            "url": "https://example.test/sk-sensitive-value",
            "kind": "artifact",
        },
        run_id="run-1",
    )
    content = artifact_content_snapshot_from_payload(
        {
            "run_id": "run-1",
            "path": "reports/sk-sensitive-value.md",
            "content": "token sk-sensitive-value",
            "mime_type": "text/markdown",
        }
    )

    rendered = str({
        "artifact": artifact.model_dump(mode="json"),
        "content": content.model_dump(mode="json"),
    })

    assert "sk-sensitive-value" not in rendered
    assert "[redacted]" in rendered
    assert artifact.source_run_id == "run-1"
    assert content.run_id == "run-1"


def test_tool_call_public_snapshots_redact_sensitive_previews() -> None:
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


def test_trace_payload_previews_redact_direct_public_events() -> None:
    memory_event = PublicRunEvent(
        run_id="run-1",
        sequence=1,
        event_type="memory.retrieved",
        payload={
            "api_key": "secret-api-key-value",
            "api_key_configured": True,
            "memories": [
                {
                    "memory_id": "memory-1",
                    "kind": "preference",
                    "content": "token sk-sensitive-value",
                }
            ],
        },
    )
    skill_event = PublicRunEvent(
        run_id="run-1",
        sequence=2,
        event_type="skill.selected",
        payload={
            "skill_id": "skill-1",
            "skill_name": "Demo sk-sensitive-value",
            "result": {"description": "bearer sensitive-token-value"},
        },
    )

    memory_traces = memory_trace_snapshots_from_events([memory_event])
    skill_traces = skill_trace_snapshots_from_events([skill_event])
    rendered = str({
        "memory_traces": [trace.model_dump(mode="json") for trace in memory_traces],
        "skill_traces": [trace.model_dump(mode="json") for trace in skill_traces],
    })

    assert "sk-sensitive-value" not in rendered
    assert "sensitive-token-value" not in rendered
    assert memory_traces[0].payload_preview["api_key"] == "[redacted]"
    assert memory_traces[0].payload_preview["api_key_configured"] is True
    assert "[redacted]" in rendered


def test_studio_run_url_is_shared_by_run_task_and_approval_snapshots() -> None:
    run_id = "run with/slash"
    expected_url = "#/agents?run_id=run%20with%2Fslash"
    expected_group_url = "#/agents?run_id=run%20with%2Fslash&group_run=group%20with%2Fslash"

    assert studio_run_url(run_id) == expected_url
    assert studio_run_url(run_id, group_run_id="group with/slash") == expected_group_url
    assert studio_run_url("") is None

    task = agent_task_snapshot_from_payload({"run_id": run_id, "status": "completed"})
    approval = approval_card_from_payload({"tool": "workspace.read"}, run_id=run_id)
    grouped_task = agent_task_snapshot_from_payload({
        "run_id": run_id,
        "run_group_id": "group with/slash",
        "status": "approval_required",
        "pending_approval": {"tool": "workspace.write"},
    })
    grouped_approval = approval_card_from_payload(
        {"tool": "workspace.write"},
        run_id=run_id,
        group_run_id="group with/slash",
    )
    legacy_payload = LegacyRunPayloadProjector().chat_task_payload({"run_id": run_id})
    grouped_legacy_payload = LegacyRunPayloadProjector().chat_task_payload({
        "run_id": run_id,
        "run_group_id": "group with/slash",
    })

    assert task.open_in_studio_url == expected_url
    assert approval.open_in_studio_url == expected_url
    assert grouped_task.open_in_studio_url == expected_group_url
    assert grouped_task.pending_approvals[0].open_in_studio_url == expected_group_url
    assert grouped_approval.open_in_studio_url == expected_group_url
    assert legacy_payload["open_in_studio_url"] == expected_url
    assert grouped_legacy_payload["open_in_studio_url"] == expected_group_url


def test_run_timeline_child_snapshots_preserve_orchestration_context() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "parent-run",
            "status": "running",
            "children": [
                {
                    "run_id": "child-run",
                    "title": "Reviewer",
                    "status": "completed",
                    "kind": "agent_run",
                    "parent_run_id": "parent-run",
                    "group_run_id": "group-run-1",
                    "workflow_run_id": "workflow-run-1",
                    "workflow_node_id": "review",
                    "workflow_node_label": "Review",
                    "member_agent_id": "agent-reviewer",
                    "workflow_id": "workflow-1",
                }
            ],
        }
    )

    child = timeline.children[0]
    assert child.run_id == "child-run"
    assert child.parent_run_id == "parent-run"
    assert child.group_run_id == "group-run-1"
    assert child.run_group_id == "group-run-1"
    assert child.workflow_run_id == "workflow-run-1"
    assert child.workflow_node_id == "review"
    assert child.workflow_node_label == "Review"
    assert child.agent_id == "agent-reviewer"
    assert child.workflow_id == "workflow-1"


def test_run_timeline_projects_rerun_provenance_from_replay_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "rerun-1",
            "kind": "agent_run",
            "status": "running",
            "events": [
                {
                    "event_type": "run.rerun.started",
                    "payload": {
                        "rerun_of_run_id": "original-run-1",
                        "rerun_of_kind": "agent_run",
                        "rerun_of_status": "completed",
                        "rerun_of_runnable_id": "agent-1",
                        "rerun_of_runnable_name": "Planner",
                        "original_created_at": "2026-06-13T00:00:00Z",
                        "original_updated_at": "2026-06-13T00:00:04Z",
                    },
                }
            ],
        }
    )

    assert timeline.rerun_of_run_id == "original-run-1"
    assert timeline.rerun_of_kind == "agent_run"
    assert timeline.rerun_of_status == "completed"
    assert timeline.rerun_of_runnable_id == "agent-1"
    assert timeline.rerun_of_runnable_name == "Planner"
    assert timeline.rerun_original_created_at == "2026-06-13T00:00:00Z"
    assert timeline.rerun_original_updated_at == "2026-06-13T00:00:04Z"


def test_run_timeline_preserves_workflow_branch_replay_payloads() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "workflow-run-branch",
            "kind": "workflow_run",
            "status": "completed",
            "events": [
                {
                    "event_type": "workflow.node.condition",
                    "sequence": 1,
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "route",
                        "workflow_node_label": "Route",
                        "workflow_node_condition": "has_changes",
                        "workflow_node_condition_matched": True,
                        "workflow_node_selected_branch": "true",
                        "workflow_node_selected_target": "ship",
                    },
                },
                {
                    "event_type": "workflow.edge.followed",
                    "sequence": 2,
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "route",
                        "workflow_node_selected_branch": "true",
                        "workflow_node_selected_target": "ship",
                    },
                },
                {
                    "event_type": "workflow.run.resumed",
                    "sequence": 3,
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "ship",
                    },
                },
            ],
        }
    )

    assert timeline.workflow_run_id == "workflow-run-branch"
    assert [event.event_type for event in timeline.events] == [
        "workflow.node.condition",
        "workflow.edge.followed",
        "workflow.run.resumed",
    ]
    assert timeline.events[0].payload["workflow_node_selected_branch"] == "true"
    assert timeline.events[0].payload["workflow_node_selected_target"] == "ship"
    assert timeline.events[1].payload["workflow_node_selected_branch"] == "true"
    assert timeline.events[2].payload["workflow_node_id"] == "ship"


def test_legacy_task_and_timeline_functions_delegate_to_shared_projector() -> None:
    payload = _run_payload()

    assert legacy_task_snapshot_from_payload(payload) == agent_task_snapshot_from_payload(payload)
    assert legacy_timeline_snapshot_from_payload(payload) == run_timeline_snapshot_from_payload(payload)


def test_workflow_run_snapshot_derives_context_from_replay_events() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-events",
            "kind": "workflow_run",
            "status": "running",
            "user_goal": "Review docs",
            "events": [
                {
                    "event_type": "workflow.node.agent",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "draft",
                        "workflow_node_label": "Draft",
                    },
                },
                {
                    "event_type": "workflow.node.approval_required",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "review",
                        "workflow_node_label": "Review",
                    },
                },
            ],
        }
    )

    assert workflow_run.workflow_id == "workflow-1"
    assert workflow_run.workflow_run_id == "workflow-run-events"
    assert workflow_run.current_node_id == "review"
    assert workflow_run.current_node_label == "Review"
    assert workflow_run.objective == "Review docs"


def test_workflow_run_snapshot_derives_child_approval_bridge_from_replay_events() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-children",
            "kind": "workflow_run",
            "status": "approval_required",
            "workflow_id": "workflow-1",
            "user_goal": "Operate desktop",
            "events": [
                {
                    "event_type": "workflow.run.approval_required",
                    "payload": {
                        "child_run_id": "child-agent-run",
                        "status": "approval_required",
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-children",
                        "workflow_node_id": "type",
                        "workflow_node_label": "Type in foreground app",
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-typer",
                        "member_agent_name": "Typer",
                        "pending_approval": {
                            "approval_id": "approval-child-agent",
                            "tool": "desktop.type_text",
                            "input_preview": {"text": "hello"},
                        },
                    },
                    "created_at": "2026-06-22T00:00:01Z",
                }
            ],
        }
    )

    child = workflow_run.children[0]

    assert child.run_id == "child-agent-run"
    assert child.parent_run_id == "workflow-run-children"
    assert child.status == "approval_required"
    assert child.kind == "agent_run"
    assert child.group_run_id == "group-run-1"
    assert child.workflow_run_id == "workflow-run-children"
    assert child.workflow_node_id == "type"
    assert child.workflow_node_label == "Type in foreground app"
    assert child.agent_id == "agent-typer"
    assert workflow_run.pending_approval is not None
    assert workflow_run.pending_approval.approval_id == "approval-child-agent"
    assert workflow_run.pending_approval.source_runnable_id == "agent-typer"
    assert workflow_run.pending_approval.workflow_node_id == "type"


def test_workflow_run_snapshot_adds_lifecycle_events_from_status() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-lifecycle",
            "kind": "workflow_run",
            "status": "completed",
            "workflow_id": "workflow-1",
            "user_goal": "Review docs",
            "current_node_id": "done",
            "current_node_label": "Done",
            "created_at": "2026-06-15T00:00:00Z",
            "updated_at": "2026-06-15T00:00:03Z",
        }
    )

    assert [event.event_type for event in workflow_run.events] == [
        "workflow.run.started",
        "workflow.run.completed",
    ]
    assert [event.sequence for event in workflow_run.events] == [1, 2]
    assert workflow_run.events[0].payload == {
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-lifecycle",
        "objective": "Review docs",
        "status": "completed",
        "workflow_node_id": "done",
        "workflow_node_label": "Done",
    }
    assert workflow_run.events[1].created_at == "2026-06-15T00:00:03Z"
    assert workflow_run.workflow_id == "workflow-1"
    assert workflow_run.workflow_run_id == "workflow-run-lifecycle"


def test_workflow_run_snapshot_does_not_duplicate_existing_lifecycle_events() -> None:
    workflow_run = workflow_run_snapshot_from_payload(
        {
            "run_id": "workflow-run-existing-lifecycle",
            "kind": "workflow_run",
            "status": "failed",
            "workflow_id": "workflow-1",
            "events": [
                {
                    "event": "workflow.started",
                    "payload": {"workflow_id": "workflow-1"},
                },
                {
                    "event_type": "workflow.node.started",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "draft",
                        "workflow_node_label": "Draft",
                    },
                },
                {
                    "event_type": "workflow.failed",
                    "payload": {"workflow_id": "workflow-1"},
                },
            ],
        }
    )

    assert [event.event_type for event in workflow_run.events] == [
        "workflow.started",
        "workflow.node.started",
        "workflow.failed",
    ]
    assert workflow_run.current_node_id == "draft"
    assert workflow_run.workflow_id == "workflow-1"


def test_run_timeline_projects_tool_lifecycle_events_as_tool_call_snapshots() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-tools",
            "status": "running",
            "events": [
                {
                    "event_type": "tool.requested",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "tool.started",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                    },
                },
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "tool": "terminal.run",
                        "group_id": "group-1",
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-1",
                        "member_agent_name": "Planner",
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "test",
                        "workflow_node_label": "Run Tests",
                        "input_preview": {"command": "npm test"},
                        "output_preview": {"approval_required": True},
                        "pending_approval": {
                            "approval_id": "approval-tool",
                            "risk_level": "high",
                            "policy_reason": "terminal command requires approval",
                        },
                    },
                },
                {
                    "event_type": "tool.approved",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
                {
                    "event_type": "tool.rejected",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "rm -rf /tmp/demo"},
                        "reason": "Too risky",
                    },
                },
                {
                    "event_type": "tool.completed",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                        "output_preview": {"ok": True},
                    },
                },
                {
                    "event_type": "tool.failed",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "error": "exit 1",
                    },
                },
                {
                    "event": "agent.tool.denied",
                    "detail": "workspace.write",
                    "input_preview": {"path": "README.md"},
                },
                {"event_type": "model.output.completed", "payload": {"content": "done"}},
            ],
        }
    )

    assert [call.tool_name for call in timeline.tool_calls] == [
        "workspace.read",
        "terminal.run",
        "terminal.run",
        "workspace.write",
    ]
    assert [call.status for call in timeline.tool_calls] == [
        "completed",
        "failed",
        "denied",
        "denied",
    ]
    assert timeline.tool_calls[0].input_preview == {"path": "README.md"}
    assert timeline.tool_calls[0].output_preview == {"ok": True}
    assert timeline.tool_calls[1].approval_id == "approval-tool"
    assert timeline.tool_calls[1].risk_level == "high"
    assert timeline.tool_calls[1].source_runnable_id == "agent-1"
    assert timeline.tool_calls[1].source_runnable_name == "Planner"
    assert timeline.tool_calls[1].workflow_id == "workflow-1"
    assert timeline.tool_calls[1].workflow_run_id == "workflow-run-1"
    assert timeline.tool_calls[1].workflow_node_id == "test"
    assert timeline.tool_calls[1].workflow_node_label == "Run Tests"
    assert timeline.tool_calls[1].group_id == "group-1"
    assert timeline.tool_calls[1].group_run_id == "group-run-1"
    assert timeline.tool_calls[1].input_preview == {
        "command": "npm test",
        "approval_id": "approval-tool",
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
    assert timeline.tool_calls[1].output_preview == {
        "approval_required": True,
        "error": "exit 1",
    }
    assert timeline.tool_calls[2].input_preview == {"command": "rm -rf /tmp/demo"}
    assert timeline.tool_calls[3].input_preview == {"path": "README.md"}
    assert all(call.run_id == "run-tools" for call in timeline.tool_calls)


def test_run_timeline_keeps_repeated_identical_tool_lifecycles_separate() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-repeated-tools",
            "status": "completed",
            "events": [
                {
                    "event_type": "tool.requested",
                    "payload": {"tool": "workspace.read", "input_preview": {"path": "README.md"}},
                },
                {
                    "event_type": "tool.completed",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                        "output_preview": {"ok": True, "first": True},
                    },
                },
                {
                    "event_type": "tool.requested",
                    "payload": {"tool": "workspace.read", "input_preview": {"path": "README.md"}},
                },
                {
                    "event_type": "tool.completed",
                    "payload": {
                        "tool": "workspace.read",
                        "input_preview": {"path": "README.md"},
                        "output_preview": {"ok": True, "second": True},
                    },
                },
            ],
        }
    )

    assert [call.status for call in timeline.tool_calls] == ["completed", "completed"]
    assert timeline.tool_calls[0].output_preview == {"ok": True, "first": True}
    assert timeline.tool_calls[1].output_preview == {"ok": True, "second": True}


def test_run_timeline_correlates_tool_events_with_trace_keys_in_input_preview() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-tool-trace-preview",
            "status": "completed",
            "events": [
                {
                    "event_type": "tool.requested",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "tool.completed",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {
                            "command": "npm test",
                            "source_runnable_id": "agent-1",
                            "source_runnable_name": "Planner",
                        },
                        "output_preview": {"ok": True},
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
            ],
        }
    )

    assert len(timeline.tool_calls) == 1
    assert timeline.tool_calls[0].status == "completed"
    assert timeline.tool_calls[0].source_runnable_id == "agent-1"
    assert timeline.tool_calls[0].source_runnable_name == "Planner"
    assert timeline.tool_calls[0].input_preview == {
        "command": "npm test",
        "source_runnable_id": "agent-1",
        "source_runnable_name": "Planner",
    }
    assert timeline.tool_calls[0].output_preview == {"ok": True}


def test_run_timeline_projects_legacy_agent_tool_lifecycle_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-legacy-tools",
            "status": "running",
            "timeline": [
                {"event": "agent.tool.started", "detail": "workspace.search"},
                {"event": "agent.tool.completed", "detail": "workspace.read"},
                {"event": "agent.tool.failed", "detail": "terminal.run", "error": "exit 1"},
                {"event": "agent.tool.skipped", "detail": "workspace.write"},
                {"event": "agent.tool.approval_approved", "detail": "terminal.run"},
                {"event": "agent.tool.approval_rejected", "detail": "workspace.write"},
                {"event": "agent.tool.denied", "detail": "workspace.delete"},
            ],
        }
    )

    assert [call.tool_name for call in timeline.tool_calls] == [
        "workspace.search",
        "workspace.read",
        "terminal.run",
        "workspace.write",
        "terminal.run",
        "workspace.write",
        "workspace.delete",
    ]
    assert [call.status for call in timeline.tool_calls] == [
        "running",
        "completed",
        "failed",
        "skipped",
        "approved",
        "denied",
        "denied",
    ]
    assert timeline.tool_calls[2].output_preview == {"error": "exit 1"}
    assert all(call.run_id == "run-legacy-tools" for call in timeline.tool_calls)


def test_run_timeline_preserves_memory_and_skill_trace_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-memory-skill",
            "status": "completed",
            "events": [
                {
                    "event_type": "memory.retrieved",
                    "payload": {
                        "count": 1,
                        "group_id": "group-1",
                        "group_run_id": "group-run-1",
                        "memories": [
                            {
                                "memory_id": "memory-1",
                                "kind": "preference",
                                "scope": "global",
                            }
                        ],
                        "member_agent_id": "agent-researcher",
                        "member_agent_name": "Researcher",
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "retrieve-context",
                        "workflow_node_label": "Retrieve Context",
                    },
                },
                {
                    "event_type": "skill.selected",
                    "payload": {
                        "group_id": "group-1",
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-researcher",
                        "member_agent_name": "Researcher",
                        "result": {
                            "skill_id": "skill-1",
                            "name": "Demo Skill",
                            "description": "Reads project context",
                            "source_ref": "skills/demo/SKILL.md",
                            "source_type": "local_dir",
                        }
                    },
                },
                {
                    "event_type": "skill.dispatch.read",
                    "payload": {
                        "group_id": "group-1",
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-researcher",
                        "member_agent_name": "Researcher",
                        "tool": "skill.read",
                        "status": "completed",
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "read-skill",
                        "workflow_node_label": "Read Skill",
                        "result": {
                            "skill_id": "skill-1",
                            "name": "Demo Skill",
                        },
                    },
                },
            ],
        }
    )

    assert [event.event_type for event in timeline.events] == [
        "memory.retrieved",
        "skill.selected",
        "skill.dispatch.read",
    ]
    assert timeline.events[0].payload["memories"][0]["memory_id"] == "memory-1"
    assert timeline.events[0].payload["memories"][0]["kind"] == "preference"
    assert timeline.events[0].payload["workflow_node_id"] == "retrieve-context"
    assert timeline.events[0].payload["member_agent_id"] == "agent-researcher"
    assert timeline.events[0].payload["group_run_id"] == "group-run-1"
    assert timeline.events[1].payload["result"]["skill_id"] == "skill-1"
    assert timeline.events[1].payload["result"]["source_ref"] == "skills/demo/SKILL.md"
    assert timeline.events[1].payload["member_agent_id"] == "agent-researcher"
    assert timeline.events[2].payload["tool"] == "skill.read"
    assert timeline.events[2].payload["status"] == "completed"
    assert timeline.events[2].payload["workflow_node_label"] == "Read Skill"
    assert [trace.event_type for trace in timeline.memory_traces] == ["memory.retrieved"]
    assert timeline.memory_traces[0].memory_id == "memory-1"
    assert timeline.memory_traces[0].memory_kind == "preference"
    assert timeline.memory_traces[0].memory_scope == "global"
    assert timeline.memory_traces[0].count == 1
    assert timeline.memory_traces[0].source_runnable_id == "agent-researcher"
    assert timeline.memory_traces[0].source_runnable_name == "Researcher"
    assert timeline.memory_traces[0].workflow_id == "workflow-1"
    assert timeline.memory_traces[0].workflow_run_id == "workflow-run-1"
    assert timeline.memory_traces[0].workflow_node_id == "retrieve-context"
    assert timeline.memory_traces[0].workflow_node_label == "Retrieve Context"
    assert timeline.memory_traces[0].group_id == "group-1"
    assert timeline.memory_traces[0].group_run_id == "group-run-1"
    assert [trace.event_type for trace in timeline.skill_traces] == [
        "skill.selected",
        "skill.dispatch.read",
    ]
    assert timeline.skill_traces[0].skill_id == "skill-1"
    assert timeline.skill_traces[0].skill_name == "Demo Skill"
    assert timeline.skill_traces[0].source_ref == "skills/demo/SKILL.md"
    assert timeline.skill_traces[0].source_type == "local_dir"
    assert timeline.skill_traces[0].source_runnable_name == "Researcher"
    assert timeline.skill_traces[0].group_id == "group-1"
    assert timeline.skill_traces[1].tool_name == "skill.read"
    assert timeline.skill_traces[1].workflow_id == "workflow-1"
    assert timeline.skill_traces[1].workflow_node_id == "read-skill"
    assert timeline.tool_calls == []


def test_run_timeline_derives_memory_trace_from_result_memories() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-memory-result",
            "status": "completed",
            "events": [
                {
                    "event_type": "memory.retrieved",
                    "payload": {
                        "result": {
                            "memories": [
                                {
                                    "memory_id": "memory-result-1",
                                    "kind": "preference",
                                    "scope": "session",
                                }
                            ],
                        },
                        "workflow_node_id": "retrieve-context",
                        "group_run_id": "group-run-1",
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                }
            ],
        }
    )

    assert len(timeline.memory_traces) == 1
    trace = timeline.memory_traces[0]
    assert trace.memory_id == "memory-result-1"
    assert trace.memory_kind == "preference"
    assert trace.memory_scope == "session"
    assert trace.count == 1
    assert trace.workflow_node_id == "retrieve-context"
    assert trace.group_run_id == "group-run-1"


def test_run_timeline_derives_skill_trace_from_nested_skill_payload() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-skill-payload",
            "status": "completed",
            "events": [
                {
                    "event_type": "skill.selected",
                    "payload": {
                        "skill": {
                            "skill_id": "skill-nested-1",
                            "name": "Nested Skill",
                            "description": "Reads nested skill payloads",
                            "source_ref": "skills/nested/SKILL.md",
                            "source_type": "local_dir",
                        },
                        "workflow_node_id": "select-skill",
                        "group_run_id": "group-run-1",
                    },
                    "created_at": "2026-06-15T00:00:02Z",
                }
            ],
        }
    )

    assert len(timeline.skill_traces) == 1
    trace = timeline.skill_traces[0]
    assert trace.skill_id == "skill-nested-1"
    assert trace.skill_name == "Nested Skill"
    assert trace.source_ref == "skills/nested/SKILL.md"
    assert trace.source_type == "local_dir"
    assert trace.detail == "Reads nested skill payloads · skills/nested/SKILL.md · local_dir"
    assert trace.workflow_node_id == "select-skill"
    assert trace.group_run_id == "group-run-1"


def test_run_timeline_derives_approvals_and_artifacts_from_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-events-only",
            "status": "approval_required",
            "events": [
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "status": "waiting_approval",
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "workflow.node.approval_required",
                    "payload": {
                        "group_id": "group-1",
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-reviewer",
                        "member_agent_name": "Reviewer",
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "run-events-only",
                        "workflow_node_id": "review",
                        "workflow_node_label": "Review Gate",
                        "pending_approval": {
                            "approval_id": "approval-workflow",
                            "tool": "workflow.approval",
                            "input_preview": {"checkpoint": "Review Gate"},
                            "requested_at": "2026-06-15T00:00:01Z",
                        },
                    },
                },
                {
                    "event_type": "artifact.created",
                    "payload": {
                        "artifact_id": "artifact-tool",
                        "path": "notes.md",
                        "size_bytes": 9,
                        "source_tool": "artifact.write",
                    },
                    "created_at": "2026-06-15T00:00:02Z",
                },
                {
                    "event_type": "workflow.node.artifact",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "report",
                        "workflow_node_label": "Report",
                        "artifact": {
                            "path": "workflow-report.md",
                            "bytes": 42,
                        },
                    },
                    "created_at": "2026-06-15T00:00:03Z",
                },
            ],
        }
    )

    assert timeline.pending_approval is not None
    assert timeline.pending_approval.tool_name == "terminal.run"
    assert [approval.tool_name for approval in timeline.approvals] == [
        "terminal.run",
        "workflow.approval",
    ]
    assert timeline.approvals[0].approval_id == "run-events-only:tool.approval_required:1"
    assert timeline.approvals[0].input_preview == {"command": "npm test"}
    assert timeline.approvals[1].approval_id == "approval-workflow"
    assert timeline.approvals[1].source_runnable_id == "agent-reviewer"
    assert timeline.approvals[1].source_runnable_name == "Reviewer"
    assert timeline.approvals[1].workflow_id == "workflow-1"
    assert timeline.approvals[1].workflow_run_id == "run-events-only"
    assert timeline.approvals[1].workflow_node_id == "review"
    assert timeline.approvals[1].workflow_node_label == "Review Gate"
    assert timeline.approvals[1].group_id == "group-1"
    assert timeline.approvals[1].group_run_id == "group-run-1"
    assert timeline.approvals[1].input_preview == {
        "checkpoint": "Review Gate",
        "group_id": "group-1",
        "group_run_id": "group-run-1",
        "member_agent_id": "agent-reviewer",
        "member_agent_name": "Reviewer",
        "workflow_id": "workflow-1",
        "workflow_run_id": "run-events-only",
        "workflow_node_id": "review",
        "workflow_node_label": "Review Gate",
    }
    assert [artifact.path for artifact in timeline.artifacts] == [
        "notes.md",
        "workflow-report.md",
    ]
    assert timeline.artifacts[0].kind == "artifact"
    assert timeline.artifacts[0].size_bytes == 9
    assert timeline.artifacts[0].source_tool == "artifact.write"
    assert timeline.artifacts[1].kind == "workflow_artifact"
    assert timeline.artifacts[1].title == "Report"
    assert timeline.artifacts[1].size_bytes == 42
    assert timeline.artifacts[1].workflow_id == "workflow-1"
    assert timeline.artifacts[1].workflow_run_id == "workflow-run-1"
    assert timeline.artifacts[1].workflow_node_id == "report"
    assert timeline.artifacts[1].workflow_node_label == "Report"


def test_run_timeline_projects_generic_approval_required_alias() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-generic-approval-required",
            "status": "approval_required",
            "events": [
                {
                    "event_type": "approval.required",
                    "payload": {
                        "approval_id": "approval-generic-required",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                }
            ],
        }
    )

    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-generic-required"
    assert timeline.approvals[0].status == "pending"
    assert timeline.approvals[0].tool_name == "terminal.run"
    assert timeline.approvals[0].input_preview == {"command": "npm test"}


def test_run_timeline_derives_workflow_artifact_from_event_path() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-workflow-artifact-path",
            "status": "completed",
            "events": [
                {
                    "event_type": "workflow.node.artifact",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "summary",
                        "workflow_node_label": "Summary",
                        "artifact_path": "reports/workflow-summary.md",
                        "bytes": 128,
                        "content_type": "text/markdown",
                    },
                    "created_at": "2026-06-15T00:00:04Z",
                },
            ],
        }
    )

    assert len(timeline.artifacts) == 1
    artifact = timeline.artifacts[0]
    assert artifact.artifact_id == "run-workflow-artifact-path:reports/workflow-summary.md"
    assert artifact.kind == "workflow_artifact"
    assert artifact.title == "Summary"
    assert artifact.path == "reports/workflow-summary.md"
    assert artifact.size_bytes == 128
    assert artifact.mime_type == "text/markdown"
    assert artifact.workflow_id == "workflow-1"
    assert artifact.workflow_run_id == "workflow-run-1"
    assert artifact.workflow_node_id == "summary"
    assert artifact.workflow_node_label == "Summary"
    assert artifact.source_run_id == "run-workflow-artifact-path"
    assert artifact.created_at == "2026-06-15T00:00:04Z"


def test_run_timeline_projects_generic_workflow_artifact_alias() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-generic-workflow-artifact",
            "status": "completed",
            "events": [
                {
                    "event_type": "artifact.created",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "report",
                        "workflow_node_label": "Report",
                        "artifact": {"path": "reports/final.md", "bytes": 42},
                    },
                    "created_at": "2026-06-15T00:00:05Z",
                },
            ],
        }
    )

    artifact = timeline.artifacts[0]
    assert artifact.kind == "workflow_artifact"
    assert artifact.title == "Report"
    assert artifact.path == "reports/final.md"
    assert artifact.size_bytes == 42
    assert artifact.workflow_id == "workflow-1"
    assert artifact.workflow_run_id == "workflow-run-1"
    assert artifact.workflow_node_id == "report"
    assert artifact.workflow_node_label == "Report"


def test_run_timeline_projects_generic_group_artifact_alias() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-generic-group-artifact",
            "status": "completed",
            "events": [
                {
                    "event_type": "artifact.created",
                    "payload": {
                        "group_id": "group-1",
                        "group_run_id": "group-run-1",
                        "member_agent_id": "agent-reviewer",
                        "member_agent_name": "Reviewer",
                        "artifact": {"path": "reports/group.md", "bytes": 31},
                    },
                    "created_at": "2026-06-15T00:00:06Z",
                },
            ],
        }
    )

    artifact = timeline.artifacts[0]
    assert artifact.kind == "group_artifact"
    assert artifact.title == "Reviewer / reports/group.md"
    assert artifact.path == "reports/group.md"
    assert artifact.group_id == "group-1"
    assert artifact.group_run_id == "group-run-1"
    assert artifact.source_runnable_id == "agent-reviewer"
    assert artifact.source_runnable_name == "Reviewer"


def test_run_timeline_merges_artifact_alias_with_source_event() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-artifact-alias-merge",
            "status": "completed",
            "events": [
                {
                    "event_type": "workflow.node.artifact",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "report",
                        "workflow_node_label": "Report",
                        "artifact": {"path": "reports/final.md", "bytes": 42},
                    },
                },
                {
                    "event_type": "artifact.created",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_run_id": "workflow-run-1",
                        "workflow_node_id": "report",
                        "workflow_node_label": "Report",
                        "artifact": {"path": "reports/final.md", "bytes": 42},
                    },
                },
            ],
        }
    )

    assert len(timeline.artifacts) == 1
    assert timeline.artifacts[0].path == "reports/final.md"
    assert timeline.artifacts[0].kind == "workflow_artifact"
    assert timeline.artifacts[0].workflow_node_label == "Report"


def test_run_timeline_keeps_secret_events_out_of_derived_runtime_facts() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-secret-derived-facts",
            "status": "running",
            "events": [
                {
                    "event_type": "agent.tool.call",
                    "sensitivity": "secret",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf sk-secret-value"},
                    },
                },
                {
                    "event_type": "tool.approval_required",
                    "sensitivity": "secret",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "printf sk-secret-value"},
                    },
                },
                {
                    "event_type": "artifact.created",
                    "sensitivity": "secret",
                    "payload": {"path": "secret-report.md"},
                },
                {
                    "event_type": "memory.retrieved",
                    "sensitivity": "secret",
                    "payload": {
                        "count": 1,
                        "memories": [{"memory_id": "memory-secret", "kind": "token"}],
                    },
                },
                {
                    "event_type": "skill.selected",
                    "sensitivity": "secret",
                    "payload": {
                        "result": {
                            "skill_id": "skill-secret",
                            "name": "Secret Skill",
                        },
                    },
                },
            ],
        }
    )

    assert [event.sensitivity for event in timeline.events] == ["secret"] * 5
    assert [event.payload for event in timeline.events] == [
        {"redacted": True, "reason": "secret_event"},
    ] * 5
    assert timeline.tool_calls == []
    assert timeline.approvals == []
    assert timeline.pending_approval is None
    assert timeline.artifacts == []
    assert timeline.memory_traces == []
    assert timeline.skill_traces == []


def test_run_timeline_projects_legacy_agent_artifact_write_events() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-agent-artifact",
            "status": "completed",
            "timeline": [
                {
                    "event": "agent.artifact.write",
                    "detail": "agent-context.md",
                    "artifact": {
                        "kind": "context",
                        "path": "agent-context.md",
                        "bytes": 21,
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                }
            ],
        }
    )

    assert len(timeline.artifacts) == 1
    assert timeline.artifacts[0].artifact_id == "run-agent-artifact:agent-context.md"
    assert timeline.artifacts[0].kind == "context"
    assert timeline.artifacts[0].path == "agent-context.md"
    assert timeline.artifacts[0].size_bytes == 21
    assert timeline.artifacts[0].source_run_id == "run-agent-artifact"
    assert timeline.artifacts[0].created_at == "2026-06-15T00:00:00Z"


def test_run_snapshots_merge_artifact_payloads_with_event_trace_context() -> None:
    payload = {
        "run_id": "run-artifact-merge",
        "status": "completed",
        "artifacts": [
            {
                "kind": "markdown",
                "path": "reports/final.md",
                "bytes": 42,
            }
        ],
        "events": [
            {
                "event_type": "artifact.created",
                "payload": {
                    "path": "reports/final.md",
                    "source_tool": "artifact.write",
                    "workflow_id": "workflow-1",
                    "workflow_run_id": "workflow-run-1",
                    "workflow_node_id": "report",
                    "workflow_node_label": "Report",
                    "group_id": "group-1",
                    "group_run_id": "group-run-1",
                    "member_agent_id": "agent-writer",
                    "member_agent_name": "Writer",
                },
                "created_at": "2026-06-15T00:00:01Z",
            },
        ],
    }

    timeline = run_timeline_snapshot_from_payload(payload)

    assert len(timeline.artifacts) == 1
    assert timeline.artifacts[0].kind == "markdown"
    assert timeline.artifacts[0].path == "reports/final.md"
    assert timeline.artifacts[0].size_bytes == 42
    assert timeline.artifacts[0].source_tool == "artifact.write"
    assert timeline.artifacts[0].source_runnable_id == "agent-writer"
    assert timeline.artifacts[0].source_runnable_name == "Writer"
    assert timeline.artifacts[0].workflow_id == "workflow-1"
    assert timeline.artifacts[0].workflow_run_id == "workflow-run-1"
    assert timeline.artifacts[0].workflow_node_id == "report"
    assert timeline.artifacts[0].workflow_node_label == "Report"
    assert timeline.artifacts[0].group_id == "group-1"
    assert timeline.artifacts[0].group_run_id == "group-run-1"


def test_run_timeline_merges_approval_lifecycle_events_into_stable_cards() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-approval-lifecycle",
            "status": "cancelled",
            "events": [
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "pending_approval": {
                            "approval_id": "approval-terminal",
                            "tool": "terminal.run",
                            "input_preview": {"command": "npm test"},
                            "requested_at": "2026-06-15T00:00:00Z",
                        },
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "agent.tool.approval_approved",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "status": "completed",
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
                {
                    "event_type": "workflow.node.approval_required",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "review",
                        "workflow_node_label": "Review Gate",
                        "pending_approval": {
                            "approval_id": "approval-workflow",
                            "tool": "workflow.approval",
                            "input_preview": {"checkpoint": "Review Gate"},
                        },
                    },
                    "created_at": "2026-06-15T00:00:02Z",
                },
                {
                    "event_type": "workflow.node.approval_rejected",
                    "payload": {
                        "workflow_id": "workflow-1",
                        "workflow_node_id": "review",
                        "workflow_node_label": "Review Gate",
                        "input_preview": {"checkpoint": "Review Gate"},
                        "reason": "Needs more detail",
                    },
                    "created_at": "2026-06-15T00:00:03Z",
                },
            ],
        }
    )

    assert timeline.pending_approval is None
    assert [approval.approval_id for approval in timeline.approvals] == [
        "approval-terminal",
        "approval-workflow",
    ]
    assert [approval.status for approval in timeline.approvals] == ["approved", "rejected"]
    assert timeline.approvals[0].requested_at == "2026-06-15T00:00:00Z"
    assert timeline.approvals[0].resolved_at == "2026-06-15T00:00:01Z"
    assert timeline.approvals[0].input_preview == {"command": "npm test"}
    assert timeline.approvals[1].description == "Needs more detail"
    assert timeline.approvals[1].resolved_at == "2026-06-15T00:00:03Z"
    assert timeline.approvals[1].workflow_id == "workflow-1"
    assert timeline.approvals[1].workflow_node_id == "review"
    assert timeline.approvals[1].workflow_node_label == "Review Gate"
    assert timeline.approvals[1].input_preview == {
        "checkpoint": "Review Gate",
        "workflow_id": "workflow-1",
        "workflow_node_id": "review",
        "workflow_node_label": "Review Gate",
    }


def test_run_timeline_does_not_treat_empty_pending_approval_as_actionable() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-empty-pending",
            "status": "cancelled",
            "pending_approval": {},
            "events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-empty-pending",
                        "tool": "terminal.run",
                    },
                },
                {
                    "event_type": "agent.tool.approval_rejected",
                    "payload": {
                        "tool": "terminal.run",
                        "reason": "No",
                        "status": "cancelled",
                    },
                },
            ],
        }
    )

    assert timeline.pending_approval is None
    assert timeline.approvals[0].approval_id == "approval-empty-pending"
    assert timeline.approvals[0].status == "rejected"


def test_run_timeline_projects_approval_timeout_as_expired_card() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-approval-timeout",
            "status": "cancelled",
            "events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-timeout",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "approval.timeout",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "reason": "approval_wait_timeout",
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
            ],
        }
    )

    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-timeout"
    assert timeline.approvals[0].status == "expired"
    assert timeline.approvals[0].description == "approval_wait_timeout"
    assert timeline.approvals[0].resolved_at == "2026-06-15T00:00:01Z"
    assert len(timeline.tool_calls) == 1
    assert timeline.tool_calls[0].tool_name == "terminal.run"
    assert timeline.tool_calls[0].status == "expired"
    assert timeline.tool_calls[0].input_preview == {
        "command": "npm test",
        "approval_id": "approval-timeout",
    }
    assert timeline.tool_calls[0].completed_at == "2026-06-15T00:00:01Z"


def test_run_timeline_projects_approval_cancelled_as_cancelled_card() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-approval-cancelled",
            "status": "cancelled",
            "events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-cancelled",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                    "created_at": "2026-06-16T00:00:00Z",
                },
                {
                    "event_type": "approval.cancelled",
                    "payload": {
                        "approval_id": "approval-cancelled",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "reason": "Run cancelled",
                    },
                    "created_at": "2026-06-16T00:00:01Z",
                },
                {
                    "event_type": "run.cancelled",
                    "payload": {"status": "cancelled", "result": "Run cancelled"},
                    "created_at": "2026-06-16T00:00:02Z",
                },
            ],
        }
    )

    assert timeline.pending_approval is None
    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-cancelled"
    assert timeline.approvals[0].status == "cancelled"
    assert timeline.approvals[0].description == "Run cancelled"
    assert timeline.approvals[0].resolved_at == "2026-06-16T00:00:01Z"
    assert len(timeline.tool_calls) == 1
    assert timeline.tool_calls[0].approval_id == "approval-cancelled"
    assert timeline.tool_calls[0].status == "cancelled"
    assert timeline.tool_calls[0].completed_at == "2026-06-16T00:00:01Z"


def test_run_timeline_projects_legacy_approval_timeout_aliases_as_expired_tool_calls() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-approval-timeout-alias",
            "status": "cancelled",
            "events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-timeout-alias",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
                {
                    "event_type": "agent.tool.approval_timeout",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "reason": "approval_wait_timeout",
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
            ],
        }
    )

    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-timeout-alias"
    assert timeline.approvals[0].status == "expired"
    assert len(timeline.tool_calls) == 1
    assert timeline.tool_calls[0].tool_name == "terminal.run"
    assert timeline.tool_calls[0].status == "expired"


def test_run_timeline_merges_minimal_approval_resolution_with_pending_card() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-minimal-approval-resolution",
            "status": "completed",
            "events": [
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "approval_id": "approval-minimal-resolution",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "tool.approved",
                    "payload": {
                        "tool": "terminal.run",
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
            ],
        }
    )

    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-minimal-resolution"
    assert timeline.approvals[0].status == "approved"
    assert timeline.approvals[0].input_preview == {"command": "npm test"}
    assert timeline.approvals[0].resolved_at == "2026-06-15T00:00:01Z"


def test_run_timeline_keeps_ambiguous_minimal_approval_resolution_separate() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-ambiguous-approval-resolution",
            "status": "cancelled",
            "events": [
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "approval_id": "approval-test",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
                {
                    "event_type": "tool.approval_required",
                    "payload": {
                        "approval_id": "approval-build",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm run build"},
                    },
                },
                {
                    "event_type": "tool.rejected",
                    "payload": {
                        "tool": "terminal.run",
                        "reason": "ambiguous resolution payload",
                    },
                    "created_at": "2026-06-15T00:00:02Z",
                },
            ],
        }
    )

    assert len(timeline.approvals) == 3
    assert [approval.approval_id for approval in timeline.approvals] == [
        "approval-test",
        "approval-build",
        "run-ambiguous-approval-resolution:tool.rejected:3",
    ]
    assert [approval.status for approval in timeline.approvals] == [
        "pending",
        "pending",
        "rejected",
    ]


def test_chat_task_snapshot_derives_approval_and_artifact_cards_from_events() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-events-only",
            "run_id": "run-task-events",
            "title": "Write notes",
            "status": "approval_required",
            "recent_events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-write",
                        "tool": "workspace.write",
                        "input_preview": {"path": "notes.md"},
                    },
                },
                {
                    "event_type": "artifact.created",
                    "payload": {
                        "path": "notes.md",
                        "size_bytes": 12,
                    },
                },
            ],
        }
    )

    assert task.status == "waiting_approval"
    assert task.needs_user_action is True
    assert task.pending_approvals[0].approval_id == "approval-write"
    assert task.pending_approvals[0].tool_name == "workspace.write"
    assert task.artifacts[0].path == "notes.md"
    assert task.artifacts[0].source_run_id == "run-task-events"


def test_chat_task_snapshot_ignores_resolved_approval_cards_for_user_action() -> None:
    task = agent_task_snapshot_from_payload(
        {
            "task_id": "task-approved",
            "run_id": "run-approved",
            "title": "Run tests",
            "status": "completed",
            "recent_events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-approved",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
                {
                    "event_type": "agent.tool.approval_approved",
                    "payload": {
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                },
            ],
        }
    )

    assert task.status == "completed"
    assert task.needs_user_action is False
    assert task.pending_approvals == []


def test_run_snapshots_merge_stale_pending_approval_payload_with_resolved_events() -> None:
    payload = {
        "task_id": "task-stale-pending",
        "run_id": "run-stale-pending",
        "title": "Run tests",
        "status": "completed",
        "pending_approval": {
            "approval_id": "approval-stale",
            "tool": "terminal.run",
            "input_preview": {"command": "npm test"},
        },
        "events": [
            {
                "event_type": "tool.approved",
                "payload": {
                    "approval_id": "approval-stale",
                    "tool": "terminal.run",
                },
                "created_at": "2026-06-15T00:00:01Z",
            },
        ],
        "recent_events": [
            {
                "event_type": "tool.approved",
                "payload": {
                    "approval_id": "approval-stale",
                    "tool": "terminal.run",
                },
                "created_at": "2026-06-15T00:00:01Z",
            },
        ],
    }

    task = agent_task_snapshot_from_payload(payload)
    timeline = run_timeline_snapshot_from_payload(payload)

    assert task.needs_user_action is False
    assert task.pending_approvals == []
    assert timeline.pending_approval is None
    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-stale"
    assert timeline.approvals[0].status == "approved"
    assert timeline.approvals[0].input_preview == {"command": "npm test"}
    assert timeline.approvals[0].resolved_at == "2026-06-15T00:00:01Z"


def test_run_timeline_does_not_fallback_to_resolved_approval_for_stale_waiting_status() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-stale-status",
            "status": "approval_required",
            "events": [
                {
                    "event_type": "agent.tool.approval_required",
                    "payload": {
                        "approval_id": "approval-stale-status",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                    },
                    "created_at": "2026-06-16T00:00:00Z",
                },
                {
                    "event_type": "approval.cancelled",
                    "payload": {
                        "approval_id": "approval-stale-status",
                        "tool": "terminal.run",
                        "input_preview": {"command": "npm test"},
                        "reason": "Run cancelled",
                    },
                    "created_at": "2026-06-16T00:00:01Z",
                },
            ],
        }
    )

    assert timeline.status == "approval_required"
    assert timeline.pending_approval is None
    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].status == "cancelled"
    assert timeline.approvals[0].resolved_at == "2026-06-16T00:00:01Z"


def test_group_run_snapshot_reuses_shared_run_projection_for_children_artifacts_and_approvals() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-1",
            "group_id": "group-1",
            "title": "Team review",
            "status": "running",
            "objective": "Compare options",
            "events": [
                {
                    "event_type": "group.member.started",
                    "detail": "Planner started",
                    "payload": {"member_agent_id": "agent-1"},
                }
            ],
            "runs": [_run_payload()],
            "shared_artifacts": [{"kind": "markdown", "path": "team.md"}],
            "pending_approvals": [{"approval_id": "approval-group", "tool": "terminal.run"}],
        }
    )

    assert group_run.group_run_id == "group-run-1"
    assert [event.event_type for event in group_run.events[:2]] == [
        "group.run.started",
        "group.member.started",
    ]
    assert group_run.events[0].payload["group_run_id"] == "group-run-1"
    assert group_run.events[0].payload["group_id"] == "group-1"
    assert group_run.events[0].payload["objective"] == "Compare options"
    assert group_run.events[1].payload["member_agent_id"] == "agent-1"
    assert group_run.runs[0].run_id == "run-1"
    assert group_run.runs[0].tool_calls[0].tool_name == "workspace.read"
    assert group_run.runs[0].pending_approval is not None
    assert group_run.shared_artifacts[0].source_run_id == "group-run-1"
    assert group_run.shared_artifacts[0].path == "team.md"
    assert group_run.pending_approvals[0].run_id == "group-run-1"
    assert group_run.pending_approvals[0].open_in_studio_url == "#/agents?run_id=group-run-1&group_run=group-run-1"


def test_group_run_snapshot_injects_group_context_into_child_run_facts() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-child-context",
            "group_id": "group-child-context",
            "title": "Team review",
            "status": "running",
            "runs": [
                {
                    "run_id": "child-run-no-context",
                    "status": "approval_required",
                    "timeline": [
                        {
                            "event_type": "tool.approval_required",
                            "payload": {
                                "tool": "terminal.run",
                                "input_preview": {"command": "npm test"},
                                "pending_approval": {
                                    "approval_id": "approval-child-context",
                                    "tool": "terminal.run",
                                },
                            },
                        },
                        {
                            "event_type": "artifact.created",
                            "payload": {"path": "child-report.md"},
                        },
                        {
                            "event_type": "memory.retrieved",
                            "payload": {"count": 1},
                        },
                        {
                            "event_type": "skill.selected",
                            "payload": {
                                "skill_id": "skill-1",
                                "skill_name": "Research",
                            },
                        },
                    ],
                },
            ],
        }
    )

    child = group_run.runs[0]

    assert child.group_run_id == "group-run-child-context"
    assert child.run_group_id == "group-run-child-context"
    assert child.events[0].payload["group_id"] == "group-child-context"
    assert child.events[0].payload["group_run_id"] == "group-run-child-context"
    assert child.tool_calls[0].group_id == "group-child-context"
    assert child.tool_calls[0].group_run_id == "group-run-child-context"
    assert child.tool_calls[0].input_preview["group_id"] == "group-child-context"
    assert child.tool_calls[0].input_preview["group_run_id"] == "group-run-child-context"
    assert child.approvals[0].group_id == "group-child-context"
    assert child.approvals[0].group_run_id == "group-run-child-context"
    assert child.approvals[0].input_preview["group_id"] == "group-child-context"
    assert child.approvals[0].input_preview["group_run_id"] == "group-run-child-context"
    assert child.artifacts[0].group_id == "group-child-context"
    assert child.artifacts[0].group_run_id == "group-run-child-context"
    assert child.memory_traces[0].group_id == "group-child-context"
    assert child.memory_traces[0].group_run_id == "group-run-child-context"
    assert child.skill_traces[0].group_id == "group-child-context"
    assert child.skill_traces[0].group_run_id == "group-run-child-context"
    assert group_run.tool_calls[0].group_id == "group-child-context"
    assert group_run.tool_calls[0].group_run_id == "group-run-child-context"
    assert group_run.memory_traces[0].group_id == "group-child-context"
    assert group_run.memory_traces[0].group_run_id == "group-run-child-context"
    assert group_run.skill_traces[0].group_id == "group-child-context"
    assert group_run.skill_traces[0].group_run_id == "group-run-child-context"


def test_group_run_snapshot_rolls_foreground_lock_waiting_tool_calls_to_member() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-lock",
            "group_id": "group-desktop",
            "title": "Desktop team",
            "status": "running",
            "members": [
                {"agent_id": "agent-reviewer", "name": "Reviewer", "role": "reviewer"}
            ],
            "runs": [
                {
                    "run_id": "run-reviewer",
                    "agent_id": "agent-reviewer",
                    "status": "running",
                    "timeline": [
                        {
                            "event_type": "agent.tool.call",
                            "detail": "desktop.type_text",
                            "payload": {
                                "tool_call_id": "call-foreground-lock",
                                "result": {
                                    "ok": False,
                                    "action": "foreground_lock",
                                    "foreground_lock_busy": True,
                                    "locked_by": "group-run-lock:run-planner",
                                    "summary": "Foreground desktop action is already locked.",
                                },
                            },
                            "created_at": "2026-06-22T00:00:01Z",
                        },
                    ],
                },
            ],
        }
    )

    call = group_run.tool_calls[0]
    participant_call = group_run.participants[0].tool_calls[0]

    assert call.status == "blocked"
    assert call.foreground_lock_busy is True
    assert call.foreground_lock_holder == "group-run-lock:run-planner"
    assert call.group_id == "group-desktop"
    assert call.group_run_id == "group-run-lock"
    assert participant_call.tool_call_id == "call-foreground-lock"
    assert participant_call.foreground_lock_busy is True


def test_group_run_snapshot_accepts_members_as_participants() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-members",
            "group_id": "group-1",
            "title": "Members only",
            "status": "running",
            "members": [
                {"agent_id": "agent-1", "name": "Planner", "role": "planner"},
                {"agent_id": "agent-2", "name": "Reviewer", "role": "reviewer"},
            ],
            "events": [],
        }
    )

    assert [member.agent_id for member in group_run.participants] == [
        "agent-1",
        "agent-2",
    ]
    assert group_run.events[0].event_type == "group.run.started"
    assert group_run.events[0].payload["participant_count"] == 2


def test_legacy_group_run_payload_collects_child_group_events_for_replay() -> None:
    runtime = _FakeLegacyGroupRuntime()
    payload = LegacyRunPayloadProjector().group_run_from_legacy_run_group(
        {
            "run_group_id": "group-run-legacy",
            "title": "Team review",
            "status": "running",
            "summary": "Compare options",
            "child_run_ids": ["run-1", "run-2"],
        },
        runtime,
    )
    group_run = group_run_snapshot_from_payload(payload)

    assert [event["event_type"] for event in payload["events"]] == [
        "group.member.started",
        "group.member.completed",
    ]
    assert [event.event_type for event in group_run.events[:3]] == [
        "group.run.started",
        "group.member.started",
        "group.member.completed",
    ]
    assert [event.sequence for event in group_run.events[:3]] == [1, 2, 3]
    assert group_run.events[1].run_id == "run-1"
    assert group_run.events[1].payload["member_agent_id"] == "agent-1"
    assert group_run.events[1].payload["source_run_id"] == "run-1"
    assert group_run.events[1].payload["source_sequence"] == 7
    assert group_run.events[2].run_id == "run-2"
    assert group_run.events[2].payload["source_run_id"] == "run-2"
    assert group_run.events[2].payload["source_sequence"] == 3
    assert runtime.event_calls == ["run-1", "run-2"]


def test_group_run_snapshot_renumbers_child_run_events_for_group_replay() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-1",
            "status": "running",
            "events": [
                {
                    "event_type": "group.run.started",
                    "run_id": "child-run-1",
                    "sequence": 9,
                    "payload": {"run_group_id": "group-run-1"},
                },
                {
                    "event_type": "group.member.completed",
                    "run_id": "child-run-2",
                    "sequence": 1,
                    "payload": {"member_agent_id": "agent-2"},
                },
            ],
        }
    )

    assert [event.sequence for event in group_run.events] == [1, 2]
    assert group_run.events[0].payload["source_run_id"] == "child-run-1"
    assert group_run.events[0].payload["source_sequence"] == 9
    assert group_run.events[1].payload["source_run_id"] == "child-run-2"
    assert group_run.events[1].payload["source_sequence"] == 1


def test_group_run_snapshot_falls_back_to_legacy_event_keys_when_events_is_empty() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-run-legacy-events",
            "group_id": "group-1",
            "status": "running",
            "events": [],
            "run_events": [
                {
                    "event_type": "group.member.started",
                    "payload": {"member_agent_id": "agent-1"},
                }
            ],
        }
    )

    assert [event.event_type for event in group_run.events[:2]] == [
        "group.run.started",
        "group.member.started",
    ]


def test_group_run_snapshot_derives_approvals_and_artifacts_from_group_events() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-events-only",
            "group_id": "group-1",
            "title": "Team review",
            "status": "approval_required",
            "objective": "Compare options",
            "events": [
                {
                    "event_type": "group.approval_required",
                    "payload": {
                        "group_id": "group-1",
                        "member_agent_id": "agent-1",
                        "member_agent_name": "Planner",
                        "pending_approval": {
                            "approval_id": "approval-group-event",
                            "input_preview": {"decision": "continue"},
                        },
                    },
                    "created_at": "2026-06-15T00:00:00Z",
                },
                {
                    "event_type": "group.shared_artifact.created",
                    "payload": {
                        "member_agent_id": "agent-1",
                        "member_agent_name": "Planner",
                        "artifact": {
                            "path": "team-summary.md",
                            "bytes": 33,
                        },
                    },
                    "created_at": "2026-06-15T00:00:01Z",
                },
            ],
        }
    )

    assert [event.event_type for event in group_run.events[:2]] == [
        "group.run.started",
        "group.approval_required",
    ]
    assert group_run.pending_approvals[0].approval_id == "approval-group-event"
    assert group_run.pending_approvals[0].tool_name == "group.approval"
    assert group_run.pending_approvals[0].title == "Approve Planner"
    assert group_run.pending_approvals[0].input_preview == {
        "decision": "continue",
        "group_id": "group-1",
        "group_run_id": "group-events-only",
        "member_agent_id": "agent-1",
        "member_agent_name": "Planner",
    }
    assert group_run.shared_artifacts[0].kind == "group_artifact"
    assert group_run.shared_artifacts[0].title == "Planner / team-summary.md"
    assert group_run.shared_artifacts[0].path == "team-summary.md"
    assert group_run.shared_artifacts[0].size_bytes == 33
    assert group_run.shared_artifacts[0].source_run_id == "group-events-only"
    assert group_run.shared_artifacts[0].source_runnable_id == "agent-1"
    assert group_run.shared_artifacts[0].source_runnable_name == "Planner"
    assert group_run.shared_artifacts[0].group_id == "group-1"
    assert group_run.shared_artifacts[0].group_run_id == "group-events-only"


def test_group_run_snapshot_adds_terminal_lifecycle_event_from_status() -> None:
    group_run = group_run_snapshot_from_payload(
        {
            "group_run_id": "group-completed",
            "group_id": "group-1",
            "title": "Team review",
            "status": "completed",
            "objective": "Compare options",
            "child_run_ids": ["run-1"],
            "events": [
                {
                    "event_type": "group.member.completed",
                    "payload": {"member_agent_id": "agent-1"},
                },
            ],
        }
    )

    assert [event.event_type for event in group_run.events] == [
        "group.run.started",
        "group.member.completed",
        "group.run.completed",
    ]
    assert group_run.events[-1].payload["status"] == "completed"
    assert group_run.events[-1].payload["child_run_ids"] == ["run-1"]


class _FakeLegacyGroupRuntime:
    def __init__(self) -> None:
        self.event_calls: list[str] = []
        self.runs = {
            "run-1": {
                "run_id": "run-1",
                "runnable_id": "agent-1",
                "runnable_name": "Planner",
                "status": "running",
                "timeline": [{"event": "agent.run.started"}],
            },
            "run-2": {
                "run_id": "run-2",
                "runnable_id": "agent-2",
                "runnable_name": "Reviewer",
                "status": "completed",
                "timeline": [{"event": "group.member.completed"}],
            },
        }

    def get_run(self, run_id: str) -> dict[str, Any]:
        return dict(self.runs[run_id])

    def list_run_events(self, run_id: str) -> dict[str, Any]:
        self.event_calls.append(run_id)
        if run_id == "run-1":
            return {
                "events": [
                    {
                        "event_type": "group.member.started",
                        "sequence": 7,
                        "payload": {"member_agent_id": "agent-1"},
                    },
                    {
                        "event_type": "agent.tool.call",
                        "payload": {"tool": "workspace.read"},
                    },
                ]
            }
        return {
            "events": [
                {
                    "event_type": "group.member.completed",
                    "sequence": 3,
                    "payload": {"member_agent_id": "agent-2"},
                }
            ]
        }
