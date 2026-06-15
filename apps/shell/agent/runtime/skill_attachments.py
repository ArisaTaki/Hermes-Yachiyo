"""Agent-to-Skill attachment operations for Agent Studio definitions."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class RuntimeAgentSkillAttachmentService:
    """Coordinates Agent skill membership without owning persistence."""

    def __init__(
        self,
        *,
        agent_definitions: Any,
        skill_records: Any,
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._agent_definitions = agent_definitions
        self._skill_records = skill_records
        self._error_type = error_type

    def attach(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        agent = self._agent_definitions.get(agent_id)
        skill = self._skill_records.get(skill_id)
        if not skill.get("enabled", True):
            raise self._error_type("Skill 已停用，不能挂载")
        skill_ids = list(dict.fromkeys([*agent.get("skill_ids", []), skill_id]))
        return self._agent_definitions.update(agent_id, {"skill_ids": skill_ids})

    def detach(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        agent = self._agent_definitions.get(agent_id)
        skill_ids = [item for item in agent.get("skill_ids", []) if item != skill_id]
        return self._agent_definitions.update(agent_id, {"skill_ids": skill_ids})
