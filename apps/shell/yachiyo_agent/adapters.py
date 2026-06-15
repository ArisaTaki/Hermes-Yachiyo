"""Adapters from runtime-like payloads to public Yachiyo snapshots."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import AgentDefinitionSnapshot, ReadinessSnapshot
from .groups import agent_group_snapshot_from_payload, group_run_snapshot_from_payload
from .skills import (
    skill_folder_snapshot_from_payload,
    skill_snapshot_from_payload,
    skill_source_root_snapshot_from_payload,
)
from .task_cards import agent_task_snapshot_from_payload
from .timelines import run_timeline_snapshot_from_payload
from .workflows import workflow_snapshot_from_payload

__all__ = [
    "agent_definition_snapshot_from_payload",
    "agent_group_snapshot_from_payload",
    "agent_task_snapshot_from_payload",
    "group_run_snapshot_from_payload",
    "readiness_snapshot_from_payload",
    "run_timeline_snapshot_from_payload",
    "skill_folder_snapshot_from_payload",
    "skill_snapshot_from_payload",
    "skill_source_root_snapshot_from_payload",
    "workflow_snapshot_from_payload",
]


def readiness_snapshot_from_payload(payload: Mapping[str, Any]) -> ReadinessSnapshot:
    ready = bool(payload.get("ready", payload.get("ok", False)))
    return ReadinessSnapshot(
        ready=ready,
        status=_text(payload.get("status") or ("ready" if ready else "unavailable")),
        message=_optional_text(payload.get("message") or payload.get("error")),
        capabilities=_mapping(payload.get("capabilities")),
    )


def agent_definition_snapshot_from_payload(payload: Mapping[str, Any]) -> AgentDefinitionSnapshot:
    return AgentDefinitionSnapshot(
        agent_id=_text(payload.get("agent_id")),
        name=_text(payload.get("name") or payload.get("agent_id") or "Agent"),
        nickname=_optional_text(payload.get("nickname")),
        description=_optional_text(payload.get("description")),
        instructions=_optional_text(payload.get("instructions")),
        persona_prompt=_optional_text(payload.get("persona_prompt")),
        avatar_url=_optional_text(payload.get("avatar_url")),
        category=_optional_text(payload.get("category")),
        model_mode=_optional_text(payload.get("model_mode")),
        execution_backend=_optional_text(payload.get("execution_backend")),
        model_profile_id=_optional_text(payload.get("model_profile_id")),
        vision_model_profile_id=_optional_text(payload.get("vision_model_profile_id")),
        model_settings=_mapping(payload.get("model_config")),
        tool_policy=_mapping(payload.get("tool_policy")),
        workspace_policy=_mapping(payload.get("workspace_policy")),
        skill_ids=[str(item) for item in payload.get("skill_ids") or []],
        output_contract=_optional_text(payload.get("output_contract")),
        enabled=bool(payload.get("enabled", True)),
        virtual=bool(payload.get("virtual", False)),
        system=bool(payload.get("system", False)),
        builtin=bool(payload.get("builtin", False)),
        editable=bool(payload.get("editable", True)),
        deletable=bool(payload.get("deletable", True)),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
