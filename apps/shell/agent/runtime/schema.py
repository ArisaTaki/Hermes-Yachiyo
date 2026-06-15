"""Runtime SQLite schema initialization and migration orchestration."""

from __future__ import annotations

from typing import Any, Callable


_RUNTIME_TABLE_SCHEMA = """
CREATE TABLE IF NOT EXISTS agents (
    agent_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    nickname TEXT NOT NULL DEFAULT '',
    description TEXT NOT NULL DEFAULT '',
    avatar_url TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT 'custom',
    instructions TEXT NOT NULL DEFAULT '',
    persona_prompt TEXT NOT NULL DEFAULT '',
    model_mode TEXT NOT NULL DEFAULT 'profile',
    execution_backend TEXT NOT NULL DEFAULT 'native_profile',
    model_profile_id TEXT NOT NULL DEFAULT '',
    vision_model_profile_id TEXT NOT NULL DEFAULT '',
    model_provider TEXT NOT NULL DEFAULT 'openai_compatible',
    model_base_url TEXT NOT NULL DEFAULT '',
    model_name TEXT NOT NULL DEFAULT '',
    model_api_key TEXT NOT NULL DEFAULT '',
    model_credential_ref TEXT NOT NULL DEFAULT '',
    tool_policy_json TEXT NOT NULL DEFAULT '{}',
    workspace_policy_json TEXT NOT NULL DEFAULT '{}',
    skill_ids_json TEXT NOT NULL DEFAULT '[]',
    output_contract TEXT NOT NULL DEFAULT 'chat',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skills (
    skill_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_path TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    folder_id TEXT NOT NULL DEFAULT '',
    source_type TEXT NOT NULL DEFAULT 'local_dir',
    origin_path TEXT NOT NULL DEFAULT '',
    source_ref TEXT NOT NULL DEFAULT '',
    content_hash TEXT NOT NULL DEFAULT '',
    last_synced_at TEXT NOT NULL DEFAULT '',
    sync_status TEXT NOT NULL DEFAULT 'imported',
    content_summary TEXT NOT NULL DEFAULT '',
    skill_markdown TEXT NOT NULL,
    asset_paths_json TEXT NOT NULL DEFAULT '[]',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS skill_folders (
    folder_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    source_scope TEXT NOT NULL DEFAULT 'all',
    sort_order INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS workflows (
    workflow_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    nodes_json TEXT NOT NULL DEFAULT '[]',
    edges_json TEXT NOT NULL DEFAULT '[]',
    default_input_schema_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS studio_deletions (
    item_type TEXT NOT NULL,
    item_key TEXT NOT NULL,
    deleted_at TEXT NOT NULL,
    PRIMARY KEY (item_type, item_key)
);
CREATE TABLE IF NOT EXISTS run_groups (
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
CREATE TABLE IF NOT EXISTS runs (
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
CREATE TABLE IF NOT EXISTS task_run_links (
    task_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL UNIQUE,
    session_id TEXT NOT NULL DEFAULT '',
    run_status TEXT NOT NULL DEFAULT '',
    last_event_sequence INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL DEFAULT '',
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS run_events (
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
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    UNIQUE (run_id, sequence)
);
CREATE TABLE IF NOT EXISTS run_approvals (
    approval_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    tool TEXT NOT NULL DEFAULT '',
    input_preview_json TEXT NOT NULL DEFAULT '{}',
    payload_json TEXT NOT NULL DEFAULT '{}',
    requested_at TEXT NOT NULL,
    resolved_at TEXT NOT NULL DEFAULT '',
    updated_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS run_artifacts (
    artifact_id TEXT PRIMARY KEY,
    run_id TEXT NOT NULL,
    sequence INTEGER NOT NULL,
    kind TEXT NOT NULL DEFAULT '',
    path TEXT NOT NULL DEFAULT '',
    source_run_id TEXT NOT NULL DEFAULT '',
    payload_json TEXT NOT NULL DEFAULT '{}',
    created_at TEXT NOT NULL,
    FOREIGN KEY (run_id) REFERENCES runs(run_id) ON DELETE CASCADE,
    UNIQUE (run_id, sequence)
);
CREATE TABLE IF NOT EXISTS trusted_workspaces (
    path TEXT PRIMARY KEY,
    source TEXT NOT NULL DEFAULT '',
    trusted_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_items (
    memory_id TEXT PRIMARY KEY,
    scope TEXT NOT NULL DEFAULT 'global',
    kind TEXT NOT NULL DEFAULT 'fact',
    content TEXT NOT NULL,
    project_id TEXT NOT NULL DEFAULT '',
    source_session_id TEXT NOT NULL DEFAULT '',
    source_message_id TEXT NOT NULL DEFAULT '',
    source_task_id TEXT NOT NULL DEFAULT '',
    source_run_id TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    pinned INTEGER NOT NULL DEFAULT 0,
    user_confirmed INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS memory_projects (
    project_id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS memory_project_sessions (
    session_id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY (project_id) REFERENCES memory_projects(project_id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS memory_events (
    event_id TEXT PRIMARY KEY,
    memory_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'agent_tool',
    payload_json TEXT NOT NULL DEFAULT '{}',
    source_run_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS future_tasks (
    future_task_id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    prompt TEXT NOT NULL,
    runnable_id TEXT NOT NULL DEFAULT '',
    runnable_name TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'scheduled',
    scheduled_at_epoch REAL NOT NULL,
    cron TEXT NOT NULL DEFAULT '',
    source_run_id TEXT NOT NULL DEFAULT '',
    last_run_id TEXT NOT NULL DEFAULT '',
    run_count INTEGER NOT NULL DEFAULT 0,
    error TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    cancelled_at TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS future_task_events (
    event_id TEXT PRIMARY KEY,
    future_task_id TEXT NOT NULL DEFAULT '',
    action TEXT NOT NULL,
    actor TEXT NOT NULL DEFAULT 'agent_runtime',
    payload_json TEXT NOT NULL DEFAULT '{}',
    source_run_id TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS runtime_schema_metadata (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
"""

_RUNTIME_INDEX_SCHEMA = """
CREATE INDEX IF NOT EXISTS idx_agents_name ON agents (LOWER(name));
CREATE INDEX IF NOT EXISTS idx_workflows_name ON workflows (LOWER(name));
CREATE INDEX IF NOT EXISTS idx_skills_folder ON skills (folder_id);
CREATE INDEX IF NOT EXISTS idx_skills_origin ON skills (origin_path);
CREATE INDEX IF NOT EXISTS idx_skills_content_hash ON skills (content_hash);
CREATE INDEX IF NOT EXISTS idx_skill_folders_sort ON skill_folders (sort_order, LOWER(name));
CREATE INDEX IF NOT EXISTS idx_run_groups_status_updated ON run_groups (status, updated_at);
CREATE INDEX IF NOT EXISTS idx_runs_group_updated ON runs (run_group_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_runs_kind_updated ON runs (kind, updated_at);
CREATE UNIQUE INDEX IF NOT EXISTS idx_runs_client_request ON runs (client_request_id) WHERE client_request_id != '';
CREATE INDEX IF NOT EXISTS idx_task_run_links_session ON task_run_links (session_id, created_at);
CREATE INDEX IF NOT EXISTS idx_run_events_run_sequence ON run_events (run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_run_approvals_run_status ON run_approvals (run_id, status);
CREATE INDEX IF NOT EXISTS idx_run_artifacts_run_sequence ON run_artifacts (run_id, sequence);
CREATE INDEX IF NOT EXISTS idx_trusted_workspaces_updated ON trusted_workspaces (updated_at);
CREATE INDEX IF NOT EXISTS idx_memory_items_scope_kind_updated ON memory_items (scope, kind, deleted_at, updated_at);
CREATE INDEX IF NOT EXISTS idx_memory_items_source_run ON memory_items (source_run_id);
CREATE INDEX IF NOT EXISTS idx_memory_project_sessions_project ON memory_project_sessions (project_id);
CREATE INDEX IF NOT EXISTS idx_memory_events_memory_created ON memory_events (memory_id, created_at);
CREATE INDEX IF NOT EXISTS idx_future_tasks_status_due ON future_tasks (status, scheduled_at_epoch);
CREATE INDEX IF NOT EXISTS idx_future_tasks_runnable_updated ON future_tasks (runnable_id, updated_at);
CREATE INDEX IF NOT EXISTS idx_future_task_events_task_created ON future_task_events (future_task_id, created_at);
"""


def initialize_runtime_schema(
    conn: Any,
    *,
    now: Callable[[], str],
    ensure_runtime_columns: Callable[[], bool],
    vacuum_after_secret_scrub: Callable[[], None],
) -> None:
    conn.executescript(_RUNTIME_TABLE_SCHEMA)
    scrubbed_secrets = ensure_runtime_columns()
    conn.executescript(_RUNTIME_INDEX_SCHEMA)
    conn.execute(
        """
        INSERT INTO runtime_schema_metadata (key, value, updated_at)
        VALUES ('schema_version', '1', ?)
        ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at
        """,
        (now(),),
    )
    conn.commit()
    if scrubbed_secrets:
        vacuum_after_secret_scrub()
