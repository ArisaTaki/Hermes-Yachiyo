"""Tool request parsing for model messages."""

from __future__ import annotations

import json
import re
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.policy import TOOL_NAME_ALIASES

MAX_AGENT_TOOL_ITERATIONS = 50


def normalize_tool_name(value: Any) -> str:
    name = str(value or "").strip()
    return TOOL_NAME_ALIASES.get(name, name)


def normalize_tool_iteration(
    value: Any,
    *,
    max_iterations: int = MAX_AGENT_TOOL_ITERATIONS,
) -> int:
    try:
        iteration = int(value or 0)
    except (TypeError, ValueError):
        iteration = 0
    return max(0, min(iteration, max_iterations))


class ToolRequestParser:
    """Parses native tool_calls and JSON fallback tool requests."""

    def requests_from_message(self, message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        native = self.parse_tool_calls(message.get("tool_calls"))
        if native:
            return native
        fallback = self.parse_json_fallback(content)
        return [fallback] if fallback else []

    def parse_tool_calls(self, tool_calls: Any) -> list[dict[str, Any]]:
        if not isinstance(tool_calls, list):
            return []
        requests = []
        for index, call in enumerate(tool_calls):
            if not isinstance(call, dict):
                continue
            function = call.get("function") if isinstance(call.get("function"), dict) else {}
            function_name = str(function.get("name") or "").strip()
            if not function_name:
                continue
            raw_arguments = function.get("arguments") or "{}"
            if isinstance(raw_arguments, str):
                try:
                    arguments = json.loads(raw_arguments or "{}")
                except json.JSONDecodeError as exc:
                    raise AgentRuntimeError(f"工具参数不是合法 JSON：{function_name}") from exc
            elif isinstance(raw_arguments, dict):
                arguments = raw_arguments
            else:
                raise AgentRuntimeError(f"工具参数格式无效：{function_name}")
            if not isinstance(arguments, dict):
                raise AgentRuntimeError(f"工具参数必须是对象：{function_name}")
            requests.append(
                {
                    "protocol": "tool_calls",
                    "tool": normalize_tool_name(function_name),
                    "input": arguments,
                    "tool_call_id": str(call.get("id") or f"call_{index}"),
                    "function_name": function_name,
                }
            )
        return requests

    def parse_json_fallback(self, content: str) -> dict[str, Any] | None:
        clean = content.strip()
        if clean.startswith("```"):
            clean = re.sub(r"^```(?:json)?\s*|\s*```$", "", clean, flags=re.DOTALL).strip()
        try:
            payload = json.loads(clean)
        except json.JSONDecodeError:
            return None
        if not isinstance(payload, dict):
            return None
        if payload.get("action") == "tool" and payload.get("tool"):
            payload["protocol"] = "json_fallback"
            payload["tool"] = normalize_tool_name(payload.get("tool"))
            if not isinstance(payload.get("input"), dict):
                payload["input"] = {}
            return payload
        return None
