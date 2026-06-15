"""Tests for Agent-Skill attachment operations split out of the legacy runtime."""

from __future__ import annotations

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.skill_attachments import RuntimeAgentSkillAttachmentService


class _FakeAgentDefinitions:
    def __init__(self) -> None:
        self.agent = {"agent_id": "agent_1", "skill_ids": ["skill_a"]}
        self.updates: list[tuple[str, dict[str, object]]] = []

    def get(self, agent_id: str) -> dict[str, object]:
        assert agent_id == "agent_1"
        return dict(self.agent)

    def update(self, agent_id: str, payload: dict[str, object]) -> dict[str, object]:
        assert agent_id == "agent_1"
        self.updates.append((agent_id, dict(payload)))
        self.agent = {**self.agent, **payload}
        return dict(self.agent)


class _FakeSkillRecords:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled

    def get(self, skill_id: str) -> dict[str, object]:
        return {"skill_id": skill_id, "enabled": self.enabled}


def test_runtime_agent_skill_attachment_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeAgentSkillAttachmentService is RuntimeAgentSkillAttachmentService


def test_agent_skill_attachment_service_attaches_unique_enabled_skill() -> None:
    agents = _FakeAgentDefinitions()
    service = RuntimeAgentSkillAttachmentService(
        agent_definitions=agents,
        skill_records=_FakeSkillRecords(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = service.attach("agent_1", "skill_b")
    duplicate = service.attach("agent_1", "skill_b")

    assert result["skill_ids"] == ["skill_a", "skill_b"]
    assert duplicate["skill_ids"] == ["skill_a", "skill_b"]
    assert agents.updates[-1] == ("agent_1", {"skill_ids": ["skill_a", "skill_b"]})


def test_agent_skill_attachment_service_rejects_disabled_skill() -> None:
    service = RuntimeAgentSkillAttachmentService(
        agent_definitions=_FakeAgentDefinitions(),
        skill_records=_FakeSkillRecords(enabled=False),
        error_type=agent_runtime.AgentRuntimeError,
    )

    with pytest.raises(agent_runtime.AgentRuntimeError, match="Skill 已停用"):
        service.attach("agent_1", "skill_b")


def test_agent_skill_attachment_service_detaches_skill() -> None:
    agents = _FakeAgentDefinitions()
    service = RuntimeAgentSkillAttachmentService(
        agent_definitions=agents,
        skill_records=_FakeSkillRecords(),
        error_type=agent_runtime.AgentRuntimeError,
    )

    result = service.detach("agent_1", "skill_a")

    assert result["skill_ids"] == []
    assert agents.updates == [("agent_1", {"skill_ids": []})]
