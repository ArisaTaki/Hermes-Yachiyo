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


def _event_types(events: Sequence[dict[str, Any]]) -> list[str]:
    return [str(event.get("event_type") or "") for event in events if isinstance(event, dict)]


def _first_event(events: Sequence[dict[str, Any]], event_type: str) -> dict[str, Any]:
    for event in events:
        if isinstance(event, dict) and event.get("event_type") == event_type:
            return event
    return {}


def _payload(event: dict[str, Any]) -> dict[str, Any]:
    payload = event.get("payload") if isinstance(event, dict) else {}
    return payload if isinstance(payload, dict) else {}


def _model_event_free(events: Sequence[dict[str, Any]]) -> bool:
    return not any(
        event_type in {"model.request.started", "model.requested"}
        for event_type in _event_types(events)
    )


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
            ):
                cases = [
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
