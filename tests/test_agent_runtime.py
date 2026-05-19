"""Agent Runtime Service tests."""

from __future__ import annotations

import sqlite3
import zipfile

import pytest

from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService, ToolBroker


def make_service(tmp_path, *, seed_templates: bool = False) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        seed_templates=seed_templates,
    )


def test_runtime_migrates_legacy_runs_before_index_creation(tmp_path):
    db_path = tmp_path / "agent-runtime.db"
    conn = sqlite3.connect(db_path)
    conn.executescript(
        """
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
        """
    )
    conn.close()

    service = make_service(tmp_path)
    try:
        columns = {row["name"] for row in service._conn.execute("PRAGMA table_info(runs)").fetchall()}
        assert "run_group_id" in columns
        indexes = {row["name"] for row in service._conn.execute("PRAGMA index_list(runs)").fetchall()}
        assert "idx_runs_group_updated" in indexes
    finally:
        service.close()


def test_runtime_restores_row_factory_before_listing_runnables(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        service._conn.row_factory = None
        result = service.list_runnables()
        assert result["ok"] is True
        assert any(item["id"] == "agent_coding" for item in result["runnables"])
    finally:
        service.close()


def test_agent_crud_and_api_key_redaction(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Private Model",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-test-secret",
                },
            }
        )

        assert agent["model_config"]["api_key_configured"] is True
        assert "api_key" not in agent["model_config"]

        updated = service.update_agent(
            agent["agent_id"],
            {
                "description": "updated",
                "model_config": {"base_url": "https://gateway.example.test/v1", "api_key": ""},
            },
        )
        assert updated["description"] == "updated"
        assert updated["model_config"]["base_url"] == "https://gateway.example.test/v1"
        assert updated["model_config"]["api_key_configured"] is True
    finally:
        service.close()


def test_agent_and_workflow_names_are_globally_unique(tmp_path):
    service = make_service(tmp_path)
    try:
        service.create_agent({"name": "Shared Name"})
        with pytest.raises(AgentRuntimeError):
            service.create_workflow(
                {
                    "name": "shared name",
                    "nodes": [{"id": "start", "type": "start", "data": {"label": "Start"}}],
                    "edges": [],
                }
            )
    finally:
        service.close()


def test_import_skill_directory_and_mount_to_agent(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "demo-skill"
    (source / "assets").mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo Skill\n\nUseful instruction.", encoding="utf-8")
    (source / "assets" / "sample.txt").write_text("asset", encoding="utf-8")
    try:
        skill = service.import_skill(str(source))
        agent = service.create_agent({"name": "Skill Agent"})
        mounted = service.attach_skill(agent["agent_id"], skill["skill_id"])

        assert skill["name"] == "Demo Skill"
        assert skill["source_path"] == "local:demo-skill"
        assert skill["asset_paths"] == ["assets/sample.txt"]
        assert mounted["skill_ids"] == [skill["skill_id"]]
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Use the skill"})
        assert "Demo Skill" in run["result"]
        artifact = service.read_run_artifact(run["run_id"], "agent-context.md")
        assert artifact["ok"] is True
        assert "Useful instruction" in artifact["content"]
        assert run["run_group_id"]
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "agent"
        assert group["child_run_ids"] == [run["run_id"]]
        with pytest.raises(AgentRuntimeError):
            service.read_run_artifact(run["run_id"], "../escape.md")
    finally:
        service.close()


def test_import_skill_rejects_missing_skill_md(tmp_path):
    service = make_service(tmp_path)
    source = tmp_path / "bad-skill"
    source.mkdir()
    try:
        with pytest.raises(AgentRuntimeError):
            service.import_skill(str(source))
    finally:
        service.close()


def test_import_skill_zip_rejects_path_traversal(tmp_path):
    service = make_service(tmp_path)
    archive = tmp_path / "bad.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr("../SKILL.md", "# Bad")
    try:
        with pytest.raises(AgentRuntimeError):
            service.import_skill(str(archive))
    finally:
        service.close()


def test_workflow_validation_rejects_branch_and_cycle(tmp_path):
    service = make_service(tmp_path)
    try:
        nodes = [
            {"id": "start", "type": "start", "data": {"label": "Start"}},
            {"id": "a", "type": "agent", "data": {"label": "A"}},
            {"id": "b", "type": "agent", "data": {"label": "B"}},
        ]
        with pytest.raises(AgentRuntimeError):
            service.validate_workflow(
                nodes,
                [
                    {"source": "start", "target": "a"},
                    {"source": "start", "target": "b"},
                ],
            )
        with pytest.raises(AgentRuntimeError):
            service.validate_workflow(
                nodes,
                [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "a"},
                ],
            )
    finally:
        service.close()


def test_linear_workflow_executes_agent_nodes_in_order(tmp_path):
    service = make_service(tmp_path)
    try:
        agent_a = service.create_agent({"name": "Agent A", "model_mode": "follow_main"})
        agent_b = service.create_agent({"name": "Agent B", "model_mode": "follow_main"})
        workflow = service.create_workflow(
            {
                "name": "Linear Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Agent A", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Agent B", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "completed"
        assert run["run_group_id"]
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 2
        assert "Agent B" in run["result"]
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "workflow"
        assert len(group["child_run_ids"]) == 3
    finally:
        service.close()


def test_agent_execution_backend_defaults_and_external_cli_placeholder(tmp_path):
    service = make_service(tmp_path)
    try:
        hermes_agent = service.create_agent({"name": "Hermes Agent"})
        assert hermes_agent["execution_backend"] == "hermes_profile"
        run = service.create_agent_run({"agent_id": hermes_agent["agent_id"], "user_goal": "Plan"})
        assert run["status"] == "completed"
        assert "hermes_profile 后端" in run["result"]

        external = service.create_agent({"name": "CLI Agent", "execution_backend": "external_cli"})
        external_run = service.create_agent_run({"agent_id": external["agent_id"], "user_goal": "Review"})
        assert external_run["status"] == "completed"
        assert "external_cli 后端" in external_run["result"]
    finally:
        service.close()


def test_tool_broker_blocks_out_of_scope_and_unapproved_terminal(tmp_path):
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello", encoding="utf-8")
    broker = ToolBroker(
        {
            "default_workdir": str(workdir),
            "readable_scopes": ["."],
            "writable_scopes": ["src"],
        },
        tmp_path / "artifacts",
    )

    assert broker.workspace_read("README.md")["content"] == "hello"
    with pytest.raises(AgentRuntimeError):
        broker.workspace_write_patch("../escape.txt", "bad", approved=True)
    assert broker.terminal_run("echo should-not-run")["approval_required"] is True
    assert broker.call("terminal.run", {"command": "echo should-not-run", "approved": True})["approval_required"] is True
