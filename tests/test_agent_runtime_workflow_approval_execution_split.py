"""Tests for Workflow approval execution split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.workflow_approval_execution import (
    RuntimeWorkflowApprovalExecutionService,
)
from apps.shell.agent.runtime.workflow_approvals import WorkflowApprovalResumeContext
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_workflow_approval_execution_remains_exported_from_legacy_module() -> None:
    assert (
        agent_runtime.RuntimeWorkflowApprovalExecutionService
        is RuntimeWorkflowApprovalExecutionService
    )


def test_native_runtime_installs_split_workflow_approval_execution_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(
            service.workflow_approval_execution,
            RuntimeWorkflowApprovalExecutionService,
        )
        assert (
            service.workflow_approval_execution._workflow_approval_resume
            is service.workflow_approval_resume
        )
        assert callable(service.workflow_approval_execution._pending_approval_private)
        assert callable(service.workflow_approval_execution._workflow_for_run_resume)
        assert callable(service.workflow_approval_execution._workflow_run_is_group_root)
    finally:
        service.close()


def test_runtime_workflow_approval_execution_builds_resume_context_and_handoffs() -> None:
    pending_calls: list[str] = []
    workflow_calls: list[dict[str, Any]] = []
    root_calls: list[dict[str, Any]] = []
    resume = FakeWorkflowApprovalResume()
    run = {
        "run_id": "workflow-run-1",
        "status": "approval_required",
        "kind": "workflow_run",
        "user_goal": "ship the workflow",
        "timeline": [{"event": "workflow.started"}],
        "artifacts": [{"path": "summary.md"}],
    }
    pending = {
        "tool": "workflow.approval",
        "workflow_node_id": "approval-1",
        "workflow_node_label": "Review",
        "workflow_node_approval_criteria": "human sign-off",
        "workflow_context": "draft result",
        "workflow_next_index": 3,
        "workflow_next_node_id": "agent-2",
        "input_preview": {"checkpoint": "Review"},
    }
    workflow = {
        "workflow_id": "workflow-1",
        "nodes": [{"id": "agent-2", "type": "agent"}],
    }
    service = RuntimeWorkflowApprovalExecutionService(
        pending_approval_private=lambda run_id: _record_pending_call(
            pending_calls,
            run_id,
            pending,
        ),
        workflow_for_run_resume=lambda current_run: _record_run_call(
            workflow_calls,
            current_run,
            workflow,
        ),
        workflow_run_is_group_root=lambda current_run: _record_run_call(
            root_calls,
            current_run,
            True,
        ),
        workflow_approval_resume=resume,  # type: ignore[arg-type]
    )

    result = service.approve_workflow_run(run)

    assert result == {"run_id": "workflow-run-1", "status": "completed"}
    assert pending_calls == ["workflow-run-1"]
    assert workflow_calls == [run]
    assert root_calls == [run]
    assert resume.calls[0]["run"] is run
    assert resume.calls[0]["pending"] is pending
    context = resume.calls[0]["context"]
    assert isinstance(context, WorkflowApprovalResumeContext)
    assert context.workflow == workflow
    assert context.root_group is True
    assert context.start_index == 3
    assert context.start_node_id == "agent-2"
    assert context.approval.workflow_node_id == "approval-1"
    assert context.approval.label == "Review"
    assert context.result_context == "draft result"
    assert context.timeline == [{"event": "workflow.started"}]
    assert context.artifacts == [{"path": "summary.md"}]


def _record_pending_call(
    calls: list[str],
    run_id: str,
    pending: dict[str, Any],
) -> dict[str, Any]:
    calls.append(run_id)
    return pending


def _record_run_call(
    calls: list[dict[str, Any]],
    run: dict[str, Any],
    result: Any,
) -> Any:
    calls.append(run)
    return result


class FakeWorkflowApprovalResume:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def resume_after_approval(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        context: WorkflowApprovalResumeContext,
    ) -> dict[str, Any]:
        self.calls.append({"run": run, "pending": pending, "context": context})
        return {"run_id": run["run_id"], "status": "completed"}
