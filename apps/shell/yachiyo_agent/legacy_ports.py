"""Ports backed by the existing Agent runtime surface."""

from __future__ import annotations

import re

from collections.abc import Mapping
from typing import Any

from apps.shell.chat_api import ChatAPI
from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.approval_tool_sets import (
    APPROVAL_PLAN_TOOLS as _APPROVAL_PLAN_TOOLS,
    SAFE_SHORTCUT_APPROVAL_TOOLS as _SAFE_SHORTCUT_APPROVAL_TOOLS,
)
from apps.shell.agent.runtime.direct_request_policy import (
    approval_required_policy_from_direct_requests,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError

from .daily_desktop import (
    daily_desktop_allowed_tools,
    daily_desktop_direct_metadata_request,
    daily_desktop_entrypoint_requests,
    daily_desktop_executable_entrypoint_requests,
    daily_desktop_planned_timeline,
    daily_desktop_recovery_execution_prompt,
    direct_browser_entrypoint_requests,
    entrypoint_plan_user_metadata,
    main_chat_entrypoint_allowed_tools,
    planner_first_daily_desktop_entrypoint_requests,
)
from .app_name_hints import is_legacy_app_name_hint
from .desktop_permissions import (
    desktop_permission_missing_by_capability,
    desktop_runtime_blocking_conditions_by_capability,
)
from .desktop_execution_policy import sandbox_desktop_provider_status
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
    planner_execution_tool_requests,
    planner_tool_requests,
)
from .recovery_actions import (
    RECOVERY_RETRY_CONTEXT_EVENT_TYPE,
    recovery_retry_context_payload,
)
from .runtime_execution import (
    runtime_execution_envelope_payload_with_request_context,
    runtime_execution_requests_from_envelope_payload,
    runtime_execution_requests_from_metadata,
)
from .runtime_progress import (
    task_progress_event_payloads_for_tool_result,
    task_replan_event_payloads_for_tool_result,
)
from .controlled_provider_diagnostics import controlled_desktop_provider_diagnostics_payload
from .groups import group_run_snapshot_from_payload
from .isolated_provider_session import (
    annotate_envelope_with_desktop_provider_session,
    ensure_isolated_desktop_provider_session_for_envelope,
    isolated_desktop_provider_session_status,
    start_isolated_desktop_provider_session,
    stop_isolated_desktop_provider_session,
)
from .tool_catalog import runtime_tool_catalog_snapshot
from .workflow_run_snapshots import workflow_run_snapshot_from_payload

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
    continuation_tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if bool(request.get("continue_to_model"))
    ]
    if continuation_tools and not (
        _primary_tool_names_for_requests(requests)
        and all(tool in _DAILY_DESKTOP_METADATA_VERIFY_TOOLS for tool in continuation_tools)
    ):
        return True
    tools = set(_tool_names_for_requests(requests))
    return bool(tools) and tools <= {"desktop.ui_elements", "screen.capture"}


def _tool_names_for_requests(requests: list[dict[str, Any]]) -> list[str]:
    return [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("tool") or "").strip()
    ]


def _planner_requests_cover_legacy_plan(
    legacy_requests: list[dict[str, Any]],
    planner_requests: list[dict[str, Any]],
) -> bool:
    legacy_tools = _primary_tool_names_for_requests(legacy_requests)
    planner_tools = _primary_tool_names_for_requests(planner_requests)
    if not legacy_tools or not planner_tools:
        return False
    if _planner_requests_need_model_followup(planner_requests):
        return False
    legacy_families = {_tool_family(tool) for tool in legacy_tools}
    planner_families = {_tool_family(tool) for tool in planner_tools}
    return bool(legacy_families) and legacy_families <= planner_families


def _primary_tool_names_for_requests(requests: list[dict[str, Any]]) -> list[str]:
    non_primary = _DAILY_DESKTOP_METADATA_DISCOVERY_TOOLS | _DAILY_DESKTOP_METADATA_VERIFY_TOOLS
    return [
        tool
        for tool in _tool_names_for_requests(requests)
        if tool not in non_primary
    ]


def _tool_family(tool_name: str) -> str:
    if tool_name.startswith("media."):
        return "media"
    if tool_name.startswith("browser."):
        return "browser"
    if tool_name.startswith("clipboard."):
        return "clipboard"
    if tool_name.startswith("system."):
        return "system"
    if tool_name.startswith(("app.", "desktop.")):
        return "desktop"
    if tool_name.startswith("file."):
        return "file"
    if tool_name.startswith("artifact."):
        return "artifact"
    return tool_name.split(".", 1)[0]


def _visible_daily_desktop_metadata_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    requests = _metadata_requests_with_split_app_shortcuts(requests)
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


def _metadata_requests_with_split_app_shortcuts(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    expanded: list[dict[str, Any]] = []
    for request in requests:
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"}:
            expanded.append(request)
            continue
        payload = request.get("input") if isinstance(request.get("input"), dict) else {}
        app_name = str(payload.get("app_name") or "").strip()
        action = str(payload.get("action") or "").strip()
        if action in {"new_document", "new_note", "new_task"}:
            expanded.append(request)
            continue
        if not app_name or not action:
            expanded.append(request)
            continue
        expanded.append(
            {
                **request,
                "tool": "app.open" if tool_name == "app.open_and_safe_shortcut" else "app.focus",
                "input": {"app_name": app_name},
            }
        )
        expanded.append(
            {
                **request,
                "tool": "desktop.safe_shortcut",
                "input": {"action": action},
            }
        )
    return expanded


def _drop_nonblocking_trailing_verify_requests(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(requests) <= 1:
        return requests
    last_primary = -1
    for index, request in enumerate(requests):
        tool_name = str(request.get("tool") or "").strip()
        if (
            tool_name
            and tool_name not in _DAILY_DESKTOP_METADATA_DISCOVERY_TOOLS
            and tool_name not in _DAILY_DESKTOP_METADATA_VERIFY_TOOLS
        ):
            last_primary = index
    if last_primary < 0:
        return requests
    primary_tool = str(requests[last_primary].get("tool") or "").strip()
    if not (
        primary_tool.startswith("media.")
        or primary_tool in {
            "app.open",
            "desktop.open_app",
            "app.focus",
            "desktop.focus_app",
            "app.show",
        }
    ):
        return requests
    trailing = requests[last_primary + 1 :]
    if not trailing:
        return requests
    if any(
        str(request.get("tool") or "").strip()
        not in _DAILY_DESKTOP_METADATA_VERIFY_TOOLS
        for request in trailing
    ):
        return requests
    return requests[: last_primary + 1]


def _allow_nonblocking_trailing_verify_without_model(
    requests: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    if len(requests) <= 1:
        return requests
    last_primary = -1
    for index, request in enumerate(requests):
        tool_name = str(request.get("tool") or "").strip()
        if (
            tool_name
            and tool_name not in _DAILY_DESKTOP_METADATA_DISCOVERY_TOOLS
            and tool_name not in _DAILY_DESKTOP_METADATA_VERIFY_TOOLS
        ):
            last_primary = index
    if last_primary < 0:
        return requests
    trailing = requests[last_primary + 1 :]
    if not trailing:
        return requests
    if any(
        str(request.get("tool") or "").strip()
        not in _DAILY_DESKTOP_METADATA_VERIFY_TOOLS
        for request in trailing
    ):
        return requests
    updated: list[dict[str, Any]] = []
    for index, request in enumerate(requests):
        item = dict(request)
        if index > last_primary:
            item.pop("continue_to_model", None)
        updated.append(item)
    return updated


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


def _expose_runtime_planner_user_metadata(
    requests: list[dict[str, Any]],
    existing_user_metadata: dict[str, Any] | None,
) -> bool:
    if _prefer_execution_requests_for_metadata(existing_user_metadata):
        return True
    if _legacy_daily_desktop_metadata_compat(
        requests,
        existing_user_metadata,
    ) and not _all_requests_from_runtime_planner(requests):
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
        "calendar.create_event",
        "notes.create",
        "reminders.create",
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


def _all_requests_from_runtime_planner(requests: list[dict[str, Any]]) -> bool:
    if not requests:
        return False
    return all(
        str(request.get("source") or "").strip() == "runtime_planner"
        for request in requests
        if isinstance(request, dict)
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
        if str(request.get("group_id") or request.get("agent_group_id") or "").strip():
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
                runtime_execution_envelope=request.get("runtime_execution_envelope"),
                direct_tool_request=request.get("direct_tool_request"),
                direct_tool_requests=request.get("direct_tool_requests"),
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
                runtime=self._runtime,
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
            runtime=self._runtime,
        )

    def execute_existing_main_chat_task(
        self,
        *,
        task_id: str,
        conversation_id: str,
        prompt: str,
        metadata: dict[str, Any] | None = None,
        runtime_execution_envelope: Any | None = None,
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any] | None:
        return self._execute_main_daily_desktop_task(
            task_id=task_id,
            conversation_id=conversation_id,
            prompt=prompt,
            metadata=metadata,
            runtime_execution_envelope=runtime_execution_envelope,
            direct_tool_request=direct_tool_request,
            direct_tool_requests=direct_tool_requests,
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
        legacy_timeline_requests: list[dict[str, Any]] = []
        if _prefer_legacy_planned_timeline_for_metadata(metadata):
            legacy_timeline_requests = daily_desktop_entrypoint_requests(
                prompt,
                metadata=metadata,
                allowed_tools=allowed_daily_desktop_tools,
            )
        planned_requests = planner_first_daily_desktop_entrypoint_requests(
            prompt,
            metadata=metadata,
            allowed_tools=allowed_entrypoint_tools,
            metadata_allowed_tools=allowed_daily_desktop_tools,
            execution_normalized=True,
            include_runtime_context=True,
        )
        if legacy_timeline_requests and not _planner_requests_cover_legacy_plan(
            legacy_timeline_requests,
            planned_requests,
        ):
            return daily_desktop_planned_timeline(
                prompt,
                requests=legacy_timeline_requests,
                metadata=metadata,
                allowed_tools=allowed_entrypoint_tools,
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
        runtime_execution_envelope: Any | None = None,
        direct_tool_request: Any | None = None,
        direct_tool_requests: Any | None = None,
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
        explicit_direct_tool_request = _explicit_direct_tool_request(
            direct_tool_request,
            allowed_entrypoint_tools,
        )
        explicit_direct_tool_requests = _explicit_direct_tool_requests(
            direct_tool_requests,
            allowed_entrypoint_tools,
        )
        direct_tool_request = explicit_direct_tool_request or daily_desktop_direct_metadata_request(
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
            )
            planner_decision = selection.decision
            selection_requests = selection.requests
            selected_source = selection.selected_source
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
            if isinstance(runtime_execution_envelope, Mapping) and direct_tool_selection_payload:
                direct_tool_selection_payload.setdefault(
                    "runtime_execution_envelope",
                    dict(runtime_execution_envelope),
                )
            explicit_runtime_execution_envelope = _has_explicit_runtime_execution_envelope(
                runtime_execution_envelope,
                metadata,
            )
            envelope_tool_requests = _safe_runtime_execution_envelope_requests(
                prompt or execution_prompt,
                metadata,
                allowed_entrypoint_tools,
                runtime_execution_envelope=runtime_execution_envelope,
                selected_requests=(
                    [] if explicit_runtime_execution_envelope else selected_requests
                ),
            )
            if explicit_direct_tool_requests:
                direct_tool_requests = explicit_direct_tool_requests
            elif envelope_tool_requests:
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
            if direct_tool_request:
                annotated_request = _direct_tool_requests_with_desktop_provider_session(
                    [direct_tool_request],
                    metadata=metadata,
                )
                if annotated_request:
                    direct_tool_request = annotated_request[0]
            if direct_tool_requests:
                direct_tool_requests = _direct_tool_requests_with_desktop_provider_session(
                    direct_tool_requests,
                    metadata=metadata,
                )
            if direct_tool_requests and direct_tool_selection_payload:
                direct_tool_selection_payload = _selection_payload_with_selected_requests(
                    direct_tool_selection_payload,
                    direct_tool_requests,
                )
                direct_tool_selection_payload = _approval_first_selection_payload(
                    direct_tool_selection_payload,
                    direct_tool_requests,
                )
            elif direct_tool_request and direct_tool_selection_payload:
                direct_tool_selection_payload = _selection_payload_with_selected_requests(
                    direct_tool_selection_payload,
                    [direct_tool_request],
                )
        if not task_id:
            return None
        if not direct_tool_request and not selected_requests and not direct_tool_requests:
            return None
        if direct_tool_request:
            metadata_tool_requests = [direct_tool_request]
        elif direct_tool_requests:
            metadata_tool_requests = direct_tool_requests
        elif _prefer_execution_requests_for_metadata(metadata):
            metadata_tool_requests = (
                planner_execution_tool_requests(
                    selected_requests,
                    allowed_entrypoint_tools,
                )
                or selected_requests
            )
        else:
            metadata_tool_requests = selected_requests
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
            effective_runtime_execution_envelope = _main_chat_runtime_execution_envelope(
                runtime_execution_envelope,
                metadata,
                direct_tool_selection_payload,
            )
            start_kwargs: dict[str, Any] = {
                "task_id": task_id,
                "session_id": conversation_id,
                "user_goal": prompt or execution_prompt,
            }
            if supports_keyword(start_main_chat_run, "metadata"):
                start_kwargs["metadata"] = metadata
            if (
                direct_tool_request is not None
                and supports_keyword(start_main_chat_run, "direct_tool_request")
            ):
                start_kwargs["direct_tool_request"] = direct_tool_request
            if (
                direct_tool_requests
                and supports_keyword(start_main_chat_run, "direct_tool_requests")
            ):
                start_kwargs["direct_tool_requests"] = direct_tool_requests
            effective_runtime_execution_envelope = (
                _runtime_execution_envelope_with_desktop_provider_session(
                    effective_runtime_execution_envelope,
                    direct_tool_request=direct_tool_request,
                    direct_tool_requests=direct_tool_requests,
                )
            )
            if (
                effective_runtime_execution_envelope is not None
                and supports_keyword(start_main_chat_run, "runtime_execution_envelope")
            ):
                start_kwargs["runtime_execution_envelope"] = (
                    effective_runtime_execution_envelope
                )
            run = start_main_chat_run(**start_kwargs)
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
            model_loop_kwargs = {
                "direct_tool_request": direct_tool_request,
                "direct_tool_requests": direct_tool_requests,
            }
            if (
                effective_runtime_execution_envelope is not None
                and supports_keyword(execute_main_chat_model_loop, "runtime_execution_envelope")
            ):
                model_loop_kwargs["runtime_execution_envelope"] = (
                    effective_runtime_execution_envelope
                )
            if supports_keyword(execute_main_chat_model_loop, "runtime_execution_metadata"):
                model_loop_kwargs["runtime_execution_metadata"] = metadata
            tool_policy = _main_chat_direct_request_tool_policy(
                direct_tool_request,
                direct_tool_requests,
            )
            if tool_policy and supports_keyword(execute_main_chat_model_loop, "tool_policy"):
                model_loop_kwargs["tool_policy"] = tool_policy
            run = execute_main_chat_model_loop(
                run_id,
                [{"role": "user", "content": execution_prompt or prompt or "执行恢复后的原操作"}],
                **model_loop_kwargs,
            )
            self._append_runtime_tool_progress_events(
                run_id,
                run,
                direct_tool_request=direct_tool_request,
                direct_tool_requests=direct_tool_requests,
                planner_decision=planner_decision,
                task_id=task_id,
            )
            status = str(run.get("status") or "").strip()
            result_text = str(run.get("result") or "").strip()
            if status == "approval_required":
                pending_approval = (
                    run.get("pending_approval")
                    if isinstance(run.get("pending_approval"), dict)
                    else {}
                )
                self._sync_chat_assistant_message(
                    task_id,
                    conversation_id,
                    "等待你在 Agent Studio 中审批后继续。",
                    status="processing",
                    metadata={
                        "run_status": "approval_required",
                        "agent_run_id": run_id,
                        "run_id": run_id,
                        "pending_approval": pending_approval,
                    },
                )
                return self._projector.chat_task_payload(
                    {**run, "task_id": task_id, "session_id": conversation_id},
                    conversation_id=conversation_id,
                    runtime=self._runtime,
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
                    runtime=self._runtime,
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
                runtime=self._runtime,
            )
        except Exception as exc:
            failed_run: dict[str, Any] | None = None
            if run_id:
                fail_main_chat_run = getattr(self._runtime, "fail_main_chat_run", None)
                if callable(fail_main_chat_run):
                    try:
                        failed = fail_main_chat_run(run_id, exc)
                        if isinstance(failed, dict):
                            failed_run = failed
                    except Exception:
                        pass
            error_text = str(exc)
            self._sync_app_task_failed(task_id, error_text)
            self._sync_chat_assistant_message(
                task_id,
                conversation_id,
                error_text,
                status="failed",
                error=error_text,
            )
            if run_id:
                return self._projector.chat_task_payload(
                    {
                        **(failed_run or {}),
                        "run_id": run_id,
                        "task_id": task_id,
                        "session_id": conversation_id,
                        "status": str((failed_run or {}).get("status") or "failed"),
                        "result": str((failed_run or {}).get("result") or error_text),
                    },
                    conversation_id=conversation_id,
                    runtime=self._runtime,
                )
            return None

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

    def _append_runtime_tool_progress_events(
        self,
        run_id: str,
        run_payload: dict[str, Any],
        *,
        direct_tool_request: dict[str, Any] | None,
        direct_tool_requests: list[dict[str, Any]],
        planner_decision: Any | None,
        task_id: str,
    ) -> None:
        append_run_event = getattr(self._runtime, "append_run_event", None)
        if not run_id or not callable(append_run_event):
            return
        requests = _direct_tool_request_sequence(
            direct_tool_request,
            direct_tool_requests,
            run_id=run_id,
            task_id=task_id,
        )
        if not requests:
            return
        timeline = _run_event_timeline_for_progress(
            self._runtime,
            run_id,
            run_payload,
        )
        tool_events = _runtime_tool_events_for_progress(timeline)
        if not tool_events:
            return
        used_event_indexes: set[int] = set()
        for request in requests:
            match = _matching_runtime_tool_event(
                request,
                tool_events,
                used_event_indexes,
            )
            if match is None:
                continue
            event_index, tool_event = match
            used_event_indexes.add(event_index)
            for payload in task_progress_event_payloads_for_tool_result(
                tool_request=request,
                tool_event=tool_event,
                existing_timeline=timeline,
            ):
                event_type = str(payload.get("event") or payload.get("event_type") or "").strip()
                if not event_type:
                    continue
                append_run_event(run_id, event_type, _event_payload_for_append(payload))
                timeline.append(dict(payload))
            if planner_decision is None:
                continue
            for payload in task_replan_event_payloads_for_tool_result(
                planner_decision,
                tool_request=request,
                tool_event=tool_event,
                run_id=run_id,
                task_id=task_id,
            ):
                event_type = str(payload.get("event") or payload.get("event_type") or "").strip()
                if not event_type:
                    continue
                append_payload = _event_payload_for_append(payload)
                if _runtime_replan_event_recorded(timeline, event_type, append_payload):
                    continue
                append_run_event(run_id, event_type, append_payload)
                timeline.append(dict(payload))

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
        metadata: dict[str, Any] | None = None,
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
                metadata=metadata,
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
        sandbox_provider = sandbox_desktop_provider_status(
            {
                "desktop_provider_health_probe": True,
                "desktop_provider_local_native": True,
            }
        )
        return runtime_tool_catalog_snapshot(
            missing_permissions=missing_permissions,
            blocking_conditions=blocking_conditions,
            plugin_states=plugin_states,
            sandbox_provider=sandbox_provider,
            controlled_provider_diagnostics=controlled_desktop_provider_diagnostics_payload(
                sandbox_provider=sandbox_provider
            ),
        ).model_dump(mode="json")

    def desktop_provider_session_status(self) -> dict[str, Any]:
        return isolated_desktop_provider_session_status()

    def start_desktop_provider_session(self, request: dict[str, Any]) -> dict[str, Any]:
        return start_isolated_desktop_provider_session(request)

    def stop_desktop_provider_session(self) -> dict[str, Any]:
        return stop_isolated_desktop_provider_session()

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
        allowed_tools = _agent_allowed_tools(self._runtime, agent_id)
        planner_decision = runtime_planner_decision(
            user_goal,
            allowed_tools=allowed_tools,
            metadata=planner_metadata,
        )
        run_payload: dict[str, Any] = {
            "agent_id": agent_id,
            "user_goal": user_goal,
            "source": "yachiyo_studio",
            "client_run_id": request.get("client_run_id"),
            "run_group_id": request.get("run_group_id"),
            "daily_desktop_policy_overlay": True,
            "runtime_planner_entrypoint": True,
        }
        if metadata:
            run_payload["metadata"] = dict(metadata)
        runtime_execution_envelope = request.get("runtime_execution_envelope")
        if runtime_execution_envelope is None and isinstance(
            metadata.get("yachiyo_execution_envelope"),
            Mapping,
        ):
            runtime_execution_envelope = metadata.get("yachiyo_execution_envelope")
        if isinstance(runtime_execution_envelope, Mapping):
            runtime_execution_envelope = runtime_execution_envelope_payload_with_request_context(
                runtime_execution_envelope,
                {"agent_id": str(agent_id or "").strip()},
            )
            run_payload["runtime_execution_envelope"] = dict(runtime_execution_envelope)
            run_metadata = (
                dict(run_payload.get("metadata"))
                if isinstance(run_payload.get("metadata"), dict)
                else {}
            )
            run_metadata["yachiyo_execution_envelope"] = dict(runtime_execution_envelope)
            run_payload["metadata"] = run_metadata
        direct_tool_request = request.get("direct_tool_request")
        if isinstance(direct_tool_request, dict):
            run_payload["direct_tool_request"] = dict(direct_tool_request)
        direct_tool_requests = request.get("direct_tool_requests")
        if isinstance(direct_tool_requests, list):
            run_payload["direct_tool_requests"] = [
                dict(item) for item in direct_tool_requests if isinstance(item, dict)
            ]
        planning_context = str(request.get("daily_desktop_planning_context") or "").strip()
        if planning_context:
            run_payload["daily_desktop_planning_context"] = planning_context
        if "direct_tool_request" not in run_payload and "direct_tool_requests" not in run_payload:
            planner_direct_requests = _planner_direct_tool_requests_for_agent_run(
                planner_decision,
                allowed_tools=allowed_tools,
                metadata=planner_metadata,
                event_context={"agent_id": str(agent_id or "").strip()},
            )
            if planner_direct_requests:
                run_payload["direct_tool_requests"] = planner_direct_requests
                run_payload.setdefault("daily_desktop_planning_context", user_goal)
        run = self._runtime.create_agent_run(run_payload)
        self._append_planner_run_events(
            _run_id_from_payload(run),
            planner_decision,
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
        allowed_tools = _request_allowed_tools(request)
        planner_decision = runtime_planner_decision(
            user_goal,
            allowed_tools=allowed_tools,
            metadata=planner_metadata,
        )
        run_payload = _studio_workflow_run_payload(
            request,
            user_goal=user_goal,
            planner_decision=planner_decision,
            allowed_tools=allowed_tools,
            event_context={
                "workflow_id": str(request.get("workflow_id") or "").strip(),
            },
        )
        run = self._runtime.create_workflow_run(run_payload)
        self._append_planner_run_events(
            _run_id_from_payload(run),
            planner_decision,
            event_context={
                "workflow_id": str(request.get("workflow_id") or "").strip(),
                "workflow_run_id": _run_id_from_payload(run),
            },
        )
        return _run_with_replay_events(run, self._runtime)

    def list_run_timelines(self, limit: int = 50) -> dict[str, Any]:
        return self._runtime.list_runs(limit)

    def get_run_timeline(self, run_id: str) -> dict[str, Any]:
        return _workflow_run_with_child_runs(
            _run_with_replay_events(self._runtime.get_run(run_id), self._runtime),
            self._runtime,
        )

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
        target_run_id = self._run_id_for_run_approval(run_id, decision)
        self._assert_run_approval(target_run_id, decision)
        approved = self._runtime.approve_run_approval(target_run_id)
        return self._timeline_after_child_action(run_id, target_run_id, approved)

    def reject_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | str | None = None,
    ) -> dict[str, Any]:
        target_run_id = self._run_id_for_run_approval(run_id, decision)
        self._assert_run_approval(target_run_id, decision)
        rejected = self._runtime.reject_run_approval(
            target_run_id,
            _rejection_reason(decision),
        )
        return self._timeline_after_child_action(run_id, target_run_id, rejected)

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
        artifact_run_id = _workflow_artifact_source_run_id(
            self._runtime,
            run_id,
            artifact_path,
        ) or run_id
        payload = self._runtime.read_run_artifact(artifact_run_id, artifact_path)
        if artifact_run_id == run_id:
            return payload
        return {
            **payload,
            "run_id": payload.get("run_id") or artifact_run_id,
            "workflow_run_id": payload.get("workflow_run_id") or run_id,
            "path": payload.get("path") or artifact_path,
        }

    def get_run_event_stream(self, run_id: str) -> dict[str, Any]:
        raw_stream = self._runtime.list_run_events(run_id)
        return _workflow_run_events_with_child_replay(
            self._runtime,
            run_id,
            raw_stream,
        )

    def get_run_event_page(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
    ) -> dict[str, Any]:
        if _is_workflow_parent_run_id(self._runtime, run_id):
            return _run_event_page_from_legacy_stream(
                self.get_run_event_stream(run_id),
                run_id=run_id,
                after_sequence=after_sequence,
                limit=limit,
            )
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

    def _run_id_for_run_approval(
        self,
        run_id: str,
        decision: dict[str, Any] | str | None,
    ) -> str:
        requested_approval_id = _approval_id_from_decision(decision)
        try:
            run = self._runtime.get_run(run_id)
        except KeyError:
            return run_id
        if _pending_approval_id(run) and (
            not requested_approval_id
            or _pending_approval_id(run) == requested_approval_id
        ):
            return run_id
        if str(run.get("kind") or "").strip() != "workflow_run":
            return run_id
        child_runs = _workflow_child_runs_for_parent_run(run, self._runtime)
        if requested_approval_id:
            for child in child_runs:
                child_run_id = str(child.get("run_id") or "").strip()
                if child_run_id and _pending_approval_id(child) == requested_approval_id:
                    return child_run_id
            return run_id
        for child in child_runs:
            child_run_id = str(child.get("run_id") or "").strip()
            if child_run_id and _pending_approval_id(child):
                return child_run_id
        return run_id

    def _timeline_after_child_action(
        self,
        run_id: str,
        target_run_id: str,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if target_run_id == run_id:
            return payload
        try:
            return self.get_run_timeline(run_id)
        except KeyError:
            return payload

    def _append_planner_run_events(
        self,
        run_id: str,
        planner_decision: Any | None,
        *,
        event_context: Mapping[str, Any] | None = None,
    ) -> None:
        append_run_event = getattr(self._runtime, "append_run_event", None)
        if not run_id or not callable(append_run_event):
            return
        if _run_has_runtime_planner_events(self._runtime, run_id):
            return
        for event_type, payload in planner_run_event_payloads(planner_decision):
            try:
                append_run_event(
                    run_id,
                    event_type,
                    _planner_event_payload_with_context(payload, event_context),
                )
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


def _planner_event_payload_with_context(
    payload: dict[str, Any],
    event_context: Mapping[str, Any] | None,
) -> dict[str, Any]:
    enriched = dict(payload)
    if not isinstance(event_context, Mapping):
        return enriched
    clean_context = {
        str(key): str(value).strip()
        for key, value in event_context.items()
        if str(key or "").strip() and str(value or "").strip()
    }
    for key, value in clean_context.items():
        enriched.setdefault(key, value)
    envelope = enriched.get("runtime_execution_envelope")
    if isinstance(envelope, Mapping):
        enriched["runtime_execution_envelope"] = (
            runtime_execution_envelope_payload_with_request_context(
                envelope,
                clean_context,
            )
        )
    return enriched


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


def _request_allowed_tools(request: Mapping[str, Any]) -> list[str] | None:
    value = request.get("allowed_tools")
    if not isinstance(value, list):
        return None
    tools = [str(tool or "").strip() for tool in value if str(tool or "").strip()]
    return tools or None


def _planner_direct_tool_requests_for_agent_run(
    planner_decision: Any | None,
    *,
    allowed_tools: list[str] | None,
    metadata: Mapping[str, Any] | None = None,
    event_context: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if planner_decision is None:
        return []
    planner_metadata = runtime_planner_metadata(
        planner_decision,
        allowed_tools=allowed_tools,
        metadata=metadata,
    )
    envelope = planner_metadata.get("yachiyo_execution_envelope")
    if isinstance(envelope, Mapping):
        envelope = runtime_execution_envelope_payload_with_request_context(
            envelope,
            event_context,
        )
    return runtime_execution_requests_from_envelope_payload(
        envelope,
        allowed_tools=allowed_tools,
    )


def _safe_runtime_planner_tool_requests(
    prompt: str,
    allowed_tools: list[str],
    *,
    metadata: dict[str, Any] | None = None,
    selected_requests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    selected_requests = selected_requests or []
    deferred_approval_sequence = _runtime_planner_deferred_ui_approval_sequence_requests(
        selected_requests,
        allowed_tools,
    )
    if deferred_approval_sequence:
        return deferred_approval_sequence
    if _has_approval_plan_tool(selected_requests):
        requests = planner_tool_requests(
            prompt,
            allowed_tools,
            metadata=metadata,
        ) or list(selected_requests)
        raw_approval_sequence = _runtime_planner_direct_approval_sequence_requests(
            requests,
            allowed_tools,
        )
        if raw_approval_sequence:
            if _has_explicit_hotkey_safe_shortcut(prompt, raw_approval_sequence, allowed_tools):
                return []
            return raw_approval_sequence
        requests = _apply_legacy_file_transfer_app_alias(prompt, requests, allowed_tools)
        requests = _apply_legacy_plain_search_open_mode(prompt, requests, allowed_tools)
        requests = _apply_legacy_search_field_target_label(prompt, requests)
        requests = _apply_legacy_return_hotkey_projection(prompt, requests, allowed_tools)
        approval_sequence = _runtime_planner_direct_approval_sequence_requests(
            requests,
            allowed_tools,
        )
        if approval_sequence:
            if _has_explicit_hotkey_safe_shortcut(prompt, approval_sequence, allowed_tools):
                return []
            return approval_sequence
        approval_sequence = _runtime_planner_direct_approval_sequence_requests(
            selected_requests,
            allowed_tools,
        )
        if approval_sequence:
            if _has_explicit_hotkey_safe_shortcut(prompt, approval_sequence, allowed_tools):
                return []
            return approval_sequence
        return []
    if _has_explicit_hotkey_safe_shortcut(prompt, selected_requests, allowed_tools):
        return []
    if selected_requests:
        requests = planner_tool_requests(
            prompt,
            allowed_tools,
            metadata=metadata,
        ) or list(selected_requests)
        direct_browser_requests = direct_browser_entrypoint_requests(requests, prompt)
        if direct_browser_requests:
            requests = direct_browser_requests
        approval_sequence = _runtime_planner_direct_approval_sequence_requests(
            requests,
            allowed_tools,
        )
        if approval_sequence:
            return approval_sequence
        requests = _apply_legacy_file_transfer_app_alias(prompt, requests, allowed_tools)
        requests = _apply_legacy_plain_search_open_mode(prompt, requests, allowed_tools)
        requests = _apply_legacy_search_field_target_label(prompt, requests)
        requests = _apply_legacy_return_hotkey_projection(prompt, requests, allowed_tools)
        requests = _prepend_legacy_focus_app_search_discovery_request(prompt, requests)
        if _has_explicit_hotkey_safe_shortcut(prompt, requests, allowed_tools):
            return []
        approval_sequence = _runtime_planner_direct_approval_sequence_requests(
            requests,
            allowed_tools,
        )
        if approval_sequence:
            return approval_sequence
    requests = _coalesce_legacy_direct_app_shortcut_requests(
        prompt,
        requests,
        allowed_tools,
    )
    requests = _split_redundant_app_safe_shortcut_requests(requests)
    requests = _drop_legacy_open_then_plain_find_submit(prompt, requests)
    execution_requests = planner_execution_tool_requests(requests, allowed_tools) or requests
    execution_requests = _drop_data_analysis_prepare_app_requests(execution_requests)
    return execution_requests


def _runtime_planner_direct_approval_sequence_requests(
    selected_requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    app_ui_approval_plan = _runtime_planner_app_ui_approval_plan(selected_requests)
    app_submit_approval_plan = _runtime_planner_app_submit_approval_plan(selected_requests)
    communication_send_plan = _runtime_planner_communication_send_plan(selected_requests)
    generic_approval_plan = _runtime_planner_generic_approval_plan(selected_requests)
    if not (
        communication_send_plan
        or app_ui_approval_plan
        or app_submit_approval_plan
        or generic_approval_plan
    ):
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools}
    executable = [
        dict(request)
        for request in selected_requests
        if isinstance(request, dict)
        and not _runtime_planner_model_followup_verification_request(request)
    ]
    if not executable:
        return []
    if any(
        not _runtime_planner_direct_approval_tool_allowed(request, allowed)
        for request in executable
    ):
        return []
    if app_ui_approval_plan:
        return executable
    execution_requests = planner_execution_tool_requests(executable, allowed_tools) or executable
    return [
        request
        for request in execution_requests
        if not _runtime_planner_model_followup_verification_request(request)
    ]


def _runtime_planner_generic_approval_plan(
    requests: list[dict[str, Any]],
) -> bool:
    return any(
        isinstance(request, dict)
        and bool(request.get("approval_required"))
        and str(request.get("source") or "").strip() == "runtime_planner"
        for request in requests
    )


def _runtime_planner_direct_approval_tool_allowed(
    request: Mapping[str, Any],
    allowed: set[str],
) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    if not tool_name:
        return False
    if not allowed or tool_name in allowed:
        return True
    return (
        bool(request.get("approval_required"))
        and str(request.get("source") or "").strip() == "runtime_planner"
    )


def _runtime_planner_deferred_ui_approval_sequence_requests(
    selected_requests: list[dict[str, Any]],
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    if not selected_requests:
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    deferred_approval_tools = {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
        "desktop.click_ui_element",
        "desktop.type_into_ui_element",
    }
    has_deferred_approval = False
    for request in selected_requests:
        if not isinstance(request, dict):
            return []
        tool_name = str(request.get("tool") or "").strip()
        if not tool_name or (allowed and tool_name not in allowed):
            return []
        deferred_tool = str(request.get("deferred_tool") or "").strip()
        if deferred_tool:
            if deferred_tool not in deferred_approval_tools:
                return []
            if allowed and deferred_tool not in allowed:
                return []
            if not isinstance(request.get("deferred_input"), dict):
                return []
            if not bool(request.get("continue_to_model")):
                return []
            has_deferred_approval = True
        continuation = request.get("deferred_continuation")
        if isinstance(continuation, list):
            for item in continuation:
                if not isinstance(item, dict):
                    return []
                continuation_tool = str(item.get("tool") or "").strip()
                if not continuation_tool or (allowed and continuation_tool not in allowed):
                    return []
    if not has_deferred_approval:
        return []
    return [dict(request) for request in selected_requests if isinstance(request, dict)]


def _runtime_planner_communication_send_plan(
    requests: list[dict[str, Any]],
) -> bool:
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("planning_reason") or "").strip()
    }
    if reasons != {"planner_fallback_communication_send"}:
        return False
    tools = _tool_names_for_requests(requests)
    return "desktop.submit_foreground" in tools


def _runtime_planner_app_ui_approval_plan(
    requests: list[dict[str, Any]],
) -> bool:
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("planning_reason") or "").strip()
    }
    if reasons not in (
        {"planner_desktop_operation"},
        {"planner_fallback_desktop_operation"},
    ):
        return False
    tools = set(_tool_names_for_requests(requests))
    app_ui_tools = {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
    }
    if not tools & app_ui_tools:
        return False
    allowed_tools = {
        "desktop.inspect_app",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.active_window",
        "app.open",
        "app.focus",
        *app_ui_tools,
    }
    if not tools <= allowed_tools:
        return False
    for request in requests:
        if not isinstance(request, dict):
            return False
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in app_ui_tools:
            continue
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        if not str(payload.get("app_name") or "").strip():
            return False
        if not str(payload.get("target") or "").strip():
            return False
    return True


def _runtime_planner_app_submit_approval_plan(
    requests: list[dict[str, Any]],
) -> bool:
    reasons = {
        str(request.get("planning_reason") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("planning_reason") or "").strip()
    }
    if reasons not in (
        {"planner_desktop_operation"},
        {"planner_fallback_desktop_operation"},
    ):
        return False
    tools = set(_tool_names_for_requests(requests))
    app_shortcut_tools = {
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
    }
    if "desktop.submit_foreground" not in tools or not (tools & app_shortcut_tools):
        return False
    allowed_tools = {
        "desktop.list_apps",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.active_window",
        "desktop.submit_foreground",
        *app_shortcut_tools,
    }
    if not tools <= allowed_tools:
        return False
    for request in requests:
        if not isinstance(request, dict):
            return False
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in app_shortcut_tools:
            continue
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        if not str(payload.get("app_name") or "").strip():
            return False
        if not str(payload.get("action") or "").strip():
            return False
    return True


def _runtime_planner_model_followup_verification_request(
    request: dict[str, Any],
) -> bool:
    tool_name = str(request.get("tool") or "").strip()
    return bool(request.get("continue_to_model")) and tool_name in {
        "desktop.active_window",
        "desktop.read_ui",
        "desktop.ui_elements",
        "desktop.windows",
        "screen.capture",
    }


def _main_chat_runtime_execution_envelope(
    runtime_execution_envelope: Any | None,
    metadata: Mapping[str, Any] | None,
    direct_tool_selection_payload: Mapping[str, Any] | None,
) -> dict[str, Any] | None:
    for envelope in (
        runtime_execution_envelope,
        (
            direct_tool_selection_payload.get("runtime_execution_envelope")
            if isinstance(direct_tool_selection_payload, Mapping)
            else None
        ),
        metadata.get("runtime_execution_envelope") if isinstance(metadata, Mapping) else None,
        metadata.get("yachiyo_execution_envelope") if isinstance(metadata, Mapping) else None,
    ):
        if isinstance(envelope, Mapping):
            return dict(envelope)
    return None


def _has_explicit_runtime_execution_envelope(
    runtime_execution_envelope: Any | None,
    metadata: Mapping[str, Any] | None,
) -> bool:
    return any(
        _runtime_execution_envelope_has_requests(envelope)
        for envelope in (
            runtime_execution_envelope,
            metadata.get("runtime_execution_envelope") if isinstance(metadata, Mapping) else None,
            metadata.get("yachiyo_execution_envelope") if isinstance(metadata, Mapping) else None,
        )
    )


def _runtime_execution_envelope_has_requests(envelope: Any | None) -> bool:
    if not isinstance(envelope, Mapping):
        return False
    requests = envelope.get("requests")
    if not isinstance(requests, list):
        return False
    return any(
        isinstance(request, Mapping)
        and str(request.get("tool") or request.get("tool_name") or "").strip()
        for request in requests
    )


def _safe_runtime_execution_envelope_requests(
    prompt: str,
    metadata: dict[str, Any] | None,
    allowed_tools: list[str],
    *,
    runtime_execution_envelope: Any | None = None,
    selected_requests: list[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    selected_requests = selected_requests or []
    if _has_approval_plan_tool(selected_requests):
        return []
    raw_requests = planner_tool_requests(
        prompt,
        allowed_tools,
        metadata=metadata,
    )
    raw_approval_sequence = _runtime_planner_direct_approval_sequence_requests(
        raw_requests,
        allowed_tools,
    )
    if raw_approval_sequence and not _has_explicit_hotkey_safe_shortcut(
        prompt,
        raw_approval_sequence,
        allowed_tools,
    ):
        return raw_approval_sequence
    if selected_requests:
        return []
    for requests in _runtime_execution_envelope_request_candidates(
        runtime_execution_envelope,
        metadata,
        allowed_tools=allowed_tools,
    ):
        if not requests:
            continue
        if _has_approval_plan_tool(requests):
            continue
        if _has_explicit_hotkey_safe_shortcut(prompt, requests, allowed_tools):
            continue
        requests = _split_redundant_app_safe_shortcut_requests(requests)
        requests = daily_desktop_executable_entrypoint_requests(requests)
        return _allow_nonblocking_trailing_verify_without_model(requests)
    return []


def _runtime_execution_envelope_request_candidates(
    runtime_execution_envelope: Any | None,
    metadata: dict[str, Any] | None,
    *,
    allowed_tools: list[str],
) -> list[list[dict[str, Any]]]:
    candidates: list[list[dict[str, Any]]] = []
    top_level_requests = runtime_execution_requests_from_envelope_payload(
        runtime_execution_envelope,
        allowed_tools=allowed_tools,
    )
    if top_level_requests:
        candidates.append(top_level_requests)
    metadata_requests = runtime_execution_requests_from_metadata(
        metadata,
        allowed_tools=allowed_tools,
    )
    if metadata_requests:
        candidates.append(metadata_requests)
    return candidates


def _studio_workflow_run_payload(
    request: dict[str, Any],
    *,
    user_goal: str,
    planner_decision: Any | None = None,
    allowed_tools: list[str] | None = None,
    event_context: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "workflow_id": request.get("workflow_id"),
        "user_goal": user_goal,
        "source": "yachiyo_studio",
        "client_run_id": request.get("client_run_id"),
        "run_group_id": request.get("run_group_id"),
    }
    metadata = request.get("metadata") if isinstance(request.get("metadata"), dict) else {}
    metadata = dict(metadata)
    had_metadata_envelope = isinstance(metadata.get("yachiyo_execution_envelope"), dict)
    explicit_runtime_envelope = (
        request.get("runtime_execution_envelope") is not None
        or had_metadata_envelope
    )
    if planner_decision is not None:
        for key, value in runtime_planner_metadata(
            planner_decision,
            allowed_tools=allowed_tools,
            metadata=metadata,
        ).items():
            if explicit_runtime_envelope and key in {
                "yachiyo_execution_envelope",
                "yachiyo_execution_requests",
                "yachiyo_execution_request_previews",
            }:
                continue
            metadata.setdefault(key, value)
    if metadata:
        payload["metadata"] = metadata

    envelope = request.get("runtime_execution_envelope")
    envelope_from_metadata = False
    generated_metadata_envelope = (
        not had_metadata_envelope
        and isinstance(metadata.get("yachiyo_execution_envelope"), dict)
    )
    if envelope is None and isinstance(metadata.get("yachiyo_execution_envelope"), dict):
        envelope = metadata.get("yachiyo_execution_envelope")
        envelope_from_metadata = True
    if generated_metadata_envelope and envelope_from_metadata and isinstance(envelope, Mapping):
        envelope = runtime_execution_envelope_payload_with_request_context(
            envelope,
            event_context,
        )
        metadata["yachiyo_execution_envelope"] = dict(envelope)
        payload["metadata"] = metadata
    if envelope is not None:
        payload["runtime_execution_envelope"] = envelope

    direct_tool_requests = _studio_workflow_direct_tool_requests(
        request,
        envelope,
        metadata,
        allowed_tools=allowed_tools,
    )
    if direct_tool_requests:
        payload["direct_tool_requests"] = direct_tool_requests

    planning_context = str(request.get("daily_desktop_planning_context") or "").strip()
    if planning_context:
        payload["daily_desktop_planning_context"] = planning_context
    elif direct_tool_requests or envelope is not None:
        payload["daily_desktop_planning_context"] = user_goal
    return payload


def _studio_workflow_direct_tool_requests(
    request: dict[str, Any],
    runtime_execution_envelope: Any | None,
    metadata: dict[str, Any],
    *,
    allowed_tools: list[str] | None = None,
) -> list[dict[str, Any]]:
    explicit_allowed_tools = allowed_tools or []
    direct_tool_request = _explicit_direct_tool_request(
        request.get("direct_tool_request"),
        explicit_allowed_tools,
    )
    direct_tool_requests = _explicit_direct_tool_requests(
        request.get("direct_tool_requests"),
        explicit_allowed_tools,
    )
    if direct_tool_request:
        return [direct_tool_request, *direct_tool_requests]
    if direct_tool_requests:
        return direct_tool_requests

    envelope_requests = runtime_execution_requests_from_envelope_payload(
        runtime_execution_envelope,
        allowed_tools=allowed_tools,
    )
    if envelope_requests:
        return envelope_requests
    return runtime_execution_requests_from_metadata(
        metadata,
        allowed_tools=allowed_tools,
    )


def _direct_tool_request_sequence(
    direct_tool_request: dict[str, Any] | None,
    direct_tool_requests: list[dict[str, Any]] | None,
    *,
    run_id: str,
    task_id: str,
) -> list[dict[str, Any]]:
    requests: list[dict[str, Any]] = []
    if isinstance(direct_tool_request, dict):
        requests.append(dict(direct_tool_request))
    if isinstance(direct_tool_requests, list):
        requests.extend(
            dict(request)
            for request in direct_tool_requests
            if isinstance(request, dict)
        )
    for request in requests:
        request.setdefault("run_id", run_id)
        request.setdefault("task_id", task_id)
    return requests


def _direct_tool_requests_with_desktop_provider_session(
    direct_tool_requests: list[dict[str, Any]],
    *,
    metadata: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    if not direct_tool_requests:
        return []
    envelope_requests = []
    for index, request in enumerate(direct_tool_requests, start=1):
        if not isinstance(request, dict):
            continue
        tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
        if not tool_name:
            continue
        envelope_request = dict(request)
        envelope_request.setdefault("tool_name", tool_name)
        envelope_request.setdefault("request_id", f"request:{index}:{tool_name}")
        envelope_requests.append(envelope_request)
    if not envelope_requests:
        return [dict(request) for request in direct_tool_requests if isinstance(request, dict)]
    envelope = {"requests": envelope_requests}
    auto_start = _desktop_provider_session_auto_start_requested(metadata)
    try:
        session = ensure_isolated_desktop_provider_session_for_envelope(
            envelope,
            auto_start=auto_start,
        )
    except Exception as exc:
        if not auto_start:
            return [dict(request) for request in direct_tool_requests if isinstance(request, dict)]
        session = _failed_desktop_provider_session_for_envelope(
            envelope_requests,
            exc,
            auto_start=auto_start,
        )
    if not isinstance(session, Mapping):
        return [dict(request) for request in direct_tool_requests if isinstance(request, dict)]
    if not session.get("needed"):
        return [dict(request) for request in direct_tool_requests if isinstance(request, dict)]
    if not (session.get("running") or auto_start):
        return [dict(request) for request in direct_tool_requests if isinstance(request, dict)]
    annotated = annotate_envelope_with_desktop_provider_session(envelope, session)
    annotated_requests = annotated.get("requests") if isinstance(annotated, dict) else None
    if not isinstance(annotated_requests, list):
        return [dict(request) for request in direct_tool_requests if isinstance(request, dict)]
    by_request_id = {
        str(request.get("request_id") or "").strip(): request
        for request in annotated_requests
        if isinstance(request, dict)
    }
    result: list[dict[str, Any]] = []
    for index, request in enumerate(direct_tool_requests, start=1):
        if not isinstance(request, dict):
            continue
        tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
        request_id = str(request.get("request_id") or f"request:{index}:{tool_name}").strip()
        annotated_request = by_request_id.get(request_id)
        if isinstance(annotated_request, dict) and isinstance(
            annotated_request.get("desktop_provider_session"),
            dict,
        ):
            result.append(
                {
                    **dict(request),
                    "desktop_provider_session": dict(
                        annotated_request["desktop_provider_session"]
                    ),
                }
            )
        else:
            result.append(dict(request))
    return result


def _failed_desktop_provider_session_for_envelope(
    envelope_requests: list[dict[str, Any]],
    exc: Exception,
    *,
    auto_start: bool,
) -> dict[str, Any]:
    request_ids = [
        str(request.get("request_id") or "").strip()
        for request in envelope_requests
        if str(request.get("request_id") or "").strip()
    ]
    tool_names = sorted(
        {
            str(request.get("tool_name") or request.get("tool") or "").strip()
            for request in envelope_requests
            if str(request.get("tool_name") or request.get("tool") or "").strip()
        }
    )
    return {
        "ok": False,
        "needed": True,
        "auto_start": bool(auto_start),
        "started": False,
        "running": False,
        "status": "start_failed",
        "error": str(exc),
        "reason": "isolated_provider_start_failed",
        "source": "isolated_provider_session_manager",
        "request_ids": request_ids,
        "tool_names": tool_names,
        "desktop_session_kind": "isolated_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "keyboard_mouse_capture_supported": True,
    }


def _runtime_execution_envelope_with_desktop_provider_session(
    runtime_execution_envelope: Any | None,
    *,
    direct_tool_request: Mapping[str, Any] | None = None,
    direct_tool_requests: list[dict[str, Any]] | None = None,
) -> dict[str, Any] | None:
    if not isinstance(runtime_execution_envelope, Mapping):
        return None
    session = _desktop_provider_session_from_direct_requests(
        direct_tool_request=direct_tool_request,
        direct_tool_requests=direct_tool_requests,
    )
    if not session:
        return dict(runtime_execution_envelope)
    payload = dict(runtime_execution_envelope)
    payload.setdefault("desktop_provider_session", dict(session))
    return payload


def _desktop_provider_session_from_direct_requests(
    *,
    direct_tool_request: Mapping[str, Any] | None = None,
    direct_tool_requests: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    candidates: list[Mapping[str, Any]] = []
    if isinstance(direct_tool_request, Mapping):
        candidates.append(direct_tool_request)
    candidates.extend(
        request
        for request in direct_tool_requests or []
        if isinstance(request, Mapping)
    )
    for request in candidates:
        session = request.get("desktop_provider_session")
        if isinstance(session, Mapping):
            return dict(session)
    return {}


def _desktop_provider_session_auto_start_requested(
    metadata: Mapping[str, Any] | None,
) -> bool:
    return _metadata_truthy(
        metadata,
        "desktop_provider_session_auto_start",
        "desktop_provider_auto_start",
        "auto_start_desktop_provider_session",
        "auto_start_isolated_desktop_provider",
    )


def _metadata_truthy(
    metadata: Mapping[str, Any] | None,
    *keys: str,
) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    for key in keys:
        value = metadata.get(key)
        if value is True:
            return True
        if isinstance(value, str) and value.strip().lower() in {"1", "true", "yes", "on"}:
            return True
    for nested_key in ("metadata", "desktop_execution_policy", "yachiyo_desktop_execution_policy"):
        nested = metadata.get(nested_key)
        if isinstance(nested, Mapping) and nested is not metadata:
            if _metadata_truthy(nested, *keys):
                return True
    return False


def _explicit_direct_tool_request(
    value: Any,
    allowed_tools: list[str],
) -> dict[str, Any] | None:
    requests = _explicit_direct_tool_requests([value], allowed_tools)
    return requests[0] if requests else None


def _main_chat_direct_request_tool_policy(
    direct_tool_request: Any,
    direct_tool_requests: Any,
) -> dict[str, Any]:
    requests: list[dict[str, Any]] = []
    if isinstance(direct_tool_request, dict):
        requests.append(dict(direct_tool_request))
    if isinstance(direct_tool_requests, list):
        requests.extend(
            dict(item) for item in direct_tool_requests if isinstance(item, dict)
        )
    allowed_tools = _tool_names_for_requests(requests)
    approval_required = approval_required_policy_from_direct_requests(requests)
    if not allowed_tools and not approval_required:
        return {}
    policy: dict[str, Any] = {}
    if allowed_tools:
        policy["allowed_tools"] = allowed_tools
    if approval_required:
        policy["approval_required"] = approval_required
    return policy


def _explicit_direct_tool_requests(
    value: Any,
    allowed_tools: list[str],
) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    allowed = {str(tool or "").strip() for tool in allowed_tools if str(tool or "").strip()}
    requests: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, dict):
            continue
        tool_name = str(item.get("tool") or item.get("tool_name") or "").strip()
        if not tool_name:
            continue
        if allowed and tool_name not in allowed:
            continue
        request = dict(item)
        request["tool"] = tool_name
        requests.append(request)
    return requests


def _run_event_timeline_for_progress(
    runtime: Any,
    run_id: str,
    run_payload: dict[str, Any],
) -> list[dict[str, Any]]:
    timeline = _event_list_from_payload(run_payload)
    list_run_events = getattr(runtime, "list_run_events", None)
    if callable(list_run_events):
        try:
            listed = list_run_events(run_id, after_sequence=0, limit=1000)
        except TypeError:
            try:
                listed = list_run_events(run_id)
            except Exception:
                listed = None
        except Exception:
            listed = None
        if isinstance(listed, Mapping):
            timeline.extend(_event_list_from_payload(dict(listed)))
        elif isinstance(listed, list):
            timeline.extend(item for item in listed if isinstance(item, dict))
    return _dedupe_progress_timeline(timeline)


def _event_list_from_payload(payload: dict[str, Any]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for key in ("timeline", "events", "run_events", "recent_events"):
        value = payload.get(key)
        if isinstance(value, list):
            events.extend(item for item in value if isinstance(item, dict))
    return events


def _dedupe_progress_timeline(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen: set[tuple[str, str, str, str, str]] = set()
    result: list[dict[str, Any]] = []
    for event in events:
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        key = (
            event_type,
            str(event.get("sequence") or "").strip(),
            str(payload.get("detail") or payload.get("tool") or event.get("detail") or event.get("tool") or "").strip(),
            str(payload.get("step_id") or event.get("step_id") or "").strip(),
            str(payload.get("todo_id") or event.get("todo_id") or "").strip(),
        )
        if key in seen:
            continue
        seen.add(key)
        result.append(dict(event))
    return result


def _runtime_tool_events_for_progress(timeline: list[dict[str, Any]]) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    for event in timeline:
        normalized = _normalized_runtime_tool_event(event)
        if normalized is not None:
            events.append(normalized)
    return events


def _normalized_runtime_tool_event(event: dict[str, Any]) -> dict[str, Any] | None:
    event_type = str(event.get("event") or event.get("event_type") or "").strip()
    payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
    if not event_type:
        event_type = str(payload.get("event") or payload.get("event_type") or "").strip()
    if event_type not in {"agent.tool.call", "agent.tool.completed", "agent.tool.failed", "agent.tool.skipped"}:
        return None
    tool_name = str(
        event.get("detail")
        or event.get("tool")
        or event.get("tool_name")
        or payload.get("detail")
        or payload.get("tool")
        or payload.get("tool_name")
        or ""
    ).strip()
    result = _mapping_payload(event.get("result")) or _mapping_payload(payload.get("result"))
    input_preview = (
        _mapping_payload(event.get("input_preview"))
        or _mapping_payload(payload.get("input_preview"))
        or _mapping_payload(event.get("input"))
        or _mapping_payload(payload.get("input"))
    )
    normalized = {
        **dict(payload),
        "event": event_type,
        "detail": tool_name,
        "result": result,
        "input_preview": input_preview,
    }
    for key in (
        "request_id",
        "step_id",
        "planner_step_id",
        "status",
        "approval_required",
        "verification_failed",
    ):
        value = event.get(key, payload.get(key))
        if value not in (None, "", [], {}):
            normalized[key] = value
    return normalized


def _matching_runtime_tool_event(
    request: dict[str, Any],
    tool_events: list[dict[str, Any]],
    used_event_indexes: set[int],
) -> tuple[int, dict[str, Any]] | None:
    request_step = str(request.get("step_id") or request.get("planner_step_id") or "").strip()
    request_id = str(request.get("request_id") or "").strip()
    request_tool = str(request.get("tool") or request.get("tool_name") or "").strip()
    for index, event in enumerate(tool_events):
        if index in used_event_indexes:
            continue
        event_request_id = str(event.get("request_id") or "").strip()
        event_step = str(event.get("step_id") or event.get("planner_step_id") or "").strip()
        event_tool = str(event.get("detail") or event.get("tool") or event.get("tool_name") or "").strip()
        if request_id and event_request_id == request_id:
            return index, event
        if request_step and event_step == request_step:
            return index, event
        if request_tool and event_tool == request_tool:
            return index, event
    return None


def _event_payload_for_append(payload: dict[str, Any]) -> dict[str, Any]:
    event_type = str(payload.get("event") or payload.get("event_type") or "").strip()
    nested_payload = payload.get("payload")
    if event_type.endswith(".replan.requested") and isinstance(nested_payload, Mapping):
        return dict(nested_payload)
    return {
        key: value
        for key, value in payload.items()
        if key not in {"event", "event_type", "detail"}
    }


def _runtime_replan_event_recorded(
    timeline: list[dict[str, Any]],
    event_type: str,
    payload: dict[str, Any],
) -> bool:
    if not event_type.endswith(".replan.requested"):
        return False
    request_id = str(payload.get("request_id") or "").strip()
    source_step_id = str(payload.get("source_step_id") or "").strip()
    trigger = str(payload.get("trigger") or "").strip()
    for event in timeline:
        existing_type = str(event.get("event") or event.get("event_type") or "").strip()
        if existing_type != event_type:
            continue
        existing = event.get("payload") if isinstance(event.get("payload"), dict) else event
        existing_request_id = str(existing.get("request_id") or "").strip()
        if request_id and existing_request_id == request_id:
            return True
        if (
            source_step_id
            and str(existing.get("source_step_id") or "").strip() == source_step_id
            and str(existing.get("trigger") or "").strip() == trigger
        ):
            return True
    return False


def _mapping_payload(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


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
        if _legacy_app_submit_approval_plan(selected_requests):
            return _split_redundant_app_safe_shortcut_requests(selected_requests)
        if _legacy_app_ui_approval_plan(selected_requests):
            return _split_redundant_app_safe_shortcut_requests(selected_requests)
        return []
    if _has_explicit_hotkey_safe_shortcut(prompt, selected_requests, allowed_tools):
        return []
    requests = planner_execution_tool_requests(selected_requests, allowed_tools) or selected_requests
    requests = _split_redundant_app_safe_shortcut_requests(requests)
    return _drop_nonblocking_trailing_verify_requests(requests)


def _legacy_app_submit_approval_plan(
    requests: list[dict[str, Any]],
) -> bool:
    tools = set(_tool_names_for_requests(requests))
    if "desktop.submit_foreground" not in tools:
        return False
    app_shortcut_tools = {"app.open_and_safe_shortcut", "app.focus_and_safe_shortcut"}
    if not tools & app_shortcut_tools:
        return False
    return tools <= {*app_shortcut_tools, "desktop.submit_foreground"}


def _legacy_app_ui_approval_plan(
    requests: list[dict[str, Any]],
) -> bool:
    tools = set(_tool_names_for_requests(requests))
    if not tools:
        return False
    app_ui_tools = {
        "app.open_and_click_ui_element",
        "app.focus_and_click_ui_element",
        "app.open_and_type_into_ui_element",
        "app.focus_and_type_into_ui_element",
    }
    if not tools & app_ui_tools:
        return False
    allowed_tools = {
        "desktop.inspect_app",
        "desktop.ui_elements",
        "desktop.read_ui",
        "desktop.active_window",
        "desktop.hotkey",
        "app.open",
        "app.focus",
        *app_ui_tools,
    }
    if not tools <= allowed_tools:
        return False
    for request in requests:
        if not isinstance(request, dict):
            return False
        tool_name = str(request.get("tool") or "").strip()
        if tool_name not in app_ui_tools:
            continue
        payload = request.get("input") if isinstance(request.get("input"), Mapping) else {}
        if not str(payload.get("app_name") or "").strip():
            return False
        if not str(payload.get("target") or "").strip():
            return False
    return True


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


def _workflow_run_with_child_runs(run: dict[str, Any], runtime: Any) -> dict[str, Any]:
    if str(run.get("kind") or "").strip() != "workflow_run":
        return run
    run_id = str(run.get("run_id") or run.get("workflow_run_id") or "").strip()
    run_group_id = str(run.get("run_group_id") or run.get("group_run_id") or "").strip()
    if not run_id:
        return run
    existing_children = [
        dict(item)
        for item in run.get("runs") or run.get("child_runs") or []
        if isinstance(item, dict)
    ]
    run_group_children: list[dict[str, Any]] = []
    if run_group_id:
        try:
            run_group = runtime.get_run_group(run_group_id)
        except (AttributeError, KeyError):
            run_group = None
        if isinstance(run_group, dict):
            run_group_children = _child_runs_for_run_group(run_group, runtime)
    children = [
        child
        for child in [*existing_children, *run_group_children]
        if str(child.get("run_id") or "").strip()
        and str(child.get("run_id") or "").strip() != run_id
    ]
    if not children:
        return run
    unique_children = []
    seen: set[str] = set()
    for child in children:
        child_run_id = str(child.get("run_id") or "").strip()
        if child_run_id in seen:
            continue
        seen.add(child_run_id)
        unique_children.append(child)
    return {**run, "runs": unique_children}


def _workflow_child_runs_for_parent_run(run: dict[str, Any], runtime: Any) -> list[dict[str, Any]]:
    return [
        dict(item)
        for item in _workflow_run_with_child_runs(run, runtime).get("runs") or []
        if isinstance(item, dict)
    ]


def _is_workflow_parent_run_id(runtime: Any, run_id: str) -> bool:
    try:
        run = runtime.get_run(run_id)
    except (AttributeError, KeyError):
        return False
    workflow_run_id = str(run.get("workflow_run_id") or "").strip()
    return (
        str(run.get("kind") or "").strip() == "workflow_run"
        or bool(workflow_run_id and workflow_run_id == run_id)
    )


def _workflow_run_events_with_child_replay(
    runtime: Any,
    run_id: str,
    raw_stream: Any,
) -> dict[str, Any]:
    parent_events = _events_from_payload(raw_stream)
    try:
        parent = runtime.get_run(run_id)
    except (AttributeError, KeyError):
        parent = {}
    if str(parent.get("kind") or "").strip() != "workflow_run":
        if isinstance(raw_stream, dict):
            return raw_stream
        return {"run_id": run_id, "events": parent_events}

    parent_run_id = str(parent.get("run_id") or parent.get("workflow_run_id") or run_id).strip()
    workflow_id = str(parent.get("workflow_id") or parent.get("runnable_id") or "").strip()
    parent_with_children = _workflow_run_with_child_runs(
        _run_with_replay_events(parent, runtime),
        runtime,
    )
    child_runs = [
        dict(item)
        for item in parent_with_children.get("runs") or []
        if isinstance(item, dict)
    ]
    context_by_child = _workflow_child_context_by_run_id(parent, parent_events)
    events = [dict(event) for event in parent_events]
    for child in child_runs:
        child_run_id = str(child.get("run_id") or "").strip()
        if not child_run_id:
            continue
        child_context = context_by_child.get(child_run_id) or {}
        for event in _events_from_payload(child):
            events.append(
                _workflow_child_replay_event(
                    event,
                    parent_run_id=parent_run_id,
                    workflow_id=workflow_id,
                    child_run_id=child_run_id,
                    context=child_context,
                )
            )

    base = dict(raw_stream) if isinstance(raw_stream, dict) else {}
    return {
        **base,
        "run_id": base.get("run_id") or parent_run_id or run_id,
        "workflow_run_id": base.get("workflow_run_id") or parent_run_id or run_id,
        "workflow_id": base.get("workflow_id") or workflow_id or None,
        "events": _resequence_events(events),
    }


def _workflow_child_context_by_run_id(
    parent: dict[str, Any],
    parent_events: list[dict[str, Any]],
) -> dict[str, dict[str, str]]:
    context: dict[str, dict[str, str]] = {}
    for event in parent_events or _events_from_payload(parent):
        payload = event.get("payload") if isinstance(event.get("payload"), dict) else {}
        child_run_id = str(
            payload.get("child_run_id")
            or payload.get("child_agent_run_id")
            or event.get("child_run_id")
            or event.get("child_agent_run_id")
            or ""
        ).strip()
        if not child_run_id:
            continue
        item: dict[str, str] = {}
        for key in (
            "workflow_node_id",
            "workflow_node_kind",
            "workflow_node_label",
            "workflow_parent_node_id",
            "workflow_parent_node_kind",
            "workflow_parent_node_label",
            "workflow_parallel_branch_entry_node_id",
            "workflow_parallel_branch_label",
        ):
            value = str(payload.get(key) or event.get(key) or "").strip()
            if value:
                item[key] = value
        if item:
            context.setdefault(child_run_id, {}).update(item)
    return context


def _workflow_child_replay_event(
    event: dict[str, Any],
    *,
    parent_run_id: str,
    workflow_id: str,
    child_run_id: str,
    context: dict[str, str],
) -> dict[str, Any]:
    item = dict(event)
    payload = dict(item.get("payload")) if isinstance(item.get("payload"), dict) else {}
    source_sequence = str(item.get("sequence") or "").strip()
    source_event_id = str(item.get("event_id") or "").strip()
    payload.setdefault("source_run_id", child_run_id)
    payload.setdefault("parent_run_id", parent_run_id)
    if source_sequence:
        payload.setdefault("source_sequence", source_sequence)
    if source_event_id:
        payload.setdefault("source_event_id", source_event_id)
    if workflow_id:
        payload.setdefault("workflow_id", workflow_id)
    payload.setdefault("workflow_run_id", parent_run_id)
    for key, value in context.items():
        if value:
            payload.setdefault(key, value)
    item["run_id"] = parent_run_id
    item["payload"] = payload
    return item


def _events_from_payload(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [dict(item) for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    for key in ("events", "run_events", "recent_events", "timeline"):
        value = payload.get(key)
        if isinstance(value, list) and value:
            return [dict(item) for item in value if isinstance(item, dict)]
    return []


def _resequence_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**event, "sequence": index}
        for index, event in enumerate(events, start=1)
    ]


def _pending_approval_id(payload: dict[str, Any]) -> str:
    pending = payload.get("pending_approval")
    if isinstance(pending, dict):
        approval_id = str(pending.get("approval_id") or "").strip()
        if approval_id:
            return approval_id
    for approval in payload.get("pending_approvals") or []:
        if not isinstance(approval, dict):
            continue
        approval_id = str(approval.get("approval_id") or "").strip()
        if approval_id:
            return approval_id
    return ""


def _workflow_artifact_source_run_id(
    runtime: Any,
    run_id: str,
    artifact_path: str,
) -> str:
    clean_path = str(artifact_path or "").strip()
    if not clean_path:
        return ""
    try:
        run = runtime.get_run(run_id)
    except (AttributeError, KeyError):
        return ""
    if str(run.get("kind") or "").strip() != "workflow_run":
        return ""
    workflow_run = workflow_run_snapshot_from_payload(
        _workflow_run_with_child_runs(
            _run_with_replay_events(run, runtime),
            runtime,
        )
    )
    for artifact in workflow_run.artifacts:
        if str(artifact.path or "").strip() != clean_path:
            continue
        source_run_id = str(artifact.source_run_id or artifact.run_id or "").strip()
        if source_run_id and source_run_id != run_id:
            return source_run_id
    return ""
