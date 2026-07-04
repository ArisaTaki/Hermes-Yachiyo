"""Tests for runnable catalog projections split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.runnables import (
    RuntimeRunnableCatalog,
    RuntimeRunnableResolver,
    RuntimeRunnableRunCoordinator,
)


def test_runnable_catalog_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunnableCatalog is RuntimeRunnableCatalog
    assert agent_runtime.RuntimeRunnableResolver is RuntimeRunnableResolver
    assert agent_runtime.RuntimeRunnableRunCoordinator is RuntimeRunnableRunCoordinator


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


def test_runnable_resolver_resolves_agents_workflows_and_system_agent() -> None:
    agents = {
        "agent-1": {
            "agent_id": "agent-1",
            "name": "Coding",
            "nickname": "Coder",
            "enabled": True,
            "tool_policy": {},
        }
    }
    workflows = {
        "workflow-1": {
            "workflow_id": "workflow-1",
            "name": "Flow",
            "enabled": True,
            "nodes": [],
        }
    }
    resolver = RuntimeRunnableResolver(
        main_chat_agent_id="builtin:yachiyo-main",
        main_chat_virtual_agent=lambda: {
            "agent_id": "builtin:yachiyo-main",
            "name": "Yachiyo",
            "enabled": True,
            "tool_policy": {},
        },
        ensure_row_factory=lambda: None,
        fetch_agent_by_id=lambda agent_id: agents.get(agent_id),
        fetch_workflow_by_id=lambda workflow_id: workflows.get(workflow_id),
        fetch_agents_by_name=lambda name: [
            agent
            for agent in agents.values()
            if str(agent["name"]).lower() == name.lower()
            or str(agent.get("nickname") or "").lower() == name.lower()
        ],
        fetch_workflow_by_name=lambda name: next(
            (workflow for workflow in workflows.values() if str(workflow["name"]).lower() == name.lower()),
            None,
        ),
        row_to_agent=lambda row: row,
        row_to_workflow=lambda row: row,
        agent_summary=RuntimeRunnableCatalog.agent_summary,
        workflow_summary=lambda workflow: {
            "id": workflow["workflow_id"],
            "name": workflow["name"],
            "kind": "workflow",
            "enabled": workflow["enabled"],
            "participants": [],
        },
        error_type=AgentRuntimeError,
    )

    assert resolver.resolve(runnable_id="builtin:yachiyo-main")["name"] == "Yachiyo"
    assert resolver.resolve(name="yachiyo")["id"] == "builtin:yachiyo-main"
    assert resolver.resolve(runnable_id="agent-1")["kind"] == "agent"
    assert resolver.resolve(name="Coder")["id"] == "agent-1"
    assert resolver.resolve(runnable_id="workflow-1")["kind"] == "workflow"
    assert resolver.resolve(name="Flow")["id"] == "workflow-1"
    assert resolver.resolve(name="Missing") is None


def test_runnable_resolver_rejects_ambiguous_agent_workflow_names() -> None:
    resolver = RuntimeRunnableResolver(
        main_chat_agent_id="builtin:yachiyo-main",
        main_chat_virtual_agent=lambda: {"agent_id": "builtin:yachiyo-main", "name": "Yachiyo", "enabled": True},
        ensure_row_factory=lambda: None,
        fetch_agent_by_id=lambda _agent_id: None,
        fetch_workflow_by_id=lambda _workflow_id: None,
        fetch_agents_by_name=lambda _name: [{"agent_id": "agent-1", "name": "Shared", "enabled": True}],
        fetch_workflow_by_name=lambda _name: {"workflow_id": "workflow-1", "name": "Shared", "enabled": True},
        row_to_agent=lambda row: row,
        row_to_workflow=lambda row: row,
        agent_summary=RuntimeRunnableCatalog.agent_summary,
        workflow_summary=lambda workflow: {
            "id": workflow["workflow_id"],
            "name": workflow["name"],
            "kind": "workflow",
            "enabled": workflow["enabled"],
            "participants": [],
        },
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match="名称不唯一"):
        resolver.resolve(name="Shared")


def test_runnable_run_coordinator_dispatches_agent_run_with_client_request_id() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    coordinator = _run_coordinator(calls)

    run = coordinator.create_run(
        name="Coding",
        user_goal="Ship it",
        run_group_id="group-1",
        upstream="context",
        client_request_id="request-1",
    )

    assert run["agent_run_id"] == "agent-run-1"
    assert run["runnable"]["id"] == "agent-1"
    assert calls == [
        (
            "agent",
            {
                "agent_id": "agent-1",
                "user_goal": "Ship it",
                "source": "agent",
                "run_group_id": "group-1",
                "upstream": "context",
                "client_run_id": "request-1",
            },
        )
    ]


def test_runnable_run_coordinator_forwards_direct_agent_execution_plan() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    coordinator = _run_coordinator(calls)
    direct_requests = [{"tool": "app.open", "input": {"app_name": "Music"}}]

    run = coordinator.create_run_async(
        runnable_id="agent-1",
        user_goal="Open Music",
        runtime_planner_entrypoint=True,
        direct_tool_requests=direct_requests,
        daily_desktop_planning_context="Open Music from planner",
    )

    assert run["agent_run_id"] == "agent-run-1"
    assert calls == [
        (
            "agent_async",
            {
                "agent_id": "agent-1",
                "user_goal": "Open Music",
                "source": "agent",
                "run_group_id": "",
                "upstream": "",
                "runtime_planner_entrypoint": True,
                "direct_tool_requests": direct_requests,
                "daily_desktop_planning_context": "Open Music from planner",
            },
        )
    ]


def test_runnable_run_coordinator_forwards_direct_workflow_execution_plan() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    coordinator = _run_coordinator(calls)
    direct_requests = [{"tool": "app.open", "input": {"app_name": "Music"}}]

    run = coordinator.create_run_async(
        runnable_id="workflow-1",
        user_goal="Open Music",
        direct_tool_requests=direct_requests,
        daily_desktop_planning_context="Open Music from workflow plan",
    )

    assert run["workflow_run_id"] == "workflow-run-1"
    assert calls == [
        (
            "workflow_async",
            {
                "workflow_id": "workflow-1",
                "user_goal": "Open Music",
                "source": "workflow",
                "run_group_id": "",
                "direct_tool_requests": direct_requests,
                "daily_desktop_planning_context": "Open Music from workflow plan",
            },
        )
    ]


def test_runnable_run_coordinator_dispatches_workflow_run_async() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    completions: list[dict[str, object]] = []
    coordinator = _run_coordinator(calls)

    run = coordinator.create_run_async(
        runnable_id="workflow-1",
        user_goal="Run flow",
        run_group_id="group-2",
        on_complete=lambda item: completions.append(item),
    )

    assert run["workflow_run_id"] == "workflow-run-1"
    assert run["runnable"]["kind"] == "workflow"
    assert completions == [{"run_id": "workflow-run-1"}]
    assert calls == [
        (
            "workflow_async",
            {
                "workflow_id": "workflow-1",
                "user_goal": "Run flow",
                "source": "workflow",
                "run_group_id": "group-2",
            },
        )
    ]


def test_runnable_run_coordinator_validates_delegation_kind_and_goal() -> None:
    calls: list[tuple[str, dict[str, object]]] = []
    coordinator = _run_coordinator(calls)

    with pytest.raises(AgentRuntimeError, match="委派目标不能为空"):
        coordinator.delegate(name="Coding", user_goal="  ")
    with pytest.raises(AgentRuntimeError, match="委派类型与目标不匹配"):
        coordinator.delegate(kind="workflow", name="Coding", user_goal="Ship it")

    result = coordinator.delegate(kind="agent", name="Coding", user_goal="Ship it")

    assert result["ok"] is True
    assert result["run_id"] == "agent-run-1"
    assert calls == [
        (
            "agent",
            {
                "agent_id": "agent-1",
                "user_goal": "Ship it",
                "source": "delegation",
                "runtime_planner_entrypoint": True,
            },
        )
    ]


def _node_kind(node: dict[str, object]) -> str:
    data = node.get("data") if isinstance(node.get("data"), dict) else {}
    data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
    node_type = str(node.get("type") or "").strip()
    if data_kind and node_type in {"", "input", "default", "output"}:
        return data_kind
    return node_type or data_kind


def _run_coordinator(calls: list[tuple[str, dict[str, object]]]) -> RuntimeRunnableRunCoordinator:
    runnables = {
        "agent-1": {"id": "agent-1", "name": "Coding", "kind": "agent", "enabled": True},
        "workflow-1": {"id": "workflow-1", "name": "Flow", "kind": "workflow", "enabled": True},
    }

    def resolve_runnable(*, runnable_id: str = "", name: str = "") -> dict[str, object] | None:
        if runnable_id:
            return runnables.get(runnable_id)
        clean_name = str(name or "").strip()
        return next((item for item in runnables.values() if item["name"] == clean_name), None)

    def create_agent_run(request: dict[str, object]) -> dict[str, object]:
        calls.append(("agent", request))
        return {"run_id": "agent-run-1", "status": "completed", "result": "done"}

    def create_workflow_run(request: dict[str, object]) -> dict[str, object]:
        calls.append(("workflow", request))
        return {"run_id": "workflow-run-1", "status": "completed", "result": "done"}

    def create_agent_run_async(
        request: dict[str, object],
        *,
        on_complete=None,
    ) -> dict[str, object]:
        calls.append(("agent_async", request))
        if on_complete:
            on_complete({"run_id": "agent-run-1"})
        return {"run_id": "agent-run-1", "status": "running"}

    def create_workflow_run_async(
        request: dict[str, object],
        *,
        on_complete=None,
    ) -> dict[str, object]:
        calls.append(("workflow_async", request))
        if on_complete:
            on_complete({"run_id": "workflow-run-1"})
        return {"run_id": "workflow-run-1", "status": "running"}

    return RuntimeRunnableRunCoordinator(
        resolve_runnable=resolve_runnable,
        create_agent_run=create_agent_run,
        create_workflow_run=create_workflow_run,
        create_agent_run_async=create_agent_run_async,
        create_workflow_run_async=create_workflow_run_async,
        error_type=AgentRuntimeError,
    )
