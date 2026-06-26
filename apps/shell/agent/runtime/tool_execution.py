"""Tool call execution coordinator for Agent runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from packages.security import redact_api_error_text


def _default_allows_tool(tool_name: str, allowed_tools: list[str]) -> bool:
    return tool_name in set(str(tool or "").strip() for tool in allowed_tools)


def _normalized_app_lookup(value: Any) -> str:
    return " ".join(str(value or "").strip().casefold().split())


def _discovered_app_name_for_query(
    timeline: list[dict[str, Any]],
    query: str,
) -> str:
    clean_query = _normalized_app_lookup(query)
    if not clean_query:
        return ""
    for event in reversed(timeline):
        if event.get("event") != "agent.tool.call":
            continue
        if str(event.get("detail") or "") != "desktop.list_apps":
            continue
        input_preview = event.get("input_preview") if isinstance(event.get("input_preview"), dict) else {}
        if _normalized_app_lookup(input_preview.get("query")) != clean_query:
            continue
        result = event.get("result") if isinstance(event.get("result"), dict) else {}
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        apps = data.get("apps") if isinstance(data.get("apps"), list) else []
        for app in apps:
            if not isinstance(app, dict):
                continue
            app_name = str(app.get("name") or "").strip()
            if app_name:
                return app_name
    return ""


def _tool_request_with_discovered_app_name(
    tool_request: dict[str, Any],
    timeline: list[dict[str, Any]],
) -> dict[str, Any]:
    raw_input = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
    requested_app_name = str(raw_input.get("app_name") or "").strip()
    discovered_app_name = _discovered_app_name_for_query(timeline, requested_app_name)
    if not discovered_app_name or _normalized_app_lookup(discovered_app_name) == _normalized_app_lookup(
        requested_app_name
    ):
        return tool_request
    return {
        **tool_request,
        "input": {
            **raw_input,
            "app_name": discovered_app_name,
        },
    }


def _tool_result_artifact(tool_name: str, tool_result: dict[str, Any]) -> dict[str, Any] | None:
    if not tool_result.get("ok"):
        return None
    if tool_name == "artifact.write":
        return {"kind": "tool_artifact", **tool_result}
    raw_artifact = tool_result.get("artifact")
    if not isinstance(raw_artifact, dict):
        return None
    artifact = {"kind": "tool_artifact", "source_tool": tool_name, **raw_artifact}
    if not artifact.get("source_tool"):
        artifact["source_tool"] = tool_name
    return artifact


def _tool_result_extra_artifacts(
    tool_name: str,
    tool_result: dict[str, Any],
    primary_artifact: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    raw_artifacts = tool_result.get("artifacts")
    if not isinstance(raw_artifacts, list):
        return []
    primary_path = str((primary_artifact or {}).get("path") or "")
    artifacts: list[dict[str, Any]] = []
    for raw_artifact in raw_artifacts:
        if not isinstance(raw_artifact, dict):
            continue
        artifact = {"kind": "tool_artifact", "source_tool": tool_name, **raw_artifact}
        if not artifact.get("source_tool"):
            artifact["source_tool"] = tool_name
        if primary_path and str(artifact.get("path") or "") == primary_path:
            continue
        if artifact not in artifacts:
            artifacts.append(artifact)
    return artifacts


class RuntimeToolCallExecutor:
    """Executes one tool call while preserving policy, budget, and event gates."""

    def __init__(
        self,
        *,
        normalize_tool_name: Callable[[Any], str],
        input_preview: Callable[[Any], Any],
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        validate_tool_payload: Callable[[str, dict[str, Any]], None],
        limit_tool_result: Callable[[dict[str, Any]], dict[str, Any]],
        timeline_factory: Callable[..., dict[str, Any]],
        tool_call_events: Any,
        trace_events: Any,
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        allows_tool: Callable[[str, list[str]], bool] | None = None,
    ) -> None:
        self._normalize_tool_name = normalize_tool_name
        self._input_preview = input_preview
        self._run_budget = run_budget
        self._validate_tool_payload = validate_tool_payload
        self._limit_tool_result = limit_tool_result
        self._timeline = timeline_factory
        self._tool_call_events = tool_call_events
        self._trace_events = trace_events
        self._append_run_event = append_run_event
        self._allows_tool = allows_tool or _default_allows_tool

    def execute(
        self,
        tool_request: dict[str, Any],
        allowed_tools: list[str],
        broker: Any,
        timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        approved: bool = False,
        run_id: str = "",
        budget: Any = None,
    ) -> dict[str, Any]:
        tool_name = self._normalize_tool_name(tool_request.get("tool"))
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        input_preview = self._input_preview(payload)
        budget = budget or self._run_budget(run_id, timeline)
        if not self._allows_tool(tool_name, allowed_tools):
            budget.claim_tool_call(tool_name)
            timeline.append(self._timeline("agent.tool.denied", tool_name, input_preview=input_preview))
            self._tool_call_events.denied(run_id, tool_name, input_preview)
            raise AgentRuntimeError(f"Agent 试图调用未授权工具：{tool_name}")
        self._tool_call_events.requested(
            run_id,
            tool_name,
            input_preview,
            approved=approved,
        )
        try:
            self._validate_tool_payload(tool_name, payload)
        except AgentRuntimeError as exc:
            self._tool_call_events.failed(
                run_id,
                tool_name,
                input_preview,
                approved=approved,
                pre_validation=True,
                error=exc,
            )
            raise
        budget.claim_tool_call(
            tool_name,
            terminal_execution=tool_name == "terminal.run" and approved,
        )
        self._tool_call_events.started(
            run_id,
            tool_name,
            input_preview,
            approved=approved,
        )
        try:
            tool_result = broker.call(tool_name, payload, approved=approved)
        except AgentRuntimeError as exc:
            if not tool_name.startswith("workspace."):
                self._tool_call_events.failed(
                    run_id,
                    tool_name,
                    input_preview,
                    approved=approved,
                    error=exc,
                )
                raise
            terminal_hint = (
                " If the required target is outside the configured workspace, "
                "use terminal.run and wait for approval."
                if "terminal.run" in allowed_tools
                else ""
            )
            tool_result = {
                "ok": False,
                "tool": tool_name,
                "error": redact_api_error_text(exc),
                "hint": (
                    "Workspace tools only accept relative paths within the configured Default Workdir. "
                    "Use a valid relative path and do not retry the same invalid path."
                    f"{terminal_hint}"
                ),
                **(
                    {"suggested_tool": "terminal.run"}
                    if "terminal.run" in allowed_tools
                    else {}
                ),
            }
        tool_result = self._limit_tool_result(tool_result)
        self._tool_call_events.result(
            run_id,
            tool_name,
            input_preview,
            tool_result,
            approved=approved,
        )
        timeline.append(
            self._timeline(
                "agent.tool.call",
                tool_name,
                input_preview=input_preview,
                result=tool_result,
            )
        )
        if run_id:
            self._tool_call_events.agent_tool_call(
                run_id,
                tool_name,
                input_preview,
                tool_result,
                approved=approved,
            )
            trace_event = self._trace_events.memory_skill_trace_event(
                tool_name,
                input_preview,
                tool_result,
            )
            if trace_event is not None:
                self._append_run_event(
                    run_id,
                    trace_event["event_type"],
                    trace_event["payload"],
                )
        artifact = _tool_result_artifact(tool_name, tool_result)
        extra_artifacts = _tool_result_extra_artifacts(tool_name, tool_result, artifact)
        if artifact is not None and artifacts is not None:
            if artifact not in artifacts:
                artifacts.append(artifact)
        for extra_artifact in extra_artifacts:
            if artifacts is not None and extra_artifact not in artifacts:
                artifacts.append(extra_artifact)
        if artifact is not None and run_id:
            self._append_run_event(
                run_id,
                "artifact.created",
                self._trace_events.artifact_created_payload(
                    tool_result,
                    run_id=run_id,
                    source_tool=tool_name,
                ),
            )
        if run_id:
            for extra_artifact in extra_artifacts:
                self._append_run_event(
                    run_id,
                    "artifact.created",
                    self._trace_events.artifact_created_payload(
                        {"ok": True, "artifact": extra_artifact},
                        run_id=run_id,
                        source_tool=tool_name,
                    ),
                )
        return tool_result


class RuntimeToolRequestRunner:
    """Runs model-requested tools while preserving pause and projection behavior."""

    def __init__(
        self,
        *,
        normalize_tool_name: Callable[[Any], str],
        input_preview: Callable[[Any], Any],
        run_budget: Callable[[str, list[dict[str, Any]]], Any],
        user_goal_from_messages: Callable[[list[dict[str, Any]]], str],
        goal_disallows_tool: Callable[[str, str], str],
        timeline_factory: Callable[..., dict[str, Any]],
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        tool_loop_projection: Any,
        pending_approval_builder: Any,
        call_agent_tool: Callable[..., dict[str, Any]],
    ) -> None:
        self._normalize_tool_name = normalize_tool_name
        self._input_preview = input_preview
        self._run_budget = run_budget
        self._user_goal_from_messages = user_goal_from_messages
        self._goal_disallows_tool = goal_disallows_tool
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._tool_loop_projection = tool_loop_projection
        self._pending_approval_builder = pending_approval_builder
        self._call_agent_tool = call_agent_tool

    def run(
        self,
        tool_requests: list[dict[str, Any]],
        allowed_tools: list[str],
        broker: Any,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        next_iteration: int,
        run_id: str = "",
        budget: Any = None,
    ) -> None:
        budget = budget or self._run_budget(run_id, timeline)
        user_goal = self._user_goal_from_messages(messages)
        for index, tool_request in enumerate(tool_requests):
            tool_request = _tool_request_with_discovered_app_name(tool_request, timeline)
            tool_name = self._normalize_tool_name(tool_request.get("tool"))
            raw_input = (
                tool_request.get("input")
                if isinstance(tool_request.get("input"), dict)
                else {}
            )
            input_preview = self._input_preview(raw_input)
            goal_block_reason = self._goal_disallows_tool(user_goal, tool_name)
            if goal_block_reason:
                budget.claim_tool_call(tool_name)
                tool_result = {
                    "ok": False,
                    "blocked_by_user_goal": True,
                    "tool": tool_name,
                    "error": goal_block_reason,
                    "hint": (
                        "Do not ask for approval. Continue with an inline answer "
                        "that follows the user's stated constraint."
                    ),
                }
                timeline.append(
                    self._timeline(
                        "agent.tool.skipped",
                        tool_name,
                        input_preview=input_preview,
                        result=tool_result,
                    )
                )
                if run_id:
                    self._append_run_event(
                        run_id,
                        "agent.tool.skipped",
                        {
                            "tool": tool_name,
                            "input_preview": input_preview,
                            "result": tool_result,
                        },
                    )
                self._tool_loop_projection.append_tool_result_message(
                    messages,
                    {**tool_request, "tool": tool_name},
                    tool_result,
                )
                continue
            tool_result = self._call_agent_tool(
                tool_request,
                allowed_tools,
                broker,
                timeline,
                artifacts=artifacts,
                run_id=run_id,
                budget=budget,
            )
            if tool_result.get("approval_required"):
                pending_approval = self._pending_approval_builder.build(
                    tool_request,
                    messages=messages,
                    next_iteration=next_iteration,
                    remaining_tool_requests=tool_requests[index + 1 :],
                )
                for key in ("risk_level", "policy_reason", "plugin_id"):
                    value = str(tool_result.get(key) or "").strip()
                    if value:
                        pending_approval[key] = value
                raise AgentApprovalRequired(pending_approval)
            fatal_failure = self._tool_loop_projection.fatal_failure_detail(
                tool_name,
                tool_request,
                tool_result,
            )
            if fatal_failure:
                timeline.append(
                    self._timeline(
                        "agent.tool.failed",
                        tool_name,
                        input_preview=input_preview,
                        result=tool_result,
                        status="failed",
                    )
                )
                raise AgentRuntimeError(fatal_failure)
            self._tool_loop_projection.append_tool_result_message(
                messages,
                tool_request,
                tool_result,
            )
