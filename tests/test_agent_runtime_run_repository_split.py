"""Tests for the RunRepository split out of agent_runtime."""

from __future__ import annotations

import json
import sqlite3
import threading
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.repositories.sqlite import (
    named_row_factory,
    open_locked_runtime_connection,
)
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.events import redact_json_value
from apps.shell.agent.runtime.run_projections import RunProjectionCoordinator


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


def _row_to_run_group(row: Any) -> dict[str, Any]:
    return {
        "run_group_id": str(row["run_group_id"]),
        "title": str(row["title"] or ""),
        "source": str(row["source"] or ""),
        "workspace_dir": str(row["workspace_dir"] or ""),
        "status": str(row["status"] or ""),
        "summary": str(row["summary"] or ""),
        "child_run_ids": _json_load(row["child_run_ids_json"], []),
        "created_at": str(row["created_at"] or ""),
        "updated_at": str(row["updated_at"] or ""),
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


def test_run_repository_terminal_cas_rejects_newer_pending_approval() -> None:
    conn = _connect_runs_db()
    synced: list[dict[str, Any]] = []
    now_values = iter(
        [
            "2026-07-11T10:00:00+00:00",
            "2026-07-11T10:00:02+00:00",
        ]
    )
    repo = RunRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run=_row_to_run,
        accepting_runs=lambda: True,
        sync_projections=lambda **payload: synced.append(payload),
        append_run_to_group=lambda *_: None,
        now=lambda: next(now_values),
        json_dump=_json_dump,
        json_load=_json_load,
        redact_secrets=str,
        redact_json_value=redact_json_value,
        contains_sensitive_text=lambda _value: False,
        error_type=AgentRuntimeError,
    )
    run = repo.insert(
        kind="main_chat_run",
        runnable_id="builtin:yachiyo-main",
        user_goal="open Calculator",
    )
    conn.execute(
        """
        UPDATE runs
           SET pending_approval_json=?
         WHERE run_id=?
        """,
        (
            _json_dump(
                {
                    "approval_id": "approval-new",
                    "tool": "desktop.verify",
                }
            ),
            run["run_id"],
        ),
    )
    conn.commit()

    updated = repo.update(
        run["run_id"],
        status="completed",
        result="model says done",
        pending_approval=None,
        expected_status="running",
        expected_updated_at=run["updated_at"],
        expected_pending_approval_absent=True,
    )

    winner = repo.get(run["run_id"])
    assert updated is None
    assert winner["status"] == "running"
    assert winner["pending_approval"]["approval_id"] == "approval-new"
    assert synced == []


def test_run_repository_terminal_cas_rejects_newer_updated_at() -> None:
    conn = _connect_runs_db()
    synced: list[dict[str, Any]] = []
    now_values = iter(
        [
            "2026-07-11T10:00:00+00:00",
            "2026-07-11T10:00:02+00:00",
        ]
    )
    repo = RunRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run=_row_to_run,
        accepting_runs=lambda: True,
        sync_projections=lambda **payload: synced.append(payload),
        append_run_to_group=lambda *_: None,
        now=lambda: next(now_values),
        json_dump=_json_dump,
        json_load=_json_load,
        redact_secrets=str,
        redact_json_value=redact_json_value,
        contains_sensitive_text=lambda _value: False,
        error_type=AgentRuntimeError,
    )
    run = repo.insert(
        kind="main_chat_run",
        runnable_id="builtin:yachiyo-main",
        user_goal="open Calculator",
    )
    conn.execute(
        """
        UPDATE runs
           SET timeline_json=?, updated_at=?
         WHERE run_id=?
        """,
        (
            _json_dump([{"event": "approval.candidate.created"}]),
            "2026-07-11T10:00:01+00:00",
            run["run_id"],
        ),
    )
    conn.commit()

    updated = repo.update(
        run["run_id"],
        status="completed",
        result="model says done",
        pending_approval=None,
        expected_status="running",
        expected_updated_at=run["updated_at"],
        expected_pending_approval_absent=True,
    )

    winner = repo.get(run["run_id"])
    assert updated is None
    assert winner["status"] == "running"
    assert winner["timeline"] == [{"event": "approval.candidate.created"}]
    assert synced == []


def test_run_repository_resume_cas_rejects_consumed_approval_generation() -> None:
    conn = _connect_runs_db()
    conn.execute(
        """
        CREATE TABLE run_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL
        )
        """
    )
    synced: list[dict[str, Any]] = []
    repo = RunRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run=_row_to_run,
        accepting_runs=lambda: True,
        sync_projections=lambda run_id, **payload: synced.append(
            {"run_id": run_id, **payload}
        ),
        append_run_to_group=lambda *_: None,
        now=lambda: "2026-07-17T10:00:00+00:00",
        json_dump=_json_dump,
        json_load=_json_load,
        redact_secrets=str,
        redact_json_value=redact_json_value,
        contains_sensitive_text=lambda _value: False,
        error_type=AgentRuntimeError,
    )
    run = repo.insert(
        kind="main_chat_run",
        runnable_id="builtin:yachiyo-main",
        user_goal="run two approved commands",
    )
    conn.executemany(
        "INSERT INTO run_approvals (approval_id, run_id, status) VALUES (?, ?, ?)",
        (
            ("approval-A", run["run_id"], "consumed"),
            ("approval-B", run["run_id"], "approved"),
            ("approval-C", run["run_id"], "consumed"),
        ),
    )
    conn.commit()

    stale_continuation = repo.update(
        run["run_id"],
        result="stale A continuation",
        expected_status="running",
        expected_approval_id="approval-A",
    )
    stale_terminal = repo.update(
        run["run_id"],
        status="completed",
        result="stale A completed",
        pending_approval=None,
        expected_status="running",
        expected_approval_id="approval-A",
    )

    assert stale_continuation is None
    assert stale_terminal is None
    assert repo.get(run["run_id"])["status"] == "running"
    assert repo.get(run["run_id"])["result"] == ""
    assert synced == []

    current_terminal = repo.update(
        run["run_id"],
        status="completed",
        result="B completed",
        pending_approval=None,
        expected_status="running",
        expected_approval_id="approval-B",
    )

    assert current_terminal is not None
    assert current_terminal["status"] == "completed"
    assert current_terminal["result"] == "B completed"
    assert [payload["status"] for payload in synced] == ["completed"]


def test_run_repository_update_rolls_back_all_projections_when_sync_crashes(
    tmp_path,
) -> None:
    lock = threading.RLock()
    conn = open_locked_runtime_connection(tmp_path / "atomic-update.db", lock)
    conn.row_factory = named_row_factory
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
        CREATE TABLE task_run_links (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL DEFAULT '',
            run_status TEXT NOT NULL DEFAULT '',
            last_event_sequence INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE run_events (
            event_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            schema_version INTEGER NOT NULL DEFAULT 1,
            event_type TEXT NOT NULL,
            actor TEXT NOT NULL DEFAULT 'native_runtime',
            visibility TEXT NOT NULL DEFAULT 'user',
            sensitivity TEXT NOT NULL DEFAULT 'public',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE (run_id, sequence)
        );
        CREATE TABLE run_approvals (
            approval_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            tool TEXT NOT NULL DEFAULT '',
            input_preview_json TEXT NOT NULL DEFAULT '{}',
            payload_json TEXT NOT NULL DEFAULT '{}',
            requested_at TEXT NOT NULL,
            resolved_at TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL
        );
        CREATE TABLE run_artifacts (
            artifact_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL,
            sequence INTEGER NOT NULL,
            kind TEXT NOT NULL DEFAULT '',
            path TEXT NOT NULL DEFAULT '',
            source_run_id TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            created_at TEXT NOT NULL,
            UNIQUE (run_id, sequence)
        );
        """
    )
    now = lambda: "2026-07-12T10:00:00+00:00"
    repo_ref: dict[str, RunRepository] = {}
    task_links = TaskRunLinkRepository(
        conn,
        ensure_row_factory=lambda: None,
        get_run=lambda run_id: repo_ref["runs"].get(run_id),
        now=now,
        error_type=AgentRuntimeError,
    )
    artifacts = RunArtifactRepository(
        conn,
        agent_artifacts_dir=tmp_path / "agent-artifacts",
        workflow_artifacts_dir=tmp_path / "workflow-artifacts",
        get_run=lambda run_id: repo_ref["runs"].get(run_id),
        now=now,
        json_dump=_json_dump,
        redact_json_value=redact_json_value,
        redact_secrets=str,
        safe_rel_path=str,
        is_within=lambda *_: True,
        read_text=lambda *_: "",
    )
    approvals = ApprovalRepository(
        conn,
        lock,
        now=now,
        json_dump=_json_dump,
        json_load=_json_load,
        public_pending_approval=lambda pending: dict(pending or {}),
        error_type=AgentRuntimeError,
    )
    projections = RunProjectionCoordinator(
        run_artifacts=artifacts,
        run_approvals=approvals,
        task_run_links=task_links,
    )
    crash_after_sync = False

    def sync_projections(run_id: str, **payload: Any) -> None:
        projections.sync(run_id, **payload)
        if crash_after_sync:
            raise RuntimeError("injected_projection_crash")

    runs = RunRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run=_row_to_run,
        accepting_runs=lambda: True,
        sync_projections=sync_projections,
        append_run_to_group=lambda *_: None,
        now=now,
        json_dump=_json_dump,
        json_load=_json_load,
        redact_secrets=str,
        redact_json_value=redact_json_value,
        contains_sensitive_text=lambda _value: False,
        error_type=AgentRuntimeError,
    )
    repo_ref["runs"] = runs
    run = runs.insert(
        kind="main_chat_run",
        runnable_id="builtin:yachiyo-main",
        user_goal="open Calculator",
    )
    task_links.link(task_id="task-atomic", run_id=run["run_id"], session_id="chat-1")
    runs.update(
        run["run_id"],
        artifacts=[{"kind": "report", "path": "old.md"}],
    )
    crash_after_sync = True

    with pytest.raises(RuntimeError, match="injected_projection_crash"):
        runs.update(
            run["run_id"],
            status="approval_required",
            result="waiting",
            artifacts=[{"kind": "report", "path": "new.md"}],
            pending_approval={
                "approval_id": "approval-atomic",
                "tool": "desktop.open_app",
                "requested_at": now(),
            },
        )

    persisted = runs.get(run["run_id"])
    approval_count = conn.execute(
        "SELECT COUNT(*) AS count FROM run_approvals WHERE run_id=?",
        (run["run_id"],),
    ).fetchone()["count"]
    artifact_paths = [
        row["path"]
        for row in conn.execute(
            "SELECT path FROM run_artifacts WHERE run_id=? ORDER BY sequence",
            (run["run_id"],),
        ).fetchall()
    ]

    assert persisted["status"] == "running"
    assert persisted["result"] == ""
    assert persisted["pending_approval"] == {}
    assert persisted["artifacts"] == [{"kind": "report", "path": "old.md"}]
    assert approval_count == 0
    assert artifact_paths == ["old.md"]
    assert task_links.get("task-atomic")["run_status"] == "running"
    conn.close()


def test_run_repository_insert_rolls_back_run_and_group_when_membership_sync_crashes(
    tmp_path,
) -> None:
    lock = threading.RLock()
    conn = open_locked_runtime_connection(tmp_path / "atomic-insert.db", lock)
    conn.row_factory = named_row_factory
    conn.executescript(
        """
        CREATE TABLE run_groups (
            run_group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            workspace_dir TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT 'running',
            summary TEXT NOT NULL DEFAULT '',
            child_run_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
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
    now = lambda: "2026-07-12T11:00:00+00:00"
    groups = RunGroupRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run_group=_row_to_run_group,
        row_to_run=_row_to_run,
        now=now,
        json_dump=_json_dump,
        redact_secrets=str,
    )
    group = groups.insert(title="Daily helper", source="agent")

    def append_membership_then_crash(run_group_id: str, run_id: str) -> None:
        groups.append_run(run_group_id, run_id)
        raise RuntimeError("injected_group_projection_crash")

    runs = RunRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run=_row_to_run,
        accepting_runs=lambda: True,
        sync_projections=lambda **_: None,
        append_run_to_group=append_membership_then_crash,
        now=now,
        json_dump=_json_dump,
        json_load=_json_load,
        redact_secrets=str,
        redact_json_value=redact_json_value,
        contains_sensitive_text=lambda _value: False,
        error_type=AgentRuntimeError,
    )

    with pytest.raises(RuntimeError, match="injected_group_projection_crash"):
        runs.insert(
            kind="agent_run",
            runnable_id="agent-daily",
            user_goal="open Calculator",
            run_group_id=group["run_group_id"],
        )

    assert conn.execute("SELECT COUNT(*) AS count FROM runs").fetchone()["count"] == 0
    assert groups.get(group["run_group_id"])["child_run_ids"] == []
    conn.close()
