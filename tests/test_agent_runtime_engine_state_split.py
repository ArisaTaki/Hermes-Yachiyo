"""Tests for native runtime engine state setup split out of the legacy runtime."""

from __future__ import annotations

from apps.shell import agent_runtime
from apps.shell.agent.repositories.sqlite import LockedConnection, named_row_factory
from apps.shell.agent.runtime.budget import RunBudgetLimits
from apps.shell.agent.runtime.engine_state import RuntimeEngineStateBundle, build_runtime_engine_state
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_engine_state_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeEngineStateBundle is RuntimeEngineStateBundle


def test_build_runtime_engine_state_creates_layout_locks_limits_and_connection(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    state = build_runtime_engine_state(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=credential_store,
    )
    try:
        assert isinstance(state, RuntimeEngineStateBundle)
        assert state.workspace_dir == tmp_path / "runtime"
        assert state.db_path == tmp_path / "agent-runtime.db"
        assert state.credential_store is credential_store
        assert state.skills_dir == tmp_path / "runtime" / "skills"
        assert state.skill_installs_dir == tmp_path / "runtime" / "skill-installs"
        assert state.skill_installs_native_home == tmp_path / "runtime" / "skill-installs" / "native-home"
        assert state.agent_artifacts_dir == tmp_path / "runtime" / "artifacts" / "agent-runs"
        assert state.workflow_artifacts_dir == tmp_path / "runtime" / "artifacts" / "workflow-runs"
        assert state.agent_workspaces_dir == tmp_path / "runtime" / "workspaces" / "agents"
        assert state.accepting_runs is True
        assert state.closed is False
        assert isinstance(state.runtime_limits, RunBudgetLimits)
        assert state.approval_execution_in_progress == set()
        assert state.run_cancel_locks == {}
        assert isinstance(state.conn, LockedConnection)
        assert state.conn.row_factory is named_row_factory
        assert hasattr(state.db_lock, "acquire")
        assert hasattr(state.approval_execution_lock, "acquire")
        assert hasattr(state.run_cancel_locks_guard, "acquire")
    finally:
        state.conn.close()
        credential_store.close()


def test_native_runtime_installs_engine_state_under_legacy_attribute_names(tmp_path) -> None:
    credential_store = MemoryCredentialStore()
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=credential_store,
        seed_templates=False,
    )
    try:
        assert service.workspace_dir == tmp_path / "runtime"
        assert service.db_path == tmp_path / "agent-runtime.db"
        assert service._credential_store is credential_store
        assert isinstance(service.runtime_limits, RunBudgetLimits)
        assert service._accepting_runs is True
        assert service._closed is False
        assert service._approval_execution_in_progress == set()
        assert service._run_cancel_locks == {}
        assert isinstance(service._conn, LockedConnection)
        assert service._conn.row_factory is named_row_factory
    finally:
        service.close()
