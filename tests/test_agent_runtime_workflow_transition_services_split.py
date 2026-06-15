"""Tests for Workflow transition service setup split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_projections import ApprovalResumeProjectionCoordinator
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
    )

    assert isinstance(bundle, RuntimeWorkflowTransitionServiceBundle)
    assert isinstance(bundle.workflow_parent_resume, WorkflowParentResumeCoordinator)
    assert isinstance(bundle.approval_resume_projection, ApprovalResumeProjectionCoordinator)
    assert isinstance(bundle.run_transition_projection, RunTransitionProjectionCoordinator)
    assert bundle.workflow_parent_resume._workflow_run_is_group_root is workflow_run_is_group_root
    assert bundle.workflow_parent_resume._timeline is timeline_factory
    assert bundle.approval_resume_projection._update_agent_run_group_if_root is update_agent_run_group_if_root
    assert bundle.run_transition_projection._workflow_run_is_group_root is workflow_run_is_group_root


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
        assert callable(service.approval_resume_projection._mark_parent_workflows_child_running)
        assert callable(service.run_transition_projection._resume_parent_workflows_after_child_update)
        assert callable(service.run_transition_projection._get_run)
    finally:
        service.close()
