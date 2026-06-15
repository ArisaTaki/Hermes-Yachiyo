"""Tests for runnable catalog projections split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.runnables import RuntimeRunnableCatalog


def test_runnable_catalog_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunnableCatalog is RuntimeRunnableCatalog


def test_runnable_catalog_projects_agent_policy_summary() -> None:
    summary = RuntimeRunnableCatalog.agent_summary(
        {
            "agent_id": "agent-1",
            "name": "Coding",
            "nickname": "",
            "description": "Writes code",
            "avatar_url": "avatar.png",
            "category": "dev",
            "output_contract": "diff",
            "enabled": True,
            "tool_policy": {
                "allowed_tools": ["workspace.read", "", "terminal.run"],
                "approval_required": {"terminal.run": True, "": True},
            },
        }
    )

    assert summary == {
        "id": "agent-1",
        "name": "Coding",
        "nickname": "Coding",
        "description": "Writes code",
        "avatar_url": "avatar.png",
        "category": "dev",
        "output_contract": "diff",
        "kind": "agent",
        "enabled": True,
        "tool_policy": {
            "allowed_tools": ["workspace.read", "terminal.run"],
            "approval_required": {"terminal.run": True},
        },
    }


def test_runnable_catalog_projects_workflow_participants_once() -> None:
    agents = {
        "agent-design": {
            "agent_id": "agent-design",
            "name": "Design",
            "nickname": "Design",
            "enabled": True,
        },
        "agent-code": {
            "agent_id": "agent-code",
            "name": "Code",
            "nickname": "Code",
            "enabled": True,
        },
    }
    catalog = RuntimeRunnableCatalog(
        node_kind=_node_kind,
        get_agent=lambda agent_id: agents[agent_id],
    )

    workflow = {
        "workflow_id": "workflow-1",
        "name": "Build Flow",
        "description": "Runs design and code",
        "enabled": True,
        "nodes": [
            {"id": "start", "type": "start", "data": {}},
            {"id": "design", "type": "agent", "data": {"agent_id": "agent-design"}},
            {"id": "design-again", "type": "agent", "data": {"agent_id": "agent-design"}},
            {"id": "code", "type": "agent", "data": {"agentId": "agent-code"}},
        ],
    }

    summary = catalog.workflow_summary(workflow)

    assert summary["id"] == "workflow-1"
    assert summary["kind"] == "workflow"
    assert [participant["id"] for participant in summary["participants"]] == [
        "agent-design",
        "agent-code",
    ]


def test_runnable_catalog_lists_delegation_targets_without_system_agents() -> None:
    targets = RuntimeRunnableCatalog.list_delegation_targets(
        [
            {"agent_id": "builtin", "name": "Yachiyo", "enabled": True, "system": True},
            {
                "agent_id": "agent-1",
                "name": "Research",
                "description": "Finds facts",
                "category": "research",
                "output_contract": "report",
                "enabled": True,
            },
            {"agent_id": "agent-disabled", "name": "Off", "enabled": False},
        ],
        [
            {
                "workflow_id": "workflow-1",
                "name": "Daily Flow",
                "description": "Runs steps",
                "nodes": [{}, {}],
                "enabled": True,
            },
            {"workflow_id": "workflow-off", "name": "Off Flow", "nodes": [], "enabled": False},
        ],
    )

    assert [agent["id"] for agent in targets["agents"]] == ["agent-1"]
    assert targets["agents"][0]["output_contract"] == "report"
    assert [workflow["id"] for workflow in targets["workflows"]] == ["workflow-1"]
    assert targets["workflows"][0]["nodes"] == 2


def _node_kind(node: dict[str, object]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
    node_type = str(node.get("type") or "").strip()
    if data_kind and node_type in {"", "input", "default", "output"}:
        return data_kind
    return node_type or data_kind
