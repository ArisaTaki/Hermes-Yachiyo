"""Helpers for materializing replan deferred tool continuations."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any


def materialized_deferred_items(source: Mapping[str, Any]) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    deferred_tool = str(source.get("deferred_tool") or "").strip()
    if deferred_tool:
        deferred_request: dict[str, Any] = {
            "tool": deferred_tool,
            "input": (
                dict(source.get("deferred_input"))
                if isinstance(source.get("deferred_input"), Mapping)
                else {}
            ),
        }
        context = (
            source.get("deferred_context")
            if isinstance(source.get("deferred_context"), Mapping)
            else {}
        )
        for key, value in context.items():
            if key not in {"tool", "tool_name", "input"} and value not in (
                None,
                "",
                [],
                {},
            ):
                deferred_request.setdefault(key, value)
        for key in (
            "approval_required",
            "desktop_execution_policy",
            "desktop_loop",
            "desktop_provider_session",
            "risk_level",
            "policy_reason",
            "runtime_stage",
            "runtime_role",
            "sandbox_desktop_provider",
            "sandbox_provider",
            "requires_observation",
            "requires_post_action_verification",
        ):
            value = source.get(key)
            if value not in (None, "", [], {}) and key not in deferred_request:
                deferred_request[key] = dict(value) if isinstance(value, Mapping) else value
        items.append(deferred_request)
    items.extend(_mapping_list(source.get("deferred_continuation")))
    return items


def safe_deferred_continuation_request(
    item: Mapping[str, Any],
    allowed: set[str],
    *,
    auto_safe_tools: Iterable[str],
    allow_approved_unsafe: bool = False,
    approved_unsafe_tools: Iterable[str] = (),
) -> dict[str, Any]:
    tool_name = str(item.get("tool") or item.get("tool_name") or "").strip()
    if not tool_name or tool_name not in allowed:
        return {}
    auto_safe = {str(tool or "").strip() for tool in auto_safe_tools}
    approved_unsafe = {str(tool or "").strip() for tool in approved_unsafe_tools}
    if tool_name not in auto_safe and not (
        allow_approved_unsafe and tool_name in approved_unsafe
    ):
        return {}
    risk_level = str(item.get("risk_level") or "").strip().lower()
    if risk_level in {"high", "critical"}:
        return {}
    request = dict(item)
    request["tool"] = tool_name
    raw_input = item.get("input") if isinstance(item.get("input"), Mapping) else {}
    request["input"] = dict(raw_input)
    request.pop("tool_name", None)
    request.pop("continue_to_model", None)
    if bool(item.get("approval_required")):
        if not allow_approved_unsafe:
            return {}
        request.pop("approval_required", None)
        request["approval_status"] = "approved"
        request["approved_by_replan_recovery_action"] = True
    return request


def _mapping_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, Mapping)]
