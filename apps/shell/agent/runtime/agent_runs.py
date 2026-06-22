"""Agent run creation helpers for the shared runtime surface."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.errors import AgentApprovalRequired


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


class RuntimeAgentRunExecutor:
    """Executes a prepared Agent Run and projects terminal/approval outcomes."""

    def __init__(
        self,
        *,
        preparer: Any,
        continue_custom_api_agent: Callable[..., str],
        agent_run_outcomes: Any,
        approval_pause: Any,
    ) -> None:
        self._preparer = preparer
        self._continue_custom_api_agent = continue_custom_api_agent
        self._agent_run_outcomes = agent_run_outcomes
        self._approval_pause = approval_pause

    def execute(
        self,
        run_id: str,
        agent: dict[str, Any],
        user_goal: str,
        upstream: str = "",
        run_group_id: str = "",
    ) -> dict[str, Any]:
        preparation = self._preparer.prepare(
            run_id,
            agent,
            user_goal,
            upstream,
            run_group_id=run_group_id,
        )
        timeline = preparation.timeline
        artifacts = preparation.artifacts
        try:
            self._preparer.write_context_artifact(run_id, preparation)
            result = self._continue_custom_api_agent(
                agent,
                preparation.context,
                preparation.broker,
                timeline,
                artifacts,
                run_id=run_id,
            )
            return self._agent_run_outcomes.completed(
                run_id,
                result,
                timeline=timeline,
                artifacts=artifacts,
            )
        except AgentApprovalRequired as exc:
            return self._approval_pause.project_tool_required(
                run_id,
                pending_approval=exc.pending_approval,
                timeline=timeline,
                artifacts=artifacts,
            )
        except Exception as exc:
            return self._agent_run_outcomes.failed(
                run_id,
                exc,
                timeline=timeline,
                artifacts=artifacts,
            )


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
            run_group_id=str(run.get("run_group_id") or ""),
        )
        if start.root_group:
            result = self._project_agent_run_group_if_root(result)
        return result


class RuntimeAgentRunAsyncCoordinator:
    """Starts Agent Runs for background execution while preserving return shape."""

    def __init__(
        self,
        *,
        get_agent_private: Callable[[str], dict[str, Any]],
        validate_agent_run_readiness: Callable[[dict[str, Any]], None],
        starter: RuntimeAgentRunStarter,
        execute_agent_run: Callable[..., dict[str, Any]],
        project_agent_run_group_if_root: Callable[[dict[str, Any]], dict[str, Any]],
        resolve_runnable: Callable[..., dict[str, Any] | None],
        update_run: Callable[..., dict[str, Any]],
        runtime_agent_timeline: Any,
        runtime_agent_run_events: Any,
        redact_error: Callable[[Any], str],
        error_type: type[Exception],
        thread_factory: Callable[..., Any] = threading.Thread,
        logger: logging.Logger | None = None,
    ) -> None:
        self._get_agent_private = get_agent_private
        self._validate_agent_run_readiness = validate_agent_run_readiness
        self._starter = starter
        self._execute_agent_run = execute_agent_run
        self._project_agent_run_group_if_root = project_agent_run_group_if_root
        self._resolve_runnable = resolve_runnable
        self._update_run = update_run
        self._runtime_agent_timeline = runtime_agent_timeline
        self._runtime_agent_run_events = runtime_agent_run_events
        self._redact_error = redact_error
        self._error_type = error_type
        self._thread_factory = thread_factory
        self._logger = logger or logging.getLogger(__name__)

    def create_async(
        self,
        payload: dict[str, Any],
        *,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        agent_id = str(payload.get("agent_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not agent_id:
            raise self._error_type("缺少 agent_id")
        if not user_goal:
            raise self._error_type("运行目标不能为空")
        agent = self._get_agent_private(agent_id)
        self._validate_agent_run_readiness(agent)
        start = self._starter.start_async(payload, agent=agent)
        run = start.run
        result = {
            **run,
            "status": "processing",
            "runnable": self._resolve_runnable(runnable_id=agent_id),
            "agent_run_id": run["run_id"],
        }

        def execute_in_background() -> None:
            try:
                exec_result = self._execute_agent_run(
                    run["run_id"],
                    agent,
                    user_goal,
                    upstream=str(payload.get("upstream") or ""),
                    run_group_id=str(run.get("run_group_id") or ""),
                )
                if start.root_group:
                    exec_result = self._project_agent_run_group_if_root(exec_result)
                if on_complete:
                    on_complete(exec_result)
            except Exception as exc:
                self._logger.error("异步 Agent Run 执行失败: %s", exc, exc_info=True)
                safe_error = self._redact_error(exc)
                self._runtime_agent_run_events.failed(run["run_id"], safe_error)
                self._update_run(
                    run["run_id"],
                    status="failed",
                    result=safe_error,
                    timeline=[self._runtime_agent_timeline.failed(safe_error)],
                    artifacts=[],
                    pending_approval=None,
                )
                if on_complete:
                    on_complete({
                        **run,
                        "status": "failed",
                        "result": safe_error,
                    })

        thread = self._thread_factory(
            target=execute_in_background,
            name=f"agent-run-{run['run_id'][:8]}",
            daemon=True,
        )
        thread.start()
        return result
