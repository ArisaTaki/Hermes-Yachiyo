"""Tests for workflow node handoffs split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowSubworkflowNodeExecution,
)


def test_workflow_node_handoffs_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.WorkflowAgentNodeHandoff is WorkflowAgentNodeHandoff
    assert agent_runtime.WorkflowAgentNodeExecution is WorkflowAgentNodeExecution
    assert agent_runtime.WorkflowSubworkflowNodeExecution is WorkflowSubworkflowNodeExecution
    assert agent_runtime.WorkflowArtifactNodeWrite is WorkflowArtifactNodeWrite


def test_workflow_artifact_node_write_accepts_prepared_artifact() -> None:
    write = WorkflowArtifactNodeWrite.from_artifact(
        {
            "id": "report",
            "type": "artifact",
            "data": {"artifact_path": "reports/final.md"},
        },
        {"ok": True, "path": "reports/final.md", "bytes": 12},
        label="Final Report",
        kind="artifact",
        node_info_extra={"workflow_parent_node_id": "fanout"},
    )

    assert WorkflowArtifactNodeWrite.configured_path(
        {"data": {"artifactPath": "reports/alt.md"}}
    ) == "reports/alt.md"
    assert write.artifact_record() == {
        "kind": "workflow_artifact",
        "workflow_node_id": "report",
        "workflow_node_label": "Final Report",
        "ok": True,
        "path": "reports/final.md",
        "bytes": 12,
    }
    assert write.event_payload() == {
        "workflow_node_id": "report",
        "workflow_node_kind": "artifact",
        "workflow_node_label": "Final Report",
        "status": "completed",
        "artifact": {"ok": True, "path": "reports/final.md", "bytes": 12},
        "workflow_parent_node_id": "fanout",
    }
