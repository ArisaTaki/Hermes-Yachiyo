"""Tests for Skill install command validation split out of the legacy runtime."""

from __future__ import annotations

import subprocess

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from apps.shell.agent.runtime.skill_install_service import RuntimeSkillInstallService
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_skill_install_validator_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillInstallCommandValidator is SkillInstallCommandValidator
    assert agent_runtime.RuntimeSkillInstallService is RuntimeSkillInstallService


def test_skill_install_validator_rejects_shell_and_normalizes_shortcuts() -> None:
    validator = SkillInstallCommandValidator(error_type=AgentRuntimeError)

    with pytest.raises(AgentRuntimeError, match="shell"):
        validator.validate("npx skills add owner/repo && rm -rf /")
    with pytest.raises(AgentRuntimeError, match="只允许"):
        validator.validate("npm install owner/repo")
    with pytest.raises(AgentRuntimeError, match="oha-yachiyo"):
        validator.validate("npx skills@latest add owner/repo --agent=codex")

    argv, installer = validator.validate("skills@latest add owner/repo")
    assert installer == "npx_skills"
    assert argv == ["npx", "skills@latest", "add", "owner/repo", "-a", "oha-yachiyo", "--copy", "-y"]
    assert validator.source_ref(argv, installer) == "https://github.com/owner/repo"

    argv, installer = validator.validate("owner/repo --skill docs")
    assert installer == "npx_skills"
    assert argv == ["npx", "skills@latest", "add", "owner/repo", "--skill", "docs", "-a", "oha-yachiyo", "--copy", "-y"]
    assert validator.source_ref(argv, installer) == "https://github.com/owner/repo --skill docs"


def test_native_runtime_uses_split_skill_install_validator(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
    )
    try:
        argv, installer = service._validated_skill_install_argv("npx -y skills@latest add owner/repo")

        assert isinstance(service.skill_install_validator, SkillInstallCommandValidator)
        assert isinstance(service.skill_install_service, RuntimeSkillInstallService)
        assert installer == "npx_skills"
        assert argv == ["npx", "-y", "skills@latest", "add", "owner/repo", "-a", "oha-yachiyo", "--copy"]
        assert service._skill_install_source_ref(argv, installer) == "https://github.com/owner/repo"
    finally:
        service.close()


def _skill_install_service(tmp_path, *, run_command, sync_installed_skills=None) -> RuntimeSkillInstallService:
    return RuntimeSkillInstallService(
        validator=SkillInstallCommandValidator(error_type=AgentRuntimeError),
        skill_installs_dir=tmp_path / "skill-installs",
        skill_installs_native_home=tmp_path / "skill-installs" / "native-home",
        normalize_skill_folder_id=lambda folder_id: folder_id or "",
        sync_installed_skills=sync_installed_skills or (lambda **_kwargs: {"ok": True}),
        run_command=run_command,
        now=lambda: "2026-06-15T00:00:00+00:00",
        redact_secrets=lambda value: str(value).replace("SECRET", "[redacted]"),
        error_type=AgentRuntimeError,
    )


def test_runtime_skill_install_service_runs_command_and_syncs(tmp_path, monkeypatch) -> None:
    recorded: dict[str, object] = {}
    sync_calls: list[dict[str, object]] = []
    monkeypatch.setenv("GITHUB_TOKEN", "SECRET")

    def fake_run(argv, **kwargs):
        recorded["argv"] = list(argv)
        recorded["cwd"] = kwargs["cwd"]
        recorded["env"] = dict(kwargs["env"])
        recorded["text"] = kwargs["text"]
        recorded["capture_output"] = kwargs["capture_output"]
        recorded["timeout"] = kwargs["timeout"]
        recorded["check"] = kwargs["check"]
        return subprocess.CompletedProcess(argv, 0, stdout=f"SECRET{'x' * 13000}", stderr="stderr SECRET")

    def fake_sync(**kwargs):
        sync_calls.append(dict(kwargs))
        return {"ok": True, "summary": {"imported": 1}}

    service = _skill_install_service(tmp_path, run_command=fake_run, sync_installed_skills=fake_sync)

    result = service.install("owner/repo --skill docs", folder_id="folder-1")

    assert result["ok"] is True
    assert result["installer"] == "npx_skills"
    assert result["command"] == [
        "npx",
        "skills@latest",
        "add",
        "owner/repo",
        "--skill",
        "docs",
        "-a",
        "oha-yachiyo",
        "--copy",
        "-y",
    ]
    assert len(result["stdout"]) == 12000
    assert "SECRET" not in result["stdout"]
    assert "SECRET" not in result["stderr"]
    assert recorded["argv"] == result["command"]
    assert recorded["cwd"] == tmp_path / "skill-installs"
    assert recorded["text"] is True
    assert recorded["capture_output"] is True
    assert recorded["timeout"] == 600
    assert recorded["check"] is False
    assert recorded["env"]["OHA_YACHIYO_HOME"] == str(tmp_path / "skill-installs" / "native-home")
    assert "GITHUB_TOKEN" not in recorded["env"]
    assert sync_calls == [
        {
            "record_source_type": "npx_skills",
            "folder_id": "folder-1",
            "source_ref_override": "https://github.com/owner/repo --skill docs",
            "restore_deleted": True,
        }
    ]
    assert result["sync"] == {"ok": True, "summary": {"imported": 1}}


def test_runtime_skill_install_service_skips_sync_when_command_fails(tmp_path) -> None:
    sync_calls: list[dict[str, object]] = []

    def fake_run(argv, **_kwargs):
        return subprocess.CompletedProcess(argv, 2, stdout="bad", stderr="failed")

    service = _skill_install_service(
        tmp_path,
        run_command=fake_run,
        sync_installed_skills=lambda **kwargs: sync_calls.append(dict(kwargs)),
    )

    result = service.install("skills@latest add owner/repo")

    assert result["ok"] is False
    assert result["returncode"] == 2
    assert result["sync"] is None
    assert sync_calls == []


def test_runtime_skill_install_service_maps_command_failures(tmp_path) -> None:
    missing = _skill_install_service(
        tmp_path,
        run_command=lambda *_args, **_kwargs: (_ for _ in ()).throw(FileNotFoundError()),
    )
    with pytest.raises(AgentRuntimeError, match="找不到安装命令"):
        missing.install("skills@latest add owner/repo")

    timeout = _skill_install_service(
        tmp_path,
        run_command=lambda argv, **_kwargs: (_ for _ in ()).throw(
            subprocess.TimeoutExpired(argv, timeout=600)
        ),
    )
    with pytest.raises(AgentRuntimeError, match="超时"):
        timeout.install("skills@latest add owner/repo")
