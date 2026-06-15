"""Legacy Agent Studio group adapters backed by chat sessions and run groups."""

from __future__ import annotations

import json
from typing import Any
from uuid import uuid4

_GROUP_CONFIG_KIND = "group_config"
_GROUP_MODES = {"moderated", "round_robin", "debate", "pipeline", "parallel", "custom"}
_MEMORY_SCOPES = {"shared", "per_agent", "hybrid"}


def chat_group_snapshots(runtime: Any) -> list[dict[str, Any]]:
    try:
        store = _chat_store()
        sessions = store.list_sessions(limit=200)
    except Exception:
        return []
    return [
        _group_definition_from_chat_session(session, runtime)
        for session in sessions
        if str(getattr(session, "conversation_kind", "") or "") == "group"
    ]


def chat_group_snapshot(group_id: str, runtime: Any) -> dict[str, Any] | None:
    try:
        session = _chat_store().get_session(group_id)
    except Exception:
        return None
    if session is None:
        return None
    if str(getattr(session, "conversation_kind", "") or "") != "group":
        return None
    return _group_definition_from_chat_session(session, runtime)


def save_chat_group_snapshot(request: dict[str, Any], runtime: Any) -> dict[str, Any]:
    store = _chat_store()
    requested_group_id = str(
        request.get("group_id") or request.get("agent_group_id") or ""
    ).strip()
    existing = store.get_session(requested_group_id) if requested_group_id else None
    if existing is not None and getattr(existing, "conversation_kind", "") != "group":
        raise ValueError("只能修改手动 Agent 群组")

    existing_participants = (
        _parse_participants_json(getattr(existing, "participants_json", "[]"))
        if existing is not None
        else []
    )
    participants = _group_participants_from_request(request, runtime)
    if not participants and existing is not None:
        participants = existing_participants
    if not _agent_participants(participants):
        raise ValueError("群组至少需要一个已启用 Agent")
    participants = _with_group_config(
        participants,
        _group_config_from_request(
            request,
            participants,
            _group_config_from_participants(existing_participants),
        ),
    )

    group_id = requested_group_id or f"agent_group_{uuid4().hex[:12]}"
    if existing is None:
        store.create_session(group_id, _group_name_from_request(request, participants))
        existing = store.get_session(group_id)

    group_name = _group_name_from_request(request, participants, existing=existing)
    avatar_url = str(
        request.get("avatar_url")
        if request.get("avatar_url") is not None
        else getattr(existing, "avatar_url", "")
    ).strip()
    store.update_session_title(group_id, group_name)
    store.update_session_context(
        group_id,
        conversation_kind="group",
        runnable_id="",
        runnable_name=group_name,
        run_group_id=str(getattr(existing, "run_group_id", "") or ""),
        participants_json=json.dumps(participants, ensure_ascii=False),
        avatar_url=avatar_url,
    )
    saved = store.get_session(group_id)
    if saved is None:
        raise KeyError(group_id)
    return _group_definition_from_chat_session(saved, runtime)


def group_definition_from_run_group(run_group: dict[str, Any], runtime: Any) -> dict[str, Any]:
    run_group_id = str(run_group.get("run_group_id") or run_group.get("group_id") or "")
    members = _run_group_members(run_group, runtime)
    source = str(run_group.get("source") or "").strip()
    summary = str(run_group.get("summary") or "").strip()
    description_parts = [part for part in (source, summary) if part]
    return {
        "group_id": run_group_id,
        "name": str(run_group.get("title") or run_group_id or "Run Group"),
        "description": " · ".join(description_parts) or None,
        "members": members,
        "mode": _run_group_mode(source),
        "moderator_agent_id": members[0]["agent_id"] if members else None,
        "memory_scope": "shared",
        "enabled": True,
        "created_at": run_group.get("created_at") or "",
        "updated_at": run_group.get("updated_at") or "",
    }


def create_runnable_run(
    runtime: Any,
    *,
    runnable_id: str,
    user_goal: str,
    run_group_id: str = "",
    client_run_id: str = "",
    on_complete: Any | None = None,
) -> dict[str, Any]:
    create_async = getattr(runtime, "create_run_for_runnable_async", None)
    if callable(create_async):
        return create_async(
            runnable_id=runnable_id,
            user_goal=user_goal,
            run_group_id=run_group_id,
            on_complete=on_complete,
        )
    return runtime.create_run_for_runnable(
        runnable_id=runnable_id,
        user_goal=user_goal,
        run_group_id=run_group_id,
        client_run_id=client_run_id,
    )


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
    if client_run_id:
        payload["client_run_id"] = client_run_id
    if child_client_run_id:
        payload["child_client_run_id"] = child_client_run_id
    append_run_event(run_id, event_type, payload)


def _chat_store() -> Any:
    from apps.core.chat_store import get_chat_store

    return get_chat_store()


def _group_definition_from_chat_session(session: Any, runtime: Any) -> dict[str, Any]:
    del runtime
    participants = _parse_participants_json(getattr(session, "participants_json", "[]"))
    config = _group_config_from_participants(participants)
    members = [
        {
            "agent_id": str(item.get("id") or item.get("agent_id") or ""),
            "name": str(item.get("nickname") or item.get("name") or item.get("id") or ""),
            "role": str(item.get("role") or "member"),
            "sort_order": _int_or_default(item.get("sort_order"), index),
            "enabled": bool(item.get("enabled", True)),
        }
        for index, item in enumerate(_agent_participants(participants))
        if str(item.get("id") or item.get("agent_id") or "").strip()
    ]
    group_id = str(getattr(session, "session_id", "") or "").strip()
    name = str(
        getattr(session, "runnable_name", "")
        or getattr(session, "title", "")
        or group_id
        or "Agent Group"
    ).strip()
    return {
        "group_id": group_id,
        "name": name,
        "description": _optional_text(config.get("description")),
        "members": members,
        "mode": _normalized_group_mode(config.get("mode")),
        "moderator_agent_id": _group_moderator_from_config(config, members),
        "default_model": _optional_text(config.get("default_model")),
        "memory_scope": _normalized_memory_scope(config.get("memory_scope")),
        "tool_policy_id": _optional_text(config.get("tool_policy_id")),
        "enabled": _bool(config.get("enabled"), default=True),
        "created_at": getattr(session, "created_at", "") or "",
        "updated_at": "",
    }


def _group_participants_from_request(
    request: dict[str, Any],
    runtime: Any,
) -> list[dict[str, Any]]:
    agent_ids = _agent_ids_from_group_request(request)
    if not agent_ids:
        return []

    member_settings = _member_settings_from_group_request(request)
    participants = [_main_participant(runtime)]
    for index, agent_id in enumerate(agent_ids):
        participant = _participant_for_agent_id(runtime, agent_id)
        settings = member_settings.get(agent_id, {})
        if settings.get("role"):
            participant["role"] = settings["role"]
        participant["sort_order"] = settings.get("sort_order", index)
        if "enabled" in settings:
            participant["enabled"] = settings["enabled"]
        participants.append(participant)
    return participants


def _agent_ids_from_group_request(request: dict[str, Any]) -> list[str]:
    raw_items: list[Any] = []
    for key in ("participant_ids", "agent_ids", "member_ids"):
        value = request.get(key)
        if isinstance(value, list):
            raw_items.extend(value)

    for key in ("members", "participants"):
        value = request.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                raw_items.append(item.get("agent_id") or item.get("id"))
            else:
                raw_items.append(item)

    seen: set[str] = set()
    agent_ids: list[str] = []
    for raw_item in raw_items:
        agent_id = str(raw_item or "").strip()
        if not agent_id or agent_id == "main" or agent_id in seen:
            continue
        seen.add(agent_id)
        agent_ids.append(agent_id)
    return agent_ids


def _member_settings_from_group_request(
    request: dict[str, Any],
) -> dict[str, dict[str, Any]]:
    settings: dict[str, dict[str, Any]] = {}
    for key in ("members", "participants"):
        value = request.get(key)
        if not isinstance(value, list):
            continue
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue
            agent_id = str(item.get("agent_id") or item.get("id") or "").strip()
            if not agent_id or agent_id == "main":
                continue
            member: dict[str, Any] = {}
            role = _optional_text(item.get("role"))
            if role:
                member["role"] = role
            member["sort_order"] = _int_or_default(item.get("sort_order"), index)
            if "enabled" in item:
                member["enabled"] = _bool(item.get("enabled"), default=True)
            settings[agent_id] = member
    return settings


def _group_config_from_participants(participants: list[dict[str, Any]]) -> dict[str, Any]:
    for item in participants:
        if str(item.get("kind") or "") == _GROUP_CONFIG_KIND:
            return dict(item)
    return {}


def _with_group_config(
    participants: list[dict[str, Any]],
    config: dict[str, Any],
) -> list[dict[str, Any]]:
    return [
        item
        for item in participants
        if str(item.get("kind") or "") != _GROUP_CONFIG_KIND
    ] + [config]


def _group_config_from_request(
    request: dict[str, Any],
    participants: list[dict[str, Any]],
    existing_config: dict[str, Any],
) -> dict[str, Any]:
    member_ids = [
        str(item.get("id") or item.get("agent_id") or "").strip()
        for item in _agent_participants(participants)
        if str(item.get("id") or item.get("agent_id") or "").strip()
    ]
    moderator = _optional_text(
        request["moderator_agent_id"]
        if "moderator_agent_id" in request
        else existing_config.get("moderator_agent_id")
    )
    if moderator not in member_ids:
        moderator = member_ids[0] if member_ids else None

    enabled_value = (
        request["enabled"] if "enabled" in request else existing_config.get("enabled", True)
    )
    config: dict[str, Any] = {
        "kind": _GROUP_CONFIG_KIND,
        "schema_version": 1,
        "mode": _normalized_group_mode(
            request["mode"] if "mode" in request else existing_config.get("mode")
        ),
        "moderator_agent_id": moderator,
        "memory_scope": _normalized_memory_scope(
            request["memory_scope"]
            if "memory_scope" in request
            else existing_config.get("memory_scope")
        ),
        "enabled": _bool(enabled_value, default=True),
    }
    for key in ("description", "default_model", "tool_policy_id"):
        value = request[key] if key in request else existing_config.get(key)
        text = _optional_text(value)
        if text:
            config[key] = text
    return config


def _group_moderator_from_config(
    config: dict[str, Any],
    members: list[dict[str, Any]],
) -> str | None:
    member_ids = {str(member.get("agent_id") or "") for member in members}
    moderator = _optional_text(config.get("moderator_agent_id"))
    if moderator and moderator in member_ids:
        return moderator
    return members[0]["agent_id"] if members else None


def _normalized_group_mode(value: Any) -> str:
    mode = str(value or "").strip()
    if not mode:
        return "moderated"
    return mode if mode in _GROUP_MODES else "custom"


def _normalized_memory_scope(value: Any) -> str:
    scope = str(value or "").strip()
    return scope if scope in _MEMORY_SCOPES else "shared"


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
    if not text:
        return default
    if text in {"0", "false", "no", "off", "disabled"}:
        return False
    if text in {"1", "true", "yes", "on", "enabled"}:
        return True
    return default


def _int_or_default(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _participant_for_agent_id(runtime: Any, agent_id: str) -> dict[str, Any]:
    resolve_runnable = getattr(runtime, "resolve_runnable", None)
    if not callable(resolve_runnable):
        return {"kind": "agent", "id": agent_id, "name": agent_id}

    try:
        runnable = resolve_runnable(runnable_id=agent_id)
    except TypeError:
        runnable = resolve_runnable(agent_id)

    if not isinstance(runnable, dict) or runnable.get("kind", "agent") != "agent":
        raise ValueError("群组成员必须是已启用的 Agent")
    if not runnable.get("enabled", True):
        raise ValueError("群组成员包含已停用 Agent")
    return _participant_for_runnable(runnable)


def _participant_for_runnable(runnable: dict[str, Any]) -> dict[str, Any]:
    participant = {
        "kind": "agent",
        "id": str(runnable.get("id") or runnable.get("agent_id") or ""),
        "name": str(runnable.get("name") or runnable.get("id") or ""),
    }
    for key in (
        "nickname",
        "description",
        "avatar_url",
        "category",
        "output_contract",
    ):
        value = runnable.get(key)
        if value:
            participant[key] = str(value)
    tool_policy = runnable.get("tool_policy")
    if isinstance(tool_policy, dict):
        participant["tool_policy"] = dict(tool_policy)
    return participant


def _main_participant(runtime: Any) -> dict[str, Any]:
    assistant = getattr(getattr(runtime, "config", None), "assistant", None)
    participant: dict[str, Any] = {
        "kind": "main",
        "id": "main",
        "name": str(getattr(assistant, "agent_name", "") or "Yachiyo"),
        "nickname": str(getattr(assistant, "agent_nickname", "") or "月見八千代"),
    }
    avatar_path = str(getattr(assistant, "agent_avatar_path", "") or "")
    if avatar_path:
        participant["avatar_path"] = avatar_path
    return participant


def _parse_participants_json(value: str | None) -> list[dict[str, Any]]:
    if not value:
        return []
    try:
        payload = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return []
    if not isinstance(payload, list):
        return []
    return [item for item in payload if isinstance(item, dict)]


def _agent_participants(participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        item
        for item in participants
        if str(item.get("kind") or "agent") == "agent"
        and str(item.get("id") or item.get("agent_id") or "").strip()
    ]


def _group_name_from_request(
    request: dict[str, Any],
    participants: list[dict[str, Any]],
    *,
    existing: Any | None = None,
) -> str:
    name = str(request.get("name") or "").strip()
    if name:
        return name
    existing_name = str(
        getattr(existing, "runnable_name", "") or getattr(existing, "title", "")
    ).strip()
    if existing_name:
        return existing_name
    names = [
        str(item.get("nickname") or item.get("name") or "").strip()
        for item in participants
        if str(item.get("kind") or "") in {"main", "agent"}
    ]
    return "、".join([name for name in names if name]) or "新群组"


def _run_group_members(run_group: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
    members: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, run_id in enumerate(run_group.get("child_run_ids") or []):
        try:
            run = runtime.get_run(str(run_id))
        except Exception:
            continue
        agent_id = str(run.get("agent_id") or run.get("runnable_id") or "").strip()
        if not agent_id or agent_id in seen:
            continue
        seen.add(agent_id)
        members.append(
            {
                "agent_id": agent_id,
                "name": str(run.get("runnable_name") or agent_id),
                "role": str(run.get("kind") or "member"),
                "sort_order": index,
                "enabled": True,
            }
        )
    return members


def _run_group_mode(source: str) -> str:
    clean = source.strip().lower()
    if clean == "workflow":
        return "pipeline"
    if clean in {"delegation", "agent"}:
        return "moderated"
    return "custom"


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
