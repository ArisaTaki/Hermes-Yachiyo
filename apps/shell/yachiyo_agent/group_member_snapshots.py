"""Agent group member public snapshot mapping."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_secrets

from .contracts import AgentGroupMemberSnapshot


def agent_group_member_from_payload(payload: Mapping[str, Any]) -> AgentGroupMemberSnapshot:
    return AgentGroupMemberSnapshot(
        agent_id=_text(payload.get("agent_id")),
        name=_text(payload.get("name") or payload.get("agent_name") or payload.get("agent_id")),
        role=_optional_text(payload.get("role")),
        sort_order=_int(payload.get("sort_order")),
        enabled=bool(payload.get("enabled", True)),
    )


def agent_group_members_from_payloads(payloads: Any) -> list[AgentGroupMemberSnapshot]:
    if not isinstance(payloads, list):
        return []
    return [agent_group_member_from_payload(item) for item in payloads if isinstance(item, Mapping)]


def group_run_participants_from_payload(
    payload: Mapping[str, Any],
) -> list[AgentGroupMemberSnapshot]:
    participants = agent_group_members_from_payloads(payload.get("participants"))
    return participants or agent_group_members_from_payloads(payload.get("members"))


def _text(value: Any) -> str:
    return str(redact_secrets(value) or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None


def _int(value: Any) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0
