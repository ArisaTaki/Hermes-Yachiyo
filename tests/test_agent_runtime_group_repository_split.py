"""Tests for the RunGroupRepository split out of agent_runtime."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.groups import RunGroupRepository


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _row_to_group(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_group_id": str(row["run_group_id"]),
        "title": str(row["title"] or ""),
        "source": str(row["source"] or ""),
        "workspace_dir": str(row["workspace_dir"] or ""),
        "status": str(row["status"] or ""),
        "summary": str(row["summary"] or ""),
        "child_run_ids": _json_load(row["child_run_ids_json"], []),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _row_to_run(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "run_id": str(row["run_id"]),
        "run_group_id": str(row["run_group_id"] or ""),
        "created_at": str(row["created_at"]),
    }


def _connect_groups_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE run_groups (
            run_group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            workspace_dir TEXT NOT NULL DEFAULT '',
            status TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            child_run_ids_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            run_group_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_run_group_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.RunGroupRepository is RunGroupRepository


def test_run_group_repository_lifecycle_and_child_membership() -> None:
    conn = _connect_groups_db()
    now_values = iter(
        [
            "2026-06-14T10:00:00Z",
            "2026-06-14T10:01:00Z",
            "2026-06-14T10:02:00Z",
            "2026-06-14T10:03:00Z",
            "2026-06-14T10:04:00Z",
        ],
    )
    repo = RunGroupRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run_group=_row_to_group,
        row_to_run=_row_to_run,
        now=lambda: next(now_values),
        json_dump=_json_dump,
        redact_secrets=lambda value: str(value).replace("secret", "[redacted]"),
    )

    group = repo.insert(title="team secret", source="workflow", workspace_dir="/tmp/secret")
    group_id = group["run_group_id"]
    assert group["title"] == "team [redacted]"
    assert group["workspace_dir"] == "/tmp/[redacted]"
    assert repo.source(group_id) == "workflow"

    repo.append_run(group_id, "run-1")
    repo.append_run(group_id, "run-1")
    repo.update(group_id, status="completed", summary="done secret")
    updated = repo.get(group_id)
    assert updated["child_run_ids"] == ["run-1"]
    assert updated["status"] == "completed"
    assert updated["summary"] == "done [redacted]"

    conn.execute(
        "INSERT INTO runs (run_id, run_group_id, created_at) VALUES (?, ?, ?)",
        ("run-1", group_id, "2026-06-14T10:00:30Z"),
    )
    conn.commit()
    assert repo.runs(group_id) == [
        {"run_id": "run-1", "run_group_id": group_id, "created_at": "2026-06-14T10:00:30Z"}
    ]

    conn.execute("DELETE FROM runs WHERE run_id=?", ("run-1",))
    repo.remove_run_ids(group_id, {"run-1"})
    assert conn.execute("SELECT COUNT(*) AS count FROM run_groups").fetchone()["count"] == 0


def test_run_group_repository_transition_cas_preserves_terminal_winner() -> None:
    conn = _connect_groups_db()
    now_values = iter(
        [
            "2026-07-12T10:00:00Z",
            "2026-07-12T10:01:00Z",
            "2026-07-12T10:02:00Z",
        ]
    )
    repo = RunGroupRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_run_group=_row_to_group,
        row_to_run=_row_to_run,
        now=lambda: next(now_values),
        json_dump=_json_dump,
        redact_secrets=str,
    )
    running = repo.insert(title="CAS group", source="workflow")
    cancelled = repo.update(
        running["run_group_id"],
        status="cancelled",
        summary="cancel wins",
    )

    stale = repo.update(
        running["run_group_id"],
        status="approval_required",
        summary="stale approval",
        expected_status="running",
        expected_updated_at=running["updated_at"],
    )

    assert cancelled is not None
    assert stale is None
    current = repo.get(running["run_group_id"])
    assert current["status"] == "cancelled"
    assert current["summary"] == "cancel wins"
