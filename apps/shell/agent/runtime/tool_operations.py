"""Tool operation facade for legacy runtime compatibility methods."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.recorders import build_tool_pending_approval
from apps.shell.agent.runtime.tool_requests import ToolRequestParser
from apps.shell.agent.tools.policy import ToolDescriptorRegistry


class RuntimeToolOperations:
    """Centralizes tool parsing, execution, and approval helper entrypoints."""

    def __init__(
        self,
        *,
        tool_request_runner: Any,
        tool_call_executor: Any,
    ) -> None:
        self._tool_request_runner = tool_request_runner
        self._tool_call_executor = tool_call_executor

    def run_tool_requests(
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
        self._tool_request_runner.run(
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

    def call_agent_tool(
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
        return self._tool_call_executor.execute(
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
    def tool_requests_from_message(message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        return ToolRequestParser().requests_from_message(message, content)

    @staticmethod
    def parse_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
        return ToolRequestParser().parse_tool_calls(tool_calls)

    @staticmethod
    def parse_tool_request(content: str) -> dict[str, Any] | None:
        return ToolRequestParser().parse_json_fallback(content)

    @staticmethod
    def validate_tool_payload(tool_name: str, payload: dict[str, Any]) -> None:
        ToolDescriptorRegistry.validate_payload(tool_name, payload)

    @staticmethod
    def build_pending_approval(
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
        now: Callable[[], str],
    ) -> dict[str, Any]:
        return build_tool_pending_approval(
            tool_request,
            messages=messages,
            next_iteration=next_iteration,
            remaining_tool_requests=remaining_tool_requests,
            now=now,
        )
