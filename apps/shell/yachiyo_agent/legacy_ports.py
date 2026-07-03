"""Ports backed by the existing Agent runtime surface."""

from __future__ import annotations

import re

from typing import Any

from apps.shell.chat_api import ChatAPI
from apps.shell.agent.runtime.approval_tool_sets import (
    APPROVAL_PLAN_TOOLS as _APPROVAL_PLAN_TOOLS,
    SAFE_SHORTCUT_APPROVAL_TOOLS as _SAFE_SHORTCUT_APPROVAL_TOOLS,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError

from .daily_desktop import (
    daily_desktop_allowed_tools,
    daily_desktop_direct_metadata_request,
    daily_desktop_entrypoint_requests,
    daily_desktop_planned_timeline,
    daily_desktop_recovery_execution_prompt,
    entrypoint_plan_user_metadata,
    main_chat_entrypoint_allowed_tools,
    planner_first_daily_desktop_entrypoint_requests,
)
from .app_name_hints import is_legacy_app_name_hint
from .desktop_permissions import (
    desktop_permission_missing_by_capability,
    desktop_runtime_blocking_conditions_by_capability,
)
from .desktop_plan_hints import hotkey_hint
from .desk import LocalAgentDeskStore
from .entrypoint_tool_selection import planner_first_direct_tool_selection
from .legacy_event_pages import (
    is_replay_enrichment_event as _is_replay_enrichment_event,
    run_event_page_from_legacy_stream as _run_event_page_from_legacy_stream,
    run_with_replay_events as _run_with_replay_events,
)
from .legacy_groups import (
    chat_group_snapshot,
    chat_group_snapshots,
    group_definition_from_run_group,
    save_chat_group_snapshot,
)
from .legacy_group_runs import start_legacy_group_run
from .legacy_runs import LegacyRunPayloadProjector
from .legacy_tasks import (
    LegacyRuntimePort,
    MAIN_CHAT_AGENT_ID,
    _approval_id_from_decision,
    _assert_matching_pending_approval,
    _planner_metadata_with_desktop_readiness,
)
from .planner_projection import (
    planner_run_event_payloads,
    runtime_planner_decision,
    runtime_planner_metadata,
)
from .planner_execution import (
    planner_direct_tool_requests,
    planner_execution_tool_requests,
    planner_tool_requests,
)
from .recovery_actions import (
    RECOVERY_RETRY_CONTEXT_EVENT_TYPE,
    recovery_retry_context_payload,
)
from .runtime_execution import runtime_execution_requests_from_metadata
from .groups import group_run_snapshot_from_payload
from .tool_catalog import runtime_tool_catalog_snapshot

_LEGACY_RUN_PROJECTOR = LegacyRunPayloadProjector()
_DAILY_DESKTOP_METADATA_DISCOVERY_TOOLS = {
    "desktop.list_apps",
    "desktop.inspect_app",
    "desktop.running_apps",
    "desktop.windows",
    "desktop.permissions",
}
_DAILY_DESKTOP_METADATA_VERIFY_TOOLS = {
    "desktop.active_window",
    "desktop.windows",
    "desktop.ui_elements",
    "desktop.inspect_app",
    "screen.capture",
}


def _rejection_reason(decision: dict[str, Any] | str | None) -> str:
    if isinstance(decision, dict):
        return str(decision.get("reason") or "").strip()
    return str(decision or "").strip()


def _entrypoint_planning_context(prompt: str, metadata: dict[str, Any] | None) -> str:
    if isinstance(metadata, dict):
        planning_context = str(metadata.get("entrypoint_planning_context") or "").strip()
        if planning_context:
            return planning_context
    return str(prompt or "").strip()


def _prefer_execution_requests_for_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    source = str(metadata.get("source") or "").strip()
    launcher_mode = str(metadata.get("launcher_mode") or "").strip()
    launcher_surface = str(metadata.get("launcher_surface") or "").strip()
    return source == "launcher" or bool(launcher_mode) or bool(launcher_surface)


def _prefer_legacy_planned_timeline_for_metadata(metadata: dict[str, Any] | None) -> bool:
    if not isinstance(metadata, dict):
        return False
    if _prefer_execution_requests_for_metadata(metadata):
        return False
    return bool(metadata.get("daily_desktop_intent"))


def _runtime_planner_compatible_legacy_plan_requests(
    requests: list[dict[str, Any]],
    metadata: dict[str, Any] | None,
) -> list[dict[str, Any]]:
    if not isinstance(metadata, dict) or not bool(metadata.get("yachiyo_runtime_planner")):
        return requests
    compatible: list[dict[str, Any]] = []
    for request in requests:
        if str(request.get("tool") or "").strip() == "media.apple_music_play":
            compatible.append(
                {
                    **request,
                    "source": "runtime_planner",
                    "planning_reason": "planner_fallback_media_playback",
                }
            )
            continue
        compatible.append(request)
    return compatible


def _legacy_direct_execution_override_requests(
    prompt: str,
    metadata: dict[str, Any] | None,
    allowed_tools: list[str],
    planner_requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    legacy_requests = daily_desktop_entrypoint_requests(
        prompt,
        metadata=metadata,
        allowed_tools=allowed_tools,
    )
    if not legacy_requests:
        return []
    if _legacy_information_capture_override_requests(legacy_requests, planner_requests):
        return legacy_requests
    if _legacy_clipboard_link_open_override_requests(legacy_requests, planner_requests):
        return legacy_requests
    if not _prefer_legacy_planned_timeline_for_metadata(metadata):
        return []
    legacy_tools = _tool_names_for_requests(legacy_requests)
    if "media.apple_music_play" in legacy_tools:
        return legacy_requests
    if _has_approval_plan_tool(legacy_requests) and _planner_requests_need_model_followup(
        planner_requests
    ):
        return _legacy_requests_with_type_sequence_verification(
            legacy_requests,
            allowed_tools,
        )
    return []


def _legacy_information_capture_override_requests(
    legacy_requests: list[dict[str, Any]],
    planner_requests: list[dict[str, Any]],
) -> bool:
    if not _planner_requests_need_model_followup(planner_requests):
        return False
    planner_tools = set(_tool_names_for_requests(planner_requests))
    if planner_tools != {"clipboard.read"}:
        return False
    legacy_tools = _tool_names_for_requests(legacy_requests)
    if "app.open_and_safe_shortcut" not in legacy_tools:
        return False
    for request in legacy_requests:
        if str(request.get("tool") or "").strip() != "desktop.safe_shortcut":
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        if str(payload.get("action") or "").strip() == "paste":
            return True
    return False


def _legacy_clipboard_link_open_override_requests(
    legacy_requests: list[dict[str, Any]],
    planner_requests: list[dict[str, Any]],
) -> bool:
    if not legacy_requests or not planner_requests:
        return False
    legacy_first = legacy_requests[0]
    planner_first = planner_requests[0]
    if str(legacy_first.get("tool") or "").strip() != "app.open_and_safe_shortcut":
        return False
    if str(planner_first.get("tool") or "").strip() != "desktop.safe_shortcut":
        return False
    legacy_input = legacy_first.get("input") if isinstance(legacy_first.get("input"), dict) else {}
    planner_input = planner_first.get("input") if isinstance(planner_first.get("input"), dict) else {}
    if str(legacy_input.get("action") or "").strip() != "focus_address_bar":
        return False
    if str(planner_input.get("action") or "").strip() != "focus_address_bar":
        return False
    return _tool_names_for_requests(planner_requests) == [
        "desktop.safe_shortcut",
        "desktop.safe_shortcut",
        "desktop.search_submit",
    ]


def _legacy_requests_with_type_sequence_verification(
    requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    if "desktop.ui_elements" not in allowed:
        return requests
    if any(str(request.get("tool") or "").strip() == "desktop.ui_elements" for request in requests):
        return requests
    type_request = next(
        (
            request
            for request in requests
            if str(request.get("tool") or "").strip() == "desktop.type_into_ui_element"
        ),
        None,
    )
    if type_request is None:
        return requests
    has_return_hotkey = False
    for request in requests:
        if str(request.get("tool") or "").strip() != "desktop.hotkey":
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        key = str(payload.get("key") or "").strip().lower()
        if key in {"return", "enter"}:
            has_return_hotkey = True
            break
    if not has_return_hotkey:
        return requests
    type_payload = type_request.get("input") if isinstance(type_request.get("input"), dict) else {}
    return [
        *requests,
        {
            "protocol": "json_fallback",
            "tool": "desktop.ui_elements",
            "input": {
                "role_filter": str(type_payload.get("role_filter") or "text").strip() or "text",
                "limit": type_payload.get("limit") or 80,
            },
            "source": "runtime_planner",
            "planning_reason": "planner_desktop_operation",
        },
    ]


def _planner_requests_need_model_followup(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    if any(bool(request.get("continue_to_model")) for request in requests):
        return True
    tools = set(_tool_names_for_requests(requests))
    return bool(tools) and tools <= {"desktop.ui_elements", "screen.capture"}


def _tool_names_for_requests(requests: list[dict[str, Any]]) -> list[str]:
    return [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("tool") or "").strip()
    ]


def _visible_daily_desktop_metadata_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    for index, request in enumerate(requests):
        if str(request.get("tool") or "").strip() == "data.analyze":
            return requests[index:]
    primary = [
        request
        for request in requests
        if str(request.get("tool") or "").strip() not in _DAILY_DESKTOP_METADATA_DISCOVERY_TOOLS
        and str(request.get("tool") or "").strip() not in _DAILY_DESKTOP_METADATA_VERIFY_TOOLS
    ]
    return primary or requests


def _task_message_metadata(chat_session: Any, task_id: str, *, role: str) -> dict[str, Any]:
    for message in getattr(chat_session, "messages", []) or []:
        if str(getattr(message, "task_id", "") or "").strip() != str(task_id or "").strip():
            continue
        message_role = getattr(message, "role", "")
        role_value = str(getattr(message_role, "value", message_role) or "").strip()
        if role_value != role:
            continue
        metadata = getattr(message, "metadata", None)
        return dict(metadata) if isinstance(metadata, dict) else {}
    return {}


def _legacy_app_launch_metadata_compat(requests: list[dict[str, Any]]) -> bool:
    if len(requests) != 1:
        return False
    request = requests[0]
    return (
        str(request.get("tool") or "").strip() == "app.open"
        and str(request.get("planning_reason") or "").strip() == "planner_desktop_operation"
    )


def _legacy_daily_desktop_metadata_compat(
    requests: list[dict[str, Any]],
    existing_user_metadata: dict[str, Any] | None,
) -> bool:
    if _prefer_execution_requests_for_metadata(existing_user_metadata):
        return False
    if _legacy_app_launch_metadata_compat(requests):
        return True
    tools = set(_tool_names_for_requests(requests))
    if not tools:
        return False
    if tools <= set(_APPROVAL_PLAN_TOOLS):
        return True
    if tools <= set(_SAFE_SHORTCUT_APPROVAL_TOOLS):
        return True
    if tools <= {"desktop.safe_shortcut", "desktop.hotkey"}:
        return True
    return False


def _legacy_daily_desktop_compatible_metadata(metadata: dict[str, Any]) -> dict[str, Any]:
    if str(metadata.get("daily_desktop_source") or "").strip() != "runtime_planner":
        return metadata
    return {
        **metadata,
        "daily_desktop_source": "daily_desktop_intent",
        "daily_desktop_planning_reason": "clear_daily_desktop_intent",
        "entrypoint_plan_source": "daily_desktop_intent",
        "entrypoint_plan_reason": "clear_daily_desktop_intent",
        "entrypoint_plan_legacy_fallback": True,
    }


def _expose_runtime_planner_user_metadata(
    requests: list[dict[str, Any]],
    existing_user_metadata: dict[str, Any] | None,
) -> bool:
    if _prefer_execution_requests_for_metadata(existing_user_metadata):
        return True
    if _legacy_daily_desktop_metadata_compat(requests, existing_user_metadata):
        return False
    tools = set(_tool_names_for_requests(requests))
    if not tools:
        return False
    if tools & {
        "artifact.write",
        "browser.current_page",
        "browser.extract",
        "browser.extract_text",
        "browser.open_url_and_extract_text",
        "data.analyze",
        "future_task.schedule",
        "terminal.run",
        "workspace.read",
    }:
        return True
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if str(request.get("planning_reason") or "").strip()
    }
    return any(
        reason.startswith("planner_builtin_")
        or reason.startswith("planner_prefetch_")
        or reason.startswith("planner_fallback_data_analysis")
        for reason in reasons
    )


def _legacy_hotkey_compat_required(runtime: Any) -> bool:
    return not callable(getattr(runtime, "_main_chat_tool_policy", None))


class LegacyChatTaskStarter:
    """Starts agent tasks through the existing Chat session path when available."""

    def __init__(self, app_runtime: Any, runtime: Any) -> None:
        self._app_runtime = app_runtime
        self._runtime = runtime
        self._projector = LegacyRunPayloadProjector()

    def start_chat_task(self, request: dict[str, Any]) -> dict[str, Any] | None:
        if str(request.get("workflow_id") or "").strip():
            return None
        agent_id = str(request.get("agent_id") or request.get("runnable_id") or "").strip()
        if not agent_id:
            agent_id = MAIN_CHAT_AGENT_ID
        if getattr(self._app_runtime, "chat_session", None) is None:
            return None

        metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
        client_message_id = str(
            metadata.get("client_message_id")
            or metadata.get("idempotency_key")
            or metadata.get("client_task_id")
            or ""
        ).strip()
        result = ChatAPI(self._app_runtime).send_runnable_message_in_session(
            str(request.get("conversation_id") or ""),
            str(request.get("prompt") or ""),
            runnable_id=agent_id,
            client_message_id=client_message_id,
            metadata=metadata,
        )
        if result.get("ok") is False:
            raise ValueError(str(result.get("error") or "发送 Agent 任务失败"))

        run_id = str(
            result.get("run_id")
            or result.get("agent_run_id")
            or result.get("workflow_run_id")
            or ""
        ).strip()
        conversation_id = str(
            result.get("session_id")
            or request.get("conversation_id")
            or getattr(getattr(self._app_runtime, "chat_session", None), "session_id", "")
            or ""
        ).strip()
        task_id = str(
            result.get("task_id")
            or metadata.get("task_id")
            or metadata.get("client_task_id")
            or run_id
        ).strip()
        if not run_id:
            if agent_id != MAIN_CHAT_AGENT_ID or not task_id:
                return None
            executed = self._execute_main_daily_desktop_task(
                task_id=task_id,
                conversation_id=conversation_id,
                prompt=str(request.get("prompt") or request.get("goal") or ""),
                metadata=metadata,
            )
            if executed is not None:
                return executed
            return self._projector.chat_task_payload(
                {
                    "task_id": task_id,
                    "session_id": conversation_id,
                    "status": result.get("status") or "pending",
                    "user_goal": request.get("prompt") or request.get("goal") or "",
                    "summary": result.get("summary") or result.get("result") or "",
                    "timeline": result.get("timeline")
                    or self._planner_first_planned_timeline(
                        str(request.get("prompt") or request.get("goal") or ""),
                        metadata=metadata,
                    ),
                },
                conversation_id=conversation_id,
            )

        link_task_run = getattr(self._runtime, "link_task_run", None)
        if callable(link_task_run):
            link_task_run(task_id=task_id, run_id=run_id, session_id=conversation_id)

        try:
            run = self._runtime.get_run(run_id)
        except KeyError:
            run = {
                **result,
                "run_id": run_id,
                "task_id": task_id,
                "session_id": conversation_id,
            }
        return self._projector.chat_task_payload(
            {**run, "task_id": task_id, "session_id": conversation_id},
            conversation_id=conversation_id,
        )

    def execute_existing_main_chat_task(
        self,
        *,
        task_id: str,
        conversation_id: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        return self._execute_main_daily_desktop_task(
            task_id=task_id,
            conversation_id=conversation_id,
            prompt=prompt,
            metadata=metadata,
        )

    def _planner_first_planned_timeline(
        self,
        prompt: str,
        *,
        metadata: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        allowed_daily_desktop_tools = daily_desktop_allowed_tools()
        allowed_entrypoint_tools = main_chat_entrypoint_allowed_tools(
            self._runtime,
            fallback=allowed_daily_desktop_tools,
        )
        if _prefer_legacy_planned_timeline_for_metadata(metadata):
            legacy_requests = daily_desktop_entrypoint_requests(
                prompt,
                metadata=metadata,
                allowed_tools=allowed_daily_desktop_tools,
            )
            legacy_requests = _runtime_planner_compatible_legacy_plan_requests(
                legacy_requests,
                metadata,
            )
            if legacy_requests:
                return daily_desktop_planned_timeline(
                    prompt,
                    requests=legacy_requests,
                    metadata=metadata,
                    allowed_tools=allowed_entrypoint_tools,
                )
        planned_requests = planner_first_daily_desktop_entrypoint_requests(
            prompt,
            metadata=metadata,
            allowed_tools=allowed_entrypoint_tools,
            metadata_allowed_tools=allowed_daily_desktop_tools,
            execution_normalized=True,
        )
        if _prefer_execution_requests_for_metadata(metadata):
            planned_requests = [
                {
                    **request,
                    "planning_reason": (
                        "planner_fallback_desktop_operation"
                        if str(request.get("planning_reason") or "").strip()
                        == "planner_desktop_operation"
                        else request.get("planning_reason")
                    ),
                }
                for request in planned_requests
            ]
        return daily_desktop_planned_timeline(
            prompt,
            requests=planned_requests,
            metadata=metadata,
            allowed_tools=allowed_entrypoint_tools,
        )

    def _execute_main_daily_desktop_task(
        self,
        *,
        task_id: str,
        conversation_id: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        prompt = str(prompt or "").strip()
        metadata = _planner_metadata_with_desktop_readiness(metadata or {})
        metadata["runtime_planner_execution_context"] = True
        allowed_daily_desktop_tools = daily_desktop_allowed_tools()
        allowed_entrypoint_tools = main_chat_entrypoint_allowed_tools(
            self._runtime,
            fallback=allowed_daily_desktop_tools,
        )
        execution_prompt = daily_desktop_recovery_execution_prompt(prompt, metadata)
        planning_prompt = _entrypoint_planning_context(prompt or execution_prompt, metadata)
        direct_tool_request = daily_desktop_direct_metadata_request(
            metadata,
            allowed_tools=allowed_daily_desktop_tools,
        )
        planner_decision, selected_requests = (None, [])
        direct_tool_requests: list[dict[str, Any]] = []
        direct_tool_selection_payload: dict[str, Any] = {}
        selected_source = ""
        if not direct_tool_request:
            selection = planner_first_direct_tool_selection(
                planning_prompt,
                allowed_entrypoint_tools,
                metadata=metadata,
                legacy_tool_requests=lambda value, tools: daily_desktop_entrypoint_requests(
                    value,
                    metadata=metadata,
                    allowed_tools=tools,
                ),
            )
            planner_decision = selection.decision
            selection_requests = selection.requests
            selected_source = selection.selected_source
            legacy_override_requests = _legacy_direct_execution_override_requests(
                prompt or execution_prompt,
                metadata,
                allowed_entrypoint_tools,
                selection_requests,
            )
            if legacy_override_requests:
                selection_requests = legacy_override_requests
                selected_source = "daily_desktop_intent"
            selected_requests = _apply_legacy_search_field_target_label(
                prompt or execution_prompt,
                selection_requests,
            )
            selected_requests = _apply_legacy_return_hotkey_projection(
                prompt or execution_prompt,
                selected_requests,
                allowed_entrypoint_tools,
            )
            raw_selected_requests = list(selected_requests)
            if _legacy_hotkey_compat_required(self._runtime):
                selected_requests = _apply_legacy_hotkey_safe_shortcut_request(
                    prompt or execution_prompt,
                    selected_requests,
                    allowed_entrypoint_tools,
                )
            selected_requests = _annotate_legacy_selected_requests_with_planner_trace(
                selected_requests,
                planner_decision,
            )
            direct_tool_selection_payload = (
                _selection_payload_with_selected_requests(
                    selection.event_payload,
                    selected_requests,
                )
                if selected_requests != raw_selected_requests
                else selection.event_payload
            )
            if selected_source != selection.selected_source:
                direct_tool_selection_payload = _selection_payload_with_selected_source(
                    direct_tool_selection_payload,
                    selected_source,
                    selected_requests,
                )
            direct_tool_selection_payload = _approval_first_selection_payload(
                direct_tool_selection_payload,
                selected_requests,
            )
            direct_tool_selection_payload = _legacy_daily_desktop_selection_payload(
                direct_tool_selection_payload,
                prompt or execution_prompt,
                metadata,
                allowed_entrypoint_tools,
                selected_requests,
            )
            envelope_tool_requests = (
                _safe_runtime_execution_envelope_requests(
                    prompt or execution_prompt,
                    metadata,
                    allowed_entrypoint_tools,
                    selected_requests=selected_requests,
                )
                if selected_source in {"runtime_planner", "none", ""}
                else []
            )
            if envelope_tool_requests:
                direct_tool_requests = envelope_tool_requests
            elif selected_source == "runtime_planner":
                direct_tool_requests = _safe_runtime_planner_tool_requests(
                    planning_prompt,
                    allowed_entrypoint_tools,
                    metadata=metadata,
                    selected_requests=selected_requests,
                )
            else:
                direct_tool_requests = _safe_selected_entrypoint_tool_requests(
                    prompt or execution_prompt,
                    selected_requests,
                    allowed_entrypoint_tools,
                )
        if not task_id:
            return None
        if not direct_tool_request and not selected_requests and not direct_tool_requests:
            return None
        if direct_tool_request:
            metadata_tool_requests = [direct_tool_request]
        elif _prefer_execution_requests_for_metadata(metadata):
            metadata_tool_requests = (
                planner_execution_tool_requests(
                    direct_tool_requests or selected_requests,
                    allowed_entrypoint_tools,
                )
                or direct_tool_requests
                or selected_requests
            )
        else:
            metadata_tool_requests = selected_requests or direct_tool_requests
        self._sync_chat_user_daily_desktop_metadata(
            task_id,
            metadata_tool_requests,
            planner_decision=(
                planner_decision if selected_source == "runtime_planner" else None
            ),
        )
        start_main_chat_run = getattr(self._runtime, "start_main_chat_run", None)
        execute_main_chat_model_loop = getattr(self._runtime, "execute_main_chat_model_loop", None)
        if not callable(start_main_chat_run) or not callable(execute_main_chat_model_loop):
            return None

        self._sync_app_task_running(task_id)
        run_id = ""
        try:
            run = start_main_chat_run(
                task_id=task_id,
                session_id=conversation_id,
                user_goal=prompt or execution_prompt,
            )
            run_id = str(run.get("run_id") or "").strip()
            if not run_id:
                return None
            self._append_planner_run_events(run_id, planner_decision)
            self._append_direct_tool_selection_run_event(run_id, direct_tool_selection_payload)
            append_run_event = getattr(self._runtime, "append_run_event", None)
            retry_context_payload = recovery_retry_context_payload(metadata)
            if retry_context_payload and callable(append_run_event):
                append_run_event(
                    run_id,
                    RECOVERY_RETRY_CONTEXT_EVENT_TYPE,
                    retry_context_payload,
                )
            run = execute_main_chat_model_loop(
                run_id,
                [{"role": "user", "content": execution_prompt or prompt or "执行恢复后的原操作"}],
                direct_tool_request=direct_tool_request,
                direct_tool_requests=direct_tool_requests,
            )
            status = str(run.get("status") or "").strip()
            result_text = str(run.get("result") or "").strip()
            if status == "approval_required":
                self._sync_chat_assistant_message(
                    task_id,
                    conversation_id,
                    "等待你在 Agent Studio 中审批后继续。",
                    status="processing",
                )
                return self._projector.chat_task_payload(
                    {**run, "task_id": task_id, "session_id": conversation_id},
                    conversation_id=conversation_id,
                )
            if status in {"failed", "cancelled"}:
                self._sync_app_task_failed(task_id, result_text or f"Native Run {status}")
                self._sync_chat_assistant_message(
                    task_id,
                    conversation_id,
                    result_text or f"Native Run {status}",
                    status="failed",
                    error=result_text or f"Native Run {status}",
                )
                return self._projector.chat_task_payload(
                    {**run, "task_id": task_id, "session_id": conversation_id},
                    conversation_id=conversation_id,
                )
            complete_main_chat_run = getattr(self._runtime, "complete_main_chat_run", None)
            if callable(complete_main_chat_run) and result_text:
                run = complete_main_chat_run(run_id, result_text)
            self._sync_app_task_completed(task_id, result_text)
            if result_text:
                self._sync_chat_assistant_message(
                    task_id,
                    conversation_id,
                    result_text,
                    status="completed",
                )
            return self._projector.chat_task_payload(
                {**run, "task_id": task_id, "session_id": conversation_id},
                conversation_id=conversation_id,
            )
        except Exception as exc:
            if run_id:
                fail_main_chat_run = getattr(self._runtime, "fail_main_chat_run", None)
                if callable(fail_main_chat_run):
                    try:
                        fail_main_chat_run(run_id, exc)
                    except Exception:
                        pass
            self._sync_app_task_failed(task_id, str(exc))
            self._sync_chat_assistant_message(
                task_id,
                conversation_id,
                str(exc),
                status="failed",
                error=str(exc),
            )
            raise

    def _sync_chat_user_daily_desktop_metadata(
        self,
        task_id: str,
        desktop_requests: list[dict[str, Any]],
        *,
        planner_decision: Any | None = None,
    ) -> None:
        chat_session = getattr(self._app_runtime, "chat_session", None)
        update_metadata = getattr(chat_session, "update_message_metadata_for_task", None)
        if not callable(update_metadata):
            return
        visible_requests = _visible_daily_desktop_metadata_requests(desktop_requests)
        existing_user_metadata = _task_message_metadata(chat_session, task_id, role="user")
        entrypoint_metadata = entrypoint_plan_user_metadata(visible_requests)
        if _legacy_daily_desktop_metadata_compat(visible_requests, existing_user_metadata):
            entrypoint_metadata = _legacy_daily_desktop_compatible_metadata(entrypoint_metadata)
        planner_metadata = (
            runtime_planner_metadata(planner_decision)
            if _expose_runtime_planner_user_metadata(visible_requests, existing_user_metadata)
            else {}
        )
        metadata = {
            **planner_metadata,
            **entrypoint_metadata,
        }
        if not metadata:
            return
        try:
            update_metadata(task_id, metadata, role="user")
        except Exception:
            return

    def _append_planner_run_events(self, run_id: str, planner_decision: Any | None) -> None:
        append_run_event = getattr(self._runtime, "append_run_event", None)
        if not run_id or not callable(append_run_event):
            return
        for event_type, payload in planner_run_event_payloads(planner_decision):
            try:
                append_run_event(run_id, event_type, payload)
            except Exception:
                continue

    def _append_direct_tool_selection_run_event(
        self,
        run_id: str,
        payload: dict[str, Any],
    ) -> None:
        append_run_event = getattr(self._runtime, "append_run_event", None)
        if not run_id or not payload or not callable(append_run_event):
            return
        try:
            append_run_event(run_id, "agent.plan.selection", dict(payload))
        except Exception:
            return

    def _sync_app_task_running(self, task_id: str) -> None:
        self._sync_app_task_status(task_id, "running", progress_label="正在执行桌面操作")

    def _sync_app_task_completed(self, task_id: str, result: str) -> None:
        self._sync_app_task_status(
            task_id,
            "completed",
            result=result or "[任务已完成，无输出]",
            progress_label="已完成",
        )

    def _sync_app_task_failed(self, task_id: str, error: str) -> None:
        self._sync_app_task_status(
            task_id,
            "failed",
            error=error or "任务执行失败",
            progress_label="执行失败",
        )

    def _sync_app_task_status(
        self,
        task_id: str,
        status: str,
        *,
        result: str | None = None,
        error: str | None = None,
        progress_label: str | None = None,
    ) -> None:
        state = getattr(self._app_runtime, "state", None)
        update_task_status = getattr(state, "update_task_status", None)
        if not callable(update_task_status):
            return
        try:
            from packages.protocol.enums import TaskStatus

            update_task_status(
                task_id,
                TaskStatus(status),
                result=result,
                error=error,
                progress_label=progress_label,
            )
        except Exception:
            return

    def _sync_chat_assistant_message(
        self,
        task_id: str,
        conversation_id: str,
        content: str,
        *,
        status: str,
        error: str | None = None,
    ) -> None:
        session = self._chat_session_for_conversation(conversation_id)
        upsert = getattr(session, "upsert_assistant_message", None)
        if session is None or not callable(upsert):
            return
        try:
            from apps.core.chat_session import MessageStatus

            message_status = {
                "completed": MessageStatus.COMPLETED,
                "failed": MessageStatus.FAILED,
                "processing": MessageStatus.PROCESSING,
            }.get(status, MessageStatus.PROCESSING)
            upsert(
                task_id=task_id,
                content=content,
                status=message_status,
                error=error,
            )
        except Exception:
            return

    def _chat_session_for_conversation(self, conversation_id: str) -> Any:
        current = getattr(self._app_runtime, "chat_session", None)
        if not conversation_id:
            return current
        if str(getattr(current, "session_id", "") or "") == conversation_id:
            return current
        try:
            from apps.core.chat_session import ChatSession
            from apps.core.chat_store import get_chat_store

            store = getattr(self._app_runtime, "store", None) or get_chat_store()
            session = ChatSession(session_id=conversation_id)
            session.attach_store(
                store,
                load_existing=True,
                fail_active_messages=False,
            )
            return session
        except Exception:
            return current

class LegacyStudioPort:
    """StudioPort adapter for the current Agent Studio runtime API."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime
        self._projector = LegacyRunPayloadProjector()
        self._desk_store = LocalAgentDeskStore(runtime=runtime)

    def list_agents(self) -> dict[str, Any]:
        return self._runtime.list_agents()

    def list_tool_catalog(self) -> dict[str, Any]:
        try:
            missing_permissions = desktop_permission_missing_by_capability()
        except Exception:
            missing_permissions = {"desktop_execution": ["permission_probe_failed"]}
        try:
            blocking_conditions = desktop_runtime_blocking_conditions_by_capability()
        except Exception:
            blocking_conditions = {}
        plugin_states = None
        list_plugins = getattr(self._runtime, "list_restricted_tool_plugins", None)
        if callable(list_plugins):
            try:
                payload = list_plugins()
                plugin_states = payload.get("plugins") if isinstance(payload, dict) else payload
            except Exception:
                plugin_states = None
        return runtime_tool_catalog_snapshot(
            missing_permissions=missing_permissions,
            blocking_conditions=blocking_conditions,
            plugin_states=plugin_states,
        ).model_dump(mode="json")

    def list_restricted_tool_plugins(self) -> dict[str, Any]:
        list_plugins = getattr(self._runtime, "list_restricted_tool_plugins", None)
        if callable(list_plugins):
            payload = list_plugins()
            if isinstance(payload, dict):
                return dict(payload)
            if isinstance(payload, (list, tuple)):
                return {"ok": True, "plugins": list(payload)}
            return {"ok": True, "plugins": []}
        catalog = runtime_tool_catalog_snapshot()
        return {
            "ok": True,
            "plugins": [plugin.model_dump(mode="json") for plugin in catalog.plugins],
        }

    def install_restricted_tool_plugin(self, request: dict[str, Any]) -> dict[str, Any]:
        install_plugin = getattr(self._runtime, "install_restricted_tool_plugin", None)
        if callable(install_plugin):
            return dict(install_plugin(dict(request)))
        raise AgentRuntimeError("Restricted tool plugin install is not available")

    def update_restricted_tool_plugin(
        self,
        plugin_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        update_plugin = getattr(self._runtime, "update_restricted_tool_plugin", None)
        if callable(update_plugin):
            return dict(update_plugin(plugin_id, dict(request)))
        raise AgentRuntimeError("Restricted tool plugin update is not available")

    def uninstall_restricted_tool_plugin(self, plugin_id: str) -> dict[str, Any]:
        uninstall_plugin = getattr(self._runtime, "uninstall_restricted_tool_plugin", None)
        if callable(uninstall_plugin):
            return dict(uninstall_plugin(plugin_id))
        raise AgentRuntimeError("Restricted tool plugin uninstall is not available")

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self._runtime.get_agent(agent_id)

    def save_agent(self, request: dict[str, Any]) -> dict[str, Any]:
        agent_id = str(request.get("agent_id") or "").strip()
        if agent_id:
            try:
                self._runtime.get_agent(agent_id)
            except KeyError:
                return self._runtime.create_agent(request)
            return self._runtime.update_agent(agent_id, request)
        return self._runtime.create_agent(request)

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        return self._runtime.delete_agent(agent_id)

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        return self._runtime.test_agent_model(agent_id)

    def get_agent_desk(self, agent_id: str) -> dict[str, Any]:
        return self._desk_store.get_agent_desk(agent_id)

    def write_agent_desk_note(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._desk_store.write_agent_desk_note(
            agent_id,
            str(request.get("content") or ""),
        )

    def write_agent_desk_file(self, agent_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._desk_store.write_agent_desk_file(
            agent_id,
            str(request.get("path") or ""),
            str(request.get("content") or ""),
        )

    def trigger_agent_desk_file_event(
        self,
        agent_id: str,
        request: dict[str, Any],
    ) -> dict[str, Any]:
        return self._desk_store.trigger_agent_desk_file_event(agent_id, request)

    def attach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        return self._runtime.attach_skill(agent_id, skill_id)

    def detach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        return self._runtime.detach_skill(agent_id, skill_id)

    def list_skills(self) -> dict[str, Any]:
        return self._runtime.list_skills()

    def update_skill(self, skill_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.update_skill(skill_id, request)

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        return self._runtime.delete_skill(skill_id)

    def list_skill_folders(self) -> dict[str, Any]:
        return self._runtime.list_skill_folders()

    def create_skill_folder(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.create_skill_folder(request)

    def update_skill_folder(self, folder_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.update_skill_folder(folder_id, request)

    def delete_skill_folder(self, folder_id: str, delete_skills: bool = False) -> dict[str, Any]:
        return self._runtime.delete_skill_folder(folder_id, delete_skills=delete_skills)

    def list_skill_sources(self) -> dict[str, Any]:
        return self._runtime.list_native_skill_sources()

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        return self._runtime.import_skill(source_path, folder_id)

    def sync_native_skills(self) -> dict[str, Any]:
        return self._runtime.sync_native_skills()

    def install_skill_command(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        return self._runtime.install_skill_command(command, folder_id)

    def list_memories(self, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        return self._runtime.list_memory_items(
            include_deleted=include_deleted,
            limit=limit,
        )

    def create_memory(self, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.create_memory_item(request)

    def update_memory(self, memory_id: str, request: dict[str, Any]) -> dict[str, Any]:
        return self._runtime.update_memory_item(memory_id, request)

    def delete_memory(self, memory_id: str, reason: str | None = None) -> dict[str, Any]:
        return self._runtime.delete_memory_item(memory_id, reason=reason or "")

    def list_future_tasks(
        self,
        include_finished: bool = True,
        limit: int = 100,
    ) -> dict[str, Any]:
        return self._runtime.list_future_tasks(
            include_finished=include_finished,
            limit=limit,
        )

    def cancel_future_task(
        self,
        future_task_id: str,
        reason: str | None = None,
    ) -> dict[str, Any]:
        return self._runtime.cancel_future_task(future_task_id, reason=reason or "")

    def trigger_due_future_tasks(
        self,
        now_epoch: float | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        return self._runtime.trigger_due_future_tasks(
            now_epoch=now_epoch,
            limit=limit,
        )

    def start_agent_run(self, request: dict[str, Any]) -> dict[str, Any]:
        user_goal = str(request.get("objective") or request.get("goal") or "").strip()
        metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
        planner_metadata = _planner_metadata_with_desktop_readiness(metadata)
        agent_id = request.get("agent_id")
        run = self._runtime.create_agent_run(
            {
                "agent_id": agent_id,
                "user_goal": user_goal,
                "source": "yachiyo_studio",
                "client_run_id": request.get("client_run_id"),
                "run_group_id": request.get("run_group_id"),
                "runtime_planner_entrypoint": True,
            }
        )
        self._append_planner_run_events(
            _run_id_from_payload(run),
            runtime_planner_decision(
                user_goal,
                allowed_tools=_agent_allowed_tools(self._runtime, agent_id),
                metadata=planner_metadata,
            ),
        )
        return run

    def list_groups(self) -> dict[str, Any]:
        list_agent_groups = getattr(self._runtime, "list_agent_groups", None)
        if callable(list_agent_groups):
            return list_agent_groups()

        chat_groups = chat_group_snapshots(self._runtime)
        if chat_groups:
            return {"ok": True, "groups": chat_groups}

        list_run_groups = getattr(self._runtime, "list_run_groups", None)
        if callable(list_run_groups):
            payload = list_run_groups(50)
            return {
                "ok": True,
                "groups": [
                    group_definition_from_run_group(item, self._runtime)
                    for item in payload.get("run_groups") or []
                    if isinstance(item, dict)
                ],
            }
        return {"ok": True, "groups": []}

    def get_group(self, group_id: str) -> dict[str, Any]:
        get_agent_group = getattr(self._runtime, "get_agent_group", None)
        if callable(get_agent_group):
            return get_agent_group(group_id)
        chat_group = chat_group_snapshot(group_id, self._runtime)
        if chat_group is not None:
            return chat_group
        run_group = self._runtime.get_run_group(group_id)
        return group_definition_from_run_group(run_group, self._runtime)

    def save_group(self, request: dict[str, Any]) -> dict[str, Any]:
        save_agent_group = getattr(self._runtime, "save_agent_group", None)
        if callable(save_agent_group):
            return save_agent_group(request)

        group_id = str(request.get("group_id") or request.get("agent_group_id") or "").strip()
        if group_id:
            update_agent_group = getattr(self._runtime, "update_agent_group", None)
            if callable(update_agent_group):
                return update_agent_group(group_id, request)
        else:
            create_agent_group = getattr(self._runtime, "create_agent_group", None)
            if callable(create_agent_group):
                return create_agent_group(request)

        return save_chat_group_snapshot(request, self._runtime)

    def start_group_run(self, request: dict[str, Any]) -> dict[str, Any]:
        start_agent_group_run = getattr(self._runtime, "start_agent_group_run", None)
        if callable(start_agent_group_run):
            return start_agent_group_run(request)

        return start_legacy_group_run(
            self._runtime,
            request,
            get_group=self.get_group,
            projector=self._projector,
        )

    def list_group_runs(self, limit: int = 50) -> dict[str, Any]:
        list_run_groups = getattr(self._runtime, "list_run_groups", None)
        if not callable(list_run_groups):
            return {"ok": True, "group_runs": []}

        payload = list_run_groups(max(1, min(200, int(limit or 50))))
        raw_items = payload.get("run_groups") if isinstance(payload, dict) else payload
        if not isinstance(raw_items, list):
            raw_items = []
        return {
            "ok": True,
            "group_runs": [
                self._projector.group_run_from_legacy_run_group(item, self._runtime)
                for item in raw_items
                if isinstance(item, dict)
            ],
        }

    def get_group_run(self, group_run_id: str) -> dict[str, Any]:
        run_group = self._runtime.get_run_group(group_run_id)
        return self._projector.group_run_from_legacy_run_group(run_group, self._runtime)

    def get_group_run_event_stream(self, group_run_id: str) -> dict[str, Any]:
        list_group_run_events = getattr(self._runtime, "list_group_run_events", None)
        if callable(list_group_run_events):
            return list_group_run_events(group_run_id, limit=500)
        group_run = group_run_snapshot_from_payload(self.get_group_run(group_run_id))
        return {
            "run_id": group_run.group_run_id,
            "events": [event.model_dump(mode="python") for event in group_run.events],
        }

    def get_group_run_event_page(
        self,
        group_run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        list_group_run_events = getattr(self._runtime, "list_group_run_events", None)
        if callable(list_group_run_events):
            return list_group_run_events(
                group_run_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        return _run_event_page_from_legacy_stream(
            self.get_group_run_event_stream(group_run_id),
            run_id=group_run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def list_workflows(self) -> dict[str, Any]:
        return self._runtime.list_workflows()

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._runtime.get_workflow(workflow_id)

    def save_workflow(self, request: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(request.get("workflow_id") or "").strip()
        if workflow_id:
            try:
                self._runtime.get_workflow(workflow_id)
            except KeyError:
                return self._runtime.create_workflow(request)
            return self._runtime.update_workflow(workflow_id, request)
        return self._runtime.create_workflow(request)

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self._runtime.delete_workflow(workflow_id)

    def start_workflow_run(self, request: dict[str, Any]) -> dict[str, Any]:
        user_goal = str(request.get("objective") or request.get("goal") or "").strip()
        metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
        planner_metadata = _planner_metadata_with_desktop_readiness(metadata)
        run = self._runtime.create_workflow_run(
            {
                "workflow_id": request.get("workflow_id"),
                "user_goal": user_goal,
                "source": "yachiyo_studio",
                "client_run_id": request.get("client_run_id"),
                "run_group_id": request.get("run_group_id"),
            }
        )
        self._append_planner_run_events(
            _run_id_from_payload(run),
            runtime_planner_decision(user_goal, metadata=planner_metadata),
        )
        return run

    def list_run_timelines(self, limit: int = 50) -> dict[str, Any]:
        return self._runtime.list_runs(limit)

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        return _run_with_replay_events(self._runtime.get_run(run_id), self._runtime)

    def rerun_run(
        self,
        run_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self._runtime.rerun_run(run_id, request)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        return self._runtime.cancel_run(run_id)

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return self._runtime.delete_run(run_id)

    def approve_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        self._assert_run_approval(run_id, decision)
        return self._runtime.approve_run_approval(run_id)

    def reject_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        self._assert_run_approval(run_id, decision)
        return self._runtime.reject_run_approval(run_id, _rejection_reason(decision))

    def _assert_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | str | None,
    ) -> None:
        requested_approval_id = _approval_id_from_decision(decision)
        if not requested_approval_id:
            return
        _assert_matching_pending_approval(
            self._runtime.get_run(run_id),
            requested_approval_id,
        )

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return self._runtime.read_run_artifact(run_id, artifact_path)

    def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
        return self._runtime.list_run_events(run_id)

    def get_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        try:
            return self._runtime.list_run_events(
                run_id,
                after_sequence=after_sequence,
                limit=limit,
            )
        except TypeError:
            raw_page = self._runtime.list_run_events(run_id)
        return _run_event_page_from_legacy_stream(
            raw_page,
            run_id=run_id,
            after_sequence=after_sequence,
            limit=limit,
        )

    def _append_planner_run_events(self, run_id: str, planner_decision: Any | None) -> None:
        append_run_event = getattr(self._runtime, "append_run_event", None)
        if not run_id or not callable(append_run_event):
            return
        if _run_has_runtime_planner_events(self._runtime, run_id):
            return
        for event_type, payload in planner_run_event_payloads(planner_decision):
            try:
                append_run_event(run_id, event_type, payload)
            except Exception:
                continue


def _chat_task_payload(run: dict[str, Any], *, conversation_id: str = "") -> dict[str, Any]:
    return _LEGACY_RUN_PROJECTOR.chat_task_payload(run, conversation_id=conversation_id)


def _run_id_from_payload(payload: dict[str, Any]) -> str:
    return str(
        payload.get("run_id")
        or payload.get("workflow_run_id")
        or payload.get("agent_run_id")
        or ""
    ).strip()


def _run_has_runtime_planner_events(runtime: Any, run_id: str) -> bool:
    list_run_events = getattr(runtime, "list_run_events", None)
    if not callable(list_run_events):
        return False
    try:
        payload = list_run_events(run_id, after_sequence=0, limit=20)
    except TypeError:
        try:
            payload = list_run_events(run_id)
        except Exception:
            return False
    except Exception:
        return False
    events = payload.get("events") if isinstance(payload, dict) else payload
    if not isinstance(events, list):
        return False
    return any(
        isinstance(event, dict)
        and str(event.get("event_type") or event.get("event") or "").strip()
        in {"agent.intent.selected", "agent.plan.created", "agent.plan.selection"}
        and (
            _event_payload_source(event) == "runtime_planner"
            or _event_payload_source(event) == ""
        )
        for event in events
    )


def _event_payload_source(event: dict[str, Any]) -> str:
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    return str(payload.get("source") or event.get("source") or "").strip()


def _agent_allowed_tools(runtime: Any, agent_id: Any) -> list[str] | None:
    clean_agent_id = str(agent_id or "").strip()
    if not clean_agent_id:
        return None
    get_agent = getattr(runtime, "get_agent", None)
    if not callable(get_agent):
        return None
    try:
        agent = get_agent(clean_agent_id)
    except Exception:
        return None
    if not isinstance(agent, dict):
        return None
    policy = agent.get("tool_policy") if isinstance(agent.get("tool_policy"), dict) else {}
    allowed = policy.get("allowed_tools")
    if not isinstance(allowed, list):
        return None
    tools = [str(tool or "").strip() for tool in allowed if str(tool or "").strip()]
    return tools or None


def _safe_runtime_planner_tool_requests(
    prompt: str,
    allowed_tools: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    selected_requests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    selected_requests = selected_requests or []
    if _has_approval_plan_tool(selected_requests):
        return []
    if _has_explicit_hotkey_safe_shortcut(prompt, selected_requests, allowed_tools):
        return []
    if selected_requests:
        requests = planner_tool_requests(
            prompt,
            allowed_tools,
            metadata=metadata,
        )
        requests = _apply_legacy_file_transfer_app_alias(prompt, requests, allowed_tools)
        requests = _apply_legacy_plain_search_open_mode(prompt, requests, allowed_tools)
        requests = _apply_legacy_search_field_target_label(prompt, requests)
        requests = _apply_legacy_return_hotkey_projection(prompt, requests, allowed_tools)
        requests = _prepend_legacy_focus_app_search_discovery_request(prompt, requests)
        if _has_explicit_hotkey_safe_shortcut(prompt, requests, allowed_tools):
            return []
    requests = _coalesce_legacy_direct_app_shortcut_requests(
        prompt,
        requests,
        allowed_tools,
    )
    requests = _split_redundant_app_safe_shortcut_requests(requests)
    requests = _drop_legacy_open_then_plain_find_submit(prompt, requests)
    execution_requests = planner_execution_tool_requests(requests, allowed_tools) or requests
    return _drop_data_analysis_prepare_app_requests(execution_requests)
    requests = planner_direct_tool_requests(
        prompt,
        allowed_tools,
        metadata=metadata,
    )
    requests = _apply_legacy_file_transfer_app_alias(prompt, requests, allowed_tools)
    requests = _apply_legacy_plain_search_open_mode(prompt, requests, allowed_tools)
    requests = _apply_legacy_search_field_target_label(prompt, requests)
    requests = _apply_legacy_return_hotkey_projection(prompt, requests, allowed_tools)
    requests = _prepend_legacy_focus_app_search_discovery_request(prompt, requests)
    if _has_explicit_hotkey_safe_shortcut(prompt, requests, allowed_tools):
        return []
    requests = _coalesce_legacy_direct_app_shortcut_requests(prompt, requests, allowed_tools)
    requests = _split_redundant_app_safe_shortcut_requests(requests)
    requests = _drop_legacy_open_then_plain_find_submit(prompt, requests)
    return planner_execution_tool_requests(requests, allowed_tools) or requests


def _safe_runtime_execution_envelope_requests(
    prompt: str,
    metadata: dict[str, Any] | None,
    allowed_tools: list[str],
    *,
    selected_requests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    selected_requests = selected_requests or []
    if _has_approval_plan_tool(selected_requests):
        return []
    requests = runtime_execution_requests_from_metadata(
        metadata,
        allowed_tools=allowed_tools,
    )
    if not requests:
        return []
    if _has_approval_plan_tool(requests):
        return []
    if _has_explicit_hotkey_safe_shortcut(prompt, requests, allowed_tools):
        return []
    requests = _split_redundant_app_safe_shortcut_requests(requests)
    return requests


def _drop_data_analysis_prepare_app_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not any(str(request.get("tool") or "").strip() == "data.analyze" for request in requests):
        return requests
    return [
        request
        for request in requests
        if not (
            str(request.get("tool") or "").strip() == "app.open"
            and str(request.get("planning_reason") or "").strip()
            == "planner_fallback_data_analysis_spreadsheet_app"
        )
    ]


def _safe_selected_entrypoint_tool_requests(
    prompt: str,
    selected_requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    if not selected_requests:
        return []
    if _has_approval_plan_tool(selected_requests):
        return selected_requests
    if _has_explicit_hotkey_safe_shortcut(prompt, selected_requests, allowed_tools):
        return []
    requests = planner_execution_tool_requests(selected_requests, allowed_tools) or selected_requests
    return _split_redundant_app_safe_shortcut_requests(requests)


def _apply_legacy_file_transfer_app_alias(
    prompt: str,
    requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    if not requests or _search_field_prompt(prompt):
        return requests
    if "企业微信" not in str(prompt or ""):
        return requests
    if not re.search(
        r"企业微信\s*(?:里|中|上|内)?\s*(?:搜索|查找|检索|找)\s*文件传输助手",
        str(prompt or ""),
    ):
        return requests
    updated: list[dict[str, Any]] = []
    for request in requests:
        copied = dict(request)
        payload = copied.get("input") if isinstance(copied.get("input"), dict) else None
        if payload and str(payload.get("app_name") or "").strip() in {"WeChat", "微信"}:
            copied["input"] = {**payload, "app_name": "企业微信"}
            if copied.get("tool") == "app.focus" and "app.open" in set(allowed_tools):
                copied["tool"] = "app.open"
        updated.append(copied)
    return updated


def _apply_legacy_plain_search_open_mode(
    prompt: str,
    requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    if not requests or "app.open" not in set(allowed_tools):
        return requests
    value = str(prompt or "")
    if _has_app_scoped_find_shortcut(requests):
        return requests
    if _search_field_prompt(value) or re.search(
        r"(?:切到|聚焦|focus|switch\s+to)",
        value,
        flags=re.IGNORECASE,
    ):
        return requests
    if not re.search(
        r"(?:搜索|查找|检索|找|\b(?:search|find|look)\b)",
        value,
        flags=re.IGNORECASE,
    ):
        return requests
    if any(str(request.get("tool") or "").strip() == "app.open" for request in requests):
        return requests
    updated: list[dict[str, Any]] = []
    converted = False
    for request in requests:
        copied = dict(request)
        if not converted and copied.get("tool") == "app.focus":
            copied["tool"] = "app.open"
            converted = True
        updated.append(copied)
    return updated


def _drop_legacy_open_then_plain_find_submit(
    prompt: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requests or not _legacy_open_then_plain_find_prompt(prompt):
        return requests
    updated: list[dict[str, Any]] = []
    has_find_shortcut = False
    has_typed_query = False
    dropped_submit = False
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        if tool_name in {"desktop.safe_shortcut", "app.open_and_safe_shortcut"}:
            has_find_shortcut = str(payload.get("action") or "").strip() == "find"
        elif has_find_shortcut and tool_name == "desktop.safe_type_text":
            has_typed_query = True
        if (
            has_find_shortcut
            and has_typed_query
            and not dropped_submit
            and tool_name == "desktop.search_submit"
        ):
            dropped_submit = True
            continue
        updated.append(request)
    return updated


def _legacy_open_then_plain_find_prompt(prompt: str) -> bool:
    value = str(prompt or "").strip()
    if _search_field_prompt(value):
        return False
    return bool(
        _legacy_explicit_app_open_request(value)
        and re.search(
            r"(?:然后|接着|之后)\s*(?:搜索|查找|检索)\s*[^。！？!?，,]+$",
            value,
            flags=re.IGNORECASE,
        )
    )


def _legacy_explicit_app_open_request(prompt: str) -> bool:
    return bool(
        re.search(
            r"(?:打开|启动|开启|open|launch|start)\s+",
            str(prompt or ""),
            flags=re.IGNORECASE,
        )
    )


def _has_app_scoped_find_shortcut(requests: list[dict[str, Any]]) -> bool:
    for index, request in enumerate(requests[:-1]):
        if str(request.get("tool") or "").strip() not in {"app.focus", "app.open"}:
            continue
        next_request = requests[index + 1]
        if str(next_request.get("tool") or "").strip() != "desktop.safe_shortcut":
            continue
        payload = next_request.get("input") if isinstance(next_request.get("input"), dict) else {}
        if str(payload.get("action") or "").strip() == "find":
            return True
    return False


def _apply_legacy_search_field_target_label(
    prompt: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requests or not _search_field_prompt(prompt):
        return requests
    updated: list[dict[str, Any]] = []
    for request in requests:
        updated.append(dict(request))
    return updated


def _apply_legacy_hotkey_safe_shortcut_request(
    prompt: str,
    requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools}
    if "desktop.safe_shortcut" not in allowed:
        return requests
    hotkey = hotkey_hint(prompt)
    if not hotkey:
        return requests
    key = str(hotkey.get("key") or "").strip().lower()
    modifiers = {str(item or "").strip().lower() for item in hotkey.get("modifiers") or []}
    if key != "l" or modifiers != {"command"}:
        return requests
    for request in requests:
        if str(request.get("tool") or "").strip() == "desktop.hotkey":
            return [
                {
                    "protocol": request.get("protocol") or "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "focus_address_bar"},
                    "source": request.get("source") or "runtime_planner",
                    "planning_reason": "planner_desktop_operation",
                }
            ]
    return requests


def _apply_legacy_return_hotkey_projection(
    prompt: str,
    requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    if not requests or "desktop.hotkey" not in {str(tool or "").strip() for tool in allowed_tools}:
        return requests
    if not _legacy_explicit_return_key_prompt(prompt):
        return requests
    updated: list[dict[str, Any]] = []
    converted = False
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        if (
            not converted
            and tool_name == "desktop.submit_foreground"
            and str(payload.get("action") or "").strip() == "confirm"
        ):
            updated.append(
                {
                    **request,
                    "tool": "desktop.hotkey",
                    "input": {"key": "return", "modifiers": []},
                    "planning_reason": "planner_desktop_hotkey",
                }
            )
            converted = True
            continue
        updated.append(request)
    return updated


def _legacy_explicit_return_key_prompt(prompt: str) -> bool:
    value = str(prompt or "").strip()
    if re.search(r"(?:发送|提交|send|submit).{0,8}(?:回车|enter|return)", value, flags=re.IGNORECASE):
        return False
    return bool(
        re.search(
            r"(?:并|再|然后|接着|之后|后|and\s+then|then)?.{0,8}"
            r"(?:按|敲|触发|press|hit|tap)?\s*(?:回车键?|enter|return)(?:\s|$|[。！？!?，,])",
            value,
            flags=re.IGNORECASE,
        )
    )


def _selection_payload_with_selected_requests(
    payload: dict[str, Any],
    selected_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    selected_tools = [
        str(request.get("tool") or "").strip()
        for request in selected_requests
        if str(request.get("tool") or "").strip()
    ]
    if not selected_tools:
        return payload
    return {
        **payload,
        "selected_tools": selected_tools,
        "selected_request_count": len(selected_tools),
    }


def _selection_payload_with_selected_source(
    payload: dict[str, Any],
    selected_source: str,
    selected_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    source = str(selected_source or "").strip()
    if not source:
        return payload
    selected_tools = _tool_names_for_requests(selected_requests)
    result = {
        **payload,
        "selection_source": source,
        "selected_tools": selected_tools,
        "selected_request_count": len(selected_tools),
    }
    if source == "daily_desktop_intent":
        result.update(
            {
                "selection_role": "legacy_desktop_intent_fallback",
                "selection_reason": "legacy_compatible_daily_desktop_entrypoint",
                "legacy_fallback": True,
                "legacy_tools": selected_tools,
                "legacy_request_count": len(selected_tools),
            }
        )
    return result


def _legacy_daily_desktop_selection_payload(
    payload: dict[str, Any],
    prompt: str,
    metadata: dict[str, Any] | None,
    allowed_tools: list[str],
    selected_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    if str(payload.get("selection_source") or "").strip() != "runtime_planner":
        return payload
    visible_requests = _visible_daily_desktop_metadata_requests(selected_requests)
    if not _legacy_daily_desktop_metadata_compat(visible_requests, metadata):
        return payload
    legacy_requests = daily_desktop_entrypoint_requests(
        prompt,
        metadata=metadata,
        allowed_tools=allowed_tools,
    )
    legacy_tools = _tool_names_for_requests(legacy_requests) or _tool_names_for_requests(
        visible_requests
    )
    selected_tools = _tool_names_for_requests(visible_requests)
    return {
        **payload,
        "selection_source": "daily_desktop_intent",
        "selection_role": "legacy_desktop_intent_fallback",
        "selection_reason": "legacy_compatible_daily_desktop_entrypoint",
        "legacy_fallback": True,
        "legacy_tools": legacy_tools,
        "legacy_request_count": len(legacy_tools),
        "selected_tools": selected_tools,
        "selected_request_count": len(selected_tools),
    }


def _annotate_legacy_selected_requests_with_planner_trace(
    selected_requests: list[dict[str, Any]],
    planner_decision: Any | None,
) -> list[dict[str, Any]]:
    if planner_decision is None or not selected_requests:
        return selected_requests
    plan = getattr(planner_decision, "plan", None)
    tool_plan = getattr(plan, "tool_plan", None)
    steps = list(getattr(tool_plan, "steps", []) or [])
    if not steps:
        return selected_requests
    used_step_indexes: set[int] = set()
    annotated: list[dict[str, Any]] = []
    for request in selected_requests:
        item = dict(request)
        step_index, step = _matching_planner_step_for_request(item, steps, used_step_indexes)
        if step_index >= 0 and step is not None:
            used_step_indexes.add(step_index)
            _attach_legacy_request_planner_trace(item, planner_decision, step)
        annotated.append(item)
    return annotated


def _matching_planner_step_for_request(
    request: dict[str, Any],
    steps: list[Any],
    used_step_indexes: set[int],
) -> tuple[int, Any | None]:
    tool_name = str(request.get("tool") or "").strip()
    if not tool_name:
        return -1, None
    for index, step in enumerate(steps):
        if index in used_step_indexes:
            continue
        if str(getattr(step, "tool_name", "") or "").strip() == tool_name:
            return index, step
    return -1, None


def _attach_legacy_request_planner_trace(
    request: dict[str, Any],
    planner_decision: Any,
    step: Any,
) -> None:
    step_id = str(getattr(step, "step_id", "") or "").strip()
    capability_id = str(getattr(step, "capability_id", "") or "").strip()
    if step_id:
        request.setdefault("step_id", step_id)
        request.setdefault("planner_step_id", step_id)
    if capability_id:
        request.setdefault("capability_id", capability_id)
    decision_id = str(getattr(planner_decision, "decision_id", "") or "").strip()
    plan = getattr(planner_decision, "plan", None)
    plan_id = str(getattr(plan, "plan_id", "") or "").strip()
    tool_plan = getattr(plan, "tool_plan", None)
    tool_plan_id = str(getattr(tool_plan, "plan_id", "") or "").strip()
    intent = getattr(planner_decision, "selected_intent", None)
    intent_kind = str(getattr(intent, "kind", "") or "").strip()
    task_core = getattr(plan, "task_core", None)
    workspace = getattr(task_core, "workspace", None)
    for key, value in (
        ("decision_id", decision_id),
        ("plan_id", plan_id),
        ("tool_plan_id", tool_plan_id),
        ("intent_kind", intent_kind),
        ("core_id", str(getattr(task_core, "core_id", "") or "").strip()),
        ("workspace_id", str(getattr(workspace, "workspace_id", "") or "").strip()),
    ):
        if value:
            request.setdefault(key, value)


def _approval_first_selection_payload(
    payload: dict[str, Any],
    selected_requests: list[dict[str, Any]],
) -> dict[str, Any]:
    if not selected_requests:
        return payload
    approval_tool = next(
        (
            str(request.get("tool") or "").strip()
            for request in selected_requests
            if str(request.get("tool") or "").strip() in _APPROVAL_PLAN_TOOLS
        ),
        "",
    )
    if not approval_tool:
        return payload
    return {
        **payload,
        "selected_tools": [approval_tool],
        "selected_request_count": 1,
    }


def _prepend_legacy_focus_app_search_discovery_request(
    prompt: str,
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requests or any(request.get("tool") == "desktop.list_apps" for request in requests):
        return requests
    if not re.search(r"(?:切到|聚焦|focus|switch\s+to)", str(prompt or ""), flags=re.IGNORECASE):
        return requests
    if not re.search(r"(?:搜索|查找|检索|找|search|find|look)", str(prompt or ""), flags=re.IGNORECASE):
        return requests
    app_name = ""
    for request in requests:
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        if str(request.get("tool") or "").strip() in {"app.focus", "app.open"}:
            app_name = str(payload.get("app_name") or "").strip()
            break
    if not app_name:
        return requests
    first = requests[0]
    discovery = {
        "protocol": "json_fallback",
        "tool": "desktop.list_apps",
        "input": {"query": app_name, "limit": 20},
        "source": str(first.get("source") or "runtime_planner"),
        "planning_reason": str(first.get("planning_reason") or "planner_desktop_operation"),
    }
    return [discovery, *requests]


def _coalesce_legacy_direct_app_shortcut_requests(
    prompt: str,
    requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    allowed = {str(tool or "").strip() for tool in allowed_tools}
    if not requests or not (
        {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"} & allowed
    ):
        return requests
    if _has_discovered_runtime_planner_verification_chain(requests):
        return requests
    if not (
        _explicit_open_prompt(prompt)
        or _search_field_prompt(prompt)
        or _has_non_search_app_shortcut_pair(requests)
    ):
        return requests
    coalesced: list[dict[str, Any]] = []
    index = 0
    while index < len(requests):
        request = requests[index]
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in {"app.open", "app.focus"}:
            coalesced.append(request)
            index += 1
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        app_name = str(payload.get("app_name") or "").strip()
        combined_tool = (
            "app.open_and_safe_shortcut"
            if tool_name == "app.open"
            else "app.focus_and_safe_shortcut"
        )
        if not app_name or combined_tool not in allowed:
            coalesced.append(request)
            index += 1
            continue
        shortcut_index = index + 1
        if (
            tool_name == "app.open"
            and shortcut_index < len(requests)
            and str(requests[shortcut_index].get("tool") or "").strip() == "app.focus"
        ):
            focus_payload = (
                requests[shortcut_index].get("input")
                if isinstance(requests[shortcut_index].get("input"), dict)
                else {}
            )
            if str(focus_payload.get("app_name") or "").strip() == app_name:
                shortcut_index += 1
        if shortcut_index >= len(requests):
            coalesced.append(request)
            index += 1
            continue
        shortcut_request = requests[shortcut_index]
        if str(shortcut_request.get("tool") or "").strip() != "desktop.safe_shortcut":
            coalesced.append(request)
            index += 1
            continue
        shortcut_payload = (
            shortcut_request.get("input")
            if isinstance(shortcut_request.get("input"), dict)
            else {}
        )
        action = str(shortcut_payload.get("action") or "").strip()
        if not action:
            coalesced.append(request)
            index += 1
            continue
        coalesced.append(
            {
                "protocol": request.get("protocol") or "json_fallback",
                "tool": combined_tool,
                "input": {"app_name": app_name, "action": action},
                "source": request.get("source") or shortcut_request.get("source") or "runtime_planner",
                "planning_reason": (
                    shortcut_request.get("planning_reason")
                    or request.get("planning_reason")
                    or "planner_desktop_operation"
                ),
            }
        )
        index = shortcut_index + 1
    return coalesced


def _split_redundant_app_safe_shortcut_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if not requests:
        return requests
    prepared_apps: set[str] = set()
    updated: list[dict[str, Any]] = []
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        app_name = str(payload.get("app_name") or "").strip()
        if tool_name in {"app.open", "app.focus", "desktop.open_app", "desktop.focus_app"}:
            if app_name:
                prepared_apps.add(app_name)
            updated.append(request)
            continue
        if (
            tool_name in {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"}
            and app_name
            and app_name in prepared_apps
        ):
            action = str(payload.get("action") or "").strip()
            if action:
                updated.append(
                    {
                        **request,
                        "tool": "desktop.safe_shortcut",
                        "input": {"action": action},
                    }
                )
                continue
        updated.append(request)
    return updated


def _has_discovered_runtime_planner_verification_chain(
    requests: list[dict[str, Any]],
) -> bool:
    if not any(str(request.get("source") or "").strip() == "runtime_planner" for request in requests):
        return False
    if not _has_unknown_discovered_app_query(requests):
        return False
    has_app_shortcut_pair = False
    for index, request in enumerate(requests[:-1]):
        if str(request.get("tool") or "").strip() not in {"app.open", "app.focus"}:
            continue
        for later_request in requests[index + 1 :]:
            if str(later_request.get("tool") or "").strip() == "desktop.safe_shortcut":
                has_app_shortcut_pair = True
                break
        if has_app_shortcut_pair:
            break
    if not has_app_shortcut_pair:
        return False
    return any(_legacy_direct_verify_request(request) for request in requests)


def _has_unknown_discovered_app_query(requests: list[dict[str, Any]]) -> bool:
    for request in requests:
        if str(request.get("tool") or "").strip() != "desktop.list_apps":
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        query = str(payload.get("query") or "").strip()
        if query and not is_legacy_app_name_hint(query):
            return True
    return False


def _has_non_search_app_shortcut_pair(requests: list[dict[str, Any]]) -> bool:
    for index, request in enumerate(requests[:-1]):
        if str(request.get("tool") or "").strip() not in {"app.open", "app.focus"}:
            continue
        shortcut = requests[index + 1]
        if str(shortcut.get("tool") or "").strip() != "desktop.safe_shortcut":
            continue
        payload = shortcut.get("input") if isinstance(shortcut.get("input"), dict) else {}
        action = str(payload.get("action") or "").strip()
        if action and action != "find":
            return True
    return False


def _explicit_open_prompt(prompt: str) -> bool:
    return bool(
        re.search(
            r"(?:打开|启动|开启|运行|拉起|open|launch|start)",
            str(prompt or ""),
            flags=re.IGNORECASE,
        )
    )


def _search_field_prompt(prompt: str) -> bool:
    return bool(
        re.search(
            r"(?:搜索框|搜索栏|搜索输入框|搜索输入栏|search\s+(?:field|box|bar|input))",
            str(prompt or ""),
            flags=re.IGNORECASE,
        )
    )


def _legacy_direct_verify_request(request: dict[str, Any]) -> bool:
    return str(request.get("tool") or "").strip() in {
        "desktop.ui_elements",
        "desktop.inspect_app",
        "desktop.active_window",
        "desktop.running_apps",
        "screen.capture",
    }


def _has_approval_plan_tool(tool_requests: list[dict[str, Any]]) -> bool:
    return any(
        isinstance(request, dict)
        and (
            str(request.get("tool") or "").strip() in _APPROVAL_PLAN_TOOLS
            or request.get("approval_required") is True
        )
        for request in tool_requests
    )


def _has_explicit_hotkey_safe_shortcut(
    prompt: str,
    tool_requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> bool:
    if not hotkey_hint(prompt):
        return False
    allowed = {str(tool or "").strip() for tool in allowed_tools}
    for request in tool_requests:
        if not isinstance(request, dict):
            continue
        tool_name = str(request.get("tool") or "").strip()
        approval_tool = _SAFE_SHORTCUT_APPROVAL_TOOLS.get(tool_name, "")
        if not approval_tool or approval_tool not in allowed:
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        if str(payload.get("action") or "").strip() == "focus_address_bar":
            return True
    return False


def _group_artifacts(runs: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.group_artifacts(runs)


def _group_run_from_legacy_run_group(
    run_group: dict[str, Any],
    runtime: Any,
) -> dict[str, Any]:
    return _LEGACY_RUN_PROJECTOR.group_run_from_legacy_run_group(run_group, runtime)


def _child_runs_for_run_group(run_group: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
    return _LEGACY_RUN_PROJECTOR.child_runs_for_run_group(run_group, runtime)
