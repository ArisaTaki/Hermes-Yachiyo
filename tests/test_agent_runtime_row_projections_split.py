import sqlite3
from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.repositories.row_projections import (
    RuntimeRowProjector,
    row_to_agent,
    row_to_agent_private,
    row_to_run,
    row_to_run_group,
    row_to_skill,
    row_to_skill_folder,
    row_to_workflow,
)
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.agent.tools.policy import RuntimePolicyCompiler
from apps.shell.agent.runtime.serialization import json_load
from apps.shell.credential_store import MemoryCredentialStore


def _row(sql: str, values: tuple[object, ...]) -> sqlite3.Row:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    row = conn.execute(sql, values).fetchone()
    assert row is not None
    return row


def test_runtime_row_projector_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeRowProjector is RuntimeRowProjector


def test_repository_row_projection_helpers_project_agent_rows() -> None:
    compiler = RuntimePolicyCompiler()
    agent_row = _row(
        """
        SELECT
          'agent-1' AS agent_id,
          'Coder' AS name,
          '' AS nickname,
          'Codes' AS description,
          '' AS avatar_url,
          'coding' AS category,
          'Do the work' AS instructions,
          'Persona' AS persona_prompt,
          'custom' AS model_mode,
          'external_cli' AS execution_backend,
          'profile-1' AS model_profile_id,
          'vision-1' AS vision_model_profile_id,
          'openai' AS model_provider,
          'https://example.test/v1' AS model_base_url,
          'gpt-test' AS model_name,
          '' AS model_api_key,
          'cred-agent-1' AS model_credential_ref,
          '{"allowed_tools":["workspace.read","terminal.run"]}' AS tool_policy_json,
          '{"default_workdir":" /tmp/agent ","readable_scopes":".,src","writable_scopes":["src"]}' AS workspace_policy_json,
          '["skill-1"]' AS skill_ids_json,
          'markdown' AS output_contract,
          1 AS enabled,
          'created' AS created_at,
          'updated' AS updated_at
        """,
        (),
    )

    def project_agent(row: sqlite3.Row) -> dict[str, object]:
        return row_to_agent(
            row,
            json_load=json_load,
            default_tool_policy=compiler.default_tool_policy,
            default_workspace_policy=compiler.default_workspace_policy,
            compile_tool_policy=compiler.compile_tool_policy,
            compile_workspace_policy=compiler.compile_workspace_policy,
            normalize_execution_backend=lambda value, **_: str(value or ""),
        )

    agent = project_agent(agent_row)
    assert agent["nickname"] == "Coder"
    assert agent["execution_backend"] == "external_cli"
    assert agent["model_config"]["api_key_configured"] is True
    assert agent["tool_policy"] == {
        "allowed_tools": ["workspace.read", "terminal.run"],
        "approval_required": {"terminal.run": True},
    }
    assert agent["workspace_policy"] == {
        "default_workdir": "/tmp/agent",
        "readable_scopes": [".", "src"],
        "writable_scopes": ["src"],
    }
    assert agent["skill_ids"] == ["skill-1"]

    private_agent = row_to_agent_private(
        agent_row,
        row_to_agent=project_agent,
        read_credential=lambda ref: "stored-secret" if ref == "cred-agent-1" else "",
    )
    assert private_agent["model_config"]["credential_ref"] == "cred-agent-1"
    assert private_agent["model_config"]["api_key"] == "stored-secret"


def test_runtime_row_projector_projects_agent_and_private_rows() -> None:
    compiler = RuntimePolicyCompiler()
    agent_row = _row(
        """
        SELECT
          'agent-1' AS agent_id,
          'Coder' AS name,
          '' AS nickname,
          'Codes' AS description,
          '' AS avatar_url,
          'coding' AS category,
          'Do the work' AS instructions,
          'Persona' AS persona_prompt,
          'custom' AS model_mode,
          'external_cli' AS execution_backend,
          'profile-1' AS model_profile_id,
          'vision-1' AS vision_model_profile_id,
          'openai' AS model_provider,
          'https://example.test/v1' AS model_base_url,
          'gpt-test' AS model_name,
          '' AS model_api_key,
          'cred-agent-1' AS model_credential_ref,
          '{"allowed_tools":["workspace.read"]}' AS tool_policy_json,
          '{"default_workdir":" /tmp/agent "}' AS workspace_policy_json,
          '["skill-1"]' AS skill_ids_json,
          'markdown' AS output_contract,
          1 AS enabled,
          'created' AS created_at,
          'updated' AS updated_at
        """,
        (),
    )
    projector = RuntimeRowProjector(
        skills_dir=Path("/skills"),
        json_load=json_load,
        default_tool_policy=compiler.default_tool_policy,
        default_workspace_policy=compiler.default_workspace_policy,
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        normalize_execution_backend=lambda value, **_: str(value or ""),
        read_credential=lambda ref: "stored-secret" if ref == "cred-agent-1" else "",
        public_pending_approval=lambda pending: pending if isinstance(pending, dict) else {},
        task_run_link_for_run=lambda _run_id: None,
        run_group_source=lambda _group_id: "",
        runnable_name=lambda kind, runnable_id: f"{kind}:{runnable_id}",
    )

    agent = projector.agent(agent_row)
    private_agent = projector.agent_private(agent_row)

    assert agent["nickname"] == "Coder"
    assert agent["skill_ids"] == ["skill-1"]
    assert private_agent["model_config"]["credential_ref"] == "cred-agent-1"
    assert private_agent["model_config"]["api_key"] == "stored-secret"


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


def test_repository_row_projection_helpers_project_run_rows() -> None:
    run = row_to_run(
        _row(
            """
            SELECT
              'run-1' AS run_id,
              'group-1' AS run_group_id,
              'client-1' AS client_request_id,
              'agent_run' AS kind,
              'agent-1' AS runnable_id,
              'approval_required' AS status,
              'goal' AS user_goal,
              'waiting' AS result,
              '[{"type":"agent.run.started"}]' AS timeline_json,
              '[{"artifact_id":"artifact-1"}]' AS artifacts_json,
              '{"tool":"terminal.run","private":"hidden"}' AS pending_approval_json,
              'created' AS created_at,
              'updated' AS updated_at
            """,
            (),
        ),
        json_load=json_load,
        public_pending_approval=lambda pending: {"tool": pending.get("tool", "")},
        task_run_link_for_run=lambda run_id: {
            "task_id": f"task-for-{run_id}",
            "session_id": "session-1",
            "created_at": "link-created",
            "updated_at": "link-updated",
            "run_status": "approval_required",
            "last_event_sequence": 7,
        },
        run_group_source=lambda group_id: f"source-for-{group_id}",
        runnable_name=lambda kind, runnable_id: f"{kind}:{runnable_id}",
    )

    assert run["task_id"] == "task-for-run-1"
    assert run["session_id"] == "session-1"
    assert run["task_run_link_last_event_sequence"] == 7
    assert run["run_group_source"] == "source-for-group-1"
    assert run["client_request_id"] == "client-1"
    assert run["runnable_name"] == "agent_run:agent-1"
    assert run["timeline"] == [{"type": "agent.run.started"}]
    assert run["artifacts"] == [{"artifact_id": "artifact-1"}]
    assert run["pending_approval"] == {"tool": "terminal.run"}


def test_agent_runtime_service_uses_runtime_row_projector(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.row_projector, RuntimeRowProjector)
    finally:
        service.close()
