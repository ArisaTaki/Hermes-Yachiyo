"""Artifact RunEvent public snapshot mapper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.artifact_event_snapshots import (
    artifact_payload_from_event,
    artifact_snapshots_from_events,
    merge_artifact_snapshot_lists,
)
from apps.shell.yachiyo_agent.artifacts import artifact_snapshot_from_payload
from apps.shell.yachiyo_agent.contracts import PublicRunEvent


def test_artifact_snapshots_from_events_preserve_runtime_trace_context() -> None:
    artifacts = artifact_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-1",
                run_id="run-artifacts",
                sequence=1,
                event_type="artifact.created",
                payload={
                    "artifact": {
                        "kind": "markdown",
                        "path": "reports/final.md",
                        "size_bytes": 42,
                        "preview_text": "done",
                    },
                    "source_tool": "artifact.write",
                    "member_agent_id": "agent-writer",
                    "member_agent_name": "Writer",
                    "workflow_id": "workflow-1",
                    "workflow_run_id": "workflow-run-1",
                    "workflow_node_id": "report",
                    "workflow_node_label": "Report",
                    "group_id": "group-1",
                    "group_run_id": "group-run-1",
                },
                created_at="2026-06-17T00:00:00Z",
            ),
            PublicRunEvent(
                event_id="evt-secret",
                run_id="run-artifacts",
                sequence=2,
                event_type="artifact.created",
                sensitivity="secret",
                payload={
                    "artifact": {
                        "path": "secrets.txt",
                        "preview_text": "secret-token",
                    },
                },
            ),
        ]
    )

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.artifact_id == "run-artifacts:reports/final.md"
    assert artifact.run_id == "run-artifacts"
    assert artifact.source_run_id == "run-artifacts"
    assert artifact.source_tool == "artifact.write"
    assert artifact.source_runnable_id == "agent-writer"
    assert artifact.source_runnable_name == "Writer"
    assert artifact.workflow_id == "workflow-1"
    assert artifact.workflow_run_id == "workflow-run-1"
    assert artifact.workflow_node_id == "report"
    assert artifact.workflow_node_label == "Report"
    assert artifact.group_id == "group-1"
    assert artifact.group_run_id == "group-run-1"
    assert artifact.kind == "markdown"
    assert artifact.path == "reports/final.md"
    assert artifact.size_bytes == 42
    assert artifact.preview_text == "done"


def test_workflow_node_artifact_payload_defaults_without_nested_artifact() -> None:
    event = PublicRunEvent(
        event_id="evt-workflow-artifact",
        run_id="workflow-run-1",
        sequence=1,
        event_type="workflow.node.artifact",
        detail="reports/summary.md",
        payload={
            "workflow_id": "workflow-1",
            "workflow_node_id": "summary",
            "workflow_node_label": "Summary",
            "size_bytes": 9,
            "content_type": "text/markdown",
        },
        created_at="2026-06-17T00:00:01Z",
    )

    payload = artifact_payload_from_event(event)
    artifacts = artifact_snapshots_from_events([event])

    assert payload["path"] == "reports/summary.md"
    assert payload["kind"] == "workflow_artifact"
    assert payload["title"] == "Summary"
    assert payload["workflow_run_id"] == "workflow-run-1"
    assert len(artifacts) == 1
    assert artifacts[0].path == "reports/summary.md"
    assert artifacts[0].title == "Summary"
    assert artifacts[0].mime_type == "text/markdown"
    assert artifacts[0].size_bytes == 9


def test_tool_completed_event_artifact_result_projects_to_public_artifact() -> None:
    event = PublicRunEvent(
        event_id="evt-screen-artifact",
        run_id="run-screen",
        sequence=4,
        event_type="tool.completed",
        detail="screen.capture",
        payload={
            "tool": "screen.capture",
            "status": "completed",
            "result": {
                "ok": True,
                "artifact": {
                    "path": "screenshots/current-screen.png",
                    "kind": "image",
                    "mime_type": "image/png",
                    "size_bytes": 321,
                },
            },
        },
        created_at="2026-06-22T00:00:00Z",
    )

    payload = artifact_payload_from_event(event)
    artifacts = artifact_snapshots_from_events([event])

    assert payload["path"] == "screenshots/current-screen.png"
    assert payload["source_tool"] == "screen.capture"
    assert payload["title"] == "screenshots/current-screen.png"
    assert len(artifacts) == 1
    assert artifacts[0].path == "screenshots/current-screen.png"
    assert artifacts[0].kind == "image"
    assert artifacts[0].mime_type == "image/png"
    assert artifacts[0].size_bytes == 321
    assert artifacts[0].source_tool == "screen.capture"


def test_tool_completed_event_artifacts_result_projects_all_public_artifacts() -> None:
    event = PublicRunEvent(
        event_id="evt-data-artifacts",
        run_id="run-data",
        sequence=5,
        event_type="tool.completed",
        detail="data.analyze",
        payload={
            "tool": "data.analyze",
            "status": "completed",
            "result": {
                "ok": True,
                "artifact": {
                    "path": "analysis-report.md",
                    "kind": "markdown",
                    "mime_type": "text/markdown",
                    "size_bytes": 111,
                },
                "artifacts": [
                    {
                        "path": "analysis-report.md",
                        "kind": "markdown",
                        "mime_type": "text/markdown",
                        "size_bytes": 111,
                    },
                    {
                        "path": "analysis-summary.csv",
                        "kind": "csv",
                        "mime_type": "text/csv",
                        "size_bytes": 222,
                    },
                    {
                        "path": "analysis-chart.png",
                        "kind": "image",
                        "mime_type": "image/png",
                        "size_bytes": 333,
                    },
                ],
            },
        },
        created_at="2026-06-22T00:00:01Z",
    )

    payload = artifact_payload_from_event(event)
    artifacts = artifact_snapshots_from_events([event])

    assert payload["path"] == "analysis-report.md"
    assert [artifact.path for artifact in artifacts] == [
        "analysis-report.md",
        "analysis-summary.csv",
        "analysis-chart.png",
    ]
    assert [artifact.source_tool for artifact in artifacts] == [
        "data.analyze",
        "data.analyze",
        "data.analyze",
    ]
    assert artifacts[1].kind == "csv"
    assert artifacts[1].mime_type == "text/csv"
    assert artifacts[2].kind == "image"
    assert artifacts[2].mime_type == "image/png"


def test_group_artifact_events_default_titles_and_group_context() -> None:
    artifacts = artifact_snapshots_from_events(
        [
            PublicRunEvent(
                event_id="evt-group-artifact",
                run_id="group-run-1",
                sequence=1,
                event_type="group.shared_artifact.created",
                payload={
                    "artifact": {"path": "team-summary.md", "size_bytes": 33},
                    "group_id": "group-1",
                    "member_agent_id": "agent-1",
                    "member_agent_name": "Planner",
                },
                created_at="2026-06-17T00:00:02Z",
            )
        ]
    )

    assert len(artifacts) == 1
    artifact = artifacts[0]
    assert artifact.kind == "group_artifact"
    assert artifact.title == "Planner / team-summary.md"
    assert artifact.path == "team-summary.md"
    assert artifact.group_id == "group-1"
    assert artifact.group_run_id == "group-run-1"
    assert artifact.source_runnable_id == "agent-1"
    assert artifact.source_runnable_name == "Planner"
    assert artifact.size_bytes == 33


def test_merge_artifact_snapshot_lists_keeps_order_and_fills_missing_fields() -> None:
    direct = artifact_snapshot_from_payload(
        {
            "artifact_id": "artifact-1",
            "kind": "markdown",
            "path": "reports/final.md",
        },
        run_id="run-1",
    )
    replay = artifact_snapshot_from_payload(
        {
            "artifact_id": "artifact-1",
            "kind": "markdown",
            "path": "reports/final.md",
            "preview_text": "done",
            "size_bytes": 42,
            "source_tool": "artifact.write",
        },
        run_id="run-1",
    )

    merged = merge_artifact_snapshot_lists([direct], [replay])

    assert len(merged) == 1
    assert merged[0].artifact_id == "artifact-1"
    assert merged[0].path == "reports/final.md"
    assert merged[0].preview_text == "done"
    assert merged[0].size_bytes == 42
    assert merged[0].source_tool == "artifact.write"
