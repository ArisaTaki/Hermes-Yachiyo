"""Memory and Skill trace snapshot mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.contracts import PublicRunEvent
from apps.shell.yachiyo_agent.trace_snapshots import (
    memory_trace_snapshots_from_events,
    skill_trace_snapshots_from_events,
)


def test_trace_snapshot_mappers_filter_secret_events_and_preserve_context() -> None:
    memory_public = PublicRunEvent(
        run_id="run-1",
        sequence=1,
        event_type="memory.retrieved",
        payload={
            "count": 1,
            "group_id": "group-1",
            "run_group_id": "group-run-1",
            "member_agent_id": "agent-1",
            "member_agent_name": "Researcher",
            "workflow_id": "workflow-1",
            "workflow_run_id": "workflow-run-1",
            "workflow_node_id": "retrieve",
            "workflow_node_label": "Retrieve Context",
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "memories": [
                {
                    "memory_id": "memory-1",
                    "kind": "preference",
                    "scope": "global",
                }
            ],
        },
    )
    memory_secret = PublicRunEvent(
        run_id="run-1",
        sequence=2,
        event_type="memory.retrieved",
        sensitivity="secret",
        payload={"memory_id": "secret-memory"},
    )
    skill_public = PublicRunEvent(
        run_id="run-1",
        sequence=3,
        event_type="skill.dispatch.read",
        payload={
            "tool": "skill.read",
            "input_preview": {
                "core_id": "core-1",
                "workspace_id": "workspace-1",
                "task_id": "task-1",
            },
            "result": {
                "skill_id": "skill-1",
                "name": "Demo Skill",
                "source_ref": "skills/demo/SKILL.md",
                "source_type": "local_dir",
            },
        },
    )

    memory_traces = memory_trace_snapshots_from_events([memory_public, memory_secret])
    skill_traces = skill_trace_snapshots_from_events([skill_public])

    assert len(memory_traces) == 1
    assert memory_traces[0].memory_id == "memory-1"
    assert memory_traces[0].source_runnable_name == "Researcher"
    assert memory_traces[0].workflow_node_id == "retrieve"
    assert memory_traces[0].group_run_id == "group-run-1"
    assert memory_traces[0].core_id == "core-1"
    assert memory_traces[0].workspace_id == "workspace-1"
    assert memory_traces[0].task_id == "task-1"
    assert skill_traces[0].skill_id == "skill-1"
    assert skill_traces[0].tool_name == "skill.read"
    assert skill_traces[0].source_ref == "skills/demo/SKILL.md"
    assert skill_traces[0].core_id == "core-1"
    assert skill_traces[0].workspace_id == "workspace-1"
    assert skill_traces[0].task_id == "task-1"


def test_trace_snapshot_mappers_use_top_level_run_context() -> None:
    traces = memory_trace_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-1",
                sequence=1,
                event_type="memory.retrieved",
                source_runnable_id="agent-1",
                source_runnable_name="Researcher",
                workflow_id="workflow-1",
                workflow_run_id="workflow-run-1",
                workflow_node_id="retrieve",
                workflow_node_label="Retrieve Context",
                group_id="group-1",
                group_run_id="group-run-1",
                payload={
                    "memories": [
                        {
                            "memory_id": "memory-1",
                            "kind": "preference",
                            "scope": "global",
                        }
                    ],
                },
            )
        ]
    )

    assert len(traces) == 1
    assert traces[0].source_runnable_id == "agent-1"
    assert traces[0].source_runnable_name == "Researcher"
    assert traces[0].workflow_id == "workflow-1"
    assert traces[0].workflow_run_id == "workflow-run-1"
    assert traces[0].workflow_node_id == "retrieve"
    assert traces[0].workflow_node_label == "Retrieve Context"
    assert traces[0].group_id == "group-1"
    assert traces[0].group_run_id == "group-run-1"


def test_trace_snapshot_payload_previews_redact_sensitive_values() -> None:
    traces = memory_trace_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-1",
                sequence=1,
                event_type="memory.retrieved",
                payload={
                    "api_key": "secret-api-key-value",
                    "api_key_configured": True,
                    "memories": [{"memory_id": "memory-1"}],
                },
            )
        ]
    )

    rendered = str([trace.model_dump(mode="json") for trace in traces])

    assert "secret-api-key-value" not in rendered
    assert traces[0].payload_preview["api_key"] == "[redacted]"
    assert traces[0].payload_preview["api_key_configured"] is True
