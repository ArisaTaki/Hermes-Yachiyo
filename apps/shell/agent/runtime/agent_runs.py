"""Agent run creation helpers for the shared runtime surface."""

from __future__ import annotations

from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AgentRunStart:
    run: dict[str, Any]
    root_group: bool
    existing: bool = False


class RuntimeAgentRunStarter:
    """Creates Agent Run rows while preserving legacy idempotency semantics."""

    def __init__(
        self,
        *,
        get_run_group: Callable[[str], dict[str, Any]],
        insert_run_group: Callable[..., dict[str, Any]],
        insert_run: Callable[..., dict[str, Any]],
        run_by_client_request_id: Callable[[str], dict[str, Any] | None],
        client_request_id_from_payload: Callable[[dict[str, Any]], str],
        agent_workspace_dir: Callable[[dict[str, Any]], str],
    ) -> None:
        self._get_run_group = get_run_group
        self._insert_run_group = insert_run_group
        self._insert_run = insert_run
        self._run_by_client_request_id = run_by_client_request_id
        self._client_request_id_from_payload = client_request_id_from_payload
        self._agent_workspace_dir = agent_workspace_dir

    def start_sync(
        self,
        payload: dict[str, Any],
        *,
        agent: dict[str, Any],
        lock: AbstractContextManager[Any],
    ) -> AgentRunStart:
        client_request_id = self._client_request_id_from_payload(payload)
        existing = self._run_by_client_request_id(client_request_id)
        if existing is not None:
            return AgentRunStart(existing, root_group=False, existing=True)
        with lock:
            existing = self._run_by_client_request_id(client_request_id)
            if existing is not None:
                return AgentRunStart(existing, root_group=False, existing=True)
            return self._insert_new_run(payload, agent=agent, client_request_id=client_request_id)

    def start_async(self, payload: dict[str, Any], *, agent: dict[str, Any]) -> AgentRunStart:
        return self._insert_new_run(payload, agent=agent, client_request_id="")

    def _insert_new_run(
        self,
        payload: dict[str, Any],
        *,
        agent: dict[str, Any],
        client_request_id: str,
    ) -> AgentRunStart:
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        run_group_id = str(payload.get("run_group_id") or "").strip()
        root_group = False
        if run_group_id:
            self._get_run_group(run_group_id)
        else:
            group = self._insert_run_group(
                title=f"{agent['name']}: {user_goal[:80]}",
                source=str(payload.get("source") or "agent"),
                workspace_dir=self._agent_workspace_dir(agent),
            )
            run_group_id = group["run_group_id"]
            root_group = True
        run = self._insert_run(
            kind="agent_run",
            runnable_id=str(payload.get("agent_id") or payload.get("runnable_id") or agent.get("agent_id") or ""),
            user_goal=user_goal,
            run_group_id=run_group_id,
            client_request_id=client_request_id,
        )
        return AgentRunStart(run, root_group=root_group)


class RuntimeAgentRunCoordinator:
    """Coordinates synchronous Agent Run validation, creation, and execution."""

    def __init__(
        self,
        *,
        get_agent_private: Callable[[str], dict[str, Any]],
        validate_agent_run_readiness: Callable[[dict[str, Any]], None],
        starter: RuntimeAgentRunStarter,
        execute_agent_run: Callable[..., dict[str, Any]],
        project_agent_run_group_if_root: Callable[[dict[str, Any]], dict[str, Any]],
        lock: AbstractContextManager[Any],
        error_type: type[Exception],
    ) -> None:
        self._get_agent_private = get_agent_private
        self._validate_agent_run_readiness = validate_agent_run_readiness
        self._starter = starter
        self._execute_agent_run = execute_agent_run
        self._project_agent_run_group_if_root = project_agent_run_group_if_root
        self._lock = lock
        self._error_type = error_type

    def create_sync(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(payload.get("agent_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not agent_id:
            raise self._error_type("缺少 agent_id")
        if not user_goal:
            raise self._error_type("运行目标不能为空")
        agent = self._get_agent_private(agent_id)
        self._validate_agent_run_readiness(agent)
        start = self._starter.start_sync(payload, agent=agent, lock=self._lock)
        if start.existing:
            return start.run
        run = start.run
        result = self._execute_agent_run(
            run["run_id"],
            agent,
            user_goal,
            upstream=str(payload.get("upstream") or ""),
        )
        if start.root_group:
            result = self._project_agent_run_group_if_root(result)
        return result
