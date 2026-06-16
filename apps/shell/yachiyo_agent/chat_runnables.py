"""Chat-facing runnable catalog adapters."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    ChatRunnableCatalogSnapshot,
    ChatRunnableParticipantSnapshot,
    ChatRunnableSnapshot,
)


def chat_runnable_catalog_from_payloads(
    agent_payloads: Iterable[Mapping[str, Any]],
    workflow_payloads: Iterable[Mapping[str, Any]],
) -> ChatRunnableCatalogSnapshot:
    agents = [chat_agent_runnable_from_payload(payload) for payload in agent_payloads]
    agents_by_id = {agent.runnable_id: agent for agent in agents if agent.runnable_id}
    workflows = [
        chat_workflow_runnable_from_payload(payload, agents_by_id)
        for payload in workflow_payloads
    ]
    return ChatRunnableCatalogSnapshot(agents=agents, workflows=workflows)


def chat_agent_runnable_from_payload(payload: Mapping[str, Any]) -> ChatRunnableSnapshot:
    agent_id = _text(payload.get("agent_id") or payload.get("id"))
    tool_policy = _mapping(payload.get("tool_policy"))
    return ChatRunnableSnapshot(
        runnable_id=agent_id,
        agent_id=agent_id,
        kind="agent",
        name=_text(payload.get("name") or agent_id or "Agent"),
        nickname=_optional_text(payload.get("nickname")),
        description=_optional_text(payload.get("description")),
        avatar_url=_optional_text(payload.get("avatar_url")),
        category=_optional_text(payload.get("category")),
        output_contract=_optional_text(payload.get("output_contract")),
        enabled=bool(payload.get("enabled", True)),
        tool_capabilities=_tool_capabilities(tool_policy),
        approval_required_tools=_approval_required_tools(tool_policy),
    )


def chat_workflow_runnable_from_payload(
    payload: Mapping[str, Any],
    agents_by_id: Mapping[str, ChatRunnableSnapshot],
) -> ChatRunnableSnapshot:
    workflow_id = _text(payload.get("workflow_id") or payload.get("id"))
    return ChatRunnableSnapshot(
        runnable_id=workflow_id,
        workflow_id=workflow_id,
        kind="workflow",
        name=_text(payload.get("name") or workflow_id or "Workflow"),
        description=_optional_text(payload.get("description")),
        output_contract="workflow",
        enabled=bool(payload.get("enabled", True)),
        participants=_workflow_participants(payload, agents_by_id),
    )


def _workflow_participants(
    payload: Mapping[str, Any],
    agents_by_id: Mapping[str, ChatRunnableSnapshot],
) -> list[ChatRunnableParticipantSnapshot]:
    participants: list[ChatRunnableParticipantSnapshot] = []
    seen: set[str] = set()
    nodes = payload.get("nodes") if isinstance(payload.get("nodes"), list) else []
    for item in nodes:
        if not isinstance(item, Mapping):
            continue
        agent_id = _workflow_node_agent_id(item)
        if not agent_id or agent_id in seen:
            continue
        agent = agents_by_id.get(agent_id)
        if agent is None:
            continue
        seen.add(agent_id)
        participants.append(
            ChatRunnableParticipantSnapshot(
                runnable_id=agent.runnable_id,
                agent_id=agent.agent_id,
                workflow_id=agent.workflow_id,
                kind=agent.kind,
                name=agent.name,
                nickname=agent.nickname,
                avatar_url=agent.avatar_url,
                category=agent.category,
                enabled=agent.enabled,
            )
        )
    return participants


def _workflow_node_agent_id(node: Mapping[str, Any]) -> str:
    data = _mapping(node.get("data"))
    if _workflow_node_kind(node, data) != "agent":
        return ""
    for key in ("agent_id", "agentId", "runnable_id", "runnableId"):
        value = data.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _workflow_node_kind(node: Mapping[str, Any], data: Mapping[str, Any]) -> str:
    return _text(data.get("kind") or data.get("node_type") or node.get("type") or "agent")


def _tool_capabilities(policy: Mapping[str, Any]) -> list[str]:
    return _string_list(policy.get("allowed_tools"))


def _approval_required_tools(policy: Mapping[str, Any]) -> list[str]:
    explicit = _string_list(policy.get("approval_required_tools"))
    approval_required = policy.get("approval_required")
    if isinstance(approval_required, Mapping):
        explicit.extend(
            str(tool).strip()
            for tool, required in approval_required.items()
            if str(tool).strip() and required is True
        )
    return _dedupe(explicit)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return _dedupe(str(item).strip() for item in value if str(item).strip())


def _dedupe(items: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        result.append(item)
    return result


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _text(value: Any) -> str:
    return str(value or "").strip()


def _optional_text(value: Any) -> str | None:
    text = _text(value)
    return text or None
