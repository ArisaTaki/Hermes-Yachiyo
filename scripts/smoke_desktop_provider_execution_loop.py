#!/usr/bin/env python3
"""Smoke-test planner-to-provider desktop execution and replan behavior."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Mapping, Sequence

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from apps.shell.agent.runtime.desktop_execution_providers import (
    DesktopExecutionProviderRegistry,
)
from apps.shell.agent.runtime.tool_execution import (
    RuntimeToolCallExecutor,
    RuntimeToolRequestRunner,
)
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.yachiyo_agent import RuntimePlanner
from apps.shell.yachiyo_agent.daily_desktop import daily_desktop_allowed_tools
from apps.shell.yachiyo_agent.runtime_execution import (
    runtime_execution_blocked_requests_from_envelope_payload,
    runtime_execution_envelope_from_decision,
    runtime_execution_requests_from_envelope_payload,
)

SMOKE_APP_NAME = "PixelForge"
SMOKE_PROVIDER_ID = "sandbox-smoke-provider"
SMOKE_PROMPT = f"打开 {SMOKE_APP_NAME}"
SMOKE_POLICY = {"desktop_execution_policy": {"mode": "sandbox_preferred"}}


class _FakeBudget:
    def __init__(self) -> None:
        self.claims: list[tuple[str, bool]] = []

    def claim_tool_call(
        self,
        tool_name: str,
        *,
        terminal_execution: bool = False,
    ) -> None:
        self.claims.append((tool_name, terminal_execution))


class _FakeToolCallEvents:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []

    def denied(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("denied", args, kwargs))

    def requested(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("requested", args, kwargs))

    def failed(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("failed", args, kwargs))

    def started(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("started", args, kwargs))

    def result(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("result", args, kwargs))

    def agent_tool_call(self, *args: Any, **kwargs: Any) -> None:
        self.calls.append(("agent_tool_call", args, kwargs))


class _FakeTraceEvents:
    def memory_skill_trace_event(
        self,
        _tool_name: str,
        _input_preview: Any,
        _tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        return None

    def artifact_created_payload(
        self,
        _tool_result: dict[str, Any],
        *,
        run_id: str,
        source_tool: str = "artifact.write",
    ) -> dict[str, Any]:
        return {"run_id": run_id, "source_tool": source_tool}


class _FakeBroker:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def call(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((tool_name, dict(payload), approved))
        return {"ok": True, "tool": tool_name, "unexpected_broker_fallback": True}


class _FakeSandboxDesktopAdapter:
    provider_kind = "sandbox_desktop"
    provider_id = SMOKE_PROVIDER_ID

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def can_execute(
        self,
        tool_name: str,
        _route: Mapping[str, Any],
        _tool_request: Mapping[str, Any],
    ) -> bool:
        return tool_name == "app.open"

    def execute(
        self,
        tool_name: str,
        payload: Mapping[str, Any],
        *,
        tool_request: Mapping[str, Any],
        route: Mapping[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": tool_name,
                "payload": dict(payload),
                "route": dict(route),
                "approved": approved,
                "broker_call_count": len(getattr(broker, "calls", [])),
                "request_id": str(tool_request.get("request_id") or ""),
            }
        )
        return {
            "ok": True,
            "tool": tool_name,
            "action": tool_name,
            "summary": f"Opened {payload.get('app_name')}",
            "data": {
                "app_name": str(payload.get("app_name") or ""),
                "running": True,
                "provider_id": SMOKE_PROVIDER_ID,
            },
        }


class _FakePendingApprovalBuilder:
    def build(
        self,
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return {
            "approval_id": "desktop-provider-smoke-approval",
            "tool": tool_request.get("tool"),
            "messages": messages,
            "next_iteration": next_iteration,
            "remaining_tool_requests": remaining_tool_requests,
        }


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def _allowed_tools() -> list[str]:
    tools = list(daily_desktop_allowed_tools())
    if "desktop.provider_session.start" not in tools:
        tools.append("desktop.provider_session.start")
    return tools


def _append_run_event_factory(
    run_events: list[tuple[str, str, dict[str, Any]]],
):
    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> None:
        run_events.append((run_id, event_type, payload))

    return append_run_event


def _executor(
    registry: DesktopExecutionProviderRegistry,
    run_events: list[tuple[str, str, dict[str, Any]]],
    tool_call_events: _FakeToolCallEvents,
) -> RuntimeToolCallExecutor:
    return RuntimeToolCallExecutor(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: _FakeBudget(),
        validate_tool_payload=lambda _tool_name, _payload: None,
        limit_tool_result=lambda result: result,
        timeline_factory=_timeline,
        tool_call_events=tool_call_events,
        trace_events=_FakeTraceEvents(),
        append_run_event=_append_run_event_factory(run_events),
        desktop_provider_registry=registry,
    )


def _runner(
    executor: RuntimeToolCallExecutor,
    run_events: list[tuple[str, str, dict[str, Any]]],
) -> RuntimeToolRequestRunner:
    return RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: _FakeBudget(),
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda _user_goal, _tool_name: "",
        timeline_factory=_timeline,
        append_run_event=_append_run_event_factory(run_events),
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=_FakePendingApprovalBuilder(),
        call_agent_tool=executor.execute,
    )


def _planner_snapshot() -> dict[str, Any]:
    allowed_tools = _allowed_tools()
    decision = RuntimePlanner().decision(
        SMOKE_PROMPT,
        allowed_tools=allowed_tools,
        metadata=SMOKE_POLICY,
    )
    envelope = runtime_execution_envelope_from_decision(
        decision,
        allowed_tools=allowed_tools,
        direct=True,
        metadata=SMOKE_POLICY,
    )
    executable = runtime_execution_requests_from_envelope_payload(
        envelope,
        allowed_tools=allowed_tools,
    )
    blocked = runtime_execution_blocked_requests_from_envelope_payload(
        envelope,
        allowed_tools=allowed_tools,
    )
    app_open = next(
        (
            request
            for request in blocked
            if str(request.get("tool") or "") == "app.open"
        ),
        {},
    )
    route = (
        app_open.get("desktop_execution_route")
        if isinstance(app_open.get("desktop_execution_route"), dict)
        else {}
    )
    sandbox_provider = (
        app_open.get("sandbox_provider")
        if isinstance(app_open.get("sandbox_provider"), dict)
        else {}
    )
    return {
        "decision": decision,
        "envelope": envelope,
        "executable": executable,
        "blocked": blocked,
        "app_open": app_open,
        "tool_steps": [step.tool_name for step in decision.plan.tool_plan.steps],
        "executable_tools": [
            str(request.get("tool") or "") for request in executable
        ],
        "blocked_tools": [str(request.get("tool") or "") for request in blocked],
        "route_status": str(route.get("status") or ""),
        "route_selected_provider_kind": str(route.get("selected_provider_kind") or ""),
        "route_blocking_conditions": [
            str(item)
            for item in route.get("blocking_conditions", [])
            if str(item or "").strip()
        ],
        "sandbox_provider_status": str(sandbox_provider.get("status") or ""),
    }


def _routable_provider_request(app_open_request: Mapping[str, Any]) -> dict[str, Any]:
    request = {
        str(key): value
        for key, value in app_open_request.items()
        if str(key) != "desktop_execution_route"
    }
    request["input_resolution"] = {
        "field": "app_name",
        "requested_app_name": SMOKE_APP_NAME,
        "resolved_app_name": SMOKE_APP_NAME,
        "source_tool": "desktop.list_apps",
    }
    request["sandbox_provider"] = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "sandbox_desktop",
        "provider_id": SMOKE_PROVIDER_ID,
        "status": "available",
        "supported_tools": ["app.open"],
    }
    request["desktop_provider_session"] = {
        "running": True,
        "started": True,
        "status": "running",
        "provider_id": SMOKE_PROVIDER_ID,
        "tool_names": ["app.open"],
        "desktop_session_kind": "isolated_desktop",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
    }
    return request


def _provider_execution_case(app_open_request: Mapping[str, Any]) -> dict[str, Any]:
    adapter = _FakeSandboxDesktopAdapter()
    broker = _FakeBroker()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    tool_call_events = _FakeToolCallEvents()
    timeline: list[dict[str, Any]] = []
    request = _routable_provider_request(app_open_request)
    result = _executor(
        DesktopExecutionProviderRegistry([adapter]),
        run_events,
        tool_call_events,
    ).execute(
        request,
        _allowed_tools(),
        broker,
        timeline,
        run_id="desktop-provider-smoke-run",
    )
    route = (
        result.get("desktop_execution_route")
        if isinstance(result.get("desktop_execution_route"), dict)
        else {}
    )
    session = (
        result.get("desktop_provider_session")
        if isinstance(result.get("desktop_provider_session"), dict)
        else {}
    )
    events = [str(event.get("event") or "") for event in timeline]
    checks = {
        "adapter_called_once": len(adapter.calls) == 1,
        "broker_not_called": broker.calls == [],
        "provider_result_ok": result.get("ok") is True,
        "provider_routed": result.get("desktop_execution_provider_routed") is True,
        "route_is_sandbox_ready": route.get("status") == "sandbox_ready",
        "route_requires_provider_execution": (
            route.get("provider_execution_required") is True
        ),
        "timeline_records_provider_execution": (
            "desktop.provider_execution.routed" in events
        ),
        "no_foreground_takeover_secret_leak": (
            "command" not in session and "env" not in session
        ),
        "provider_session_isolated": session.get("desktop_session_isolated") is True,
        "no_skip": "agent.tool.skipped" not in events,
    }
    return {
        "id": "provider_execution",
        "ok": all(checks.values()),
        "checks": checks,
        "events": events,
        "run_event_types": [event_type for _run_id, event_type, _payload in run_events],
        "tool_call_event_types": [name for name, _args, _kwargs in tool_call_events.calls],
        "adapter_calls": adapter.calls,
        "broker_calls": broker.calls,
        "result": _provider_result_summary(result),
    }


def _provider_unavailable_replan_case(
    app_open_request: Mapping[str, Any],
) -> dict[str, Any]:
    broker = _FakeBroker()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    tool_call_events = _FakeToolCallEvents()
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": SMOKE_PROMPT}]
    request = _routable_provider_request(app_open_request)
    executor = _executor(
        DesktopExecutionProviderRegistry(),
        run_events,
        tool_call_events,
    )
    _runner(executor, run_events).run(
        [request],
        _allowed_tools(),
        broker,
        messages,
        timeline,
        [],
        next_iteration=2,
        run_id="desktop-provider-unavailable-smoke-run",
    )
    events = [str(event.get("event") or "") for event in timeline]
    tool_call = next(
        (
            event
            for event in timeline
            if str(event.get("event") or "") == "agent.tool.call"
        ),
        {},
    )
    result = (
        tool_call.get("result")
        if isinstance(tool_call.get("result"), dict)
        else {}
    )
    replan = next(
        (
            event
            for event in timeline
            if str(event.get("event") or "") == "agent.replan.requested"
        ),
        {},
    )
    replan_payload = (
        replan.get("payload")
        if isinstance(replan.get("payload"), dict)
        else {}
    )
    recovery_tools = [
        str(action.get("tool") or "")
        for action in result.get("recovery_actions", [])
        if isinstance(action, dict)
    ]
    fallback_tools = [
        str(tool)
        for tool in replan_payload.get("fallback_tools", [])
        if str(tool or "").strip()
    ]
    checks = {
        "broker_not_called": broker.calls == [],
        "provider_unavailable_result": result.get("status") == "provider_unavailable",
        "provider_failure_routed": (
            result.get("desktop_execution_provider_routed") is True
        ),
        "recovery_starts_provider": (
            "desktop.provider_session.start" in recovery_tools
        ),
        "timeline_requests_replan": "agent.replan.requested" in events,
        "replan_trigger_is_provider_unavailable": (
            replan_payload.get("trigger") == "desktop_execution_provider_unavailable"
        ),
        "replan_fallback_starts_provider": (
            "desktop.provider_session.start" in fallback_tools
        ),
        "run_events_project_replan": any(
            event_type == "agent.replan.requested"
            for _run_id, event_type, _payload in run_events
        ),
        "approval_required_recovery_not_auto_enqueued": (
            "agent.deferred_continuation.enqueued" not in events
        ),
    }
    return {
        "id": "provider_unavailable_replan",
        "ok": all(checks.values()),
        "checks": checks,
        "events": events,
        "run_event_types": [event_type for _run_id, event_type, _payload in run_events],
        "tool_call_event_types": [name for name, _args, _kwargs in tool_call_events.calls],
        "broker_calls": broker.calls,
        "result": _provider_result_summary(result),
        "replan": _replan_summary(replan_payload),
    }


def _provider_result_summary(result: Mapping[str, Any]) -> dict[str, Any]:
    route = (
        result.get("desktop_execution_route")
        if isinstance(result.get("desktop_execution_route"), Mapping)
        else {}
    )
    provider = (
        result.get("desktop_execution_provider")
        if isinstance(result.get("desktop_execution_provider"), Mapping)
        else {}
    )
    session = (
        result.get("desktop_provider_session")
        if isinstance(result.get("desktop_provider_session"), Mapping)
        else {}
    )
    return {
        "ok": result.get("ok"),
        "tool": str(result.get("tool") or ""),
        "status": str(result.get("status") or ""),
        "error": str(result.get("error") or ""),
        "summary": str(result.get("summary") or ""),
        "desktop_execution_provider_routed": result.get(
            "desktop_execution_provider_routed"
        ),
        "provider_id": str(provider.get("provider_id") or ""),
        "adapter_registered": provider.get("adapter_registered"),
        "route_status": str(route.get("status") or ""),
        "route_provider_execution_required": route.get("provider_execution_required"),
        "session_provider_id": str(session.get("provider_id") or ""),
        "session_isolated": session.get("desktop_session_isolated"),
        "recovery_tools": [
            str(action.get("tool") or "")
            for action in result.get("recovery_actions", [])
            if isinstance(action, Mapping)
        ],
    }


def _replan_summary(replan_payload: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "request_id": str(replan_payload.get("request_id") or ""),
        "trigger": str(replan_payload.get("trigger") or ""),
        "source_tool_name": str(replan_payload.get("source_tool_name") or ""),
        "fallback_tools": [
            str(tool)
            for tool in replan_payload.get("fallback_tools", [])
            if str(tool or "").strip()
        ],
    }


def run_smoke() -> dict[str, Any]:
    planner = _planner_snapshot()
    planner_checks = {
        "intent_is_desktop_operation": (
            planner["decision"].selected_intent.kind == "desktop_operation"
        ),
        "tool_plan_is_discover_operate_verify": planner["tool_steps"]
        == ["desktop.list_apps", "app.open", "desktop.verify"],
        "app_open_blocked_until_provider": "app.open" in planner["blocked_tools"],
        "executable_requests_skip_blocked_app_open": (
            "app.open" not in planner["executable_tools"]
        ),
        "blocked_route_requires_sandbox_provider": (
            planner["route_status"] == "provider_required"
            and planner["route_selected_provider_kind"] == "sandbox_desktop"
        ),
        "blocked_route_explains_provider_requirement": (
            "sandbox_desktop_provider_required"
            in planner["route_blocking_conditions"]
        ),
    }
    provider_execution = _provider_execution_case(planner["app_open"])
    provider_unavailable = _provider_unavailable_replan_case(planner["app_open"])
    checks = {
        "planner_blocks_provider_required_app_open": all(planner_checks.values()),
        "provider_executes_sandbox_ready_request": provider_execution["ok"] is True,
        "provider_unavailable_requests_replan": provider_unavailable["ok"] is True,
    }
    return {
        "ok": all(checks.values()),
        "mode": "desktop_provider_execution_loop_smoke",
        "prompt": SMOKE_PROMPT,
        "checks": checks,
        "planner": {
            "ok": all(planner_checks.values()),
            "checks": planner_checks,
            "tool_steps": planner["tool_steps"],
            "executable_tools": planner["executable_tools"],
            "blocked_tools": planner["blocked_tools"],
            "route_status": planner["route_status"],
            "route_selected_provider_kind": planner["route_selected_provider_kind"],
            "route_blocking_conditions": planner["route_blocking_conditions"],
            "sandbox_provider_status": planner["sandbox_provider_status"],
        },
        "provider_execution": provider_execution,
        "provider_unavailable_replan": provider_unavailable,
    }


def _write_report(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report-json", type=Path)
    parser.add_argument("--pretty", action="store_true")
    args = parser.parse_args(argv)
    report = run_smoke()
    if args.report_json:
        _write_report(args.report_json, report)
    print(json.dumps(report, ensure_ascii=False, indent=2 if args.pretty else None))
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
