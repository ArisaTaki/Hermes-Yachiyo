"""Tests for Workflow transition service setup split out of the legacy runtime."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_projections import ApprovalResumeProjectionCoordinator
from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext
from apps.shell.agent.runtime.workflow_parent_resume import WorkflowParentResumeCoordinator
from apps.shell.agent.runtime.workflow_resume import RunTransitionProjectionCoordinator
from apps.shell.agent.runtime.workflow_services import (
    RuntimeWorkflowTransitionServiceBundle,
    build_runtime_workflow_transition_services,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_workflow_transition_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeWorkflowTransitionServiceBundle is RuntimeWorkflowTransitionServiceBundle


def test_build_runtime_workflow_transition_services_wires_parent_resume_and_projections() -> None:
    def workflow_run_is_group_root(_run: dict[str, Any]) -> bool:
        return True

    def update_agent_run_group_if_root(_run: dict[str, Any]) -> None:
        return None

    def timeline_factory(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {"event": event, "detail": detail, **extra}

    def transaction_scope():
        return SimpleNamespace(
            __enter__=lambda self: self,
            __exit__=lambda self, *_args: None,
        )

    bundle = build_runtime_workflow_transition_services(
        parent_runs_waiting_for_child=lambda _child_run: [],
        workflow_run_is_group_root=workflow_run_is_group_root,
        workflow_child_node_context=lambda _timeline, _child_run: ("Child", {}),
        merge_workflow_child_run_outcome=lambda *_args, **_kwargs: None,
        workflow_for_run_resume=lambda workflow_run: workflow_run,
        workflow_resume_start_index=lambda *_args, **_kwargs: 0,
        workflow_next_node_id=lambda *_args, **_kwargs: "",
        continue_workflow_run=lambda run, _workflow, **_kwargs: run,
        timeline_factory=timeline_factory,
        append_run_event=lambda _run_id, _event_type, _payload: None,
        update_run=lambda run_id, **kwargs: {"run_id": run_id, **kwargs},
        update_run_group=lambda run_group_id, **kwargs: {"run_group_id": run_group_id, **kwargs},
        update_agent_run_group_if_root=update_agent_run_group_if_root,
        mark_parent_workflows_child_running=lambda _run: None,
        resume_parent_workflows_after_child_update=lambda _run: None,
        get_run=lambda run_id: {"run_id": run_id},
        get_run_group=lambda run_group_id: {
            "run_group_id": run_group_id,
            "status": "running",
            "updated_at": "group-version-1",
        },
        transaction_scope=transaction_scope,
    )

    assert isinstance(bundle, RuntimeWorkflowTransitionServiceBundle)
    assert isinstance(bundle.workflow_parent_resume, WorkflowParentResumeCoordinator)
    assert isinstance(bundle.approval_resume_projection, ApprovalResumeProjectionCoordinator)
    assert isinstance(bundle.run_transition_projection, RunTransitionProjectionCoordinator)
    assert bundle.workflow_parent_resume._workflow_run_is_group_root is workflow_run_is_group_root
    assert bundle.workflow_parent_resume._timeline is timeline_factory
    assert bundle.workflow_parent_resume._transaction_scope is transaction_scope
    assert bundle.approval_resume_projection._update_agent_run_group_if_root is update_agent_run_group_if_root
    assert bundle.run_transition_projection._workflow_run_is_group_root is workflow_run_is_group_root
    assert callable(bundle.run_transition_projection._get_run_group)


def test_cancelled_root_group_projection_rejects_different_terminal_winner() -> None:
    group = {
        "run_group_id": "workflow-group-race",
        "status": "running",
        "updated_at": "group-version-1",
    }
    updates: list[dict[str, Any]] = []

    def update_run_group(run_group_id: str, **fields: Any) -> None:
        updates.append({"run_group_id": run_group_id, **fields})
        group.update(
            status="completed",
            summary="completed by winner",
            updated_at="group-version-2",
        )
        return None

    coordinator = RunTransitionProjectionCoordinator(
        update_agent_run_group_if_root=lambda _run: None,
        resume_parent_workflows_after_child_update=lambda _run: None,
        workflow_run_is_group_root=lambda _run: True,
        update_run_group=update_run_group,
        get_run=lambda _run_id: pytest.fail(
            "group CAS loser must not project a stale Run"
        ),
        get_run_group=lambda _run_group_id: dict(group),
    )

    with pytest.raises(
        AgentRuntimeError,
        match="run_group_terminal_outcome_conflict",
    ):
        coordinator.project_cancelled_workflow_group_if_root(
            {
                "run_id": "workflow-root-race",
                "run_group_id": group["run_group_id"],
            },
            {
                "run_id": "workflow-root-race",
                "status": "cancelled",
                "result": "Workflow cancelled",
            },
        )

    assert updates == [
        {
            "run_group_id": "workflow-group-race",
            "status": "cancelled",
            "summary": "Workflow cancelled",
            "expected_status": "running",
            "expected_updated_at": "group-version-1",
        }
    ]
    assert group["status"] == "completed"
    assert group["summary"] == "completed by winner"


def test_cancelled_root_group_projection_accepts_same_terminal_cas_winner() -> None:
    group = {
        "run_group_id": "workflow-group-same-winner",
        "status": "running",
        "summary": "",
        "updated_at": "group-version-1",
    }
    persisted_run = {
        "run_id": "workflow-root-same-winner",
        "kind": "workflow_run",
        "status": "cancelled",
        "result": "Workflow cancelled",
    }
    updates: list[dict[str, Any]] = []

    def update_run_group(run_group_id: str, **fields: Any) -> None:
        updates.append({"run_group_id": run_group_id, **fields})
        group.update(
            status="canceled",
            summary="Workflow cancelled",
            updated_at="group-version-2",
        )
        return None

    coordinator = RunTransitionProjectionCoordinator(
        update_agent_run_group_if_root=lambda _run: None,
        resume_parent_workflows_after_child_update=lambda _run: None,
        workflow_run_is_group_root=lambda _run: True,
        update_run_group=update_run_group,
        get_run=lambda _run_id: dict(persisted_run),
        get_run_group=lambda _run_group_id: dict(group),
    )

    result = coordinator.project_cancelled_workflow_group_if_root(
        {
            "run_id": persisted_run["run_id"],
            "run_group_id": group["run_group_id"],
        },
        persisted_run,
    )

    assert result == persisted_run
    assert updates == [
        {
            "run_group_id": group["run_group_id"],
            "status": "cancelled",
            "summary": "Workflow cancelled",
            "expected_status": "running",
            "expected_updated_at": "group-version-1",
        }
    ]


def test_native_runtime_installs_workflow_transition_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.workflow_parent_resume, WorkflowParentResumeCoordinator)
        assert isinstance(service.approval_resume_projection, ApprovalResumeProjectionCoordinator)
        assert isinstance(service.run_transition_projection, RunTransitionProjectionCoordinator)
        assert callable(service.workflow_parent_resume._continue_workflow_run)
        assert callable(service.workflow_parent_resume._workflow_next_node_id)
        assert callable(service.workflow_parent_resume._transaction_scope)
        assert callable(service.approval_resume_projection._mark_parent_workflows_child_running)
        assert callable(service.run_transition_projection._resume_parent_workflows_after_child_update)
        assert callable(service.run_transition_projection._get_run)
    finally:
        service.close()


def test_legacy_resume_projection_without_approval_id_cannot_resurrect_terminal_run() -> None:
    current = {
        "run_id": "legacy-resume-race",
        "status": "running",
        "result": "approved tool is running",
        "pending_approval": {},
        "timeline": [],
        "artifacts": [],
        "updated_at": "2026-07-11T10:00:00+00:00",
    }
    events: list[tuple[str, str, dict[str, Any]]] = []

    def update_run(_run_id: str, **fields: Any):
        assert fields["expected_status"] == "running"
        assert fields["expected_updated_at"] == "2026-07-11T10:00:00+00:00"
        assert fields["expected_pending_approval_absent"] is True
        current.update(
            status="cancelled",
            result="cancelled by user",
            updated_at="2026-07-11T10:00:01+00:00",
        )
        return None

    coordinator = ApprovalResumeProjectionCoordinator(
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        update_run=update_run,
        update_agent_run_group_if_root=lambda _run: None,
        mark_parent_workflows_child_running=lambda _run: None,
        get_run=lambda _run_id: dict(current),
    )
    context = ToolApprovalResumeContext(
        run_id="legacy-resume-race",
        timeline=[],
        artifacts=[],
        broker=SimpleNamespace(),
        allowed_tools=["desktop.open_app"],
        budget=SimpleNamespace(),
        messages=[],
        tool_request={"tool": "desktop.open_app", "input": {"app": "Notes"}},
        tool_name="desktop.open_app",
        input_preview={"app": "Notes"},
        remaining_requests=[],
        next_iteration=1,
        approval_id="",
    )

    result = coordinator.project_required(
        context,
        {
            "approval_id": "approval-next",
            "tool": "desktop.verify",
            "input_preview": {"app": "Notes"},
        },
    )

    assert result["status"] == "cancelled"
    assert result["result"] == "cancelled by user"
    assert events == []
