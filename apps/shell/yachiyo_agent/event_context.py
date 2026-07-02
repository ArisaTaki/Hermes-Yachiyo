"""Helpers for applying PublicRunEvent top-level correlation context."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .contracts import PublicRunEvent


def run_event_context_payload(
    event: PublicRunEvent,
    payload: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(payload if payload is not None else event.payload)
    merged.update(run_event_context(event))
    return merged


def run_event_context(event: PublicRunEvent) -> dict[str, Any]:
    context: dict[str, Any] = {}
    _set(context, "parent_run_id", event.parent_run_id)
    _set(context, "source_run_id", event.source_run_id)
    _set(context, "core_id", event.core_id)
    _set(context, "workspace_id", event.workspace_id)
    _set(context, "task_id", event.task_id)
    _set(
        context,
        "source_runnable_id",
        _first(event.source_runnable_id, event.member_agent_id, event.agent_id),
    )
    _set(
        context,
        "source_runnable_name",
        _first(event.source_runnable_name, event.member_agent_name, event.agent_name),
    )
    _set(context, "workflow_id", event.workflow_id)
    _set(context, "workflow_run_id", event.workflow_run_id)
    _set(context, "workflow_node_id", event.workflow_node_id)
    _set(context, "workflow_node_label", event.workflow_node_label)
    _set(context, "group_id", event.group_id)
    _set(context, "group_run_id", _first(event.group_run_id, event.run_group_id))
    _set(context, "run_group_id", _first(event.run_group_id, event.group_run_id))
    _set(context, "agent_id", _first(event.agent_id, event.member_agent_id))
    _set(context, "agent_name", _first(event.agent_name, event.member_agent_name))
    _set(context, "member_agent_id", _first(event.member_agent_id, event.agent_id))
    _set(context, "member_agent_name", _first(event.member_agent_name, event.agent_name))
    return context


def _set(target: dict[str, Any], key: str, value: Any) -> None:
    text = _optional_text(value)
    if text:
        target[key] = text


def _first(*values: Any) -> str | None:
    for value in values:
        text = _optional_text(value)
        if text:
            return text
    return None


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None
