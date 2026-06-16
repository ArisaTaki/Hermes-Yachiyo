"""Tests for runtime foundation setup split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.row_projections import RuntimeRowProjector
from apps.shell.agent.runtime.definition_names import RuntimeDefinitionNameGuard
from apps.shell.agent.runtime.foundation import (
    RuntimeFoundationSetup,
    build_runtime_foundation_setup,
)
from apps.shell.agent.runtime.recorders import RuntimeRecorderBundle
from apps.shell.agent.runtime.run_requests import RuntimeRunRequestParser
from apps.shell.agent.runtime.run_status import RuntimeTerminalRunResolver
from apps.shell.agent.runtime.runnable_names import RuntimeRunnableNameResolver
from apps.shell.agent.runtime.schema import RuntimeSchemaService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_foundation_setup_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeFoundationSetup is RuntimeFoundationSetup
    assert agent_runtime._build_runtime_foundation_setup is build_runtime_foundation_setup


def test_build_runtime_foundation_setup_wires_foundation_collaborators(tmp_path: Path) -> None:
    credential_store = MemoryCredentialStore()
    events: list[tuple[str, str, dict[str, Any]]] = []
    setup = build_runtime_foundation_setup(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=credential_store,
        default_tool_policy=lambda _category: {"allowed_tools": []},
        default_workspace_policy=lambda: {},
        compile_tool_policy=lambda _category, policy: dict(policy),
        compile_workspace_policy=lambda policy: dict(policy),
        read_credential=lambda _credential_ref: "",
        task_run_link_for_run=lambda _run_id: None,
        run_group_source=lambda _run_group_id: "",
        runnable_name=lambda _kind, _runnable_id: "",
        ensure_row_factory=lambda: None,
        append_run_event=lambda run_id, event_type, payload: events.append(
            (run_id, event_type, payload)
        ),
        get_run=lambda run_id: {"run_id": run_id, "status": "completed"},
    )
    try:
        assert isinstance(setup, RuntimeFoundationSetup)
        assert setup.engine_state.workspace_dir == tmp_path / "runtime"
        assert isinstance(setup.runtime_schema, RuntimeSchemaService)
        assert isinstance(setup.row_projector, RuntimeRowProjector)
        assert isinstance(setup.definition_name_guard, RuntimeDefinitionNameGuard)
        assert isinstance(setup.runnable_name_resolver, RuntimeRunnableNameResolver)
        assert isinstance(setup.run_request_parser, RuntimeRunRequestParser)
        assert isinstance(setup.terminal_run_resolver, RuntimeTerminalRunResolver)
        assert isinstance(setup.recorders, RuntimeRecorderBundle)
        assert setup.terminal_run_resolver.terminal_run_or_none("run-1") == {
            "run_id": "run-1",
            "status": "completed",
        }
        setup.recorders.runtime_agent_run_events.completed("run-1", "ok")
        assert events[0][1] == "agent.run.completed"
    finally:
        setup.engine_state.conn.close()
        credential_store.close()
