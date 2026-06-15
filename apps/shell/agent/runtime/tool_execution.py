"""Tool call execution coordinator for Agent runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.policy import PolicyGate
from packages.security import redact_api_error_text


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
        if not PolicyGate.allows_tool(tool_name, allowed_tools):
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
        if artifacts is not None and tool_name == "artifact.write" and tool_result.get("ok"):
            artifact = {"kind": "tool_artifact", **tool_result}
            if artifact not in artifacts:
                artifacts.append(artifact)
            if run_id:
                self._append_run_event(
                    run_id,
                    "artifact.created",
                    self._trace_events.artifact_created_payload(
                        tool_result,
                        run_id=run_id,
                    ),
                )
        return tool_result
