"""Tests for runtime shutdown orchestration split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.shutdown import RuntimeShutdownService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class _FakeCursor:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self._rows = rows

    def fetchall(self) -> list[dict[str, Any]]:
        return self._rows


class _FakeConnection:
    def __init__(self, rows: list[dict[str, Any]]) -> None:
        self.rows = rows
        self.executed_sql: list[str] = []
        self.commits = 0
        self.closes = 0

    def execute(self, sql: str) -> _FakeCursor:
        self.executed_sql.append(sql)
        return _FakeCursor(self.rows)

    def commit(self) -> None:
        self.commits += 1

    def close(self) -> None:
        self.closes += 1


class _FakeCredentialStore:
    def __init__(self) -> None:
        self.closes = 0

    def close(self) -> None:
        self.closes += 1


def test_runtime_shutdown_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeShutdownService is RuntimeShutdownService


def test_runtime_shutdown_service_cancels_active_runs_and_keeps_db_open() -> None:
    conn = _FakeConnection([{"run_id": "run-2"}, {"run_id": "run-1"}])
    credential_store = _FakeCredentialStore()
    calls: list[str] = []
    state = {"closed": False, "accepting": True}

    def cancel_run(run_id: str) -> dict[str, Any]:
        calls.append(run_id)
        if run_id == "run-2":
            raise RuntimeError("already gone")
        return {"run_id": run_id, "status": "cancelled"}

    service = RuntimeShutdownService(
        conn=conn,
        credential_store=credential_store,
        is_closed=lambda: state["closed"],
        mark_not_accepting=lambda: state.update(accepting=False),
        mark_closed=lambda: state.update(closed=True),
        cancel_terminal_process_groups=lambda: calls.append("terminal.cancel"),
        ensure_row_factory=lambda: calls.append("row_factory"),
        cancel_run=cancel_run,
    )

    service.shutdown(close_db=False)

    assert state == {"closed": False, "accepting": False}
    assert calls == ["terminal.cancel", "row_factory", "run-2", "run-1"]
    assert conn.commits == 1
    assert conn.closes == 0
    assert credential_store.closes == 0
    assert "status NOT IN" in conn.executed_sql[0]


def test_runtime_shutdown_service_closes_resources_when_requested() -> None:
    conn = _FakeConnection([])
    credential_store = _FakeCredentialStore()
    state = {"closed": False, "accepting": True}

    service = RuntimeShutdownService(
        conn=conn,
        credential_store=credential_store,
        is_closed=lambda: state["closed"],
        mark_not_accepting=lambda: state.update(accepting=False),
        mark_closed=lambda: state.update(closed=True),
        cancel_terminal_process_groups=lambda: None,
        ensure_row_factory=lambda: None,
        cancel_run=lambda _run_id: {},
    )

    service.shutdown(close_db=True)

    assert state == {"closed": True, "accepting": False}
    assert conn.commits == 1
    assert conn.closes == 1
    assert credential_store.closes == 1


def test_runtime_shutdown_service_returns_when_already_closed() -> None:
    conn = _FakeConnection([{"run_id": "run-1"}])
    credential_store = _FakeCredentialStore()

    service = RuntimeShutdownService(
        conn=conn,
        credential_store=credential_store,
        is_closed=lambda: True,
        mark_not_accepting=lambda: (_ for _ in ()).throw(AssertionError("closed")),
        mark_closed=lambda: (_ for _ in ()).throw(AssertionError("closed")),
        cancel_terminal_process_groups=lambda: (_ for _ in ()).throw(AssertionError("closed")),
        ensure_row_factory=lambda: (_ for _ in ()).throw(AssertionError("closed")),
        cancel_run=lambda _run_id: {},
    )

    service.shutdown()

    assert conn.executed_sql == []
    assert conn.commits == 0
    assert conn.closes == 0
    assert credential_store.closes == 0


def test_native_runtime_installs_shutdown_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runtime_shutdown, RuntimeShutdownService)
    finally:
        service.close()
