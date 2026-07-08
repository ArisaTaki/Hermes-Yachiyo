"""Shared daily desktop runtime helpers for Chat, Bubble, and Live2D."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from typing import Any

from apps.shell.agent.runtime.desktop_intents import (
    daily_desktop_entrypoint_tool_requests,
    daily_desktop_metadata_tool_request,
    daily_desktop_recovery_prompt,
)
from apps.shell.agent.tools.policy import DAILY_DESKTOP_TOOL_NAMES

logger = logging.getLogger(__name__)

_ENTRYPOINT_DISCOVERY_TOOLS = {
    "desktop.list_apps",
    "desktop.inspect_app",
    "desktop.running_apps",
    "desktop.permissions",
}
_ENTRYPOINT_VERIFY_TOOLS = {
    "desktop.active_window",
    "desktop.list_windows",
    "desktop.read_ui",
    "desktop.windows",
    "desktop.ui_elements",
    "screen.capture",
}
_ENTRYPOINT_NON_PRIMARY_TOOLS = {
    *_ENTRYPOINT_DISCOVERY_TOOLS,
    *_ENTRYPOINT_VERIFY_TOOLS,
}
_ENTRYPOINT_TIMELINE_CONTEXT_KEYS = (
    "request_id",
    "step_id",
    "capability_id",
    "decision_id",
    "plan_id",
    "tool_plan_id",
    "intent_kind",
    "core_id",
    "workspace_id",
    "group_run_id",
    "run_group_id",
    "group_id",
    "workflow_run_id",
    "workflow_id",
    "workflow_node_id",
    "workflow_node_label",
    "workflow_node_kind",
    "approval_required",
    "depends_on",
    "fallback_tools",
    "legacy_fallback",
    "compatibility_boundary",
    "runtime_doctrine",
    "runtime_stage",
    "runtime_role",
    "requires_observation",
    "requires_post_action_verification",
    "replan_triggers",
    "replan_signal_ids",
    "task_todo",
    "task_checkpoints",
    "task_workspace_items",
    "task_verification_targets",
)
_DESKTOP_AGENT_ENTRYPOINT_EXTRA_TOOLS = (
    "workspace.list",
    "workspace.read",
    "data.analyze",
    "workspace.write_patch",
    "file.organize",
    "terminal.run",
    "python.run",
    "artifact.write",
)
_DIRECT_BROWSER_ENTRYPOINT_TOOLS = frozenset(
    {
        "browser.open_url",
        "browser.open_url_and_extract_text",
    }
)


def daily_desktop_allowed_tools(
    allowed_tools: Sequence[str] | None = None,
) -> list[str]:
    if allowed_tools is None:
        allowed_tools = DAILY_DESKTOP_TOOL_NAMES
    return [
        str(tool or "").strip()
        for tool in allowed_tools
        if str(tool or "").strip()
    ]


def desktop_agent_entrypoint_allowed_tools(
    allowed_tools: Sequence[str] | None = None,
) -> list[str]:
    """Fallback tool boundary for Chat/Bubble/Live2D as desktop agent entrypoints."""

    allowed = daily_desktop_allowed_tools(allowed_tools)
    result: list[str] = []
    seen: set[str] = set()
    for tool in [*allowed, *_DESKTOP_AGENT_ENTRYPOINT_EXTRA_TOOLS]:
        clean = str(tool or "").strip()
        if not clean or clean in seen:
            continue
        seen.add(clean)
        result.append(clean)
    return result


def direct_browser_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
    text: str = "",
) -> list[dict[str, Any]]:
    """Return direct low-risk browser requests even when artifact tools are available."""

    request_list = [request for request in requests or [] if isinstance(request, Mapping)]
    if len(request_list) != 1:
        return []
    if _looks_like_browser_artifact_request(text):
        return []
    request = request_list[0]
    tool_name = str(request.get("tool") or "").strip()
    if tool_name not in _DIRECT_BROWSER_ENTRYPOINT_TOOLS:
        return []
    if str(request.get("source") or "").strip() != "runtime_planner":
        return []
    if str(request.get("planning_reason") or "").strip() != "planner_fallback_web_research":
        return []
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    if not str(payload.get("url") or "").strip():
        return []
    normalized = dict(request)
    normalized.pop("continue_to_model", None)
    return [normalized]


def _looks_like_browser_artifact_request(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(
        re.search(
            r"(?:报告|文档|文件|产出|输出|导出|保存|生成\s*(?:一份)?\s*(?:报告|文档|文件)|"
            r"\breport\b|\bartifact\b|\bsave\b|\bexport\b)",
            value,
            flags=re.IGNORECASE,
        )
    )


def main_chat_entrypoint_allowed_tools(
    runtime: Any | None,
    *,
    fallback: Sequence[str] | None = None,
) -> list[str]:
    for policy in _runtime_main_chat_tool_policies(runtime):
        allowed = policy.get("allowed_tools") if isinstance(policy, Mapping) else None
        if allowed:
            return desktop_agent_entrypoint_allowed_tools(
                [*daily_desktop_allowed_tools(allowed), *DAILY_DESKTOP_TOOL_NAMES]
            )
    return desktop_agent_entrypoint_allowed_tools(fallback)


def daily_desktop_entrypoint_requests(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
) -> list[dict[str, Any]]:
    allowed = daily_desktop_allowed_tools(allowed_tools)
    planner_requests = _planner_owned_legacy_compatible_entrypoint_requests(
        str(text or ""),
        allowed,
        metadata=metadata,
    )
    if planner_requests:
        return planner_requests
    return daily_desktop_entrypoint_tool_requests(
        str(text or ""),
        allowed,
        metadata=metadata,
    )


def _planner_owned_legacy_compatible_entrypoint_requests(
    text: str,
    allowed: Sequence[str],
    *,
    metadata: Mapping[str, Any] | None,
) -> list[dict[str, Any]]:
    try:
        from .planner_execution import planner_tool_requests

        planner_requests = planner_tool_requests(
            str(text or ""),
            allowed,
            metadata=metadata,
        )
    except Exception:
        logger.debug("Runtime planner legacy-compatible entrypoint unavailable", exc_info=True)
        return []
    media_requests = _legacy_compatible_media_entrypoint_requests(
        planner_requests,
        text=text,
    )
    if media_requests:
        return media_requests
    search_requests = _legacy_compatible_search_entrypoint_requests(
        planner_requests,
        text=text,
    )
    if search_requests:
        return search_requests
    return _legacy_compatible_simple_entrypoint_requests(planner_requests, text=text)


def _legacy_compatible_media_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
    *,
    text: str,
) -> list[dict[str, Any]]:
    if not requests:
        return []
    items = [dict(request) for request in requests if isinstance(request, Mapping)]
    if not items:
        return []
    if not any(
        str(request.get("planning_reason") or "").strip() == "planner_fallback_media_playback"
        for request in items
    ):
        return []
    visible = [
        request
        for request in _visible_entrypoint_plan_requests(items)
        if str(request.get("tool") or "").strip() not in {"desktop.ui_elements"}
    ]
    if not visible:
        return []
    if any(_request_has_selected_app_placeholder(request) for request in visible):
        return []
    tools = [str(request.get("tool") or "").strip() for request in visible]
    if _legacy_compatible_simple_media_request(tools):
        return [_legacy_shape_request(visible[0])]
    if _legacy_compatible_named_music_search_sequence(visible, tools, text=text):
        return [_legacy_shape_request(request) for request in visible]
    return []


def _legacy_compatible_search_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
    *,
    text: str,
) -> list[dict[str, Any]]:
    if not requests:
        return []
    items = [dict(request) for request in requests if isinstance(request, Mapping)]
    if not items:
        return []
    if not any(
        str(request.get("planning_reason") or "").strip() == "planner_desktop_operation"
        for request in items
    ):
        return []
    visible = _visible_entrypoint_plan_requests(items)
    if not visible:
        return []
    if any(_request_has_selected_app_placeholder(request) for request in visible):
        return []
    tools = [str(request.get("tool") or "").strip() for request in visible]
    if tools == ["desktop.search_submit"]:
        return [_legacy_shape_request(visible[0])]
    if not _explicit_spotlight_prompt(text):
        return []
    if tools not in (
        ["desktop.safe_shortcut"],
        ["desktop.safe_shortcut", "desktop.safe_type_text"],
    ):
        return []
    first_input = visible[0].get("input") if isinstance(visible[0].get("input"), Mapping) else {}
    if str(first_input.get("action") or "").strip() != "spotlight_search":
        return []
    if len(visible) == 2:
        second_input = visible[1].get("input") if isinstance(visible[1].get("input"), Mapping) else {}
        if not str(second_input.get("text") or "").strip():
            return []
    return [_legacy_shape_request(request) for request in visible]


def _legacy_compatible_simple_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
    *,
    text: str,
) -> list[dict[str, Any]]:
    if not requests:
        return []
    items = [dict(request) for request in requests if isinstance(request, Mapping)]
    if not items:
        return []
    if not any(
        str(request.get("planning_reason") or "").strip()
        in {
            "planner_desktop_operation",
            "planner_fallback_file_access",
            "planner_fallback_web_research",
        }
        for request in items
    ):
        return []
    visible = _visible_entrypoint_plan_requests(items)
    if len(visible) != 1:
        return []
    request = visible[0]
    tool_name = str(request.get("tool") or "").strip()
    if tool_name not in _LEGACY_COMPATIBLE_SIMPLE_PLANNER_TOOLS:
        return []
    if _request_has_selected_app_placeholder(request):
        return []
    if not _legacy_compatible_simple_request(text, request):
        return []
    return [_legacy_shape_request(request)]


_LEGACY_COMPATIBLE_SIMPLE_PLANNER_TOOLS = frozenset(
    {
        "app.focus",
        "app.focus_and_safe_key",
        "app.focus_and_safe_scroll",
        "app.focus_and_safe_shortcut",
        "app.open",
        "app.open_and_safe_key",
        "app.open_and_safe_scroll",
        "app.open_and_safe_shortcut",
        "app.status",
        "browser.open_url",
        "desktop.open_path",
        "desktop.reveal_path",
        "desktop.running_apps",
    }
)


def _legacy_compatible_simple_request(text: str, request: Mapping[str, Any]) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if tool_name in {"desktop.open_path", "desktop.reveal_path", "desktop.running_apps"}:
        return True
    if tool_name == "browser.open_url":
        return _legacy_compatible_browser_open_request(text, request)
    if tool_name in _LEGACY_COMPATIBLE_APP_ACTION_TOOLS:
        return _legacy_compatible_app_action_request(request)
    if tool_name == "app.status":
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        return bool(str(payload.get("app_name") or "").strip())
    if tool_name not in {"app.open", "app.focus"}:
        return False
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name:
        return False
    if _generic_non_app_name(app_name):
        return False
    return not _app_prompt_has_non_launch_followup(text)


_LEGACY_COMPATIBLE_APP_ACTION_TOOLS = frozenset(
    {
        "app.focus_and_safe_key",
        "app.focus_and_safe_scroll",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_key",
        "app.open_and_safe_scroll",
        "app.open_and_safe_shortcut",
    }
)

_LEGACY_COMPATIBLE_APP_ACTIONS = frozenset(
    {
        "copy",
        "escape",
        "find",
        "finder_get_info",
        "focus_address_bar",
        "new_event",
        "new_message",
        "new_note",
        "new_private_window",
        "new_reminder",
        "open_devtools",
        "parent_folder",
        "rename_selected",
        "show_history",
        "tab",
    }
)

_LEGACY_COMPATIBLE_NEW_MESSAGE_APPS = frozenset(
    {"Mail", "Messages", "Microsoft Outlook", "Slack", "WeChat"}
)

_LEGACY_COMPATIBLE_CREATION_ACTION_APPS = {
    "new_event": "Calendar",
    "new_note": "Notes",
    "new_reminder": "Reminders",
}

_LEGACY_COMPATIBLE_FINDER_ACTIONS = frozenset(
    {"copy", "finder_get_info", "parent_folder", "rename_selected"}
)


def _legacy_compatible_app_action_request(request: Mapping[str, Any]) -> bool:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name or _generic_non_app_name(app_name):
        return False
    action = str(
        payload.get("action")
        or payload.get("direction")
        or ""
    ).strip()
    if not action:
        return False
    tool_name = str(request.get("tool") or "").strip()
    if tool_name.endswith("_safe_scroll"):
        return action in {"down", "left", "right", "up"}
    if action not in _LEGACY_COMPATIBLE_APP_ACTIONS:
        return False
    if action in _LEGACY_COMPATIBLE_FINDER_ACTIONS:
        return app_name == "Finder"
    if action == "new_message":
        return app_name in _LEGACY_COMPATIBLE_NEW_MESSAGE_APPS
    expected_creation_app = _LEGACY_COMPATIBLE_CREATION_ACTION_APPS.get(action)
    if expected_creation_app:
        return app_name == expected_creation_app
    return True


def _generic_non_app_name(app_name: str) -> bool:
    compact = re.sub(r"\s+", "", str(app_name or "").strip().lower())
    return compact in {
        "project",
        "repo",
        "repository",
        "workspace",
        "leave",
        "privatewindow",
        "incognitowindow",
        "项目",
        "仓库",
        "工作区",
        "私密窗口",
        "无痕窗口",
        "隐身窗口",
    }


def _legacy_compatible_browser_open_request(text: str, request: Mapping[str, Any]) -> bool:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    url = str(payload.get("url") or "").strip().lower()
    if not url:
        return False
    if re.search(r"(?:搜索|搜|聚焦|spotlight|\bsearch\b|\bfind\b)", str(text or ""), flags=re.IGNORECASE):
        return False
    if "google.com/search" in url or "/search?" in url:
        return False
    return True


def _app_prompt_has_non_launch_followup(text: str) -> bool:
    value = str(text or "")
    lowered = value.lower()
    return bool(
        re.search(
            r"(?:浏览器|新建|无痕|隐身|开发者|历史|地址栏|搜索|取消|全屏|设置|"
            r"并|然后|之后|再|里|中|上|按|点击|点|输入|滚动|刷新|标签页|页面)",
            value,
        )
        or re.search(
            r"\b(?:browser|new|incognito|private|devtools|developer|history|address|"
            r"search|find|cancel|escape|fullscreen|full\s+screen|settings?|and|then|after|"
            r"in|inside|press|click|type|scroll|refresh|tab|page)\b",
            lowered,
        )
    )


def _legacy_compatible_simple_media_request(tools: Sequence[str]) -> bool:
    return len(tools) == 1 and tools[0] in {
        "media.apple_music_play",
        "media.apple_music_status",
        "media.music_app_open_and_play",
    }


def _legacy_compatible_named_music_search_sequence(
    requests: Sequence[Mapping[str, Any]],
    tools: Sequence[str],
    *,
    text: str,
) -> bool:
    if not _explicit_music_search_play_prompt(text):
        return False
    if list(tools) != [
        "app.open_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
    ] and list(tools) != [
        "app.focus_and_safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "media.music_app_open_and_play",
    ]:
        return False
    first_input = requests[0].get("input") if isinstance(requests[0].get("input"), Mapping) else {}
    final_input = requests[-1].get("input") if isinstance(requests[-1].get("input"), Mapping) else {}
    first_app = str(first_input.get("app_name") or "").strip()
    final_app = str(final_input.get("app_name") or "").strip()
    return bool(first_app and final_app and first_app == final_app and first_app != "Music")


def _explicit_music_search_play_prompt(text: str) -> bool:
    value = str(text or "")
    has_search = bool(
        "搜索" in value
        or "搜" in value
        or re.search(r"\b(?:search|find)\b", value, flags=re.IGNORECASE)
    )
    if not has_search:
        return False
    return bool(
        re.search(r"(?:打开|启动|运行|拉起|开启)", value)
        or re.search(r"\b(?:open|launch|start)\b", value, flags=re.IGNORECASE)
    )


def _explicit_spotlight_prompt(text: str) -> bool:
    return bool(
        re.search(
            r"(?:Spotlight|spotlight|聚焦搜索|系统搜索)",
            str(text or ""),
            flags=re.IGNORECASE,
        )
    )


def _legacy_shape_request(request: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "protocol": str(request.get("protocol") or "json_fallback"),
        "tool": str(request.get("tool") or "").strip(),
        "input": dict(request.get("input") if isinstance(request.get("input"), Mapping) else {}),
    }


def _request_has_selected_app_placeholder(request: Mapping[str, Any]) -> bool:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    for value in payload.values():
        text = str(value or "").strip()
        if text.startswith("<selected app from "):
            return True
    return False


def planner_first_daily_desktop_entrypoint_requests(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
    metadata_allowed_tools: Sequence[str] | None = None,
    execution_normalized: bool = False,
    include_runtime_context: bool = False,
    allow_legacy_fallback: bool = False,
) -> list[dict[str, Any]]:
    """Return daily entrypoint requests from Runtime Planner by default."""

    allowed = daily_desktop_allowed_tools(allowed_tools)
    direct_tool_request = daily_desktop_direct_metadata_request(
        metadata,
        allowed_tools=metadata_allowed_tools if metadata_allowed_tools is not None else allowed,
    )
    if direct_tool_request:
        return [direct_tool_request]
    try:
        from .planner_execution import planner_execution_tool_requests, planner_tool_requests

        if execution_normalized and include_runtime_context:
            runtime_requests = _runtime_execution_context_entrypoint_requests(
                str(text or ""),
                allowed,
                metadata=metadata,
            )
            if runtime_requests:
                return [dict(request) for request in runtime_requests]

        planner_requests = planner_tool_requests(
            str(text or ""),
            allowed,
            metadata=metadata,
        )
    except Exception:
        logger.debug("Runtime planner daily desktop candidates unavailable", exc_info=True)
        planner_requests = []
    if planner_requests:
        if execution_normalized:
            normalized = (
                planner_execution_tool_requests(planner_requests, allowed)
                or planner_requests
            )
            return [dict(request) for request in normalized]
        return planner_requests
    if not allow_legacy_fallback:
        return []
    return _legacy_entrypoint_compatibility_requests(
        daily_desktop_entrypoint_requests(
            text,
            metadata=metadata,
            allowed_tools=allowed,
        )
    )


def daily_desktop_runtime_execution_envelope(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
) -> dict[str, Any]:
    """Return the full Runtime execution envelope for daily entrypoints."""

    allowed = daily_desktop_allowed_tools(allowed_tools)
    try:
        from .runtime_execution import runtime_execution_envelope_payload
        from .runtime_planner import RuntimePlanner

        decision = RuntimePlanner().decision(
            str(text or ""),
            allowed_tools=allowed,
            metadata=metadata,
        )
        return runtime_execution_envelope_payload(
            decision,
            allowed_tools=allowed,
            full_plan=True,
            metadata=metadata,
        )
    except Exception:
        logger.debug("Runtime execution envelope unavailable for daily desktop", exc_info=True)
        return {}


def daily_desktop_executable_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    return [dict(request) for request in requests if isinstance(request, Mapping)]


def daily_desktop_direct_metadata_request(
    metadata: Mapping[str, Any] | None,
    *,
    allowed_tools: Sequence[str] | None = None,
) -> dict[str, Any] | None:
    return daily_desktop_metadata_tool_request(
        metadata,
        daily_desktop_allowed_tools(allowed_tools),
    )


def daily_desktop_recovery_execution_prompt(
    prompt: str,
    metadata: Mapping[str, Any] | None = None,
) -> str:
    return daily_desktop_recovery_prompt(metadata) or str(prompt or "").strip()


def daily_desktop_user_metadata(
    requests: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    if not requests:
        return {}
    tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if str(request.get("tool") or "").strip()
    ]
    if not tools:
        return {}
    first_request = requests[0]
    payload: dict[str, Any] = {
        "daily_desktop_intent": True,
        "daily_desktop_source": str(first_request.get("source") or "daily_desktop_intent"),
        "daily_desktop_planning_reason": str(
            first_request.get("planning_reason") or "clear_daily_desktop_intent"
        ),
        "daily_desktop_tool": tools[0],
        "daily_desktop_tools": tools,
    }
    compatibility_boundary = str(first_request.get("compatibility_boundary") or "").strip()
    if compatibility_boundary:
        payload["daily_desktop_compatibility_boundary"] = compatibility_boundary
    if first_request.get("legacy_fallback"):
        payload["daily_desktop_legacy_fallback"] = True
    return payload


def entrypoint_plan_user_metadata(
    requests: Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    """Project planner-first entrypoint metadata while preserving legacy keys."""

    metadata = daily_desktop_user_metadata(_visible_entrypoint_plan_requests(requests))
    if not metadata:
        return {}
    source = str(metadata.get("daily_desktop_source") or "").strip()
    reason = str(metadata.get("daily_desktop_planning_reason") or "").strip()
    tool = str(metadata.get("daily_desktop_tool") or "").strip()
    tools = metadata.get("daily_desktop_tools")
    tool_list = [str(item or "").strip() for item in tools or [] if str(item or "").strip()]
    return {
        **metadata,
        "entrypoint_plan": True,
        "entrypoint_plan_source": source,
        "entrypoint_plan_reason": reason,
        "entrypoint_plan_tool": tool,
        "entrypoint_plan_tools": tool_list,
        "entrypoint_plan_legacy_fallback": source != "runtime_planner",
    }


def _visible_entrypoint_plan_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[Mapping[str, Any]]:
    items = [request for request in requests or [] if isinstance(request, Mapping)]
    if len(items) <= 1:
        return items
    primary_indexes = [
        index
        for index, request in enumerate(items)
        if str(request.get("tool") or "").strip() not in _ENTRYPOINT_NON_PRIMARY_TOOLS
    ]
    if not primary_indexes:
        visible = list(items)
        while (
            len(visible) > 1
            and str(visible[0].get("tool") or "").strip() in _ENTRYPOINT_DISCOVERY_TOOLS
        ):
            visible = visible[1:]
        return visible
    first_primary = primary_indexes[0]
    last_primary = primary_indexes[-1]
    visible = []
    for index, request in enumerate(items):
        tool_name = str(request.get("tool") or "").strip()
        if tool_name in _ENTRYPOINT_DISCOVERY_TOOLS and (
            index < first_primary or index > last_primary
        ):
            continue
        if tool_name in _ENTRYPOINT_NON_PRIMARY_TOOLS and index > last_primary:
            continue
        visible.append(request)
    return visible or items


def _legacy_entrypoint_compatibility_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    compatible: list[dict[str, Any]] = []
    for request in requests or ():
        if not isinstance(request, Mapping):
            continue
        compatible.append(
            {
                **dict(request),
                "legacy_fallback": True,
                "compatibility_boundary": "legacy_daily_desktop_intent",
            }
        )
    return compatible


def daily_desktop_planned_timeline(
    prompt: str = "",
    *,
    requests: Sequence[Mapping[str, Any]] | None = None,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
    include_runtime_context: bool = False,
) -> list[dict[str, Any]]:
    planned_requests = list(requests or ())
    if not planned_requests:
        planned_requests = planner_first_daily_desktop_entrypoint_requests(
            prompt,
            metadata=metadata,
            allowed_tools=allowed_tools,
            execution_normalized=True,
            include_runtime_context=include_runtime_context,
        )
    if not planned_requests:
        return []
    timeline: list[dict[str, Any]] = []
    for request in planned_requests:
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name:
            continue
        tool_input = request.get("input") if isinstance(request.get("input"), dict) else {}
        event = {
            "event": "agent.desktop.intent_planned",
            "detail": tool_name,
            "tool": tool_name,
            "status": "planned",
            "source": str(request.get("source") or "daily_desktop_intent"),
            "planning_reason": str(
                request.get("planning_reason") or "clear_daily_desktop_intent"
            ),
            "input_preview": dict(tool_input),
        }
        if request.get("continue_to_model"):
            event["continue_to_model"] = True
        for key in _ENTRYPOINT_TIMELINE_CONTEXT_KEYS:
            value = request.get(key)
            if _has_entrypoint_timeline_context_value(value):
                event[key] = value
        timeline.append(event)
    return timeline


def _has_entrypoint_timeline_context_value(value: Any) -> bool:
    return value not in (None, "", [], {}) and value is not False


def _runtime_execution_context_entrypoint_requests(
    text: str,
    allowed_tools: Sequence[str],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    try:
        from .runtime_execution import runtime_execution_requests_from_envelope_payload

        envelope = daily_desktop_runtime_execution_envelope(
            text,
            metadata=metadata,
            allowed_tools=allowed_tools,
        )
        return runtime_execution_requests_from_envelope_payload(
            envelope,
            allowed_tools=allowed_tools,
        )
    except Exception:
        logger.debug("Runtime execution context entrypoint unavailable", exc_info=True)
        return []


def _runtime_main_chat_tool_policies(runtime: Any | None) -> list[Mapping[str, Any]]:
    if runtime is None:
        return []
    policies: list[Mapping[str, Any]] = []
    main_chat_tool_policy = getattr(runtime, "_main_chat_tool_policy", None)
    if callable(main_chat_tool_policy):
        try:
            policy = main_chat_tool_policy()
            if isinstance(policy, Mapping):
                policies.append(policy)
        except Exception:
            pass
    main_chat_config = getattr(runtime, "main_chat_config", None)
    config_tool_policy = getattr(main_chat_config, "tool_policy", None)
    if callable(config_tool_policy):
        try:
            policy = config_tool_policy()
            if isinstance(policy, Mapping):
                policies.append(policy)
        except Exception:
            pass
    return policies
