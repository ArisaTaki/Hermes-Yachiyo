#!/usr/bin/env python3
"""Smoke-test that Agent entrypoints execute desktop intents before model fallback."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import apps.shell.agent_runtime as agent_runtime_mod
from apps.shell.agent.tools import desktop as desktop_tools
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class _FakeDefaultProfileService:
    def get_defaults(self) -> dict[str, str]:
        return {"chat": "profile_default"}

    def get_profile_private(self, profile_id: str) -> dict[str, Any]:
        if profile_id != "profile_default":
            raise KeyError(profile_id)
        return {
            "profile_id": profile_id,
            "provider": "openai_compatible",
            "base_url": "https://api.example.test/v1",
            "model": "demo-model",
            "api_key": "sk-secret",
            "capability": "chat",
            "status": "available",
            "enabled": True,
        }


@contextmanager
def _patched_attr(target: Any, name: str, value: Any) -> Iterator[None]:
    original = getattr(target, name)
    setattr(target, name, value)
    try:
        yield
    finally:
        setattr(target, name, original)


def _make_service(root: Path) -> AgentRuntimeService:
    return AgentRuntimeService(
        db_path=root / "agent-runtime.db",
        workspace_dir=root / "runtime",
        credential_store=MemoryCredentialStore(),
    )


def _fake_apple_music_open_and_play() -> dict[str, Any]:
    return {
        "ok": True,
        "action": "media.apple_music_open_and_play",
        "summary": "Opened Music and started playback",
        "data": {
            "app_name": "Music",
            "open_ok": True,
            "playback_ok": True,
            "control": "play",
            "player_state": "playing",
            "track": "超时空辉夜姬",
            "artist": "Yachiyo",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _fake_list_apps(*, query: str = "", limit: Any = 200) -> dict[str, Any]:
    clean_query = str(query or "").strip()
    return {
        "ok": True,
        "action": "desktop.list_apps",
        "summary": f"Installed apps matching {clean_query}: PixelForge",
        "data": {
            "query": clean_query,
            "apps": [
                {
                    "name": "PixelForge",
                    "path": "/Applications/PixelForge.app",
                    "match_score": 100,
                }
            ],
            "count": 1,
            "total_count": 1,
            "truncated": False,
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _fake_app_open(app_name: str) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "app.open",
        "summary": f"已打开 {app_name}",
        "data": {
            "app_name": str(app_name or "").strip(),
            "running": True,
            "status": "running",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _fake_open_path_with_app(path: str, app_name: str) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "desktop.open_path_with_app",
        "summary": f"Opened {path} with {app_name}",
        "data": {
            "path": str(path or "").strip(),
            "app_name": str(app_name or "").strip(),
            "exists": True,
            "is_dir": False,
            "suffix": ".pdf",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _fake_active_window() -> dict[str, Any]:
    return {
        "ok": True,
        "action": "desktop.active_window",
        "summary": "PixelForge is active",
        "data": {
            "app_name": "PixelForge",
            "frontmost_app": "PixelForge",
            "title": "PixelForge",
        },
        "permission_error": False,
        "fallback_used": False,
    }


def _event_types(events: Sequence[dict[str, Any]]) -> list[str]:
    return [str(event.get("event_type") or "") for event in events if isinstance(event, dict)]


def _events_of_type(events: Sequence[dict[str, Any]], event_type: str) -> list[dict[str, Any]]:
    return [
        event
        for event in events
        if isinstance(event, dict) and event.get("event_type") == event_type
    ]


def _first_event(events: Sequence[dict[str, Any]], event_type: str) -> dict[str, Any]:
    for event in events:
        if isinstance(event, dict) and event.get("event_type") == event_type:
            return event
    return {}


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _mapping_includes(mapping: Any, expected: dict[str, Any]) -> bool:
    if not isinstance(mapping, dict):
        return False
    return all(mapping.get(key) == value for key, value in expected.items())


def _is_desktop_operation_planning_reason(value: Any) -> bool:
    return str(value or "").strip() in {
        "planner_desktop_operation",
        "planner_full_plan_desktop_operation",
    }


def _model_event_free(events: Sequence[dict[str, Any]]) -> bool:
    return not any(
        event_type in {"model.request.started", "model.requested"}
        for event_type in _event_types(events)
    )


def _generic_app_open_case(
    service: AgentRuntimeService,
    *,
    entrypoint: str,
) -> dict[str, Any]:
    prompt = "打开 PixelForge"
    if entrypoint == "main_chat":
        run = service.start_main_chat_run(
            task_id="smoke-main-chat-pixelforge",
            session_id="smoke-main-chat-generic-app-session",
            user_goal=prompt,
        )
        loop_result = service.execute_main_chat_model_loop(
            str(run["run_id"]),
            [{"role": "user", "content": prompt}],
        )
        updated = service.complete_main_chat_run(
            str(run["run_id"]),
            str(loop_result.get("result") or ""),
        )
        run_id = str(run.get("run_id") or "")
        loop_status = loop_result.get("status")
    else:
        agent = service.create_agent(
            {
                "name": "Generic Desktop Agent",
                "model_mode": "custom_api",
                "model_config": {
                    "base_url": "https://api.example.test/v1",
                    "model": "demo-model",
                    "api_key": "sk-secret",
                },
                "tool_policy": {
                    "allowed_tools": ["workspace.read"],
                    "approval_required": {},
                },
            }
        )
        updated = service.create_agent_run(
            {
                "agent_id": agent["agent_id"],
                "user_goal": prompt,
                "daily_desktop_policy_overlay": True,
            }
        )
        run_id = str(updated.get("run_id") or "")
        loop_status = ""

    events = service.list_run_events(run_id)["events"]
    planned_events = _events_of_type(events, "agent.desktop.intent_planned")
    tool_events = _events_of_type(events, "agent.tool.call")
    completed_event = _first_event(events, "agent.desktop.intent_completed")
    selection_event = _first_event(events, "agent.plan.selection")
    selected_intent_event = _first_event(events, "agent.intent.selected")
    planned_tools = [_payload(event).get("tool") for event in planned_events]
    tool_call_tools = [_payload(event).get("tool") for event in tool_events]
    tool_result_actions = [
        (_payload(event).get("result") or {}).get("action")
        for event in tool_events
        if isinstance(_payload(event).get("result"), dict)
    ]
    completed_payload = _payload(completed_event)
    completed_tools = completed_payload.get("tools")
    selection_payload = _payload(selection_event)
    selected_intent_payload = _payload(selected_intent_event)
    expected_plan_tools = ["desktop.list_apps", "app.open", "desktop.active_window"]
    expected_execution_tools = expected_plan_tools
    checks = {
        "run_completed": updated.get("status") == "completed",
        "summary_names_generic_app": "已打开 PixelForge" in str(updated.get("result") or ""),
        "model_not_called": _model_event_free(events),
        "intent_is_desktop_operation": (
            (selected_intent_payload.get("intent") or {}).get("kind") == "desktop_operation"
            if isinstance(selected_intent_payload.get("intent"), dict)
            else False
        ),
        "selection_uses_runtime_planner_full_plan": selection_payload.get("selection_reason")
        == "runtime_planner_full_plan_execution",
        "selection_source_runtime_planner": selection_payload.get("selection_source") == "runtime_planner",
        "selection_plan_tool_chain": selection_payload.get("plan_tools") == expected_plan_tools,
        "planned_tool_chain": planned_tools == expected_execution_tools,
        "planned_discovery_query": _payload(planned_events[0]).get("input_preview")
        == {"query": "PixelForge", "limit": 20}
        if planned_events
        else False,
        "planned_open_input": _mapping_includes(
            _payload(planned_events[1]).get("input_preview"),
            {"app_name": "PixelForge"},
        )
        if len(planned_events) > 1
        else False,
        "tool_call_chain": tool_call_tools == expected_execution_tools,
        "tool_results_match_chain": tool_result_actions == expected_execution_tools,
        "completed_from_runtime_planner": completed_payload.get("source") == "runtime_planner",
        "completed_tools_match": completed_tools == expected_execution_tools,
        "completed_summary_names_generic_app": "已打开 PixelForge" in str(
            completed_payload.get("summary") or ""
        ),
    }
    return {
        "id": f"{entrypoint}_generic_app_open_before_model",
        "ok": all(checks.values()),
        "run_id": run_id,
        "status": updated.get("status"),
        "loop_status": loop_status,
        "result": updated.get("result"),
        "event_types": _event_types(events),
        "selection_event": selection_event,
        "planned_events": planned_events,
        "tool_events": tool_events,
        "completed_event": completed_event,
        "checks": checks,
    }


def _capability_discovered_app_open_case(service: AgentRuntimeService) -> dict[str, Any]:
    prompt = "找一个能编辑 PDF 的本机应用并打开它"
    run = service.start_main_chat_run(
        task_id="smoke-main-chat-capability-discovered-app",
        session_id="smoke-main-chat-capability-discovery-session",
        user_goal=prompt,
    )
    loop_result = service.execute_main_chat_model_loop(
        str(run["run_id"]),
        [{"role": "user", "content": prompt}],
    )
    updated = service.complete_main_chat_run(
        str(run["run_id"]),
        str(loop_result.get("result") or ""),
    )
    run_id = str(run.get("run_id") or "")
    events = service.list_run_events(run_id)["events"]
    planned_events = _events_of_type(events, "agent.desktop.intent_planned")
    tool_events = _events_of_type(events, "agent.tool.call")
    completed_event = _first_event(events, "agent.desktop.intent_completed")
    selection_event = _first_event(events, "agent.plan.selection")
    selected_intent_event = _first_event(events, "agent.intent.selected")
    planned_tools = [_payload(event).get("tool") for event in planned_events]
    tool_call_tools = [_payload(event).get("tool") for event in tool_events]
    tool_result_actions = [
        (_payload(event).get("result") or {}).get("action")
        for event in tool_events
        if isinstance(_payload(event).get("result"), dict)
    ]
    selection_payload = _payload(selection_event)
    followup_target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), dict)
        else {}
    )
    selected_intent_payload = _payload(selected_intent_event)
    completed_payload = _payload(completed_event)
    app_open_input = (
        _payload(tool_events[1]).get("input_preview")
        if len(tool_events) > 1 and isinstance(_payload(tool_events[1]), dict)
        else {}
    )
    checks = {
        "run_completed": updated.get("status") == "completed",
        "summary_names_discovered_app": "已打开 PixelForge" in str(updated.get("result") or ""),
        "model_not_called": _model_event_free(events),
        "intent_is_desktop_operation": (
            (selected_intent_payload.get("intent") or {}).get("kind") == "desktop_operation"
            if isinstance(selected_intent_payload.get("intent"), dict)
            else False
        ),
        "selection_source_runtime_planner": selection_payload.get("selection_source") == "runtime_planner",
        "selection_has_discovered_app_followup": followup_target == {
            "kind": "desktop_discovered_app_action",
            "app_query": "pdf",
            "app_name_source": "desktop.list_apps",
            "capability_description": "PDF",
            "target_action": "open_app",
        },
        "planned_tool_chain": planned_tools == [
            "desktop.list_apps",
            "app.open",
            "desktop.active_window",
        ],
        "planned_discovery_is_direct_execution": (
            not bool(_payload(planned_events[0]).get("continue_to_model"))
            if planned_events
            else False
        ),
        "planned_discovery_query": _payload(planned_events[0]).get("input_preview")
        == {"query": "pdf", "limit": 20}
        if planned_events
        else False,
        "planned_followup_tools": all(
            _is_desktop_operation_planning_reason(
                _payload(event).get("planning_reason")
            )
            for event in planned_events[1:]
        )
        if len(planned_events) > 1
        else False,
        "tool_call_chain": tool_call_tools == [
            "desktop.list_apps",
            "app.open",
            "desktop.active_window",
        ],
        "tool_results_match_chain": tool_result_actions == [
            "desktop.list_apps",
            "app.open",
            "desktop.active_window",
        ],
        "resolved_app_from_discovery": {
            "app_name": "PixelForge",
            "app_resolution_source": "desktop.list_apps",
            "requested_app_name": "pdf",
            "resolved_app_name": "PixelForge",
            "resolved_app_path": "/Applications/PixelForge.app",
            "app_resolution_score": "100",
        }.items()
        <= app_open_input.items()
        if isinstance(app_open_input, dict)
        else False,
        "completed_from_runtime_planner": completed_payload.get("source") == "runtime_planner",
        "completed_tools_match": completed_payload.get("tools")
        == ["desktop.list_apps", "app.open", "desktop.active_window"],
        "completed_after_discovered_app_open": completed_payload.get("tool") == "app.open",
    }
    return {
        "id": "main_chat_capability_discovered_app_open_before_model",
        "ok": all(checks.values()),
        "run_id": run_id,
        "status": updated.get("status"),
        "loop_status": loop_result.get("status"),
        "result": updated.get("result"),
        "event_types": _event_types(events),
        "selection_event": selection_event,
        "planned_events": planned_events,
        "tool_events": tool_events,
        "completed_event": completed_event,
        "checks": checks,
    }


def _capability_discovered_app_open_path_case(service: AgentRuntimeService) -> dict[str, Any]:
    prompt = "打开一个能编辑 PDF 的应用并打开 Downloads/report.pdf"
    run = service.start_main_chat_run(
        task_id="smoke-main-chat-capability-discovered-app-open-path",
        session_id="smoke-main-chat-capability-discovered-app-open-path-session",
        user_goal=prompt,
    )
    loop_result = service.execute_main_chat_model_loop(
        str(run["run_id"]),
        [{"role": "user", "content": prompt}],
    )
    updated = service.complete_main_chat_run(
        str(run["run_id"]),
        str(loop_result.get("result") or ""),
    )
    run_id = str(run.get("run_id") or "")
    events = service.list_run_events(run_id)["events"]
    planned_events = _events_of_type(events, "agent.desktop.intent_planned")
    tool_events = _events_of_type(events, "agent.tool.call")
    completed_event = _first_event(events, "agent.desktop.intent_completed")
    selection_event = _first_event(events, "agent.plan.selection")
    selected_intent_event = _first_event(events, "agent.intent.selected")
    resolved_event = next(
        (
            event
            for event in events
            if event.get("event_type") == "agent.tool.input_resolved"
            and _payload(event).get("tool") == "desktop.open_path_with_app"
        ),
        {},
    )
    planned_tools = [_payload(event).get("tool") for event in planned_events]
    tool_call_tools = [_payload(event).get("tool") for event in tool_events]
    tool_result_actions = [
        (_payload(event).get("result") or {}).get("action")
        for event in tool_events
        if isinstance(_payload(event).get("result"), dict)
    ]
    selection_payload = _payload(selection_event)
    followup_target = (
        selection_payload.get("followup_target")
        if isinstance(selection_payload.get("followup_target"), dict)
        else {}
    )
    selected_intent_payload = _payload(selected_intent_event)
    completed_payload = _payload(completed_event)
    open_path_input = (
        _payload(tool_events[1]).get("input_preview")
        if len(tool_events) > 1 and isinstance(_payload(tool_events[1]), dict)
        else {}
    )
    checks = {
        "run_completed": updated.get("status") == "completed",
        "summary_names_discovered_app_and_path": (
            "已用 PixelForge 打开文件：Downloads/report.pdf。"
            in str(updated.get("result") or "")
        ),
        "model_not_called": _model_event_free(events),
        "intent_is_desktop_operation": (
            (selected_intent_payload.get("intent") or {}).get("kind") == "desktop_operation"
            if isinstance(selected_intent_payload.get("intent"), dict)
            else False
        ),
        "selection_source_runtime_planner": selection_payload.get("selection_source") == "runtime_planner",
        "selection_has_discovered_app_open_path_followup": followup_target == {
            "kind": "desktop_discovered_app_action",
            "app_query": "pdf",
            "app_name_source": "desktop.list_apps",
            "capability_description": "PDF",
            "target_action": "open_path_with_selected_app",
            "target_path": "Downloads/report.pdf",
        },
        "planned_tool_chain": planned_tools == [
            "desktop.list_apps",
            "desktop.open_path_with_app",
        ],
        "planned_discovery_is_direct_execution": (
            not bool(_payload(planned_events[0]).get("continue_to_model"))
            if planned_events
            else False
        ),
        "planned_discovery_query": _payload(planned_events[0]).get("input_preview")
        == {"query": "pdf", "limit": 20}
        if planned_events
        else False,
        "planned_followup_tool": (
            _is_desktop_operation_planning_reason(
                _payload(planned_events[1]).get("planning_reason")
            )
            if len(planned_events) > 1
            else False
        ),
        "tool_call_chain": tool_call_tools == [
            "desktop.list_apps",
            "desktop.open_path_with_app",
        ],
        "tool_results_match_chain": tool_result_actions == [
            "desktop.list_apps",
            "desktop.open_path_with_app",
        ],
        "resolved_app_from_discovery": {
            "app_name": "PixelForge",
            "path": "Downloads/report.pdf",
            "requested_app_name": "pdf",
            "resolved_app_name": "PixelForge",
            "resolved_app_path": "/Applications/PixelForge.app",
            "app_resolution_source": "desktop.list_apps",
            "app_resolution_score": "100",
        }.items()
        <= open_path_input.items()
        if isinstance(open_path_input, dict)
        else False,
        "resolved_event_recorded": _payload(resolved_event).get("resolved_app_name") == "PixelForge",
        "completed_from_runtime_planner": completed_payload.get("source") == "runtime_planner",
        "completed_tools_match": completed_payload.get("tools")
        == ["desktop.list_apps", "desktop.open_path_with_app"],
        "completed_after_open_path": completed_payload.get("tool") == "desktop.open_path_with_app",
    }
    return {
        "id": "main_chat_capability_discovered_app_open_path_before_model",
        "ok": all(checks.values()),
        "run_id": run_id,
        "status": updated.get("status"),
        "loop_status": loop_result.get("status"),
        "result": updated.get("result"),
        "event_types": _event_types(events),
        "selection_event": selection_event,
        "planned_events": planned_events,
        "tool_events": tool_events,
        "resolved_event": resolved_event,
        "completed_event": completed_event,
        "checks": checks,
    }


def _main_chat_loop_case(service: AgentRuntimeService) -> dict[str, Any]:
    run = service.start_main_chat_run(
        task_id="smoke-main-chat-apple-music",
        session_id="smoke-main-chat-session",
        user_goal="能否帮我播放 Apple Music?",
    )
    loop_result = service.execute_main_chat_model_loop(
        str(run["run_id"]),
        [{"role": "user", "content": "能否帮我播放 Apple Music?"}],
    )
    updated = service.complete_main_chat_run(str(run["run_id"]), str(loop_result.get("result") or ""))
    events = service.list_run_events(str(run["run_id"]))["events"]
    planned_event = _first_event(events, "agent.desktop.intent_planned")
    tool_event = _first_event(events, "agent.tool.call")
    completed_event = _first_event(events, "agent.desktop.intent_completed")
    tool_payload = _payload(tool_event)
    tool_result = tool_payload.get("result") if isinstance(tool_payload.get("result"), dict) else {}
    checks = {
        "run_completed": updated.get("status") == "completed",
        "loop_summary_names_apple_music": "已打开 Apple Music，并开始播放"
        in str(loop_result.get("result") or ""),
        "completion_summary_names_apple_music": "已打开 Apple Music，并开始播放"
        in str(updated.get("result") or ""),
        "model_not_called": _model_event_free(events),
        "planned_generic_music_tool": _payload(planned_event).get("tool") == "media.music_app_open_and_play",
        "planned_music_app_input": _payload(planned_event).get("input_preview") == {"app_name": "Music"},
        "tool_called": tool_payload.get("tool") == "media.music_app_open_and_play",
        "tool_result_used_apple_music_automation": tool_result.get("action")
        == "media.apple_music_open_and_play",
        "completed_from_runtime_planner": _payload(completed_event).get("source") == "runtime_planner",
    }
    return {
        "id": "main_chat_daily_desktop_before_model",
        "ok": all(checks.values()),
        "run_id": run.get("run_id"),
        "status": updated.get("status"),
        "loop_status": loop_result.get("status"),
        "result": updated.get("result"),
        "loop_result": loop_result.get("result"),
        "event_types": _event_types(events),
        "planned_event": planned_event,
        "tool_event": tool_event,
        "completed_event": completed_event,
        "checks": checks,
    }


def _agent_run_overlay_case(service: AgentRuntimeService) -> dict[str, Any]:
    agent = service.create_agent(
        {
            "name": "Native Agent",
            "model_mode": "custom_api",
            "model_config": {
                "base_url": "https://api.example.test/v1",
                "model": "demo-model",
                "api_key": "sk-secret",
            },
            "tool_policy": {
                "allowed_tools": ["workspace.read"],
                "approval_required": {},
            },
        }
    )
    run = service.create_agent_run(
        {
            "agent_id": agent["agent_id"],
            "user_goal": "能否帮我播放apple Music?",
            "daily_desktop_policy_overlay": True,
        }
    )
    events = service.list_run_events(str(run["run_id"]))["events"]
    planned_event = _first_event(events, "agent.desktop.intent_planned")
    policy_event = _first_event(events, "agent.tool.policy_decision")
    tool_event = _first_event(events, "agent.tool.call")
    tool_payload = _payload(tool_event)
    tool_result = tool_payload.get("result") if isinstance(tool_payload.get("result"), dict) else {}
    checks = {
        "run_completed": run.get("status") == "completed",
        "summary_names_apple_music": "已打开 Apple Music，并开始播放" in str(run.get("result") or ""),
        "model_not_called": _model_event_free(events),
        "planned_generic_music_tool": _payload(planned_event).get("tool") == "media.music_app_open_and_play",
        "policy_overlay_recorded": _payload(policy_event).get("policy_overlay") is True,
        "policy_reason_recorded": _payload(policy_event).get("reason") == "daily_desktop_policy_overlay",
        "tool_called": tool_payload.get("tool") == "media.music_app_open_and_play",
        "tool_result_used_apple_music_automation": tool_result.get("action")
        == "media.apple_music_open_and_play",
    }
    return {
        "id": "agent_run_daily_desktop_overlay_before_model",
        "ok": all(checks.values()),
        "run_id": run.get("run_id"),
        "status": run.get("status"),
        "result": run.get("result"),
        "event_types": _event_types(events),
        "planned_event": planned_event,
        "policy_event": policy_event,
        "tool_event": tool_event,
        "checks": checks,
    }


def run_smoke(*, workdir: Path | None = None) -> dict[str, Any]:
    model_call_count = 0

    def forbidden_model_call(*_args: Any, **_kwargs: Any) -> dict[str, str]:
        nonlocal model_call_count
        model_call_count += 1
        raise RuntimeError("desktop entrypoint smoke should execute before model call")

    with tempfile.TemporaryDirectory(prefix="oha-entrypoint-desktop-smoke-") as temp_dir:
        root = Path(workdir) if workdir is not None else Path(temp_dir)
        root.mkdir(parents=True, exist_ok=True)
        service = _make_service(root)
        try:
            with _patched_attr(
                agent_runtime_mod,
                "get_model_profile_service",
                lambda: _FakeDefaultProfileService(),
            ), _patched_attr(
                agent_runtime_mod,
                "openai_compatible_chat_message",
                forbidden_model_call,
            ), _patched_attr(
                desktop_tools,
                "apple_music_open_and_play",
                _fake_apple_music_open_and_play,
            ), _patched_attr(
                desktop_tools,
                "list_apps",
                _fake_list_apps,
            ), _patched_attr(
                desktop_tools,
                "app_open",
                _fake_app_open,
            ), _patched_attr(
                desktop_tools,
                "open_path_with_app",
                _fake_open_path_with_app,
            ), _patched_attr(
                desktop_tools,
                "active_window",
                _fake_active_window,
            ):
                cases = [
                    _generic_app_open_case(service, entrypoint="main_chat"),
                    _generic_app_open_case(service, entrypoint="agent_run"),
                    _capability_discovered_app_open_case(service),
                    _capability_discovered_app_open_path_case(service),
                    _main_chat_loop_case(service),
                    _agent_run_overlay_case(service),
                ]
        finally:
            service.close()
    checks = {
        "all_cases_passed": all(case.get("ok") is True for case in cases),
        "model_never_called": model_call_count == 0,
    }
    return {
        "ok": all(checks.values()),
        "mode": "agent_entrypoint_desktop_execution_smoke",
        "case_count": len(cases),
        "model_call_count": model_call_count,
        "cases": cases,
        "checks": checks,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workdir", type=Path, help="Optional persistent smoke workdir.")
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke(workdir=args.workdir)
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"agent entrypoint desktop execution smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
