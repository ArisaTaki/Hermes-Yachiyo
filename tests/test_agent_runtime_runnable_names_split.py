"""Tests for runnable name lookup split out of the legacy runtime."""

from __future__ import annotations

import sqlite3

from apps.shell import agent_runtime
from apps.shell.agent.runtime.runnable_names import RuntimeRunnableNameResolver
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _connect_runnable_names_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE workflows (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        INSERT INTO agents (agent_id, name) VALUES ('agent_1', 'Research');
        INSERT INTO workflows (workflow_id, name) VALUES ('workflow_1', 'Release Flow');
        """
    )
    return conn


def test_runtime_runnable_name_resolver_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRunnableNameResolver is RuntimeRunnableNameResolver


def test_runtime_runnable_name_resolver_returns_agent_workflow_and_main_chat_names() -> None:
    resolver = RuntimeRunnableNameResolver(
        _connect_runnable_names_db(),
        ensure_row_factory=lambda: None,
        main_chat_agent_id="builtin:yachiyo-main",
    )

    assert resolver.resolve("main_chat_run", "builtin:yachiyo-main") == "Yachiyo"
    assert resolver.resolve("agent_run", "agent_1") == "Research"
    assert resolver.resolve("workflow_run", "workflow_1") == "Release Flow"
    assert resolver.resolve("agent_run", "missing") == ""
    assert resolver.resolve("unknown", "agent_1") == ""


def test_native_runtime_installs_runnable_name_resolver(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runnable_name_resolver, RuntimeRunnableNameResolver)
        assert service._runnable_name("main_chat_run", "builtin:yachiyo-main") == "Yachiyo"
    finally:
        service.close()
