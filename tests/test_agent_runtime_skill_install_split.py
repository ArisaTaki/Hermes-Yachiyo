"""Tests for Skill install command validation split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from apps.shell.agent_runtime import AgentRuntimeError, AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_skill_install_validator_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.SkillInstallCommandValidator is SkillInstallCommandValidator


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
        assert installer == "npx_skills"
        assert argv == ["npx", "-y", "skills@latest", "add", "owner/repo", "-a", "oha-yachiyo", "--copy"]
        assert service._skill_install_source_ref(argv, installer) == "https://github.com/owner/repo"
    finally:
        service.close()
