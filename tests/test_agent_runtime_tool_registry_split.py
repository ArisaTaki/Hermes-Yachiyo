"""Tests for the split ToolBroker dispatch registry."""

from __future__ import annotations

import pytest

from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import KNOWN_AGENT_TOOLS
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY, dispatch_tool_call


def _broker(tmp_path):
    return ToolBroker(
        {"default_workdir": str(tmp_path), "readable_scopes": ["."], "writable_scopes": ["."]},
        tmp_path / "artifacts",
    )


def test_tool_dispatch_registry_covers_known_agent_tools() -> None:
    assert set(TOOL_DISPATCH_REGISTRY) == KNOWN_AGENT_TOOLS


def test_tool_broker_call_uses_split_registry_for_workspace_read(tmp_path) -> None:
    (tmp_path / "note.txt").write_text("hello", encoding="utf-8")
    broker = _broker(tmp_path)

    assert broker.call("workspace.read", {"path": "note.txt"}) == {
        "ok": True,
        "path": "note.txt",
        "content": "hello",
    }


def test_tool_dispatch_registry_keeps_terminal_approval_gate(tmp_path) -> None:
    broker = _broker(tmp_path)

    result = broker.call("terminal.run", {"command": "printf blocked", "approved": True})

    assert result["ok"] is False
    assert result["approval_required"] is True
    assert result["tool"] == "terminal.run"
    assert result["input_preview"] == {"command": "printf blocked", "shell": False}


def test_tool_dispatch_registry_rejects_unknown_tool(tmp_path) -> None:
    with pytest.raises(AgentRuntimeError, match="未知工具"):
        dispatch_tool_call(_broker(tmp_path), "unknown.tool", {})
