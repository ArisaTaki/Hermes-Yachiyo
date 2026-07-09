#!/usr/bin/env python3
"""Aggregate release smoke for Oha-Yachiyo desktop-agent product readiness."""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent import daily_desktop as daily_desktop_module
from apps.shell.yachiyo_agent.desktop_provider_contract import (
    VIRTUAL_DESKTOP_PROVIDER_TEMPLATE_BASE_URL,
    virtual_desktop_provider_conformance_summary,
    virtual_desktop_provider_manifest_contract_evidence,
    virtual_desktop_provider_manifest_template,
)
from apps.shell.yachiyo_agent.desktop_execution_policy import (
    desktop_provider_session_auto_start_recommended_for_requests,
)
from apps.shell.yachiyo_agent.daily_desktop import (
    daily_desktop_direct_metadata_request,
    daily_desktop_allowed_tools,
    planner_first_daily_desktop_entrypoint_requests,
)
from apps.shell.yachiyo_agent.run_timeline_snapshots import (
    run_timeline_snapshot_from_payload,
)
from apps.shell.yachiyo_agent.start_event_enrichment import (
    start_payload_with_planner_decision_events,
)
from apps.shell.yachiyo_agent.tool_catalog import runtime_tool_catalog_snapshot
from scripts import smoke_agent_entrypoint_desktop_execution
from scripts import smoke_agent_studio_planner_orchestration
from scripts import smoke_approval_policy_gate
from scripts import smoke_data_analysis_artifacts
from scripts import smoke_desktop_provider_execution_loop
from scripts import smoke_group_run_timeline
from scripts import smoke_isolated_desktop_provider
from scripts import smoke_planner_runtime_tool_parity
from scripts import smoke_workflow_run_timeline

SmokeRunner = Callable[[], dict[str, Any]]


def _tools(requests: Sequence[dict[str, Any]]) -> list[str]:
    return [
        str(request.get("tool") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("tool") or "").strip()
    ]


def _sources(requests: Sequence[dict[str, Any]]) -> list[str]:
    return [
        str(request.get("source") or "").strip()
        for request in requests
        if isinstance(request, dict) and str(request.get("source") or "").strip()
    ]


def _deepagent_core_case() -> dict[str, Any]:
    decision = RuntimePlanner().decision(
        "打开 PixelForge",
        allowed_tools=daily_desktop_allowed_tools(),
    )
    plan = decision.plan
    tool_plan = plan.tool_plan
    task_core = plan.task_core
    checks = {
        "intent_is_desktop_operation": decision.selected_intent.kind == "desktop_operation",
        "tool_plan_has_discover_operate_verify": [
            step.tool_name for step in tool_plan.steps
        ]
        == ["desktop.list_apps", "app.open", "desktop.verify"],
        "task_core_exists": bool(task_core.core_id),
        "workspace_exists": bool(task_core.workspace.workspace_id),
        "todos_cover_steps": [todo.step_id for todo in task_core.todos]
        == [step.step_id for step in tool_plan.steps],
        "checkpoints_cover_steps": [checkpoint.after_step_id for checkpoint in task_core.checkpoints]
        == [step.step_id for step in tool_plan.steps],
        "replan_signals_cover_steps": [signal.source_step_id for signal in task_core.replan_signals]
        == [step.step_id for step in tool_plan.steps],
    }
    return {
        "id": "deepagent_task_core",
        "ok": all(checks.values()),
        "intent_kind": decision.selected_intent.kind,
        "plan_id": plan.plan_id,
        "tool_plan_id": tool_plan.plan_id,
        "core_id": task_core.core_id,
        "workspace_id": task_core.workspace.workspace_id,
        "tool_steps": [step.tool_name for step in tool_plan.steps],
        "todo_step_ids": [todo.step_id for todo in task_core.todos],
        "checkpoint_step_ids": [checkpoint.after_step_id for checkpoint in task_core.checkpoints],
        "replan_step_ids": [signal.source_step_id for signal in task_core.replan_signals],
        "checks": checks,
    }


def _shared_surface_case() -> dict[str, Any]:
    surface_metadata = {
        "chat": {"surface": "chat_window"},
        "bubble": {
            "source": "launcher",
            "launcher_mode": "bubble",
            "launcher_surface": "quick_message",
        },
        "live2d": {
            "source": "launcher",
            "launcher_mode": "live2d",
            "launcher_surface": "live2d",
        },
    }
    cases: list[dict[str, Any]] = []
    for surface, metadata in surface_metadata.items():
        requests = planner_first_daily_desktop_entrypoint_requests(
            "打开 PixelForge",
            metadata=metadata,
            execution_normalized=True,
            include_runtime_context=True,
        )
        cases.append(
            {
                "surface": surface,
                "tools": _tools(requests),
                "sources": _sources(requests),
                "planning_reasons": [
                    str(request.get("planning_reason") or "").strip()
                    for request in requests
                    if isinstance(request, dict)
                ],
            }
        )
    checks = {
        "all_surfaces_present": [case["surface"] for case in cases]
        == ["chat", "bubble", "live2d"],
        "all_use_runtime_planner": all(
            case["sources"]
            and set(case["sources"]) <= {"runtime_planner", "runtime_verification"}
            and "runtime_planner" in set(case["sources"])
            for case in cases
        ),
        "all_share_discover_operate_verify_tools": all(
            case["tools"] == ["desktop.list_apps", "app.open", "desktop.verify"]
            for case in cases
        ),
        "no_legacy_surface_fallback": all(
            "daily_desktop_intent" not in case["sources"] for case in cases
        ),
    }
    direct_recovery_request = daily_desktop_direct_metadata_request(
        {
            "desktop_permission_recovery": True,
            "recovery_risk_level": "low",
            "recovery_tool": "app.focus_and_safe_shortcut",
            "recovery_input": {"app_name": "Finder", "action": "rename_selected"},
            "launcher_mode": "bubble",
        },
        allowed_tools=["app.focus_and_safe_shortcut"],
    )
    direct_policy = (
        direct_recovery_request.get("desktop_execution_policy")
        if isinstance(direct_recovery_request, dict)
        and isinstance(direct_recovery_request.get("desktop_execution_policy"), dict)
        else {}
    )
    checks["direct_recovery_keeps_daily_sandbox_policy"] = (
        bool(direct_recovery_request)
        and direct_policy.get("mode") == "preview_input"
        and direct_policy.get("prefer_isolated_desktop") is True
        and direct_policy.get("avoid_user_foreground_takeover") is True
        and direct_policy.get("require_sandbox_for_keyboard_mouse") is True
    )
    checks["direct_recovery_recommends_provider_session"] = (
        bool(direct_recovery_request)
        and desktop_provider_session_auto_start_recommended_for_requests(
            [direct_recovery_request]
        )
        is True
    )
    return {
        "id": "chat_bubble_live2d_shared_runtime",
        "ok": all(checks.values()),
        "cases": cases,
        "direct_recovery_request": direct_recovery_request,
        "checks": checks,
    }


def _tool_catalog_case() -> dict[str, Any]:
    catalog = runtime_tool_catalog_snapshot()
    tool_names = {tool.tool_name for tool in catalog.tools}
    coverage = catalog.legacy_cleanup_coverage
    checks = {
        "desktop_discovery_tools_visible": {
            "desktop.list_apps",
            "app.open",
            "desktop.active_window",
        }.issubset(tool_names),
        "approval_tools_visible": {
            "app.focus_and_click_ui_element",
            "app.focus_and_type_into_ui_element",
        }.issubset(tool_names),
        "legacy_cleanup_coverage_visible": coverage is not None,
        "cleanup_owned_by_runtime_planner": bool(coverage)
        and coverage.planner_owner == "runtime_planner",
        "cleanup_has_release_sized_sample_set": bool(coverage)
        and coverage.total_samples >= 57,
        "cleanup_tracks_app_launch": bool(coverage)
        and int(coverage.areas.get("app_launch", 0)) > 0,
        "cleanup_lists_planner_owned_entrypoints": bool(coverage)
        and len(coverage.planner_owned_entrypoints) >= 5,
        "cleanup_lists_remaining_fallbacks": bool(coverage)
        and len(coverage.remaining_fallback_contracts) == 0,
        "cleanup_remaining_fallbacks_are_planner_covered": bool(coverage)
        and coverage.remaining_fallback_count == coverage.planner_covered_fallback_count
        and coverage.compatibility_cleanup_pending_count
        == len(coverage.remaining_fallback_contracts),
    }
    return {
        "id": "studio_tool_catalog_runtime_coverage",
        "ok": all(checks.values()),
        "tool_count": len(tool_names),
        "coverage": coverage.model_dump(mode="json") if coverage else None,
        "checks": checks,
    }


def _provider_session_observability_case() -> dict[str, Any]:
    envelope = {
        "envelope_id": "release-provider-session-envelope",
        "requests": [
            {
                "request_id": "request-focus-app",
                "tool_name": "app.focus",
            }
        ],
        "desktop_provider_session": {
            "ok": False,
            "status": "start_failed",
            "needed": True,
            "running": False,
            "provider_id": "local-isolated-desktop",
            "reason": "sandbox_desktop_provider_required",
            "tool_names": ["app.focus"],
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "supported_tools": ["app.focus", "desktop.ui_elements"],
            "provider_manifest_evidence": {
                "ok": False,
                "remote_endpoint_allowed": False,
                "remote_endpoint_urls": [
                    "https://provider.example.com/tools/execute"
                ],
                "blocking_conditions": [
                    "desktop_provider_manifest_remote_endpoint_not_allowed"
                ],
            },
        },
    }
    enriched_start = start_payload_with_planner_decision_events(
        {
            "run_id": "run-provider-session-release",
            "task_id": "task-provider-session-release",
            "session_id": "chat-release",
            "events": [
                {
                    "event_type": "agent.intent.selected",
                    "payload": {"intent": {"kind": "desktop_operation"}},
                }
            ],
            "runtime_execution_envelope": envelope,
        },
        None,
    )
    timeline = run_timeline_snapshot_from_payload(
        {
            "run_id": "run-provider-session-release",
            "task_id": "task-provider-session-release",
            "session_id": "chat-release",
            "status": "running",
            "events": [
                {
                    "event_type": "run.started",
                    "sequence": 1,
                    "payload": {"task_id": "task-provider-session-release"},
                }
            ],
            "runtime_execution_envelope": envelope,
        }
    )
    start_event_types = [
        str(event.get("event_type") or event.get("event") or "").strip()
        for event in enriched_start.get("events") or []
        if isinstance(event, dict)
    ]
    timeline_event_types = [event.event_type for event in timeline.events]
    runtime_debug = timeline.runtime_debug
    checks = {
        "start_payload_preserves_existing_planner_event": start_event_types.count(
            "agent.intent.selected"
        )
        == 1,
        "start_payload_projects_provider_session_event": (
            "desktop.provider_session.failed" in start_event_types
        ),
        "run_timeline_projects_provider_session_event": (
            "desktop.provider_session.failed" in timeline_event_types
        ),
        "runtime_debug_surfaces_provider_session": bool(runtime_debug)
        and runtime_debug.desktop_provider_session_status == "start_failed"
        and runtime_debug.desktop_provider_session_provider_id
        == "local-isolated-desktop",
        "runtime_debug_marks_replan_and_user_action": bool(runtime_debug)
        and runtime_debug.needs_replan
        and runtime_debug.needs_user_action,
        "runtime_debug_marks_no_foreground_takeover": bool(runtime_debug)
        and runtime_debug.desktop_provider_session_foreground_takeover_required
        is False,
        "runtime_debug_surfaces_provider_manifest": bool(runtime_debug)
        and runtime_debug.desktop_provider_manifest_ok is False
        and runtime_debug.desktop_provider_manifest_remote_endpoint_allowed is False
        and "desktop_provider_manifest_remote_endpoint_not_allowed"
        in runtime_debug.desktop_provider_manifest_blocking_conditions,
    }
    return {
        "id": "provider_session_observability",
        "ok": all(checks.values()),
        "start_event_types": start_event_types,
        "timeline_event_types": timeline_event_types,
        "runtime_debug": runtime_debug.model_dump(mode="json") if runtime_debug else None,
        "checks": checks,
    }


def _legacy_facade_planner_ownership_case() -> dict[str, Any]:
    cases = [
        {
            "id": "media_playback",
            "prompt": "能帮我播放 Apple Music 吗",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "media.music_app_open_and_play",
                    "input": {"app_name": "Music"},
                },
            ],
        },
        {
            "id": "simple_app_open",
            "prompt": "可以帮我打开 Word 吗",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "app.open",
                    "input": {"app_name": "Microsoft Word"},
                },
            ],
        },
        {
            "id": "file_reveal",
            "prompt": "显示当前选中文件",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.reveal_path",
                    "input": {"path": "finder_selection"},
                },
            ],
        },
        {
            "id": "browser_navigation",
            "prompt": "打开 GitHub 首页",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "browser.open_url",
                    "input": {"url": "https://github.com"},
                },
            ],
        },
        {
            "id": "safe_app_action",
            "prompt": "Chrome 新建无痕窗口",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_safe_shortcut",
                    "input": {"app_name": "Google Chrome", "action": "new_private_window"},
                },
            ],
        },
        {
            "id": "spotlight_search",
            "prompt": "打开聚焦搜索 yachiyo",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "spotlight_search"},
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_type_text",
                    "input": {"text": "yachiyo"},
                },
            ],
        },
        {
            "id": "finder_item_shortcut",
            "prompt": "Finder 重命名选中文件",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_safe_shortcut",
                    "input": {"app_name": "Finder", "action": "rename_selected"},
                },
            ],
        },
        {
            "id": "browser_app_search",
            "prompt": "Chrome 搜索 OpenAI",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus",
                    "input": {"app_name": "Google Chrome"},
                },
                {
                    "protocol": "json_fallback",
                    "tool": "browser.open_url",
                    "input": {"url": "https://www.google.com/search?q=OpenAI"},
                },
            ],
        },
        {
            "id": "browser_app_new_tab_search",
            "prompt": "Chrome 新建标签页搜索 OpenAI",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_safe_shortcut",
                    "input": {"app_name": "Google Chrome", "action": "new_tab"},
                },
                {
                    "protocol": "json_fallback",
                    "tool": "browser.open_url",
                    "input": {"url": "https://www.google.com/search?q=OpenAI"},
                },
            ],
        },
        {
            "id": "context_transfer_search_box",
            "prompt": "把当前页面内容输入到搜索框",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "select_all"},
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "copy"},
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.click_ui_element",
                    "input": {
                        "target": "搜索",
                        "role_filter": "text",
                        "limit": 80,
                        "click_count": 1,
                    },
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "paste"},
                },
            ],
        },
        {
            "id": "app_context_transfer_search_box",
            "prompt": "打开 Slack 搜索框输入选中的内容",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "copy"},
                },
                {
                    "protocol": "json_fallback",
                    "tool": "app.open_and_click_ui_element",
                    "input": {
                        "app_name": "Slack",
                        "target": "搜索",
                        "role_filter": "text",
                        "limit": 80,
                        "click_count": 1,
                    },
                },
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.safe_shortcut",
                    "input": {"action": "paste"},
                },
            ],
        },
        {
            "id": "semantic_ui_click",
            "prompt": "在 Linear 上的创建按钮点击",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "app.focus_and_click_ui_element",
                    "input": {
                        "app_name": "Linear",
                        "target": "创建",
                        "role_filter": "button",
                        "click_count": 1,
                        "limit": 80,
                    },
                },
            ],
        },
        {
            "id": "semantic_ui_type",
            "prompt": "Can you type hello into the search field?",
            "expected": [
                {
                    "protocol": "json_fallback",
                    "tool": "desktop.type_into_ui_element",
                    "input": {
                        "target": "search",
                        "text": "hello",
                        "role_filter": "text",
                        "limit": 80,
                    },
                },
            ],
        },
    ]
    legacy_calls: list[dict[str, Any]] = []
    original_legacy_parser = daily_desktop_module.daily_desktop_entrypoint_tool_requests

    def fail_legacy_parser(context: str, allowed_tools: Sequence[str], **_kwargs: Any) -> list[dict[str, Any]]:
        legacy_calls.append(
            {
                "context": str(context or ""),
                "allowed_tools": [str(tool) for tool in allowed_tools],
            }
        )
        raise AssertionError("legacy daily desktop parser should not own planner-compatible entrypoints")

    results: list[dict[str, Any]] = []
    daily_desktop_module.daily_desktop_entrypoint_tool_requests = fail_legacy_parser
    try:
        for case in cases:
            error = ""
            actual: list[dict[str, Any]] = []
            try:
                actual = daily_desktop_module.daily_desktop_entrypoint_requests(case["prompt"])
            except Exception as exc:
                error = str(exc)
            expected = case["expected"]
            results.append(
                {
                    "id": case["id"],
                    "prompt": case["prompt"],
                    "ok": not error and actual == expected,
                    "tools": _tools(actual),
                    "expected_tools": _tools(expected),
                    "actual": actual,
                    "expected": expected,
                    "error": error,
                }
            )
    finally:
        daily_desktop_module.daily_desktop_entrypoint_tool_requests = original_legacy_parser

    checks = {
        "legacy_parser_not_called": legacy_calls == [],
        "all_compatible_facade_cases_matched": all(result["ok"] for result in results),
        "covers_media_app_file_browser_and_action": {
            "media_playback",
            "simple_app_open",
            "file_reveal",
            "browser_navigation",
            "safe_app_action",
        }.issubset({str(result["id"]) for result in results}),
        "covers_media_app_file_browser_action_and_search": {
            "media_playback",
            "simple_app_open",
            "file_reveal",
            "browser_navigation",
            "safe_app_action",
            "spotlight_search",
            "finder_item_shortcut",
            "browser_app_search",
            "browser_app_new_tab_search",
            "context_transfer_search_box",
            "app_context_transfer_search_box",
            "semantic_ui_click",
            "semantic_ui_type",
        }.issubset({str(result["id"]) for result in results}),
    }
    return {
        "id": "legacy_facade_planner_ownership",
        "ok": all(checks.values()),
        "legacy_call_count": len(legacy_calls),
        "legacy_calls": legacy_calls,
        "cases": results,
        "checks": checks,
    }


def _run_section(
    section_id: str,
    objective: str,
    runner: SmokeRunner,
) -> dict[str, Any]:
    try:
        report = runner()
    except Exception as exc:
        return {
            "id": section_id,
            "objective": objective,
            "ok": False,
            "mode": "",
            "error": str(exc),
        }
    return {
        "id": section_id,
        "objective": objective,
        "ok": report.get("ok") is True,
        "mode": str(report.get("mode") or section_id),
        "report": report,
    }


def _build_sections(
    workdir: Path,
    *,
    run_isolated_provider_smoke: bool = True,
    use_configured_virtual_desktop_provider: bool = False,
    provider_manifest: Path | None = None,
) -> list[dict[str, Any]]:
    sections = [
        _run_section(
            "deepagent_core",
            "Task workspace, todo, checkpoint, and replan signals exist for desktop plans.",
            _deepagent_core_case,
        ),
        _run_section(
            "shared_daily_surfaces",
            "Chat, Bubble, and Live2D share the runtime planner entrypoint.",
            _shared_surface_case,
        ),
        _run_section(
            "desktop_executor_before_model",
            "Desktop discover/operate/verify runs before model fallback.",
            lambda: smoke_agent_entrypoint_desktop_execution.run_smoke(
                workdir=workdir / "desktop-entrypoint"
            ),
        ),
        _run_section(
            "desktop_provider_execution_loop",
            "Planner-selected sandbox desktop routes execute through a provider and request replan when the provider is unavailable.",
            smoke_desktop_provider_execution_loop.run_smoke,
        ),
        _run_section(
            "legacy_facade_planner_ownership",
            "Legacy-compatible Chat facade entrypoints are owned by Runtime Planner.",
            _legacy_facade_planner_ownership_case,
        ),
        _run_section(
            "capability_planner_tool_parity",
            "Runtime planner tool plans map to registered executable tools and approval policy.",
            smoke_planner_runtime_tool_parity.run_smoke,
        ),
        _run_section(
            "data_analysis_artifacts",
            "Data analysis handles CSV, JSON, text tables, XLSX, and produces artifacts.",
            lambda: smoke_data_analysis_artifacts.run_smoke(workdir / "data-analysis"),
        ),
        _run_section(
            "agent_studio_orchestration",
            "Agent Studio starts Workflow and GroupRun through the shared planner.",
            smoke_agent_studio_planner_orchestration.run_smoke,
        ),
        _run_section(
            "group_run_timeline",
            "GroupRun timeline preserves participant, approval, artifact, and event context.",
            smoke_group_run_timeline.run_smoke,
        ),
        _run_section(
            "workflow_run_timeline",
            "WorkflowRun timeline preserves child run, approval, artifact, and event context.",
            smoke_workflow_run_timeline.run_smoke,
        ),
        _run_section(
            "approval_policy_gate",
            "Approval and policy gates remain enforced for higher-risk desktop actions.",
            smoke_approval_policy_gate.run_smoke,
        ),
        _run_section(
            "studio_tool_catalog",
            "Agent Studio sees runtime tools and legacy-cleanup coverage.",
            _tool_catalog_case,
        ),
        _run_section(
            "provider_session_observability",
            "Provider session requirements and failures are visible in start events, Run Timeline, and RuntimeDebug.",
            _provider_session_observability_case,
        ),
    ]
    if run_isolated_provider_smoke:
        sections.append(
            _run_section(
                "isolated_desktop_provider",
                "Desktop provider can execute discover, operate, input, and verify without taking over the user's foreground session.",
                lambda: smoke_isolated_desktop_provider.run_smoke(
                    use_configured_provider=(
                        use_configured_virtual_desktop_provider
                        or provider_manifest is not None
                    ),
                    provider_manifest=provider_manifest,
                ),
            )
        )
    return sections


def run_smoke(
    *,
    workdir: Path | None = None,
    run_isolated_provider_smoke: bool = True,
    use_configured_virtual_desktop_provider: bool = False,
    provider_manifest: Path | None = None,
    require_public_release_backend: bool = False,
) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="oha-desktop-agent-release-smoke-") as temp_dir:
        root = Path(workdir) if workdir is not None else Path(temp_dir)
        root.mkdir(parents=True, exist_ok=True)
        sections = _build_sections(
            root,
            run_isolated_provider_smoke=run_isolated_provider_smoke,
            use_configured_virtual_desktop_provider=(
                use_configured_virtual_desktop_provider
            ),
            provider_manifest=provider_manifest,
        )
    failed = [section for section in sections if section.get("ok") is not True]
    isolated_provider_backend = _isolated_provider_backend_summary(sections)
    configured_virtual_desktop_provider_requested = bool(
        use_configured_virtual_desktop_provider or provider_manifest is not None
    )
    isolated_provider_release_blockers = _isolated_provider_release_blockers(
        run_isolated_provider_smoke=run_isolated_provider_smoke,
        configured_virtual_desktop_provider_requested=(
            configured_virtual_desktop_provider_requested
        ),
        isolated_provider_backend=isolated_provider_backend,
        require_public_release_backend=require_public_release_backend,
    )
    isolated_provider_smoke_collected = any(
        section.get("id") == "isolated_desktop_provider"
        and section.get("ok") is True
        for section in sections
    )
    checks = {
        "all_sections_passed": not failed,
        "covers_deepagent_core": any(section["id"] == "deepagent_core" for section in sections),
        "covers_desktop_executor": any(
            section["id"] == "desktop_executor_before_model" for section in sections
        ),
        "covers_desktop_provider_execution_loop": any(
            section["id"] == "desktop_provider_execution_loop"
            for section in sections
        ),
        "covers_legacy_facade_planner_ownership": any(
            section["id"] == "legacy_facade_planner_ownership" for section in sections
        ),
        "covers_chat_bubble_live2d": any(
            section["id"] == "shared_daily_surfaces" for section in sections
        ),
        "covers_agent_studio": any(
            section["id"] == "agent_studio_orchestration" for section in sections
        ),
        "covers_groups_workflow": {
            "group_run_timeline",
            "workflow_run_timeline",
        }.issubset({str(section["id"]) for section in sections}),
        "covers_approval_gate": any(
            section["id"] == "approval_policy_gate" for section in sections
        ),
        "covers_data_analysis": any(
            section["id"] == "data_analysis_artifacts" for section in sections
        ),
        "covers_studio_debug_catalog": any(
            section["id"] == "studio_tool_catalog" for section in sections
        ),
        "covers_provider_session_observability": any(
            section["id"] == "provider_session_observability"
            for section in sections
        ),
    }
    if run_isolated_provider_smoke:
        checks["covers_isolated_desktop_provider"] = any(
            section["id"] == "isolated_desktop_provider" for section in sections
        )
        checks["isolated_provider_dev_smoke_verified"] = (
            isolated_provider_smoke_collected
        )
        if configured_virtual_desktop_provider_requested or require_public_release_backend:
            checks["isolated_provider_release_backend_verified"] = (
                not isolated_provider_release_blockers
            )
    isolated_provider_release_ready = (
        run_isolated_provider_smoke
        and configured_virtual_desktop_provider_requested
        and not isolated_provider_release_blockers
    )
    public_release_ready = (
        all(checks.values())
        and (isolated_provider_release_ready if require_public_release_backend else False)
    )
    return {
        "ok": all(checks.values()),
        "mode": "oha_desktop_agent_release_smoke",
        "public_release_required": bool(require_public_release_backend),
        "public_release_ready": public_release_ready,
        "section_count": len(sections),
        "failed_sections": [str(section["id"]) for section in failed],
        "checks": checks,
        "isolated_provider_smoke_requested": run_isolated_provider_smoke,
        "configured_virtual_desktop_provider_requested": (
            configured_virtual_desktop_provider_requested
        ),
        "provider_manifest": str(provider_manifest or ""),
        "isolated_provider_smoke_mode": (
            "release_virtual_desktop_provider_smoke"
            if run_isolated_provider_smoke
            and configured_virtual_desktop_provider_requested
            else (
                "dev_loopback_provider_smoke"
                if run_isolated_provider_smoke
                else ""
            )
        ),
        "isolated_provider_smoke_collected": isolated_provider_smoke_collected,
        "isolated_provider_dev_smoke_ready": (
            run_isolated_provider_smoke and isolated_provider_smoke_collected
        ),
        "isolated_provider_release_ready": isolated_provider_release_ready,
        "isolated_provider_release_blockers": isolated_provider_release_blockers,
        "isolated_provider_backend": isolated_provider_backend,
        "sections": sections,
    }


def _isolated_provider_backend_summary(
    sections: Sequence[dict[str, Any]],
) -> dict[str, Any]:
    section = next(
        (
            candidate
            for candidate in sections
            if candidate.get("id") == "isolated_desktop_provider"
        ),
        {},
    )
    report = section.get("report") if isinstance(section.get("report"), dict) else {}
    if not report:
        return {}
    provider_contract = (
        report.get("provider_contract")
        if isinstance(report.get("provider_contract"), dict)
        else {}
    )
    provider_conformance = (
        report.get("provider_conformance")
        if isinstance(report.get("provider_conformance"), dict)
        else {}
    ) or virtual_desktop_provider_conformance_summary(
        provider_contract,
        status=report,
        mode="release_smoke_backend_summary",
        runtime_checked=True,
        public_release_ready=provider_contract.get("ok") is True,
        release_candidate=provider_contract.get("ok") is True,
        smoke_ok=section.get("ok") is True,
        supported_tools=report.get("supported_tools") or report.get("covered_tools"),
    )
    return {
        "desktop_session_kind": str(report.get("desktop_session_kind") or ""),
        "desktop_session_isolated": report.get("desktop_session_isolated"),
        "foreground_takeover_required": report.get("foreground_takeover_required"),
        "keyboard_mouse_capture_supported": report.get(
            "keyboard_mouse_capture_supported"
        ),
        "desktop_backend_kind": str(report.get("desktop_backend_kind") or ""),
        "desktop_backend_is_loopback": report.get("desktop_backend_is_loopback"),
        "desktop_backend_ready_for_public_release": report.get(
            "desktop_backend_ready_for_public_release"
        ),
        "requires_real_virtual_desktop_backend": report.get(
            "requires_real_virtual_desktop_backend"
        ),
        "provider_contract_ok": provider_contract.get("ok"),
        "provider_contract_version": str(
            provider_contract.get("contract_version") or ""
        ),
        "provider_contract_blocking_conditions": [
            str(item)
            for item in provider_contract.get("blocking_conditions") or []
            if str(item or "").strip()
        ],
        "provider_conformance_ok": provider_conformance.get("ok"),
        "provider_conformance_mode": str(provider_conformance.get("mode") or ""),
        "provider_conformance_smoke_ok": provider_conformance.get("smoke_ok"),
        "provider_conformance_public_release_ready": provider_conformance.get(
            "public_release_ready"
        ),
        "provider_conformance_release_candidate": provider_conformance.get(
            "release_candidate"
        ),
        "provider_conformance_release_blocking_conditions": [
            str(item)
            for item in provider_conformance.get("release_blocking_conditions") or []
            if str(item or "").strip()
        ],
        "provider_conformance_missing_required_tools": [
            str(item)
            for item in provider_conformance.get("missing_required_tools") or []
            if str(item or "").strip()
        ],
        "provider_conformance_failed_tools": [
            str(item)
            for item in provider_conformance.get("failed_tools") or []
            if str(item or "").strip()
        ],
    }


def _isolated_provider_release_blockers(
    *,
    run_isolated_provider_smoke: bool,
    configured_virtual_desktop_provider_requested: bool,
    isolated_provider_backend: dict[str, Any],
    require_public_release_backend: bool = False,
) -> list[str]:
    if not run_isolated_provider_smoke:
        if require_public_release_backend:
            return ["isolated_desktop_provider_smoke_required"]
        return []
    if not configured_virtual_desktop_provider_requested:
        if require_public_release_backend:
            blockers = _isolated_provider_backend_release_blockers(
                isolated_provider_backend
            )
            blockers.append("virtual_desktop_provider_not_configured")
            return _unique_strings(blockers)
        return []
    blockers = _isolated_provider_backend_release_blockers(isolated_provider_backend)
    return _unique_strings(blockers)


def _isolated_provider_backend_release_blockers(
    isolated_provider_backend: dict[str, Any],
) -> list[str]:
    blockers: list[str] = []
    conformance_ready = isolated_provider_backend.get(
        "provider_conformance_public_release_ready"
    )
    if conformance_ready is False:
        blockers.extend(
            str(item)
            for item in isolated_provider_backend.get(
                "provider_conformance_release_blocking_conditions",
                [],
            )
            if str(item or "").strip()
        )
        if not blockers:
            blockers.append("virtual_desktop_provider_contract_not_ready")
    elif isolated_provider_backend.get("provider_contract_ok") is not True:
        blockers.extend(
            str(item)
            for item in isolated_provider_backend.get(
                "provider_contract_blocking_conditions",
                [],
            )
            if str(item or "").strip()
        )
        if not blockers:
            blockers.append("virtual_desktop_provider_contract_not_ready")
    return blockers


def _unique_strings(values: Sequence[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        item = str(value or "").strip()
        if not item or item in seen:
            continue
        result.append(item)
        seen.add(item)
    return result


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _provider_manifest_validation_evidence(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return {
            "ok": False,
            "mode": "virtual_desktop_provider_manifest_validation",
            "manifest_path": str(path),
            "runtime_checked": False,
            "blocking_conditions": ["desktop_provider_manifest_unreadable"],
            "error": str(exc),
        }
    if not isinstance(payload, dict):
        return {
            "ok": False,
            "mode": "virtual_desktop_provider_manifest_validation",
            "manifest_path": str(path),
            "runtime_checked": False,
            "blocking_conditions": ["desktop_provider_manifest_not_object"],
        }
    evidence = virtual_desktop_provider_manifest_contract_evidence(payload)
    evidence["mode"] = "virtual_desktop_provider_manifest_validation"
    evidence["manifest_path"] = str(path)
    return evidence


def _compact_stdout_summary(payload: dict[str, Any]) -> dict[str, Any]:
    sections = [
        {
            "id": str(section.get("id") or ""),
            "ok": section.get("ok") is True,
            "mode": str(section.get("mode") or ""),
        }
        for section in payload.get("sections") or []
        if isinstance(section, dict)
    ]
    return {
        "ok": payload.get("ok") is True,
        "mode": str(payload.get("mode") or ""),
        "public_release_required": bool(payload.get("public_release_required") is True),
        "public_release_ready": bool(payload.get("public_release_ready") is True),
        "section_count": int(payload.get("section_count") or len(sections)),
        "failed_sections": [
            str(section)
            for section in payload.get("failed_sections") or []
            if str(section or "").strip()
        ],
        "checks": dict(payload.get("checks") or {}),
        "isolated_provider_smoke_requested": bool(
            payload.get("isolated_provider_smoke_requested") is True
        ),
        "configured_virtual_desktop_provider_requested": bool(
            payload.get("configured_virtual_desktop_provider_requested") is True
        ),
        "isolated_provider_smoke_collected": bool(
            payload.get("isolated_provider_smoke_collected") is True
        ),
        "isolated_provider_smoke_mode": str(
            payload.get("isolated_provider_smoke_mode") or ""
        ),
        "isolated_provider_dev_smoke_ready": bool(
            payload.get("isolated_provider_dev_smoke_ready") is True
        ),
        "isolated_provider_release_ready": bool(
            payload.get("isolated_provider_release_ready") is True
        ),
        "isolated_provider_release_blockers": [
            str(item)
            for item in payload.get("isolated_provider_release_blockers") or []
            if str(item or "").strip()
        ],
        "isolated_provider_backend": dict(
            payload.get("isolated_provider_backend") or {}
        ),
        "sections": sections,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--workdir",
        type=Path,
        help="Optional persistent workspace for smoke-generated files.",
    )
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
    parser.add_argument(
        "--print-full-report",
        action="store_true",
        help="Print the complete JSON report to stdout even when --report-json is set.",
    )
    parser.add_argument(
        "--run-isolated-provider-smoke",
        action="store_true",
        help=(
            "Run the isolated desktop provider smoke. This is now the default; "
            "the flag is kept for older release scripts."
        ),
    )
    parser.add_argument(
        "--skip-isolated-provider-smoke",
        action="store_true",
        help=(
            "Skip the default local isolated provider smoke. Cannot skip when a "
            "provider manifest or configured virtual provider smoke is requested."
        ),
    )
    parser.add_argument(
        "--use-configured-virtual-desktop-provider",
        action="store_true",
        help=(
            "Run the isolated provider smoke against OHA_YACHIYO_DESKTOP_PROVIDER_* "
            "instead of the local loopback harness."
        ),
    )
    parser.add_argument(
        "--provider-manifest",
        type=Path,
        help=(
            "Provider manifest JSON for the isolated provider smoke. The manifest "
            "may point to an already-running virtual desktop provider or provide "
            "an entrypoint for Oha-Yachiyo to start."
        ),
    )
    parser.add_argument(
        "--public-release",
        "--require-public-release-backend",
        dest="require_public_release_backend",
        action="store_true",
        help=(
            "Fail unless the isolated desktop provider smoke uses a real, "
            "public-release-ready virtual desktop backend."
        ),
    )
    parser.add_argument(
        "--validate-provider-manifest",
        type=Path,
        help=(
            "Validate a virtual desktop provider manifest statically and exit. "
            "This checks the provider contract fields before running the real "
            "provider smoke."
        ),
    )
    parser.add_argument(
        "--write-provider-manifest-template",
        type=Path,
        help=(
            "Write a real virtual desktop provider manifest template and exit. "
            "Use the generated file with --provider-manifest after replacing the "
            "entrypoint/backend details with a real provider."
        ),
    )
    parser.add_argument(
        "--provider-manifest-template-provider-id",
        default="oha-virtual-desktop-provider",
        help="Provider id to place in --write-provider-manifest-template output.",
    )
    parser.add_argument(
        "--provider-manifest-template-base-url",
        default=VIRTUAL_DESKTOP_PROVIDER_TEMPLATE_BASE_URL,
        help="Base URL to place in --write-provider-manifest-template output.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    if args.write_provider_manifest_template is not None:
        template = virtual_desktop_provider_manifest_template(
            provider_id=args.provider_manifest_template_provider_id,
            base_url=args.provider_manifest_template_base_url,
        )
        _write_report(args.write_provider_manifest_template, template)
        print(
            "oha virtual desktop provider manifest template: "
            f"{args.write_provider_manifest_template}",
            file=sys.stderr,
        )
        print(json.dumps(template, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    if args.validate_provider_manifest is not None:
        evidence = _provider_manifest_validation_evidence(
            args.validate_provider_manifest,
        )
        if args.report_json is not None:
            _write_report(args.report_json, evidence)
            print(
                "oha virtual desktop provider manifest validation report: "
                f"{args.report_json}",
                file=sys.stderr,
            )
        print(json.dumps(evidence, ensure_ascii=False, indent=2, sort_keys=True))
        return 0 if evidence.get("ok") is True else 1
    run_isolated_provider_smoke = (
        bool(args.run_isolated_provider_smoke)
        or not bool(args.skip_isolated_provider_smoke)
        or bool(args.use_configured_virtual_desktop_provider)
        or args.provider_manifest is not None
        or bool(args.require_public_release_backend)
    )
    evidence = run_smoke(
        workdir=args.workdir,
        run_isolated_provider_smoke=run_isolated_provider_smoke,
        use_configured_virtual_desktop_provider=bool(
            args.use_configured_virtual_desktop_provider
        ),
        provider_manifest=args.provider_manifest,
        require_public_release_backend=bool(args.require_public_release_backend),
    )
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"oha desktop agent release smoke report: {args.report_json}", file=sys.stderr)
    stdout_payload = (
        evidence
        if args.report_json is None or args.print_full_report
        else _compact_stdout_summary(evidence)
    )
    print(json.dumps(stdout_payload, ensure_ascii=False, indent=2, sort_keys=True))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
