"""Tests for tool request parsing split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.tool_requests import (
    MAX_AGENT_TOOL_ITERATIONS,
    ToolRequestParser,
    normalize_tool_iteration,
    normalize_tool_name,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_tool_request_parser_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.ToolRequestParser is ToolRequestParser
    assert agent_runtime._normalize_tool_name is normalize_tool_name
    assert agent_runtime._normalize_tool_iteration is normalize_tool_iteration
    assert agent_runtime._MAX_AGENT_TOOL_ITERATIONS == MAX_AGENT_TOOL_ITERATIONS


def test_tool_request_parser_parses_native_tool_calls_and_aliases() -> None:
    parser = ToolRequestParser()

    requests = parser.parse_tool_calls(
        [
            "ignore",
            {"function": {"name": ""}},
            {
                "id": "call_read",
                "function": {"name": "workspace_read", "arguments": '{"path": "README.md"}'},
            },
            {
                "function": {"name": "memory_add", "arguments": {"content": "Remember", "kind": "fact"}},
            },
        ]
    )

    assert normalize_tool_name("workspace_read") == "workspace.read"
    assert requests == [
        {
            "protocol": "tool_calls",
            "tool": "workspace.read",
            "input": {"path": "README.md"},
            "tool_call_id": "call_read",
            "function_name": "workspace_read",
        },
        {
            "protocol": "tool_calls",
            "tool": "memory.add",
            "input": {"content": "Remember", "kind": "fact"},
            "tool_call_id": "call_3",
            "function_name": "memory_add",
        },
    ]


def test_tool_request_normalizes_iteration_bounds() -> None:
    assert normalize_tool_iteration(None) == 0
    assert normalize_tool_iteration("bad") == 0
    assert normalize_tool_iteration(-1) == 0
    assert normalize_tool_iteration(7) == 7
    assert normalize_tool_iteration(999) == MAX_AGENT_TOOL_ITERATIONS


def test_tool_request_parser_rejects_invalid_native_arguments() -> None:
    parser = ToolRequestParser()

    with pytest.raises(AgentRuntimeError, match="不是合法 JSON"):
        parser.parse_tool_calls([{"function": {"name": "workspace_read", "arguments": "{"}}])
    with pytest.raises(AgentRuntimeError, match="格式无效"):
        parser.parse_tool_calls([{"function": {"name": "workspace_read", "arguments": ["README.md"]}}])
    with pytest.raises(AgentRuntimeError, match="必须是对象"):
        parser.parse_tool_calls([{"function": {"name": "workspace_read", "arguments": '"README.md"'}}])


def test_tool_request_parser_parses_json_fallback_and_prefers_native_calls() -> None:
    parser = ToolRequestParser()
    fallback_content = """```json
{"action":"tool","tool":"artifact_write","input":{"path":"report.md","content":"ok"}}
```"""

    fallback = parser.parse_json_fallback(fallback_content)
    from_message = parser.requests_from_message(
        {
            "tool_calls": [
                {
                    "id": "call_native",
                    "function": {"name": "workspace_read", "arguments": '{"path":"README.md"}'},
                }
            ]
        },
        fallback_content,
    )

    assert fallback == {
        "action": "tool",
        "tool": "artifact.write",
        "input": {"path": "report.md", "content": "ok"},
        "protocol": "json_fallback",
    }
    assert parser.parse_json_fallback('{"action":"tool","tool":"workspace_read","input":"bad"}') == {
        "action": "tool",
        "tool": "workspace.read",
        "input": {},
        "protocol": "json_fallback",
    }
    assert parser.parse_json_fallback("not json") is None
    assert parser.parse_json_fallback('["not", "object"]') is None
    assert from_message == [
        {
            "protocol": "tool_calls",
            "tool": "workspace.read",
            "input": {"path": "README.md"},
            "tool_call_id": "call_native",
            "function_name": "workspace_read",
        }
    ]


def test_native_runtime_uses_split_tool_request_parser(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        assert isinstance(service.tool_request_parser, ToolRequestParser)
        assert service._parse_tool_calls(
            [{"id": "call_read", "function": {"name": "workspace_read", "arguments": '{"path":"README.md"}'}}]
        )[0]["tool"] == "workspace.read"
        assert service._parse_tool_request('{"action":"tool","tool":"workspace_read"}')["input"] == {}
    finally:
        service.close()
