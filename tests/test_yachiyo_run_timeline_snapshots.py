"""Tests for Studio-facing RunTimeline public snapshot projection."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import RunTimelineSnapshot
from apps.shell.yachiyo_agent.run_timeline_snapshots import (
    run_timeline_snapshot_from_payload,
)


def test_run_timeline_snapshot_projects_studio_runtime_facts() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-studio-1",
            "parent_run_id": "run-parent-1",
            "group_run_id": "group-run-1",
            "workflow_run_id": "workflow-run-1",
            "agent_id": "agent-1",
            "status": "approval_required",
            "title": "Review project",
            "task_id": "task-1",
            "session_id": "chat-1",
            "task_run_link_last_event_sequence": "9",
            "pending_approval": {
                "approval_id": "approval-direct",
                "tool": "workspace.write_patch",
                "risk_level": "high",
                "input_preview": {"path": "README.md"},
            },
            "tool_calls": [
                {
                    "tool_call_id": "call-direct",
                    "tool_name": "workspace.read",
                    "status": "completed",
                    "input_preview": {"path": "README.md"},
                    "output_preview": {"ok": True},
                }
            ],
            "runtime_execution_envelope": {
                "envelope_id": "envelope-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "intent_kind": "data_analysis",
                "requests": [
                    {
                        "request_id": "request-1",
                        "tool_name": "workspace.read",
                        "runtime_stage": "discover",
                    }
                ],
                "runtime_stage_counts": {"discover": 1},
                "runtime_doctrine": "discover / operate / verify",
            },
            "artifacts": [
                {
                    "artifact_id": "artifact-direct",
                    "kind": "markdown",
                    "path": "reports/direct.md",
                    "title": "Direct report",
                    "bytes": 128,
                }
            ],
            "children": [
                {
                    "run_id": "child-run-1",
                    "kind": "agent_run",
                    "runnable_id": "agent-reviewer",
                    "title": "Reviewer",
                    "status": "completed",
                    "group_run_id": "group-run-1",
                }
            ],
            "events": [
                {
                    "event_id": "event-memory",
                    "event_type": "memory.retrieved",
                    "created_at": "2026-06-16T00:00:00Z",
                    "payload": {
                        "memories": [
                            {
                                "memory_id": "memory-1",
                                "kind": "preference",
                                "scope": "shared",
                            }
                        ],
                        "count": 1,
                    },
                },
                {
                    "event_id": "event-skill",
                    "event_type": "skill.selected",
                    "created_at": "2026-06-16T00:00:01Z",
                    "payload": {
                        "skill_id": "skill-1",
                        "skill_name": "Release reviewer",
                        "source_ref": "skills/release-reviewer",
                    },
                },
                {
                    "event_id": "event-artifact",
                    "event_type": "artifact.created",
                    "created_at": "2026-06-16T00:00:02Z",
                    "payload": {
                        "artifact_id": "artifact-event",
                        "kind": "markdown",
                        "path": "reports/event.md",
                        "title": "Event report",
                    },
                },
                {
                    "event_id": "event-rerun",
                    "event_type": "run.rerun.started",
                    "created_at": "2026-06-16T00:00:03Z",
                    "payload": {
                        "rerun_of_run_id": "run-original-1",
                        "rerun_of_kind": "agent_run",
                        "rerun_of_status": "failed",
                        "rerun_of_runnable_id": "agent-1",
                        "rerun_of_runnable_name": "Planner",
                        "original_created_at": "2026-06-15T00:00:00Z",
                        "original_updated_at": "2026-06-15T00:00:05Z",
                    },
                },
            ],
            "created_at": "2026-06-16T00:00:00Z",
            "updated_at": "2026-06-16T00:00:04Z",
        }
    )

    assert timeline.run_id == "run-studio-1"
    assert timeline.parent_run_id == "run-parent-1"
    assert timeline.group_run_id == "group-run-1"
    assert timeline.run_group_id == "group-run-1"
    assert timeline.workflow_run_id == "workflow-run-1"
    assert timeline.agent_id == "agent-1"
    assert timeline.task_run_link_last_event_sequence == 9
    assert timeline.pending_approval is not None
    assert timeline.pending_approval.approval_id == "approval-direct"
    assert timeline.pending_approval.group_run_id == "group-run-1"
    assert timeline.tool_calls[0].tool_call_id == "call-direct"
    assert timeline.tool_calls[0].output_preview == {"ok": True}
    assert timeline.runtime_execution_envelope is not None
    assert timeline.runtime_execution_envelope.envelope_id == "envelope-1"
    assert timeline.runtime_execution_envelope.requests[0].runtime_stage == "discover"
    assert timeline.memory_traces[0].memory_id == "memory-1"
    assert timeline.skill_traces[0].skill_id == "skill-1"
    assert [artifact.artifact_id for artifact in timeline.artifacts] == [
        "artifact-direct",
        "artifact-event",
    ]
    assert timeline.children[0].agent_id == "agent-reviewer"
    assert timeline.rerun_of_run_id == "run-original-1"
    assert timeline.rerun_original_updated_at == "2026-06-15T00:00:05Z"


def test_run_timeline_snapshot_returns_existing_public_snapshot() -> None:
    existing = RunTimelineSnapshot(
        run_id="run-existing",
        status="completed",
        created_at="2026-06-16T00:00:00Z",
        updated_at="2026-06-16T00:00:01Z",
    )

    assert run_timeline_snapshot_from_payload(existing) is existing


def test_run_timeline_projects_failed_runtime_request_into_replan_event() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-runtime-replan",
            "task_id": "task-runtime-replan",
            "workflow_run_id": "workflow-runtime-replan",
            "status": "running",
            "runtime_execution_envelope": {
                "envelope_id": "execution-envelope-runtime-replan",
                "decision_id": "decision-runtime-replan",
                "plan_id": "runtime-plan-replan",
                "intent_kind": "desktop_operation",
                "task_core": {
                    "core_id": "task-core-runtime-replan",
                    "workspace": {
                        "workspace_id": "workspace-runtime-replan",
                        "title": "Runtime Replan Workspace",
                    },
                    "todos": [
                        {
                            "todo_id": "todo-open-app",
                            "title": "Open app",
                            "step_id": "open-app",
                            "tool_name": "app.open",
                        }
                    ],
                },
                "requests": [
                    {
                        "request_id": "request-open-app",
                        "step_id": "open-app",
                        "tool_name": "app.open",
                        "runtime_stage": "operate",
                        "runtime_role": "open_app",
                        "fallback_tools": ["desktop.list_apps"],
                        "observation_evidence": {
                            "blocking_condition": "app_not_found",
                        },
                        "observation_retry": {
                            "tool": "desktop.list_apps",
                            "input": {"query": "PixelForge", "limit": 20},
                            "reason": "discover_app_again",
                        },
                    }
                ],
                "runtime_stage_counts": {"operate": 1},
            },
            "tool_calls": [
                {
                    "tool_call_id": "tool-call-open-app",
                    "tool_name": "app.open",
                    "step_id": "open-app",
                    "status": "failed",
                }
            ],
            "created_at": "2026-06-16T00:00:00Z",
            "updated_at": "2026-06-16T00:00:01Z",
        }
    )

    assert timeline.runtime_execution_envelope is not None
    assert timeline.runtime_execution_envelope.requests[0].status == "failed"
    assert timeline.task_progress is not None
    assert timeline.task_progress.needs_replan is True
    assert timeline.runtime_debug is not None
    assert timeline.runtime_debug.needs_replan is True
    assert any(
        event.event_type == "workflow.run.replan.requested"
        for event in timeline.events
    )
    assert any(
        recovery.selected_tool_name == "desktop.list_apps"
        for recovery in timeline.replan_recoveries
    )


def test_run_timeline_merges_stale_pending_approval_with_resolution_event() -> None:
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-approval-merge",
            "status": "approval_required",
            "pending_approval": {
                "approval_id": "approval-merge",
                "tool": "workspace.write_patch",
            },
            "events": [
                {
                    "event_type": "approval.approved",
                    "created_at": "2026-06-16T00:00:02Z",
                    "payload": {
                        "approval_id": "approval-merge",
                        "tool": "workspace.write_patch",
                    },
                }
            ],
        }
    )

    assert len(timeline.approvals) == 1
    assert timeline.approvals[0].approval_id == "approval-merge"
    assert timeline.approvals[0].status == "approved"
    assert timeline.approvals[0].resolved_at == "2026-06-16T00:00:02Z"
    assert timeline.pending_approval is None
