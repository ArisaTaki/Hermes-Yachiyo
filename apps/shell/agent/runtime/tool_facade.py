"""Tool-loop compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.clock import utc_now_iso as _now
from apps.shell.agent.runtime.tool_loop import (
    append_tool_result_message as _runtime_append_tool_result_message,
    assistant_message_for_history as _runtime_assistant_message_for_history,
    fatal_tool_failure_detail as _runtime_fatal_tool_failure_detail,
    tool_loop_limit_artifact_completion as _runtime_tool_loop_limit_artifact_completion,
    tool_loop_limit_detail as _runtime_tool_loop_limit_detail,
)
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations


class RuntimeToolFacadeMixin:
    """Keeps legacy Tool helper methods while delegating to split services."""

    @staticmethod
    def _tool_loop_limit_detail(timeline: list[dict[str, Any]]) -> str:
        return _runtime_tool_loop_limit_detail(timeline)

    @staticmethod
    def _tool_loop_limit_artifact_completion(timeline: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> str | None:
        return _runtime_tool_loop_limit_artifact_completion(timeline, artifacts)

    @staticmethod
    def _fatal_tool_failure_detail(tool_name: str, tool_request: dict[str, Any], tool_result: dict[str, Any]) -> str:
        return _runtime_fatal_tool_failure_detail(tool_name, tool_request, tool_result)

    @staticmethod
    def _assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
        return _runtime_assistant_message_for_history(message)

    @staticmethod
    def _append_tool_result_message(messages: list[dict[str, Any]], tool_request: dict[str, Any], tool_result: dict[str, Any]) -> None:
        _runtime_append_tool_result_message(messages, tool_request, tool_result)

    def _run_tool_requests(
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
        budget: Any | None = None,
    ) -> None:
        self.tool_operations.run_tool_requests(
            tool_requests,
            allowed_tools,
            broker,
            messages,
            timeline,
            artifacts,
            next_iteration=next_iteration,
            run_id=run_id,
            budget=budget,
        )

    def _call_agent_tool(
        self,
        tool_request: dict[str, Any],
        allowed_tools: list[str],
        broker: Any,
        timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        approved: bool = False,
        run_id: str = "",
        budget: Any | None = None,
    ) -> dict[str, Any]:
        return self.tool_operations.call_agent_tool(
            tool_request,
            allowed_tools,
            broker,
            timeline,
            artifacts=artifacts,
            approved=approved,
            run_id=run_id,
            budget=budget,
        )

    @staticmethod
    def _make_pending_approval(
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return RuntimeToolOperations.build_pending_approval(
            tool_request,
            messages=messages,
            next_iteration=next_iteration,
            remaining_tool_requests=remaining_tool_requests,
            now=_now,
        )

    def _tool_requests_from_message(self, message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        return self.tool_operations.tool_requests_from_message(message, content)
