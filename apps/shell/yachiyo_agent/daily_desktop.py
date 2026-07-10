"""Shared daily desktop runtime helpers for Chat, Bubble, and Live2D."""

from __future__ import annotations

import logging
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.desktop_recovery_metadata import (
    daily_desktop_metadata_tool_request,
    daily_desktop_recovery_prompt,
)
from apps.shell.agent.tools.policy import DAILY_DESKTOP_TOOL_NAMES

from .app_name_hints import explicit_known_app_action_target_hint
from .desktop_execution_policy import (
    daily_entrypoint_desktop_execution_policy,
    desktop_execution_policy_payload,
    desktop_provider_session_auto_start_recommended_for_requests,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class DailyDesktopEntrypointRuntimePlan:
    decision: Any | None
    entrypoint_requests: list[dict[str, Any]]
    executable_requests: list[dict[str, Any]]
    runtime_execution_envelope: dict[str, Any]
    selected_source: str
    allowed_tools: tuple[str, ...] = ()

    @property
    def has_plan(self) -> bool:
        requests = self.runtime_execution_envelope.get("requests")
        return bool(
            self.entrypoint_requests
            or (isinstance(requests, list) and requests)
        )


_ENTRYPOINT_DISCOVERY_TOOLS = {
    "desktop.list_apps",
    "desktop.inspect_app",
    "desktop.running_apps",
    "desktop.permissions",
}
_ENTRYPOINT_VERIFY_TOOLS = {
    "desktop.active_window",
    "desktop.verify",
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
    if not request_list:
        return []
    readback_requests = _direct_browser_readback_entrypoint_requests(request_list, text)
    if readback_requests:
        return readback_requests
    if _looks_like_browser_artifact_request(text):
        return []
    for index, request in enumerate(request_list):
        normalized = _direct_browser_entrypoint_request(request)
        if not normalized:
            continue
        if not _direct_browser_entrypoint_suffix_is_deferred_output_only(
            request_list[index + 1:],
        ):
            continue
        return [normalized]
    return []


_DIRECT_BROWSER_DEFERRED_OUTPUT_TOOLS = frozenset(
    {
        "artifact.write",
        "browser.current_page",
        "browser.extract",
        "browser.extract_text",
        "clipboard.write",
        "data.analyze",
    }
)
_DIRECT_BROWSER_READBACK_TOOLS = frozenset(
    {
        "browser.current_page",
        "browser.extract",
        "browser.extract_text",
    }
)


def _direct_browser_entrypoint_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    tool_name = str(request.get("tool") or "").strip()
    if tool_name not in _DIRECT_BROWSER_ENTRYPOINT_TOOLS:
        return {}
    source = str(request.get("source") or "").strip()
    if source and source != "runtime_planner":
        return {}
    planning_reason = str(request.get("planning_reason") or "").strip()
    if planning_reason and "web" not in planning_reason:
        return {}
    if bool(request.get("approval_required")):
        return {}
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    if not str(payload.get("url") or "").strip():
        return {}
    normalized = dict(request)
    normalized.pop("continue_to_model", None)
    return normalized


def _direct_browser_entrypoint_suffix_is_deferred_output_only(
    requests: Sequence[Mapping[str, Any]],
) -> bool:
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        if tool_name in _ENTRYPOINT_VERIFY_TOOLS:
            continue
        if tool_name not in _DIRECT_BROWSER_DEFERRED_OUTPUT_TOOLS:
            return False
        if bool(request.get("approval_required")):
            return False
    return True


def _direct_browser_readback_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]],
    text: str,
) -> list[dict[str, Any]]:
    if _looks_like_browser_persistent_artifact_request(text):
        return []
    if not _looks_like_current_page_summary_request(text):
        return []
    for index, request in enumerate(requests):
        normalized = _direct_browser_readback_entrypoint_request(request)
        if not normalized:
            continue
        if not _direct_browser_entrypoint_suffix_is_deferred_output_only(
            requests[index + 1:],
        ):
            continue
        normalized.setdefault("presentation", "summary")
        return [normalized]
    return []


def _direct_browser_readback_entrypoint_request(
    request: Mapping[str, Any],
) -> dict[str, Any]:
    tool_name = str(request.get("tool") or "").strip()
    if tool_name not in _DIRECT_BROWSER_READBACK_TOOLS:
        return {}
    source = str(request.get("source") or "").strip()
    if source and source != "runtime_planner":
        return {}
    planning_reason = str(request.get("planning_reason") or "").strip()
    if planning_reason and "web" not in planning_reason:
        return {}
    if bool(request.get("approval_required")):
        return {}
    normalized = dict(request)
    normalized.pop("continue_to_model", None)
    return normalized


def _looks_like_current_page_summary_request(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(
        re.search(
            r"(?:当前(?:网页|页面)|current\s+(?:webpage|page)|this\s+(?:webpage|page))",
            value,
            flags=re.IGNORECASE,
        )
        and re.search(
            r"(?:总结|摘要|概括|summari[sz]e|summary|recap)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _looks_like_browser_persistent_artifact_request(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(
        re.search(
            r"(?:报告|文档|文件|产出|输出|导出|保存|表格|调研|研究|分析|生成\s*(?:一份)?\s*"
            r"(?:报告|文档|文件|表格)|\breport\b|\bartifact\b|\bsave\b|\bexport\b|"
            r"\btable\b|\bresearch\b|\banaly[sz]e\b|\bmarkdown\b|\bmd\s+file\b)",
            value,
            flags=re.IGNORECASE,
        )
    )


def daily_desktop_requests_can_complete_without_model(
    requests: Sequence[Mapping[str, Any]] | None,
) -> bool:
    """Return true when deferred planner steps are only deterministic verification."""

    items = [request for request in requests or [] if isinstance(request, Mapping)]
    if not items:
        return False
    deferred = [request for request in items if bool(request.get("continue_to_model"))]
    if not deferred:
        return True
    return all(_deferred_request_is_direct_verification(request) for request in deferred)


def _deferred_request_is_direct_verification(request: Mapping[str, Any]) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if (
        tool_name not in _ENTRYPOINT_VERIFY_TOOLS
        and tool_name not in _ENTRYPOINT_DISCOVERY_TOOLS
        and tool_name != "desktop.verify"
    ):
        return False
    if bool(request.get("approval_required")):
        return False
    runtime_stage = str(request.get("runtime_stage") or "").strip()
    runtime_role = str(request.get("runtime_role") or "").strip()
    step_id = str(request.get("step_id") or "").strip()
    if runtime_stage == "verify" or runtime_role == "verify_result":
        return True
    return step_id.startswith("verify-")


_SAFE_DIRECT_ENTRYPOINT_TOOLS = frozenset(
    {
        "app.focus",
        "app.focus_window",
        "app.hide",
        "app.minimize",
        "app.open",
        "app.open_path_with_app",
        "app.show",
        "desktop.active_window",
        "desktop.verify",
        "desktop.focus_app",
        "desktop.list_apps",
        "desktop.list_windows",
        "desktop.open_app",
        "desktop.open_path_with_app",
        "desktop.read_ui",
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.windows",
        "media.music_app_control",
        "media.music_app_open_and_play",
        "media.system_control",
        "screen.capture",
        "system.settings_open",
    }
)
_BLOCKED_DIRECT_ENTRYPOINT_TOOLS = frozenset(
    {
        "app.focus_and_click_ui_element",
        "app.focus_and_safe_click",
        "app.focus_and_safe_key",
        "app.focus_and_safe_scroll",
        "app.focus_and_safe_shortcut",
        "app.focus_and_safe_type_text",
        "app.focus_and_type_into_ui_element",
        "app.open_and_click_ui_element",
        "app.open_and_safe_click",
        "app.open_and_safe_key",
        "app.open_and_safe_scroll",
        "app.open_and_safe_shortcut",
        "app.open_and_safe_type_text",
        "app.open_and_type_into_ui_element",
        "browser.click",
        "browser.type_text",
        "desktop.safe_click",
        "desktop.safe_key",
        "desktop.safe_scroll",
        "desktop.safe_shortcut",
        "desktop.safe_type_text",
        "desktop.search_submit",
        "desktop.click",
        "desktop.click_ui_element",
        "desktop.type",
        "desktop.type_into_ui_element",
        "desktop.type_text",
    }
)


def daily_desktop_safe_direct_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    executable = daily_desktop_executable_entrypoint_requests(requests or [])
    if not executable:
        return []
    if not daily_desktop_requests_can_complete_without_model(executable):
        return []
    for request in executable:
        if not _daily_desktop_safe_direct_entrypoint_request(request):
            return []
    return executable


def _daily_desktop_safe_direct_entrypoint_request(request: Mapping[str, Any]) -> bool:
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    if not tool_name or tool_name in _BLOCKED_DIRECT_ENTRYPOINT_TOOLS:
        return False
    if tool_name not in _SAFE_DIRECT_ENTRYPOINT_TOOLS:
        return False
    if bool(request.get("approval_required")) or bool(request.get("requires_approval")):
        return False
    risk_level = str(request.get("risk_level") or "").strip().lower()
    return risk_level not in {"high", "critical"}


def daily_desktop_approval_or_submit_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
    *,
    text: str = "",
) -> list[dict[str, Any]]:
    """Return approval-preserving foreground requests for Chat/Bubble entrypoints."""

    return _approval_entrypoint_requests(requests or []) or _submit_foreground_entrypoint_request(text)


_APPROVAL_ENTRYPOINT_PREREQUISITE_TOOLS = frozenset(
    {
        "app.open",
        "app.focus",
        "app.focus_window",
        "desktop.open_app",
        "desktop.focus_app",
    }
)


def _approval_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    for request in requests:
        if not isinstance(request, Mapping):
            continue
        tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
        if not tool_name:
            continue
        if bool(request.get("approval_required")) or bool(request.get("requires_approval")):
            if _system_ui_open_confirm_is_redundant(selected, request):
                return selected
            selected.append(_entrypoint_request_copy(request))
            return selected
        if tool_name in _APPROVAL_ENTRYPOINT_PREREQUISITE_TOOLS:
            selected.append(_entrypoint_request_copy(request))
    return []


def _system_ui_open_confirm_is_redundant(
    selected: list[dict[str, Any]],
    approval_request: Mapping[str, Any],
) -> bool:
    tool_name = str(approval_request.get("tool") or approval_request.get("tool_name") or "").strip()
    payload = approval_request.get("input") if isinstance(approval_request.get("input"), Mapping) else {}
    if tool_name != "desktop.submit_foreground" or str(payload.get("action") or "").strip() != "confirm":
        return False
    if len(selected) != 1:
        return False
    open_request = selected[0]
    open_tool = str(open_request.get("tool") or open_request.get("tool_name") or "").strip()
    if open_tool not in {"app.open", "desktop.open_app"}:
        return False
    open_input = open_request.get("input") if isinstance(open_request.get("input"), Mapping) else {}
    app_name = str(open_input.get("app_name") or "").strip().lower()
    return app_name in {"control center", "notification center", "launchpad"}


def _entrypoint_request_copy(request: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(request)
    tool_name = str(payload.get("tool") or payload.get("tool_name") or "").strip()
    tool_input = payload.get("input")
    if isinstance(tool_input, Mapping) and tool_input.get("app_name"):
        clean_input = dict(tool_input)
        clean_input.pop("query", None)
        clean_input.pop("selection_source", None)
        payload["input"] = clean_input
    if tool_name in _APPROVAL_ENTRYPOINT_PREREQUISITE_TOOLS:
        payload["requires_post_action_verification"] = False
    return payload


def _submit_foreground_entrypoint_request(text: str) -> list[dict[str, Any]]:
    value = str(text or "").strip().lower()
    action = ""
    if re.fullmatch(
        r"(?:send)\s+(?:the\s+)?current\s+(?:message|content|input|text)",
        value,
    ):
        action = "send"
    elif re.fullmatch(
        r"(?:submit)\s+(?:the\s+)?current\s+(?:message|content|input|text|form)",
        value,
    ):
        action = "submit"
    if not action:
        return []
    return [
        {
            "protocol": "json_fallback",
            "tool": "desktop.submit_foreground",
            "input": {"action": action},
            "source": "runtime_planner",
            "planning_reason": "planner_submit_foreground_entrypoint",
            "approval_required": True,
            "risk_level": "high",
        }
    ]


def _looks_like_browser_artifact_request(text: str) -> bool:
    value = str(text or "").strip()
    if not value:
        return False
    return bool(
        re.search(
            r"(?:报告|文档|文件|产出|输出|导出|保存|总结|摘要|表格|调研|研究|分析|阅读|"
            r"读取|读一下|解释|提炼|生成\s*(?:一份)?\s*(?:报告|文档|文件|总结|摘要|表格)|"
            r"\breport\b|\bartifact\b|\bsave\b|\bexport\b|\bsummary\b|\bsummarize\b|"
            r"\bsummarise\b|\btable\b|\bresearch\b|\banaly[sz]e\b|\bread\b|\bextract\b|"
            r"\bdescribe\b|\bexplain\b)",
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
    from apps.shell.agent.runtime.desktop_intents import (
        daily_desktop_entrypoint_tool_requests,
    )

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
        from .planner_execution import planner_decision_and_tool_requests

        decision, planner_requests = planner_decision_and_tool_requests(
            str(text or ""),
            allowed,
            metadata=metadata,
        )
    except Exception:
        logger.debug("Runtime planner legacy-compatible entrypoint unavailable", exc_info=True)
        return []
    context_capture_requests = (
        _legacy_compatible_context_capture_schedule_entrypoint_requests(
            decision,
            planner_requests,
            allowed=allowed,
        )
    )
    if context_capture_requests:
        return context_capture_requests
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
    browser_search_requests = _legacy_compatible_browser_search_entrypoint_requests(
        planner_requests,
        text=text,
    )
    if browser_search_requests:
        return browser_search_requests
    browser_internal_page_requests = (
        _legacy_compatible_browser_internal_page_entrypoint_requests(
            planner_requests,
        )
    )
    if browser_internal_page_requests:
        return browser_internal_page_requests
    foreground_command_requests = (
        _legacy_compatible_foreground_command_entrypoint_requests(
            planner_requests,
        )
    )
    if foreground_command_requests:
        return foreground_command_requests
    search_box_requests = _legacy_compatible_context_transfer_search_box_requests(
        planner_requests,
        text=text,
    )
    if search_box_requests:
        return search_box_requests
    browser_click_requests = _legacy_compatible_browser_click_entrypoint_requests(
        planner_requests,
        text=text,
    )
    if browser_click_requests:
        return browser_click_requests
    semantic_ui_requests = _legacy_compatible_semantic_ui_entrypoint_requests(
        planner_requests,
        text=text,
    )
    if semantic_ui_requests:
        return semantic_ui_requests
    foreground_type_requests = _legacy_compatible_foreground_type_entrypoint_requests(
        planner_requests,
    )
    if foreground_type_requests:
        return foreground_type_requests
    observation_requests = _legacy_compatible_observation_entrypoint_requests(
        planner_requests,
    )
    if observation_requests:
        return observation_requests
    return _legacy_compatible_simple_entrypoint_requests(planner_requests, text=text)


_LEGACY_COMPATIBLE_OBSERVATION_TOOLS = frozenset(
    {
        "desktop.active_window",
        "desktop.list_apps",
        "desktop.permissions",
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.windows",
        "screen.capture",
    }
)


def _legacy_compatible_context_capture_schedule_entrypoint_requests(
    decision: Any,
    requests: Sequence[Mapping[str, Any]] | None,
    *,
    allowed: Sequence[str],
) -> list[dict[str, Any]]:
    intent = getattr(decision, "selected_intent", None)
    intent_kind = str(getattr(intent, "kind", "") or "").strip()
    intent_inputs = getattr(intent, "inputs", None)
    if intent_kind not in {"information_capture", "schedule"} or not isinstance(
        intent_inputs,
        Mapping,
    ):
        return []
    source = str(
        intent_inputs.get("source")
        if intent_kind == "information_capture"
        else intent_inputs.get("context_source")
        or ""
    ).strip()
    user_goal = str(getattr(intent, "user_goal", "") or "")
    if source == "visible_text" and re.search(
        r"(?:屏幕|screen)",
        user_goal,
        flags=re.IGNORECASE,
    ):
        return []
    expected_source_tools = {
        "clipboard": ["clipboard.read"],
        "selection": ["desktop.safe_shortcut", "clipboard.read"],
        "current_page_link": ["browser.current_page"],
        "current_page_content": ["browser.extract_text"],
        "visible_text": ["desktop.ui_elements"],
    }
    source_tools = expected_source_tools.get(source)
    items = [dict(request) for request in requests or [] if isinstance(request, Mapping)]
    if not source_tools or [str(item.get("tool") or "").strip() for item in items] != source_tools:
        return []
    expected_reason = (
        "planner_prefetch_information_capture_context"
        if intent_kind == "information_capture"
        else "planner_prefetch_schedule_context"
    )
    if any(
        str(item.get("planning_reason") or "").strip() != expected_reason
        for item in items
    ):
        return []
    if source == "selection":
        first_input = items[0].get("input") if isinstance(items[0].get("input"), Mapping) else {}
        if str(first_input.get("action") or "").strip() != "copy":
            return []
    if source == "visible_text":
        source_input = items[0].get("input") if isinstance(items[0].get("input"), Mapping) else {}
        if str(source_input.get("role_filter") or "").strip() != "text":
            return []
    destination = _context_capture_schedule_destination(decision, intent_kind, source)
    if not destination:
        return []
    required_tools = {"app.open_and_safe_shortcut", "desktop.safe_shortcut"}
    if not required_tools.issubset(set(allowed)):
        return []
    app_name, action = destination
    source_actions = {
        "clipboard": [],
        "selection": ["copy"],
        "current_page_link": ["copy_current_page_link"],
        "current_page_content": ["select_all", "copy"],
        "visible_text": ["select_all", "copy"],
    }[source]
    projected = [
        {"tool": "desktop.safe_shortcut", "input": {"action": action_name}}
        for action_name in source_actions
    ]
    projected.extend(
        [
            {
                "tool": "app.open_and_safe_shortcut",
                "input": {"app_name": app_name, "action": action},
            },
            {"tool": "desktop.safe_shortcut", "input": {"action": "paste"}},
        ]
    )
    return [_legacy_shape_request(request) for request in projected]


def _context_capture_schedule_destination(
    decision: Any,
    intent_kind: str,
    source: str,
) -> tuple[str, str] | None:
    plan = getattr(decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = list(getattr(tool_plan, "steps", None) or [])
    if not steps:
        return None
    destination_step = steps[-1]
    tool_name = str(getattr(destination_step, "tool_name", "") or "").strip()
    input_preview = getattr(destination_step, "input_preview", None)
    if not isinstance(input_preview, Mapping) or str(
        input_preview.get("body_source") or ""
    ).strip() != source:
        return None
    destinations = {
        "notes.create": ("Notes", "new_note"),
        "reminders.create": ("Reminders", "new_reminder"),
        "calendar.create_event": ("Calendar", "new_event"),
    }
    destination = destinations.get(tool_name)
    if intent_kind == "information_capture":
        return destination if tool_name == "notes.create" else None
    return destination if tool_name in {"reminders.create", "calendar.create_event"} else None


def _legacy_compatible_foreground_type_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    items = [dict(request) for request in requests or [] if isinstance(request, Mapping)]
    if not items:
        return []
    if any(
        str(request.get("planning_reason") or "").strip()
        != "planner_desktop_operation"
        for request in items
    ):
        return []
    tools = [str(request.get("tool") or "").strip() for request in items]
    if tools.count("desktop.safe_type_text") != 1 or any(
        tool
        not in {
            "desktop.running_apps",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        }
        for tool in tools
    ):
        return []
    selected = next(
        request
        for request in items
        if str(request.get("tool") or "").strip() == "desktop.safe_type_text"
    )
    payload = selected.get("input") if isinstance(selected.get("input"), Mapping) else {}
    if not str(payload.get("text") or "").strip():
        return []
    return [_legacy_shape_request(selected)]


def _legacy_compatible_observation_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    items = [dict(request) for request in requests or [] if isinstance(request, Mapping)]
    if not items:
        return []
    if any(
        str(request.get("planning_reason") or "").strip()
        != "planner_desktop_operation"
        for request in items
    ):
        return []
    tools = [str(request.get("tool") or "").strip() for request in items]
    if any(tool not in _LEGACY_COMPATIBLE_OBSERVATION_TOOLS for tool in tools):
        return []
    selected = _legacy_shape_request(items[-1])
    if str(selected.get("tool") or "").strip() == "desktop.ui_elements":
        payload = selected.get("input") if isinstance(selected.get("input"), Mapping) else {}
        selected["input"] = {"role_filter": "", **dict(payload)}
    return [selected]


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


def _legacy_compatible_browser_internal_page_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    items = [dict(request) for request in requests or [] if isinstance(request, Mapping)]
    if not items or any(
        str(request.get("planning_reason") or "").strip()
        != "planner_desktop_operation"
        for request in items
    ):
        return []
    visible = _visible_entrypoint_plan_requests(items)
    tools = [str(request.get("tool") or "").strip() for request in visible]
    if tools not in (
        [
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ],
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.search_submit",
        ],
    ):
        return []
    first_input = visible[0].get("input") if isinstance(visible[0].get("input"), Mapping) else {}
    type_input = visible[1].get("input") if isinstance(visible[1].get("input"), Mapping) else {}
    app_name = str(first_input.get("app_name") or "").strip()
    internal_url = str(type_input.get("text") or "").strip()
    allowed_internal_urls = {
        "Google Chrome": r"chrome://(?:bookmarks|downloads|extensions)/",
        "Microsoft Edge": r"edge://(?:downloads|extensions|favorites)/",
        "Brave Browser": r"brave://(?:bookmarks|downloads|extensions)/",
        "Firefox": r"about:(?:addons|downloads)",
    }
    allowed_url = allowed_internal_urls.get(app_name, "")
    if (
        str(first_input.get("action") or "").strip() != "focus_address_bar"
        or not allowed_url
        or not re.fullmatch(allowed_url, internal_url, flags=re.IGNORECASE)
    ):
        return []
    legacy_requests = [_legacy_shape_request(request) for request in visible]
    if internal_url.lower() == "edge://favorites/":
        legacy_requests[1]["input"] = {"text": "edge://bookmarks/"}
    return legacy_requests


def _legacy_compatible_foreground_command_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
) -> list[dict[str, Any]]:
    items = [dict(request) for request in requests or [] if isinstance(request, Mapping)]
    if not items or any(
        str(request.get("planning_reason") or "").strip()
        != "planner_desktop_operation"
        for request in items
    ):
        return []
    visible = _visible_entrypoint_plan_requests(items)
    if _legacy_compatible_command_palette_sequence(visible):
        return [_legacy_shape_request(request) for request in visible]
    if _legacy_compatible_app_management_sequence(visible):
        return [_legacy_shape_request(request) for request in visible]
    return []


def _legacy_compatible_command_palette_sequence(
    requests: Sequence[Mapping[str, Any]],
) -> bool:
    tools = [str(request.get("tool") or "").strip() for request in requests]
    if tools not in (
        ["app.open_and_safe_shortcut", "desktop.safe_type_text"],
        ["app.focus_and_safe_shortcut", "desktop.safe_type_text"],
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
        ],
        [
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.submit_foreground",
        ],
        [
            "app.open_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.submit_foreground",
        ],
        [
            "app.focus_and_safe_shortcut",
            "desktop.safe_type_text",
            "desktop.safe_key",
            "desktop.submit_foreground",
        ],
    ):
        return False
    first_input = requests[0].get("input")
    type_input = requests[1].get("input")
    if not isinstance(first_input, Mapping) or not isinstance(type_input, Mapping):
        return False
    if (
        str(first_input.get("action") or "").strip()
        not in {"command_palette", "obsidian_command_palette"}
        or not str(first_input.get("app_name") or "").strip()
        or not str(type_input.get("text") or "").strip()
    ):
        return False
    for request in requests[2:]:
        tool_name = str(request.get("tool") or "").strip()
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        if tool_name == "desktop.safe_key":
            if str(payload.get("action") or "").strip() not in {
                "arrow_down",
                "arrow_left",
                "arrow_right",
                "arrow_up",
            }:
                return False
            repeat_count = payload.get("repeat_count", 1)
            if not isinstance(repeat_count, int) or not 1 <= repeat_count <= 10:
                return False
        elif (
            tool_name != "desktop.submit_foreground"
            or str(payload.get("action") or "").strip() != "confirm"
        ):
            return False
    return True


def _legacy_compatible_app_management_sequence(
    requests: Sequence[Mapping[str, Any]],
) -> bool:
    if len(requests) != 2:
        return False
    first, second = requests
    first_tool = str(first.get("tool") or "").strip()
    second_tool = str(second.get("tool") or "").strip()
    first_input = first.get("input") if isinstance(first.get("input"), Mapping) else {}
    second_input = second.get("input") if isinstance(second.get("input"), Mapping) else {}
    app_name = str(first_input.get("app_name") or "").strip()
    if first_tool not in {"app.focus", "app.open"} or not app_name:
        return False
    if second_tool in {"app.hide", "app.minimize", "app.quit"}:
        return str(second_input.get("app_name") or "").strip() == app_name
    return second_tool == "desktop.close_window" and not second_input


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


def _legacy_compatible_browser_search_entrypoint_requests(
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
        str(request.get("planning_reason") or "").strip() == "planner_fallback_web_research"
        for request in items
    ):
        return []
    visible = _visible_entrypoint_plan_requests(items)
    if not visible or any(request.get("continue_to_model") for request in visible):
        return []
    if any(_request_has_selected_app_placeholder(request) for request in visible):
        return []
    tools = [str(request.get("tool") or "").strip() for request in visible]
    if tools == ["browser.open_url"]:
        request = visible[0]
        return [_legacy_shape_request(request)] if _browser_search_open_url_request(request) else []
    if len(visible) != 2 or tools[1] != "browser.open_url":
        return []
    if tools[0] not in {
        "app.focus",
        "app.open",
        "app.focus_and_safe_shortcut",
        "app.open_and_safe_shortcut",
    }:
        return []
    first_input = visible[0].get("input") if isinstance(visible[0].get("input"), Mapping) else {}
    if not _browser_app_name(str(first_input.get("app_name") or "")):
        return []
    action = str(first_input.get("action") or "").strip()
    if action and action != "new_tab":
        return []
    if not _browser_search_open_url_request(visible[1]):
        return []
    return [_legacy_shape_request(request) for request in visible]


def _legacy_compatible_context_transfer_search_box_requests(
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
    if not visible or any(request.get("continue_to_model") for request in visible):
        return []
    if any(_request_has_selected_app_placeholder(request) for request in visible):
        return []
    if not _looks_like_search_box_transfer_prompt(text):
        return []
    compatible: list[dict[str, Any]] = []
    index = 0
    found_click = False
    while index < len(visible):
        request = visible[index]
        tool_name = str(request.get("tool") or "").strip()
        if tool_name == "desktop.safe_shortcut":
            payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
            if str(payload.get("action") or "").strip() not in _CONTEXT_TRANSFER_SAFE_SHORTCUTS:
                return []
            compatible.append(_legacy_shape_request(request))
            index += 1
            continue
        if tool_name in {"app.focus", "app.open"}:
            if index + 1 >= len(visible):
                return []
            next_request = visible[index + 1]
            click_payload = _search_box_click_payload(next_request)
            if not click_payload:
                return []
            payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
            app_name = str(payload.get("app_name") or "").strip()
            if not app_name or _generic_non_app_name(app_name):
                return []
            combined_tool = (
                "app.open_and_click_ui_element"
                if tool_name == "app.open"
                else "app.focus_and_click_ui_element"
            )
            compatible.append(
                {
                    "protocol": str(next_request.get("protocol") or "json_fallback"),
                    "tool": combined_tool,
                    "input": {"app_name": app_name, **click_payload},
                }
            )
            found_click = True
            index += 2
            continue
        click_payload = _search_box_click_payload(request)
        if click_payload:
            compatible.append(_legacy_shape_request(request))
            found_click = True
            index += 1
            continue
        return []
    return compatible if found_click else []


def _legacy_compatible_browser_click_entrypoint_requests(
    requests: Sequence[Mapping[str, Any]] | None,
    *,
    text: str,
) -> list[dict[str, Any]]:
    if not requests:
        return []
    visible = _visible_entrypoint_plan_requests(
        [dict(request) for request in requests if isinstance(request, Mapping)]
    )
    if len(visible) != 1:
        return []
    request = visible[0]
    tool_name = str(request.get("tool") or "").strip()
    if tool_name not in {
        "app.focus_and_click_ui_element",
        "app.open_and_click_ui_element",
    }:
        return []
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    app_name = str(payload.get("app_name") or "").strip()
    target = str(payload.get("target") or "").strip()
    if not app_name or not target or not _browser_app_name(app_name):
        return []
    if not re.search(
        r"(?:点|点击|点按|单击|click|press|tap)",
        str(text or ""),
        flags=re.IGNORECASE,
    ):
        return []
    focus_tool = "app.open" if tool_name == "app.open_and_click_ui_element" else "app.focus"
    return [
        {
            "protocol": str(request.get("protocol") or "json_fallback"),
            "tool": focus_tool,
            "input": {"app_name": app_name},
        },
        {
            "protocol": str(request.get("protocol") or "json_fallback"),
            "tool": "browser.click",
            "input": {
                "selector": f"text={target}",
                "click_count": int(payload.get("click_count") or 1),
            },
        },
    ]


def _legacy_compatible_semantic_ui_entrypoint_requests(
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
    if not visible or any(request.get("continue_to_model") for request in visible):
        return []
    if any(_request_has_selected_app_placeholder(request) for request in visible):
        return []
    semantic = [
        request
        for request in visible
        if _semantic_ui_entrypoint_tool(str(request.get("tool") or ""))
    ]
    if len(semantic) != 1:
        return []
    if not _looks_like_semantic_ui_prompt(text):
        return []
    request = semantic[0]
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    if not _semantic_ui_payload(payload):
        return []
    non_semantic = [
        request
        for request in visible
        if request not in semantic
    ]
    if non_semantic and any(
        str(request.get("tool") or "").strip() != "desktop.submit_foreground"
        for request in non_semantic
    ):
        return []
    return [
        _legacy_shape_request(request)
        for request in _legacy_semantic_ui_shape_requests(
            request,
            non_semantic,
            text=text,
        )
    ]


def _legacy_semantic_ui_shape_requests(
    semantic_request: Mapping[str, Any],
    suffix_requests: Sequence[Mapping[str, Any]],
    *,
    text: str,
) -> list[Mapping[str, Any]]:
    tool_name = str(semantic_request.get("tool") or "").strip()
    if (
        tool_name
        in {
            "app.focus_and_type_into_ui_element",
            "app.open_and_type_into_ui_element",
        }
        and _looks_like_click_then_type_prompt(text)
    ):
        payload = (
            semantic_request.get("input")
            if isinstance(semantic_request.get("input"), Mapping)
            else {}
        )
        typed_text = str(payload.get("text") or "").strip()
        app_name = str(payload.get("app_name") or "").strip()
        target = _legacy_semantic_click_target(payload)
        if typed_text and app_name and target:
            click_tool = (
                "app.open_and_click_ui_element"
                if tool_name == "app.open_and_type_into_ui_element"
                else "app.focus_and_click_ui_element"
            )
            click_payload = {
                "app_name": app_name,
                "target": target,
                "role_filter": str(payload.get("role_filter") or "").strip(),
                "limit": payload.get("limit") or 80,
                "click_count": int(payload.get("click_count") or 1),
            }
            return [
                {
                    **dict(semantic_request),
                    "tool": click_tool,
                    "input": click_payload,
                },
                {
                    **dict(semantic_request),
                    "tool": "desktop.safe_type_text",
                    "input": {"text": typed_text},
                },
                *suffix_requests,
            ]
    return [_legacy_normalized_semantic_ui_request(semantic_request), *suffix_requests]


def _legacy_normalized_semantic_ui_request(
    request: Mapping[str, Any],
) -> Mapping[str, Any]:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    target = _legacy_semantic_click_target(payload)
    if not target or target == str(payload.get("target") or "").strip():
        return request
    return {
        **dict(request),
        "input": {
            **dict(payload),
            "target": target,
        },
    }


def _legacy_semantic_click_target(payload: Mapping[str, Any]) -> str:
    target = str(payload.get("target") or "").strip()
    replacements = {
        "消息框": "消息",
        "聊天框": "消息",
        "搜索框": "搜索",
        "搜索栏": "搜索",
        "地址栏": "地址",
    }
    target = replacements.get(target, target)
    return re.sub(
        r"\s*(?:按钮|button)$",
        "",
        target,
        flags=re.IGNORECASE,
    ).strip(" .，,。")


def _looks_like_click_then_type_prompt(text: str) -> bool:
    value = str(text or "")
    return bool(
        re.search(
            r"(?:点击|点一下|点按|单击|点).{0,40}(?:输入|填写|填入|键入|写入|写)",
            value,
            flags=re.IGNORECASE,
        )
        or re.search(
            r"\b(?:click|press|tap).{0,80}\b(?:type|enter|fill|write)\b",
            value,
            flags=re.IGNORECASE,
        )
    )


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
    return [_legacy_finder_action_shape(text, _legacy_shape_request(request))]


def _legacy_finder_action_shape(text: str, request: dict[str, Any]) -> dict[str, Any]:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    if str(payload.get("app_name") or "").strip() != "Finder":
        return request
    if (
        str(payload.get("action") or "").strip()
        not in _LEGACY_FINDER_FOCUS_SHAPE_ACTIONS
    ):
        return request
    if str(request.get("tool") or "").strip() != "app.open_and_safe_shortcut":
        return request
    if _explicit_open_finder_action_prompt(text):
        return request
    return {**request, "tool": "app.focus_and_safe_shortcut"}


def _explicit_open_finder_action_prompt(text: str) -> bool:
    value = str(text or "").strip()
    return bool(
        re.match(r"^(?:打开|启动|开启)\s*Finder\b", value, flags=re.IGNORECASE)
        or re.match(r"^(?:open|launch|start)\s+finder\b", value, flags=re.IGNORECASE)
    )


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
        "app.hide",
        "app.minimize",
        "app.quit",
        "app.show",
        "app.status",
        "browser.open_url",
        "desktop.safe_shortcut",
        "desktop.open_path",
        "desktop.reveal_path",
        "desktop.running_apps",
        "desktop.close_window",
        "desktop.hide_app",
        "desktop.minimize_window",
        "desktop.quit_app",
        "desktop.show_all_apps",
    }
)


def _legacy_compatible_simple_request(text: str, request: Mapping[str, Any]) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if tool_name in _LEGACY_COMPATIBLE_FOREGROUND_COMMAND_TOOLS:
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        return not payload
    if tool_name in {"desktop.open_path", "desktop.reveal_path", "desktop.running_apps"}:
        return True
    if tool_name == "desktop.safe_shortcut":
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        return str(payload.get("action") or "").strip() in _LEGACY_COMPATIBLE_SAFE_SHORTCUTS
    if tool_name == "browser.open_url":
        return _legacy_compatible_browser_open_request(text, request)
    if tool_name in _LEGACY_COMPATIBLE_APP_ACTION_TOOLS:
        return _legacy_compatible_app_action_request(request)
    if tool_name == "app.status":
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        return bool(str(payload.get("app_name") or "").strip())
    if tool_name not in {
        "app.focus",
        "app.hide",
        "app.minimize",
        "app.open",
        "app.quit",
        "app.show",
    }:
        return False
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    app_name = str(payload.get("app_name") or "").strip()
    if not app_name:
        return False
    if _generic_non_app_name(app_name):
        return False
    if tool_name in {"app.hide", "app.minimize", "app.quit"}:
        return True
    if explicit_known_app_action_target_hint(text) == app_name:
        return True
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
        "command_palette",
        "copy",
        "escape",
        "find",
        "finder_airdrop",
        "finder_get_info",
        "finder_network",
        "finder_quick_look",
        "finder_recents",
        "focus_address_bar",
        "new_folder",
        "new_event",
        "new_message",
        "new_note",
        "new_private_window",
        "new_reminder",
        "open_devtools",
        "obsidian_command_palette",
        "parent_folder",
        "preferences",
        "rename_selected",
        "show_history",
        "tab",
        "toggle_full_screen",
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
    {
        "copy",
        "finder_airdrop",
        "finder_get_info",
        "finder_network",
        "finder_quick_look",
        "finder_recents",
        "new_folder",
        "parent_folder",
        "rename_selected",
    }
)

_LEGACY_FINDER_FOCUS_SHAPE_ACTIONS = frozenset(
    {"copy", "finder_get_info", "parent_folder", "rename_selected"}
)

_CONTEXT_TRANSFER_SAFE_SHORTCUTS = frozenset(
    {"copy", "copy_current_page_link", "paste", "select_all"}
)

_LEGACY_COMPATIBLE_FOREGROUND_COMMAND_TOOLS = frozenset(
    {
        "desktop.close_window",
        "desktop.hide_app",
        "desktop.minimize_window",
        "desktop.quit_app",
        "desktop.show_all_apps",
    }
)

_LEGACY_COMPATIBLE_SAFE_SHORTCUTS = frozenset(
    {
        *_CONTEXT_TRANSFER_SAFE_SHORTCUTS,
        "application_windows",
        "bookmark_page",
        "browser_back",
        "browser_forward",
        "close_tab",
        "focus_address_bar",
        "force_quit_dialog",
        "hide_other_apps",
        "emoji_picker",
        "find",
        "lock_screen",
        "mission_control",
        "new_private_window",
        "new_tab",
        "new_window",
        "next_tab",
        "next_window",
        "open_devtools",
        "previous_tab",
        "previous_window",
        "redo",
        "refresh",
        "reopen_closed_tab",
        "reset_zoom",
        "show_history",
        "spotlight_search",
        "switch_next_app",
        "switch_previous_app",
        "toggle_full_screen",
        "undo",
        "zoom_in",
        "zoom_out",
    }
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


def _looks_like_search_box_transfer_prompt(text: str) -> bool:
    value = str(text or "")
    return bool(
        re.search(r"(?:搜索框|搜索栏|查找框|search\s+(?:box|field|input))", value, flags=re.IGNORECASE)
        and re.search(
            r"(?:输入|填入|粘贴|贴到|填到|type|enter|paste)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _search_box_click_payload(request: Mapping[str, Any]) -> dict[str, Any]:
    if str(request.get("tool") or "").strip() != "desktop.click_ui_element":
        return {}
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    target = str(payload.get("target") or "").strip()
    role_filter = str(payload.get("role_filter") or "").strip()
    if not target or not role_filter:
        return {}
    if not re.search(r"(?:搜索|查找|search|find)", target, flags=re.IGNORECASE):
        return {}
    if role_filter not in {"text", "textbox", "search"}:
        return {}
    return dict(payload)


def _semantic_ui_entrypoint_tool(tool_name: str) -> bool:
    clean = str(tool_name or "").strip()
    return clean in {
        "app.focus_and_click_ui_element",
        "app.open_and_click_ui_element",
        "app.focus_and_type_into_ui_element",
        "app.open_and_type_into_ui_element",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
    }


def _looks_like_semantic_ui_prompt(text: str) -> bool:
    value = str(text or "")
    return bool(
        re.search(
            r"(?:点击|点一下|点按|单击|点|按钮|输入|填写|键入|click|press|tap|type|enter|fill)",
            value,
            flags=re.IGNORECASE,
        )
    )


def _semantic_ui_payload(payload: Mapping[str, Any]) -> bool:
    target = str(payload.get("target") or "").strip()
    if not target:
        return False
    role_filter = str(payload.get("role_filter") or "").strip()
    if role_filter and role_filter not in {"button", "text", "textbox", "search"}:
        return False
    text = payload.get("text")
    if text is not None and not str(text).strip():
        return False
    app_name = str(payload.get("app_name") or "").strip()
    return not app_name or not _generic_non_app_name(app_name)


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


def _browser_search_open_url_request(request: Mapping[str, Any]) -> bool:
    payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
    url = str(payload.get("url") or "").strip().lower()
    return bool(url and ("google.com/search" in url or "/search?" in url))


def _browser_app_name(app_name: str) -> bool:
    compact = re.sub(r"\s+", " ", str(app_name or "").strip().lower())
    return compact in {
        "chrome",
        "google chrome",
        "safari",
        "firefox",
        "edge",
        "microsoft edge",
        "brave",
    }


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
            if runtime_requests and _entrypoint_requests_have_primary_action(
                runtime_requests,
            ):
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


def daily_desktop_entrypoint_runtime_plan(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
    metadata_allowed_tools: Sequence[str] | None = None,
    allow_legacy_fallback: bool = False,
) -> DailyDesktopEntrypointRuntimePlan:
    """Plan once, then derive entrypoint and Runtime execution projections."""

    allowed = daily_desktop_allowed_tools(allowed_tools)
    direct_request = daily_desktop_metadata_tool_request(
        metadata,
        daily_desktop_allowed_tools(
            metadata_allowed_tools
            if metadata_allowed_tools is not None
            else allowed
        ),
    )
    if direct_request:
        requests = [direct_request]
        return DailyDesktopEntrypointRuntimePlan(
            decision=None,
            entrypoint_requests=requests,
            executable_requests=requests,
            runtime_execution_envelope={},
            selected_source="metadata",
            allowed_tools=tuple(allowed),
        )

    decision = None
    planner_requests: list[dict[str, Any]] = []
    runtime_execution_envelope: dict[str, Any] = {}
    executable_requests: list[dict[str, Any]] = []
    blocked_requests: list[dict[str, Any]] = []
    try:
        from .planner_execution import (
            planner_decision_and_tool_requests,
            planner_execution_tool_requests,
        )
        from .runtime_execution import (
            runtime_execution_blocked_requests_from_envelope_payload,
            runtime_execution_requests_from_envelope_payload,
        )

        decision, planner_requests = planner_decision_and_tool_requests(
            str(text or ""),
            allowed,
            metadata=metadata,
        )
        runtime_execution_envelope = daily_desktop_runtime_execution_envelope(
            text,
            metadata=metadata,
            allowed_tools=allowed,
            decision=decision,
        )
        executable_requests = runtime_execution_requests_from_envelope_payload(
            runtime_execution_envelope,
            allowed_tools=allowed,
        )
        blocked_requests = runtime_execution_blocked_requests_from_envelope_payload(
            runtime_execution_envelope,
            allowed_tools=allowed,
        )
        if executable_requests or blocked_requests:
            return DailyDesktopEntrypointRuntimePlan(
                decision=decision,
                entrypoint_requests=executable_requests or blocked_requests,
                executable_requests=executable_requests,
                runtime_execution_envelope=runtime_execution_envelope,
                selected_source="runtime_execution_envelope",
                allowed_tools=tuple(allowed),
            )
        if planner_requests:
            normalized = planner_execution_tool_requests(planner_requests, allowed)
            executable_requests = [
                dict(request) for request in (normalized or planner_requests)
            ]
    except Exception:
        logger.debug("Runtime planner entrypoint plan unavailable", exc_info=True)

    if executable_requests:
        return DailyDesktopEntrypointRuntimePlan(
            decision=decision,
            entrypoint_requests=executable_requests,
            executable_requests=executable_requests,
            runtime_execution_envelope=runtime_execution_envelope,
            selected_source="runtime_planner",
            allowed_tools=tuple(allowed),
        )
    legacy_requests = (
        _legacy_entrypoint_compatibility_requests(
            daily_desktop_entrypoint_requests(
                text,
                metadata=metadata,
                allowed_tools=allowed,
            )
        )
        if allow_legacy_fallback
        else []
    )
    return DailyDesktopEntrypointRuntimePlan(
        decision=decision,
        entrypoint_requests=legacy_requests,
        executable_requests=legacy_requests,
        runtime_execution_envelope={},
        selected_source="daily_desktop_intent" if legacy_requests else "none",
        allowed_tools=tuple(allowed),
    )


def daily_desktop_runtime_plan_prepared_for_execution(
    plan: DailyDesktopEntrypointRuntimePlan,
    *,
    metadata: Mapping[str, Any] | None = None,
) -> DailyDesktopEntrypointRuntimePlan:
    """Start an approved low-risk provider session without replanning the task."""

    if (
        plan.decision is None
        or not plan.runtime_execution_envelope
        or not desktop_provider_session_auto_start_recommended_for_requests(
            plan.runtime_execution_envelope
        )
    ):
        return plan
    refreshed_envelope = daily_desktop_runtime_execution_envelope(
        "",
        metadata=metadata,
        allowed_tools=plan.allowed_tools,
        decision=plan.decision,
        ensure_provider=True,
    )
    if not refreshed_envelope:
        return plan
    try:
        from .runtime_execution import (
            runtime_execution_blocked_requests_from_envelope_payload,
            runtime_execution_requests_from_envelope_payload,
        )

        executable_requests = runtime_execution_requests_from_envelope_payload(
            refreshed_envelope,
            allowed_tools=plan.allowed_tools,
        )
        blocked_requests = runtime_execution_blocked_requests_from_envelope_payload(
            refreshed_envelope,
            allowed_tools=plan.allowed_tools,
        )
    except Exception:
        logger.debug("Prepared Runtime envelope projection unavailable", exc_info=True)
        return plan
    return DailyDesktopEntrypointRuntimePlan(
        decision=plan.decision,
        entrypoint_requests=(
            executable_requests
            or blocked_requests
            or plan.entrypoint_requests
        ),
        executable_requests=executable_requests,
        runtime_execution_envelope=refreshed_envelope,
        selected_source="runtime_execution_envelope",
        allowed_tools=plan.allowed_tools,
    )


def daily_desktop_runtime_execution_envelope(
    text: str,
    *,
    metadata: Mapping[str, Any] | None = None,
    allowed_tools: Sequence[str] | None = None,
    decision: Any | None = None,
    ensure_provider: bool = False,
) -> dict[str, Any]:
    """Return the full Runtime execution envelope for daily entrypoints."""

    allowed = daily_desktop_allowed_tools(allowed_tools)
    try:
        from .runtime_execution import runtime_execution_envelope_payload
        from .runtime_planner import RuntimePlanner

        selected_decision = (
            decision
            if decision is not None
            else RuntimePlanner().decision(
                str(text or ""), allowed_tools=allowed, metadata=metadata
            )
        )
        envelope = runtime_execution_envelope_payload(
            selected_decision,
            allowed_tools=allowed,
            full_plan=True,
            metadata=metadata,
        )
        if not envelope or not ensure_provider:
            return envelope
        from .isolated_provider_session import (
            annotate_envelope_with_desktop_provider_session,
            ensure_isolated_desktop_provider_session_for_envelope,
        )

        session = ensure_isolated_desktop_provider_session_for_envelope(envelope)
        if session.get("needed") and session.get("running"):
            refreshed = runtime_execution_envelope_payload(
                selected_decision,
                allowed_tools=allowed,
                full_plan=True,
                metadata=metadata,
            )
            if refreshed:
                envelope = refreshed
        return annotate_envelope_with_desktop_provider_session(envelope, session)
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
    request = daily_desktop_metadata_tool_request(
        metadata,
        daily_desktop_allowed_tools(allowed_tools),
    )
    if request is None:
        return None
    return _daily_desktop_request_with_execution_policy(request, metadata)


def _daily_desktop_request_with_execution_policy(
    request: Mapping[str, Any],
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    payload = dict(request)
    if desktop_execution_policy_payload(payload.get("desktop_execution_policy")):
        return payload
    metadata_policy = (
        desktop_execution_policy_payload(metadata.get("desktop_execution_policy"))
        if isinstance(metadata, Mapping)
        else {}
    )
    if not metadata_policy and isinstance(metadata, Mapping):
        metadata_policy = desktop_execution_policy_payload(
            metadata.get("yachiyo_desktop_execution_policy")
        )
    payload["desktop_execution_policy"] = metadata_policy or (
        daily_entrypoint_desktop_execution_policy(
            surface=_daily_desktop_surface_from_metadata(metadata),
        )
    )
    return payload


def _daily_desktop_surface_from_metadata(metadata: Mapping[str, Any] | None) -> str:
    if not isinstance(metadata, Mapping):
        return "chat"
    launcher_mode = str(metadata.get("launcher_mode") or "").strip()
    if launcher_mode in {"bubble", "live2d"}:
        return launcher_mode
    source = str(
        metadata.get("entrypoint_source")
        or metadata.get("source")
        or metadata.get("surface")
        or ""
    ).strip()
    if source in {"bubble", "live2d"}:
        return source
    return "chat"


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


def _entrypoint_requests_have_primary_action(
    requests: Sequence[Mapping[str, Any]] | None,
) -> bool:
    for request in requests or ():
        if not isinstance(request, Mapping):
            continue
        tool_name = str(request.get("tool") or "").strip()
        if tool_name and tool_name not in _ENTRYPOINT_NON_PRIMARY_TOOLS:
            return True
    return False


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
