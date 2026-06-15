"""Tests for agent skill loading split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.agent_skills import RuntimeAgentSkillLoader
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def _loader(skills: dict[str, dict[str, Any]]) -> RuntimeAgentSkillLoader:
    def get_skill(skill_id: str) -> dict[str, Any]:
        try:
            return skills[skill_id]
        except KeyError as exc:
            raise KeyError(skill_id) from exc

    return RuntimeAgentSkillLoader(
        get_skill=get_skill,
        error_type=AgentRuntimeError,
    )


def test_runtime_agent_skill_loader_loads_enabled_skills_in_order() -> None:
    skill_one = {"skill_id": "skill-1", "name": "Read Brief", "enabled": True}
    skill_two = {"skill_id": "skill-2", "name": "Write Notes"}

    assert _loader({"skill-1": skill_one, "skill-2": skill_two}).load(["skill-2", "skill-1"]) == [
        skill_two,
        skill_one,
    ]


def test_runtime_agent_skill_loader_rejects_missing_skills() -> None:
    with pytest.raises(AgentRuntimeError, match="不存在：skill-missing"):
        _loader({}).load(["skill-missing"])


def test_runtime_agent_skill_loader_rejects_disabled_skills() -> None:
    with pytest.raises(AgentRuntimeError, match="已停用：Paused Skill"):
        _loader({"skill-1": {"skill_id": "skill-1", "name": "Paused Skill", "enabled": False}}).load(
            ["skill-1"]
        )


def test_native_runtime_uses_split_agent_skill_loader(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    source = tmp_path / "runtime-skill"
    source.mkdir()
    (source / "SKILL.md").write_text("# Runtime Skill\n\nLoad me.", encoding="utf-8")
    try:
        assert agent_runtime.RuntimeAgentSkillLoader is RuntimeAgentSkillLoader
        assert isinstance(service.agent_skill_loader, RuntimeAgentSkillLoader)
        skill = service.import_skill(str(source))
        assert service._load_agent_skills([skill["skill_id"]])[0]["skill_id"] == skill["skill_id"]
    finally:
        service.close()
