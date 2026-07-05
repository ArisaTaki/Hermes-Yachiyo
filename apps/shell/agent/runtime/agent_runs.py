"""Agent run creation helpers for the shared runtime surface."""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.errors import AgentApprovalRequired
from apps.shell.agent.tools.policy import DAILY_DESKTOP_TOOL_NAMES, RuntimePolicyCompiler
from apps.shell.yachiyo_agent.entrypoint_tool_selection import (
    planner_first_direct_decision_and_tool_requests,
)

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
        workflow_run_id: str = "",
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        daily_desktop_planning_context: str | None = None,
    ) -> dict[str, Any]:
        preparation = self._preparer.prepare(
            run_id,
            agent,
            user_goal,
            upstream,
            run_group_id=run_group_id,
            workflow_run_id=workflow_run_id,
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
                daily_desktop_planning_context=(
                    daily_desktop_planning_context
                    if daily_desktop_planning_context is not None
                    else (
                        _runtime_planner_entrypoint_context(agent, user_goal)
                        if (
                            agent.get("_daily_desktop_policy_overlay") is True
                            or agent.get("_runtime_planner_entrypoint") is True
                        )
                        else ""
                    )
                ),
                direct_tool_request=direct_tool_request,
                direct_tool_requests=direct_tool_requests,
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
        agent = self._agent_for_payload(payload, agent_id)
        self._validate_agent_run_readiness(agent)
        start = self._starter.start_sync(payload, agent=agent, lock=self._lock)
        if start.existing:
            return start.run
        run = start.run
        execute_kwargs = {
            "upstream": str(payload.get("upstream") or ""),
            "run_group_id": str(run.get("run_group_id") or ""),
            **_agent_run_execution_options(payload),
        }
        workflow_run_id = str(payload.get("workflow_run_id") or "").strip()
        if workflow_run_id:
            execute_kwargs["workflow_run_id"] = workflow_run_id
        result = self._execute_agent_run(
            run["run_id"],
            agent,
            user_goal,
            **execute_kwargs,
        )
        if start.root_group:
            result = self._project_agent_run_group_if_root(result)
        return result

    def _agent_for_payload(self, payload: dict[str, Any], agent_id: str) -> dict[str, Any]:
        override = payload.get("agent_override")
        if not isinstance(override, dict):
            agent = self._get_agent_private(agent_id)
            return _with_entrypoint_runtime_planner(agent, payload)
        override_agent_id = str(override.get("agent_id") or override.get("id") or agent_id)
        if override_agent_id != agent_id:
            raise self._error_type("agent_override 与 agent_id 不一致")
        return _with_entrypoint_runtime_planner({**override, "agent_id": agent_id}, payload)


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
        agent = self._agent_for_payload(payload, agent_id)
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
                execute_kwargs = {
                    "upstream": str(payload.get("upstream") or ""),
                    "run_group_id": str(run.get("run_group_id") or ""),
                    **_agent_run_execution_options(payload),
                }
                workflow_run_id = str(payload.get("workflow_run_id") or "").strip()
                if workflow_run_id:
                    execute_kwargs["workflow_run_id"] = workflow_run_id
                exec_result = self._execute_agent_run(
                    run["run_id"],
                    agent,
                    user_goal,
                    **execute_kwargs,
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

    def _agent_for_payload(self, payload: dict[str, Any], agent_id: str) -> dict[str, Any]:
        override = payload.get("agent_override")
        if not isinstance(override, dict):
            agent = self._get_agent_private(agent_id)
            return _with_entrypoint_runtime_planner(agent, payload)
        override_agent_id = str(override.get("agent_id") or override.get("id") or agent_id)
        if override_agent_id != agent_id:
            raise self._error_type("agent_override 与 agent_id 不一致")
        return _with_entrypoint_runtime_planner({**override, "agent_id": agent_id}, payload)


def _runtime_planner_entrypoint_context(agent: dict[str, Any], user_goal: str) -> str:
    clean_goal = str(user_goal or "").strip()
    if (
        agent.get("_daily_desktop_policy_overlay") is True
        and agent.get("_runtime_planner_entrypoint") is not True
    ):
        return clean_goal
    if agent.get("_runtime_planner_entrypoint") is True:
        context = str(agent.get("_runtime_planner_entrypoint_context") or "").strip()
        candidate = context or clean_goal
        policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
        allowed = _string_list(policy.get("allowed_tools"))
        return candidate if _runtime_planner_entrypoint_should_execute(candidate, allowed) else ""
    return clean_goal


def _runtime_planner_entrypoint_should_execute(context: str, allowed_tools: list[str]) -> bool:
    clean_context = str(context or "").strip()
    if not clean_context:
        return False
    _decision, direct_requests = planner_first_direct_decision_and_tool_requests(
        clean_context,
        allowed_tools,
    )
    return bool(direct_requests)


def _with_entrypoint_runtime_planner(agent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    agent = _with_daily_desktop_policy_overlay(agent, payload)
    if not payload.get("runtime_planner_entrypoint"):
        return agent
    user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
    planning_goal = _payload_daily_desktop_planning_context(payload) or user_goal
    if (
        _looks_like_daily_desktop_howto_question(user_goal)
        or _looks_like_daily_desktop_howto_question(planning_goal)
    ):
        return agent
    policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
    allowed = _string_list(policy.get("allowed_tools"))
    _decision, direct_requests = planner_first_direct_decision_and_tool_requests(
        planning_goal,
        allowed,
    )
    if not direct_requests:
        overlay_selection = _daily_desktop_policy_overlay_selection(planning_goal)
        if not overlay_selection:
            return agent
        agent = _agent_with_daily_desktop_policy_overlay(agent)
    return {
        **agent,
        "_runtime_planner_entrypoint": True,
        "_runtime_planner_entrypoint_context": planning_goal,
    }


def _with_daily_desktop_policy_overlay(agent: dict[str, Any], payload: dict[str, Any]) -> dict[str, Any]:
    if not payload.get("daily_desktop_policy_overlay"):
        return agent
    user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
    planning_goal = _payload_daily_desktop_planning_context(payload) or user_goal
    if (
        _looks_like_daily_desktop_howto_question(user_goal)
        or _looks_like_daily_desktop_howto_question(planning_goal)
    ):
        return agent
    direct_requests = _payload_direct_tool_requests(payload)
    if not direct_requests:
        _decision, direct_requests = planner_first_direct_decision_and_tool_requests(
            planning_goal,
            list(DAILY_DESKTOP_TOOL_NAMES),
        )
        if not direct_requests:
            return agent
    return _agent_with_daily_desktop_policy_overlay(agent)


def _daily_desktop_policy_overlay_selection(planning_goal: str) -> bool:
    try:
        decision, direct_requests = planner_first_direct_decision_and_tool_requests(
            planning_goal,
            list(DAILY_DESKTOP_TOOL_NAMES),
        )
    except Exception:
        return False
    if not direct_requests:
        return False
    return _decision_supports_daily_desktop_policy_overlay(decision)


def _decision_supports_daily_desktop_policy_overlay(decision: Any) -> bool:
    intent = getattr(decision, "selected_intent", None)
    kind = str(getattr(intent, "kind", "") or "").strip()
    return kind in {
        "desktop_operation",
        "media_playback",
        "system_control",
        "clipboard_operation",
        "web_research",
        "information_capture",
        "communication",
        "schedule",
    }


def _agent_with_daily_desktop_policy_overlay(agent: dict[str, Any]) -> dict[str, Any]:
    policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
    allowed = _string_list(policy.get("allowed_tools"))
    approval_required = _daily_desktop_overlay_approval_required(policy)
    return {
        **agent,
        "_daily_desktop_policy_overlay": True,
        "tool_policy": {
            **policy,
            "allowed_tools": _unique_tools([*allowed, *DAILY_DESKTOP_TOOL_NAMES]),
            "approval_required": approval_required,
        },
    }


def _daily_desktop_overlay_approval_required(policy: dict[str, Any]) -> dict[str, Any]:
    approval_required = (
        dict(policy.get("approval_required"))
        if isinstance(policy.get("approval_required"), dict)
        else {}
    )
    default_approval = RuntimePolicyCompiler.default_tool_policy("custom")[
        "approval_required"
    ]
    for tool in DAILY_DESKTOP_TOOL_NAMES:
        if default_approval.get(tool):
            approval_required.setdefault(tool, True)
    return approval_required


def _payload_daily_desktop_planning_context(payload: dict[str, Any]) -> str:
    return str(payload.get("daily_desktop_planning_context") or "").strip()


def _agent_run_execution_options(payload: dict[str, Any]) -> dict[str, Any]:
    options: dict[str, Any] = {}
    direct_tool_request = payload.get("direct_tool_request")
    if isinstance(direct_tool_request, dict):
        options["direct_tool_request"] = dict(direct_tool_request)
    direct_tool_requests = _payload_direct_tool_requests(payload)
    if direct_tool_requests:
        options["direct_tool_requests"] = direct_tool_requests
    if "daily_desktop_planning_context" in payload:
        options["daily_desktop_planning_context"] = str(
            payload.get("daily_desktop_planning_context") or ""
        )
    return options


def _payload_direct_tool_requests(payload: dict[str, Any]) -> list[dict[str, Any]]:
    value = payload.get("direct_tool_requests")
    raw_items: list[Any] = list(value) if isinstance(value, list) else []
    single = payload.get("direct_tool_request")
    if isinstance(single, dict):
        raw_items.insert(0, single)
    requests: list[dict[str, Any]] = []
    for item in raw_items:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool") or "").strip()
        if not tool_name:
            continue
        request_input = item.get("input") if isinstance(item.get("input"), dict) else {}
        requests.append({**item, "tool": tool_name, "input": dict(request_input)})
    return requests


def _looks_like_daily_desktop_howto_question(text: str) -> bool:
    lowered = str(text or "").strip().lower()
    if not lowered:
        return False
    return (
        lowered.startswith(("怎么", "如何", "怎样"))
        or "怎么用" in lowered
        or "如何用" in lowered
        or "how to " in lowered
        or "how do i " in lowered
        or "how can i " in lowered
    )


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        value = [value]
    if not isinstance(value, list):
        return []
    return [str(item or "").strip() for item in value if str(item or "").strip()]


def _unique_tools(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        clean = str(value or "").strip()
        if clean and clean not in result:
            result.append(clean)
    return result
