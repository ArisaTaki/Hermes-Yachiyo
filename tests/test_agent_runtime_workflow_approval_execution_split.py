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


def test_workflow_approval_authority_projects_group_only_for_persisted_owner(
    tmp_path,
) -> None:
    runtime = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime-owner.db",
        workspace_dir=tmp_path / "runtime-owner",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        group = runtime._insert_run_group(title="Nested workflow", source="workflow")
        parent = runtime._insert_run(
            kind="workflow_run",
            runnable_id="workflow-parent",
            user_goal="own the group",
            run_group_id=group["run_group_id"],
        )
        child = runtime._insert_run(
            kind="workflow_run",
            runnable_id="workflow-child",
            user_goal="share the group",
            run_group_id=group["run_group_id"],
        )
        pending_by_run: dict[str, dict[str, Any]] = {}
        for run, label in ((parent, "Parent gate"), (child, "Child gate")):
            pending = {
                "approval_id": f"approval-{run['run_id']}",
                "tool": "workflow.approval",
                "workflow_node_id": "gate",
                "workflow_node_label": label,
                "workflow_node_approval_criteria": "approve",
                "workflow_context": "ready",
                "workflow_next_index": 1,
                "input_preview": {"checkpoint": label},
            }
            pending_by_run[run["run_id"]] = pending
            runtime._update_run(
                run["run_id"],
                status="approval_required",
                result=f"waiting: {label}",
                pending_approval=pending,
            )

        class OwnerAwareResume:
            def __init__(self) -> None:
                self.root_flags: list[tuple[str, bool]] = []

            def resume_after_approval(
                self,
                run: dict[str, Any],
                _pending: dict[str, Any],
                context: WorkflowApprovalResumeContext,
                *,
                expected_approval_id: str,
            ) -> dict[str, Any]:
                assert expected_approval_id == pending_by_run[run["run_id"]]["approval_id"]
                self.root_flags.append((run["run_id"], context.root_group))
                completed = runtime._update_run(
                    run["run_id"],
                    status="completed",
                    result=f"completed: {run['run_id']}",
                    pending_approval=None,
                )
                assert completed is not None
                if context.root_group:
                    runtime._update_run_group(
                        group["run_group_id"],
                        status="completed",
                        summary=str(completed["result"]),
                    )
                return completed

        resume = OwnerAwareResume()
        approval_execution = RuntimeWorkflowApprovalExecutionService(
            pending_approval_private=lambda run_id: pending_by_run[run_id],
            workflow_for_run_resume=lambda run: {
                "workflow_id": run["runnable_id"],
                "nodes": [],
                "edges": [],
            },
            workflow_run_is_group_root=runtime._workflow_run_is_group_root,
            workflow_approval_resume=resume,  # type: ignore[arg-type]
        )

        child_result = approval_execution.approve_workflow_run(
            runtime.get_run(child["run_id"]),
            expected_approval_id=pending_by_run[child["run_id"]]["approval_id"],
        )

        assert child_result["status"] == "completed"
        assert runtime.get_run_group(group["run_group_id"])["status"] == "running"

        parent_result = approval_execution.approve_workflow_run(
            runtime.get_run(parent["run_id"]),
            expected_approval_id=pending_by_run[parent["run_id"]]["approval_id"],
        )

        assert parent_result["status"] == "completed"
        assert runtime.get_run_group(group["run_group_id"])["status"] == "completed"
        assert resume.root_flags == [
            (child["run_id"], False),
            (parent["run_id"], True),
        ]
    finally:
        runtime.close()


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
        "approval_id": "approval-workflow",
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

    result = service.approve_workflow_run(
        run,
        expected_approval_id="approval-workflow",
    )

    assert result == {"run_id": "workflow-run-1", "status": "completed"}
    assert pending_calls == ["workflow-run-1"]
    assert workflow_calls == [run]
    assert root_calls == [run]
    assert resume.calls[0]["run"] is run
    assert resume.calls[0]["pending"] is pending
    assert resume.calls[0]["expected_approval_id"] == "approval-workflow"
    context = resume.calls[0]["context"]
    assert isinstance(context, WorkflowApprovalResumeContext)
    assert context.workflow == workflow
    assert context.root_group is True
    assert context.start_index == 3
    assert context.start_node_id == "agent-2"
    assert context.expected_approval_id == "approval-workflow"
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
        *,
        expected_approval_id: str,
    ) -> dict[str, Any]:
        self.calls.append({
            "run": run,
            "pending": pending,
            "context": context,
            "expected_approval_id": expected_approval_id,
        })
        return {"run_id": run["run_id"], "status": "completed"}
