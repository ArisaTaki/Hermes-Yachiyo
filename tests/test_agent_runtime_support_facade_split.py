"""Tests for runtime support facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.support_facade import RuntimeSupportFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_support_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeSupportFacadeMixin is RuntimeSupportFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeSupportFacadeMixin)
    for method_name in (
        "_timeline",
        "_run_budget",
        "_check_context_budget",
        "_limit_model_output",
        "_limit_tool_result",
    ):
        assert method_name not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_support_facade_methods_available_after_split(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        service.runtime_limits = RunBudgetLimits(
            max_context_chars=10,
            max_model_output_chars=5,
            max_tool_output_chars=4,
        )
        timeline_event = service._timeline(
            "agent.tool.call",
            "api_key=sk-secret123456",
            payload={"api_key": "sk-secret123456"},
        )
        budget = service._run_budget("", [])
        limited_model, model_truncated = service._limit_model_output("abcdefghi")
        limited_tool = service._limit_tool_result({"ok": True, "content": "abcdef"})

        assert timeline_event["event"] == "agent.tool.call"
        assert "sk-secret123456" not in str(timeline_event)
        assert budget.model_calls_used == service.runtime_run_budget("", []).model_calls_used
        with pytest.raises(agent_runtime.AgentRuntimeError, match="max_context_chars=10"):
            service._check_context_budget(
                budget,
                [{"role": "user", "content": "this context is too long"}],
            )
        assert limited_model == "abcde"
        assert model_truncated is True
        assert limited_tool["content"] == "abcd"
        assert limited_tool["truncated"] is True
    finally:
        service.close()
