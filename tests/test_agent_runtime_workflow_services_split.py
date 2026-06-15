"""Tests for Workflow planning service setup split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_readiness import RuntimeRunReadinessValidator
from apps.shell.agent.runtime.workflow_path import WorkflowDefinitionValidator, WorkflowPathPlanner
from apps.shell.agent.runtime.workflow_resume import WorkflowParentRunLocator, WorkflowResumePlanner
from apps.shell.agent.runtime.workflow_runs import RuntimeWorkflowRunStarter
from apps.shell.agent.runtime.workflow_services import (
    RuntimeWorkflowPlanningServiceBundle,
    build_runtime_workflow_planning_services,
)
from apps.shell.agent.runtime.workflow_start import WorkflowRunStartProjector
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_workflow_planning_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeWorkflowPlanningServiceBundle is RuntimeWorkflowPlanningServiceBundle


def test_build_runtime_workflow_planning_services_wires_planners_and_starters() -> None:
    def node_kind(node: dict[str, Any]) -> str:
        return str(node.get("type") or "")

    def get_run_group(run_group_id: str) -> dict[str, Any]:
        return {"run_group_id": run_group_id}

    def get_run(run_id: str) -> dict[str, Any]:
        return {"run_id": run_id}

    def get_workflow(workflow_id: str) -> dict[str, Any]:
        return {"workflow_id": workflow_id, "nodes": [], "edges": []}

    def workflow_path(workflow: dict[str, Any]) -> list[dict[str, Any]]:
        return list(workflow.get("nodes") or [])

    def timeline_factory(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {"event": event, "detail": detail, **extra}

    bundle = build_runtime_workflow_planning_services(
        get_run_group=get_run_group,
        get_run=get_run,
        node_kind=node_kind,
        node_types={"start", "agent"},
        get_agent_private=lambda agent_id: {"agent_id": agent_id, "enabled": True},
        get_workflow=get_workflow,
        load_agent_skills=lambda _skill_ids: [],
        agent_model_config_private=lambda _agent: {},
        default_agent_ids={"builtin:yachiyo-main"},
        timeline_factory=timeline_factory,
        workflow_path_snapshot=workflow_path,
        workflow_runtime_snapshot=lambda workflow: dict(workflow),
        insert_run_group=lambda **kwargs: {"run_group_id": "group-1", **kwargs},
        insert_run=lambda **kwargs: {"run_id": "run-1", **kwargs},
        run_by_client_request_id=lambda _client_request_id: None,
        client_request_id_from_payload=lambda payload: str(payload.get("client_request_id") or ""),
        workflow_path=workflow_path,
    )

    assert isinstance(bundle, RuntimeWorkflowPlanningServiceBundle)
    assert isinstance(bundle.workflow_parent_locator, WorkflowParentRunLocator)
    assert isinstance(bundle.workflow_path_planner, WorkflowPathPlanner)
    assert isinstance(bundle.workflow_definition_validator, WorkflowDefinitionValidator)
    assert isinstance(bundle.run_readiness_validator, RuntimeRunReadinessValidator)
    assert isinstance(bundle.workflow_run_start_projector, WorkflowRunStartProjector)
    assert isinstance(bundle.workflow_run_starter, RuntimeWorkflowRunStarter)
    assert isinstance(bundle.workflow_resume_planner, WorkflowResumePlanner)
    assert bundle.workflow_parent_locator._get_run_group is get_run_group
    assert bundle.workflow_path_planner._node_kind is node_kind
    assert bundle.workflow_definition_validator._node_kind is node_kind
    assert bundle.run_readiness_validator._node_kind is node_kind
    assert bundle.run_readiness_validator._default_agent_ids == {"builtin:yachiyo-main"}
    assert bundle.workflow_run_start_projector._timeline is timeline_factory
    assert bundle.workflow_run_starter._get_run_group is get_run_group
    assert bundle.workflow_resume_planner._workflow_path is workflow_path
    assert bundle.workflow_resume_planner._nodes_by_id is WorkflowPathPlanner.nodes_by_id
    assert bundle.workflow_resume_planner._next_node_id.__self__ is bundle.workflow_path_planner


def test_native_runtime_installs_workflow_planning_services_under_legacy_attribute_names(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.workflow_parent_locator, WorkflowParentRunLocator)
        assert isinstance(service.workflow_path_planner, WorkflowPathPlanner)
        assert isinstance(service.workflow_definition_validator, WorkflowDefinitionValidator)
        assert isinstance(service.run_readiness_validator, RuntimeRunReadinessValidator)
        assert isinstance(service.workflow_run_start_projector, WorkflowRunStartProjector)
        assert isinstance(service.workflow_run_starter, RuntimeWorkflowRunStarter)
        assert isinstance(service.workflow_resume_planner, WorkflowResumePlanner)
        assert service.workflow_parent_locator._get_run_group.__self__ is service
        assert service.workflow_path_planner._node_kind is service._node_kind
        assert service.run_readiness_validator._get_workflow.__self__ is service
        assert service.workflow_run_starter._insert_run.__self__ is service
        assert service.workflow_resume_planner._workflow_path.__self__ is service
        assert service.workflow_resume_planner._nodes_by_id is WorkflowPathPlanner.nodes_by_id
        assert service.workflow_resume_planner._next_node_id.__self__ is service.workflow_path_planner
    finally:
        service.close()
