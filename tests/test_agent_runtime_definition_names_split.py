"""Tests for Agent/Workflow name validation split out of the legacy runtime."""

from __future__ import annotations

import sqlite3

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.definition_names import RuntimeDefinitionNameGuard
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _connect_definition_names_db() -> sqlite3.Connection:
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
        INSERT INTO agents (agent_id, name) VALUES ('agent_1', 'Planner');
        INSERT INTO workflows (workflow_id, name) VALUES ('workflow_1', 'Release Flow');
        """
    )
    return conn


def test_runtime_definition_name_guard_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeDefinitionNameGuard is RuntimeDefinitionNameGuard


def test_runtime_definition_name_guard_rejects_empty_reserved_and_duplicate_names() -> None:
    guard = RuntimeDefinitionNameGuard(
        _connect_definition_names_db(),
        ensure_row_factory=lambda: None,
        error_type=AgentRuntimeError,
    )

    with pytest.raises(AgentRuntimeError, match="名称不能为空"):
        guard.ensure_available("  ")
    with pytest.raises(AgentRuntimeError, match="系统 Agent 名称"):
        guard.ensure_available("Yachiyo")
    with pytest.raises(AgentRuntimeError, match="名称必须全局唯一"):
        guard.ensure_available("planner")
    with pytest.raises(AgentRuntimeError, match="名称必须全局唯一"):
        guard.ensure_available("release flow")


def test_runtime_definition_name_guard_allows_current_agent_or_workflow_name() -> None:
    guard = RuntimeDefinitionNameGuard(
        _connect_definition_names_db(),
        ensure_row_factory=lambda: None,
        error_type=AgentRuntimeError,
    )

    guard.ensure_available("Planner", ignore_agent_id="agent_1")
    guard.ensure_available("Release Flow", ignore_workflow_id="workflow_1")
    guard.ensure_available("New Name")


def test_native_runtime_installs_definition_name_guard(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.definition_name_guard, RuntimeDefinitionNameGuard)
    finally:
        service.close()
