"""Tests for runtime schema initialization split out of the legacy runtime."""

from __future__ import annotations

import sqlite3
from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.schema import (
    RuntimeSchemaMigrator,
    RuntimeSchemaService,
    agent_model_credential_ref,
    initialize_runtime_schema,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_schema_helpers_remain_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeSchemaService is RuntimeSchemaService
    assert agent_runtime.RuntimeSchemaMigrator is RuntimeSchemaMigrator
    assert agent_runtime._initialize_runtime_schema is initialize_runtime_schema


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


def test_runtime_schema_service_initializes_schema_and_exposes_migrator(tmp_path: Path) -> None:
    conn = sqlite3.connect(tmp_path / "agent-runtime.db")
    conn.row_factory = sqlite3.Row
    service = RuntimeSchemaService(
        conn,
        now=lambda: "2026-06-15T00:00:00+00:00",
        redact_secrets=str,
        credential_store=MemoryCredentialStore(),
    )

    service.init_db()

    tables = {
        row["name"]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    }
    metadata = {
        row["key"]: row["value"]
        for row in conn.execute("SELECT key, value FROM runtime_schema_metadata").fetchall()
    }
    assert {"agents", "runs", "run_events", "runtime_schema_metadata"}.issubset(tables)
    assert metadata["schema_version"] == "1"
    assert isinstance(service.migrator(), RuntimeSchemaMigrator)


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


def test_agent_runtime_service_uses_runtime_schema_service(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.runtime_schema, RuntimeSchemaService)
        assert isinstance(service._schema_migrator(), RuntimeSchemaMigrator)
    finally:
        service.close()


def test_runtime_schema_migrator_updates_legacy_columns_projections_and_secrets(
    tmp_path: Path,
) -> None:
    conn = sqlite3.connect(tmp_path / "agent-runtime.db")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            execution_backend TEXT NOT NULL DEFAULT 'external_cli',
            model_api_key TEXT NOT NULL DEFAULT ''
        );
        CREATE TABLE skills (
            skill_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            skill_markdown TEXT NOT NULL
        );
        CREATE TABLE skill_folders (
            folder_id TEXT PRIMARY KEY,
            source_scope TEXT NOT NULL DEFAULT 'yachiyo'
        );
        CREATE TABLE studio_deletions (
            item_type TEXT NOT NULL,
            item_key TEXT NOT NULL,
            deleted_at TEXT NOT NULL
        );
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY,
            kind TEXT NOT NULL,
            runnable_id TEXT NOT NULL,
            status TEXT NOT NULL,
            user_goal TEXT NOT NULL DEFAULT '',
            result TEXT NOT NULL DEFAULT '',
            timeline_json TEXT NOT NULL DEFAULT '[]',
            artifacts_json TEXT NOT NULL DEFAULT '[]',
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        CREATE TABLE task_run_links (
            task_id TEXT PRIMARY KEY,
            run_id TEXT NOT NULL UNIQUE,
            session_id TEXT NOT NULL DEFAULT '',
            created_at TEXT NOT NULL
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
            created_at TEXT NOT NULL
        );
        CREATE TABLE run_groups (
            run_group_id TEXT PRIMARY KEY,
            title TEXT NOT NULL DEFAULT '',
            source TEXT NOT NULL DEFAULT '',
            workspace_dir TEXT NOT NULL DEFAULT '',
            summary TEXT NOT NULL DEFAULT '',
            updated_at TEXT NOT NULL DEFAULT ''
        );
        INSERT INTO agents (agent_id, name, model_api_key)
        VALUES ('agent-1', 'Agent One', 'sk-secret-agent-key');
        INSERT INTO skill_folders (folder_id, source_scope)
        VALUES ('folder-1', 'yachiyo');
        INSERT INTO studio_deletions (item_type, item_key, deleted_at)
        VALUES ('skill_source', 'yachiyo:/old/path', '2026-06-15T00:00:00+00:00');
        INSERT INTO runs (
            run_id, kind, runnable_id, status, created_at, updated_at
        ) VALUES (
            'run-1', 'main_chat_run', 'builtin:yachiyo-main', 'completed',
            '2026-06-15T00:00:00+00:00', '2026-06-15T00:00:01+00:00'
        );
        INSERT INTO task_run_links (task_id, run_id, session_id, created_at)
        VALUES ('task-1', 'run-1', 'session-1', '2026-06-15T00:00:00+00:00');
        INSERT INTO run_events (
            event_id, run_id, sequence, event_type, payload_json, created_at
        ) VALUES
            ('event-1', 'run-1', 1, 'run.started', '{}', '2026-06-15T00:00:00+00:00'),
            ('event-2', 'run-1', 2, 'run.completed', '{}', '2026-06-15T00:00:01+00:00');
        INSERT INTO run_groups (run_group_id, title, source, workspace_dir, summary, updated_at)
        VALUES (
            'group-1',
            'title sk-secret',
            'source sk-secret',
            '/tmp/sk-secret/project',
            'summary sk-secret',
            '2026-06-15T00:00:00+00:00'
        );
        """
    )
    credentials = MemoryCredentialStore()
    migrator = RuntimeSchemaMigrator(
        conn,
        now=lambda: "2026-06-15T00:00:02+00:00",
        redact_secrets=lambda value: str(value).replace("sk-secret", "[redacted]"),
        credential_store=credentials,
    )

    assert migrator.ensure_runtime_columns() is True

    agent_columns = {row["name"] for row in conn.execute("PRAGMA table_info(agents)").fetchall()}
    skill_columns = {row["name"] for row in conn.execute("PRAGMA table_info(skills)").fetchall()}
    run_columns = {row["name"] for row in conn.execute("PRAGMA table_info(runs)").fetchall()}
    link = conn.execute("SELECT * FROM task_run_links WHERE task_id='task-1'").fetchone()
    folder = conn.execute("SELECT source_scope FROM skill_folders WHERE folder_id='folder-1'").fetchone()
    deletion = conn.execute("SELECT item_key FROM studio_deletions").fetchone()
    group = conn.execute("SELECT * FROM run_groups WHERE run_group_id='group-1'").fetchone()
    agent = conn.execute("SELECT model_api_key, model_credential_ref FROM agents WHERE agent_id='agent-1'").fetchone()

    assert {"nickname", "persona_prompt", "model_credential_ref"}.issubset(agent_columns)
    assert {"local_path", "folder_id", "source_type", "sync_status"}.issubset(skill_columns)
    assert {"run_group_id", "client_request_id", "pending_approval_json"}.issubset(run_columns)
    assert link["run_status"] == "completed"
    assert link["last_event_sequence"] == 2
    assert link["updated_at"] == "2026-06-15T00:00:00+00:00"
    assert folder["source_scope"] == "installed"
    assert deletion["item_key"] == "installed:/old/path"
    assert group["title"] == "title [redacted]"
    assert group["source"] == "source [redacted]"
    assert group["workspace_dir"] == "/tmp/[redacted]/project"
    assert group["summary"] == "summary [redacted]"
    assert agent["model_api_key"] == ""
    assert agent["model_credential_ref"] == agent_model_credential_ref("agent-1")
    assert credentials.get(agent_model_credential_ref("agent-1")) == "sk-secret-agent-key"
