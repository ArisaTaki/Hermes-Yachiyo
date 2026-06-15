import sqlite3
from pathlib import Path

from apps.shell.agent.repositories.row_projections import (
    row_to_run_group,
    row_to_skill,
    row_to_skill_folder,
    row_to_workflow,
)
from apps.shell.agent.runtime.serialization import json_load


def _row(sql: str, values: tuple[object, ...]) -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute(sql, values).fetchone()
    assert row is not None
    return row


def test_repository_row_projection_helpers_project_skill_and_folder_rows() -> None:
    skill = row_to_skill(
        _row(
            """
            SELECT
              'skill-1' AS skill_id,
              'Writer' AS name,
              'Writes' AS description,
              'local:writer' AS source_path,
              '' AS local_path,
              'folder-1' AS folder_id,
              'Writing' AS folder_name,
              'local_dir' AS source_type,
              '/tmp/writer' AS origin_path,
              'origin' AS source_ref,
              'hash' AS content_hash,
              '2026-06-15T09:00:00Z' AS last_synced_at,
              'imported' AS sync_status,
              'summary' AS content_summary,
              '# Writer' AS skill_markdown,
              '["assets/a.txt"]' AS asset_paths_json,
              1 AS enabled,
              'created' AS created_at,
              'updated' AS updated_at
            """,
            (),
        ),
        skills_dir=Path("/skills"),
        json_load=json_load,
    )
    assert skill["local_path"] == "/skills/skill-1"
    assert skill["folder_name"] == "Writing"
    assert skill["asset_paths"] == ["assets/a.txt"]
    assert skill["enabled"] is True

    folder = row_to_skill_folder(
        _row(
            """
            SELECT
              'folder-1' AS folder_id,
              'Writing' AS name,
              '' AS description,
              'all' AS source_scope,
              2 AS sort_order,
              3 AS skill_count,
              1 AS installed_count,
              2 AS native_count,
              'created' AS created_at,
              'updated' AS updated_at
            """,
            (),
        )
    )
    assert folder["skill_count"] == 3
    assert folder["native_count"] == 2


def test_repository_row_projection_helpers_project_workflow_and_group_rows() -> None:
    workflow = row_to_workflow(
        _row(
            """
            SELECT
              'workflow-1' AS workflow_id,
              'Research Flow' AS name,
              'desc' AS description,
              '[{"id":"start"}]' AS nodes_json,
              '[{"source":"start","target":"end"}]' AS edges_json,
              '{"topic":"string"}' AS default_input_schema_json,
              1 AS enabled,
              'created' AS created_at,
              'updated' AS updated_at
            """,
            (),
        ),
        json_load=json_load,
    )
    assert workflow["nodes"] == [{"id": "start"}]
    assert workflow["default_input_schema"] == {"topic": "string"}
    assert workflow["enabled"] is True

    group = row_to_run_group(
        _row(
            """
            SELECT
              'group-1' AS run_group_id,
              'Group' AS title,
              'agent_group' AS source,
              '/workspace' AS workspace_dir,
              'running' AS status,
              'summary' AS summary,
              '["run-1","run-2"]' AS child_run_ids_json,
              'created' AS created_at,
              'updated' AS updated_at
            """,
            (),
        ),
        json_load=json_load,
    )
    assert group["child_run_ids"] == ["run-1", "run-2"]
    assert group["source"] == "agent_group"
