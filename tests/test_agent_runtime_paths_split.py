from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.paths import (
    RuntimeDirectoryLayout,
    agent_workspace_dir,
    native_skill_home,
    oha_yachiyo_home,
    runtime_directory_layout,
)


def test_runtime_path_helpers_remain_exported_from_legacy_runtime_module(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("OHA_YACHIYO_HOME", str(tmp_path / "runtime-home"))

    assert agent_runtime._oha_yachiyo_home is oha_yachiyo_home
    assert agent_runtime._native_skill_home is native_skill_home
    assert oha_yachiyo_home() == tmp_path / "runtime-home"
    assert oha_yachiyo_home().is_dir()
    assert native_skill_home() == tmp_path / "runtime-home" / "skill-library"


def test_agent_workspace_dir_projects_default_workdir() -> None:
    assert agent_workspace_dir({"workspace_policy": {"default_workdir": "/tmp/yachiyo"}}) == "/tmp/yachiyo"
    assert agent_runtime.NativeRunEngine._agent_workspace_dir({"workspace_policy": {}}) == ""
    assert agent_workspace_dir({"workspace_policy": {"default_workdir": Path("/tmp/path-value")}}) == "/tmp/path-value"


def test_runtime_directory_layout_creates_expected_runtime_dirs(tmp_path) -> None:
    layout = runtime_directory_layout(tmp_path / "runtime", tmp_path / "custom.db")

    assert isinstance(layout, RuntimeDirectoryLayout)
    assert layout.root == tmp_path / "runtime"
    assert layout.db_path == tmp_path / "custom.db"
    assert layout.skills_dir == tmp_path / "runtime" / "skills"
    assert layout.skill_installs_native_home == tmp_path / "runtime" / "skill-installs" / "native-home"
    assert layout.agent_artifacts_dir == tmp_path / "runtime" / "artifacts" / "agent-runs"
    assert layout.workflow_artifacts_dir == tmp_path / "runtime" / "artifacts" / "workflow-runs"
    assert layout.agent_workspaces_dir == tmp_path / "runtime" / "workspaces" / "agents"

    for path in (
        layout.root,
        layout.skills_dir,
        layout.skill_installs_dir,
        layout.skill_installs_native_home,
        layout.agent_artifacts_dir,
        layout.workflow_artifacts_dir,
        layout.agent_workspaces_dir,
    ):
        assert path.is_dir()
