"""Tests for runtime schema initialization split out of the legacy runtime."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from apps.shell.agent.runtime.schema import initialize_runtime_schema


def test_runtime_schema_initializer_creates_runtime_tables_indexes_and_metadata(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "agent-runtime.db")
    conn.row_factory = sqlite3.Row
    calls: list[str] = []

    def ensure_runtime_columns() -> bool:
        assert conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='run_events'"
        ).fetchone()
        assert not conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name='idx_run_events_run_sequence'"
        ).fetchone()
        calls.append("ensure")
        return True

    initialize_runtime_schema(
        conn,
        now=lambda: "2026-06-15T00:00:00+00:00",
        ensure_runtime_columns=ensure_runtime_columns,
        vacuum_after_secret_scrub=lambda: calls.append("vacuum"),
    )

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    indexes = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
    }
    metadata = {
        row["key"]: row["value"]
        for row in conn.execute("SELECT key, value FROM runtime_schema_metadata").fetchall()
    }

    assert calls == ["ensure", "vacuum"]
    assert {
        "agents",
        "runs",
        "run_events",
        "run_approvals",
        "run_artifacts",
        "memory_items",
        "future_tasks",
        "runtime_schema_metadata",
    }.issubset(tables)
    assert {
        "idx_runs_group_updated",
        "idx_run_events_run_sequence",
        "idx_run_approvals_run_status",
        "idx_run_artifacts_run_sequence",
        "idx_memory_items_scope_kind_updated",
        "idx_future_tasks_status_due",
    }.issubset(indexes)
    assert metadata["schema_version"] == "1"


def test_runtime_schema_initializer_skips_vacuum_without_secret_scrub(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "agent-runtime.db")
    conn.row_factory = sqlite3.Row
    calls: list[str] = []

    initialize_runtime_schema(
        conn,
        now=lambda: "2026-06-15T00:00:00+00:00",
        ensure_runtime_columns=lambda: calls.append("ensure") or False,
        vacuum_after_secret_scrub=lambda: calls.append("vacuum"),
    )

    assert calls == ["ensure"]
