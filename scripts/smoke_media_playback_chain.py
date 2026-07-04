#!/usr/bin/env python3
"""Smoke-test media playback planning and executable tool wiring.

The default mode is non-invasive: it verifies planner/tool dispatch wiring and
reads Apple Music status when available. Use --execute-playback to opt into a
real playback attempt.
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from pathlib import Path
from typing import Any, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.policy import (
    RuntimePolicyCompiler,
    ToolDescriptorRegistry,
    TOOL_NAME_ALIASES,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY, dispatch_tool_call
from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent.planner_execution import planner_tool_requests

MEDIA_TOOL_NAMES = {
    "media.apple_music_play",
    "media.apple_music_status",
    "media.apple_music_open_and_play",
    "media.apple_music_control",
    "media.music_app_open_and_play",
    "media.music_app_control",
    "media.system_control",
}

MEDIA_PLAYBACK_CASES: tuple[dict[str, Any], ...] = (
    {
        "id": "apple_music_open_and_play",
        "prompt": "能帮我播放 Apple Music 吗",
        "expected_intent": "media_playback",
        "expected_first_tool": "media.music_app_open_and_play",
        "expected_first_input": {"app_name": "Music"},
    },
    {
        "id": "apple_music_query_play",
        "prompt": "播放超时空辉夜姬",
        "expected_intent": "media_playback",
        "expected_first_tool": "desktop.list_apps",
        "expected_first_input": {"query": "music", "limit": 20},
        "expected_media_tool": "media.music_app_open_and_play",
        "expected_media_input": {
            "app_name": "<selected app from desktop.list_apps>",
            "selection_source": "desktop.list_apps",
            "query": "music",
        },
    },
    {
        "id": "unknown_named_media_app",
        "prompt": "open VLC play test",
        "expected_intent": "media_playback",
        "expected_first_tool": "desktop.list_apps",
        "expected_first_input": {"query": "VLC", "limit": 20},
        "expected_media_tool": "media.music_app_open_and_play",
        "expected_media_input": {"app_name": "VLC"},
    },
)


def _compiled_orchestrator_policy() -> dict[str, Any]:
    compiler = RuntimePolicyCompiler()
    return compiler.compile_tool_policy(
        "orchestrator",
        RuntimePolicyCompiler.default_tool_policy("orchestrator"),
    )


def _descriptor_tools(tools: Sequence[str]) -> list[str]:
    schemas = ToolDescriptorRegistry.model_tool_schemas(tools)
    return [
        TOOL_NAME_ALIASES.get(
            str(schema.get("function", {}).get("name") or "").strip(),
            str(schema.get("function", {}).get("name") or "").strip(),
        )
        for schema in schemas
        if isinstance(schema, dict)
    ]


def _broker() -> ToolBroker:
    return ToolBroker(
        workspace_policy={
            "default_workdir": str(PROJECT_ROOT),
            "readable_scopes": ["."],
            "writable_scopes": ["tmp"],
        },
        artifact_root=PROJECT_ROOT / "tmp" / "media-playback-chain-artifacts",
    )


def _first_media_request(requests: Sequence[dict[str, Any]]) -> dict[str, Any]:
    for request in requests:
        if str(request.get("tool") or "") in MEDIA_TOOL_NAMES:
            return dict(request)
    return {}


def _case_evidence(case: dict[str, Any], allowed_tools: Sequence[str]) -> dict[str, Any]:
    prompt = str(case["prompt"])
    decision = RuntimePlanner().decision(prompt, allowed_tools=allowed_tools)
    requests = planner_tool_requests(prompt, allowed_tools)
    plan_tools = [
        str(getattr(step, "tool_name", "") or "").strip()
        for step in decision.plan.tool_plan.steps
        if str(getattr(step, "tool_name", "") or "").strip()
    ]
    request_tools = [
        str(request.get("tool") or "").strip()
        for request in requests
        if str(request.get("tool") or "").strip()
    ]
    descriptor_tools = _descriptor_tools(sorted(set(request_tools + plan_tools)))
    first_request = dict(requests[0]) if requests else {}
    first_media_request = _first_media_request(requests)
    expected_first_tool = str(case.get("expected_first_tool") or "")
    expected_media_tool = str(case.get("expected_media_tool") or expected_first_tool)
    checks = {
        "intent_matches": decision.selected_intent.kind == str(case["expected_intent"]),
        "first_tool_matches": str(first_request.get("tool") or "") == expected_first_tool,
        "first_input_matches": (
            dict(first_request.get("input") or {}) == dict(case.get("expected_first_input") or {})
            if "expected_first_input" in case
            else True
        ),
        "media_tool_present": str(first_media_request.get("tool") or "") == expected_media_tool,
        "media_input_matches": (
            dict(first_media_request.get("input") or {}) == dict(case.get("expected_media_input") or {})
            if "expected_media_input" in case
            else True
        ),
        "request_tools_dispatched": all(tool in TOOL_DISPATCH_REGISTRY for tool in request_tools),
        "request_tools_allowed_by_policy": all(tool in allowed_tools for tool in request_tools),
        "request_tools_have_descriptors": set(request_tools).issubset(set(descriptor_tools)),
    }
    return {
        "id": str(case["id"]),
        "ok": all(checks.values()),
        "prompt": prompt,
        "intent_kind": decision.selected_intent.kind,
        "intent_inputs": dict(decision.selected_intent.inputs),
        "plan_tools": plan_tools,
        "request_tools": request_tools,
        "first_request": first_request,
        "first_media_request": first_media_request,
        "descriptor_tools": descriptor_tools,
        "checks": checks,
    }


def _is_structured_tool_result(result: Any, *, action: str) -> bool:
    if not isinstance(result, dict):
        return False
    return (
        result.get("action") == action
        and isinstance(result.get("ok"), bool)
        and isinstance(result.get("summary"), str)
        and isinstance(result.get("permission_error"), bool)
        and isinstance(result.get("fallback_used"), bool)
    )


def _apple_music_status_evidence(broker: ToolBroker) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {
            "ok": True,
            "skipped": True,
            "reason": "Apple Music status smoke only runs on macOS",
            "platform": platform.system(),
            "checks": {"status_result_structured": True},
        }
    result = dispatch_tool_call(broker, "media.apple_music_status", {}, approved=True)
    checks = {
        "status_result_structured": _is_structured_tool_result(
            result,
            action="media.apple_music_status",
        ),
    }
    return {
        "ok": all(checks.values()),
        "skipped": False,
        "platform": platform.system(),
        "result": result,
        "checks": checks,
    }


def _playback_state(result: Any) -> str:
    if not isinstance(result, dict):
        return ""
    data = result.get("data") if isinstance(result.get("data"), dict) else {}
    return str(data.get("player_state") or "").strip()


def _playback_attempt_evidence(
    broker: ToolBroker,
    *,
    restore_playback_state: bool,
    require_playback_ok: bool,
) -> dict[str, Any]:
    if platform.system() != "Darwin":
        return {
            "ok": True,
            "skipped": True,
            "reason": "Real media playback smoke only runs on macOS",
            "platform": platform.system(),
            "checks": {"playback_result_structured": True},
        }

    before_status = dispatch_tool_call(broker, "media.apple_music_status", {}, approved=True)
    playback_result = dispatch_tool_call(
        broker,
        "media.music_app_open_and_play",
        {"app_name": "Music"},
        approved=True,
    )
    after_status = dispatch_tool_call(broker, "media.apple_music_status", {}, approved=True)
    restore_result: dict[str, Any] = {}
    final_status: dict[str, Any] = dict(after_status) if isinstance(after_status, dict) else {}
    restore_needed = restore_playback_state and _playback_state(before_status) != "playing"
    if (
        restore_needed
        and playback_result.get("ok") is True
    ):
        restore_result = dispatch_tool_call(
            broker,
            "media.apple_music_control",
            {"action": "pause"},
            approved=True,
        )
        time.sleep(0.5)
        final_status = dispatch_tool_call(broker, "media.apple_music_status", {}, approved=True)

    expected_actions = {
        "media.music_app_open_and_play",
        "media.apple_music_open_and_play",
    }
    checks = {
        "playback_result_structured": (
            isinstance(playback_result, dict)
            and str(playback_result.get("action") or "") in expected_actions
            and isinstance(playback_result.get("ok"), bool)
            and isinstance(playback_result.get("summary"), str)
            and isinstance(playback_result.get("permission_error"), bool)
            and isinstance(playback_result.get("fallback_used"), bool)
        ),
        "playback_ok": playback_result.get("ok") is True if require_playback_ok else True,
        "restore_not_left_playing": (
            _playback_state(final_status) != "playing"
            if restore_needed and playback_result.get("ok") is True
            else True
        ),
    }
    return {
        "ok": all(checks.values()),
        "skipped": False,
        "platform": platform.system(),
        "before_status": before_status,
        "playback_result": playback_result,
        "after_status": after_status,
        "restore_result": restore_result,
        "final_status": final_status,
        "restore_requested": restore_playback_state,
        "restore_needed": restore_needed,
        "require_playback_ok": require_playback_ok,
        "checks": checks,
    }


def run_smoke(
    *,
    execute_playback: bool = False,
    restore_playback_state: bool = True,
    require_playback_ok: bool = False,
) -> dict[str, Any]:
    policy = _compiled_orchestrator_policy()
    allowed_tools = [str(tool) for tool in policy.get("allowed_tools") or []]
    cases = [_case_evidence(case, allowed_tools) for case in MEDIA_PLAYBACK_CASES]
    broker = _broker()
    status_evidence = _apple_music_status_evidence(broker)
    playback_evidence = (
        _playback_attempt_evidence(
            broker,
            restore_playback_state=restore_playback_state,
            require_playback_ok=require_playback_ok,
        )
        if execute_playback
        else {
            "ok": True,
            "skipped": True,
            "reason": "pass --execute-playback to attempt real Apple Music playback",
            "checks": {"playback_result_structured": True},
        }
    )
    return {
        "ok": (
            all(case["ok"] for case in cases)
            and status_evidence.get("ok") is True
            and playback_evidence.get("ok") is True
        ),
        "mode": "media_playback_chain_smoke",
        "execute_playback": execute_playback,
        "case_count": len(cases),
        "cases": cases,
        "apple_music_status": status_evidence,
        "playback_attempt": playback_evidence,
    }


def _write_report(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path, help="Optional JSON evidence report path.")
    parser.add_argument(
        "--execute-playback",
        action="store_true",
        help="Opt into a real Apple Music open-and-play attempt.",
    )
    parser.add_argument(
        "--no-restore-playback-state",
        action="store_true",
        help="Do not pause Apple Music after an opt-in playback attempt.",
    )
    parser.add_argument(
        "--require-playback-ok",
        action="store_true",
        help="Fail the opt-in playback smoke unless playback_result.ok is true.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    evidence = run_smoke(
        execute_playback=args.execute_playback,
        restore_playback_state=not args.no_restore_playback_state,
        require_playback_ok=args.require_playback_ok,
    )
    if args.report_json is not None:
        _write_report(args.report_json, evidence)
        print(f"media playback chain smoke report: {args.report_json}", file=sys.stderr)
    print(json.dumps(evidence, ensure_ascii=False, indent=2))
    return 0 if evidence.get("ok") is True else 1


if __name__ == "__main__":
    raise SystemExit(main())
