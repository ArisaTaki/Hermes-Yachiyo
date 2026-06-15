"""Tests for terminal Run status lookup split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.runtime.run_status import RuntimeTerminalRunResolver
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_terminal_run_resolver_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeTerminalRunResolver is RuntimeTerminalRunResolver


def test_terminal_run_resolver_returns_only_final_runs() -> None:
    runs = {
        "done": {"run_id": "done", "status": "completed"},
        "active": {"run_id": "active", "status": "running"},
    }
    resolver = RuntimeTerminalRunResolver(
        get_run=lambda run_id: runs[run_id],
        final_statuses={"completed", "failed", "cancelled"},
    )

    assert resolver.terminal_run_or_none("done") == runs["done"]
    assert resolver.terminal_run_or_none("active") is None
    assert resolver.terminal_run_or_none("missing") is None


def test_native_runtime_uses_split_terminal_run_resolver(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.terminal_run_resolver, RuntimeTerminalRunResolver)
        assert service.main_chat_model._terminal_run_or_none.__self__ is service.terminal_run_resolver
        assert service.main_chat_model_loop._terminal_run_or_none.__self__ is service.terminal_run_resolver
    finally:
        service.close()
