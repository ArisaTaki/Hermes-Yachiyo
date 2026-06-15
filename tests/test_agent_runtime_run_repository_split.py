"""Tests for the RunRepository split out of agent_runtime."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_json_value


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": str(row["run_id"]),
        "run_group_id": str(row["run_group_id"] or ""),
        "client_request_id": str(row["client_request_id"] or ""),
        "kind": str(row["kind"]),
        "runnable_id": str(row["runnable_id"]),
        "status": str(row["status"]),
        "user_goal": str(row["user_goal"] or ""),
        "result": str(row["result"] or ""),
        "timeline": _json_load(row["timeline_json"], []),
        "artifacts": _json_load(row["artifacts_json"], []),
        "pending_approval": _json_load(row["pending_approval_json"], {}),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _connect_runs_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE run_groups (
            run_group_id TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            run_group_id TEXT NOT NULL DEFAULT '',
            client_request_id TEXT NOT NULL DEFAULT '',
            kind TEXT NOT NULL,
            runnable_id TEXT NOT NULL,
            status TEXT NOT NULL,
            user_goal TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            timeline_json TEXT NOT NULL DEFAULT '[]',
            artifacts_json TEXT NOT NULL DEFAULT '[]',
            pending_approval_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_run_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.RunRepository is RunRepository


def test_run_repository_insert_update_idempotency_and_delete() -> None:
    conn = _connect_runs_db()
    appended: list[tuple[str, str]] = []
    synced: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    now_values = iter(["2026-06-14T10:00:00Z", "2026-06-14T10:01:00Z"])
    unset = object()
    repo = RunRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run=_row_to_run,
        accepting_runs=lambda: True,
        sync_projections=lambda run_id, status, artifacts, pending_approval: synced.append(
            (run_id, status, artifacts, pending_approval),
        ),
        append_run_to_group=lambda group_id, run_id: appended.append((group_id, run_id)),
        now=lambda: next(now_values),
        json_dump=_json_dump,
        json_load=_json_load,
        redact_secrets=lambda value: str(value).replace("secret", "[redacted]"),
        redact_json_value=redact_json_value,
        contains_sensitive_text=lambda value: "sk-" in value,
        error_type=AgentRuntimeError,
        unset_sentinel=unset,
    )

    run = repo.insert(
        kind="agent_run",
        runnable_id="agent-1",
        user_goal="keep secret out",
        run_group_id="group-1",
        client_request_id="request-1",
    )
    assert run["status"] == "running"
    assert run["user_goal"] == "keep [redacted] out"
    assert appended == [("group-1", run["run_id"])]
    assert repo.by_client_request_id("request-1")["idempotent"] is True  # type: ignore[index]

    updated = repo.update(
        run["run_id"],
        status="approval_required",
        result="result secret",
        timeline=[{"event": "agent.tool.approval_required"}],
        artifacts=[{"path": "artifact.md"}],
        pending_approval={"tool": "terminal.run"},
    )
    assert updated["status"] == "approval_required"
    assert updated["result"] == "result [redacted]"
    assert updated["pending_approval"] == {"tool": "terminal.run"}
    assert repo.pending_approval_private(run["run_id"]) == {"tool": "terminal.run"}
    assert synced == [
        (
            run["run_id"],
            "approval_required",
            [{"path": "artifact.md"}],
            {"tool": "terminal.run"},
        )
    ]

    deleted = repo.delete_rows([updated], delete_artifacts=lambda item: item.update(deleted=True))
    assert deleted == [run["run_id"]]
    assert conn.execute("SELECT COUNT(*) AS count FROM runs").fetchone()["count"] == 0


def test_run_repository_rejects_sensitive_client_request_ids() -> None:
    conn = _connect_runs_db()
    repo = RunRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run=_row_to_run,
        accepting_runs=lambda: True,
        sync_projections=lambda **_: None,
        append_run_to_group=lambda *_: None,
        now=lambda: "2026-06-14T10:00:00Z",
        json_dump=_json_dump,
        json_load=_json_load,
        redact_secrets=str,
        redact_json_value=redact_json_value,
        contains_sensitive_text=lambda value: "sk-" in value,
        error_type=AgentRuntimeError,
    )

    try:
        repo.insert(
            kind="agent_run",
            runnable_id="agent-1",
            user_goal="goal",
            client_request_id="sk-secret",
        )
    except AgentRuntimeError as exc:
        assert "client_request_id" in str(exc)
    else:
        raise AssertionError("sensitive client_request_id should be rejected")
