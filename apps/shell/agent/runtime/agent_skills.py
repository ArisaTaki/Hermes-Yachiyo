"""Agent skill loading helpers for runtime run preparation."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeAgentSkillLoader:
    """Loads mounted skills while preserving legacy runtime validation errors."""

    def __init__(
        self,
        *,
        get_skill: Callable[[str], dict[str, Any]],
        error_type: type[Exception],
    ) -> None:
        self._get_skill = get_skill
        self._error_type = error_type

    def load(self, skill_ids: list[str]) -> list[dict[str, Any]]:
        skills: list[dict[str, Any]] = []
        for skill_id in skill_ids:
            try:
                skill = self._get_skill(skill_id)
            except KeyError as exc:
                raise self._error_type(f"Agent 挂载的 Skill 不存在：{skill_id}") from exc
            if not skill.get("enabled", True):
                raise self._error_type(f"Agent 挂载的 Skill 已停用：{skill.get('name') or skill_id}")
            skills.append(skill)
        return skills
