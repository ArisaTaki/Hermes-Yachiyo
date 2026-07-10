"""Runtime-owned helpers for GroupRun child execution and event recording."""

from __future__ import annotations

import inspect
from typing import Any

from apps.shell.yachiyo_agent.policy import group_tool_policy_for_id, merge_tool_policies


def create_runnable_run(
    runtime: Any,
    *,
    runnable_id: str,
    user_goal: str,
    run_group_id: str = "",
    client_run_id: str = "",
    on_complete: Any | None = None,
    agent_override: dict[str, Any] | None = None,
    daily_desktop_policy_overlay: bool = False,
    runtime_planner_entrypoint: bool = False,
    runtime_execution_envelope: dict[str, Any] | None = None,
    metadata: dict[str, Any] | None = None,
    direct_tool_requests: list[dict[str, Any]] | None = None,
    daily_desktop_planning_context: str | None = None,
) -> dict[str, Any]:
    create_async = getattr(runtime, "create_run_for_runnable_async", None)
    payload = {
        "runnable_id": runnable_id,
        "user_goal": user_goal,
        "run_group_id": run_group_id,
    }
    if agent_override is not None:
        payload["agent_override"] = agent_override
    if daily_desktop_policy_overlay:
        payload["daily_desktop_policy_overlay"] = True
    if runtime_planner_entrypoint:
        payload["runtime_planner_entrypoint"] = True
    if runtime_execution_envelope is not None:
        payload["runtime_execution_envelope"] = runtime_execution_envelope
    if metadata is not None:
        payload["metadata"] = metadata
    if direct_tool_requests is not None:
        payload["direct_tool_requests"] = direct_tool_requests
    if daily_desktop_planning_context is not None:
        payload["daily_desktop_planning_context"] = daily_desktop_planning_context
    if callable(create_async):
        payload["on_complete"] = on_complete
        return _call_with_supported_kwargs(create_async, payload)
    payload["client_run_id"] = client_run_id
    return _call_with_supported_kwargs(runtime.create_run_for_runnable, payload)


def append_group_member_event(
    runtime: Any,
    run: dict[str, Any],
    event_type: str,
    *,
    group_id: str,
    group: dict[str, Any] | None = None,
    run_group_id: str,
    objective: str,
    member: dict[str, Any],
    member_index: int,
    client_run_id: str = "",
    child_client_run_id: str = "",
    orchestration: dict[str, Any] | None = None,
) -> None:
    append_run_event = getattr(runtime, "append_run_event", None)
    run_id = str(run.get("run_id") or "").strip()
    if not callable(append_run_event) or not run_id:
        return
    payload = {
        "agent_id": str(member.get("agent_id") or run.get("runnable_id") or ""),
        "agent_name": str(member.get("name") or run.get("runnable_name") or ""),
        "group_id": group_id,
        "member_index": member_index,
        "member_role": str(member.get("role") or ""),
        "objective": objective,
        "run_group_id": run_group_id or str(run.get("run_group_id") or ""),
        "run_id": run_id,
        "status": str(run.get("status") or ""),
    }
    if group:
        payload.update(_group_event_context(group))
    inherited_policy_id = _optional_text(member.get("inherited_tool_policy_id"))
    if inherited_policy_id:
        payload["inherited_tool_policy_id"] = inherited_policy_id
    inherited_policy = member.get("tool_policy")
    if isinstance(inherited_policy, dict) and isinstance(
        inherited_policy.get("allowed_tools"), list
    ):
        payload["member_allowed_tools"] = [
            str(tool or "").strip()
            for tool in inherited_policy["allowed_tools"]
            if str(tool or "").strip()
        ]
    if client_run_id:
        payload["client_run_id"] = client_run_id
    if child_client_run_id:
        payload["child_client_run_id"] = child_client_run_id
    if orchestration:
        payload.update(orchestration)
    append_run_event(run_id, event_type, payload)


def append_group_run_event(
    runtime: Any,
    run: dict[str, Any],
    event_type: str,
    *,
    group_id: str,
    group: dict[str, Any] | None = None,
    run_group_id: str,
    objective: str,
    status: str = "",
    members: list[dict[str, Any]] | None = None,
    child_run_ids: list[str] | None = None,
    client_run_id: str = "",
    orchestration: dict[str, Any] | None = None,
) -> None:
    append_run_event = getattr(runtime, "append_run_event", None)
    run_id = str(run.get("run_id") or "").strip()
    if not callable(append_run_event) or not run_id:
        return
    payload = {
        "child_run_ids": [str(item) for item in child_run_ids or [] if str(item)],
        "group_id": group_id,
        "group_run_id": run_group_id or str(run.get("run_group_id") or ""),
        "objective": objective,
        "participant_count": len(members or []),
        "run_group_id": run_group_id or str(run.get("run_group_id") or ""),
        "status": status or str(run.get("status") or "running"),
    }
    if group:
        payload.update(_group_event_context(group))
    if client_run_id:
        payload["client_run_id"] = client_run_id
    if orchestration:
        payload.update(orchestration)
    append_run_event(run_id, event_type, payload)


def group_member_agent_override(
    runtime: Any,
    member: dict[str, Any],
    group: dict[str, Any],
) -> dict[str, Any] | None:
    inherited_policy = group_tool_policy_for_id(_optional_text(group.get("tool_policy_id")))
    if not inherited_policy:
        return None
    agent_id = str(member.get("agent_id") or member.get("id") or "").strip()
    if not agent_id:
        return None
    agent = _private_agent_for_group_member(runtime, agent_id)
    if agent is None:
        return None
    return {
        **agent,
        "tool_policy": merge_tool_policies(agent.get("tool_policy"), inherited_policy),
        "inherited_tool_policy_id": _optional_text(group.get("tool_policy_id")),
    }


def group_member_with_inherited_policy(
    runtime: Any,
    member: dict[str, Any],
    group: dict[str, Any],
) -> dict[str, Any]:
    override = group_member_agent_override(runtime, member, group)
    if override is None:
        return member
    return {
        **member,
        "tool_policy": dict(override.get("tool_policy") or {}),
        "inherited_tool_policy_id": _optional_text(group.get("tool_policy_id")),
    }


def _call_with_supported_kwargs(
    callable_obj: Any,
    payload: dict[str, Any],
) -> dict[str, Any]:
    try:
        signature = inspect.signature(callable_obj)
    except (TypeError, ValueError):
        return callable_obj(**payload)
    if any(
        parameter.kind == inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    ):
        return callable_obj(**payload)
    return callable_obj(
        **{key: value for key, value in payload.items() if key in signature.parameters}
    )


def _private_agent_for_group_member(runtime: Any, agent_id: str) -> dict[str, Any] | None:
    for getter_name in ("_get_agent_private", "get_agent"):
        getter = getattr(runtime, getter_name, None)
        if not callable(getter):
            continue
        try:
            agent = getter(agent_id)
        except KeyError:
            continue
        if isinstance(agent, dict):
            return dict(agent)
    return None


def _group_event_context(group: dict[str, Any]) -> dict[str, Any]:
    context: dict[str, Any] = {}
    for source_key, event_key in (
        ("name", "group_name"),
        ("mode", "group_mode"),
        ("moderator_agent_id", "group_moderator_agent_id"),
        ("memory_scope", "group_memory_scope"),
        ("tool_policy_id", "group_tool_policy_id"),
    ):
        value = _optional_text(group.get(source_key))
        if value:
            context[event_key] = value
    context["group_enabled"] = _bool(group.get("enabled"), default=True)
    return context


def _optional_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _bool(value: Any, *, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    text = str(value).strip().lower()
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    return default
