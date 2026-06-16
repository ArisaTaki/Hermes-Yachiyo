"""Tests for Tool facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.tool_facade import RuntimeToolFacadeMixin
from apps.shell.agent.runtime.tool_loop import (
    append_tool_result_message,
    assistant_message_for_history,
    fatal_tool_failure_detail,
    tool_loop_limit_artifact_completion,
    tool_loop_limit_detail,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_tool_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeToolFacadeMixin is RuntimeToolFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeToolFacadeMixin)
    for method_name in (
        "_tool_loop_limit_detail",
        "_tool_loop_limit_artifact_completion",
        "_fatal_tool_failure_detail",
        "_assistant_message_for_history",
        "_append_tool_result_message",
        "_run_tool_requests",
        "_call_agent_tool",
        "_make_pending_approval",
        "_tool_requests_from_message",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_tool_facade_static_helpers_available_after_split() -> None:
    timeline = [
        {"event": "agent.tool.started", "detail": "read"},
        {"event": "agent.tool.failed", "detail": "boom"},
    ]
    artifacts = [{"artifact_id": "artifact-1", "path": "result.md"}]
    tool_request = {"tool": "workspace.read", "input": {"path": "README.md"}}
    terminal_result = {"ok": False, "error": "failed", "fatal": True}
    assistant_message = {
        "role": "assistant",
        "content": "done",
        "tool_calls": [{"id": "call-1", "function": {"name": "workspace_read", "arguments": "{}"}}],
    }
    messages: list[dict[str, Any]] = [assistant_message_for_history(assistant_message)]

    agent_runtime.NativeRunEngine._append_tool_result_message(
        messages,
        {"tool_call_id": "call-1", "tool": "workspace.read"},
        {"ok": True, "content": "file"},
    )

    assert agent_runtime.NativeRunEngine._tool_loop_limit_detail(timeline) == tool_loop_limit_detail(timeline)
    assert agent_runtime.NativeRunEngine._tool_loop_limit_artifact_completion(
        timeline,
        artifacts,
    ) == tool_loop_limit_artifact_completion(timeline, artifacts)
    assert agent_runtime.NativeRunEngine._fatal_tool_failure_detail(
        "workspace.read",
        tool_request,
        terminal_result,
    ) == fatal_tool_failure_detail("workspace.read", tool_request, terminal_result)
    assert agent_runtime.NativeRunEngine._assistant_message_for_history(
        assistant_message,
    ) == assistant_message_for_history(assistant_message)
    expected_messages = [assistant_message_for_history(assistant_message)]
    append_tool_result_message(
        expected_messages,
        {"tool_call_id": "call-1", "tool": "workspace.read"},
        {"ok": True, "content": "file"},
    )
    assert messages == expected_messages


def test_native_runtime_keeps_tool_facade_operations_available_after_split(tmp_path: Path) -> None:
    calls: list[tuple[str, Any]] = []

    class _ToolOperations:
        @staticmethod
        def run_tool_requests(
            tool_requests: list[dict[str, Any]],
            allowed_tools: list[str],
            broker: Any,
            messages: list[dict[str, Any]],
            timeline: list[dict[str, Any]],
            artifacts: list[dict[str, Any]],
            **kwargs: Any,
        ) -> None:
            calls.append(("run-requests", tool_requests, allowed_tools, broker, messages, timeline, artifacts, kwargs))

        @staticmethod
        def call_agent_tool(
            tool_request: dict[str, Any],
            allowed_tools: list[str],
            broker: Any,
            timeline: list[dict[str, Any]],
            **kwargs: Any,
        ) -> dict[str, Any]:
            calls.append(("call-tool", tool_request, allowed_tools, broker, timeline, kwargs))
            return {"ok": True, "content": "tool result"}

        @staticmethod
        def tool_requests_from_message(message: dict[str, Any], content: str) -> list[dict[str, Any]]:
            calls.append(("parse-requests", message, content))
            return [{"tool": "workspace.read", "input": {}}]

    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        service.tool_operations = _ToolOperations()
        tool_requests = [{"tool": "workspace.read", "input": {"path": "README.md"}}]
        allowed_tools = ["workspace.read"]
        broker = {"broker": True}
        messages = [{"role": "user", "content": "read"}]
        timeline = [{"event": "agent.run.started"}]
        artifacts = [{"artifact_id": "artifact-1"}]

        service._run_tool_requests(
            tool_requests,
            allowed_tools,
            broker,
            messages,
            timeline,
            artifacts,
            next_iteration=2,
            run_id="run-1",
            budget="budget",
        )
        assert service._call_agent_tool(
            tool_requests[0],
            allowed_tools,
            broker,
            timeline,
            artifacts=artifacts,
            approved=True,
            run_id="run-1",
            budget="budget",
        ) == {"ok": True, "content": "tool result"}
        assert service._tool_requests_from_message(
            {"role": "assistant", "content": "use tool"},
            "use tool",
        ) == [{"tool": "workspace.read", "input": {}}]

        pending = service._make_pending_approval(
            tool_requests[0],
            messages=messages,
            next_iteration=3,
            remaining_tool_requests=[],
        )

        assert pending["tool"] == "workspace.read"
        assert pending["next_iteration"] == 3
        assert calls == [
            (
                "run-requests",
                tool_requests,
                allowed_tools,
                broker,
                messages,
                timeline,
                artifacts,
                {"next_iteration": 2, "run_id": "run-1", "budget": "budget"},
            ),
            (
                "call-tool",
                tool_requests[0],
                allowed_tools,
                broker,
                timeline,
                {"artifacts": artifacts, "approved": True, "run_id": "run-1", "budget": "budget"},
            ),
            ("parse-requests", {"role": "assistant", "content": "use tool"}, "use tool"),
        ]
    finally:
        service.close()
