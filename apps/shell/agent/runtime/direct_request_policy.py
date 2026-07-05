"""Policy helpers for planner/direct tool requests."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def agent_with_direct_request_approvals(
    agent: dict[str, Any],
    direct_tool_requests: Any,
) -> dict[str, Any]:
    """Promote request-level approval flags into the temporary agent policy."""

    approval_overrides = approval_required_policy_from_direct_requests(
        direct_tool_requests,
    )
    if not approval_overrides:
        return agent

    policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
    approval_required = (
        dict(policy.get("approval_required"))
        if isinstance(policy.get("approval_required"), dict)
        else {}
    )
    changed = False
    for tool_name in approval_overrides:
        if approval_required.get(tool_name) is True:
            continue
        approval_required[tool_name] = True
        changed = True
    if not changed:
        return agent
    return {
        **agent,
        "tool_policy": {
            **policy,
            "approval_required": approval_required,
        },
    }


def approval_required_policy_from_direct_requests(
    direct_tool_requests: Any,
) -> dict[str, bool]:
    return {tool_name: True for tool_name in _approval_required_tools(direct_tool_requests)}


def _approval_required_tools(direct_tool_requests: Any) -> list[str]:
    raw_items = direct_tool_requests if isinstance(direct_tool_requests, list) else []
    tools: list[str] = []
    for item in raw_items:
        if not isinstance(item, Mapping):
            continue
        if not _request_requires_approval(item):
            continue
        tool_name = str(item.get("tool") or item.get("tool_name") or "").strip()
        if tool_name and tool_name not in tools:
            tools.append(tool_name)
    return tools


def _request_requires_approval(request: Mapping[str, Any]) -> bool:
    return any(
        request.get(key) is True
        for key in ("approval_required", "requires_approval", "approvalRequired")
    )
