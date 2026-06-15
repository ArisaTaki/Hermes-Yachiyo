"""Tests for tool operation facade split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_tool_operations_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeToolOperations is RuntimeToolOperations


def test_native_runtime_installs_split_tool_operations(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.tool_operations, RuntimeToolOperations)
        assert service.tool_operations._tool_request_runner is service.tool_request_runner
        assert service.tool_operations._tool_call_executor is service.tool_call_executor
        assert service._parse_tool_request('{"action":"tool","tool":"workspace_read"}')["tool"] == "workspace.read"
    finally:
        service.close()


def test_runtime_tool_operations_delegates_runner_and_executor() -> None:
    runner = FakeToolRequestRunner()
    executor = FakeToolCallExecutor()
    operations = RuntimeToolOperations(
        tool_request_runner=runner,
        tool_call_executor=executor,
    )
    broker = object()
    messages: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []
    artifacts: list[dict[str, Any]] = []

    operations.run_tool_requests(
        [{"tool": "workspace.read"}],
        ["workspace.read"],
        broker,
        messages,
        timeline,
        artifacts,
        next_iteration=2,
        run_id="run-1",
        budget="budget",
    )
    result = operations.call_agent_tool(
        {"tool": "workspace.read", "input": {"path": "README.md"}},
        ["workspace.read"],
        broker,
        timeline,
        artifacts=artifacts,
        approved=True,
        run_id="run-1",
        budget="budget",
    )

    assert runner.calls == [
        {
            "tool_requests": [{"tool": "workspace.read"}],
            "allowed_tools": ["workspace.read"],
            "broker": broker,
            "messages": messages,
            "timeline": timeline,
            "artifacts": artifacts,
            "next_iteration": 2,
            "run_id": "run-1",
            "budget": "budget",
        }
    ]
    assert executor.calls == [
        {
            "tool_request": {"tool": "workspace.read", "input": {"path": "README.md"}},
            "allowed_tools": ["workspace.read"],
            "broker": broker,
            "timeline": timeline,
            "artifacts": artifacts,
            "approved": True,
            "run_id": "run-1",
            "budget": "budget",
        }
    ]
    assert result == {"ok": True, "tool": "workspace.read"}


def test_runtime_tool_operations_static_helpers_match_legacy_contracts() -> None:
    tool_calls = [
        {
            "id": "call-1",
            "function": {
                "name": "workspace_read",
                "arguments": '{"path":"README.md"}',
            },
        }
    ]
    pending = RuntimeToolOperations.build_pending_approval(
        {"tool": "terminal_run", "input": {"command": "printf ok"}},
        messages=[],
        next_iteration=3,
        remaining_tool_requests=[],
        now=lambda: "2026-06-15T10:00:00Z",
    )

    assert RuntimeToolOperations.parse_tool_calls(tool_calls)[0]["tool"] == "workspace.read"
    assert RuntimeToolOperations.parse_tool_request('{"action":"tool","tool":"artifact_write"}')["tool"] == "artifact.write"
    assert RuntimeToolOperations.model_tool_schemas(["workspace.read"])[0]["function"]["name"] == "workspace_read"
    assert pending["tool"] == "terminal.run"
    assert pending["next_iteration"] == 3
    RuntimeToolOperations.validate_tool_payload("workspace.write_patch", {"path": "src/out.txt", "patch": "*** patch"})
    with pytest.raises(AgentRuntimeError, match="未声明字段"):
        RuntimeToolOperations.validate_tool_payload(
            "workspace.write_patch",
            {"path": "src/out.txt", "patch": "*** patch", "approved": True},
        )


class FakeToolRequestRunner:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(
        self,
        tool_requests,
        allowed_tools,
        broker,
        messages,
        timeline,
        artifacts,
        **kwargs,
    ) -> None:
        self.calls.append(
            {
                "tool_requests": tool_requests,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "messages": messages,
                "timeline": timeline,
                "artifacts": artifacts,
                **kwargs,
            }
        )


class FakeToolCallExecutor:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def execute(
        self,
        tool_request,
        allowed_tools,
        broker,
        timeline,
        **kwargs,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tool_request": tool_request,
                "allowed_tools": allowed_tools,
                "broker": broker,
                "timeline": timeline,
                **kwargs,
            }
        )
        return {"ok": True, "tool": str(tool_request.get("tool") or "")}
