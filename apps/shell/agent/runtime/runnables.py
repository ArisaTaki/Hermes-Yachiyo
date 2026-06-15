"""Runnable catalog projections for Agents and Workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeRunnableCatalog:
    """Builds public runnable summaries without owning persistence."""

    def __init__(
        self,
        *,
        node_kind: Callable[[dict[str, Any]], str],
        get_agent: Callable[[str], dict[str, Any]],
    ) -> None:
        self._node_kind = node_kind
        self._get_agent = get_agent

    def list_runnables(
        self,
        agents: list[dict[str, Any]],
        workflows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "runnables": [
                self.agent_summary(agent)
                for agent in agents
            ]
            + [
                self.workflow_summary(workflow)
                for workflow in workflows
            ],
        }

    @staticmethod
    def agent_summary(agent: dict[str, Any]) -> dict[str, Any]:
        tool_policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
        allowed_tools = tool_policy.get("allowed_tools") if isinstance(tool_policy.get("allowed_tools"), list) else []
        approval_required = (
            tool_policy.get("approval_required")
            if isinstance(tool_policy.get("approval_required"), dict)
            else {}
        )
        return {
            "id": agent["agent_id"],
            "name": agent["name"],
            "nickname": agent.get("nickname") or agent["name"],
            "description": agent.get("description") or "",
            "avatar_url": agent.get("avatar_url") or "",
            "category": agent.get("category") or "custom",
            "output_contract": agent.get("output_contract") or "chat",
            "kind": "agent",
            "enabled": agent["enabled"],
            "tool_policy": {
                "allowed_tools": [str(item) for item in allowed_tools if str(item)],
                "approval_required": {
                    str(tool): bool(required)
                    for tool, required in approval_required.items()
                    if str(tool)
                },
            },
        }

    def workflow_participants(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        participants: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for node in workflow.get("nodes") or []:
            if self._node_kind(node) != "agent":
                continue
            data = node.get("data") or {}
            agent_id = str(data.get("agent_id") or data.get("agentId") or "").strip()
            if not agent_id or agent_id in seen_ids:
                continue
            try:
                agent = self._get_agent(agent_id)
            except KeyError:
                continue
            seen_ids.add(agent_id)
            participants.append(self.agent_summary(agent))
        return participants

    def workflow_summary(self, workflow: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": workflow["workflow_id"],
            "name": workflow["name"],
            "description": workflow.get("description") or "",
            "kind": "workflow",
            "enabled": workflow["enabled"],
            "participants": self.workflow_participants(workflow),
        }

    @staticmethod
    def list_delegation_targets(
        agents: list[dict[str, Any]],
        workflows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "agents": [
                {
                    "kind": "agent",
                    "id": agent["agent_id"],
                    "name": agent["name"],
                    "description": agent.get("description") or "",
                    "category": agent.get("category") or "custom",
                    "output_contract": agent.get("output_contract") or "chat",
                }
                for agent in agents
                if agent.get("enabled", True) and not agent.get("system")
            ],
            "workflows": [
                {
                    "kind": "workflow",
                    "id": workflow["workflow_id"],
                    "name": workflow["name"],
                    "description": workflow.get("description") or "",
                    "nodes": len(workflow.get("nodes") or []),
                    "output_contract": "workflow",
                }
                for workflow in workflows
                if workflow.get("enabled", True)
            ],
        }


class RuntimeRunnableResolver:
    """Resolves Agent/Workflow launch targets while leaving storage to callbacks."""

    def __init__(
        self,
        *,
        main_chat_agent_id: str,
        main_chat_virtual_agent: Callable[[], dict[str, Any]],
        ensure_row_factory: Callable[[], None],
        fetch_agent_by_id: Callable[[str], Any],
        fetch_workflow_by_id: Callable[[str], Any],
        fetch_agents_by_name: Callable[[str], list[Any]],
        fetch_workflow_by_name: Callable[[str], Any],
        row_to_agent: Callable[[Any], dict[str, Any]],
        row_to_workflow: Callable[[Any], dict[str, Any]],
        agent_summary: Callable[[dict[str, Any]], dict[str, Any]],
        workflow_summary: Callable[[dict[str, Any]], dict[str, Any]],
        error_type: type[Exception] = RuntimeError,
    ) -> None:
        self._main_chat_agent_id = main_chat_agent_id
        self._main_chat_virtual_agent = main_chat_virtual_agent
        self._ensure_row_factory = ensure_row_factory
        self._fetch_agent_by_id = fetch_agent_by_id
        self._fetch_workflow_by_id = fetch_workflow_by_id
        self._fetch_agents_by_name = fetch_agents_by_name
        self._fetch_workflow_by_name = fetch_workflow_by_name
        self._row_to_agent = row_to_agent
        self._row_to_workflow = row_to_workflow
        self._agent_summary = agent_summary
        self._workflow_summary = workflow_summary
        self._error_type = error_type

    def resolve(self, *, runnable_id: str = "", name: str = "") -> dict[str, Any] | None:
        self._ensure_row_factory()
        clean_id = str(runnable_id or "").strip()
        if clean_id == self._main_chat_agent_id:
            return self._agent_summary(self._main_chat_virtual_agent())
        if runnable_id:
            agent = self._fetch_agent_by_id(runnable_id)
            if agent:
                return self._agent_summary(self._row_to_agent(agent))
            workflow = self._fetch_workflow_by_id(runnable_id)
            if workflow:
                return self._workflow_summary(self._row_to_workflow(workflow))

        clean_name = str(name or "").strip()
        if not clean_name:
            return None
        if clean_name.lower() == "yachiyo":
            return self._agent_summary(self._main_chat_virtual_agent())

        agents = self._fetch_agents_by_name(clean_name)
        workflow = self._fetch_workflow_by_name(clean_name)
        matches = [*agents, *([workflow] if workflow is not None else [])]
        if len(matches) > 1:
            raise self._error_type("Agent/Workflow 名称不唯一")
        if agents:
            return self._agent_summary(self._row_to_agent(agents[0]))
        if workflow:
            return self._workflow_summary(self._row_to_workflow(workflow))
        return None


class RuntimeRunnableRunCoordinator:
    """Dispatches runnable launch requests to Agent or Workflow run creators."""

    def __init__(
        self,
        *,
        resolve_runnable: Callable[..., dict[str, Any] | None],
        create_agent_run: Callable[[dict[str, Any]], dict[str, Any]],
        create_workflow_run: Callable[[dict[str, Any]], dict[str, Any]],
        create_agent_run_async: Callable[..., dict[str, Any]],
        create_workflow_run_async: Callable[..., dict[str, Any]],
        error_type: type[Exception] = RuntimeError,
    ) -> None:
        self._resolve_runnable = resolve_runnable
        self._create_agent_run = create_agent_run
        self._create_workflow_run = create_workflow_run
        self._create_agent_run_async = create_agent_run_async
        self._create_workflow_run_async = create_workflow_run_async
        self._error_type = error_type

    def create_run(
        self,
        *,
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
        run_group_id: str = "",
        upstream: str = "",
        client_run_id: str = "",
        client_request_id: str = "",
    ) -> dict[str, Any]:
        runnable = self._required_runnable(runnable_id=runnable_id, name=name, message="未找到指定 Agent 或 Workflow")
        request_id = client_run_id or client_request_id
        if runnable["kind"] == "agent":
            run = self._create_agent_run({
                "agent_id": runnable["id"],
                "user_goal": user_goal,
                "source": "agent",
                "run_group_id": run_group_id,
                "upstream": upstream,
                "client_run_id": request_id,
            })
            run["agent_run_id"] = run["run_id"]
            run["runnable"] = runnable
            return run
        run = self._create_workflow_run({
            "workflow_id": runnable["id"],
            "user_goal": user_goal,
            "source": "workflow",
            "run_group_id": run_group_id,
            "client_run_id": request_id,
        })
        run["workflow_run_id"] = run["run_id"]
        run["runnable"] = runnable
        return run

    def create_run_async(
        self,
        *,
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
        run_group_id: str = "",
        upstream: str = "",
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        runnable = self._required_runnable(runnable_id=runnable_id, name=name, message="未找到指定 Agent 或 Workflow")
        if runnable["kind"] == "agent":
            run = self._create_agent_run_async(
                {
                    "agent_id": runnable["id"],
                    "user_goal": user_goal,
                    "source": "agent",
                    "run_group_id": run_group_id,
                    "upstream": upstream,
                },
                on_complete=on_complete,
            )
            run["agent_run_id"] = run["run_id"]
            run["runnable"] = runnable
            return run

        run = self._create_workflow_run_async(
            {
                "workflow_id": runnable["id"],
                "user_goal": user_goal,
                "source": "workflow",
                "run_group_id": run_group_id,
            },
            on_complete=on_complete,
        )
        run["workflow_run_id"] = run["run_id"]
        run["runnable"] = runnable
        return run

    def delegate(
        self,
        *,
        kind: str = "",
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
    ) -> dict[str, Any]:
        goal = str(user_goal or "").strip()
        if not goal:
            raise self._error_type("委派目标不能为空")
        runnable = self._required_runnable(runnable_id=runnable_id, name=name, message="未找到可委派的 Agent 或 Workflow")
        requested_kind = str(kind or "").strip()
        if requested_kind and requested_kind not in {runnable["kind"], f"{runnable['kind']}_run"}:
            raise self._error_type("委派类型与目标不匹配")
        if runnable["kind"] == "agent":
            run = self._create_agent_run({"agent_id": runnable["id"], "user_goal": goal, "source": "delegation"})
        else:
            run = self._create_workflow_run({"workflow_id": runnable["id"], "user_goal": goal, "source": "delegation"})
        return {
            "ok": run["status"] == "completed",
            "runnable": runnable,
            "run_id": run["run_id"],
            "run_group_id": run.get("run_group_id", ""),
            "status": run["status"],
            "result": run.get("result") or "",
            "pending_approval": run.get("pending_approval") if isinstance(run.get("pending_approval"), dict) else {},
        }

    def _required_runnable(
        self,
        *,
        runnable_id: str,
        name: str,
        message: str,
    ) -> dict[str, Any]:
        runnable = self._resolve_runnable(runnable_id=runnable_id, name=name)
        if runnable is None:
            raise self._error_type(message)
        if not runnable.get("enabled", True):
            raise self._error_type("指定 Agent 或 Workflow 已停用")
        return runnable
