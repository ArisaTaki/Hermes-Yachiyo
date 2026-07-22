"""Tests for runtime shutdown orchestration split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime import installation_facade as installation_facade_module
from apps.shell.agent.runtime.run_cancellation import RuntimeRunCancellationService
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


def test_runtime_shutdown_reuses_cancel_once_browser_cleanup_without_duplicates() -> None:
    conn = _FakeConnection([{"run_id": "run-browser"}])
    credential_store = _FakeCredentialStore()
    state = {"closed": False}
    runs = {
        "run-browser": {
            "run_id": "run-browser",
            "kind": "agent_run",
            "status": "running",
            "result": "",
            "timeline": [],
        }
    }
    cleanup_calls: list[str] = []

    def update_run(run_id: str, **kwargs: Any) -> dict[str, Any]:
        runs[run_id] = {**runs[run_id], **kwargs}
        return runs[run_id]

    cancellation = RuntimeRunCancellationService(
        get_run=lambda run_id: runs[run_id],
        update_run=update_run,
        append_run_event=lambda *_args, **_kwargs: None,
        timeline_factory=lambda event, detail="", **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        workflow_cancellation=object(),
        workflow_run_is_group_root=lambda _run: False,
        project_cancelled_workflow_group_if_root=lambda *_args: {},
        resume_parent_workflows_after_child_update=lambda *_args: None,
        project_child_run_transition=lambda result: result,
        final_statuses={"completed", "failed", "cancelled"},
        close_run_owned_browser_target=lambda run: cleanup_calls.append(run["run_id"]),
    )
    shutdown = RuntimeShutdownService(
        conn=conn,
        credential_store=credential_store,
        is_closed=lambda: state["closed"],
        mark_not_accepting=lambda: None,
        mark_closed=lambda: state.update(closed=True),
        cancel_terminal_process_groups=lambda: None,
        ensure_row_factory=lambda: None,
        cancel_run=cancellation.cancel_once,
    )

    shutdown.shutdown(close_db=False)
    shutdown.shutdown(close_db=False)

    assert runs["run-browser"]["status"] == "cancelled"
    assert cleanup_calls == ["run-browser"]
    assert conn.commits == 2


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


def test_runtime_shutdown_releases_owned_desktop_provider_only_when_closing() -> None:
    conn = _FakeConnection([])
    credential_store = _FakeCredentialStore()
    releases: list[str] = []
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
        release_desktop_provider_session_owner=lambda: releases.append("released"),
    )

    service.shutdown(close_db=False)

    assert releases == []

    service.shutdown(close_db=True)
    service.shutdown(close_db=True)

    assert releases == ["released"]


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


def test_native_runtime_provider_owner_tokens_are_isolated_and_released_once(
    tmp_path,
    monkeypatch,
) -> None:
    released: list[str] = []
    monkeypatch.setattr(
        installation_facade_module,
        "_release_desktop_provider_session_owner",
        lambda owner_token: released.append(owner_token) or {},
    )
    first = AgentRuntimeService(
        db_path=tmp_path / "first.db",
        workspace_dir=tmp_path / "first-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    second = AgentRuntimeService(
        db_path=tmp_path / "second.db",
        workspace_dir=tmp_path / "second-runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    first_token = first._desktop_provider_session_owner_token
    second_token = second._desktop_provider_session_owner_token

    try:
        assert first_token != second_token

        first.close()
        first.close()

        assert released == [first_token]

        second.close()

        assert released == [first_token, second_token]
    finally:
        first.close()
        second.close()
