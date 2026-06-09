"""Agent Runtime Service tests."""

from __future__ import annotations

import json
import sqlite3
import subprocess
import zipfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService, ToolBroker


def make_service(tmp_path, *, seed_templates: bool = False) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        seed_templates=seed_templates,
    )


class FakeDefaultProfileService:
    def get_defaults(self):
        return {"chat": "profile_default"}

    def get_profile_private(self, profile_id):
        assert profile_id == "profile_default"
        return {
            "profile_id": profile_id,
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
            "capability": "chat",
            "status": "available",
            "enabled": True,
        }


class FakeNoDefaultProfileService:
    def get_defaults(self):
        return {"chat": ""}

    def get_profile_private(self, profile_id):
        raise KeyError(profile_id)


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
        coding = next(item for item in result["runnables"] if item["id"] == "agent_coding")
        assert coding["output_contract"]
        assert "workspace.read" in coding["tool_policy"]["allowed_tools"]
        assert coding["tool_policy"]["approval_required"]["terminal.run"] is True
    finally:
        service.close()


def test_runtime_restores_row_factory_before_listing_agents(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        service._conn.row_factory = None
        service._ensure_row_factory = lambda: None  # type: ignore[method-assign]
        result = service.list_agents()
        assert result["ok"] is True
        assert any(agent["agent_id"] == "agent_coding" for agent in result["agents"])
    finally:
        service.close()


def test_runtime_agent_studio_reads_are_safe_under_parallel_refresh(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        def read_agent_studio_state(_index: int):
            return (
                service.list_agents()["agents"],
                service.list_skill_folders()["uncategorized"],
                service.list_runnables()["runnables"],
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(read_agent_studio_state, range(40)))

        assert results
        for agents, uncategorized, runnables in results:
            assert any(agent["agent_id"] == "agent_coding" for agent in agents)
            assert "skill_count" in uncategorized
            assert any(item["id"] == "agent_coding" for item in runnables)
    finally:
        service.close()


def test_seed_templates_backfill_default_workflows_when_agents_exist(tmp_path):
    service = make_service(tmp_path)
    try:
        service.create_agent({"name": "Existing Agent"})
    finally:
        service.close()

    service = make_service(tmp_path, seed_templates=True)
    try:
        workflows = service.list_workflows()["workflows"]
        workflow_ids = {workflow["workflow_id"] for workflow in workflows}

        assert "workflow_web_idea_full" in workflow_ids
        assert "workflow_phase4_agent_line_smoke" in workflow_ids
        assert any(agent["agent_id"] == "agent_coding" for agent in service.list_agents()["agents"])
    finally:
        service.close()


def test_deleted_seed_templates_do_not_return_after_restart(tmp_path):
    service = make_service(tmp_path, seed_templates=True)
    try:
        service.delete_agent("agent_coding")
        service.delete_workflow("workflow_web_idea_full")
    finally:
        service.close()

    service = make_service(tmp_path, seed_templates=True)
    try:
        agent_ids = {agent["agent_id"] for agent in service.list_agents()["agents"]}
        workflow_ids = {workflow["workflow_id"] for workflow in service.list_workflows()["workflows"]}

        assert "agent_coding" not in agent_ids
        assert "workflow_web_idea_full" not in workflow_ids
    finally:
        service.close()


def test_phase4_seeded_workflow_executes_default_agent_line(tmp_path, monkeypatch):
    service = make_service(tmp_path, seed_templates=True)
    calls = []
    expected_step_tasks = [
        "拆解全局目标，明确后续 Agent 的交付边界、依赖关系、风险和验收口径。",
        "基于全局目标整理事实、约束、参考信息和不确定点，为设计与实现提供依据。",
        "基于研究结果提出信息架构、交互结构、视觉方向和需要交付的设计要点。",
        "根据上游设计与约束给出实现方案、必要代码或变更计划，并说明验证方式。",
        "审查上游实现或方案，列出问题优先级、风险、缺失测试和可验收结论。",
        "把整条流程的目标、关键决策、产物、风险和后续待办整理成最终汇报。",
    ]

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": f"Step {len(calls)} complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: FakeDefaultProfileService())
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        run = service.create_workflow_run(
            {
                "workflow_id": "workflow_phase4_agent_line_smoke",
                "user_goal": "跑一次 Phase 4 全线流通性测试",
            }
        )

        assert run["status"] == "completed"
        assert run["result"] == "Step 6 complete"
        assert len(calls) == 6
        for index, task in enumerate(expected_step_tasks):
            assert f"# User Goal\n{task}\n\nWorkflow Goal:\n跑一次 Phase 4 全线流通性测试" in calls[index][-1]["content"]
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 6
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert [item.get("task") for item in started_event["workflow_path"] if item.get("kind") == "agent"] == expected_step_tasks
        assert [
            item.get("artifact_path")
            for item in started_event["workflow_path"]
            if item.get("kind") == "artifact"
        ] == ["reports/phase-4-flow-summary.md"]
        assert any(artifact.get("kind") == "workflow_artifact" for artifact in run["artifacts"])
        group = service.get_run_group(run["run_group_id"])
        assert group["status"] == "completed"
        assert len(group["child_run_ids"]) == 7
    finally:
        service.close()


def test_agent_crud_and_api_key_redaction(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Private Model",
                "nickname": "Private",
                "persona_prompt": "Keep a concise operator tone.",
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
        assert agent["nickname"] == "Private"
        assert agent["persona_prompt"] == "Keep a concise operator tone."

        updated = service.update_agent(
            agent["agent_id"],
            {
                "description": "updated",
                "nickname": "Private Ops",
                "model_config": {"base_url": "https://gateway.example.test/v1", "api_key": ""},
            },
        )
        assert updated["description"] == "updated"
        assert updated["nickname"] == "Private Ops"
        assert updated["model_config"]["base_url"] == "https://gateway.example.test/v1"
        assert updated["model_config"]["api_key_configured"] is True
    finally:
        service.close()


def test_agents_receive_isolated_default_workdirs(tmp_path):
    service = make_service(tmp_path)
    try:
        coding = service.create_agent({"name": "Default Writer", "category": "coding"})
        reader = service.create_agent({"name": "Default Reader"})

        coding_workdir = Path(coding["workspace_policy"]["default_workdir"])
        reader_workdir = Path(reader["workspace_policy"]["default_workdir"])
        assert coding_workdir == service.agent_workspaces_dir / coding["agent_id"]
        assert reader_workdir == service.agent_workspaces_dir / reader["agent_id"]
        assert coding_workdir.is_dir()
        assert reader_workdir.is_dir()
        assert coding["workspace_policy"]["writable_scopes"] == ["."]
        assert reader["workspace_policy"]["writable_scopes"] == []
    finally:
        service.close()


def test_runtime_migrates_blank_agent_workdirs(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent({"name": "Legacy Writer", "category": "coding"})
        service._conn.execute(
            "UPDATE agents SET workspace_policy_json=? WHERE agent_id=?",
            (json.dumps({"default_workdir": "", "readable_scopes": ["."], "writable_scopes": []}), agent["agent_id"]),
        )
        service._conn.commit()
    finally:
        service.close()

    service = make_service(tmp_path)
    try:
        migrated = service.get_agent(agent["agent_id"])
        assert Path(migrated["workspace_policy"]["default_workdir"]) == service.agent_workspaces_dir / agent["agent_id"]
        assert migrated["workspace_policy"]["writable_scopes"] == ["."]
    finally:
        service.close()


def test_explicit_agent_workdir_preserves_empty_writable_scopes(tmp_path):
    service = make_service(tmp_path)
    workdir = tmp_path / "custom-workdir"
    try:
        agent = service.create_agent(
            {
                "name": "Explicit Writer",
                "category": "coding",
                "workspace_policy": {
                    "default_workdir": str(workdir),
                    "readable_scopes": ["."],
                    "writable_scopes": [],
                },
            }
        )

        assert agent["workspace_policy"]["default_workdir"] == str(workdir)
        assert agent["workspace_policy"]["writable_scopes"] == []
        assert not workdir.exists()
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


def test_import_skill_directory_and_mount_to_agent(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    source = tmp_path / "demo-skill"
    (source / "assets").mkdir(parents=True)
    (source / "SKILL.md").write_text("# Demo Skill\n\nUseful instruction.", encoding="utf-8")
    (source / "assets" / "sample.txt").write_text("asset", encoding="utf-8")
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Demo Skill used"})
    try:
        skill = service.import_skill(str(source))
        agent = service.create_agent(
            {
                "name": "Skill Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        mounted = service.attach_skill(agent["agent_id"], skill["skill_id"])

        assert skill["name"] == "Demo Skill"
        assert skill["source_path"] == "local:demo-skill"
        assert skill["local_path"].endswith(skill["skill_id"])
        assert skill["enabled"] is True
        assert skill["asset_paths"] == ["assets/sample.txt"]
        assert mounted["skill_ids"] == [skill["skill_id"]]
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Use the skill"})
        assert run["result"] == "Demo Skill used"
        artifact = service.read_run_artifact(run["run_id"], "agent-context.md")
        assert artifact["ok"] is True
        assert "Useful instruction" in artifact["content"]
        assert run["run_group_id"]
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "agent"
        assert group["child_run_ids"] == [run["run_id"]]
        disabled = service.update_skill(skill["skill_id"], {"enabled": False})
        assert disabled["enabled"] is False
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Use disabled skill"})
        other_agent = service.create_agent({"name": "Other Skill Agent"})
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.attach_skill(other_agent["agent_id"], skill["skill_id"])
        with pytest.raises(AgentRuntimeError):
            service.read_run_artifact(run["run_id"], "../escape.md")
    finally:
        service.close()


def test_agent_context_includes_nickname_and_persona_prompt(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "ok"})
    try:
        agent = service.create_agent(
            {
                "name": "Context Agent",
                "nickname": "Ctx",
                "instructions": "Always inspect the local brief.",
                "persona_prompt": "Speak like a careful reviewer.",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Check context"})
        artifact = service.read_run_artifact(run["run_id"], "agent-context.md")

        assert "Nickname: Ctx" in artifact["content"]
        assert "# Functional Instructions" in artifact["content"]
        assert "Always inspect the local brief." in artifact["content"]
        assert "# Persona Prompt" in artifact["content"]
        assert "Speak like a careful reviewer." in artifact["content"]
    finally:
        service.close()


def test_agent_run_rejects_unrunnable_config_before_start(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Broken Standalone Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "provider": "openai_compatible",
                    "model": "demo-model",
                },
            }
        )

        with pytest.raises(AgentRuntimeError, match="Custom API 配置不完整"):
            service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run it"})
        assert service.list_runs()["runs"] == []
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


def test_import_skill_zip_uses_frontmatter_source_when_available(tmp_path):
    service = make_service(tmp_path)
    archive = tmp_path / "with-source.zip"
    with zipfile.ZipFile(archive, "w") as zf:
        zf.writestr(
            "skill/SKILL.md",
            "---\nname: Source Skill\nrepository: https://example.test/source-skill\n---\n\n# Source Skill\n",
        )
    try:
        skill = service.import_skill(str(archive))
        assert skill["source_type"] == "local_zip"
        assert skill["source_ref"] == "https://example.test/source-skill"
    finally:
        service.close()


def test_sync_hermes_skills_imports_skips_and_updates(tmp_path):
    service = make_service(tmp_path)
    hermes_root = tmp_path / ".hermes" / "skills"
    skill_root = hermes_root / "research" / "demo-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "---\nname: demo-sync\ndescription: Synced skill.\n---\n\n# Demo Sync\n\nUse carefully.",
        encoding="utf-8",
    )
    (hermes_root / "not-a-skill").mkdir(parents=True)
    try:
        first = service.sync_hermes_skills(roots=[{"path": str(hermes_root), "source_type": "hermes_global"}])
        assert first["summary"]["imported"] == 1
        assert first["summary"]["skipped"] == 1
        skill = service.list_skills()["skills"][0]
        assert skill["name"] == "demo-sync"
        assert skill["description"] == "Synced skill."
        assert skill["source_type"] == "hermes_global"
        assert skill["origin_path"] == str(skill_root.resolve())
        assert skill["local_path"] == str(skill_root.resolve())
        assert skill["source_ref"] == "research/demo-skill"
        assert skill["content_hash"]
        assert skill["last_synced_at"]

        second = service.sync_hermes_skills(roots=[{"path": str(hermes_root), "source_type": "hermes_global"}])
        assert second["summary"]["imported"] == 0
        assert second["summary"]["skipped"] >= 1
        assert len(service.list_skills()["skills"]) == 1

        (skill_root / "SKILL.md").write_text(
            "---\nname: demo-sync\ndescription: Updated skill.\n---\n\n# Demo Sync\n\nUpdated instruction.",
            encoding="utf-8",
        )
        updated = service.sync_hermes_skills(roots=[{"path": str(hermes_root), "source_type": "hermes_global"}])
        assert updated["summary"]["updated"] == 1
        skills = service.list_skills()["skills"]
        assert len(skills) == 1
        assert skills[0]["skill_id"] == skill["skill_id"]
        assert skills[0]["description"] == "Updated skill."
        assert "Updated instruction" in skills[0]["skill_markdown"]
        service.delete_skill(skill["skill_id"])
        assert skill_root.exists()
    finally:
        service.close()


def test_deleted_synced_skill_stays_deleted_after_restart_and_sync(tmp_path):
    hermes_root = tmp_path / ".hermes" / "skills"
    skill_root = hermes_root / "research" / "deleted-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Deleted Skill\n\nDo not restore automatically.", encoding="utf-8")

    service = make_service(tmp_path)
    try:
        synced = service.sync_hermes_skills(
            roots=[{"path": str(hermes_root), "source_type": "hermes_global"}]
        )
        skill_id = synced["results"][0]["skill_id"]
        service.delete_skill(skill_id)
    finally:
        service.close()

    service = make_service(tmp_path, seed_templates=True)
    try:
        synced = service.sync_hermes_skills(
            roots=[{"path": str(hermes_root), "source_type": "hermes_global"}]
        )

        assert service.list_skills()["skills"] == []
        assert synced["summary"]["imported"] == 0
        assert synced["results"][0]["status"] == "skipped"
        assert "用户已删除" in synced["results"][0]["message"]
    finally:
        service.close()


def test_explicit_skill_import_restores_deleted_synced_skill(tmp_path):
    hermes_root = tmp_path / ".hermes" / "skills"
    skill_root = hermes_root / "research" / "restored-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text("# Restored Skill\n\nRestore explicitly.", encoding="utf-8")

    service = make_service(tmp_path)
    try:
        synced = service.sync_hermes_skills(
            roots=[{"path": str(hermes_root), "source_type": "hermes_global"}]
        )
        service.delete_skill(synced["results"][0]["skill_id"])

        restored = service.import_skill(str(skill_root))

        assert restored["name"] == "Restored Skill"
        assert service.get_skill(restored["skill_id"])["source_type"] == "local_dir"
    finally:
        service.close()


def test_failed_skill_reimport_keeps_deletion_record(tmp_path):
    hermes_root = tmp_path / ".hermes" / "skills"
    skill_root = hermes_root / "research" / "failed-restore-skill"
    skill_root.mkdir(parents=True)
    skill_md = skill_root / "SKILL.md"
    skill_md.write_text("# Failed Restore Skill\n\nKeep deletion.", encoding="utf-8")

    service = make_service(tmp_path)
    try:
        synced = service.sync_hermes_skills(
            roots=[{"path": str(hermes_root), "source_type": "hermes_global"}]
        )
        service.delete_skill(synced["results"][0]["skill_id"])
        skill_md.unlink()

        with pytest.raises(AgentRuntimeError, match="SKILL.md"):
            service.import_skill(str(skill_root))

        skill_md.write_text("# Failed Restore Skill\n\nKeep deletion.", encoding="utf-8")
        resynced = service.sync_hermes_skills(
            roots=[{"path": str(hermes_root), "source_type": "hermes_global"}]
        )

        assert resynced["summary"]["imported"] == 0
        assert service.list_skills()["skills"] == []
    finally:
        service.close()


def test_explicit_skill_reinstall_restores_deleted_installed_skill(tmp_path):
    service = make_service(tmp_path)
    skill_root = service.skill_installs_hermes_home / "skills" / "restored-installed-skill"
    skill_root.mkdir(parents=True)
    (skill_root / "SKILL.md").write_text(
        "# Restored Installed Skill\n\nRestore through reinstall.",
        encoding="utf-8",
    )
    try:
        synced = service.sync_yachiyo_installed_skills()
        synced_skill = next(result for result in synced["results"] if result.get("skill_id"))
        service.delete_skill(synced_skill["skill_id"])

        skipped = service.sync_yachiyo_installed_skills()
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text(
            "# Restored Installed Skill\n\nRestore through reinstall.",
            encoding="utf-8",
        )
        restored = service.sync_yachiyo_installed_skills(restore_deleted=True)

        assert skipped["summary"]["imported"] == 0
        assert restored["summary"]["imported"] == 1
        assert service.list_skills()["skills"][0]["name"] == "Restored Installed Skill"
    finally:
        service.close()


def test_skill_install_command_validation_rejects_shell_and_unknown_commands(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="shell"):
            service.install_skill_command("npx skills add owner/repo && rm -rf /")
        with pytest.raises(AgentRuntimeError, match="只允许"):
            service.install_skill_command("npm install owner/repo")
    finally:
        service.close()


def test_skill_install_command_validation_accepts_latest_and_source_shortcuts(tmp_path):
    service = make_service(tmp_path)
    try:
        argv, installer = service._validated_skill_install_argv("skills@latest add owner/repo")
        assert installer == "npx_skills"
        assert argv == ["npx", "skills@latest", "add", "owner/repo", "-a", "hermes-agent", "--copy", "-y"]

        argv, installer = service._validated_skill_install_argv("npx -y skills@latest add owner/repo")
        assert installer == "npx_skills"
        assert argv == ["npx", "-y", "skills@latest", "add", "owner/repo", "-a", "hermes-agent", "--copy"]

        argv, installer = service._validated_skill_install_argv("owner/repo --skill docs")
        assert installer == "npx_skills"
        assert argv == ["npx", "skills@latest", "add", "owner/repo", "--skill", "docs", "-a", "hermes-agent", "--copy", "-y"]

        with pytest.raises(AgentRuntimeError, match="hermes-agent"):
            service._validated_skill_install_argv("npx skills@latest add owner/repo -a codex")
    finally:
        service.close()


def test_skill_dedup_is_scoped_to_yachiyo_or_hermes_library(tmp_path):
    service = make_service(tmp_path)
    hermes_root = tmp_path / ".hermes" / "skills" / "dev" / "shared"
    yachiyo_root = tmp_path / "local-shared"
    content = "# Shared Skill\n\nSame instructions."
    hermes_root.mkdir(parents=True)
    yachiyo_root.mkdir()
    (hermes_root / "SKILL.md").write_text(content, encoding="utf-8")
    (yachiyo_root / "SKILL.md").write_text(content, encoding="utf-8")
    try:
        service.sync_hermes_skills(roots=[{"path": str(tmp_path / ".hermes" / "skills"), "source_type": "hermes_global"}])
        service.import_skill(str(yachiyo_root))
        skills = service.list_skills()["skills"]
        assert len(skills) == 2
        assert {skill["source_type"] for skill in skills} == {"hermes_global", "local_dir"}
    finally:
        service.close()


def test_skill_folders_assign_move_and_delete_without_moving_files(tmp_path):
    service = make_service(tmp_path)
    skill_root = tmp_path / "laravel-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("# Laravel Skill\n\nUse Laravel conventions.", encoding="utf-8")
    try:
        folder = service.create_skill_folder({"name": "Laravel"})
        skill = service.import_skill(str(skill_root), folder["folder_id"])
        assert skill["folder_id"] == folder["folder_id"]
        assert skill["folder_name"] == "Laravel"

        folders = service.list_skill_folders()
        listed = next(item for item in folders["folders"] if item["folder_id"] == folder["folder_id"])
        assert listed["skill_count"] == 1
        assert listed["yachiyo_count"] == 1

        moved = service.update_skill(skill["skill_id"], {"folder_id": ""})
        assert moved["folder_id"] == ""
        assert moved["local_path"].startswith(str(service.skills_dir))

        service.update_skill(skill["skill_id"], {"folder_id": folder["folder_id"]})
        service.delete_skill_folder(folder["folder_id"])
        after_delete = service.get_skill(skill["skill_id"])
        assert after_delete["folder_id"] == ""
        assert after_delete["local_path"].startswith(str(service.skills_dir))
    finally:
        service.close()


def test_delete_skill_folder_can_delete_contained_skills(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    skill_root = tmp_path / "folder-delete-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("# Folder Delete Skill\n\nDelete with folder.", encoding="utf-8")
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "ok"})
    try:
        folder = service.create_skill_folder({"name": "Disposable"})
        skill = service.import_skill(str(skill_root), folder["folder_id"])
        local_path = Path(skill["local_path"])
        agent = service.create_agent({"name": "Folder Delete Agent"})
        service.attach_skill(agent["agent_id"], skill["skill_id"])

        deleted = service.delete_skill_folder(folder["folder_id"], delete_skills=True)

        assert deleted["ok"] is True
        assert deleted["deleted_skill_count"] == 1
        with pytest.raises(KeyError):
            service.get_skill(skill["skill_id"])
        assert service.get_agent(agent["agent_id"])["skill_ids"] == []
        assert not local_path.exists()
    finally:
        service.close()


def test_skill_folder_validation_rejects_missing_folder(tmp_path):
    service = make_service(tmp_path)
    skill_root = tmp_path / "missing-folder-skill"
    skill_root.mkdir()
    (skill_root / "SKILL.md").write_text("# Missing Folder Skill\n\nDemo.", encoding="utf-8")
    try:
        with pytest.raises(AgentRuntimeError, match="文件夹不存在"):
            service.import_skill(str(skill_root), "folder_missing")
    finally:
        service.close()


def test_skill_folder_validation_rejects_duplicate_and_long_names(tmp_path):
    service = make_service(tmp_path)
    try:
        service.create_skill_folder({"name": "Design"})
        with pytest.raises(AgentRuntimeError, match="已存在"):
            service.create_skill_folder({"name": "design"})
        with pytest.raises(AgentRuntimeError, match="不能超过"):
            service.create_skill_folder({"name": "x" * 121})
    finally:
        service.close()


def test_hermes_skill_list_repairs_old_managed_copy_path(tmp_path):
    service = make_service(tmp_path)
    hermes_root = tmp_path / ".hermes" / "skills" / "productivity" / "powerpoint"
    hermes_root.mkdir(parents=True)
    (hermes_root / "SKILL.md").write_text("# Powerpoint\n\nCreate decks.", encoding="utf-8")
    try:
        skill = service.sync_hermes_skills(roots=[{"path": str(tmp_path / ".hermes" / "skills"), "source_type": "hermes_global"}])["results"][0]
        skill_id = skill["skill_id"]
        old_copy = service.skills_dir / skill_id
        old_copy.mkdir(parents=True, exist_ok=True)
        (old_copy / "SKILL.md").write_text("# Old Copy\n\nold", encoding="utf-8")
        service._conn.execute("UPDATE skills SET local_path=? WHERE skill_id=?", (str(old_copy), skill_id))
        service._conn.commit()

        repaired = service.list_skills()["skills"][0]
        assert repaired["local_path"] == str(hermes_root.resolve())
        assert repaired["origin_path"] == str(hermes_root.resolve())
        assert not old_copy.exists()
    finally:
        service.close()


def test_skill_install_command_runs_whitelisted_npx_and_syncs(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    hermes_home = tmp_path / ".hermes"
    recorded: dict[str, list[str]] = {}

    def fake_run(argv, **_kwargs):
        recorded["argv"] = list(argv)
        skill_root = Path(_kwargs["cwd"]) / ".hermes" / "skills" / "dev" / "installed-skill"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text("# Installed Skill\n\nInstalled by npx.", encoding="utf-8")
        (Path(_kwargs["cwd"]) / "skills-lock.json").write_text(
            json.dumps(
                {
                    "version": 1,
                    "skills": {
                        "installed-skill": {
                            "source": "owner/repo",
                            "sourceType": "github",
                            "skillPath": "skills/dev/installed-skill/SKILL.md",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.run", fake_run)
    try:
        result = service.install_skill_command("npx skills add owner/repo")
        assert result["ok"] is True
        assert result["installer"] == "npx_skills"
        assert recorded["argv"] == ["npx", "skills", "add", "owner/repo", "-a", "hermes-agent", "--copy", "-y"]
        assert result["sync"]["summary"]["imported"] == 1
        skill = service.list_skills()["skills"][0]
        assert skill["name"] == "Installed Skill"
        assert skill["source_type"] == "npx_skills"
        assert skill["source_ref"] == "https://github.com/owner/repo/blob/main/skills/dev/installed-skill/SKILL.md"
        assert "/skill-installs/.hermes/skills/" in skill["local_path"]
    finally:
        service.close()


def test_workflow_validation_rejects_branch_and_cycle(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="未知 Workflow 节点类型"):
            service.validate_workflow(
                [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "mystery", "type": "email", "data": {"label": "Email Step"}},
                ],
                [{"source": "start", "target": "mystery"}],
            )

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


def test_workflow_run_rejects_start_only_draft(tmp_path):
    service = make_service(tmp_path)
    try:
        workflow = service.create_workflow(
            {
                "name": "Start Only Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                ],
                "edges": [],
            }
        )

        assert service.validate_workflow(workflow["nodes"], workflow["edges"]) == {"ok": True}
        with pytest.raises(AgentRuntimeError, match="至少需要一个可执行节点"):
            service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
    finally:
        service.close()


def test_workflow_name_validation_and_update_trim(tmp_path):
    service = make_service(tmp_path)
    try:
        nodes = [{"id": "start", "type": "start", "data": {"label": "Start"}}]
        with pytest.raises(AgentRuntimeError, match="名称不能为空"):
            service.create_workflow({"name": "  ", "nodes": nodes, "edges": []})

        workflow = service.create_workflow({"name": "Name Trim Flow", "nodes": nodes, "edges": []})
        updated = service.update_workflow(workflow["workflow_id"], {"name": "  Renamed Flow  "})

        assert updated["name"] == "Renamed Flow"
        with pytest.raises(AgentRuntimeError, match="名称不能为空"):
            service.update_workflow(workflow["workflow_id"], {"name": "   "})
    finally:
        service.close()


def test_workflow_run_rejects_unrunnable_agent_config_before_start(tmp_path):
    service = make_service(tmp_path)
    try:
        agent = service.create_agent(
            {
                "name": "Broken Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "provider": "openai_compatible",
                    "base_url": "https://api.example.test/v1",
                },
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Broken Agent Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Broken Agent", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        with pytest.raises(AgentRuntimeError, match="Custom API 配置不完整"):
            service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        assert service.list_runs()["runs"] == []
    finally:
        service.close()


def test_workflow_run_rejects_follow_main_agent_without_default_profile(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.get_model_profile_service", lambda: FakeNoDefaultProfileService())
    try:
        agent = service.create_agent(
            {
                "name": "Follow Main Agent",
                "model_mode": "follow_main",
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Follow Main Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Follow Main", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        with pytest.raises(AgentRuntimeError, match="缺少可运行的 Chat Profile"):
            service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        assert service.list_runs()["runs"] == []
    finally:
        service.close()


def test_linear_workflow_executes_agent_nodes_in_order(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Profile result"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Agent A", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Agent B", "model_mode": "custom_api", "model_config": model_config})
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
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "a", "kind": "agent", "label": "Agent A"},
            {"id": "b", "kind": "agent", "label": "Agent B"},
        ]
        assert run["result"] == "Profile result"
        group = service.get_run_group(run["run_group_id"])
        assert group["source"] == "workflow"
        assert len(group["child_run_ids"]) == 3
    finally:
        service.close()


def test_updated_workflow_run_uses_latest_saved_graph(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    contexts: list[str] = []
    responses = iter(["Fresh design", "Fresh code"])

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        old_agent = service.create_agent({"name": "Old Agent", "model_mode": "custom_api", "model_config": model_config})
        design_agent = service.create_agent({"name": "Fresh Design", "model_mode": "custom_api", "model_config": model_config})
        coding_agent = service.create_agent({"name": "Fresh Coding", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Save And Run Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "old", "type": "agent", "data": {"label": "Old Agent", "agent_id": old_agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "old"}],
            }
        )
        service.update_workflow(
            workflow["workflow_id"],
            {
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Fresh Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "coding", "type": "agent", "data": {"label": "Fresh Coding", "agent_id": coding_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "coding"},
                ],
            },
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship latest graph"})

        assert run["status"] == "completed"
        assert run["result"] == "Fresh code"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "design", "kind": "agent", "label": "Fresh Design"},
            {"id": "coding", "kind": "agent", "label": "Fresh Coding"},
        ]
        agent_events = [event for event in run["timeline"] if event["event"] == "workflow.node.agent"]
        assert [event["workflow_node_id"] for event in agent_events] == ["design", "coding"]
        assert [event["workflow_node_label"] for event in agent_events] == ["Fresh Design", "Fresh Coding"]
        group = service.get_run_group(run["run_group_id"])
        child_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["runnable_id"] for child in child_runs] == [design_agent["agent_id"], coding_agent["agent_id"]]
        assert len(contexts) == 2
        assert "Old Agent" not in "\n".join(contexts)
    finally:
        service.close()


def test_workflow_child_agents_keep_goal_and_receive_prior_result_as_upstream(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    contexts = []
    responses = iter(["Design output", "Code output"])

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Design Agent", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Coding Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Context Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Design Agent", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Coding Agent", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "completed"
        assert run["result"] == "Code output"
        assert "# User Goal\nShip it" in contexts[0]
        assert "# Upstream Context\nNone" in contexts[0]
        assert "# User Goal\nShip it" in contexts[1]
        assert "# Upstream Context\nDesign output" in contexts[1]
        assert "# User Goal\nDesign output" not in contexts[1]
        assert contexts[1].count("Design output") == 1

        group = service.get_run_group(run["run_group_id"])
        agent_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["user_goal"] for child in agent_runs] == ["Ship it", "Ship it"]
    finally:
        service.close()


def test_workflow_agent_nodes_can_define_step_tasks(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    contexts: list[str] = []
    responses = iter(["Research notes", "Implementation plan"])

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        research_agent = service.create_agent({"name": "Research Agent", "model_mode": "custom_api", "model_config": model_config})
        coding_agent = service.create_agent({"name": "Coding Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Step Task Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "research",
                        "type": "agent",
                        "data": {
                            "label": "Research",
                            "agent_id": research_agent["agent_id"],
                            "task": "Collect constraints and summarize the tradeoffs.",
                        },
                    },
                    {
                        "id": "coding",
                        "type": "agent",
                        "data": {
                            "label": "Coding",
                            "agent_id": coding_agent["agent_id"],
                            "instructions": "Turn the research notes into an implementation plan.",
                        },
                    },
                ],
                "edges": [
                    {"source": "start", "target": "research"},
                    {"source": "research", "target": "coding"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship feature X"})

        assert run["status"] == "completed"
        assert "# User Goal\nCollect constraints and summarize the tradeoffs.\n\nWorkflow Goal:\nShip feature X" in contexts[0]
        assert "# Upstream Context\nNone" in contexts[0]
        assert "# User Goal\nTurn the research notes into an implementation plan.\n\nWorkflow Goal:\nShip feature X" in contexts[1]
        assert "# Upstream Context\nResearch notes" in contexts[1]

        group = service.get_run_group(run["run_group_id"])
        agent_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["user_goal"] for child in agent_runs] == [
            "Collect constraints and summarize the tradeoffs.\n\nWorkflow Goal:\nShip feature X",
            "Turn the research notes into an implementation plan.\n\nWorkflow Goal:\nShip feature X",
        ]
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"][1]["task"] == "Collect constraints and summarize the tradeoffs."
        agent_events = [event for event in run["timeline"] if event["event"] == "workflow.node.agent"]
        assert [event["workflow_node_task"] for event in agent_events] == [
            "Collect constraints and summarize the tradeoffs.",
            "Turn the research notes into an implementation plan.",
        ]
    finally:
        service.close()


def test_workflow_rejects_missing_and_disabled_agent_nodes(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="没有选择 Agent"):
            service.create_workflow(
                {
                    "name": "Missing Agent Flow",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {"id": "agent", "type": "agent", "data": {"label": "Agent Step"}},
                    ],
                    "edges": [{"source": "start", "target": "agent"}],
                }
            )

        with pytest.raises(AgentRuntimeError, match="引用了不存在的 Agent"):
            service.create_workflow(
                {
                    "name": "Unknown Agent Flow",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {
                            "id": "agent",
                            "type": "agent",
                            "data": {"label": "Agent Step", "agent_id": "agent_missing"},
                        },
                    ],
                    "edges": [{"source": "start", "target": "agent"}],
                }
            )

        disabled = service.create_agent({"name": "Disabled Agent", "enabled": False})
        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.create_workflow(
                {
                    "name": "Disabled Agent Flow",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {
                            "id": "agent",
                            "type": "agent",
                            "data": {"label": "Agent Step", "agent_id": disabled["agent_id"]},
                        },
                    ],
                    "edges": [{"source": "start", "target": "agent"}],
                }
            )
    finally:
        service.close()


def test_workflow_run_rejects_agent_disabled_after_save(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": "Should not run"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Later Disabled",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Later Disabled Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Agent Step", "agent_id": agent["agent_id"]},
                    },
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )
        service.update_agent(agent["agent_id"], {"enabled": False})

        with pytest.raises(AgentRuntimeError, match="已停用"):
            service.create_workflow_run(
                {"workflow_id": workflow["workflow_id"], "user_goal": "Run disabled agent"}
            )

        assert calls == []
    finally:
        service.close()


def test_workflow_approval_node_pauses_and_resumes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": f"Agent {len(calls)} complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Before Approval", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "After Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Human Gate Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Before Approval", "agent_id": agent_a["agent_id"]}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {
                            "label": "人工确认",
                            "criteria": "确认设计输出已经覆盖验收点，再继续编码。",
                        },
                    },
                    {"id": "b", "type": "agent", "data": {"label": "After Approval", "agent_id": agent_b["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "gate"},
                    {"source": "gate", "target": "b"},
                    {"source": "b", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "approval_required"
        assert run["result"] == "等待审批：人工确认"
        assert run["pending_approval"]["tool"] == "workflow.approval"
        assert run["pending_approval"]["input_preview"]["checkpoint"] == "人工确认"
        assert run["pending_approval"]["input_preview"]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert run["pending_approval"]["input_preview"]["context"] == "Agent 1 complete"
        assert "workflow_context" not in run["pending_approval"]
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"][2]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert [event["event"] for event in run["timeline"] if event["event"] == "workflow.node.agent"] == [
            "workflow.node.agent",
        ]
        start_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.start")
        assert start_event["workflow_node_id"] == "start"
        assert start_event["status"] == "completed"
        approval_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.approval_required")
        assert approval_event["workflow_node_id"] == "gate"
        assert approval_event["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert approval_event["status"] == "approval_required"
        assert service.get_run_group(run["run_group_id"])["status"] == "approval_required"

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Agent 2 complete"
        assert resumed["pending_approval"] == {}
        assert len(calls) == 2
        approval_approved = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.approval_approved")
        assert approval_approved["detail"] == "人工确认"
        assert approval_approved["workflow_node_id"] == "gate"
        assert approval_approved["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert approval_approved["input_preview"]["checkpoint"] == "人工确认"
        assert approval_approved["input_preview"]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert approval_approved["input_preview"]["context"] == "Agent 1 complete"
        assert approval_approved["status"] == "completed"
        assert [event["event"] for event in resumed["timeline"]].count("workflow.node.agent") == 2
        artifact_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.artifact")
        assert artifact_event["workflow_node_id"] == "summary"
        assert artifact_event["status"] == "completed"
        assert artifact_event["artifact"]["path"] == "summary.md"
        assert any(artifact.get("kind") == "workflow_artifact" for artifact in resumed["artifacts"])
        assert service.get_run_group(run["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_cancel_workflow_approval_updates_group_and_step_info(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": f"Agent {len(calls)} complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Before Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Cancelable Gate Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Before Approval", "agent_id": agent["agent_id"]}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {
                            "label": "人工确认",
                            "criteria": "确认设计输出已经覆盖验收点，再继续编码。",
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "gate"},
                    {"source": "gate", "target": "summary"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        assert run["status"] == "approval_required"
        assert service.get_run_group(run["run_group_id"])["status"] == "approval_required"

        cancelled = service.cancel_run(run["run_id"])

        assert cancelled["status"] == "cancelled"
        assert cancelled["pending_approval"] == {}
        assert cancelled["result"] == "Workflow 已取消：人工确认"
        assert len(calls) == 1
        cancelled_event = next(event for event in cancelled["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["detail"] == "人工确认 cancelled"
        assert cancelled_event["workflow_node_id"] == "gate"
        assert cancelled_event["workflow_node_kind"] == "approval"
        assert cancelled_event["workflow_node_label"] == "人工确认"
        assert cancelled_event["status"] == "cancelled"
        group = service.get_run_group(run["run_group_id"])
        assert group["status"] == "cancelled"
        assert group["summary"] == "Workflow 已取消：人工确认"
    finally:
        service.close()


def test_workflow_approval_resume_uses_runtime_snapshot_after_workflow_edit(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        context = str(messages[1]["content"])
        assert "Name: Original After Approval" in context
        assert "Name: Edited After Approval" not in context
        return {"content": "Original agent complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        original_agent = service.create_agent({"name": "Original After Approval", "model_mode": "custom_api", "model_config": model_config})
        edited_agent = service.create_agent({"name": "Edited After Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Editable Paused Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {"id": "after", "type": "agent", "data": {"label": "Original After Approval", "agent_id": original_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Wait then run"})
        assert run["status"] == "approval_required"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_snapshot"]["nodes"][2]["data"]["agent_id"] == original_agent["agent_id"]

        service.update_workflow(
            workflow["workflow_id"],
            {
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {"id": "after", "type": "agent", "data": {"label": "Edited After Approval", "agent_id": edited_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            },
        )

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Original agent complete"
        assert len(calls) == 1
        agent_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "after"
        assert agent_event["workflow_node_label"] == "Original After Approval"
    finally:
        service.close()


def test_workflow_approval_node_reject_cancels_run(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": "First step complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Before Approval", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Reject Gate Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Before Approval", "agent_id": agent["agent_id"]}},
                    {
                        "id": "gate",
                        "type": "approval",
                        "data": {
                            "label": "人工确认",
                            "criteria": "确认设计输出已经覆盖验收点，再继续编码。",
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "gate"},
                    {"source": "gate", "target": "summary"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        rejected = service.reject_run_approval(run["run_id"], "先暂停")

        assert rejected["status"] == "cancelled"
        assert rejected["pending_approval"] == {}
        assert rejected["result"] == "Workflow 审批已拒绝：先暂停"
        assert len(calls) == 1
        rejected_event = next(event for event in rejected["timeline"] if event["event"] == "workflow.node.approval_rejected")
        assert rejected_event["detail"] == "先暂停"
        assert rejected_event["workflow_node_id"] == "gate"
        assert rejected_event["workflow_node_kind"] == "approval"
        assert rejected_event["workflow_node_label"] == "人工确认"
        assert rejected_event["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert rejected_event["input_preview"]["checkpoint"] == "人工确认"
        assert rejected_event["input_preview"]["criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert rejected_event["input_preview"]["context"] == "First step complete"
        assert rejected_event["status"] == "cancelled"
        cancelled_event = next(event for event in rejected["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["detail"] == "先暂停"
        assert cancelled_event["workflow_node_id"] == "gate"
        assert cancelled_event["workflow_node_kind"] == "approval"
        assert cancelled_event["workflow_node_label"] == "人工确认"
        assert cancelled_event["workflow_node_approval_criteria"] == "确认设计输出已经覆盖验收点，再继续编码。"
        assert cancelled_event["input_preview"]["checkpoint"] == "人工确认"
        assert cancelled_event["status"] == "cancelled"
        group = service.get_run_group(run["run_group_id"])
        assert group["status"] == "cancelled"
        assert group["summary"] == "Workflow 审批已拒绝：先暂停"
    finally:
        service.close()


def test_workflow_duplicate_artifact_labels_write_unique_paths(tmp_path):
    service = make_service(tmp_path)
    try:
        workflow = service.create_workflow(
            {
                "name": "Duplicate Artifact Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "summary-a", "type": "artifact", "data": {"label": "Summary"}},
                    {"id": "summary-b", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "summary-a"},
                    {"source": "summary-a", "target": "summary-b"},
                ],
            }
        )

        run = service.create_workflow_run(
            {"workflow_id": workflow["workflow_id"], "user_goal": "Write duplicate artifacts"}
        )

        assert run["status"] == "completed"
        artifacts = [artifact for artifact in run["artifacts"] if artifact.get("kind") == "workflow_artifact"]
        assert [artifact["path"] for artifact in artifacts] == ["summary.md", "summary-2.md"]
        assert [artifact["workflow_node_id"] for artifact in artifacts] == ["summary-a", "summary-b"]
        assert service.read_run_artifact(run["run_id"], "summary.md")["content"] == "Write duplicate artifacts"
        assert service.read_run_artifact(run["run_id"], "summary-2.md")["content"] == "Write duplicate artifacts"
        artifact_events = [event for event in run["timeline"] if event["event"] == "workflow.node.artifact"]
        assert [event["artifact"]["path"] for event in artifact_events] == ["summary.md", "summary-2.md"]
        assert [event["workflow_node_id"] for event in artifact_events] == ["summary-a", "summary-b"]
    finally:
        service.close()


def test_workflow_artifact_nodes_can_use_configured_paths(tmp_path):
    service = make_service(tmp_path)
    try:
        workflow = service.create_workflow(
            {
                "name": "Configured Artifact Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "report-a",
                        "type": "artifact",
                        "data": {"label": "Report A", "artifact_path": "reports/final-report.md"},
                    },
                    {
                        "id": "report-b",
                        "type": "artifact",
                        "data": {"label": "Report B", "artifact_path": "reports/final-report.md"},
                    },
                    {
                        "id": "notes",
                        "type": "artifact",
                        "data": {"label": "Notes", "artifact_path": "reports/notes"},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "report-a"},
                    {"source": "report-a", "target": "report-b"},
                    {"source": "report-b", "target": "notes"},
                ],
            }
        )

        run = service.create_workflow_run(
            {"workflow_id": workflow["workflow_id"], "user_goal": "Configured artifact content"}
        )

        assert run["status"] == "completed"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert [item.get("artifact_path") for item in started_event["workflow_path"] if item.get("kind") == "artifact"] == [
            "reports/final-report.md",
            "reports/final-report-2.md",
            "reports/notes.md",
        ]
        artifacts = [artifact for artifact in run["artifacts"] if artifact.get("kind") == "workflow_artifact"]
        assert [artifact["path"] for artifact in artifacts] == [
            "reports/final-report.md",
            "reports/final-report-2.md",
            "reports/notes.md",
        ]
        assert service.read_run_artifact(run["run_id"], "reports/final-report.md")["content"] == "Configured artifact content"
        assert service.read_run_artifact(run["run_id"], "reports/final-report-2.md")["content"] == "Configured artifact content"
        assert service.read_run_artifact(run["run_id"], "reports/notes.md")["content"] == "Configured artifact content"
    finally:
        service.close()


def test_workflow_rejects_invalid_artifact_path(tmp_path):
    service = make_service(tmp_path)
    try:
        with pytest.raises(AgentRuntimeError, match="Artifact 节点 Report 的产物路径无效"):
            service.create_workflow(
                {
                    "name": "Bad Artifact Path",
                    "nodes": [
                        {"id": "start", "type": "start", "data": {"label": "Start"}},
                        {
                            "id": "report",
                            "type": "artifact",
                            "data": {"label": "Report", "artifact_path": "../escape.md"},
                        },
                    ],
                    "edges": [{"source": "start", "target": "report"}],
                }
            )
    finally:
        service.close()


def test_workflow_approval_resume_fails_if_next_agent_was_disabled(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {"content": "Should not run"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Next Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Approval Then Agent",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Next Agent", "agent_id": agent["agent_id"]},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "agent"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Wait first"})
        service.update_agent(agent["agent_id"], {"enabled": False})

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "failed"
        assert "已停用" in resumed["result"]
        assert calls == []
        failed_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "agent"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Next Agent"
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_workflow_canvas_spec_exposes_participants_and_executes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    responses = iter(["Design brief", "Code patch"])

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": next(responses)}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design = service.create_agent({
            "name": "Design Agent",
            "nickname": "Design",
            "avatar_url": "https://example.test/design.png",
            "model_mode": "custom_api",
            "model_config": model_config,
        })
        coding = service.create_agent({
            "name": "Coding Agent",
            "nickname": "Code",
            "avatar_url": "https://example.test/code.png",
            "model_mode": "custom_api",
            "model_config": model_config,
        })
        workflow = service.create_workflow(
            {
                "name": "Web Design Chain",
                "nodes": [
                    {"id": "start", "type": "start", "position": {"x": 40, "y": 120}, "data": {"label": "Start", "kind": "start"}},
                    {"id": "design", "type": "agent", "position": {"x": 260, "y": 120}, "data": {"label": "Design", "kind": "agent", "agent_id": design["agent_id"]}},
                    {"id": "coding", "type": "agent", "position": {"x": 480, "y": 120}, "data": {"label": "Coding", "kind": "agent", "agent_id": coding["agent_id"]}},
                ],
                "edges": [
                    {"id": "edge-start-design", "source": "start", "target": "design"},
                    {"id": "edge-design-coding", "source": "design", "target": "coding"},
                ],
            }
        )

        runnable = next(item for item in service.list_runnables()["runnables"] if item["id"] == workflow["workflow_id"])
        run = service.create_run_for_runnable(runnable_id=workflow["workflow_id"], user_goal="Build a landing page")

        assert runnable["kind"] == "workflow"
        assert [participant["name"] for participant in runnable["participants"]] == ["Design Agent", "Coding Agent"]
        assert [participant["avatar_url"] for participant in runnable["participants"]] == [
            "https://example.test/design.png",
            "https://example.test/code.png",
        ]
        assert all("tool_policy" in participant for participant in runnable["participants"])
        assert all("artifact.write" in participant["tool_policy"]["allowed_tools"] for participant in runnable["participants"])
        assert run["status"] == "completed"
        assert run["result"] == "Code patch"
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 2
        assert service.get_run_group(run["run_group_id"])["source"] == "workflow"
    finally:
        service.close()


def test_list_runs_returns_roots_and_standalone_agents_only(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "OK"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Workflow Agent A", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Workflow Agent B", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "List Runs Flow",
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

        workflow_run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})
        standalone_agent_run = service.create_agent_run({"agent_id": agent_a["agent_id"], "user_goal": "Run alone"})

        listed = service.list_runs(limit=20)["runs"]
        listed_ids = {run["run_id"] for run in listed}
        group = service.get_run_group(workflow_run["run_group_id"])
        workflow_child_run_ids = [
            run_id
            for run_id in group["child_run_ids"]
            if run_id != workflow_run["run_id"]
        ]

        assert workflow_run["run_id"] in listed_ids
        assert standalone_agent_run["run_id"] in listed_ids
        assert not any(run_id in listed_ids for run_id in workflow_child_run_ids)
        assert service.get_run(workflow_child_run_ids[0])["run_group_source"] == "workflow"
        assert service.get_run(standalone_agent_run["run_id"])["run_group_source"] == "agent"
    finally:
        service.close()


def test_list_runs_hides_workflow_child_agents_for_delegated_workflows(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "OK"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Delegated Workflow Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Delegated Workflow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Agent", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        delegated = service.delegate_runnable(
            kind="workflow",
            runnable_id=workflow["workflow_id"],
            user_goal="Run delegated workflow",
        )
        group = service.get_run_group(delegated["run_group_id"])
        child_agent_run_ids = [
            run_id
            for run_id in group["child_run_ids"]
            if service.get_run(run_id)["kind"] == "agent_run"
        ]
        listed_ids = {run["run_id"] for run in service.list_runs(limit=20)["runs"]}

        assert service.get_run_group(delegated["run_group_id"])["source"] == "delegation"
        assert delegated["run_id"] in listed_ids
        assert child_agent_run_ids
        assert not any(run_id in listed_ids for run_id in child_agent_run_ids)
    finally:
        service.close()


def test_list_runs_hides_workflow_child_agents_for_custom_workflow_sources(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "OK"})
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Custom Source Workflow Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Custom Source Workflow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "agent", "type": "agent", "data": {"label": "Agent", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "agent"}],
            }
        )

        workflow_run = service.create_workflow_run(
            {
                "workflow_id": workflow["workflow_id"],
                "user_goal": "Run workflow from a specific smoke source",
                "source": "workflow_child_artifact_smoke",
            }
        )
        group = service.get_run_group(workflow_run["run_group_id"])
        child_agent_run_ids = [
            run_id
            for run_id in group["child_run_ids"]
            if service.get_run(run_id)["kind"] == "agent_run"
        ]
        listed_ids = {run["run_id"] for run in service.list_runs(limit=20)["runs"]}

        assert group["source"] == "workflow_child_artifact_smoke"
        assert workflow_run["run_id"] in listed_ids
        assert child_agent_run_ids
        assert not any(run_id in listed_ids for run_id in child_agent_run_ids)
    finally:
        service.close()


def test_workflow_stops_when_child_agent_fails(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(*_args, **_kwargs):
        calls.append("called")
        raise RuntimeError("model exploded")

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent({"name": "Failing Agent", "model_mode": "custom_api", "model_config": model_config})
        agent_b = service.create_agent({"name": "Skipped Agent", "model_mode": "custom_api", "model_config": model_config})
        workflow = service.create_workflow(
            {
                "name": "Fail Fast Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Failing Agent", "agent_id": agent_a["agent_id"]}},
                    {"id": "b", "type": "agent", "data": {"label": "Skipped Agent", "agent_id": agent_b["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship it"})

        assert run["status"] == "failed"
        assert run["result"] == "model exploded"
        assert calls == ["called"]
        assert [event["event"] for event in run["timeline"]].count("workflow.node.agent") == 1
        failed_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "a"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Failing Agent"
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_agent_execution_backend_legacy_values_normalize_to_yachiyo(tmp_path):
    service = make_service(tmp_path)
    try:
        hermes_agent = service.create_agent({"name": "Hermes Agent"})
        assert hermes_agent["execution_backend"] == "yachiyo_profile"
        run = service.create_agent_run({"agent_id": hermes_agent["agent_id"], "user_goal": "Plan"})
        assert run["status"] == "failed"
        assert "Chat Profile" in run["result"]

        external = service.create_agent({"name": "CLI Agent", "execution_backend": "external_cli"})
        assert external["execution_backend"] == "yachiyo_profile"
        external_run = service.create_agent_run({"agent_id": external["agent_id"], "user_goal": "Review"})
        assert external_run["status"] == "failed"
        assert "Chat Profile" in external_run["result"]
    finally:
        service.close()


def test_delegation_targets_and_delegate_run(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Delegated result"})
    try:
        agent = service.create_agent(
            {
                "name": "Delegated Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
            }
        )
        targets = service.list_delegation_targets()
        assert any(item["name"] == "Delegated Agent" for item in targets["agents"])

        result = service.delegate_runnable(kind="agent", name="Delegated Agent", user_goal="Do the work")
        assert result["ok"] is True
        assert result["runnable"]["id"] == agent["agent_id"]
        assert result["result"] == "Delegated result"
        run = service.get_run(result["run_id"])
        assert run["status"] == "completed"
        assert run["run_group_id"]
    finally:
        service.close()


def test_agent_run_executes_native_tool_call_and_continues(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello native tools", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "workspace_read" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "README.md"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "hello native tools" in messages[-1]["content"]
        return {"content": "Read complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Read README"})

        assert run["status"] == "completed"
        assert run["result"] == "Read complete"
        tool_event = next(event for event in run["timeline"] if event["event"] == "agent.tool.call" and event["detail"] == "workspace.read")
        assert tool_event["input_preview"]["path"] == "README.md"
        assert tool_event["result"]["ok"] is True
    finally:
        service.close()


def test_agent_run_can_recover_from_workspace_tool_shape_error(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    (workdir / "README.md").write_text("hello", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bad_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": "."})},
                    }
                ],
            }
        if len(calls) == 2:
            assert messages[-1]["role"] == "tool"
            assert "suggested_tool" in messages[-1]["content"]
            assert "workspace.list" in messages[-1]["content"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_list",
                        "type": "function",
                        "function": {"name": "workspace_list", "arguments": json.dumps({"path": "."})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "README.md" in messages[-1]["content"]
        return {"content": "Recovered and listed files"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Recovering Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read", "workspace.list"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Inspect repo"})

        assert run["status"] == "completed"
        assert run["result"] == "Recovered and listed files"
        tool_results = [
            event["result"]
            for event in run["timeline"]
            if event["event"] == "agent.tool.call" and isinstance(event.get("result"), dict)
        ]
        assert tool_results[0]["ok"] is False
        assert tool_results[0]["suggested_tool"] == "workspace.list"
        assert tool_results[1]["ok"] is True
    finally:
        service.close()


def test_agent_run_recovers_from_absolute_workspace_path_with_terminal(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    external_file = tmp_path / "external.txt"
    external_file.write_text("outside workspace", encoding="utf-8")
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert "Never pass absolute paths to workspace tools" in messages[0]["content"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_bad_read",
                        "type": "function",
                        "function": {"name": "workspace_read", "arguments": json.dumps({"path": str(external_file)})},
                    }
                ],
            }
        if len(calls) == 2:
            assert messages[-1]["role"] == "tool"
            assert "suggested_tool" in messages[-1]["content"]
            assert "terminal.run" in messages[-1]["content"]
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": f"cat {external_file}"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "outside workspace" in messages[-1]["content"]
        return {"content": "Recovered with terminal"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "External Path Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read", "terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Read the external file"})

        assert run["status"] == "approval_required"
        workspace_event = next(
            event
            for event in run["timeline"]
            if event["event"] == "agent.tool.call" and event["detail"] == "workspace.read"
        )
        assert workspace_event["result"]["ok"] is False
        assert workspace_event["result"]["suggested_tool"] == "terminal.run"

        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Recovered with terminal"
    finally:
        service.close()


def test_agent_tool_loop_limit_includes_last_tool_detail(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": f"call_bad_read_{len(calls)}",
                    "type": "function",
                    "function": {"name": "workspace_read", "arguments": json.dumps({"path": "."})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Looping Reader",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read", "workspace.list"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Inspect repo"})

        assert run["status"] == "failed"
        assert "工具循环超过上限" in run["result"]
        assert "最后一次工具调用：workspace.read" in run["result"]
        assert "建议工具：workspace.list" in run["result"]
    finally:
        service.close()


def test_agent_tool_loop_limit_after_artifact_write_completes_with_artifact(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": json.dumps(
                {
                    "action": "tool",
                    "tool": "artifact.write",
                    "input": {"path": "done.md", "content": "done"},
                }
            )
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Looping Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write artifact"})

        assert run["status"] == "completed"
        assert "模型在工具循环上限前没有返回最终总结" in run["result"]
        assert "done.md" in run["result"]
        assert any(artifact.get("path") == "done.md" for artifact in run["artifacts"])
        assert service.read_run_artifact(run["run_id"], "done.md")["content"] == "done"
        assert any(event["event"] == "agent.tool.loop_limit_completed" for event in run["timeline"])
        assert len(calls) == 50
    finally:
        service.close()


def test_agent_run_json_fallback_writes_artifact(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"action": "tool", "tool": "artifact.write", "input": {"path": "notes.md", "content": "hello"}})}
        assert "Tool result for artifact.write" in messages[-1]["content"]
        return {"content": "Artifact done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Artifact Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write artifact"})

        assert run["status"] == "completed"
        assert any(artifact.get("path") == "notes.md" for artifact in run["artifacts"])
        assert service.read_run_artifact(run["run_id"], "notes.md")["content"] == "hello"
    finally:
        service.close()


def test_agent_output_contract_expands_diff_rules_in_runtime_context(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        return {"content": "Inline code response"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Diff Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch", "artifact.write"]},
                "output_contract": "diff",
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Show a tiny function without changing files"})

        assert run["status"] == "completed"
        assert calls
        system_prompt = calls[0]["messages"][0]["content"]
        context = calls[0]["messages"][1]["content"]
        assert "Do not request a tool solely because of the output contract" in system_prompt
        assert "If the user asks not to create, save, write, or modify files" in system_prompt
        assert "If the user asks not to run or execute commands" in system_prompt
        assert "Contract: diff" in context
        assert "Do not call workspace.write_patch merely because the output contract is diff" in context
        assert "If no file change is requested, provide code inline." in context
    finally:
        service.close()


def test_agent_run_skips_write_tool_when_user_goal_forbids_file_changes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append({"messages": messages, "tools": tools})
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_write",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": json.dumps({"path": "scripts/demo.py", "content": "print('demo')"}),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        tool_result = json.loads(messages[-1]["content"])
        assert tool_result["blocked_by_user_goal"] is True
        assert tool_result["tool"] == "workspace.write_patch"
        assert "inline" in tool_result["hint"]
        return {"content": "Here is the code inline."}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "No File Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch", "artifact.write"]},
                "output_contract": "diff",
            }
        )
        run = service.create_agent_run({
            "agent_id": agent["agent_id"],
            "user_goal": "Show a tiny function without changing files",
        })

        assert run["status"] == "completed"
        assert run["result"] == "Here is the code inline."
        assert run["pending_approval"] == {}
        skipped_event = next(event for event in run["timeline"] if event["event"] == "agent.tool.skipped" and event["detail"] == "workspace.write_patch")
        assert skipped_event["input_preview"]["path"] == "scripts/demo.py"
        assert skipped_event["result"]["blocked_by_user_goal"] is True
        assert not any(event["event"] == "agent.tool.approval_required" for event in run["timeline"])
    finally:
        service.close()


def test_agent_run_skips_artifact_tool_when_chinese_goal_says_inline_only(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"action": "tool", "tool": "artifact.write", "input": {"path": "card.html", "content": "<div>card</div>"}})}
        assert "blocked_by_user_goal" in messages[-1]["content"]
        assert "inline" in messages[-1]["content"]
        return {"content": "完整代码如下：<div>card</div>"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Inline Design Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["artifact.write"]},
                "output_contract": "artifacts",
            }
        )
        run = service.create_agent_run({
            "agent_id": agent["agent_id"],
            "user_goal": "用纯 HTML + CSS 制作一个简单卡片组件，代码完整展示即可。",
        })

        assert run["status"] == "completed"
        assert run["result"] == "完整代码如下：<div>card</div>"
        assert not any(artifact.get("path") == "card.html" for artifact in run["artifacts"])
        assert not any(artifact.get("kind") == "tool_artifact" for artifact in run["artifacts"])
        assert run["pending_approval"] == {}
        assert any(event["event"] == "agent.tool.skipped" and event["detail"] == "artifact.write" for event in run["timeline"])
    finally:
        service.close()


def test_workflow_child_agent_no_run_goal_does_not_request_terminal_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": "python3 demo.py"})},
                    }
                ],
            }
        assert "blocked_by_user_goal" in messages[-1]["content"]
        assert "不要运行命令或脚本" in messages[-1]["content"]
        return {"content": "代码示例已经 inline 展示。"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "No Run Coding Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "No Run Workflow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": agent["agent_id"]}},
                ],
                "edges": [{"source": "start", "target": "code"}],
            }
        )
        run = service.create_workflow_run({
            "workflow_id": workflow["workflow_id"],
            "user_goal": "写一个 Python 示例即可，不需要运行命令或脚本。",
        })

        assert run["status"] == "completed"
        assert run["result"] == "代码示例已经 inline 展示。"
        assert run["pending_approval"] == {}
        assert service.get_run_group(run["run_group_id"])["status"] == "completed"
        child_run_id = next(run_id for run_id in service.get_run_group(run["run_group_id"])["child_run_ids"] if run_id != run["run_id"])
        child = service.get_run(child_run_id)
        assert child["status"] == "completed"
        assert child["pending_approval"] == {}
        assert any(event["event"] == "agent.tool.skipped" and event["detail"] == "terminal.run" for event in child["timeline"])
        assert not any(event["event"] == "agent.tool.approval_required" for event in child["timeline"])
    finally:
        service.close()


def test_agent_run_explicit_terminal_goal_not_blocked_by_downstream_no_execute_text(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf terminal-explicit-smoke; exit 7"}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Explicit Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({
            "agent_id": agent["agent_id"],
            "user_goal": "必须请求 terminal.run 执行命令。不要执行后续 artifact 节点，只使用 terminal.run。",
        })

        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "terminal.run"
        assert not any(event["event"] == "agent.tool.skipped" and event["detail"] == "terminal.run" for event in run["timeline"])
    finally:
        service.close()


def test_agent_run_denies_unallowed_tool(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "echo no"})},
                }
            ],
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Denied Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.read"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})

        assert run["status"] == "failed"
        assert "未授权工具" in run["result"]
        assert any(event["event"] == "agent.tool.denied" for event in run["timeline"])
    finally:
        service.close()


def test_workflow_parent_records_child_agent_artifact_refs(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {"content": json.dumps({"action": "tool", "tool": "artifact.write", "input": {"path": "design.md", "content": "design artifact"}})}
        if len(calls) == 2:
            assert "Tool result for artifact.write" in messages[-1]["content"]
            return {"content": "Design done"}
        return {"content": "Code done"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design_agent = service.create_agent(
            {
                "name": "Design Artifact Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        coding_agent = service.create_agent(
            {
                "name": "Coding Summary Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Artifact Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": coding_agent["agent_id"]}},
                ],
                "edges": [
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "code"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Ship artifacts"})

        assert run["status"] == "completed"
        child_artifact_refs = [
            artifact
            for artifact in run["artifacts"]
            if artifact.get("kind") == "workflow_child_artifact"
        ]
        assert all(artifact.get("artifact_kind") != "context" for artifact in child_artifact_refs)
        design_ref = next(artifact for artifact in child_artifact_refs if artifact.get("path") == "design.md")
        assert design_ref["workflow_step_label"] == "Design"
        assert design_ref["source_runnable_name"] == "Design Artifact Agent"
        assert service.read_run_artifact(design_ref["source_run_id"], "design.md")["content"] == "design artifact"
        design_event = next(
            event
            for event in run["timeline"]
            if event["event"] == "workflow.node.agent" and event["detail"] == "Design"
        )
        assert design_event["status"] == "completed"
        assert design_event["result"] == "Design done"
        assert design_event["artifact_count"] >= 1
    finally:
        service.close()


def test_agent_run_pauses_for_terminal_approval_and_resumes(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf approved"}),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "approved" in messages[-1]["content"]
        return {"content": "Command complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})

        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "terminal.run"
        assert "messages" not in run["pending_approval"]
        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Command complete"
        approved_event = next(event for event in resumed["timeline"] if event["event"] == "agent.tool.approval_approved")
        assert approved_event["detail"] == "terminal.run"
        assert approved_event["input_preview"]["command"] == "printf approved"
        assert approved_event["status"] == "completed"
        assert service.get_run_group(resumed["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_agent_run_consecutive_terminal_approvals_update_pending_request(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_first_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf first-approved"}),
                        },
                    },
                    {
                        "id": "call_second_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf second-approved"}),
                        },
                    },
                ],
            }
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert any("first-approved" in message.get("content", "") for message in tool_messages)
        assert any("second-approved" in message.get("content", "") for message in tool_messages)
        return {"content": "Both terminal approvals completed"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Consecutive Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run both commands"})

        assert run["status"] == "approval_required"
        assert run["pending_approval"]["tool"] == "terminal.run"
        assert run["pending_approval"]["input_preview"]["command"] == "printf first-approved"

        after_first = service.approve_run_approval(run["run_id"])
        assert after_first["status"] == "approval_required"
        assert after_first["result"] == "等待审批：terminal.run"
        assert after_first["pending_approval"]["tool"] == "terminal.run"
        assert after_first["pending_approval"]["input_preview"]["command"] == "printf second-approved"
        assert len(calls) == 1

        after_second = service.approve_run_approval(run["run_id"])
        assert after_second["status"] == "completed"
        assert after_second["result"] == "Both terminal approvals completed"
        assert after_second["pending_approval"] == {}
        assert len(calls) == 2

        approved_events = [event for event in after_second["timeline"] if event["event"] == "agent.tool.approval_approved"]
        assert [event["input_preview"]["command"] for event in approved_events] == [
            "printf first-approved",
            "printf second-approved",
        ]
        assert service.get_run_group(after_second["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_agent_run_supports_more_than_six_terminal_turns(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []
    terminal_turns = 8

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        turn = len(calls)
        if turn <= terminal_turns:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": f"call_terminal_{turn}",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": f"printf terminal-turn-{turn}"}),
                        },
                    }
                ],
            }
        return {"content": "All terminal turns completed"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Long Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run all terminal checks"})

        for turn in range(terminal_turns):
            assert run["status"] == "approval_required"
            assert run["pending_approval"]["input_preview"]["command"] == f"printf terminal-turn-{turn + 1}"
            run = service.approve_run_approval(run["run_id"])

        assert run["status"] == "completed"
        assert run["result"] == "All terminal turns completed"
        assert len(calls) == terminal_turns + 1
    finally:
        service.close()


def test_agent_run_fails_when_approved_terminal_returns_nonzero(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf terminal-failure-smoke; exit 7"}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Failing Terminal Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run failing command"})

        assert run["status"] == "approval_required"
        resumed = service.approve_run_approval(run["run_id"])

        assert resumed["status"] == "failed"
        assert "terminal.run 执行失败" in resumed["result"]
        assert "退出码：7" in resumed["result"]
        assert "terminal-failure-smoke" in resumed["result"]
        assert len(calls) == 1
        failed_event = next(event for event in resumed["timeline"] if event["event"] == "agent.tool.failed")
        assert failed_event["status"] == "failed"
        assert failed_event["result"]["returncode"] == 7
        assert failed_event["result"]["stdout"] == "terminal-failure-smoke"
        assert service.get_run_group(resumed["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_workflow_resumes_after_child_agent_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []
    resuming_statuses = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf approved"})},
                    }
                ],
            }
        if len(calls) == 2:
            assert messages[-1]["role"] == "tool"
            assert "approved" in messages[-1]["content"]
            parent_during_resume = service.get_run(run["run_id"])
            child_during_resume = service.get_run(child_run_ids[0])
            group_during_resume = service.get_run_group(run["run_group_id"])
            resuming_statuses.append(
                (
                    child_during_resume["status"],
                    parent_during_resume["status"],
                    group_during_resume["status"],
                    parent_during_resume["result"],
                )
            )
            return {"content": "Agent A complete"}
        return {"content": "Agent B complete"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent_a = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        agent_b = service.create_agent(
            {
                "name": "After Approval",
                "model_mode": "custom_api",
                "model_config": model_config,
            }
        )
        edited_agent = service.create_agent(
            {
                "name": "Edited After Approval",
                "model_mode": "custom_api",
                "model_config": model_config,
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Approval Resume Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "a",
                        "type": "agent",
                        "data": {
                            "label": "Needs Approval",
                            "agent_id": agent_a["agent_id"],
                        },
                    },
                    {
                        "id": "b",
                        "type": "agent",
                        "data": {
                            "label": "After Approval",
                            "agent_id": agent_b["agent_id"],
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run(
            {"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"}
        )

        assert run["status"] == "approval_required"
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        assert len(child_run_ids) == 1
        child = service.get_run(child_run_ids[0])
        assert child["status"] == "approval_required"

        service.update_workflow(
            workflow["workflow_id"],
            {
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "a",
                        "type": "agent",
                        "data": {
                            "label": "Needs Approval",
                            "agent_id": agent_a["agent_id"],
                        },
                    },
                    {
                        "id": "b",
                        "type": "agent",
                        "data": {
                            "label": "Edited After Approval",
                            "agent_id": edited_agent["agent_id"],
                        },
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "b"},
                    {"source": "b", "target": "summary"},
                ],
            },
        )
        approved_child = service.approve_run_approval(child["run_id"])

        assert resuming_statuses == [
            ("running", "running", "running", "Needs Approval 已批准，正在继续执行")
        ]
        assert approved_child["status"] == "completed"
        assert any(event["event"] == "agent.run.resumed" for event in approved_child["timeline"])
        resumed_parent = service.get_run(run["run_id"])
        assert resumed_parent["status"] == "completed"
        assert resumed_parent["result"] == "Agent B complete"
        agent_events = [
            event
            for event in resumed_parent["timeline"]
            if event["event"] == "workflow.node.agent"
        ]
        assert len(agent_events) == 2
        assert agent_events[0]["status"] == "completed"
        assert agent_events[0]["result"] == "Agent A complete"
        assert agent_events[1]["workflow_node_label"] == "After Approval"
        assert any(event["event"] == "workflow.run.child_resumed" for event in resumed_parent["timeline"])
        assert any(event["event"] == "workflow.run.resumed" for event in resumed_parent["timeline"])
        assert any(
            artifact.get("kind") == "workflow_artifact"
            for artifact in resumed_parent["artifacts"]
        )
        assert service.get_run_group(run["run_group_id"])["status"] == "completed"
    finally:
        service.close()


def test_workflow_fails_when_child_terminal_returns_nonzero_after_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf workflow-child-failure-smoke; exit 7"}),
                    },
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent(
            {
                "name": "Failing Child",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Child Terminal Failure Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Failing Child", "agent_id": agent["agent_id"]}},
                    {
                        "id": "artifact",
                        "type": "artifact",
                        "data": {"label": "Should Not Run", "artifact_path": "reports/should-not-run.md"},
                    },
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "artifact"},
                ],
            }
        )
        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run failing child"})

        assert run["status"] == "approval_required"
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        assert len(child_run_ids) == 1
        child = service.get_run(child_run_ids[0])

        resumed_child = service.approve_run_approval(child["run_id"])
        resumed_parent = service.get_run(run["run_id"])

        assert resumed_child["status"] == "failed"
        assert resumed_parent["status"] == "failed"
        assert "workflow-child-failure-smoke" in resumed_parent["result"]
        assert not any(artifact.get("path") == "reports/should-not-run.md" for artifact in resumed_parent["artifacts"])
        failed_event = next(event for event in resumed_parent["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "a"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Failing Child"
        assert failed_event["child_run_id"] == child["run_id"]
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
        assert len(calls) == 1
    finally:
        service.close()


def test_workflow_resume_failure_keeps_child_node_context(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    responses = iter(["approval", "Agent A complete"])

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        response = next(responses)
        if response == "approval":
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf approved"})},
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        return {"content": response}

    def fail_resume(_run):
        raise AgentRuntimeError("workflow snapshot unavailable")

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Approval Resume Failure Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Needs Approval", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"})
        group = service.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        monkeypatch.setattr(service, "_workflow_for_run_resume", fail_resume)

        approved_child = service.approve_run_approval(child_run_id)
        parent = service.get_run(run["run_id"])

        assert approved_child["status"] == "completed"
        assert parent["status"] == "failed"
        assert parent["result"] == "workflow snapshot unavailable"
        failed_event = next(event for event in parent["timeline"] if event["event"] == "workflow.run.failed")
        assert failed_event["workflow_node_id"] == "a"
        assert failed_event["workflow_node_kind"] == "agent"
        assert failed_event["workflow_node_label"] == "Needs Approval"
        assert failed_event["child_run_id"] == child_run_id
        assert failed_event["child_run_status"] == "completed"
        assert service.get_run_group(run["run_group_id"])["status"] == "failed"
    finally:
        service.close()


def test_workflow_parent_records_child_agent_rejection_node_info(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf blocked"})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Rejected Child Approval Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Needs Approval", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"})
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        child = service.get_run(child_run_ids[0])

        rejected_child = service.reject_run_approval(child["run_id"], "not now")
        parent = service.get_run(run["run_id"])

        assert rejected_child["status"] == "cancelled"
        assert parent["status"] == "cancelled"
        assert service.get_run_group(run["run_group_id"])["status"] == "cancelled"
        agent_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "a"
        assert agent_event["workflow_node_kind"] == "agent"
        assert agent_event["workflow_node_label"] == "Needs Approval"
        assert agent_event["status"] == "cancelled"
        cancelled_event = next(event for event in parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "a"
        assert cancelled_event["workflow_node_kind"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Needs Approval"
        assert cancelled_event["child_run_id"] == child["run_id"]
    finally:
        service.close()


def test_cancel_workflow_waiting_for_child_approval_cancels_child_run(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {"name": "terminal_run", "arguments": json.dumps({"command": "printf blocked"})},
                }
            ],
        }

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Needs Approval",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = service.create_workflow(
            {
                "name": "Cancelable Child Approval Flow",
                "nodes": [
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "a", "type": "agent", "data": {"label": "Needs Approval", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                "edges": [
                    {"source": "start", "target": "a"},
                    {"source": "a", "target": "summary"},
                ],
            }
        )

        run = service.create_workflow_run({"workflow_id": workflow["workflow_id"], "user_goal": "Run approval flow"})
        group = service.get_run_group(run["run_group_id"])
        child_run_ids = [run_id for run_id in group["child_run_ids"] if run_id != run["run_id"]]
        child = service.get_run(child_run_ids[0])

        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"

        cancelled_parent = service.cancel_run(run["run_id"])
        cancelled_child = service.get_run(child["run_id"])

        assert cancelled_parent["status"] == "cancelled"
        assert cancelled_parent["result"] == "Workflow 已取消：Needs Approval"
        assert cancelled_child["status"] == "cancelled"
        assert cancelled_child["pending_approval"] == {}
        assert cancelled_child["result"] == "父 Workflow 已取消"
        assert service.get_run_group(run["run_group_id"])["status"] == "cancelled"
        agent_event = next(event for event in cancelled_parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "a"
        assert agent_event["workflow_node_kind"] == "agent"
        assert agent_event["workflow_node_label"] == "Needs Approval"
        assert agent_event["status"] == "cancelled"
        cancelled_event = next(event for event in cancelled_parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "a"
        assert cancelled_event["workflow_node_kind"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Needs Approval"
        assert cancelled_event["child_run_id"] == child["run_id"]
    finally:
        service.close()


def test_agent_run_rejects_pending_tool(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": json.dumps({"action": "tool", "tool": "terminal.run", "input": {"command": "echo blocked"}})
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Reject Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["terminal.run"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Run command"})
        rejected = service.reject_run_approval(run["run_id"], "not now")

        assert rejected["status"] == "cancelled"
        assert rejected["pending_approval"] == {}
        assert "not now" in rejected["result"]
        rejected_event = next(event for event in rejected["timeline"] if event["event"] == "agent.tool.approval_rejected")
        assert rejected_event["tool"] == "terminal.run"
        assert rejected_event["input_preview"]["command"] == "echo blocked"
        assert rejected_event["status"] == "cancelled"
    finally:
        service.close()


def test_model_payload_approved_flag_does_not_bypass_write_approval(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    (workdir / "src").mkdir(parents=True)
    monkeypatch.setattr(
        "apps.shell.agent_runtime.openai_compatible_chat_message",
        lambda *_args, **_kwargs: {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_write",
                    "type": "function",
                    "function": {
                        "name": "workspace_write_patch",
                        "arguments": json.dumps({"path": "src/out.txt", "content": "bad", "approved": True}),
                    },
                }
            ],
        },
    )
    try:
        agent = service.create_agent(
            {
                "name": "Writer",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
                "tool_policy": {"allowed_tools": ["workspace.write_patch"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."], "writable_scopes": ["src"]},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Write file"})

        assert run["status"] == "approval_required"
        assert not (workdir / "src" / "out.txt").exists()
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
    directory_read = broker.workspace_read(".")
    assert directory_read["ok"] is False
    assert directory_read["suggested_tool"] == "workspace.list"
    file_list = broker.workspace_list("README.md")
    assert file_list["ok"] is False
    assert file_list["suggested_tool"] == "workspace.read"
    with pytest.raises(AgentRuntimeError):
        broker.workspace_write_patch("../escape.txt", "bad", approved=True)
    assert broker.terminal_run("echo should-not-run")["approval_required"] is True
    assert broker.call("terminal.run", {"command": "echo should-not-run", "approved": True})["approval_required"] is True


def test_explicit_empty_tool_policy_disables_model_tools(tmp_path, monkeypatch):
    service = make_service(tmp_path)
    captured = {}

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        captured["messages"] = messages
        captured["tools"] = tools
        return {"content": "No tools used"}

    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "No Tools Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": []},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Answer only"})

        assert agent["tool_policy"]["allowed_tools"] == []
        assert run["status"] == "completed"
        assert captured["tools"] == []
        prompt = captured["messages"][0]["content"]
        assert "artifact.write" not in prompt
        compiled = next(event for event in run["timeline"] if event["event"] == "agent.runtime.compiled")
        assert compiled["allowed_tools"] == []
    finally:
        service.close()


@pytest.mark.asyncio
async def test_run_approval_routes_return_404_and_400(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", lambda *_args, **_kwargs: {"content": "Done"})
    try:
        with pytest.raises(HTTPException) as missing:
            await agent_routes.approve_run_approval("run_missing")
        assert missing.value.status_code == 404

        agent = service.create_agent(
            {
                "name": "Done Agent",
                "model_mode": "custom_api",
                "model_config": {"base_url": "https://api.example.test/v1", "model": "demo-model", "api_key": "sk-secret"},
            }
        )
        run = service.create_agent_run({"agent_id": agent["agent_id"], "user_goal": "Finish"})
        with pytest.raises(HTTPException) as invalid:
            await agent_routes.approve_run_approval(run["run_id"])
        assert invalid.value.status_code == 400
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_routes_update_then_run_latest_graph(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    responses = iter(["Route design", "Route code"])

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": next(responses)}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        old_agent = service.create_agent({"name": "Route Old", "model_mode": "custom_api", "model_config": model_config})
        design_agent = service.create_agent({"name": "Route Design", "model_mode": "custom_api", "model_config": model_config})
        coding_agent = service.create_agent({"name": "Route Coding", "model_mode": "custom_api", "model_config": model_config})

        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Save And Run",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "old", "type": "agent", "data": {"label": "Route Old", "agent_id": old_agent["agent_id"]}},
                ],
                edges=[{"source": "start", "target": "old"}],
            )
        )
        updated = await agent_routes.update_workflow(
            workflow["workflow_id"],
            agent_routes.WorkflowRequest(
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Route Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "coding", "type": "agent", "data": {"label": "Route Coding", "agent_id": coding_agent["agent_id"]}},
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "coding"},
                ],
            ),
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(
                workflow_id=updated["workflow_id"],
                user_goal="Run latest route graph",
            )
        )

        assert run["status"] == "completed"
        assert run["result"] == "Route code"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "design", "kind": "agent", "label": "Route Design"},
            {"id": "coding", "kind": "agent", "label": "Route Coding"},
        ]
        group = service.get_run_group(run["run_group_id"])
        child_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["runnable_id"] for child in child_runs] == [design_agent["agent_id"], coding_agent["agent_id"]]
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_routes_save_and_run_latest_canvas_with_step_approval_and_artifact(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    contexts: list[str] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        contexts.append(messages[-1]["content"])
        return {"content": "Mobile acceptance risks ready"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        old_agent = service.create_agent({"name": "Canvas Old", "model_mode": "custom_api", "model_config": model_config})
        design_agent = service.create_agent({"name": "Canvas Design", "model_mode": "custom_api", "model_config": model_config})

        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Canvas Save And Run",
                nodes=[
                    {"id": "start", "type": "input", "data": {"label": "Start", "kind": "start"}},
                    {
                        "id": "old",
                        "type": "default",
                        "data": {"label": "Old Agent", "kind": "agent", "agent_id": old_agent["agent_id"]},
                    },
                ],
                edges=[{"source": "start", "target": "old"}],
            )
        )
        updated = await agent_routes.update_workflow(
            workflow["workflow_id"],
            agent_routes.WorkflowRequest(
                nodes=[
                    {"id": "start", "type": "input", "data": {"label": "Start", "kind": "start"}},
                    {
                        "id": "design",
                        "type": "default",
                        "data": {
                            "label": "Mobile Design",
                            "kind": "agent",
                            "agent_id": design_agent["agent_id"],
                            "step_task": "List mobile acceptance risks and the checks to verify them.",
                        },
                    },
                    {
                        "id": "gate",
                        "type": "default",
                        "data": {
                            "label": "Review Gate",
                            "kind": "approval",
                            "approval_criteria": "Confirm the mobile risks are specific enough before writing the report.",
                        },
                    },
                    {
                        "id": "report",
                        "type": "output",
                        "data": {
                            "label": "Risk Report",
                            "kind": "artifact",
                            "artifact_path": "reports/mobile-risk.md",
                        },
                    },
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "gate"},
                    {"source": "gate", "target": "report"},
                ],
            ),
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(
                workflow_id=updated["workflow_id"],
                user_goal="Prepare mobile release acceptance",
            )
        )

        assert run["status"] == "approval_required"
        assert len(contexts) == 1
        assert "# User Goal\nList mobile acceptance risks and the checks to verify them." in contexts[0]
        assert "Workflow Goal:\nPrepare mobile release acceptance" in contexts[0]
        assert "# Upstream Context\nNone" in contexts[0]
        assert "Old Agent" not in contexts[0]
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {
                "id": "design",
                "kind": "agent",
                "label": "Mobile Design",
                "task": "List mobile acceptance risks and the checks to verify them.",
            },
            {
                "id": "gate",
                "kind": "approval",
                "label": "Review Gate",
                "criteria": "Confirm the mobile risks are specific enough before writing the report.",
            },
            {
                "id": "report",
                "kind": "artifact",
                "label": "Risk Report",
                "artifact_path": "reports/mobile-risk.md",
            },
        ]
        assert run["pending_approval"]["input_preview"]["criteria"] == (
            "Confirm the mobile risks are specific enough before writing the report."
        )
        agent_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "design"
        assert agent_event["workflow_node_task"] == "List mobile acceptance risks and the checks to verify them."
        approval_event = next(event for event in run["timeline"] if event["event"] == "workflow.node.approval_required")
        assert approval_event["workflow_node_id"] == "gate"
        assert approval_event["workflow_node_approval_criteria"] == (
            "Confirm the mobile risks are specific enough before writing the report."
        )
        group = service.get_run_group(run["run_group_id"])
        child_runs = [
            service.get_run(run_id)
            for run_id in group["child_run_ids"]
            if run_id != run["run_id"]
        ]
        assert [child["runnable_id"] for child in child_runs] == [design_agent["agent_id"]]
        assert child_runs[0]["user_goal"] == (
            "List mobile acceptance risks and the checks to verify them.\n\n"
            "Workflow Goal:\n"
            "Prepare mobile release acceptance"
        )

        resumed = await agent_routes.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        artifact_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.artifact")
        assert artifact_event["workflow_node_id"] == "report"
        assert artifact_event["artifact"]["path"] == "reports/mobile-risk.md"
        assert service.read_run_artifact(resumed["run_id"], "reports/mobile-risk.md")["content"] == "Mobile acceptance risks ready"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_routes_accept_reactflow_node_types(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {"content": "ReactFlow route done"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        agent = service.create_agent({"name": "Route Design", "model_mode": "custom_api", "model_config": model_config})

        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="ReactFlow Raw Types",
                nodes=[
                    {"id": "start", "type": "input", "data": {"label": "Start", "kind": "start"}},
                    {"id": "design", "type": "default", "data": {"label": "Route Design", "kind": "agent", "agent_id": agent["agent_id"]}},
                    {"id": "summary", "type": "output", "data": {"label": "Summary", "kind": "artifact"}},
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(
                workflow_id=workflow["workflow_id"],
                user_goal="Run raw ReactFlow graph",
            )
        )

        assert run["status"] == "completed"
        started_event = next(event for event in run["timeline"] if event["event"] == "workflow.run.started")
        assert started_event["workflow_path"] == [
            {"id": "start", "kind": "start", "label": "Start"},
            {"id": "design", "kind": "agent", "label": "Route Design"},
            {"id": "summary", "kind": "artifact", "label": "Summary", "artifact_path": "summary.md"},
        ]
        assert service.read_run_artifact(run["run_id"], "summary.md")["content"] == "ReactFlow route done"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_run_route_rejects_start_only_saved_draft(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Draft Only",
                nodes=[{"id": "start", "type": "start", "data": {"label": "Start"}}],
                edges=[],
            )
        )

        with pytest.raises(HTTPException) as invalid:
            await agent_routes.create_workflow_run(
                agent_routes.WorkflowRunRequest(
                    workflow_id=workflow["workflow_id"],
                    user_goal="Run empty draft",
                )
            )

        assert invalid.value.status_code == 400
        assert "至少需要一个可执行节点" in str(invalid.value.detail)
        assert service.list_runs()["runs"] == []
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_approval_route_resumes_runtime_snapshot_after_edit(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        calls.append(messages)
        context = str(messages[1]["content"])
        assert "Name: Original After Approval" in context
        assert "Name: Edited After Approval" not in context
        return {"content": "Original route agent complete"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        original_agent = service.create_agent(
            {"name": "Original After Approval", "model_mode": "custom_api", "model_config": model_config}
        )
        edited_agent = service.create_agent(
            {"name": "Edited After Approval", "model_mode": "custom_api", "model_config": model_config}
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Editable Paused Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {
                        "id": "after",
                        "type": "agent",
                        "data": {"label": "Original After Approval", "agent_id": original_agent["agent_id"]},
                    },
                ],
                edges=[
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Wait then run")
        )
        assert run["status"] == "approval_required"

        await agent_routes.update_workflow(
            workflow["workflow_id"],
            agent_routes.WorkflowRequest(
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "gate", "type": "approval", "data": {"label": "Manual Gate"}},
                    {
                        "id": "after",
                        "type": "agent",
                        "data": {"label": "Edited After Approval", "agent_id": edited_agent["agent_id"]},
                    },
                ],
                edges=[
                    {"source": "start", "target": "gate"},
                    {"source": "gate", "target": "after"},
                ],
            ),
        )

        resumed = await agent_routes.approve_run_approval(run["run_id"])

        assert resumed["status"] == "completed"
        assert resumed["result"] == "Original route agent complete"
        assert len(calls) == 1
        agent_event = next(event for event in resumed["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "after"
        assert agent_event["workflow_node_label"] == "Original After Approval"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_cancel_route_cancels_child_agent_approval(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, **_kwargs):
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf blocked"}),
                    },
                }
            ],
        }

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Needs Approval",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Cancel Child Approval Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Needs Approval", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run approval flow")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)
        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"

        cancelled_parent = await agent_routes.cancel_run(run["run_id"])
        cancelled_child = await agent_routes.get_any_run(child_run_id)

        assert cancelled_parent["status"] == "cancelled"
        assert cancelled_parent["result"] == "Workflow 已取消：Route Needs Approval"
        assert cancelled_child["status"] == "cancelled"
        assert cancelled_child["pending_approval"] == {}
        assert cancelled_child["result"] == "父 Workflow 已取消"
        cancelled_group = await agent_routes.get_run_group(run["run_group_id"])
        assert cancelled_group["status"] == "cancelled"
        cancelled_event = next(event for event in cancelled_parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Route Needs Approval"
        assert cancelled_event["child_run_id"] == child_run_id
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_approval_route_approve_resumes_parent_workflow(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf route-approved"}),
                        },
                    }
                ],
            }
        assert messages[-1]["role"] == "tool"
        assert "route-approved" in messages[-1]["content"]
        return {"content": "Route child approved result"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Approval Child",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Child Approval Resume Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Approval Child", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run route approval flow")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)

        assert run["status"] == "approval_required"
        assert run["pending_approval"] == {}
        assert child["status"] == "approval_required"
        assert child["pending_approval"]["tool"] == "terminal.run"
        assert child["pending_approval"]["input_preview"]["command"] == "printf route-approved"

        approved_child = await agent_routes.approve_run_approval(child_run_id)
        parent = await agent_routes.get_workflow_run(run["run_id"])
        completed_group = await agent_routes.get_run_group(run["run_group_id"])

        assert approved_child["status"] == "completed"
        assert approved_child["pending_approval"] == {}
        assert approved_child["result"] == "Route child approved result"
        assert parent["status"] == "completed"
        assert parent["result"] == "Route child approved result"
        assert completed_group["status"] == "completed"
        assert any(event["event"] == "workflow.run.child_resumed" for event in parent["timeline"])
        assert any(event["event"] == "workflow.run.resumed" for event in parent["timeline"])
        agent_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "agent"
        assert agent_event["workflow_node_label"] == "Route Approval Child"
        assert agent_event["child_run_id"] == child_run_id
        assert agent_event["status"] == "completed"
        artifact_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.artifact")
        assert artifact_event["workflow_node_id"] == "summary"
        assert artifact_event["status"] == "completed"
        assert artifact_event["artifact"]["path"] == "summary.md"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_consecutive_approvals_keep_parent_waiting(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, *, tools=None):
        calls.append(messages)
        if len(calls) == 1:
            assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
            return {
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_first_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf workflow-first-approved"}),
                        },
                    },
                    {
                        "id": "call_second_terminal",
                        "type": "function",
                        "function": {
                            "name": "terminal_run",
                            "arguments": json.dumps({"command": "printf workflow-second-approved"}),
                        },
                    },
                ],
            }
        tool_messages = [message for message in messages if message.get("role") == "tool"]
        assert any("workflow-first-approved" in message.get("content", "") for message in tool_messages)
        assert any("workflow-second-approved" in message.get("content", "") for message in tool_messages)
        return {"content": "Workflow child consecutive approvals completed"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Consecutive Approval Child",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Child Consecutive Approval Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Consecutive Approval Child", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run two child approvals")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)

        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"
        assert child["pending_approval"]["input_preview"]["command"] == "printf workflow-first-approved"

        after_first = await agent_routes.approve_run_approval(child_run_id)
        parent_after_first = await agent_routes.get_workflow_run(run["run_id"])
        group_after_first = await agent_routes.get_run_group(run["run_group_id"])

        assert after_first["status"] == "approval_required"
        assert after_first["pending_approval"]["input_preview"]["command"] == "printf workflow-second-approved"
        assert parent_after_first["status"] == "approval_required"
        assert parent_after_first["pending_approval"] == {}
        assert parent_after_first["result"] == "等待审批：terminal.run"
        assert group_after_first["status"] == "approval_required"
        assert group_after_first["summary"] == "等待审批：terminal.run"
        approval_events = [
            event for event in parent_after_first["timeline"]
            if event["event"] == "workflow.run.approval_required"
        ]
        assert len(approval_events) == 2
        assert approval_events[-1]["child_run_id"] == child_run_id
        assert approval_events[-1]["workflow_node_id"] == "agent"
        assert approval_events[-1]["workflow_node_label"] == "Route Consecutive Approval Child"
        agent_event = next(event for event in parent_after_first["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["status"] == "approval_required"
        assert agent_event["child_run_id"] == child_run_id

        after_second = await agent_routes.approve_run_approval(child_run_id)
        parent_after_second = await agent_routes.get_workflow_run(run["run_id"])
        group_after_second = await agent_routes.get_run_group(run["run_group_id"])

        assert after_second["status"] == "completed"
        assert after_second["pending_approval"] == {}
        assert after_second["result"] == "Workflow child consecutive approvals completed"
        assert parent_after_second["status"] == "completed"
        assert parent_after_second["result"] == "Workflow child consecutive approvals completed"
        assert group_after_second["status"] == "completed"
        completed_agent_event = next(
            event for event in parent_after_second["timeline"] if event["event"] == "workflow.node.agent"
        )
        assert completed_agent_event["status"] == "completed"
        approved_events = [
            event for event in after_second["timeline"] if event["event"] == "agent.tool.approval_approved"
        ]
        assert [event["input_preview"]["command"] for event in approved_events] == [
            "printf workflow-first-approved",
            "printf workflow-second-approved",
        ]
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_approval_route_reject_cancels_parent_workflow(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    workdir = tmp_path / "repo"
    workdir.mkdir()

    def fake_chat(_base_url, _model, _api_key, _messages, *, tools=None):
        assert any((tool.get("function") or {}).get("name") == "terminal_run" for tool in tools or [])
        return {
            "content": "",
            "tool_calls": [
                {
                    "id": "call_terminal",
                    "type": "function",
                    "function": {
                        "name": "terminal_run",
                        "arguments": json.dumps({"command": "printf route-blocked"}),
                    },
                }
            ],
        }

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        agent = service.create_agent(
            {
                "name": "Route Reject Child",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {"allowed_tools": ["terminal.run"]},
                "workspace_policy": {"default_workdir": str(workdir), "readable_scopes": ["."]},
            }
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Child Approval Reject Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {
                        "id": "agent",
                        "type": "agent",
                        "data": {"label": "Route Reject Child", "agent_id": agent["agent_id"]},
                    },
                    {"id": "summary", "type": "artifact", "data": {"label": "Summary"}},
                ],
                edges=[
                    {"source": "start", "target": "agent"},
                    {"source": "agent", "target": "summary"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Run route rejection flow")
        )
        group = await agent_routes.get_run_group(run["run_group_id"])
        child_run_id = next(run_id for run_id in group["child_run_ids"] if run_id != run["run_id"])
        child = await agent_routes.get_any_run(child_run_id)

        assert run["status"] == "approval_required"
        assert child["status"] == "approval_required"
        assert child["pending_approval"]["tool"] == "terminal.run"

        rejected_child = await agent_routes.reject_run_approval(
            child_run_id,
            agent_routes.ApprovalRejectRequest(reason="not now"),
        )
        parent = await agent_routes.get_workflow_run(run["run_id"])
        cancelled_group = await agent_routes.get_run_group(run["run_group_id"])

        assert rejected_child["status"] == "cancelled"
        assert rejected_child["pending_approval"] == {}
        assert "not now" in rejected_child["result"]
        assert parent["status"] == "cancelled"
        assert cancelled_group["status"] == "cancelled"
        agent_event = next(event for event in parent["timeline"] if event["event"] == "workflow.node.agent")
        assert agent_event["workflow_node_id"] == "agent"
        assert agent_event["workflow_node_kind"] == "agent"
        assert agent_event["workflow_node_label"] == "Route Reject Child"
        assert agent_event["status"] == "cancelled"
        cancelled_event = next(event for event in parent["timeline"] if event["event"] == "workflow.run.cancelled")
        assert cancelled_event["workflow_node_id"] == "agent"
        assert cancelled_event["workflow_node_kind"] == "agent"
        assert cancelled_event["workflow_node_label"] == "Route Reject Child"
        assert cancelled_event["child_run_id"] == child_run_id
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_child_artifact_route_reads_source_run_artifact(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        calls.append(messages)
        if len(calls) == 1:
            return {
                "content": json.dumps(
                    {
                        "action": "tool",
                        "tool": "artifact.write",
                        "input": {"path": "design.md", "content": "route design artifact"},
                    }
                )
            }
        if len(calls) == 2:
            assert "Tool result for artifact.write" in messages[-1]["content"]
            return {"content": "Design done"}
        return {"content": "Code done"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design_agent = service.create_agent(
            {
                "name": "Route Design Artifact Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        coding_agent = service.create_agent(
            {"name": "Route Coding Summary Agent", "model_mode": "custom_api", "model_config": model_config}
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Artifact Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": coding_agent["agent_id"]}},
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "code"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Ship artifacts")
        )
        parent = await agent_routes.get_workflow_run(run["run_id"])
        design_ref = next(
            artifact
            for artifact in parent["artifacts"]
            if artifact.get("kind") == "workflow_child_artifact" and artifact.get("path") == "design.md"
        )

        artifact = await agent_routes.get_run_artifact(design_ref["source_run_id"], design_ref["path"])

        assert artifact["ok"] is True
        assert artifact["path"] == "design.md"
        assert artifact["content"] == "route design artifact"
        assert design_ref["source_runnable_name"] == "Route Design Artifact Agent"
        assert design_ref["workflow_step_label"] == "Design"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_workflow_artifact_review_route_exposes_outputs_and_reruns(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    calls: list[list[dict]] = []

    def fake_chat(_base_url, _model, _api_key, messages, **_kwargs):
        calls.append(messages)
        if len(calls) in {1, 4}:
            return {
                "content": json.dumps(
                    {
                        "action": "tool",
                        "tool": "artifact.write",
                        "input": {
                            "path": "design.md",
                            "content": f"design artifact run {1 if len(calls) == 1 else 2}",
                        },
                    }
                )
            }
        if len(calls) in {2, 5}:
            assert "Tool result for artifact.write" in messages[-1]["content"]
            return {"content": f"Design done run {1 if len(calls) == 2 else 2}"}
        return {"content": f"Code final result run {1 if len(calls) == 3 else 2}"}

    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.openai_compatible_chat_message", fake_chat)
    try:
        model_config = {
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
        }
        design_agent = service.create_agent(
            {
                "name": "Route Design Artifact Agent",
                "model_mode": "custom_api",
                "model_config": model_config,
                "tool_policy": {"allowed_tools": ["artifact.write"]},
            }
        )
        coding_agent = service.create_agent(
            {"name": "Route Coding Final Agent", "model_mode": "custom_api", "model_config": model_config}
        )
        workflow = await agent_routes.create_workflow(
            agent_routes.WorkflowRequest(
                name="Route Artifact Review Flow",
                nodes=[
                    {"id": "start", "type": "start", "data": {"label": "Start"}},
                    {"id": "design", "type": "agent", "data": {"label": "Design", "agent_id": design_agent["agent_id"]}},
                    {"id": "code", "type": "agent", "data": {"label": "Code", "agent_id": coding_agent["agent_id"]}},
                    {
                        "id": "report",
                        "type": "artifact",
                        "data": {"label": "Final Report", "artifact_path": "reports/final.md"},
                    },
                ],
                edges=[
                    {"source": "start", "target": "design"},
                    {"source": "design", "target": "code"},
                    {"source": "code", "target": "report"},
                ],
            )
        )
        run = await agent_routes.create_workflow_run(
            agent_routes.WorkflowRunRequest(workflow_id=workflow["workflow_id"], user_goal="Ship artifact review")
        )
        parent = await agent_routes.get_workflow_run(run["run_id"])

        assert parent["status"] == "completed"
        assert parent["result"] == "Code final result run 1"
        assert parent["runnable_id"] == workflow["workflow_id"]
        assert parent["user_goal"] == "Ship artifact review"
        child_ref = next(
            artifact
            for artifact in parent["artifacts"]
            if artifact.get("kind") == "workflow_child_artifact" and artifact.get("path") == "design.md"
        )
        workflow_ref = next(
            artifact
            for artifact in parent["artifacts"]
            if artifact.get("kind") == "workflow_artifact" and artifact.get("path") == "reports/final.md"
        )
        assert child_ref["workflow_step_label"] == "Design"
        assert child_ref["source_runnable_name"] == "Route Design Artifact Agent"
        assert workflow_ref["workflow_node_id"] == "report"
        assert workflow_ref["workflow_node_label"] == "Final Report"

        child_artifact = await agent_routes.get_run_artifact(child_ref["source_run_id"], child_ref["path"])
        workflow_artifact = await agent_routes.get_run_artifact(parent["run_id"], workflow_ref["path"])

        assert child_artifact["content"] == "design artifact run 1"
        assert workflow_artifact["content"] == "Code final result run 1"
        steps = [event for event in parent["timeline"] if str(event.get("event") or "").startswith("workflow.node.")]
        assert [(event["event"], event.get("workflow_node_id"), event.get("status")) for event in steps] == [
            ("workflow.node.start", "start", "completed"),
            ("workflow.node.agent", "design", "completed"),
            ("workflow.node.agent", "code", "completed"),
            ("workflow.node.artifact", "report", "completed"),
        ]

        rerun = await agent_routes.rerun_run(parent["run_id"])
        rerun_artifact = await agent_routes.get_run_artifact(rerun["run_id"], "reports/final.md")
        rerun_group = service.get_run_group(rerun["run_group_id"])
        rerun_event = rerun["timeline"][0]

        assert rerun["run_id"] != parent["run_id"]
        assert rerun["status"] == "completed"
        assert rerun["result"] == "Code final result run 2"
        assert rerun["workflow_run_id"] == rerun["run_id"]
        assert rerun_group["source"] == "rerun"
        assert rerun_event["event"] == "run.rerun.started"
        assert rerun_event["rerun_of_run_id"] == parent["run_id"]
        assert rerun_event["input_preview"]["original_status"] == "completed"
        assert rerun_event["input_preview"]["original_goal"] == parent["user_goal"]
        assert rerun_artifact["content"] == "Code final result run 2"
    finally:
        service.close()


@pytest.mark.asyncio
async def test_skill_update_route_toggles_enabled_and_returns_404(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    source = tmp_path / "route-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Route Skill\n\nRoute import.", encoding="utf-8")
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        skill = service.import_skill(str(source))
        updated = await agent_routes.update_skill(
            skill["skill_id"],
            agent_routes.SkillUpdateRequest(enabled=False),
        )
        assert updated["enabled"] is False

        with pytest.raises(HTTPException) as missing:
            await agent_routes.update_skill("missing", agent_routes.SkillUpdateRequest(enabled=True))
        assert missing.value.status_code == 404
    finally:
        service.close()


@pytest.mark.asyncio
async def test_skill_folder_routes_rename_delete_and_validate(tmp_path, monkeypatch):
    from fastapi import HTTPException

    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    source = tmp_path / "route-folder-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Route Folder Skill\n\nRoute folder.", encoding="utf-8")
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    try:
        folder = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Writing"))
        skill = service.import_skill(str(source), folder["folder_id"])

        renamed = await agent_routes.update_skill_folder(
            folder["folder_id"],
            agent_routes.SkillFolderRequest(name="Docs"),
        )
        assert renamed["name"] == "Docs"
        assert service.get_skill(skill["skill_id"])["folder_name"] == "Docs"

        duplicate = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Research"))
        with pytest.raises(HTTPException) as duplicate_name:
            await agent_routes.update_skill_folder(
                duplicate["folder_id"],
                agent_routes.SkillFolderRequest(name="docs"),
            )
        assert duplicate_name.value.status_code == 400

        deleted = await agent_routes.delete_skill_folder(folder["folder_id"])
        assert deleted["ok"] is True
        assert service.get_skill(skill["skill_id"])["folder_id"] == ""

        destructive_folder = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Temporary"))
        destructive_skill = service.import_skill(str(source), destructive_folder["folder_id"])
        deleted_with_skills = await agent_routes.delete_skill_folder(destructive_folder["folder_id"], delete_skills=True)
        assert deleted_with_skills["ok"] is True
        assert deleted_with_skills["deleted_skill_count"] == 1
        with pytest.raises(KeyError):
            service.get_skill(destructive_skill["skill_id"])

        with pytest.raises(HTTPException) as missing:
            await agent_routes.delete_skill_folder("folder_missing")
        assert missing.value.status_code == 404
    finally:
        service.close()


@pytest.mark.asyncio
async def test_skill_sync_and_install_routes(tmp_path, monkeypatch):
    from apps.bridge.routes import agents as agent_routes

    service = make_service(tmp_path)
    hermes_home = tmp_path / ".hermes"

    def fake_run(argv, **_kwargs):
        skill_root = Path(_kwargs["cwd"]) / ".hermes" / "skills" / "office" / "route-installed"
        skill_root.mkdir(parents=True)
        (skill_root / "SKILL.md").write_text("# Route Installed\n\nRoute install.", encoding="utf-8")
        return subprocess.CompletedProcess(argv, 0, stdout="installed", stderr="")

    monkeypatch.setenv("HERMES_HOME", str(hermes_home))
    monkeypatch.setattr(agent_routes, "get_agent_runtime_service", lambda: service)
    monkeypatch.setattr("apps.shell.agent_runtime.subprocess.run", fake_run)
    try:
        sources = await agent_routes.list_skill_sources()
        assert sources["roots"][0]["path"] == str(hermes_home / "skills")

        folder = await agent_routes.create_skill_folder(agent_routes.SkillFolderRequest(name="Office"))
        installed = await agent_routes.install_skill(
            agent_routes.SkillInstallRequest(command="skills@latest add owner/repo", folder_id=folder["folder_id"])
        )
        assert installed["ok"] is True
        assert installed["sync"]["summary"]["imported"] == 1
        skills = service.list_skills()["skills"]
        assert skills[0]["folder_id"] == folder["folder_id"]
        assert skills[0]["folder_name"] == "Office"

        synced = await agent_routes.sync_hermes_skills()
        assert synced["summary"]["skipped"] >= 1
    finally:
        service.close()
