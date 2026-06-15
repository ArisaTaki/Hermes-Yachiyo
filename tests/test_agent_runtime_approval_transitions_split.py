"""Tests for approval reject/timeout transition service split."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_transitions import RuntimeApprovalTransitionService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeApprovals:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def reject_tool_run(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("reject_tool_run", {"run_id": run_id, **kwargs}))
        return {"run_id": run_id, "kind": "agent_run", "status": "cancelled"}

    def timeout_tool_run(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("timeout_tool_run", {"run_id": run_id, **kwargs}))
        return {"run_id": run_id, "kind": "agent_run", "status": "cancelled"}

    def reject_workflow_node(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("reject_workflow_node", {"run_id": run_id, **kwargs}))
        return {"run_id": run_id, "kind": "workflow_run", "status": "cancelled"}

    def timeout_workflow_node(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(("timeout_workflow_node", {"run_id": run_id, **kwargs}))
        return {"run_id": run_id, "kind": "workflow_run", "status": "cancelled"}


def _tool_pending() -> dict[str, Any]:
    return {
        "tool": "terminal.run",
        "tool_request": {"tool": "terminal.run", "input": {"command": "printf ok"}},
    }


def _workflow_pending() -> dict[str, Any]:
    return {
        "tool": "workflow.approval",
        "workflow_node_id": "approval-1",
        "workflow_node_label": "Review",
        "workflow_node_approval_criteria": "Check output",
        "input_preview": {"checkpoint": "Review"},
    }


def test_approval_transition_service_rejects_tool_approval() -> None:
    approvals = FakeApprovals()
    projected: list[dict[str, Any]] = []
    run = {
        "run_id": "run-tool",
        "kind": "agent_run",
        "status": "approval_required",
        "timeline": [{"event": "agent.tool.approval_required"}],
    }
    service = RuntimeApprovalTransitionService(
        get_run=lambda _run_id: run,
        pending_approval_private=lambda _run_id: _tool_pending(),
        approvals=approvals,
        project_child_run_transition=lambda result: projected.append(result)
        or {"projected_child": result},
        project_cancelled_workflow_group_if_root=lambda _run, result: {"projected_workflow": result},
        cancel_run=lambda run_id: {"run_id": run_id, "status": "cancelled"},
    )

    result = service.reject("run-tool", "not now")

    assert result == {
        "projected_child": {"run_id": "run-tool", "kind": "agent_run", "status": "cancelled"}
    }
    assert approvals.calls == [
        (
            "reject_tool_run",
            {
                "run_id": "run-tool",
                "timeline": [{"event": "agent.tool.approval_required"}],
                "reason": "not now",
                "tool_name": "terminal.run",
                "input_preview": {"command": "printf ok"},
            },
        )
    ]
    assert projected == [{"run_id": "run-tool", "kind": "agent_run", "status": "cancelled"}]


def test_approval_transition_service_times_out_workflow_approval() -> None:
    approvals = FakeApprovals()
    run = {
        "run_id": "run-workflow",
        "kind": "workflow_run",
        "status": "approval_required",
        "timeline": [{"event": "workflow.approval.required"}],
    }
    service = RuntimeApprovalTransitionService(
        get_run=lambda _run_id: run,
        pending_approval_private=lambda _run_id: _workflow_pending(),
        approvals=approvals,
        project_child_run_transition=lambda result: {"projected_child": result},
        project_cancelled_workflow_group_if_root=lambda run_arg, result: {
            "root": run_arg["run_id"],
            "projected_workflow": result,
        },
        cancel_run=lambda run_id: {"run_id": run_id, "status": "cancelled"},
    )

    result = service.timeout("run-workflow")

    assert result == {
        "root": "run-workflow",
        "projected_workflow": {"run_id": "run-workflow", "kind": "workflow_run", "status": "cancelled"},
    }
    assert approvals.calls == [
        (
            "timeout_workflow_node",
            {
                "run_id": "run-workflow",
                "timeline": [{"event": "workflow.approval.required"}],
                "reason": "approval_wait_timeout",
                "workflow_node_id": "approval-1",
                "label": "Review",
                "criteria": "Check output",
                "input_preview": {"checkpoint": "Review"},
            },
        )
    ]


def test_approval_transition_service_returns_non_waiting_run() -> None:
    run = {"run_id": "run-done", "kind": "agent_run", "status": "completed"}
    service = RuntimeApprovalTransitionService(
        get_run=lambda _run_id: run,
        pending_approval_private=lambda _run_id: None,
        approvals=FakeApprovals(),
        project_child_run_transition=lambda result: result,
        project_cancelled_workflow_group_if_root=lambda _run, result: result,
        cancel_run=lambda run_id: {"run_id": run_id, "status": "cancelled"},
    )

    assert service.reject("run-done") is run
    assert service.timeout("run-done") is run


def test_native_runtime_installs_approval_transition_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeApprovalTransitionService is RuntimeApprovalTransitionService
        assert isinstance(service.approval_transitions, RuntimeApprovalTransitionService)
    finally:
        service.close()
