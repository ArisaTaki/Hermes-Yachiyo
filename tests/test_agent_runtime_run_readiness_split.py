"""Tests for run readiness validation split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.run_readiness import RuntimeRunReadinessValidator


def test_run_readiness_validator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunReadinessValidator is RuntimeRunReadinessValidator


def test_run_readiness_validator_projects_workflow_agent_node() -> None:
    validator = _validator(
        agents={
            "agent-1": {
                "agent_id": "agent-1",
                "name": "Research",
                "enabled": True,
            }
        },
    )

    agent = validator.workflow_agent_for_node(
        {"id": "research", "type": "agent", "data": {"agent_id": "agent-1"}}
    )

    assert agent["name"] == "Research"
    with pytest.raises(AgentRuntimeError, match="没有选择 Agent"):
        validator.workflow_agent_for_node({"id": "empty", "type": "agent", "data": {}})


def test_run_readiness_validator_rejects_self_referencing_subworkflow() -> None:
    validator = _validator(
        workflows={
            "workflow-1": {
                "workflow_id": "workflow-1",
                "name": "Parent",
                "enabled": True,
            }
        },
    )

    with pytest.raises(AgentRuntimeError, match="不能引用当前 Workflow"):
        validator.validate_workflow_subworkflow_nodes(
            [
                {
                    "id": "child",
                    "type": "workflow",
                    "data": {"workflow_id": "workflow-1", "label": "Child Flow"},
                }
            ],
            parent_workflow_id="workflow-1",
        )


def test_run_readiness_validator_checks_agent_model_configuration() -> None:
    validator = _validator()

    with pytest.raises(AgentRuntimeError, match="缺少可运行的 Chat Profile"):
        validator.validate_agent_run_readiness(
            {
                "agent_id": "custom-agent",
                "name": "Custom Agent",
                "enabled": True,
                "model_mode": "profile",
                "skill_ids": [],
            },
            require_model_config=True,
        )
    with pytest.raises(AgentRuntimeError, match="缺少 API Key"):
        validator.validate_agent_run_readiness(
            {
                "agent_id": "api-agent",
                "name": "API Agent",
                "enabled": True,
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                },
                "skill_ids": [],
            },
            require_model_config=True,
        )


def _validator(
    *,
    agents: dict[str, dict[str, object]] | None = None,
    workflows: dict[str, dict[str, object]] | None = None,
) -> RuntimeRunReadinessValidator:
    agents = agents or {}
    workflows = workflows or {}

    def get_agent_private(agent_id: str) -> dict[str, object]:
        if agent_id not in agents:
            raise KeyError(agent_id)
        return agents[agent_id]

    def get_workflow(workflow_id: str) -> dict[str, object]:
        if workflow_id not in workflows:
            raise KeyError(workflow_id)
        return workflows[workflow_id]

    def load_agent_skills(_skill_ids: list[str]) -> list[dict[str, object]]:
        return []

    def agent_model_config_private(agent: dict[str, object]) -> dict[str, object]:
        if str(agent.get("model_mode") or "") == "custom_api":
            return dict(agent.get("model_config") or {})
        profile_id = str(agent.get("model_profile_id") or "")
        if not profile_id:
            raise AgentRuntimeError("Chat Profile 不存在")
        return {"profile_id": profile_id}

    return RuntimeRunReadinessValidator(
        node_kind=_node_kind,
        get_agent_private=get_agent_private,
        get_workflow=get_workflow,
        load_agent_skills=load_agent_skills,
        agent_model_config_private=agent_model_config_private,
        default_agent_ids={"builtin"},
    )


def _node_kind(node: dict[str, object]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
    node_type = str(node.get("type") or "").strip()
    if data_kind and node_type in {"", "input", "default", "output"}:
        return data_kind
    return node_type or data_kind
