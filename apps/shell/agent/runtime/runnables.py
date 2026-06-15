"""Runnable catalog projections for Agents and Workflows."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeRunnableCatalog:
    """Builds public runnable summaries without owning persistence."""

    def __init__(
        self,
        *,
        node_kind: Callable[[dict[str, Any]], str],
        get_agent: Callable[[str], dict[str, Any]],
    ) -> None:
        self._node_kind = node_kind
        self._get_agent = get_agent

    def list_runnables(
        self,
        agents: list[dict[str, Any]],
        workflows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "runnables": [
                self.agent_summary(agent)
                for agent in agents
            ]
            + [
                self.workflow_summary(workflow)
                for workflow in workflows
            ],
        }

    @staticmethod
    def agent_summary(agent: dict[str, Any]) -> dict[str, Any]:
        tool_policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
        allowed_tools = tool_policy.get("allowed_tools") if isinstance(tool_policy.get("allowed_tools"), list) else []
        approval_required = (
            tool_policy.get("approval_required")
            if isinstance(tool_policy.get("approval_required"), dict)
            else {}
        )
        return {
            "id": agent["agent_id"],
            "name": agent["name"],
            "nickname": agent.get("nickname") or agent["name"],
            "description": agent.get("description") or "",
            "avatar_url": agent.get("avatar_url") or "",
            "category": agent.get("category") or "custom",
            "output_contract": agent.get("output_contract") or "chat",
            "kind": "agent",
            "enabled": agent["enabled"],
            "tool_policy": {
                "allowed_tools": [str(item) for item in allowed_tools if str(item)],
                "approval_required": {
                    str(tool): bool(required)
                    for tool, required in approval_required.items()
                    if str(tool)
                },
            },
        }

    def workflow_participants(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        participants: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for node in workflow.get("nodes") or []:
            if self._node_kind(node) != "agent":
                continue
            data = node.get("data") or {}
            agent_id = str(data.get("agent_id") or data.get("agentId") or "").strip()
            if not agent_id or agent_id in seen_ids:
                continue
            try:
                agent = self._get_agent(agent_id)
            except KeyError:
                continue
            seen_ids.add(agent_id)
            participants.append(self.agent_summary(agent))
        return participants

    def workflow_summary(self, workflow: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": workflow["workflow_id"],
            "name": workflow["name"],
            "description": workflow.get("description") or "",
            "kind": "workflow",
            "enabled": workflow["enabled"],
            "participants": self.workflow_participants(workflow),
        }

    @staticmethod
    def list_delegation_targets(
        agents: list[dict[str, Any]],
        workflows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "agents": [
                {
                    "kind": "agent",
                    "id": agent["agent_id"],
                    "name": agent["name"],
                    "description": agent.get("description") or "",
                    "category": agent.get("category") or "custom",
                    "output_contract": agent.get("output_contract") or "chat",
                }
                for agent in agents
                if agent.get("enabled", True) and not agent.get("system")
            ],
            "workflows": [
                {
                    "kind": "workflow",
                    "id": workflow["workflow_id"],
                    "name": workflow["name"],
                    "description": workflow.get("description") or "",
                    "nodes": len(workflow.get("nodes") or []),
                    "output_contract": "workflow",
                }
                for workflow in workflows
                if workflow.get("enabled", True)
            ],
        }
