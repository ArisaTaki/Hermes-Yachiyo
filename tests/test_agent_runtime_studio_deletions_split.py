"""Tests for Studio deletion tombstones split out of the legacy runtime."""

from __future__ import annotations

import sqlite3

from apps.shell import agent_runtime
from apps.shell.agent.repositories.studio_deletions import StudioDeletionRepository
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _connect_studio_deletions_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE studio_deletions (
            item_type TEXT NOT NULL,
            item_key TEXT NOT NULL,
            deleted_at TEXT NOT NULL,
            PRIMARY KEY (item_type, item_key)
        )
        """
    )
    return conn


def test_studio_deletion_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.StudioDeletionRepository is StudioDeletionRepository


def test_studio_deletion_repository_records_clears_and_ignores_empty_keys() -> None:
    conn = _connect_studio_deletions_db()
    now_values = iter(["2026-06-15T10:00:00Z", "2026-06-15T10:01:00Z"])
    repo = StudioDeletionRepository(conn, now=lambda: next(now_values))

    repo.record("skill_source", "")
    assert conn.execute("SELECT COUNT(*) AS count FROM studio_deletions").fetchone()["count"] == 0

    repo.record("skill_source", " native:/skills/demo ")
    assert repo.has("skill_source", "native:/skills/demo") is True
    first_deleted_at = conn.execute("SELECT deleted_at FROM studio_deletions").fetchone()["deleted_at"]

    repo.record("skill_source", "native:/skills/demo")
    second_deleted_at = conn.execute("SELECT deleted_at FROM studio_deletions").fetchone()["deleted_at"]
    assert second_deleted_at != first_deleted_at

    repo.clear("skill_source", "native:/skills/demo")
    assert repo.has("skill_source", "native:/skills/demo") is False


def test_native_runtime_uses_split_studio_deletion_repository(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        assert isinstance(service.studio_deletions, StudioDeletionRepository)

        service._record_studio_deletion("workflow", "workflow-demo")
        assert service._has_studio_deletion("workflow", "workflow-demo") is True

        service._clear_studio_deletion("workflow", "workflow-demo")
        assert service._has_studio_deletion("workflow", "workflow-demo") is False
    finally:
        service.close()
