from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.paths import (
    agent_workspace_dir,
    native_skill_home,
    oha_yachiyo_home,
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
