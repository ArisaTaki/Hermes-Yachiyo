"""Tests for Agent Studio facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.studio_facade import RuntimeStudioFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_studio_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeStudioFacadeMixin is RuntimeStudioFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeStudioFacadeMixin)
    assert "list_agents" not in agent_runtime.NativeRunEngine.__dict__
    assert "list_workflows" not in agent_runtime.NativeRunEngine.__dict__
    assert "list_runs" not in agent_runtime.NativeRunEngine.__dict__
    assert "sync_native_skills" not in agent_runtime.NativeRunEngine.__dict__
    assert "install_skill_command" not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_studio_facade_methods_available_after_split(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        agent = service.create_agent({"name": "Facade Agent"})
        folder = service.create_skill_folder({"name": "Facade Skills"})
        workflow = service.create_workflow(
            {
                "name": "Facade Workflow",
                "nodes": [{"id": "start", "type": "start", "data": {"kind": "start"}}],
                "edges": [],
            }
        )

        assert service.get_agent(agent["agent_id"])["name"] == "Facade Agent"
        assert service.list_agents()["agents"]
        assert service.get_skill_folder(folder["folder_id"])["name"] == "Facade Skills"
        assert service._normalize_skill_folder_id(folder["folder_id"]) == folder["folder_id"]
        assert service.get_workflow(workflow["workflow_id"])["name"] == "Facade Workflow"
        assert service.list_workflows()["workflows"]
        assert service.validate_workflow(workflow["nodes"], workflow["edges"])["ok"] is True
        assert service.list_runs()["runs"] == []
        assert service.list_run_groups()["run_groups"] == []
        assert service._skill_name("# Facade Skill\n\nDescription", "Fallback") == "Facade Skill"
        assert service._validated_skill_install_argv("skills@latest add owner/repo")[1] == "npx_skills"
        assert service._count_skill_files(tmp_path / "missing") == 0
        synced = service.sync_native_skills(roots=[{"path": str(tmp_path / "missing"), "source_type": "native_global"}])
        assert synced["summary"] == {"imported": 0, "updated": 0, "skipped": 1, "failed": 0}
    finally:
        service.close()
