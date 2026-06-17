"""Agent group public snapshot mapping compatibility exports."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import (
    AgentGroupSnapshot,
    GroupRunSnapshot,
)
from .group_member_snapshots import (
    agent_group_member_from_payload,
    agent_group_members_from_payloads,
    group_run_participants_from_payload,
)
from .group_run_snapshots import group_run_snapshot_from_payload


def agent_group_snapshot_from_payload(
    payload: Mapping[str, Any] | AgentGroupSnapshot,
) -> AgentGroupSnapshot:
    if isinstance(payload, AgentGroupSnapshot):
        return payload

    return AgentGroupSnapshot(
        group_id=_text(payload.get("group_id") or payload.get("agent_group_id")),
        name=_text(payload.get("name") or "Agent Group"),
        description=_optional_text(payload.get("description")),
        members=agent_group_members_from_payloads(payload.get("members")),
        mode=_group_mode(payload.get("mode")),
        moderator_agent_id=_optional_text(payload.get("moderator_agent_id")),
        default_model=_optional_text(payload.get("default_model")),
        memory_scope=_memory_scope(payload.get("memory_scope")),
        tool_policy_id=_optional_text(payload.get("tool_policy_id")),
        enabled=bool(payload.get("enabled", True)),
        created_at=_text(payload.get("created_at")),
        updated_at=_text(payload.get("updated_at")),
    )


def _group_mode(value: Any) -> str:
    mode = _text(value) or "moderated"
    allowed = {"moderated", "round_robin", "debate", "pipeline", "parallel", "custom"}
    return mode if mode in allowed else "custom"


def _memory_scope(value: Any) -> str:
    scope = _text(value) or "shared"
    return scope if scope in {"shared", "per_agent", "hybrid"} else "shared"


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
