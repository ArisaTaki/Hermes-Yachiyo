"""Tests for tool-call execution split out of the legacy runtime."""

from __future__ import annotations

import hashlib
import json
import subprocess
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime import tool_execution as tool_execution_module
from apps.shell.agent.runtime.desktop_execution_providers import (
    LOCAL_DESKTOP_PROVIDER_ID,
    LOCAL_DESKTOP_PROVIDER_KIND,
    DesktopExecutionProviderRegistry,
    LocalDesktopExecutionProviderAdapter,
)
from apps.shell.agent.runtime.errors import (
    AgentApprovalRequired,
    AgentDirectOutcomeUnverified,
    AgentRuntimeError,
)
from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.goal_runtime import runtime_goal_assessment
from apps.shell.agent.runtime.outcome_evaluator import evaluate_main_chat_outcome
from apps.shell.agent.runtime.recovery_lineage import (
    RUNTIME_PRIVATE_RECOVERY_AUTHORITY,
    RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY,
    RUNTIME_PRIVATE_RECOVERY_CONTEXT_VERSION,
)
from apps.shell.agent.runtime.tool_approvals import ToolPendingApprovalBuilder
from apps.shell.agent.runtime.tool_execution import (
    RuntimeToolCallExecutor,
    RuntimeToolRequestRunner,
)
from apps.shell.agent.runtime.tool_loop import (
    RuntimeToolLoopProjectionBuilder,
    assistant_message_for_history,
    stage_tool_result_messages,
)
from apps.shell.agent.tools import desktop as desktop_tools
from apps.shell.agent.tools.broker import ToolBroker
from apps.shell.agent.tools.plugins import (
    RestrictedPluginTool,
    RestrictedToolPlugin,
    clear_restricted_tool_plugins,
    register_restricted_tool_plugin,
)
from apps.shell.agent.tools.policy import ToolDescriptorRegistry
from apps.shell.agent.tools.registry import dispatch_tool_call
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore
from apps.shell.yachiyo_agent.contracts import PublicRunEvent
from apps.shell.yachiyo_agent.tool_call_event_snapshots import (
    tool_call_snapshots_from_events,
)


class FakeBudget:
    def __init__(self) -> None:
        self.claims: list[tuple[str, bool]] = []

    def claim_tool_call(self, tool_name: str, *, terminal_execution: bool = False) -> None:
        self.claims.append((tool_name, terminal_execution))


def test_runtime_replan_respects_explicit_fail_closed_handoff() -> None:
    assert tool_execution_module._tool_event_requests_runtime_replan(
        {"event": "agent.tool.failed"},
        {
            "ok": False,
            "status": "blocked",
            "error": "browser_owned_target_required",
            "user_handoff_required": True,
            "replan_allowed": False,
        },
    ) is False


class FakeToolCallEvents:
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


class FakeTraceEvents:
    def memory_skill_trace_event(
        self,
        tool_name: str,
        input_preview: Any,
        tool_result: dict[str, Any],
    ) -> dict[str, Any] | None:
        if tool_name != "memory.add":
            return None
        return {
            "event_type": "memory.write.add",
            "payload": {"tool": tool_name, "input_preview": input_preview, "ok": tool_result.get("ok")},
        }

    def artifact_created_payload(
        self,
        tool_result: dict[str, Any],
        *,
        run_id: str,
        source_tool: str = "artifact.write",
    ) -> dict[str, Any]:
        artifact = tool_result.get("artifact") if isinstance(tool_result.get("artifact"), dict) else {}
        payload = {
            "run_id": run_id,
            "path": artifact.get("path") or tool_result.get("path"),
            "source_tool": source_tool,
        }
        if artifact:
            payload["artifact"] = {**artifact, "source_tool": source_tool}
        return payload


class FakeBroker:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.calls: list[tuple[str, dict[str, Any], bool]] = []

    def call(self, tool_name: str, payload: dict[str, Any], *, approved: bool = False) -> dict[str, Any]:
        self.calls.append((tool_name, payload, approved))
        if isinstance(self.result, Exception):
            raise self.result
        return dict(self.result)


class FakePermissionPreflightBroker(FakeBroker):
    def __init__(
        self,
        result: dict[str, Any] | Exception,
        preflight_result: dict[str, Any],
    ) -> None:
        super().__init__(result)
        self.preflight_result = dict(preflight_result)
        self.preflight_calls = 0

    def desktop_permission_preflight(self) -> dict[str, Any]:
        self.preflight_calls += 1
        return dict(self.preflight_result)


class FakeSandboxDesktopAdapter:
    provider_kind = "sandbox_desktop"
    provider_id = "sandbox-1"

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def can_execute(
        self,
        tool_name: str,
        route: dict[str, Any],
        tool_request: dict[str, Any],
    ) -> bool:
        return tool_name in {
            "desktop.click_ui_element",
            "desktop.safe_type_text",
            "desktop.ui_elements",
        }

    def execute(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        tool_request: dict[str, Any],
        route: dict[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.calls.append(
            {
                "tool": tool_name,
                "payload": dict(payload),
                "route": dict(route),
                "approved": approved,
            }
        )
        return {
            "ok": True,
            "tool": tool_name,
            "summary": "Executed in sandbox desktop provider",
            "data": {"text": str(payload.get("text") or "")},
        }


class FakeOwnedBackgroundAdapter:
    provider_kind = "background_desktop"
    provider_id = "owned-background-1"
    supported_tools = ["desktop.read_ui"]

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def owns_task_scope(self, tool_request: dict[str, Any]) -> bool:
        return isinstance(tool_request.get("_runtime_execution_scope"), dict)

    def can_execute(
        self,
        tool_name: str,
        route: dict[str, Any],
        tool_request: dict[str, Any],
    ) -> bool:
        del route, tool_request
        return tool_name in self.supported_tools

    def execute(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        tool_request: dict[str, Any],
        route: dict[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        del tool_request, broker
        self.calls.append(
            {
                "tool": tool_name,
                "payload": dict(payload),
                "route": dict(route),
                "approved": approved,
            }
        )
        return {
            "ok": True,
            "tool": tool_name,
            "action": tool_name,
            "summary": "Observed the provider-owned background target",
            "data": {"target_bound": True, "frontmost": False},
        }


class FakeTrustedVerificationAdapter:
    provider_kind = "background_desktop"
    provider_id = "trusted-background-verifier"
    supported_tools = ["app.open", "desktop.verify"]

    def __init__(self) -> None:
        self.verification_contexts: list[Any] = []

    def owns_task_scope(self, tool_request: dict[str, Any]) -> bool:
        return isinstance(tool_request.get("_runtime_execution_scope"), dict)

    def can_execute(
        self,
        tool_name: str,
        route: dict[str, Any],
        tool_request: dict[str, Any],
    ) -> bool:
        del route, tool_request
        return tool_name in self.supported_tools

    def execute(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        tool_request: dict[str, Any],
        route: dict[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        del payload, route, broker, approved
        if tool_name == "app.open":
            return {
                "ok": True,
                "tool": tool_name,
                "action": tool_name,
                "name": "Notes",
                "pid": 4401,
                "window_id": 77,
                "agent_owned_target": True,
                "self_activation_suppressed": True,
            }
        self.verification_contexts.append(
            tool_request.get("_runtime_verification_context")
        )
        return {
            "ok": True,
            "tool": tool_name,
            "action": tool_name,
            "observation_verified": True,
            "postcondition_verified": False,
        }


class FakeTrustedTypedContentVerificationAdapter(FakeTrustedVerificationAdapter):
    supported_tools = ["desktop.type_into_ui_element", "desktop.verify"]

    def execute(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        tool_request: dict[str, Any],
        route: dict[str, Any],
        broker: Any,
        approved: bool = False,
    ) -> dict[str, Any]:
        del payload, route, broker, approved
        if tool_name == "desktop.type_into_ui_element":
            return {
                "ok": True,
                "tool": tool_name,
                "action": tool_name,
                "action_dispatched": True,
                "app_name": "Notes",
                "pid": 4401,
                "window_id": 77,
                "agent_owned_target": True,
                "grounded_element": {
                    "pid": 4401,
                    "window_id": 77,
                    "role": "AXTextArea",
                },
            }
        self.verification_contexts.append(
            tool_request.get("_runtime_verification_context")
        )
        return {
            "ok": True,
            "tool": tool_name,
            "action": tool_name,
            "observation_verified": True,
            "postcondition_verified": False,
        }


class FakePendingApprovalBuilder:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def build(
        self,
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        pending = {
            "approval_id": "approval-1",
            "tool": tool_request.get("tool"),
            "messages": messages,
            "next_iteration": next_iteration,
            "remaining_tool_requests": remaining_tool_requests,
        }
        self.calls.append(pending)
        return pending


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}


def _last_event(timeline: list[dict[str, Any]], event_name: str) -> dict[str, Any]:
    return next(event for event in reversed(timeline) if event["event"] == event_name)


def _input_resolution_tool_call_id(timeline: list[dict[str, Any]]) -> str:
    tool_call_id = str(
        _last_event(timeline, "agent.tool.input_resolved").get("tool_call_id") or ""
    )
    assert tool_call_id.startswith("call_")
    return tool_call_id


def _executor(
    *,
    tool_call_events: FakeToolCallEvents,
    trace_events: FakeTraceEvents | None = None,
    run_events: list[tuple[str, str, dict[str, Any]]] | None = None,
    allows_tool=None,
    desktop_provider_registry: Any | None = None,
    execution_lease_checker=None,
    validate_tool_payload=None,
) -> RuntimeToolCallExecutor:
    run_events = run_events if run_events is not None else []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        run_events.append((run_id, event_type, payload))

    return RuntimeToolCallExecutor(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: FakeBudget(),
        validate_tool_payload=(
            validate_tool_payload
            if validate_tool_payload is not None
            else lambda _tool_name, _payload: None
        ),
        limit_tool_result=lambda result: result,
        timeline_factory=_timeline,
        tool_call_events=tool_call_events,
        trace_events=trace_events or FakeTraceEvents(),
        append_run_event=append_run_event,
        allows_tool=allows_tool,
        desktop_provider_registry=desktop_provider_registry,
        execution_lease_checker=execution_lease_checker,
    )


def _runner(
    *,
    call_agent_tool,
    pending_approval_builder: FakePendingApprovalBuilder | None = None,
    run_events: list[tuple[str, str, dict[str, Any]]] | None = None,
) -> RuntimeToolRequestRunner:
    run_events = run_events if run_events is not None else []

    def append_run_event(run_id: str, event_type: str, payload: dict[str, Any]) -> None:
        run_events.append((run_id, event_type, payload))

    return RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: FakeBudget(),
        user_goal_from_messages=lambda messages: str(messages[0].get("content") or ""),
        goal_disallows_tool=lambda user_goal, tool_name: (
            "no terminal"
            if tool_name == "terminal.run" and "no commands" in user_goal
            else ""
        ),
        timeline_factory=_timeline,
        append_run_event=append_run_event,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=pending_approval_builder or FakePendingApprovalBuilder(),
        call_agent_tool=call_agent_tool,
    )


def _missing_accessibility_preflight() -> dict[str, Any]:
    return {
        "ok": True,
        "action": "desktop.permission_preflight",
        "permission_error": True,
        "permission_targets": ["accessibility"],
        "affected_tools": [
            "app.open_and_safe_type_text",
            "desktop.safe_shortcut",
        ],
        "recovery_actions": [
            {
                "label": "Open Accessibility settings",
                "tool": "system.settings_open",
                "input": {"target": "accessibility"},
                "permission_target": "accessibility",
                "risk_level": "low",
            }
        ],
        "diagnostic_route": "/yachiyo/readiness",
        "data": {
            "ready": False,
            "permission_targets": ["accessibility"],
            "affected_tools": [
                "app.open_and_safe_type_text",
                "desktop.safe_shortcut",
            ],
        },
    }


def test_runner_permission_preflight_blocks_split_foreground_plan_before_first_mutation() -> None:
    executed: list[str] = []
    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "Open Notes, type hello, then copy"}]
    broker = FakePermissionPreflightBroker(
        {"ok": True},
        _missing_accessibility_preflight(),
    )

    _runner(
        call_agent_tool=lambda request, *_args, **_kwargs: executed.append(
            str(request.get("tool") or "")
        )
        or {"ok": True}
    ).run(
        [
            {"tool": "app.open", "input": {"app_name": "Notes"}, "step_id": "open"},
            {"tool": "app.focus", "input": {"app_name": "Notes"}, "step_id": "focus"},
            {
                "tool": "desktop.active_window",
                "input": {},
                "step_id": "verify-focus",
            },
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "step_id": "type",
            },
            {
                "tool": "desktop.safe_shortcut",
                "input": {"action": "copy"},
                "step_id": "copy",
            },
        ],
        [
            "app.open",
            "app.focus",
            "desktop.active_window",
            "desktop.safe_type_text",
            "desktop.safe_shortcut",
        ],
        broker,
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-permission-preflight",
        budget=FakeBudget(),
    )

    assert broker.preflight_calls == 1
    assert executed == []
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    assert skipped["detail"] == "app.open"
    assert skipped["result"]["blocked_by_permission_preflight"] is True
    assert skipped["result"]["permission_targets"] == ["accessibility"]
    assert skipped["result"]["affected_tools"] == [
        "app.open_and_safe_type_text",
        "desktop.safe_shortcut",
    ]
    assert skipped["result"]["user_handoff_required"] is True
    assert skipped["result"]["replan_allowed"] is False
    assert not any(event["event"] == "agent.replan.requested" for event in timeline)
    assert "accessibility" in messages[-1]["content"]


def test_runner_permission_preflight_allows_unaffected_read_only_diagnostics() -> None:
    executed: list[str] = []
    broker = FakePermissionPreflightBroker(
        {"ok": True},
        _missing_accessibility_preflight(),
    )

    _runner(
        call_agent_tool=lambda request, *_args, **_kwargs: executed.append(
            str(request.get("tool") or "")
        )
        or {"ok": True}
    ).run(
        [
            {"tool": "desktop.permissions", "input": {}},
            {"tool": "desktop.list_apps", "input": {"query": "Notes"}},
            {
                "tool": "system.settings_open",
                "input": {"target": "accessibility"},
            },
        ],
        ["desktop.permissions", "desktop.list_apps", "system.settings_open"],
        broker,
        [{"role": "user", "content": "Open Accessibility settings"}],
        [],
        [],
        next_iteration=1,
        budget=FakeBudget(),
    )

    assert executed == [
        "desktop.permissions",
        "desktop.list_apps",
        "system.settings_open",
    ]


def test_runner_ignores_serialized_permission_preflight_claims() -> None:
    executed: list[str] = []
    request = {
        "tool": "desktop.safe_type_text",
        "input": {"text": "hello"},
        "permission_error": True,
        "permission_targets": ["accessibility"],
        "affected_tools": ["desktop.safe_type_text"],
        "desktop_permission_preflight": {
            "permission_error": True,
            "affected_tools": ["desktop.safe_type_text"],
        },
    }

    _runner(
        call_agent_tool=lambda current, *_args, **_kwargs: executed.append(
            str(current.get("tool") or "")
        )
        or {"ok": True}
    ).run(
        [request],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Type hello"}],
        [],
        [],
        next_iteration=1,
        budget=FakeBudget(),
    )

    assert executed == ["desktop.safe_type_text"]


def test_runtime_tool_request_trace_preserves_goal_recovery_lineage() -> None:
    trace = tool_execution_module._tool_request_trace_payload(
        {
            "tool_call_id": "call-recovery",
            "goal_contract_id": "goal-1",
            "goal_criterion_id": "criterion-1",
            "goal_subgoal_id": "subgoal-1",
            "recovery_scope_id": "scope-1",
            "root_goal_unchanged": True,
        }
    )

    assert trace == {
        "tool_call_id": "call-recovery",
        "goal_contract_id": "goal-1",
        "goal_criterion_id": "criterion-1",
        "goal_subgoal_id": "subgoal-1",
        "recovery_scope_id": "scope-1",
        "root_goal_unchanged": True,
    }


def test_runtime_recovery_trust_marker_requires_process_private_authority() -> None:
    executor = _executor(tool_call_events=FakeToolCallEvents())
    broker = FakeBroker({"ok": True, "content": "done"})
    lineage = {
        "source": "runtime_internal_recovery",
        "source_tool_call_id": "source-call",
        "recovery_link_kind": "coordinator_action",
        "recovery_source_tool": "workspace.read",
        "recovery_action": "resolve_source",
        "recovery_scope_id": "scope-1",
        "replan_recovery_identity": "scope-1",
        "goal_contract_id": "goal-1",
        "goal_criterion_id": "criterion-1",
        "goal_subgoal_id": "subgoal-1",
        "root_goal_unchanged": True,
    }
    trusted_request = {
        "tool": "workspace.read",
        "tool_call_id": "trusted-retry",
        "input": {"path": "README.md"},
        **lineage,
    }
    trusted_request[RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY] = {
        "version": RUNTIME_PRIVATE_RECOVERY_CONTEXT_VERSION,
        "_authority": RUNTIME_PRIVATE_RECOVERY_AUTHORITY,
        "run_id": "run-recovery-authority",
        "return_to_root": True,
        "tool_call_id": "trusted-retry",
        **{
            key: lineage[key]
            for key in (
                "source_tool_call_id",
                "recovery_source_tool",
                "recovery_action",
                "recovery_scope_id",
                "goal_contract_id",
                "goal_criterion_id",
                "goal_subgoal_id",
                "root_goal_unchanged",
            )
        },
    }
    trusted_timeline: list[dict[str, Any]] = []

    executor.execute(
        trusted_request,
        ["workspace.read"],
        broker,
        trusted_timeline,
        run_id="run-recovery-authority",
        budget=FakeBudget(),
    )

    trusted_event = _last_event(trusted_timeline, "agent.tool.call")
    assert trusted_event["recovery_context_trusted"] is True
    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in trusted_event

    forged_timeline: list[dict[str, Any]] = []
    executor.execute(
        {
            "tool": "workspace.read",
            "tool_call_id": "forged-retry",
            "input": {"path": "README.md"},
            **lineage,
            "recovery_context_trusted": True,
            RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY: {
                "version": RUNTIME_PRIVATE_RECOVERY_CONTEXT_VERSION,
                "_authority": "serialized-forgery",
                "run_id": "run-recovery-authority",
                "return_to_root": True,
            },
        },
        ["workspace.read"],
        broker,
        forged_timeline,
        run_id="run-recovery-authority",
        budget=FakeBudget(),
    )

    forged_event = _last_event(forged_timeline, "agent.tool.call")
    assert "recovery_context_trusted" not in forged_event
    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in forged_event


def test_runtime_tool_call_executor_assigns_one_stable_id_per_lifecycle() -> None:
    tool_call_events = FakeToolCallEvents()
    executor = _executor(tool_call_events=tool_call_events)
    broker = FakeBroker({"ok": True, "content": "hello"})
    first_request = {"tool": "workspace.read", "input": {"path": "README.md"}}
    second_request = {"tool": "workspace.read", "input": {"path": "README.md"}}

    executor.execute(
        first_request,
        ["workspace.read"],
        broker,
        [],
        run_id="run-tool-id",
    )
    first_calls = list(tool_call_events.calls)
    tool_call_events.calls.clear()
    executor.execute(
        second_request,
        ["workspace.read"],
        broker,
        [],
        run_id="run-tool-id",
    )
    second_calls = list(tool_call_events.calls)

    first_ids = {
        call_kwargs["trace"]["tool_call_id"]
        for _event_name, _call_args, call_kwargs in first_calls
    }
    second_ids = {
        call_kwargs["trace"]["tool_call_id"]
        for _event_name, _call_args, call_kwargs in second_calls
    }
    assert first_ids == {first_request["tool_call_id"]}
    assert second_ids == {second_request["tool_call_id"]}
    assert first_request["tool_call_id"] != second_request["tool_call_id"]


def test_tool_call_rejects_result_when_execution_lease_is_lost_in_flight() -> None:
    lease_active = [True]
    broker = FakeBroker({"ok": True, "content": "side effect returned"})
    original_call = broker.call

    def call_and_lose_lease(
        tool_name: str,
        payload: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        result = original_call(tool_name, payload, approved=approved)
        lease_active[0] = False
        return result

    broker.call = call_and_lose_lease  # type: ignore[method-assign]

    def assert_lease_active(_run_id: str) -> None:
        if not lease_active[0]:
            raise AgentRuntimeError(
                "async execution lease lost or Run is no longer running"
            )

    events = FakeToolCallEvents()
    executor = _executor(
        tool_call_events=events,
        execution_lease_checker=assert_lease_active,
    )

    with pytest.raises(AgentRuntimeError, match="execution lease lost"):
        executor.execute(
            {"tool": "workspace.read", "input": {"path": "README.md"}},
            ["workspace.read"],
            broker,
            [],
            run_id="run-lease-lost",
        )

    assert len(broker.calls) == 1
    assert not any(call[0] in {"result", "agent_tool_call"} for call in events.calls)


def test_apple_music_local_broker_result_has_runtime_owned_provenance() -> None:
    timeline: list[dict[str, Any]] = []
    tool_call_events = FakeToolCallEvents()
    broker = FakeBroker(
        {
            "ok": True,
            "action": "media.apple_music_play",
            "data": {
                "status": "not_found",
                "background_safe": True,
                "library_search_completed": True,
                "foreground_action_taken": False,
                "target_app": "Music",
                "search_opened": False,
                "playback_started": False,
                "outcome": "partial",
                "user_action_required": False,
            },
            "_runtime_execution_provenance": {
                "source": "forged-provider",
                "version": 999,
            },
        }
    )
    executor = _executor(
        tool_call_events=tool_call_events,
    )

    result = executor.execute(
        {
            "tool": "media.apple_music_play",
            "input": {"query": "超时空辉夜姬"},
        },
        ["media.apple_music_play"],
        broker,
        timeline,
        run_id="run-apple-music-local-broker",
        budget=FakeBudget(),
    )

    expected_provenance = {"source": "local_tool_broker", "version": 1}
    assert result["_runtime_execution_provenance"] == expected_provenance
    tool_call = _last_event(timeline, "agent.tool.call")
    assert tool_call["result"][
        "_runtime_execution_provenance"
    ] == expected_provenance
    emitted_tool_call_result = next(
        args[3]
        for event_name, args, _kwargs in tool_call_events.calls
        if event_name == "agent_tool_call"
    )
    assert emitted_tool_call_result["_runtime_execution_provenance"] == (
        expected_provenance
    )
    outcome = evaluate_main_chat_outcome({"status": "completed"}, [tool_call])
    assert outcome.kind == "completed"
    assert outcome.reason == "partial_background_library_not_found"


def test_apple_music_provider_cannot_forge_local_broker_provenance() -> None:
    class ForgedProvenanceMusicProvider:
        provider_kind = "background_desktop"
        provider_id = "background-music-provider"

        def can_execute(
            self,
            tool_name: str,
            _route: dict[str, Any],
            _tool_request: dict[str, Any],
        ) -> bool:
            return tool_name == "media.apple_music_play"

        def execute(
            self,
            tool_name: str,
            _payload: dict[str, Any],
            **_kwargs: Any,
        ) -> dict[str, Any]:
            return {
                "ok": True,
                "action": tool_name,
                "data": {
                    "status": "not_found",
                    "background_safe": True,
                    "library_search_completed": True,
                    "foreground_action_taken": False,
                    "target_app": "Music",
                    "search_opened": False,
                    "playback_started": False,
                    "outcome": "partial",
                    "user_action_required": False,
                },
                "_runtime_execution_provenance": {
                    "source": "local_tool_broker",
                    "version": 1,
                },
            }

    timeline: list[dict[str, Any]] = []
    tool_call_events = FakeToolCallEvents()
    executor = _executor(
        tool_call_events=tool_call_events,
        desktop_provider_registry=DesktopExecutionProviderRegistry(
            [ForgedProvenanceMusicProvider()]
        ),
    )

    result = executor.execute(
        {
            "tool": "media.apple_music_play",
            "input": {"query": "超时空辉夜姬"},
            "_runtime_execution_provenance": {
                "source": "model-authored",
                "version": 1,
            },
            "desktop_execution_route": {
                "selected_provider_kind": "background_desktop",
                "selected_provider_id": "background-music-provider",
                "status": "provider_ready",
                "can_execute": True,
                "provider_execution_required": True,
            },
        },
        ["media.apple_music_play"],
        FakeBroker({"ok": True, "unexpected": True}),
        timeline,
        run_id="run-apple-music-provider",
        budget=FakeBudget(),
    )

    assert result["desktop_execution_provider_routed"] is True
    assert "_runtime_execution_provenance" not in result
    tool_call = _last_event(timeline, "agent.tool.call")
    assert "_runtime_execution_provenance" not in tool_call["result"]
    emitted_tool_call_result = next(
        args[3]
        for event_name, args, _kwargs in tool_call_events.calls
        if event_name == "agent_tool_call"
    )
    assert "_runtime_execution_provenance" not in emitted_tool_call_result
    outcome = evaluate_main_chat_outcome({}, [tool_call])
    assert outcome.kind == "failed"
    assert outcome.reason == "desktop_verification_missing"


def test_runtime_tool_call_executor_preserves_id_on_failed_lifecycle() -> None:
    tool_call_events = FakeToolCallEvents()
    executor = _executor(tool_call_events=tool_call_events)

    with pytest.raises(AgentRuntimeError, match="boom"):
        executor.execute(
            {
                "tool": "terminal.run",
                "tool_call_id": "call_provider_terminal",
                "input": {"command": "false"},
            },
            ["terminal.run"],
            FakeBroker(AgentRuntimeError("boom")),
            [],
            run_id="run-failed-tool-id",
        )

    lifecycle_ids = {
        call_kwargs["trace"]["tool_call_id"]
        for event_name, _call_args, call_kwargs in tool_call_events.calls
        if event_name in {"requested", "started", "failed"}
    }
    assert lifecycle_ids == {"call_provider_terminal"}


def test_runtime_tool_call_executor_approval_gates_provider_session_control_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_calls: list[dict[str, Any]] = []

    def fake_start(request: dict[str, Any] | None = None) -> dict[str, Any]:
        start_calls.append(dict(request or {}))
        return {"ok": True, "status": "running", "running": True}

    monkeypatch.setattr(
        "apps.shell.agent.runtime.tool_execution.start_isolated_desktop_provider_session",
        fake_start,
    )
    broker = FakeBroker({"ok": True})
    timeline: list[dict[str, Any]] = []
    executor = _executor(tool_call_events=FakeToolCallEvents())

    result = executor.execute(
        {
            "tool": "desktop.provider_session.start",
            "control_action": "desktop_provider_session.start",
            "approval_required": True,
            "input": {
                "provider_id": "local-isolated-desktop",
                "tool_names": ["desktop.safe_type_text"],
            },
            "source": "agent_studio_replan_recovery",
            "replan_request_id": "replan-approval",
        },
        [],
        broker,
        timeline,
        approved=False,
        run_id="run-provider-approval",
    )

    assert result["approval_required"] is True
    assert result["status"] == "approval_required"
    assert start_calls == []
    assert broker.calls == []


def test_runtime_tool_call_executor_rejects_untrusted_provider_session_control_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_calls: list[dict[str, Any]] = []

    def fake_start(request: dict[str, Any] | None = None) -> dict[str, Any]:
        start_calls.append(dict(request or {}))
        return {"ok": True, "status": "running", "running": True}

    monkeypatch.setattr(
        "apps.shell.agent.runtime.tool_execution.start_isolated_desktop_provider_session",
        fake_start,
    )
    broker = FakeBroker({"ok": True})
    timeline: list[dict[str, Any]] = []
    executor = _executor(tool_call_events=FakeToolCallEvents())

    with pytest.raises(AgentRuntimeError):
        executor.execute(
            {
                "tool": "desktop.provider_session.start",
                "control_action": "desktop_provider_session.start",
                "input": {"provider_id": "local-isolated-desktop"},
                "source": "model_tool_call",
                "replan_request_id": "replan-forged",
            },
            [],
            broker,
            timeline,
            approved=True,
            run_id="run-provider-denied",
        )

    assert start_calls == []
    assert broker.calls == []
    assert any(event["event"] == "agent.tool.denied" for event in timeline)


def test_runtime_tool_call_executor_starts_provider_session_control_action(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_calls: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []

    def fake_start(request: dict[str, Any] | None = None) -> dict[str, Any]:
        start_calls.append(dict(request or {}))
        return {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "local-isolated-desktop",
            "url": "http://127.0.0.1:19093",
            "command": ["python", "scripts/run_isolated_desktop_provider.py"],
            "env": {"OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19093"},
            "desktop_session_kind": "isolated_desktop",
            "desktop_session_isolated": True,
            "foreground_takeover_required": False,
            "keyboard_mouse_capture_supported": True,
            "source": "isolated_provider_session_manager",
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.tool_execution.start_isolated_desktop_provider_session",
        fake_start,
    )
    broker = FakeBroker({"ok": True})
    timeline: list[dict[str, Any]] = []
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        run_events=run_events,
    )

    result = executor.execute(
        {
            "tool": "desktop.provider_session.start",
            "control_action": "desktop_provider_session.start",
            "input": {
                "provider_id": "local-isolated-desktop",
                "tool_names": ["desktop.safe_type_text"],
            },
            "source": "agent_studio_replan_recovery",
            "replan_request_id": "replan-1",
        },
        [],
        broker,
        timeline,
        approved=True,
        run_id="run-provider-start",
    )

    assert start_calls == [
        {
            "provider_id": "local-isolated-desktop",
            "tools": ["desktop.safe_type_text"],
        }
    ]
    assert broker.calls == []
    assert result["ok"] is True
    assert result["control_action"] == "desktop_provider_session.start"
    assert result["desktop_provider_session"]["provider_id"] == "local-isolated-desktop"
    assert result["desktop_provider_session"]["running"] is True
    assert result["desktop_provider_session"]["started"] is True
    assert result["desktop_provider_session"]["desktop_session_kind"] == (
        "isolated_desktop"
    )
    assert result["desktop_provider_session"]["desktop_session_isolated"] is True
    assert result["desktop_provider_session"]["foreground_takeover_required"] is False
    assert (
        result["desktop_provider_session"]["keyboard_mouse_capture_supported"]
        is True
    )
    assert "command" not in result["desktop_provider_session"]
    assert "env" not in result["desktop_provider_session"]
    assert any(event["event"] == "desktop.provider_session.started" for event in timeline)
    provider_events = [
        event for event in run_events if event[1] == "desktop.provider_session.started"
    ]
    assert len(provider_events) == 1
    assert provider_events[0][2]["control_action"] == "desktop_provider_session.start"
    assert provider_events[0][2]["replan_request_id"] == "replan-1"
    event_session = provider_events[0][2]["desktop_provider_session"]
    assert event_session["desktop_session_kind"] == "isolated_desktop"
    assert event_session["desktop_session_isolated"] is True
    assert event_session["foreground_takeover_required"] is False
    assert event_session["keyboard_mouse_capture_supported"] is True


def test_runtime_tool_call_executor_preserves_real_backend_provider_start_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_calls: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []

    def fake_start(request: dict[str, Any] | None = None) -> dict[str, Any]:
        start_calls.append(dict(request or {}))
        return {
            "ok": False,
            "status": "real_virtual_desktop_provider_required",
            "running": False,
            "started": False,
            "provider_id": "real-virtual-desktop",
            "requires_real_virtual_desktop_backend": True,
            "blocking_conditions": [
                "configured_virtual_desktop_provider_required",
                "real_virtual_desktop_backend_required",
            ],
            "source": "isolated_provider_session_manager",
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.tool_execution.start_isolated_desktop_provider_session",
        fake_start,
    )
    timeline: list[dict[str, Any]] = []
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        run_events=run_events,
    )

    result = executor.execute(
        {
            "tool": "desktop.provider_session.start",
            "control_action": "desktop_provider_session.start",
            "input": {
                "provider_id": "real-virtual-desktop",
                "tool_names": ["app.open"],
                "requires_real_virtual_desktop_backend": True,
            },
            "source": "agent_studio_replan_recovery",
            "replan_request_id": "replan-real-provider",
            "replan_recovery_action_id": (
                "replan-real-provider:action:1:desktop.provider_session.start"
            ),
        },
        [],
        FakeBroker({"ok": True}),
        timeline,
        approved=True,
        run_id="run-real-provider-start",
    )

    assert start_calls == [
        {
            "provider_id": "real-virtual-desktop",
            "tools": ["app.open"],
            "requires_real_virtual_desktop_backend": True,
        }
    ]
    assert result["ok"] is False
    assert result["status"] == "real_virtual_desktop_provider_required"
    assert result["desktop_provider_session"]["requires_real_virtual_desktop_backend"] is True
    assert "real_virtual_desktop_backend_required" in result[
        "desktop_provider_session"
    ]["blocking_conditions"]
    assert any(event["event"] == "desktop.provider_session.failed" for event in timeline)
    provider_events = [
        event for event in run_events if event[1] == "desktop.provider_session.failed"
    ]
    assert provider_events
    assert provider_events[0][2]["desktop_provider_session"][
        "requires_real_virtual_desktop_backend"
    ] is True


def test_runtime_tool_request_runner_continues_after_provider_session_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    start_calls: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []

    def fake_start(request: dict[str, Any] | None = None) -> dict[str, Any]:
        start_calls.append(dict(request or {}))
        return {
            "ok": True,
            "status": "running",
            "running": True,
            "started": True,
            "provider_id": "sandbox-1",
            "url": "http://127.0.0.1:19093",
            "tool_names": ["desktop.safe_type_text"],
            "source": "isolated_provider_session_manager",
        }

    monkeypatch.setattr(
        "apps.shell.agent.runtime.tool_execution.start_isolated_desktop_provider_session",
        fake_start,
    )
    adapter = FakeSandboxDesktopAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        run_events=run_events,
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    runner = _runner(call_agent_tool=executor.execute, run_events=run_events)
    timeline: list[dict[str, Any]] = []

    runner.run(
        [
            {
                "tool": "desktop.provider_session.start",
                "control_action": "desktop_provider_session.start",
                "input": {
                    "provider_id": "sandbox-1",
                    "tool_names": ["desktop.safe_type_text"],
                },
                "source": "agent_studio_replan_recovery",
                "replan_request_id": "replan-1",
                "replan_recovery_action_id": "replan-1:action:1:desktop.provider_session.start",
                "deferred_continuation": [
                    {
                        "tool": "desktop.safe_type_text",
                        "input": {"text": "hello"},
                        "desktop_execution_policy": {
                            "mode": "sandbox_preferred",
                            "prefer_isolated_desktop": True,
                            "avoid_user_foreground_takeover": True,
                        },
                        "desktop_execution_route": {
                            "status": "provider_required",
                            "can_execute": False,
                        },
                        "sandbox_provider": {"status": "provider_required"},
                    }
                ],
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True, "unexpected": True}),
        [{"role": "user", "content": "启动隔离桌面后输入 hello"}],
        timeline,
        [],
        next_iteration=3,
        run_id="run-provider-continuation",
        budget=FakeBudget(),
    )

    assert start_calls == [
        {"provider_id": "sandbox-1", "tools": ["desktop.safe_type_text"]}
    ]
    assert adapter.calls == [
        {
            "tool": "desktop.safe_type_text",
            "payload": {"text": "hello"},
            "route": adapter.calls[0]["route"],
            "approved": False,
        }
    ]
    assert adapter.calls[0]["route"]["status"] == "sandbox_ready"
    assert adapter.calls[0]["route"]["selected_provider_id"] == "sandbox-1"
    provider_events = [
        event["event"]
        for event in timeline
        if event["event"]
        in {
            "desktop.provider_session.started",
            "agent.deferred_continuation.enqueued",
        }
    ]
    assert provider_events == [
        "desktop.provider_session.started",
        "agent.deferred_continuation.enqueued",
    ]
    tool_calls = [event for event in timeline if event["event"] == "agent.tool.call"]
    assert [event["detail"] for event in tool_calls] == [
        "desktop.provider_session.start",
        "desktop.safe_type_text",
    ]
    assert tool_calls[-1]["result"]["desktop_execution_provider_routed"] is True
    assert any(
        event_type == "agent.deferred_continuation.enqueued"
        and payload["deferred_tools"] == ["desktop.safe_type_text"]
        for _run_id, event_type, payload in run_events
    )


def test_runtime_tool_request_runner_marks_task_todo_active_before_tool_call() -> None:
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    observed_statuses_before_call: list[str] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        current_timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        observed_statuses_before_call.extend(
            event["status"]
            for event in current_timeline
            if event["event"] == "agent.task.todo.updated"
        )
        assert tool_request["step_id"] == "write-report"
        return {"ok": True, "summary": "Report artifact written."}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "artifact.write",
                "request_id": "request-write-report",
                "input": {"path": "report.md"},
                "source": "runtime_planner",
                "step_id": "write-report",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "task_workspace_items": [
                    {
                        "item_id": "workspace-report",
                        "title": "report.md",
                        "status": "planned",
                        "source_step_id": "write-report",
                    }
                ],
                "task_todo": {
                    "todo_id": "todo-write-report",
                    "title": "Write report",
                    "status": "pending",
                    "step_id": "write-report",
                    "tool_name": "artifact.write",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-write-report",
                        "title": "Verify report",
                        "status": "planned",
                        "after_step_id": "write-report",
                    }
                ],
            }
        ],
        ["artifact.write"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "写报告"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-progress-start",
    )

    todo_updates = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
    ]
    checkpoint_updates = [
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
    ]

    assert observed_statuses_before_call == ["in_progress"]
    assert [event["status"] for event in todo_updates] == [
        "in_progress",
        "completed",
    ]
    assert [event["status"] for event in checkpoint_updates] == [
        "ready",
        "completed",
    ]
    completed_todo = todo_updates[-1]
    assert completed_todo["run_id"] == "run-progress-start"
    assert completed_todo["decision_id"] == "decision-1"
    assert completed_todo["plan_id"] == "plan-1"
    assert completed_todo["request_id"] == "request-write-report"
    assert completed_todo["step_id"] == "write-report"
    assert completed_todo["tool_call_id"]
    assert completed_todo["actor"] == "native_runtime"
    assert completed_todo["visibility"] == "internal"
    assert completed_todo["source_event"] == {
        "event": "agent.tool.call",
        "detail": "artifact.write",
        "request_id": "request-write-report",
        "tool_call_id": completed_todo["tool_call_id"],
    }
    assert [
        event_type
        for _run_id, event_type, _payload in run_events
        if event_type == "agent.task.todo.updated"
    ] == ["agent.task.todo.updated", "agent.task.todo.updated"]


def test_runtime_tool_request_runner_resolves_analysis_artifact_body(tmp_path) -> None:
    artifact_text = "Data analysis result for sales.csv.\nEast revenue: 10."
    artifact_path = tmp_path / "analysis-report.md"
    artifact_path.write_text(artifact_text, encoding="utf-8")
    captured_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    class Broker:
        artifact_root = tmp_path

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_requests.append(tool_request)
        return {"ok": True, "summary": "typed"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {
                    "body_source": "analysis_artifact",
                    "artifact_path": "analysis-report.md",
                    "target_action": "app_paste",
                },
                "source": "runtime_planner",
            }
        ],
        ["desktop.safe_type_text"],
        Broker(),
        [{"role": "user", "content": "分析 sales.csv 并写入前台应用"}],
        timeline,
        [
            {
                "path": "analysis-report.md",
                "kind": "markdown",
                "source_tool": "data.analyze",
            }
        ],
        next_iteration=1,
        run_id="run-artifact-body",
    )

    assert captured_requests[0]["input"]["text"] == artifact_text
    assert captured_requests[0]["input"]["body_source"] == "analysis_artifact"
    assert captured_requests[0]["input_resolution"] == {
        "field": "text",
        "body_source": "analysis_artifact",
        "artifact_path": "analysis-report.md",
        "source_tool": "data.analyze",
        "resolved_text_bytes": len(artifact_text.encode("utf-8")),
    }
    assert (
        "run-artifact-body",
        "agent.tool.input_resolved",
        {
            "field": "text",
            "body_source": "analysis_artifact",
            "artifact_path": "analysis-report.md",
            "source_tool": "data.analyze",
            "resolved_text_bytes": len(artifact_text.encode("utf-8")),
            "tool": "desktop.safe_type_text",
            "tool_call_id": captured_requests[0]["tool_call_id"],
        },
    ) in run_events


def test_runtime_tool_request_runner_resolves_research_artifact_body(tmp_path) -> None:
    artifact_text = "Research summary for example.com.\nKey finding: stable."
    artifact_path = tmp_path / "research-summary.md"
    artifact_path.write_text(artifact_text, encoding="utf-8")
    captured_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    class Broker:
        artifact_root = tmp_path

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_requests.append(tool_request)
        return {"ok": True, "summary": "typed"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {
                    "body_source": "research_artifact",
                    "artifact_path": "research-summary.md",
                    "target_action": "app_paste",
                },
                "source": "runtime_planner",
            }
        ],
        ["desktop.safe_type_text"],
        Broker(),
        [{"role": "user", "content": "调研 example.com 并写入前台应用"}],
        timeline,
        [
            {
                "path": "research-summary.md",
                "kind": "markdown",
                "source_tool": "artifact.write",
            }
        ],
        next_iteration=1,
        run_id="run-research-artifact-body",
    )

    assert captured_requests[0]["input"]["text"] == artifact_text
    assert captured_requests[0]["input"]["body_source"] == "research_artifact"
    assert captured_requests[0]["input_resolution"] == {
        "field": "text",
        "body_source": "research_artifact",
        "artifact_path": "research-summary.md",
        "source_tool": "artifact.write",
        "resolved_text_bytes": len(artifact_text.encode("utf-8")),
    }
    assert (
        "run-research-artifact-body",
        "agent.tool.input_resolved",
        {
            "field": "text",
            "body_source": "research_artifact",
            "artifact_path": "research-summary.md",
            "source_tool": "artifact.write",
            "resolved_text_bytes": len(artifact_text.encode("utf-8")),
            "tool": "desktop.safe_type_text",
            "tool_call_id": captured_requests[0]["tool_call_id"],
        },
    ) in run_events


def test_runtime_tool_request_runner_preserves_scope_on_task_progress_events() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "action": str(tool_request.get("tool") or ""),
            "summary": "done",
        }

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "artifact.write",
                "input": {"path": "report.md"},
                "source": "runtime_planner",
                "step_id": "write-report",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "task_id": "task-1",
                "group_run_id": "group-run-1",
                "workflow_run_id": "workflow-run-1",
                "task_todo": {
                    "todo_id": "todo-write-report",
                    "title": "Write report",
                    "status": "pending",
                    "step_id": "write-report",
                    "tool_name": "artifact.write",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-write-report",
                        "title": "Verify report",
                        "status": "planned",
                        "after_step_id": "write-report",
                    }
                ],
            }
        ],
        ["artifact.write"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "write report"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    todo_events = [
        event for event in timeline if event["event"] == "workflow.run.task.todo.updated"
    ]
    checkpoint_events = [
        event
        for event in timeline
        if event["event"] == "workflow.run.task.checkpoint.updated"
    ]
    assert [event["status"] for event in todo_events] == [
        "in_progress",
        "completed",
    ]
    assert [event["status"] for event in checkpoint_events] == [
        "ready",
        "completed",
    ]
    todo_event = todo_events[-1]
    checkpoint_event = checkpoint_events[-1]
    for event in (todo_event, checkpoint_event):
        assert event["task_id"] == "task-1"
        assert event["group_run_id"] == "group-run-1"
        assert event["workflow_run_id"] == "workflow-run-1"
        assert event["status"] == "completed"
        assert event["planner_scope"] == "workflow.run"
    assert todo_event["planner_event_type"] == "agent.task.todo.updated"
    assert checkpoint_event["planner_event_type"] == "agent.task.checkpoint.updated"

    run_todo_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "workflow.run.task.todo.updated"
    )
    assert run_todo_event["task_id"] == "task-1"
    assert run_todo_event["group_run_id"] == "group-run-1"
    assert run_todo_event["workflow_run_id"] == "workflow-run-1"
    assert run_todo_event["planner_event_type"] == "agent.task.todo.updated"


def test_runtime_tool_request_runner_records_group_scoped_task_progress() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "action": "artifact.write",
            "summary": "done",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "artifact.write",
                "input": {"path": "report.md"},
                "source": "runtime_planner",
                "step_id": "write-report",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "group_run_id": "group-run-1",
                "task_todo": {
                    "todo_id": "todo-write-report",
                    "title": "Write report",
                    "status": "pending",
                    "step_id": "write-report",
                    "tool_name": "artifact.write",
                },
            }
        ],
        ["artifact.write"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "write report"}],
        timeline,
        [],
        next_iteration=1,
        run_id="group-run-1",
        budget=FakeBudget(),
    )

    todo_event = next(
        event for event in timeline if event["event"] == "group.run.task.todo.updated"
    )
    assert todo_event["group_run_id"] == "group-run-1"
    assert todo_event["planner_event_type"] == "agent.task.todo.updated"
    assert todo_event["planner_scope"] == "group.run"
    assert next(
        event_type
        for _run_id, event_type, _payload in run_events
        if event_type == "group.run.task.todo.updated"
    )


def test_runtime_tool_request_runner_marks_operate_steps_ready_for_verification() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "action": str(tool_request.get("tool") or ""),
            "summary": "clicked",
        }

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "selector": "text=Export"},
                "source": "runtime_planner",
                "step_id": "operate-foreground-ui",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "operate",
                "runtime_role": "click_ui",
                "requires_post_action_verification": True,
                "task_todo": {
                    "todo_id": "todo-operate",
                    "title": "Click Export",
                    "status": "pending",
                    "step_id": "operate-foreground-ui",
                    "tool_name": "app.open_and_click_ui_element",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-operate",
                        "title": "Verify Export",
                        "status": "planned",
                        "after_step_id": "operate-foreground-ui",
                    }
                ],
            }
        ],
        ["app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify",
        budget=FakeBudget(),
    )

    todo_event = next(event for event in timeline if event["event"] == "agent.task.todo.updated")
    checkpoint_event = next(
        event for event in timeline if event["event"] == "agent.task.checkpoint.updated"
    )
    assert todo_event["status"] == "in_progress"
    assert todo_event["todo"]["status"] == "in_progress"
    assert checkpoint_event["status"] == "ready"
    assert checkpoint_event["checkpoint"]["status"] == "ready"
    assert not any(event["event"] == "agent.replan.requested" for event in timeline)

    run_checkpoint_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.task.checkpoint.updated"
    )
    assert run_checkpoint_event["status"] == "ready"


def test_runtime_tool_request_runner_completes_operate_step_after_verify() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    operate_todo = {
        "todo_id": "todo-operate",
        "title": "Click Export",
        "status": "pending",
        "step_id": "operate-foreground-ui",
        "tool_name": "app.open_and_click_ui_element",
    }
    operate_checkpoint = {
        "checkpoint_id": "checkpoint-operate",
        "title": "Verify Export",
        "status": "planned",
        "after_step_id": "operate-foreground-ui",
    }

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "action": str(tool_request.get("tool") or ""),
            "summary": "done",
        }

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "selector": "text=Export"},
                "source": "runtime_planner",
                "step_id": "operate-foreground-ui",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
                "task_todo": operate_todo,
                "task_checkpoints": [operate_checkpoint],
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"role_filter": "text", "limit": 80},
                "source": "runtime_planner",
                "step_id": "verify-desktop-result",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "verify",
                "depends_on": ["operate-foreground-ui"],
                "task_verification_targets": [
                    {
                        "step_id": "operate-foreground-ui",
                        "todo": operate_todo,
                        "checkpoints": [operate_checkpoint],
                    }
                ],
            },
        ],
        ["app.open_and_click_ui_element", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify-complete",
        budget=FakeBudget(),
    )

    todo_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
    ]
    checkpoint_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
    ]
    assert todo_statuses == ["in_progress", "completed"]
    assert checkpoint_statuses == ["ready", "completed"]
    completed_checkpoint = next(
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
        and event["status"] == "completed"
    )
    assert completed_checkpoint["verified_by_step_id"] == "verify-desktop-result"
    assert completed_checkpoint["previous_status"] == "ready"

    run_todo_statuses = [
        payload["status"]
        for _run_id, event_type, payload in run_events
        if event_type == "agent.task.todo.updated"
        and payload["todo_id"] == "todo-operate"
    ]
    assert run_todo_statuses == ["in_progress", "completed"]


def test_runtime_tool_request_runner_records_verification_failure_recovery_context() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    operate_todo = {
        "todo_id": "todo-operate",
        "title": "Click Export",
        "status": "pending",
        "step_id": "operate-foreground-ui",
        "tool_name": "app.open_and_click_ui_element",
    }
    operate_checkpoint = {
        "checkpoint_id": "checkpoint-operate",
        "title": "Verify Export",
        "status": "planned",
        "after_step_id": "operate-foreground-ui",
    }
    desktop_execution_policy = {
        "mode": "preview_input",
        "prefer_isolated_desktop": True,
        "avoid_user_foreground_takeover": True,
    }
    desktop_provider_session = {
        "running": True,
        "started": True,
        "status": "running",
        "provider_id": "sandbox-1",
        "url": "http://127.0.0.1:19093",
        "tool_names": ["desktop.ui_elements"],
        "command": ["sandbox-provider", "--token", "secret"],
        "env": {"SECRET": "not-for-events"},
    }
    sandbox_provider = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "sandbox_desktop",
        "provider_id": "sandbox-1",
        "status": "available",
        "supported_tools": ["desktop.ui_elements"],
    }
    desktop_execution_route = {
        "status": "sandbox_ready",
        "can_execute": True,
        "selected_provider_kind": "sandbox_desktop",
        "selected_provider_id": "sandbox-1",
        "provider_execution_required": True,
        "sandbox_required": True,
    }
    desktop_loop = {
        "stage": "verify",
        "role": "verify_result",
        "action": "verify_after_action",
        "source_tool": "desktop.ui_elements",
        "retry_tool": "desktop.ui_elements",
        "retry_reason": "verification_failed",
        "retry_input": {"app_name": "PixelForge", "role_filter": "text", "limit": 80},
        "verification_target_step_ids": ["operate-foreground-ui"],
        "requires_observation": True,
        "requires_post_action_verification": True,
        "can_auto_retry": True,
        "source": "runtime_post_action_auto_verify",
    }

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        if str(tool_request.get("tool") or "") == "desktop.ui_elements":
            return {
                "ok": False,
                "verification_failed": True,
                "summary": "Export dialog is still not visible",
                "blocking_condition": "ui_inspection_failed",
            }
        return {"ok": True, "summary": "clicked"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "selector": "text=Export"},
                "source": "runtime_planner",
                "step_id": "operate-foreground-ui",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
                "task_todo": operate_todo,
                "task_checkpoints": [operate_checkpoint],
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"app_name": "PixelForge", "role_filter": "text", "limit": 80},
                "source": "runtime_planner",
                "step_id": "verify-desktop-result",
                "capability_id": "desktop.visual_verification",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "verify",
                "desktop_execution_policy": desktop_execution_policy,
                "desktop_execution_route": desktop_execution_route,
                "desktop_provider_session": desktop_provider_session,
                "sandbox_provider": sandbox_provider,
                "desktop_loop": desktop_loop,
                "depends_on": ["operate-foreground-ui"],
                "replan_signal_ids": ["signal-verify-export-failed"],
                "replan_triggers": ["verification_failed"],
                "task_verification_targets": [
                    {
                        "step_id": "operate-foreground-ui",
                        "todo": operate_todo,
                        "checkpoints": [operate_checkpoint],
                    }
                ],
            },
        ],
        ["app.open_and_click_ui_element", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify-failed",
        budget=FakeBudget(),
    )

    todo_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
    ]
    checkpoint_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
    ]
    assert todo_statuses == ["in_progress", "blocked"]
    assert checkpoint_statuses == ["ready", "blocked"]

    replan_event = next(
        event for event in timeline if event["event"] == "agent.replan.requested"
    )
    payload = replan_event["payload"]
    assert payload["trigger"] == "verification_failed"
    assert payload["source_step_id"] == "verify-desktop-result"
    assert payload["source_tool_name"] == "desktop.ui_elements"
    assert payload["verification_targets"][0]["step_id"] == "operate-foreground-ui"
    assert payload["verification_targets"][0]["todo_id"] == "todo-operate"
    assert payload["action_target"]["action"] == "verify_after_action"
    assert payload["action_target"]["step_id"] == "operate-foreground-ui"
    assert payload["action_target"]["todo_id"] == "todo-operate"
    assert payload["action_target"]["app_name"] == "PixelForge"
    assert payload["observation_evidence"]["source_tool"] == "desktop.ui_elements"
    assert payload["observation_evidence"]["verification_failed"] is True
    assert payload["observation_retry"]["tool"] == "desktop.ui_elements"
    assert payload["observation_retry"]["input"]["app_name"] == "PixelForge"
    assert payload["metadata"]["verification_targets"] == payload["verification_targets"]
    assert payload["metadata"]["action_target"] == payload["action_target"]
    assert payload["metadata"]["desktop_execution_policy"] == desktop_execution_policy
    assert payload["metadata"]["desktop_execution_route"] == desktop_execution_route
    assert payload["metadata"]["sandbox_provider"] == sandbox_provider
    assert payload["metadata"]["desktop_loop"] == desktop_loop
    assert payload["metadata"]["desktop_provider_session"]["provider_id"] == "sandbox-1"
    assert "command" not in payload["metadata"]["desktop_provider_session"]
    assert "env" not in payload["metadata"]["desktop_provider_session"]
    assert payload["metadata"]["recovery_actions"][0]["tool"] == "desktop.ui_elements"
    assert (
        payload["metadata"]["recovery_actions"][0]["action_target"]["step_id"]
        == "operate-foreground-ui"
    )
    recovery_metadata = payload["metadata"]["recovery_actions"][0]["metadata"]
    assert recovery_metadata["desktop_execution_route"] == desktop_execution_route
    assert recovery_metadata["sandbox_provider"] == sandbox_provider
    assert recovery_metadata["desktop_loop"] == desktop_loop
    assert recovery_metadata["desktop_provider_session"]["provider_id"] == "sandbox-1"
    assert "command" not in recovery_metadata["desktop_provider_session"]
    assert "env" not in recovery_metadata["desktop_provider_session"]

    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["request_id"] == payload["request_id"]
    assert run_replan_event["metadata"]["action_target"] == payload["action_target"]
    assert run_replan_event["metadata"]["desktop_execution_route"] == (
        desktop_execution_route
    )
    assert run_replan_event["metadata"]["desktop_provider_session"]["provider_id"] == (
        "sandbox-1"
    )
    assert "command" not in run_replan_event["metadata"]["desktop_provider_session"]
    assert "env" not in run_replan_event["metadata"]["desktop_provider_session"]

    runner.run(
        [
            {
                "tool": "desktop.active_window",
                "input": {"reason": "re-observe failed verification target"},
                "source": "runtime_planner",
                "planning_reason": "planner_replan_runtime_recovery_action",
                "step_id": "verify-desktop-result",
                "replan_request_id": payload["request_id"],
                "replan_trigger": "verification_failed",
                "verification_targets": payload["verification_targets"],
                "action_target": payload["action_target"],
                "observation_evidence": payload["observation_evidence"],
                "observation_retry": payload["observation_retry"],
                "recovery_action_label": "Re-observe failed verification target",
            }
        ],
        ["desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "click export"}],
        timeline,
        [],
        next_iteration=2,
        run_id="run-verify-failed",
        budget=FakeBudget(),
    )

    recovery_update = next(
        event for event in timeline if event["event"] == "agent.replan.recovery.updated"
    )
    assert recovery_update["request_id"] == payload["request_id"]
    assert recovery_update["verification_targets"] == payload["verification_targets"]
    assert recovery_update["action_target"] == payload["action_target"]
    recovered_todo_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
    ]
    recovered_checkpoint_statuses = [
        event["status"]
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-operate"
    ]
    assert recovered_todo_statuses == ["in_progress", "blocked", "completed"]
    assert recovered_checkpoint_statuses == ["ready", "blocked", "completed"]
    recovered_todo = next(
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-operate"
        and event["status"] == "completed"
    )
    assert recovered_todo["previous_status"] == "blocked"
    assert recovered_todo["verified_by_step_id"] == "verify-desktop-result"
    run_recovery_update = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.recovery.updated"
    )
    assert run_recovery_update["verification_targets"] == payload["verification_targets"]
    run_recovered_todo_statuses = [
        payload["status"]
        for _run_id, event_type, payload in run_events
        if event_type == "agent.task.todo.updated"
        and payload["todo_id"] == "todo-operate"
    ]
    assert run_recovered_todo_statuses == ["in_progress", "blocked", "completed"]


def test_runtime_tool_request_runner_records_replan_request_for_failed_planned_step() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "unsupported chart type",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "task_id": "task-1",
                "group_run_id": "group-run-1",
                "workflow_run_id": "workflow-run-1",
                "replan_signal_ids": ["signal-analyze-failed"],
                "replan_triggers": ["tool_failure"],
                "fallback_tools": ["terminal.run"],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    replan_event = next(
        event for event in timeline if event["event"] == "workflow.run.replan.requested"
    )
    assert replan_event["task_id"] == "task-1"
    assert replan_event["group_run_id"] == "group-run-1"
    assert replan_event["workflow_run_id"] == "workflow-run-1"
    assert replan_event["payload"]["planner_event_type"] == "agent.replan.requested"
    assert replan_event["payload"]["planner_scope"] == "workflow.run"
    assert replan_event["payload"]["trigger"] == "tool_failure"
    assert replan_event["payload"]["source_step_id"] == "analyze-data-file"
    assert replan_event["payload"]["source_tool_name"] == "data.analyze"
    assert replan_event["payload"]["target_capability_id"] == "data.analysis"
    assert replan_event["payload"]["input_preview"] == {"path": "data/sales.csv"}
    assert replan_event["payload"]["metadata"]["input_preview"] == {
        "path": "data/sales.csv"
    }
    assert replan_event["payload"]["fallback_tools"] == ["terminal.run"]
    assert "unsupported chart type" in replan_event["payload"]["failure_detail"]

    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "workflow.run.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_event["payload"]["request_id"]
    assert run_replan_event["replan_signal_ids"] == ["signal-analyze-failed"]


def test_runtime_tool_request_runner_uses_capability_recovery_for_generic_media_tool() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "media bridge unavailable",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "media.spotify_open_and_play",
                "input": {"app_name": "Spotify", "query": "lofi study"},
                "source": "runtime_planner",
                "step_id": "play-media",
                "capability_id": "media.playback",
            }
        ],
        ["media.spotify_open_and_play", "desktop.list_apps", "app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "play lofi in Spotify"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-generic-media-recovery",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["trigger"] == "tool_unavailable"
    assert payload["source_tool_name"] == "media.spotify_open_and_play"
    assert payload["target_capability_id"] == "media.playback"
    assert payload["fallback_tools"] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    recovery_actions = payload["metadata"]["recovery_actions"]
    assert [action["tool"] for action in recovery_actions] == [
        "desktop.list_apps",
        "app.open",
        "desktop.active_window",
    ]
    assert recovery_actions[0]["input"] == {"query": "lofi study", "limit": 20}
    assert recovery_actions[1]["input"] == {"app_name": "Spotify"}
    assert recovery_actions[2]["input"] == {}
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["fallback_tools"] == payload["fallback_tools"]


def test_runtime_tool_request_runner_projects_data_analysis_python_recovery_action() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "built-in parser could not parse file",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "replan_triggers": ["tool_failure"],
            }
        ],
        ["data.analyze", "python.run", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data/sales.csv"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-data-recovery",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["fallback_tools"] == ["python.run", "terminal.run"]
    assert payload["recovery_actions"] == payload["metadata"]["recovery_actions"]
    recovery_actions = payload["metadata"]["recovery_actions"]
    assert len(recovery_actions) == 1
    python_action = recovery_actions[0]
    assert python_action["tool"] == "python.run"
    assert python_action["permission_target"] == "terminal_execution"
    assert python_action["risk_level"] == "high"
    assert python_action["approval_required"] is True
    assert "data/sales.csv" in python_action["input"]["code"]
    assert "pd.read_csv" in python_action["input"]["code"]
    assert python_action["metadata"] == {
        "runtime_replan_auto_start_eligible": False,
        "runtime_replan_auto_start_reason": "manual_runtime_replan_recovery_required",
        "runtime_replan_auto_start_blockers": [
            "approval_required",
            "high_risk",
            "tool_not_auto_safe",
        ],
    }
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["recovery_actions"] == payload["recovery_actions"]


def test_runtime_tool_request_runner_auto_runs_safe_replan_recovery_action() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        if tool_request["tool"] == "desktop.verify":
            return {
                "ok": False,
                "verification_failed": True,
                "error": "foreground_focus_unverified",
                "recovery_actions": [
                    {
                        "label": "Open target app",
                        "tool": "app.open",
                        "input": {"app_name": "PixelForge"},
                        "risk_level": "low",
                        "permission_target": "app_launch",
                    }
                ],
            }
        return {"ok": True, "status": "ok"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "desktop.verify",
                "input": {"app_name": "PixelForge"},
                "source": "runtime_planner",
                "step_id": "verify-pixelforge",
                "capability_id": "desktop.app",
                "requires_observation": True,
                "replan_triggers": ["verification_failed"],
            }
        ],
        ["desktop.verify", "app.open"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Open PixelForge"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-auto-recovery",
        budget=FakeBudget(),
    )

    assert [request["tool"] for request in seen_requests] == [
        "desktop.verify",
        "app.open",
    ]
    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    auto_request = seen_requests[1]
    assert auto_request["source"] == "runtime_replan_recovery"
    assert auto_request["replan_request_id"] == replan_event["payload"]["request_id"]
    assert auto_request["recovery_action_label"] == "Open target app"
    enqueued_event = next(
        event
        for event in timeline
        if event["event"] == "agent.deferred_continuation.enqueued"
    )
    assert enqueued_event["runtime_retry_source"] == "runtime_replan_recovery"
    assert enqueued_event["deferred_tools"] == ["app.open"]
    run_enqueued = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.deferred_continuation.enqueued"
    )
    assert run_enqueued["replan_request_id"] == replan_event["payload"]["request_id"]


def _owned_background_window_not_ready_result() -> dict[str, Any]:
    return {
        "ok": False,
        "action": "app.open",
        "error": "cua_background_window_not_ready",
        "retryable": True,
        "agent_owned_target": True,
        "pid": 731011,
        "self_activation_suppressed": True,
        "foreground_takeover_detected": False,
        "fallback_used": False,
        "desktop_execution_provider_transport": {
            "provider_kind": "background_desktop",
            "delivery_mode": "background",
            "foreground_takeover_required": False,
            "foreground_takeover_detected": False,
            "transport": "electron_bridge",
        },
    }


def test_runtime_tool_request_runner_defers_exact_background_window_recovery() -> None:
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        return _owned_background_window_not_ready_result()

    runner = _runner(call_agent_tool=call_agent_tool, run_events=[])
    runner.run(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "TextEdit", "bring_to_front": False},
                "source": "runtime_planner",
                "step_id": "open-textedit",
                "capability_id": "desktop.app_control",
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.inspect_app",
                "input": {"app_name": "TextEdit"},
                "source": "runtime_planner",
                "step_id": "inspect-textedit",
                "depends_on": ["open-textedit"],
                "requires_observation": True,
            },
        ],
        ["app.open", "desktop.list_apps", "desktop.active_window", "desktop.inspect_app"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Open TextEdit in the background"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-background-window-coordinator-deferral",
        budget=FakeBudget(),
    )

    assert [request["tool"] for request in seen_requests] == ["app.open"]
    assert any(event["event"] == "agent.replan.requested" for event in timeline)
    assert not any(
        event["event"] == "agent.deferred_continuation.enqueued"
        for event in timeline
    )


@pytest.mark.parametrize(
    "result_override",
    [
        {"error": "ordinary_app_open_failure"},
        {
            "desktop_execution_provider_transport": {
                "provider_kind": "background_desktop",
                "delivery_mode": "background",
                "foreground_takeover_required": True,
                "transport": "electron_bridge",
            }
        },
    ],
)
def test_runtime_tool_request_runner_keeps_generic_recovery_for_other_open_failures(
    result_override: dict[str, Any],
) -> None:
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []
    first_result = {**_owned_background_window_not_ready_result(), **result_override}

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        return first_result if len(seen_requests) == 1 else {"ok": True, "status": "ok"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=[])
    runner.run(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "TextEdit", "bring_to_front": False},
                "source": "runtime_planner",
                "step_id": "open-textedit",
                "capability_id": "desktop.app_control",
            }
        ],
        ["app.open", "desktop.list_apps", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Open TextEdit"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-generic-app-open-recovery",
        budget=FakeBudget(),
    )

    assert seen_requests[0]["tool"] == "app.open"
    assert len(seen_requests) > 1
    assert all(
        request.get("source") == "runtime_replan_recovery"
        for request in seen_requests[1:]
    )
    assert any(
        event["event"] == "agent.deferred_continuation.enqueued"
        for event in timeline
    )


def _runtime_intrinsic_action_event(
    action_tool: str,
    action_input: dict[str, Any],
    result: dict[str, Any],
    *,
    run_id: str,
    plan_id: str,
    step_id: str,
    request_id: str,
    tool_call_id: str,
) -> dict[str, Any]:
    app_name = str(action_input.get("app_name") or "")
    data = dict(result.get("data") or {})
    if action_tool == "app.open":
        data.update(
            {
                "app_name": app_name,
                "launch_verified": True,
                "launch_status": "running",
                "postcondition_verified": True,
            }
        )
        target_action = "open_app"
    elif action_tool == "app.focus_window":
        data.update(
            {
                "app_name": app_name,
                "focus_status": "focused",
                "postcondition_verified": True,
            }
        )
        target_action = "focus_app_window"
    else:
        raise AssertionError(f"unsupported intrinsic fixture: {action_tool}")
    return {
        "event": "agent.tool.call",
        "tool": action_tool,
        "detail": action_tool,
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "visibility": "internal",
        "run_id": run_id,
        "plan_id": plan_id,
        "step_id": step_id,
        "request_id": request_id,
        "tool_call_id": tool_call_id,
        "input_preview": dict(action_input),
        "action_target": {
            "kind": "desktop_app",
            "action": target_action,
            "app_name": app_name,
        },
        "result": {
            **result,
            "ok": True,
            "action": action_tool,
            "postcondition_verified": True,
            "desktop_execution_provider_routed": True,
            "desktop_execution_provider": {
                "adapter_registered": True,
                "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
            },
            "_runtime_execution_provenance": {
                "source": "local_tool_broker",
                "version": 1,
            },
            "data": data,
        },
    }


@pytest.mark.parametrize(
    "source_tool",
    ["app.open", "desktop.open_app", "app.focus", "desktop.focus_app"],
)
def test_local_app_not_found_batch_only_runs_one_read_only_discovery(
    source_tool: str,
) -> None:
    query = "Missing Writer"
    open_failure = desktop_tools._app_open_failed(  # noqa: SLF001
        query,
        subprocess.CompletedProcess(
            args=["open", "-a", query],
            returncode=1,
            stdout="",
            stderr=f"Unable to find application named {query}",
        ),
    )
    if source_tool in {"app.open", "desktop.open_app"}:
        source_result = {**open_failure, "action": source_tool}
    else:
        source_result = {
            "ok": False,
            "action": source_tool,
            "summary": f"{source_tool} failed",
            "error": f"application {query} was not found",
            "data": {},
            "permission_error": False,
            "fallback_used": False,
            "fallback_result": open_failure,
        }

    class _AppNotFoundBroker:
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
            if len(self.calls) == 1:
                assert tool_name == source_tool
                return dict(source_result)
            if tool_name == "desktop.list_apps":
                return {
                    "ok": True,
                    "action": "desktop.list_apps",
                    "data": {"apps": []},
                }
            return {"ok": True, "action": tool_name, "data": {}}

    broker = _AppNotFoundBroker()
    executor = _executor(tool_call_events=FakeToolCallEvents())
    runner = _runner(call_agent_tool=executor.execute)
    timeline: list[dict[str, Any]] = []
    allowed_tools = [
        source_tool,
        "desktop.list_apps",
        "desktop.open_path",
        "app.open",
        "desktop.running_apps",
        "desktop.active_window",
        "screen.capture",
    ]

    runner.run(
        [
            {
                "tool": source_tool,
                "input": {"app_name": query},
                "source": "runtime_planner",
                "replan_triggers": ["tool_failure"],
            }
        ],
        allowed_tools,
        broker,
        [{"role": "user", "content": f"Open {query}"}],
        timeline,
        [],
        next_iteration=1,
        run_id=f"run-app-not-found-{source_tool}",
        budget=FakeBudget(),
    )

    called_tools = [tool_name for tool_name, _payload, _approved in broker.calls]
    assert called_tools == [source_tool, "desktop.list_apps"]
    assert called_tools.count("desktop.list_apps") == 1
    replan_event = next(
        event for event in timeline if event["event"] == "agent.replan.requested"
    )
    assert replan_event["payload"]["fallback_tools"] == ["desktop.list_apps"]
    assert [
        action["tool"]
        for action in replan_event["payload"]["metadata"]["recovery_actions"]
    ] == ["desktop.list_apps"]


def test_runtime_replan_does_not_auto_start_external_permission_recovery_action() -> None:
    requests = tool_execution_module._runtime_replan_auto_recovery_action_requests(
        {
            "request_id": "runtime-replan:chrome-cdp",
            "trigger": "verification_failed",
            "source_tool_name": "desktop.verify",
            "metadata": {
                "recovery_actions": [
                    {
                        "label": "Open Chrome for external CDP recovery",
                        "tool": "app.open",
                        "input": {"app_name": "Google Chrome"},
                        "risk_level": "low",
                        "permission_target": "chrome_cdp",
                        "metadata": {
                            "runtime_replan_auto_start_eligible": True,
                            "runtime_replan_auto_start_blockers": [],
                        },
                    }
                ]
            },
        },
        allowed_tools=["desktop.verify", "app.open"],
        remaining_requests=[],
        timeline=[],
        tool_timeline_start=0,
    )

    assert requests == []


@pytest.mark.parametrize(
    "tool_name",
    [
        "screen.capture",
        "browser.screenshot",
        "desktop.read_ui",
        "desktop.ui_elements",
    ],
)
def test_runtime_replan_does_not_auto_start_sensitive_observation_recovery(
    tool_name: str,
) -> None:
    requests = tool_execution_module._runtime_replan_auto_recovery_action_requests(
        {
            "request_id": "runtime-replan:sensitive-observation",
            "trigger": "verification_failed",
            "source_tool_name": "desktop.active_window",
            "metadata": {
                "recovery_actions": [
                    {
                        "label": "Inspect foreground state",
                        "tool": tool_name,
                        "input": {},
                        "risk_level": "low",
                        "permission_target": "runtime_observation",
                    }
                ]
            },
        },
        allowed_tools=["desktop.active_window", tool_name],
        remaining_requests=[],
        timeline=[],
        tool_timeline_start=0,
    )

    assert requests == []


@pytest.mark.parametrize("open_tool", ["app.open", "desktop.open_app"])
def test_runtime_tool_request_runner_does_not_repeat_successful_open_on_replan(
    open_tool: str,
) -> None:
    seen_requests: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = [
        _timeline(
            "agent.tool.call",
            open_tool,
            input_preview={"app_name": "EarlierApp"},
            result={"ok": True, "status": "ok"},
        )
    ]

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        if tool_request["tool"] == "desktop.verify":
            result = {
                "ok": False,
                "verification_failed": True,
                "error": "foreground_focus_unverified",
                "recovery_actions": [
                    {
                        "label": "Open target app",
                        "tool": open_tool,
                        "input": {"app_name": "PixelForge"},
                        "risk_level": "low",
                        "permission_target": "app_launch",
                    }
                ],
            }
        else:
            result = {"ok": True, "status": "ok"}
        timeline.append(
            _timeline(
                "agent.tool.call",
                tool_request["tool"],
                input_preview=dict(tool_request.get("input") or {}),
                result=result,
            )
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=[])

    runner.run(
        [
            {
                "tool": open_tool,
                "input": {"app_name": "PixelForge"},
                "source": "runtime_planner",
            },
            {
                "tool": "desktop.verify",
                "input": {"app_name": "PixelForge"},
                "source": "runtime_planner",
                "replan_triggers": ["verification_failed"],
            },
        ],
        [open_tool, "desktop.verify"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Open PixelForge and verify it"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-idempotent-open-recovery",
        budget=FakeBudget(),
    )

    assert [request["tool"] for request in seen_requests] == [
        open_tool,
        "desktop.verify",
    ]
    assert not [
        event
        for event in timeline
        if event["event"] == "agent.deferred_continuation.enqueued"
        and open_tool in event["deferred_tools"]
    ]
    replan_event = next(
        event for event in timeline if event["event"] == "agent.replan.requested"
    )
    assert replan_event["payload"]["runtime_tool_timeline_start"] == 1


def test_runtime_replan_idempotency_keeps_focus_retryable() -> None:
    request = {
        "tool": "app.focus",
        "input": {"app_name": "PixelForge"},
    }
    timeline = [
        _timeline(
            "agent.tool.call",
            "app.focus",
            input_preview={"app_name": "PixelForge"},
            result={"ok": True, "status": "ok"},
        )
    ]

    assert not tool_execution_module._runtime_replan_request_already_succeeded(
        request,
        timeline,
        tool_timeline_start=0,
    )


def test_runtime_replan_idempotency_ignores_success_from_prior_tool_batch() -> None:
    request = {
        "tool": "app.open",
        "input": {"app_name": "PixelForge"},
    }
    timeline = [
        _timeline(
            "agent.tool.call",
            "app.open",
            input_preview={"app_name": "PixelForge"},
            result={"ok": True, "status": "ok"},
        )
    ]

    assert not tool_execution_module._runtime_replan_request_already_succeeded(
        request,
        timeline,
        tool_timeline_start=len(timeline),
    )


@pytest.mark.parametrize(
    "deferred_fields",
    [
        {
            "deferred_continuation": [
                {"tool": "desktop.active_window", "input": {}}
            ]
        },
        {
            "deferred_tool": "desktop.active_window",
            "deferred_input": {},
        },
    ],
)
def test_runtime_replan_skips_completed_open_but_runs_deferred_observation(
    deferred_fields: dict[str, Any],
) -> None:
    seen_requests: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        if tool_request["tool"] == "desktop.verify":
            result = {
                "ok": False,
                "verification_failed": True,
                "error": "foreground_focus_unverified",
                "recovery_actions": [
                    {
                        "label": "Open and observe target app",
                        "tool": "app.open",
                        "input": {"app_name": "PixelForge"},
                        "risk_level": "low",
                        "permission_target": "app_launch",
                        **deferred_fields,
                    }
                ],
            }
        else:
            result = {"ok": True, "status": "ok"}
        timeline.append(
            _timeline(
                "agent.tool.call",
                tool_request["tool"],
                input_preview=dict(tool_request.get("input") or {}),
                result=result,
            )
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=[])
    runner.run(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "PixelForge"},
                "source": "runtime_planner",
            },
            {
                "tool": "desktop.verify",
                "input": {"app_name": "PixelForge"},
                "source": "runtime_planner",
                "replan_triggers": ["verification_failed"],
            },
        ],
        ["app.open", "desktop.verify", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Open PixelForge and verify it"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-idempotent-open-with-observation",
        budget=FakeBudget(),
    )

    assert [request["tool"] for request in seen_requests] == [
        "app.open",
        "desktop.verify",
        "desktop.active_window",
    ]
    assert seen_requests[-1]["source"] == "runtime_replan_recovery"


def test_runtime_tool_request_runner_runs_safe_replan_deferred_continuation() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        if tool_request["tool"] == "desktop.verify":
            return {
                "ok": False,
                "verification_failed": True,
                "error": "foreground_focus_unverified",
                "recovery_actions": [
                    {
                        "label": "Open target app",
                        "tool": "app.open",
                        "input": {"app_name": "PixelForge"},
                        "risk_level": "low",
                        "permission_target": "app_launch",
                        "deferred_continuation": [
                            {
                                "tool": "desktop.active_window",
                                "input": {},
                                "risk_level": "low",
                            }
                        ],
                    }
                ],
            }
        return {"ok": True, "status": "ok"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "desktop.verify",
                "input": {"app_name": "PixelForge"},
                "source": "runtime_planner",
                "step_id": "verify-pixelforge",
                "capability_id": "desktop.app",
                "requires_observation": True,
                "replan_triggers": ["verification_failed"],
            }
        ],
        ["desktop.verify", "app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Open PixelForge and verify it"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-auto-recovery-continuation",
        budget=FakeBudget(),
    )

    assert [request["tool"] for request in seen_requests] == [
        "desktop.verify",
        "app.open",
        "desktop.active_window",
    ]
    assert seen_requests[2]["source"] == "runtime_replan_recovery"
    assert seen_requests[2]["replan_request_id"] == seen_requests[1]["replan_request_id"]
    enqueued_events = [
        event
        for event in timeline
        if event["event"] == "agent.deferred_continuation.enqueued"
        and event["runtime_retry_source"] == "runtime_replan_recovery"
    ]
    assert [event["deferred_tools"] for event in enqueued_events] == [
        ["app.open"],
        ["desktop.active_window"],
    ]


def test_runtime_tool_request_runner_runs_approved_replan_deferred_tool() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        return {"ok": True, "status": "ok"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "desktop.ui_elements",
                "input": {"target": "Export", "limit": 80},
                "source": "agent_studio_replan_recovery",
                "replan_request_id": "runtime-replan-ui",
                "replan_recovery_action_id": "runtime-replan-ui:action:1:desktop.ui_elements",
                "approval_required": True,
                "risk_level": "medium",
                "deferred_tool": "desktop.click_ui_element",
                "deferred_input": {"target": "Export", "click_count": 1, "limit": 80},
                "deferred_context": {
                    "step_id": "operate-foreground-ui",
                    "runtime_stage": "operate",
                    "runtime_role": "click_ui",
                },
                "deferred_continuation": [
                    {
                        "tool": "desktop.ui_elements",
                        "input": {"limit": 80},
                        "step_id": "verify-desktop-result",
                        "runtime_stage": "verify",
                        "risk_level": "low",
                    }
                ],
            }
        ],
        ["desktop.ui_elements", "desktop.click_ui_element"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Retry approved UI recovery"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-approved-recovery-deferred-tool",
        budget=FakeBudget(),
    )

    assert [request["tool"] for request in seen_requests] == [
        "desktop.ui_elements",
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    click_request = seen_requests[1]
    assert click_request["source"] == "agent_studio_replan_recovery"
    assert click_request["replan_request_id"] == "runtime-replan-ui"
    assert click_request["step_id"] == "operate-foreground-ui"
    assert click_request["approved_by_replan_recovery_action"] is True
    assert click_request["approval_status"] == "approved"
    assert "approval_required" not in click_request
    enqueued_event = next(
        event
        for event in timeline
        if event["event"] == "agent.deferred_continuation.enqueued"
    )
    assert enqueued_event["deferred_tools"] == [
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]
    assert enqueued_event["runtime_retry_source"] == "runtime_replan_recovery"
    run_enqueued = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.deferred_continuation.enqueued"
    )
    assert run_enqueued["deferred_tools"] == [
        "desktop.click_ui_element",
        "desktop.ui_elements",
    ]


def test_runtime_tool_request_runner_routes_deferred_tool_through_provider_session() -> None:
    timeline: list[dict[str, Any]] = []
    adapter = FakeSandboxDesktopAdapter()
    broker = FakeBroker({"ok": True, "unexpected": True})
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    runner = _runner(call_agent_tool=executor.execute)

    runner.run(
        [
            {
                "tool": "desktop.ui_elements",
                "input": {"target": "Export", "limit": 80},
                "source": "agent_studio_replan_recovery",
                "replan_request_id": "runtime-replan-provider",
                "replan_recovery_action_id": (
                    "runtime-replan-provider:action:1:desktop.ui_elements"
                ),
                "desktop_execution_policy": {
                    "mode": "sandbox_preferred",
                    "prefer_isolated_desktop": True,
                    "avoid_user_foreground_takeover": True,
                },
                "sandbox_provider": {
                    "available": True,
                    "adapter_ready": True,
                    "provider_kind": "sandbox_desktop",
                    "provider_id": "sandbox-1",
                    "status": "available",
                    "supported_tools": ["desktop.ui_elements", "desktop.safe_type_text"],
                },
                "desktop_provider_session": {
                    "running": True,
                    "started": True,
                    "status": "running",
                    "provider_id": "sandbox-1",
                    "url": "http://127.0.0.1:19093",
                    "tool_names": ["desktop.ui_elements", "desktop.safe_type_text"],
                    "command": ["python", "scripts/run_isolated_desktop_provider.py"],
                    "env": {"OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret"},
                },
                "deferred_tool": "desktop.safe_type_text",
                "deferred_input": {"text": "hello"},
                "deferred_context": {
                    "step_id": "type-export-name",
                    "runtime_stage": "operate",
                    "runtime_role": "type_ui",
                },
            }
        ],
        ["desktop.ui_elements", "desktop.safe_type_text"],
        broker,
        [{"role": "user", "content": "Type hello in the sandbox provider"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-provider-deferred-tool",
        budget=FakeBudget(),
    )

    assert [call["tool"] for call in adapter.calls] == [
        "desktop.ui_elements",
        "desktop.safe_type_text",
    ]
    assert broker.calls == []
    typed_call = adapter.calls[1]
    assert typed_call["payload"] == {"text": "hello"}
    assert typed_call["route"]["status"] == "sandbox_ready"
    assert typed_call["route"]["selected_provider_id"] == "sandbox-1"
    enqueued = next(
        event
        for event in timeline
        if event["event"] == "agent.deferred_continuation.enqueued"
    )
    assert enqueued["deferred_tools"] == ["desktop.safe_type_text"]


def test_runtime_tool_request_runner_does_not_auto_start_partial_deferred_recovery() -> None:
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(dict(tool_request))
        if tool_request["tool"] == "desktop.ui_elements":
            return {
                "ok": False,
                "verification_failed": True,
                "error": "target unavailable",
                "recovery_actions": [
                    {
                        "label": "Observe then click Export",
                        "tool": "desktop.ui_elements",
                        "input": {"target": "Export", "limit": 80},
                        "risk_level": "low",
                        "deferred_continuation": [
                            {
                                "tool": "desktop.click_ui_element",
                                "input": {"target": "Export", "click_count": 1},
                                "approval_required": True,
                                "risk_level": "medium",
                            },
                            {
                                "tool": "desktop.ui_elements",
                                "input": {"limit": 80},
                                "risk_level": "low",
                            },
                        ],
                    }
                ],
            }
        return {"ok": True, "status": "ok"}

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "desktop.ui_elements",
                "input": {"target": "Export", "limit": 80},
                "source": "runtime_planner",
                "step_id": "read-foreground-ui",
                "replan_triggers": ["verification_failed"],
            }
        ],
        ["desktop.ui_elements", "desktop.click_ui_element"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Observe then click Export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-partial-recovery-blocked",
        budget=FakeBudget(),
    )

    assert [request["tool"] for request in seen_requests] == ["desktop.ui_elements"]
    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    action = replan_event["payload"]["recovery_actions"][0]
    assert action["deferred_continuation"][0]["tool"] == "desktop.click_ui_element"
    assert not any(
        event["event"] == "agent.deferred_continuation.enqueued"
        for event in timeline
    )


def test_runtime_tool_request_runner_records_group_scoped_replan_request() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "group analysis failed",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "group_run_id": "group-run-1",
                "replan_triggers": ["tool_failure"],
                "fallback_tools": ["terminal.run"],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data"}],
        timeline,
        [],
        next_iteration=1,
        run_id="group-run-1",
        budget=FakeBudget(),
    )

    replan_event = next(
        event for event in timeline if event["event"] == "group.run.replan.requested"
    )
    assert replan_event["group_run_id"] == "group-run-1"
    assert replan_event["payload"]["planner_event_type"] == "agent.replan.requested"
    assert replan_event["payload"]["planner_scope"] == "group.run"
    assert replan_event["payload"]["source_step_id"] == "analyze-data-file"
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "group.run.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_event["payload"]["request_id"]


def test_runtime_tool_request_runner_records_explicit_verification_failure_replan() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "verification_failed": True,
            "summary": "The generated report did not include the requested chart.",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "data/sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data-file",
                "capability_id": "data.analysis",
                "core_id": "task-core-1",
                "workspace_id": "task-workspace-1",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "task_id": "task-1",
                "replan_signal_ids": ["signal-analyze-verify-failed"],
                "replan_triggers": ["verification_failed"],
                "fallback_tools": ["terminal.run"],
                "task_todo": {
                    "todo_id": "todo-analyze-data",
                    "title": "Analyze data",
                    "status": "pending",
                    "step_id": "analyze-data-file",
                    "tool_name": "data.analyze",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-analyze-data",
                        "title": "Verify analysis",
                        "status": "planned",
                        "after_step_id": "analyze-data-file",
                    }
                ],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "analyze data"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-verify-1",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    assert replan_event["payload"]["trigger"] == "verification_failed"
    assert replan_event["payload"]["source_step_id"] == "analyze-data-file"
    assert replan_event["payload"]["source_tool_name"] == "data.analyze"
    assert replan_event["payload"]["target_capability_id"] == "data.analysis"
    assert replan_event["payload"]["fallback_tools"] == ["terminal.run"]
    assert (
        replan_event["payload"]["failure_detail"]
        == "The generated report did not include the requested chart."
    )
    todo_events = [
        event
        for event in timeline
        if event["event"] == "agent.task.todo.updated"
        and event["todo_id"] == "todo-analyze-data"
    ]
    checkpoint_events = [
        event
        for event in timeline
        if event["event"] == "agent.task.checkpoint.updated"
        and event["checkpoint_id"] == "checkpoint-analyze-data"
    ]
    assert [event["status"] for event in todo_events] == ["in_progress", "blocked"]
    assert [event["status"] for event in checkpoint_events] == ["ready", "blocked"]
    todo_event = todo_events[-1]
    checkpoint_event = checkpoint_events[-1]
    assert todo_event["status"] == "blocked"
    assert todo_event["todo"]["status"] == "blocked"
    assert checkpoint_event["status"] == "blocked"
    assert checkpoint_event["checkpoint"]["status"] == "blocked"

    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_event["payload"]["request_id"]
    assert run_replan_event["replan_signal_ids"] == ["signal-analyze-verify-failed"]


def test_runtime_tool_request_runner_stops_after_nested_verification_failure() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(str(tool_request.get("tool") or ""))
        if tool_request["tool"] == "desktop.verify":
            return {
                "ok": True,
                "summary": "Expected UI state was not present.",
                "data": {
                    "verification_passed": False,
                    "expected_app_name": "Music",
                    "active_app_name": "Music",
                },
            }
        return {"ok": True, "content": "should not run"}

    runner = _runner(
        call_agent_tool=call_agent_tool,
        run_events=run_events,
    )
    messages = [{"role": "user", "content": "open Music and verify it"}]

    runner.run(
        [
            {
                "tool": "desktop.verify",
                "input": {"app_name": "Music", "expected_text": "Playing"},
                "source": "runtime_post_action_auto_verify",
                "runtime_stage": "verify",
                "requires_observation": True,
                "replan_triggers": ["verification_failed"],
            },
            {"tool": "workspace.read", "input": {"path": "README.md"}},
        ],
        ["desktop.verify", "workspace.read"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-nested-verify-failed",
        budget=FakeBudget(),
    )

    assert calls == ["desktop.verify"]
    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    assert replan_event["payload"]["trigger"] == "verification_failed"
    assert replan_event["payload"]["source_tool_name"] == "desktop.verify"
    assert replan_event["payload"]["metadata"]["result_preview"]["verification_failed"] is True
    assert replan_event["payload"]["metadata"]["result_preview"]["verification_passed"] is False
    assert "verification_failed" in messages[-1]["content"]
    assert any(event_type == "agent.replan.requested" for _run_id, event_type, _payload in run_events)


def test_runtime_tool_request_runner_synthesizes_observation_retry_recovery_action() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    observation_retry = {
        "from_tool": "desktop.active_window",
        "tool": "desktop.active_window",
        "input": {
            "app_name": "PixelForge",
            "query": "PixelForge",
            "selection_source": "desktop.list_apps",
        },
        "reason": "verification_failed",
    }
    action_target = {
        "kind": "desktop_app",
        "action": "verify_after_action",
        "app_name": "PixelForge",
        "step_id": "verify-desktop-result",
    }
    observation_evidence = {
        "source_tool": "desktop.active_window",
        "app_name": "PixelForge",
    }

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "verification_failed": True,
            "summary": "Active app was not PixelForge.",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "desktop.active_window",
                "input": {},
                "source": "runtime_planner",
                "step_id": "verify-desktop-result",
                "capability_id": "desktop.visual_verification",
                "decision_id": "decision-1",
                "plan_id": "plan-1",
                "runtime_stage": "verify",
                "requires_observation": True,
                "replan_triggers": ["verification_failed"],
                "action_target": action_target,
                "observation_evidence": observation_evidence,
                "observation_retry": observation_retry,
            }
        ],
        ["desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open PixelForge"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-observation-retry",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["trigger"] == "verification_failed"
    assert payload["fallback_tools"] == ["desktop.active_window"]
    assert payload["action_target"] == action_target
    assert payload["observation_evidence"] == observation_evidence
    assert payload["observation_retry"] == observation_retry
    assert payload["recovery_actions"] == payload["metadata"]["recovery_actions"]
    assert payload["metadata"]["recovery_actions"] == [
        {
            "label": "Re-run runtime observation",
            "tool": "desktop.active_window",
            "input": {
                "app_name": "PixelForge",
                "query": "PixelForge",
                "selection_source": "desktop.list_apps",
            },
            "permission_target": "runtime_observation",
            "risk_level": "low",
            "observation_retry": observation_retry,
            "action_target": action_target,
            "observation_evidence": observation_evidence,
            "metadata": {
                "runtime_replan_auto_start_eligible": True,
                "runtime_replan_auto_start_reason": (
                    "safe_low_risk_runtime_replan_recovery"
                ),
                "runtime_replan_auto_start_blockers": [],
            },
        }
    ]
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["metadata"]["recovery_actions"] == payload["metadata"][
        "recovery_actions"
    ]
    assert run_replan_event["recovery_actions"] == payload["recovery_actions"]


def test_runtime_tool_request_runner_marks_unsafe_recovery_actions_manual() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "terminal retry failed",
        },
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {"path": "sales.csv"},
                "source": "runtime_planner",
                "step_id": "analyze-data",
                "capability_id": "data.analysis",
                "requires_observation": True,
                "replan_triggers": ["tool_failure"],
                "recovery_actions": [
                    {
                        "label": "Run fallback script",
                        "tool": "terminal.run",
                        "input": {"command": "python analyze_sales.py"},
                        "risk_level": "high",
                        "approval_required": True,
                    }
                ],
            }
        ],
        ["data.analyze", "terminal.run"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Analyze sales.csv"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-unsafe-recovery",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    action_metadata = replan_event["payload"]["metadata"]["recovery_actions"][0]["metadata"]
    assert action_metadata["runtime_replan_auto_start_eligible"] is False
    assert action_metadata["runtime_replan_auto_start_reason"] == (
        "manual_runtime_replan_recovery_required"
    )
    assert action_metadata["runtime_replan_auto_start_blockers"] == [
        "approval_required",
        "high_risk",
        "tool_not_auto_safe",
    ]


def test_runtime_tool_request_runner_records_explicit_desktop_verification_target() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_requests.append(tool_request)
        return {
            "ok": False,
            "verification_failed": True,
            "error": "foreground_focus_unverified",
            "blocking_condition": "foreground_focus_unverified",
            "blocking_conditions": ["foreground_focus_unverified"],
            "summary": "Chrome is active",
            "expected_app_name": "PixelForge",
            "active_app_name": "Chrome",
            "data": {
                "app_name": "Chrome",
                "title": "Search",
                "expected_app_name": "PixelForge",
                "active_app_name": "Chrome",
                "focus_verified": False,
            },
        }

    runner = _runner(
        call_agent_tool=call_agent_tool,
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "desktop.active_window",
                "input": {},
                "source": "runtime_verification",
                "planning_reason": "runtime_desktop_app_foreground_verification",
                "capability_id": "desktop.visual_verification",
                "runtime_doctrine": "discover_operate_verify",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "requires_observation": True,
                "replan_triggers": ["verification_failed"],
                "target_app_name": "PixelForge",
                "verification_target": {"app_name": "PixelForge"},
            }
        ],
        ["app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open PixelForge"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-explicit-desktop-verification-target",
        budget=FakeBudget(),
    )

    assert seen_requests[0]["verification_target"] == {"app_name": "PixelForge"}
    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["trigger"] == "verification_failed"
    assert payload["source_tool_name"] == "desktop.active_window"
    assert payload["target_app_name"] == "PixelForge"
    assert payload["metadata"]["target_app_name"] == "PixelForge"
    assert payload["verification_targets"] == [
        {
            "kind": "desktop_verification_target",
            "tool_name": "desktop.active_window",
            "app_name": "PixelForge",
            "target_app_name": "PixelForge",
        }
    ]
    assert payload["action_target"] == {
        "kind": "desktop_verification_target",
        "action": "verify_after_action",
        "verification_tool": "desktop.active_window",
        "tool_name": "desktop.active_window",
        "app_name": "PixelForge",
    }
    actions = payload["metadata"]["recovery_actions"]
    assert actions[0]["tool"] == "app.open"
    assert actions[0]["input"] == {"app_name": "PixelForge"}
    assert actions[0]["selected"] is True
    assert actions[0]["observation_retry"]["reason"] == "foreground_focus_unverified"
    assert actions[0]["deferred_continuation"][0]["tool"] == "desktop.active_window"
    assert actions[0]["deferred_continuation"][0]["verification_target"] == {
        "app_name": "PixelForge",
        "source_tool": "desktop.active_window",
    }
    assert (
        actions[0]["action_target"]
        == payload["action_target"]
    )
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["target_app_name"] == "PixelForge"
    assert run_replan_event["metadata"]["target_app_name"] == "PixelForge"


def test_runtime_tool_request_runner_synthesizes_default_desktop_failure_replan() -> None:
    calls: list[str] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(str(tool_request.get("tool") or ""))
        return {
            "ok": False,
            "error": "foreground input failed",
        }

    runner = _runner(
        call_agent_tool=call_agent_tool,
        run_events=run_events,
    )
    messages = [{"role": "user", "content": "type into the current app"}]

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
            },
            {
                "tool": "desktop.safe_key",
                "input": {"action": "return"},
            },
        ],
        ["desktop.safe_type_text", "desktop.safe_key"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-default-desktop-replan",
        budget=FakeBudget(),
    )

    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]

    assert payload["trigger"] == "tool_failure"
    assert payload["source_tool_name"] == "desktop.safe_type_text"
    assert payload["fallback_tools"] == [
        "desktop.active_window",
        "desktop.ui_elements",
        "screen.capture",
    ]
    assert [
        action["tool"] for action in payload["metadata"]["recovery_actions"]
    ] == [
        "desktop.active_window",
        "desktop.ui_elements",
        "screen.capture",
    ]
    assert calls == ["desktop.safe_type_text"]
    assert len([event for event in timeline if event["event"] == "agent.replan.requested"]) == 1
    run_replan_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.replan.requested"
    )
    assert run_replan_event["fallback_tools"] == payload["fallback_tools"]
    assert "recovery_actions" in messages[-1]["content"]


def test_runtime_tool_call_executor_denies_unallowed_tools_before_broker_call() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    budget = FakeBudget()
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True})

    with pytest.raises(AgentRuntimeError, match="未授权工具"):
        executor.execute(
            {
                "tool": "terminal.run",
                "tool_call_id": "call-denied",
                "input": {"command": "echo hi"},
            },
            ["workspace.read"],
            broker,
            timeline,
            run_id="run-1",
            budget=budget,
        )

    assert budget.claims == [("terminal.run", False)]
    assert broker.calls == []
    assert timeline == [
        {
            "event": "agent.tool.denied",
            "detail": "terminal.run",
            "input_preview": {"command": "echo hi"},
            "tool_call_id": "call-denied",
            "run_id": "run-1",
            "actor": "native_runtime",
            "visibility": "internal",
            "execution_authority": "runtime_tool_executor",
        }
    ]
    assert [call[0] for call in events.calls] == ["denied"]


def test_runtime_tool_call_executor_uses_injected_policy_gate() -> None:
    events = FakeToolCallEvents()
    policy_calls: list[tuple[str, list[str]]] = []
    executor = _executor(
        tool_call_events=events,
        allows_tool=lambda tool_name, allowed_tools: policy_calls.append(
            (tool_name, allowed_tools)
        )
        or False,
    )
    broker = FakeBroker({"ok": True})

    with pytest.raises(AgentRuntimeError, match="未授权工具"):
        executor.execute(
            {"tool": "workspace.read", "input": {"path": "README.md"}},
            ["workspace.read"],
            broker,
            [],
            budget=FakeBudget(),
        )

    assert policy_calls == [("workspace.read", ["workspace.read"])]
    assert broker.calls == []


def test_runtime_tool_call_executor_validates_active_window_target_before_projection() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    timeline: list[dict[str, Any]] = []

    result = executor.execute(
        {
            "tool": "desktop.active_window",
            "input": {},
            "verification_target": {"app_name": "Safari"},
        },
        ["desktop.active_window"],
        FakeBroker({"ok": True, "data": {"app_name": "Google Chrome", "title": "Search"}}),
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["verification_failed"] is True
    assert result["error"] == "foreground_focus_unverified"
    assert result["data"]["expected_app_name"] == "Safari"
    assert result["data"]["active_app_name"] == "Google Chrome"
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"]["ok"] is False
    assert events.calls[-1][0] == "agent_tool_call"
    assert events.calls[-1][1][3]["ok"] is False

    matching_timeline: list[dict[str, Any]] = []
    matching = executor.execute(
        {
            "tool": "desktop.active_window",
            "input": {},
            "verification_target": {"app_name": "Chrome"},
        },
        ["desktop.active_window"],
        FakeBroker({"ok": True, "data": {"app_name": "Google Chrome", "title": "Search"}}),
        matching_timeline,
        run_id="run-2",
        budget=FakeBudget(),
    )

    assert matching["ok"] is True
    assert matching["data"]["focus_verified"] is True

    substring_collision = executor.execute(
        {
            "tool": "desktop.active_window",
            "input": {},
            "verification_target": {"app_name": "Notes"},
        },
        ["desktop.active_window"],
        FakeBroker(
            {
                "ok": True,
                "action": "desktop.active_window",
                "data": {"app_name": "Notes Helper", "title": "Background"},
            }
        ),
        [],
        run_id="run-substring-collision",
        budget=FakeBudget(),
    )

    assert substring_collision["ok"] is False
    assert substring_collision["verification_failed"] is True
    assert substring_collision["data"]["focus_verified"] is False


def test_runtime_tool_call_executor_projects_workspace_failure_as_tool_result() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker(AgentRuntimeError("outside workspace"))

    result = executor.execute(
        {"tool": "workspace.read", "input": {"path": "../secret.txt"}},
        ["workspace.read", "terminal.run"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["tool"] == "workspace.read"
    assert result["suggested_tool"] == "terminal.run"
    assert "relative paths" in result["hint"]
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"] == result
    assert [call[0] for call in events.calls] == [
        "requested",
        "started",
        "result",
        "agent_tool_call",
    ]


def test_runtime_pins_owned_background_scope_instead_of_using_local_route() -> None:
    owner = FakeOwnedBackgroundAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([owner]),
    )
    broker = FakeBroker({"ok": True, "unexpected_local_read": True})
    timeline: list[dict[str, Any]] = []

    result = executor.execute(
        {
            "tool": "desktop.read_ui",
            "input": {},
            "desktop_execution_route": {
                "tool_name": "desktop.read_ui",
                "selected_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                "selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
                "status": "provider_ready",
                "can_execute": True,
                "foreground_takeover_allowed": True,
            },
        },
        ["desktop.read_ui"],
        broker,
        timeline,
        run_id="run-owned-background-affinity",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert result["desktop_execution_route"]["desktop_provider_affinity"] is True
    assert result["desktop_execution_route"]["selected_provider_id"] == (
        "owned-background-1"
    )
    assert result["desktop_execution_route"]["foreground_takeover_allowed"] is False
    assert owner.calls[0]["tool"] == "desktop.read_ui"
    assert broker.calls == []


def test_runtime_validates_and_routes_background_only_app_open_to_provider() -> None:
    class CapturingBackgroundLaunchAdapter(FakeTrustedVerificationAdapter):
        def __init__(self) -> None:
            super().__init__()
            self.payloads: list[dict[str, Any]] = []

        def execute(self, tool_name: str, payload: dict[str, Any], **kwargs: Any):
            self.payloads.append(dict(payload))
            return super().execute(tool_name, payload, **kwargs)

    adapter = CapturingBackgroundLaunchAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
        validate_tool_payload=ToolDescriptorRegistry.validate_payload,
    )
    broker = FakeBroker({"ok": True, "unexpected_local_open": True})

    result = executor.execute(
        {
            "tool": "app.open",
            "input": {"app_name": "TextEdit", "bring_to_front": False},
        },
        ["app.open"],
        broker,
        [],
        run_id="run-background-only-open",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert adapter.payloads == [
        {"app_name": "TextEdit", "bring_to_front": False}
    ]
    assert broker.calls == []


def test_runtime_fails_closed_when_owned_background_provider_lacks_tool() -> None:
    owner = FakeOwnedBackgroundAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([owner]),
    )
    broker = FakeBroker({"ok": True, "unexpected_local_verify": True})
    timeline: list[dict[str, Any]] = []

    result = executor.execute(
        {
            "tool": "desktop.verify",
            "input": {},
            "desktop_execution_route": {
                "tool_name": "desktop.verify",
                "selected_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                "selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
                "status": "provider_ready",
                "can_execute": True,
                "foreground_takeover_allowed": True,
            },
        },
        ["desktop.verify"],
        broker,
        timeline,
        run_id="run-owned-background-unsupported",
        budget=FakeBudget(),
    )

    route = result["desktop_execution_route"]
    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["blocked_by_desktop_execution_provider"] is True
    assert result["status"] == "provider_capability_mismatch"
    assert result["error"] == "desktop_execution_provider_tool_unavailable"
    assert result["desktop_provider_capability_mismatch"] is True
    assert result["retryable"] is True
    assert result["replan_allowed"] is True
    assert result["retry_with_alternative_capability"] is True
    assert result["user_handoff_recommended"] is False
    assert result["recommended_tools"] == []
    assert result["recovery_actions"] == []
    assert route["selected_provider_kind"] == "background_desktop"
    assert route["selected_provider_id"] == "owned-background-1"
    assert route["fallback_mode"] == "user_handoff"
    assert route["blocking_conditions"] == [
        "desktop_execution_provider_tool_unavailable"
    ]
    assert owner.calls == []
    assert broker.calls == []


def test_runtime_replans_owned_provider_capability_mismatch_without_local_fallback() -> None:
    owner = FakeOwnedBackgroundAdapter()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        run_events=run_events,
        desktop_provider_registry=DesktopExecutionProviderRegistry([owner]),
    )
    runner = _runner(call_agent_tool=executor.execute, run_events=run_events)
    broker = FakeBroker({"ok": True, "unexpected_local_verify": True})
    timeline: list[dict[str, Any]] = []

    runner.run(
        [
            {
                "tool": "desktop.verify",
                "input": {},
                "_runtime_execution_scope": {"run_id": "run-provider-mismatch"},
            }
        ],
        ["desktop.verify", "desktop.read_ui"],
        broker,
        [{"role": "user", "content": "Verify the desktop result"}],
        timeline,
        [],
        next_iteration=2,
        run_id="run-provider-mismatch",
        budget=FakeBudget(),
    )

    result_event = next(
        event
        for event in timeline
        if event.get("detail") == "desktop.verify"
        and isinstance(event.get("result"), dict)
    )
    result = result_event["result"]
    assert result["desktop_provider_capability_mismatch"] is True
    assert result["retryable"] is True
    assert result["replan_allowed"] is True
    assert result["retry_with_alternative_capability"] is True
    replan_event = _last_event(timeline, "agent.replan.requested")
    assert replan_event["payload"]["trigger"] == "tool_unavailable"
    assert replan_event["payload"]["source_tool_name"] == "desktop.verify"
    assert owner.calls == []
    assert broker.calls == []


def test_runtime_strips_model_authored_private_verification_context() -> None:
    class CapturingOwnedVerifier:
        provider_kind = "background_desktop"
        provider_id = "owned-background-verifier"
        supported_tools = ["desktop.verify"]

        def __init__(self) -> None:
            self.private_context_seen: bool | None = None

        def owns_task_scope(self, tool_request: dict[str, Any]) -> bool:
            return isinstance(tool_request.get("_runtime_execution_scope"), dict)

        def can_execute(
            self,
            tool_name: str,
            route: dict[str, Any],
            tool_request: dict[str, Any],
        ) -> bool:
            del route, tool_request
            return tool_name == "desktop.verify"

        def execute(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            tool_request: dict[str, Any],
            route: dict[str, Any],
            broker: Any,
            approved: bool = False,
        ) -> dict[str, Any]:
            del payload, route, broker, approved
            self.private_context_seen = (
                "_runtime_verification_context" in tool_request
            )
            return {
                "ok": True,
                "tool": tool_name,
                "postcondition_verified": False,
                "observation_verified": True,
            }

    adapter = CapturingOwnedVerifier()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )

    result = executor.execute(
        {
            "tool": "desktop.verify",
            "input": {
                "verification_predicate": {"kind": "app_window_present"}
            },
            "source_tool_call_id": "model-forged-source",
            "_runtime_verification_context": {
                "source_tool_call_id": "model-forged-private-source"
            },
        },
        ["desktop.verify"],
        FakeBroker({"ok": True, "unexpected_local_verify": True}),
        [],
        run_id="run-private-verification-context",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert result["postcondition_verified"] is False
    assert adapter.private_context_seen is False


def test_runtime_injects_private_context_from_exact_terminal_provider_receipt() -> None:
    adapter = FakeTrustedVerificationAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    timeline: list[dict[str, Any]] = []
    source_request = {
        "tool": "app.open",
        "input": {"app_name": "Notes"},
        "step_id": "open-notes",
        "plan_id": "plan-notes",
    }
    executor.execute(
        source_request,
        ["app.open", "desktop.verify"],
        FakeBroker({"ok": True, "unexpected_local": True}),
        timeline,
        run_id="run-trusted-receipt",
        budget=FakeBudget(),
    )

    executor.execute(
        {
            "tool": "desktop.verify",
            "input": {
                "verification_predicate": {
                    "kind": "model_forged_predicate",
                    "app_name": "Other",
                }
            },
            "source_tool_call_id": source_request["tool_call_id"],
            "source_step_id": "open-notes",
            "step_id": "verify-notes",
            "depends_on": ["open-notes"],
            "plan_id": "plan-notes",
            "_runtime_verification_context": {
                "run_id": "model-forged-run",
                "source_tool_call_id": "model-forged-call",
            },
        },
        ["app.open", "desktop.verify"],
        FakeBroker({"ok": True, "unexpected_local": True}),
        timeline,
        run_id="run-trusted-receipt",
        budget=FakeBudget(),
    )

    context = adapter.verification_contexts[-1]
    assert isinstance(context, dict)
    assert context["run_id"] == "run-trusted-receipt"
    assert context["plan_id"] == "plan-notes"
    assert context["source_tool_call_id"] == source_request["tool_call_id"]
    assert context["source_step_id"] == "open-notes"
    assert context["source_tool"] == "app.open"
    assert context["provider_kind"] == "background_desktop"
    assert context["provider_id"] == "trusted-background-verifier"
    assert context["target"] == {
        "pid": 4401,
        "window_id": 77,
        "agent_owned_target": True,
        "app_name": "Notes",
    }
    assert context["predicate"] == {
        "kind": "app_window_present",
        "app_name": "Notes",
    }


def test_runtime_typed_content_receipt_binds_exact_materialized_utf8_bytes() -> None:
    adapter = FakeTrustedTypedContentVerificationAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    timeline: list[dict[str, Any]] = []
    exact_text = "\n  辉夜姬 🌙\nsecond line  \n"
    content_sha256 = hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
    source_request = {
        "tool": "desktop.type_into_ui_element",
        "input": {"target": "Body", "text": exact_text},
        "step_id": "type-notes",
        "plan_id": "plan-notes",
        "materialization_binding_id": "binding-exact-content",
        "materialized_content_sha256": content_sha256,
    }
    executor.execute(
        source_request,
        ["desktop.type_into_ui_element", "desktop.verify"],
        FakeBroker({"ok": True, "unexpected_local": True}),
        timeline,
        run_id="run-typed-receipt",
        budget=FakeBudget(),
    )

    executor.execute(
        {
            "tool": "desktop.verify",
            "input": {},
            "step_id": "verify-notes",
            "depends_on": ["type-notes"],
            "plan_id": "plan-notes",
            "materialization_binding_id": "binding-exact-content",
            "materialized_content_sha256": content_sha256,
        },
        ["desktop.type_into_ui_element", "desktop.verify"],
        FakeBroker({"ok": True, "unexpected_local": True}),
        timeline,
        run_id="run-typed-receipt",
        budget=FakeBudget(),
    )

    context = adapter.verification_contexts[-1]
    assert isinstance(context, dict)
    assert context["materialization_binding_id"] == "binding-exact-content"
    assert context["materialized_content_sha256"] == content_sha256
    assert context["predicate"] == {
        "kind": "exact_typed_content_present",
        "expected_text": exact_text,
        "text_sha256": content_sha256,
    }


@pytest.mark.parametrize(
    ("action_hash", "verifier_binding", "verifier_hash"),
    (
        ("wrong-action-hash", "binding-exact-content", "expected-hash"),
        ("expected-hash", "wrong-binding", "expected-hash"),
        ("expected-hash", "binding-exact-content", "wrong-verifier-hash"),
    ),
)
def test_runtime_typed_content_receipt_rejects_wrong_materialization_identity(
    action_hash: str,
    verifier_binding: str,
    verifier_hash: str,
) -> None:
    adapter = FakeTrustedTypedContentVerificationAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    timeline: list[dict[str, Any]] = []
    exact_text = "expected-hash-content"
    expected_hash = hashlib.sha256(exact_text.encode("utf-8")).hexdigest()
    resolved_action_hash = expected_hash if action_hash == "expected-hash" else action_hash
    resolved_verifier_hash = (
        expected_hash if verifier_hash == "expected-hash" else verifier_hash
    )
    executor.execute(
        {
            "tool": "desktop.type_into_ui_element",
            "input": {"target": "Body", "text": exact_text},
            "step_id": "type-notes",
            "plan_id": "plan-notes",
            "materialization_binding_id": "binding-exact-content",
            "materialized_content_sha256": resolved_action_hash,
        },
        ["desktop.type_into_ui_element", "desktop.verify"],
        FakeBroker({"ok": True}),
        timeline,
        run_id="run-typed-receipt-negative",
        budget=FakeBudget(),
    )
    executor.execute(
        {
            "tool": "desktop.verify",
            "input": {},
            "step_id": "verify-notes",
            "depends_on": ["type-notes"],
            "plan_id": "plan-notes",
            "materialization_binding_id": verifier_binding,
            "materialized_content_sha256": resolved_verifier_hash,
        },
        ["desktop.type_into_ui_element", "desktop.verify"],
        FakeBroker({"ok": True}),
        timeline,
        run_id="run-typed-receipt-negative",
        budget=FakeBudget(),
    )

    assert adapter.verification_contexts[-1] is None


def test_runtime_derives_verifier_source_from_unique_same_plan_private_receipt() -> None:
    adapter = FakeTrustedVerificationAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    timeline: list[dict[str, Any]] = []
    source_request = {
        "tool": "app.open",
        "input": {"app_name": "Notes"},
        "step_id": "open-notes",
        "plan_id": "plan-notes",
        "tool_plan_id": "tool-plan-notes",
    }
    executor.execute(
        source_request,
        ["app.open", "desktop.verify"],
        FakeBroker({"ok": True, "unexpected_local": True}),
        timeline,
        run_id="run-private-derived-source",
        budget=FakeBudget(),
    )

    executor.execute(
        {
            "tool": "desktop.verify",
            "input": {},
            "step_id": "verify-notes",
            "depends_on": ["open-notes"],
            "plan_id": "plan-notes",
            "tool_plan_id": "tool-plan-notes",
            # Serialized/model-authored source ids are deliberately wrong.
            # The executor must replace them from its private receipt store.
            "source_tool_call_id": "model-forged-call",
            "source_step_id": "model-forged-step",
        },
        ["app.open", "desktop.verify"],
        FakeBroker({"ok": True, "unexpected_local": True}),
        timeline,
        run_id="run-private-derived-source",
        budget=FakeBudget(),
    )

    context = adapter.verification_contexts[-1]
    assert isinstance(context, dict)
    assert context["source_tool_call_id"] == source_request["tool_call_id"]
    assert context["source_step_id"] == "open-notes"
    verifier_event = next(
        event
        for event in reversed(timeline)
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "desktop.verify"
    )
    assert verifier_event["step_id"] == "verify-notes"
    assert verifier_event["source_tool_call_id"] == source_request["tool_call_id"]
    assert verifier_event["source_step_id"] == "open-notes"


@pytest.mark.parametrize(
    "mismatch",
    [
        "run",
        "plan",
        "tool_plan",
        "provider",
        "target",
        "ambiguous",
        "missing_dependency",
    ],
)
def test_runtime_private_verification_context_fails_closed_on_mismatch(
    mismatch: str,
) -> None:
    adapter = FakeTrustedVerificationAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    timeline: list[dict[str, Any]] = []
    source_request = {
        "tool": "app.open",
        "input": {"app_name": "Notes"},
        "step_id": "open-notes",
        "plan_id": "plan-notes",
        "tool_plan_id": "tool-plan-notes",
    }
    executor.execute(
        source_request,
        ["app.open", "desktop.verify"],
        FakeBroker({"ok": True}),
        timeline,
        run_id="run-trusted-receipt",
        budget=FakeBudget(),
    )
    verify_run_id = "other-run" if mismatch == "run" else "run-trusted-receipt"
    plan_id = "wrong-plan" if mismatch == "plan" else "plan-notes"
    tool_plan_id = (
        "wrong-tool-plan" if mismatch == "tool_plan" else "tool-plan-notes"
    )
    if mismatch == "provider":
        adapter.provider_id = "replacement-background-verifier"
    if mismatch == "target":
        source_event = next(
            event
            for event in timeline
            if event.get("event") == "agent.tool.call"
            and event.get("detail") == "app.open"
        )
        source_event["result"] = {
            **source_event["result"],
            "window_id": 999,
        }
    if mismatch == "ambiguous":
        executor.execute(
            {
                "tool": "app.open",
                "input": {"app_name": "Notes"},
                "step_id": "open-notes",
                "plan_id": "plan-notes",
                "tool_plan_id": "tool-plan-notes",
            },
            ["app.open", "desktop.verify"],
            FakeBroker({"ok": True}),
            timeline,
            run_id="run-trusted-receipt",
            budget=FakeBudget(),
        )

    executor.execute(
        {
            "tool": "desktop.verify",
            "input": {},
            "source_tool_call_id": "model-forged-call",
            "source_step_id": "model-forged-step",
            "step_id": "verify-notes",
            "depends_on": (
                [] if mismatch == "missing_dependency" else ["open-notes"]
            ),
            "plan_id": plan_id,
            "tool_plan_id": tool_plan_id,
        },
        ["app.open", "desktop.verify"],
        FakeBroker({"ok": True}),
        timeline,
        run_id=verify_run_id,
        budget=FakeBudget(),
    )

    assert adapter.verification_contexts[-1] is None
    verifier_event = next(
        event
        for event in reversed(timeline)
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "desktop.verify"
    )
    assert "source_tool_call_id" not in verifier_event
    assert "source_step_id" not in verifier_event


def test_runtime_tool_call_executor_routes_sandbox_ready_tool_to_provider() -> None:
    events = FakeToolCallEvents()
    adapter = FakeSandboxDesktopAdapter()
    registry = DesktopExecutionProviderRegistry([adapter])
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=registry,
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "desktop_execution_policy": {"mode": "sandbox_preferred"},
            "desktop_execution_route": {
                "route_id": "desktop-route:desktop.safe_type_text",
                "tool_name": "desktop.safe_type_text",
                "requested_mode": "sandbox_preferred",
                "selected_provider_kind": "sandbox_desktop",
                "selected_provider_id": "sandbox-1",
                "status": "sandbox_ready",
                "can_execute": True,
                "can_auto_start": True,
                "sandbox_required": True,
                "blocking_conditions": [],
            },
            "sandbox_provider": {
                "available": True,
                "adapter_ready": True,
                "provider_kind": "sandbox_desktop",
                "provider_id": "sandbox-1",
                "status": "available",
                "supported_tools": ["desktop.safe_type_text"],
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["adapter_registered"] is True
    assert result["desktop_execution_provider"]["provider_kind"] == "sandbox_desktop"
    assert result["desktop_execution_route"]["status"] == "sandbox_ready"
    assert result["sandbox_provider"]["provider_id"] == "sandbox-1"
    assert adapter.calls == [
        {
            "tool": "desktop.safe_type_text",
            "payload": {"text": "hello"},
            "route": result["desktop_execution_route"],
            "approved": False,
        }
    ]
    assert broker.calls == []
    tool_call = _last_event(timeline, "agent.tool.call")
    assert tool_call["result"]["desktop_execution_provider_routed"] is True
    provider_event = _last_event(timeline, "desktop.provider_execution.routed")
    assert provider_event["desktop_execution_provider"]["provider_kind"] == "sandbox_desktop"
    assert provider_event["desktop_execution_route"]["status"] == "sandbox_ready"
    assert provider_event["sandbox_provider"]["provider_id"] == "sandbox-1"


def test_runtime_tool_call_executor_routes_running_provider_session_to_adapter() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    adapter = FakeSandboxDesktopAdapter()
    registry = DesktopExecutionProviderRegistry([adapter])
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=registry,
        run_events=run_events,
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "desktop_execution_policy": {
                "mode": "sandbox_preferred",
                "prefer_isolated_desktop": True,
                "avoid_user_foreground_takeover": True,
            },
            "desktop_provider_session": {
                "running": True,
                "status": "running",
                "provider_id": "sandbox-1",
                "url": "http://127.0.0.1:19093",
                "tool_names": ["desktop.safe_type_text"],
                "command": ["python", "scripts/run_isolated_desktop_provider.py"],
                "env": {
                    "OHA_YACHIYO_DESKTOP_PROVIDER_URL": "http://127.0.0.1:19093"
                },
                "desktop_session_kind": "isolated_desktop",
                "desktop_session_isolated": True,
                "foreground_takeover_required": False,
                "keyboard_mouse_capture_supported": True,
                "provider_manifest_evidence": {
                    "provider_id": "sandbox-1",
                    "ok": True,
                },
                "provider_conformance": {
                    "ok": True,
                    "public_release_ready": True,
                },
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_route"]["status"] == "sandbox_ready"
    assert result["desktop_execution_route"]["selected_provider_id"] == "sandbox-1"
    assert result["sandbox_provider"]["source"] == "desktop_provider_session"
    assert result["sandbox_provider"]["provider_manifest_evidence"]["provider_id"] == (
        "sandbox-1"
    )
    assert result["sandbox_provider"]["provider_conformance"]["public_release_ready"] is True
    assert result["desktop_provider_session"]["provider_id"] == "sandbox-1"
    assert result["desktop_provider_session"]["provider_conformance"] == {
        "ok": True,
        "public_release_ready": True,
    }
    assert "command" not in result["desktop_provider_session"]
    assert "env" not in result["desktop_provider_session"]
    assert adapter.calls == [
        {
            "tool": "desktop.safe_type_text",
            "payload": {"text": "hello"},
            "route": result["desktop_execution_route"],
            "approved": False,
        }
    ]
    assert broker.calls == []
    provider_event = _last_event(timeline, "desktop.provider_execution.routed")
    assert provider_event["desktop_execution_provider"]["provider_id"] == "sandbox-1"
    assert provider_event["desktop_execution_route"]["status"] == "sandbox_ready"
    assert provider_event["sandbox_provider"]["source"] == "desktop_provider_session"
    assert provider_event["sandbox_provider"]["provider_manifest_evidence"] == {
        "provider_id": "sandbox-1",
        "ok": True,
    }
    event_session = provider_event["desktop_provider_session"]
    assert event_session["provider_id"] == "sandbox-1"
    assert event_session["desktop_session_isolated"] is True
    assert event_session["foreground_takeover_required"] is False
    assert event_session["provider_conformance"]["public_release_ready"] is True
    assert "command" not in event_session
    assert "env" not in event_session
    assert any(
        event_type == "desktop.provider_execution.routed"
        and payload["desktop_execution_provider"]["provider_id"] == "sandbox-1"
        for _run_id, event_type, payload in run_events
    )


def test_runtime_tool_call_executor_routes_local_desktop_app_open_to_provider() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    registry = DesktopExecutionProviderRegistry([LocalDesktopExecutionProviderAdapter()])
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=registry,
        run_events=run_events,
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker(
        {
            "ok": True,
            "action": "app.open",
            "summary": "Opened PixelForge",
            "data": {"app_name": "PixelForge"},
        }
    )

    result = executor.execute(
        {
            "tool": "app.open",
            "input": {"app_name": "PixelForge"},
            "allow_user_foreground_takeover": True,
            "desktop_execution_policy": {
                "mode": "allow",
                "allow_live_foreground": True,
                "prefer_background_desktop": False,
                "prefer_isolated_desktop": False,
                "avoid_user_foreground_takeover": False,
                "require_sandbox_for_keyboard_mouse": False,
            },
            "desktop_execution_route": {
                "route_id": "desktop-route:app.open",
                "tool_name": "app.open",
                "requested_mode": "preview_input",
                "selected_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                "selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
                "status": "provider_ready",
                "can_execute": True,
                "can_auto_start": True,
                "sandbox_required": False,
                "foreground_takeover_allowed": True,
                "foreground_takeover_required": True,
                "requires_user_foreground_session": True,
                "user_foreground_takeover_risk": True,
                "blocking_conditions": [],
            },
            "sandbox_provider": {
                "available": True,
                "adapter_ready": True,
                "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
                "status": "available",
                "supported_tools": ["app.open"],
            },
        },
        ["app.open"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert result["desktop_execution_provider_routed"] is True
    assert result["desktop_execution_provider"]["adapter_registered"] is True
    assert result["desktop_execution_provider"]["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert result["desktop_execution_provider"]["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert result["local_desktop_provider"]["provider_id"] == LOCAL_DESKTOP_PROVIDER_ID
    assert result["desktop_execution_route"]["status"] == "provider_ready"
    assert result["sandbox_provider"]["provider_kind"] == LOCAL_DESKTOP_PROVIDER_KIND
    assert broker.calls == [("app.open", {"app_name": "PixelForge"}, False)]
    notice = next(
        event for event in timeline if event["event"] == "agent.tool.foreground_session_notice"
    )
    assert notice["detail"] == "app.open"
    assert notice["user_foreground_takeover_risk"] is True
    assert notice["foreground_takeover_required"] is True
    assert notice["desktop_execution_route"]["selected_provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert run_events[0][1] == "agent.tool.foreground_session_notice"
    assert run_events[0][2]["tool"] == "app.open"
    tool_call = _last_event(timeline, "agent.tool.call")
    assert tool_call["result"]["local_desktop_provider"]["provider_id"] == (
        LOCAL_DESKTOP_PROVIDER_ID
    )
    provider_event = _last_event(timeline, "desktop.provider_execution.routed")
    assert provider_event["desktop_execution_provider"]["provider_id"] == (
        LOCAL_DESKTOP_PROVIDER_ID
    )


def test_runtime_tool_call_executor_blocks_provider_route_until_approved() -> None:
    events = FakeToolCallEvents()
    adapter = FakeSandboxDesktopAdapter()
    registry = DesktopExecutionProviderRegistry([adapter])
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=registry,
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})
    broker.approvals = {"desktop.safe_type_text": True}

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "approval_required": True,
            "risk_level": "high",
            "policy_reason": "Provider-routed foreground input requires approval.",
            "desktop_execution_policy": {"mode": "sandbox_preferred"},
            "desktop_execution_route": {
                "route_id": "desktop-route:desktop.safe_type_text",
                "tool_name": "desktop.safe_type_text",
                "requested_mode": "sandbox_preferred",
                "selected_provider_kind": "sandbox_desktop",
                "selected_provider_id": "sandbox-1",
                "status": "sandbox_ready",
                "can_execute": True,
                "can_auto_start": True,
                "sandbox_required": True,
                "blocking_conditions": [],
            },
            "sandbox_provider": {
                "available": True,
                "adapter_ready": True,
                "provider_kind": "sandbox_desktop",
                "provider_id": "sandbox-1",
                "status": "available",
                "supported_tools": ["desktop.safe_type_text"],
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["approval_required"] is True
    assert result["risk_level"] == "high"
    assert result["policy_reason"] == (
        "Provider-routed foreground input requires approval."
    )
    assert adapter.calls == []
    assert broker.calls == []
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["result"]["approval_required"] is True


def test_runtime_tool_call_executor_fails_closed_when_provider_adapter_is_missing() -> None:
    events = FakeToolCallEvents()
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=DesktopExecutionProviderRegistry(),
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "desktop_execution_policy": {"mode": "sandbox_preferred"},
            "desktop_execution_route": {
                "route_id": "desktop-route:desktop.safe_type_text",
                "tool_name": "desktop.safe_type_text",
                "requested_mode": "sandbox_preferred",
                "selected_provider_kind": "sandbox_desktop",
                "selected_provider_id": "sandbox-1",
                "status": "sandbox_ready",
                "can_execute": True,
                "can_auto_start": True,
                "sandbox_required": True,
                "blocking_conditions": [],
            },
            "sandbox_provider": {
                "available": True,
                "adapter_ready": True,
                "provider_kind": "sandbox_desktop",
                "provider_id": "sandbox-1",
                "status": "available",
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_provider"] is True
    assert result["error"] == "desktop_execution_provider_unavailable"
    assert result["blocking_conditions"] == ["desktop_execution_provider_unavailable"]
    assert result["desktop_execution_provider"]["adapter_registered"] is False
    assert result["desktop_execution_route"]["status"] == "sandbox_ready"
    assert result["recommended_tools"] == ["desktop.provider_session.start"]
    recovery = result["recovery_actions"][0]
    assert recovery["tool"] == "desktop.provider_session.start"
    assert recovery["input"]["tools"] == ["desktop.safe_type_text"]
    assert recovery["approval_required"] is True
    assert recovery["metadata"]["runtime_retry_source"] == "desktop_provider_session"
    assert recovery["deferred_tool"] == "desktop.safe_type_text"
    assert recovery["deferred_continuation"][0]["tool"] == "desktop.safe_type_text"
    assert "desktop_execution_route" not in recovery["deferred_continuation"][0]
    assert broker.calls == []
    tool_call = _last_event(timeline, "agent.tool.call")
    assert tool_call["result"]["blocked_by_desktop_execution_provider"] is True


def test_runtime_tool_request_runner_replans_missing_desktop_provider() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(
        tool_call_events=events,
        run_events=run_events,
        desktop_provider_registry=DesktopExecutionProviderRegistry(),
    )
    runner = _runner(call_agent_tool=executor.execute, run_events=run_events)
    timeline: list[dict[str, Any]] = []

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {"mode": "sandbox_preferred"},
                "desktop_execution_route": {
                    "route_id": "desktop-route:desktop.safe_type_text",
                    "tool_name": "desktop.safe_type_text",
                    "requested_mode": "sandbox_preferred",
                    "selected_provider_kind": "sandbox_desktop",
                    "selected_provider_id": "sandbox-1",
                    "status": "sandbox_ready",
                    "can_execute": True,
                    "can_auto_start": True,
                    "sandbox_required": True,
                    "blocking_conditions": [],
                },
                "sandbox_provider": {
                    "available": True,
                    "adapter_ready": True,
                    "provider_kind": "sandbox_desktop",
                    "provider_id": "sandbox-1",
                    "status": "available",
                },
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True, "unexpected": True}),
        [{"role": "user", "content": "在隔离桌面里输入 hello"}],
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=FakeBudget(),
    )

    replan_event = next(
        event for event in timeline if event["event"] == "agent.replan.requested"
    )
    payload = replan_event["payload"]
    recovery = payload["recovery_actions"][0]
    assert payload["trigger"] == "desktop_execution_provider_unavailable"
    assert payload["source_tool_name"] == "desktop.safe_type_text"
    assert payload["fallback_tools"][0] == "desktop.provider_session.start"
    assert "desktop.active_window" in payload["fallback_tools"]
    assert recovery["tool"] == "desktop.provider_session.start"
    assert recovery["metadata"]["runtime_retry_source"] == "desktop_provider_session"
    assert recovery["metadata"]["runtime_replan_auto_start_eligible"] is False
    assert "approval_required" in recovery["metadata"]["runtime_replan_auto_start_blockers"]
    assert recovery["deferred_continuation"][0]["desktop_execution_policy"][
        "prefer_isolated_desktop"
    ] is True
    assert run_events[-1][1] == "agent.replan.requested"


def test_runtime_reacquires_stale_background_target_then_retries_read_only_observation() -> None:
    source_request = {
        "tool": "desktop.ui_elements",
        "tool_call_id": "observe-textedit-1",
        "input": {"app_name": "TextEdit", "role_filter": "text", "limit": 120},
        "runtime_stage": "discover",
        "runtime_role": "inspect_ui",
    }
    target_failure = {
        "event": "agent.tool.call",
        "detail": "desktop.ui_elements",
        "status": "failed",
        "result": {
            "ok": False,
            "status": "provider_target_invalidated",
            "error": "cua_background_target_identity_mismatch",
            "summary": "The cached pid no longer belongs to the launched app.",
            "blocked_by_desktop_execution_provider": False,
            "blocked_by_desktop_target": True,
            "target_reacquisition_required": True,
            "blocking_condition": "desktop_background_target_required",
            "retryable": True,
            "requires_user_handoff": False,
            "recommended_tools": ["app.open"],
            "desktop_execution_provider_transport": {
                "provider_kind": "background_desktop",
                "provider_id": "cua-driver",
                "delivery_mode": "background",
                "foreground_takeover_required": False,
            },
        },
    }

    replan_payload = (
        tool_execution_module._runtime_replan_request_payload_for_tool_result(
            source_request,
            target_failure,
            run_id="run-target-reacquisition",
        )
    )
    prior_timeline = [
        {
            "event": "agent.tool.call",
            "detail": "app.open",
            "input_preview": {"app_name": "TextEdit"},
            "result": {"ok": True},
        }
    ]
    recovery_requests = (
        tool_execution_module._runtime_replan_auto_recovery_action_requests(
            replan_payload,
            allowed_tools=["app.open", "desktop.ui_elements"],
            remaining_requests=[],
            timeline=prior_timeline,
            tool_timeline_start=0,
        )
    )

    assert replan_payload["trigger"] == "tool_failure"
    assert replan_payload["fallback_tools"] == ["app.open"]
    assert len(recovery_requests) == 1
    reopen_request = recovery_requests[0]
    assert reopen_request["tool"] == "app.open"
    assert reopen_request["input"] == {"app_name": "TextEdit"}
    assert reopen_request["recovery_action_kind"] == "desktop_target_reacquisition"
    assert reopen_request["allow_repeat_after_success"] is True

    continuation = (
        tool_execution_module._runtime_replan_deferred_continuation_requests(
            "app.open",
            reopen_request,
            {"ok": True},
            allowed_tools=["app.open", "desktop.ui_elements"],
            remaining_requests=[],
        )
    )
    assert len(continuation) == 1
    assert continuation[0]["tool"] == "desktop.ui_elements"
    assert continuation[0]["input"] == source_request["input"]


def test_runtime_tool_call_executor_blocks_policy_required_sandbox_before_broker() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(
        tool_call_events=events,
        run_events=run_events,
        desktop_provider_registry=DesktopExecutionProviderRegistry(),
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "unexpected": True})
    budget = FakeBudget()

    result = executor.execute(
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "desktop_execution_policy": {
                "mode": "supervised_live",
                "allow_live_foreground": True,
                "avoid_user_foreground_takeover": True,
                "require_sandbox_for_keyboard_mouse": True,
            },
        },
        ["desktop.safe_type_text"],
        broker,
        timeline,
        approved=True,
        run_id="run-1",
        budget=budget,
    )

    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["desktop_execution_route"]["can_execute"] is False
    assert result["desktop_execution_route"]["sandbox_required"] is True
    assert result["desktop_execution_policy"]["allow_live_foreground"] is True
    assert result["recommended_tools"][0] == "desktop.provider_session.start"
    recovery = result["recovery_actions"][0]
    assert recovery["tool"] == "desktop.provider_session.start"
    assert recovery["approval_required"] is True
    assert recovery["metadata"]["runtime_retry_source"] == "desktop_provider_session"
    assert recovery["metadata"]["runtime_replan_auto_start_eligible"] is False
    assert recovery["deferred_tool"] == "desktop.safe_type_text"
    assert recovery["deferred_continuation"][0]["desktop_execution_policy"][
        "prefer_isolated_desktop"
    ] is True
    assert broker.calls == []
    assert budget.claims == [("desktop.safe_type_text", False)]
    assert [event["event"] for event in timeline] == [
        "agent.tool.skipped",
        "desktop.provider_session.required",
    ]
    assert run_events[0][1] == "agent.tool.skipped"
    assert run_events[1][1] == "desktop.provider_session.required"
    session = run_events[1][2]["desktop_provider_session"]
    assert session["needed"] is True
    assert session["provider_id"] == "local-isolated-desktop"
    assert session["tool_names"] == ["desktop.safe_type_text"]
    assert [call[0] for call in events.calls] == ["requested", "result"]


def test_runtime_tool_call_executor_blocks_provider_required_app_activation_before_broker() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(
        tool_call_events=events,
        run_events=run_events,
        desktop_provider_registry=DesktopExecutionProviderRegistry(),
    )
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "action": "app.open"})

    result = executor.execute(
        {
            "tool": "app.open",
            "input": {"app_name": "PixelForge"},
            "desktop_execution_policy": {
                "mode": "preview_input",
                "prefer_isolated_desktop": True,
                "avoid_user_foreground_takeover": True,
                "require_sandbox_for_keyboard_mouse": True,
            },
            "desktop_execution_route": {
                "route_id": "desktop-route:app.open",
                "tool_name": "app.open",
                "requested_mode": "preview_input",
                "selected_provider_kind": "sandbox_desktop",
                "selected_provider_id": "",
                "status": "provider_required",
                "can_execute": False,
                "can_auto_start": False,
                "sandbox_required": True,
                "isolated_desktop_preferred": True,
                "foreground_takeover_allowed": False,
                "desktop_execution_session_policy": "isolated_preferred",
                "blocking_conditions": ["sandbox_desktop_provider_required"],
            },
            "sandbox_provider": {
                "available": False,
                "adapter_ready": False,
                "provider_kind": "sandbox_desktop",
                "status": "provider_required",
                "blocking_conditions": ["sandbox_desktop_provider_required"],
            },
        },
        ["app.open"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is False
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["blocking_condition"] == "sandbox_desktop_provider_required"
    assert result["desktop_execution_route"]["status"] == "provider_required"
    assert result["desktop_execution_route"]["can_execute"] is False
    assert result["desktop_execution_route"]["isolated_desktop_preferred"] is True
    assert result["recommended_tools"][0] == "desktop.provider_session.start"
    assert result["recovery_actions"][0]["tool"] == "desktop.provider_session.start"
    assert broker.calls == []
    assert [event["event"] for event in timeline] == [
        "agent.tool.skipped",
        "desktop.provider_session.required",
    ]
    assert run_events[0][1] == "agent.tool.skipped"
    assert run_events[1][1] == "desktop.provider_session.required"
    required_payload = run_events[1][2]
    assert required_payload["blocked_tool"] == "app.open"
    assert required_payload["desktop_provider_session"]["needed"] is True
    assert required_payload["desktop_provider_session"]["tool_names"] == ["app.open"]
    assert required_payload["desktop_execution_route"]["status"] == "provider_required"


def test_runtime_tool_call_executor_reuses_same_background_provider_after_health_probe(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class HealthyBackgroundVerifyAdapter:
        provider_kind = "background_desktop"
        provider_id = "cua-driver"
        supported_tools = ["desktop.verify"]

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def can_execute(
            self,
            tool_name: str,
            route: dict[str, Any],
            tool_request: dict[str, Any],
        ) -> bool:
            del tool_request
            return (
                tool_name == "desktop.verify"
                and route.get("selected_provider_kind") == "background_desktop"
                and route.get("selected_provider_id") == "cua-driver"
            )

        def execute(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            tool_request: dict[str, Any],
            route: dict[str, Any],
            broker: Any,
            approved: bool = False,
        ) -> dict[str, Any]:
            del broker, approved
            self.calls.append(
                {
                    "tool": tool_name,
                    "payload": dict(payload),
                    "route": dict(route),
                    "tool_request": dict(tool_request),
                }
            )
            return {
                "ok": True,
                "tool": tool_name,
                "summary": "Verified through background desktop provider",
                "desktop_execution_provider_routed": True,
                "desktop_execution_provider": {
                    "provider_kind": "background_desktop",
                    "provider_id": "cua-driver",
                },
            }

    import apps.shell.yachiyo_agent.desktop_execution_policy as desktop_execution_policy_module

    adapter = HealthyBackgroundVerifyAdapter()
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    broker = FakeBroker({"ok": True, "unexpected_local_verify": True})
    healthy_provider_status = {
        "available": True,
        "adapter_ready": True,
        "provider_kind": "background_desktop",
        "provider_id": "cua-driver",
        "status": "available",
        "blocking_conditions": [],
        "supported_tools": ["desktop.verify"],
        "health": {
            "ok": True,
            "checked": True,
            "status": "ready",
            "provider_kind": "background_desktop",
            "provider_id": "cua-driver",
            "supported_tools": ["desktop.verify"],
            "blocking_conditions": [],
        },
        "foreground_mutation_supported": False,
        "keyboard_mouse_capture_supported": False,
        "desktop_session_kind": "background",
        "desktop_session_isolated": True,
        "foreground_takeover_required": False,
        "desktop_backend_kind": "cua_background",
        "desktop_backend_is_loopback": False,
        "desktop_backend_ready_for_public_release": True,
        "requires_real_virtual_desktop_backend": False,
        "source": "test_probe",
    }
    monkeypatch.setattr(
        desktop_execution_policy_module,
        "cua_background_provider_status",
        lambda probe_health=False: {
            **healthy_provider_status,
            "health": {
                **healthy_provider_status["health"],
                "checked": bool(probe_health),
            },
        },
    )

    result = executor.execute(
        {
            "tool": "desktop.verify",
            "input": {
                "app_name": "PixelForge",
                "verification_goal": "app_running",
                "limit": 80,
            },
            "desktop_execution_policy": {
                "mode": "preview",
                "prefer_background_desktop": True,
            },
            "desktop_execution_route": {
                "route_id": "desktop-route:desktop.verify",
                "tool_name": "desktop.verify",
                "requested_mode": "preview",
                "selected_provider_kind": "background_desktop",
                "selected_provider_id": "cua-driver",
                "status": "provider_required",
                "can_execute": False,
                "blocking_conditions": ["sandbox_desktop_provider_required"],
            },
            "sandbox_provider": {
                "provider_kind": "background_desktop",
                "provider_id": "cua-driver",
                "status": "installed_not_checked",
                "health": {
                    "checked": False,
                    "status": "not_checked",
                },
            },
        },
        ["desktop.verify"],
        broker,
        [],
        run_id="run-background-health-probe",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert broker.calls == []
    assert len(adapter.calls) == 1
    routed = adapter.calls[0]
    assert routed["route"]["selected_provider_kind"] == "background_desktop"
    assert routed["route"]["selected_provider_id"] == "cua-driver"
    assert routed["route"]["can_execute"] is True
    assert routed["tool_request"]["sandbox_provider"]["status"] == "available"


def test_runtime_tool_call_executor_preserves_planner_trace_on_tool_call_events() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)
    timeline: list[dict[str, Any]] = []
    broker = FakeBroker({"ok": True, "data": {"app_name": "PixelForge"}})

    result = executor.execute(
        {
            "tool": "desktop.open_path",
            "tool_call_id": "call-planner-trace",
            "input": {"path": "legacy-report.xls"},
            "source": "runtime_planner",
            "planning_reason": "planner_replan_fallback_recovery",
            "step_id": "inspect-data-source",
            "capability_id": "file.workspace_read",
            "capability_title": "Read workspace file",
            "capability_status": "selected",
            "capability_reason": "The task needs to inspect a local source file.",
            "capability_selected_tools": ["workspace.read", "desktop.open_path"],
            "capability_planned_step_ids": ["inspect-data-source", "open-source-file"],
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "replan_request_id": "replan-1",
            "replan_trigger": "tool_failure",
            "target_app_name": "Figma",
            "target_app_query": "design",
            "target_search_text": "logo 模板",
        },
        ["desktop.open_path"],
        broker,
        timeline,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert timeline[0]["event"] == "agent.tool.started"
    assert timeline[0]["status"] == "running"
    assert timeline[0]["step_id"] == "inspect-data-source"
    assert timeline[0]["capability_id"] == "file.workspace_read"
    assert timeline[0]["capability_title"] == "Read workspace file"
    assert timeline[0]["capability_selected_tools"] == ["workspace.read", "desktop.open_path"]
    assert timeline[0]["capability_planned_step_ids"] == [
        "inspect-data-source",
        "open-source-file",
    ]
    assert timeline[0]["core_id"] == "core-1"
    assert timeline[0]["target_app_name"] == "Figma"
    assert timeline[0]["replan_request_id"] == "replan-1"
    assert timeline[-1]["event"] == "agent.tool.call"
    assert timeline[-1]["step_id"] == "inspect-data-source"
    assert timeline[-1]["capability_id"] == "file.workspace_read"
    assert timeline[-1]["capability_title"] == "Read workspace file"
    assert timeline[-1]["capability_reason"] == "The task needs to inspect a local source file."
    assert timeline[-1]["core_id"] == "core-1"
    assert timeline[-1]["target_app_name"] == "Figma"
    assert timeline[-1]["replan_request_id"] == "replan-1"
    agent_call = [call for call in events.calls if call[0] == "agent_tool_call"][0]
    assert agent_call[2]["trace"] == {
        "source": "runtime_planner",
        "tool_call_id": "call-planner-trace",
        "planning_reason": "planner_replan_fallback_recovery",
        "step_id": "inspect-data-source",
        "capability_id": "file.workspace_read",
        "capability_title": "Read workspace file",
        "capability_status": "selected",
        "capability_reason": "The task needs to inspect a local source file.",
        "capability_selected_tools": ["workspace.read", "desktop.open_path"],
        "capability_planned_step_ids": ["inspect-data-source", "open-source-file"],
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "replan_request_id": "replan-1",
        "replan_trigger": "tool_failure",
        "target_app_name": "Figma",
        "target_app_query": "design",
        "target_search_text": "logo 模板",
        "run_id": "run-1",
        "actor": "native_runtime",
        "visibility": "internal",
        "execution_authority": "runtime_tool_executor",
    }
    lifecycle_trace = {
        call[0]: call[2]["trace"]
        for call in events.calls
        if call[0] in {"requested", "started", "result"}
    }
    assert lifecycle_trace == {
        "requested": agent_call[2]["trace"],
        "started": agent_call[2]["trace"],
        "result": agent_call[2]["trace"],
    }


def test_runtime_tool_call_executor_records_non_workspace_failures() -> None:
    events = FakeToolCallEvents()
    executor = _executor(tool_call_events=events)

    with pytest.raises(AgentRuntimeError, match="boom"):
        executor.execute(
            {"tool": "terminal.run", "input": {"command": "echo hi"}},
            ["terminal.run"],
            FakeBroker(AgentRuntimeError("boom")),
            [],
            run_id="run-1",
            budget=FakeBudget(),
        )

    assert [call[0] for call in events.calls] == ["requested", "started", "failed"]


def test_runtime_tool_call_executor_counts_approved_python_run_as_terminal_execution() -> None:
    executor = _executor(tool_call_events=FakeToolCallEvents())
    budget = FakeBudget()

    result = executor.execute(
        {"tool": "python.run", "input": {"code": "print('ok')"}},
        ["python.run"],
        FakeBroker({"ok": True}),
        [],
        approved=True,
        run_id="run-1",
        budget=budget,
    )

    assert result["ok"] is True
    assert budget.claims == [("python.run", True)]


def test_runtime_tool_call_executor_projects_trace_and_artifact_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []

    artifact_result = executor.execute(
        {"tool": "artifact.write", "input": {"path": "notes.md", "content": "body"}},
        ["artifact.write"],
        FakeBroker({"ok": True, "path": "notes.md", "content": "body"}),
        [],
        artifacts=artifacts,
        run_id="run-1",
        budget=FakeBudget(),
    )
    memory_result = executor.execute(
        {"tool": "memory.add", "input": {"content": "remember"}},
        ["memory.add"],
        FakeBroker({"ok": True, "memory_id": "mem-1"}),
        [],
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert artifact_result["ok"] is True
    assert memory_result["ok"] is True
    assert artifacts == [{"kind": "tool_artifact", **artifact_result}]
    assert ("run-1", "artifact.created", {"run_id": "run-1", "path": "notes.md", "source_tool": "artifact.write"}) in run_events
    assert ("run-1", "memory.write.add", {"tool": "memory.add", "input_preview": {"content": "remember"}, "ok": True}) in run_events


def test_runtime_tool_call_executor_preserves_scope_on_memory_skill_trace_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)

    result = executor.execute(
        {
            "tool": "memory.add",
            "input": {"content": "remember"},
            "core_id": "core-1",
            "workspace_id": "workspace-1",
            "task_id": "task-1",
            "group_run_id": "group-run-1",
            "workflow_run_id": "workflow-run-1",
            "workflow_node_id": "remember",
        },
        ["memory.add"],
        FakeBroker({"ok": True, "memory_id": "mem-1"}),
        [],
        run_id="run-memory",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    memory_payload = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "memory.write.add"
    )
    for key, value in {
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "group_run_id": "group-run-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "remember",
    }.items():
        assert memory_payload[key] == value
        assert memory_payload["input_preview"][key] == value


def test_runtime_tool_call_executor_projects_structured_tool_artifact_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []
    screen_artifact = {
        "path": "screenshots/current-screen.png",
        "kind": "image",
        "mime_type": "image/png",
        "size_bytes": 321,
        "width": 800,
        "height": 600,
    }

    result = executor.execute(
        {"tool": "screen.capture", "input": {"display": "main"}},
        ["screen.capture"],
        FakeBroker({"ok": True, "summary": "Captured screen", "artifact": screen_artifact}),
        [],
        artifacts=artifacts,
        run_id="run-screen",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert artifacts == [{**screen_artifact, "source_tool": "screen.capture"}]
    assert (
        "run-screen",
        "artifact.created",
        {
            "run_id": "run-screen",
            "path": "screenshots/current-screen.png",
            "source_tool": "screen.capture",
            "artifact": {**screen_artifact, "source_tool": "screen.capture"},
        },
    ) in run_events


def test_runtime_tool_call_executor_preserves_scope_on_artifact_events() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []
    report_artifact = {
        "path": "reports/analysis.md",
        "kind": "markdown",
        "mime_type": "text/markdown",
    }
    request_context = {
        "source": "runtime_planner",
        "decision_id": "decision-1",
        "plan_id": "plan-1",
        "step_id": "write-analysis",
        "capability_id": "data.analysis",
        "capability_title": "Analyze data",
        "capability_status": "selected",
        "capability_reason": "The user asked for a data-backed report artifact.",
        "capability_selected_tools": ["data.analyze", "artifact.write"],
        "capability_planned_step_ids": ["analyze-data", "write-analysis"],
        "core_id": "core-1",
        "workspace_id": "workspace-1",
        "task_id": "task-1",
        "group_id": "group-1",
        "run_group_id": "run-group-1",
        "group_run_id": "group-run-1",
        "workflow_id": "workflow-1",
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "node-analyze",
        "workflow_node_label": "Analyze data",
    }

    result = executor.execute(
        {
            "tool": "data.analyze",
            "input": {"path": "sales.csv"},
            **request_context,
        },
        ["data.analyze"],
        FakeBroker({"ok": True, "summary": "Analyzed data", "artifact": report_artifact}),
        [],
        artifacts=artifacts,
        run_id="run-data",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert artifacts == [
        {
            **report_artifact,
            "source_tool": "data.analyze",
            **request_context,
        }
    ]
    artifact_event = next(
        payload for _run_id, event_type, payload in run_events if event_type == "artifact.created"
    )
    for key, value in request_context.items():
        assert artifact_event[key] == value
        assert artifact_event["artifact"][key] == value
    assert artifact_event["path"] == "reports/analysis.md"
    assert artifact_event["source_tool"] == "data.analyze"


def test_runtime_tool_call_executor_projects_multiple_structured_artifacts() -> None:
    events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=events, run_events=run_events)
    artifacts: list[dict[str, Any]] = []
    markdown_artifact = {
        "path": "analysis-report.md",
        "kind": "markdown",
        "mime_type": "text/markdown",
        "size_bytes": 120,
    }
    chart_artifact = {
        "path": "analysis-chart.png",
        "kind": "image",
        "mime_type": "image/png",
        "size_bytes": 321,
        "width": 640,
        "height": 360,
    }

    result = executor.execute(
        {"tool": "data.analyze", "input": {"path": "sales.csv"}},
        ["data.analyze"],
        FakeBroker(
            {
                "ok": True,
                "summary": "Analyzed data",
                "artifact": markdown_artifact,
                "artifacts": [markdown_artifact, chart_artifact],
            }
        ),
        [],
        artifacts=artifacts,
        run_id="run-data",
        budget=FakeBudget(),
    )

    assert result["ok"] is True
    assert artifacts == [
        {**markdown_artifact, "source_tool": "data.analyze"},
        {**chart_artifact, "source_tool": "data.analyze"},
    ]
    assert (
        "run-data",
        "artifact.created",
        {
            "run_id": "run-data",
            "path": "analysis-chart.png",
            "source_tool": "data.analyze",
            "artifact": {**chart_artifact, "source_tool": "data.analyze"},
        },
    ) in run_events


def test_runtime_tool_call_executor_routes_restricted_plugin_tools_through_timeline(
    tmp_path,
) -> None:
    clear_restricted_tool_plugins()

    def echo_tool(payload, context):
        return {
            "ok": True,
            "summary": f"Echoed {payload['text']}",
            "context_tool": context.tool_name,
        }

    try:
        register_restricted_tool_plugin(
            RestrictedToolPlugin(
                plugin_id="notes",
                tools=(
                    RestrictedPluginTool(
                        tool_id="echo",
                        description="Echo text through a restricted plugin.",
                        properties={"text": {"type": "string"}},
                        required=("text",),
                        risk_level="low",
                        execute=echo_tool,
                    ),
                ),
            )
        )
        tool_name = "plugin.notes.echo"
        events = FakeToolCallEvents()
        executor = RuntimeToolCallExecutor(
            normalize_tool_name=lambda value: str(value or "").strip(),
            input_preview=lambda value: value,
            run_budget=lambda _run_id, _timeline: FakeBudget(),
            validate_tool_payload=ToolDescriptorRegistry.validate_payload,
            limit_tool_result=lambda result: result,
            timeline_factory=_timeline,
            tool_call_events=events,
            trace_events=FakeTraceEvents(),
            append_run_event=lambda _run_id, _event_type, _payload: None,
        )
        broker = ToolBroker(
            {
                "default_workdir": str(tmp_path),
                "readable_scopes": ["."],
                "writable_scopes": [],
            },
            tmp_path / "artifacts",
        )
        timeline: list[dict[str, Any]] = []

        result = executor.execute(
            {"tool": tool_name, "input": {"text": "hello"}},
            [tool_name],
            broker,
            timeline,
            run_id="run-1",
            budget=FakeBudget(),
        )

        assert result["ok"] is True
        assert result["summary"] == "Echoed hello"
        assert result["plugin_id"] == "notes"
        assert result["risk_level"] == "low"
        assert timeline[-1]["event"] == "agent.tool.call"
        assert timeline[-1]["detail"] == tool_name
        assert timeline[-1]["result"] == result
        assert [call[0] for call in events.calls] == [
            "requested",
            "started",
            "result",
            "agent_tool_call",
        ]
    finally:
        clear_restricted_tool_plugins()


def test_runtime_tool_request_runner_pauses_for_high_risk_restricted_plugin(
    tmp_path,
) -> None:
    clear_restricted_tool_plugins()

    def destructive_tool(payload, context):
        return {"ok": True, "approved": context.approved, "target": payload["target"]}

    try:
        register_restricted_tool_plugin(
            RestrictedToolPlugin(
                plugin_id="ops",
                tools=(
                    RestrictedPluginTool(
                        tool_id="delete_file",
                        description="High-risk restricted plugin test tool.",
                        properties={"target": {"type": "string"}},
                        required=("target",),
                        risk_level="high",
                        execute=destructive_tool,
                    ),
                ),
            )
        )
        tool_name = "plugin.ops.delete_file"
        events = FakeToolCallEvents()
        executor = RuntimeToolCallExecutor(
            normalize_tool_name=lambda value: str(value or "").strip(),
            input_preview=lambda value: value,
            run_budget=lambda _run_id, _timeline: FakeBudget(),
            validate_tool_payload=ToolDescriptorRegistry.validate_payload,
            limit_tool_result=lambda result: result,
            timeline_factory=_timeline,
            tool_call_events=events,
            trace_events=FakeTraceEvents(),
            append_run_event=lambda _run_id, _event_type, _payload: None,
        )
        runner = _runner(
            call_agent_tool=executor.execute,
            pending_approval_builder=FakePendingApprovalBuilder(),
        )
        broker = ToolBroker(
            {
                "default_workdir": str(tmp_path),
                "readable_scopes": ["."],
                "writable_scopes": [],
            },
            tmp_path / "artifacts",
        )
        timeline: list[dict[str, Any]] = []
        messages = [{"role": "user", "content": "delete the file"}]

        with pytest.raises(AgentApprovalRequired) as exc_info:
            runner.run(
                [{"tool": tool_name, "input": {"target": "notes.md"}}],
                [tool_name],
                broker,
                messages,
                timeline,
                [],
                next_iteration=4,
                run_id="run-1",
                budget=FakeBudget(),
            )

        assert exc_info.value.pending_approval["tool"] == tool_name
        assert timeline[-1]["event"] == "agent.tool.call"
        assert timeline[-1]["result"]["approval_required"] is True
        assert timeline[-1]["result"]["risk_level"] == "high"
        assert [call[0] for call in events.calls] == [
            "requested",
            "started",
            "result",
            "agent_tool_call",
        ]
    finally:
        clear_restricted_tool_plugins()


def test_native_runtime_uses_split_tool_call_executor(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolCallExecutor is RuntimeToolCallExecutor
        assert isinstance(service.tool_call_executor, RuntimeToolCallExecutor)
    finally:
        service.close()


def test_runtime_tool_request_runner_blocks_tools_disallowed_by_user_goal() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "no commands please"}]
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []
    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: calls.append("call_agent_tool") or {"ok": True},
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "terminal.run",
                "tool_call_id": "call-user-goal-blocked",
                "input": {"command": "echo hi"},
            }
        ],
        ["terminal.run"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert calls == []
    assert budget.claims == [("terminal.run", False)]
    assert timeline == [
        {
            "event": "agent.tool.skipped",
            "detail": "terminal.run",
            "input_preview": {"command": "echo hi"},
            "result": {
                "ok": False,
                "blocked_by_user_goal": True,
                "tool": "terminal.run",
                "error": "no terminal",
                "hint": (
                    "Do not ask for approval. Continue with an inline answer "
                    "that follows the user's stated constraint."
                ),
                },
                "tool_call_id": "call-user-goal-blocked",
                "run_id": "run-1",
                "actor": "native_runtime",
                "visibility": "internal",
                "execution_authority": "runtime_tool_executor",
            }
    ]
    assert run_events[0][1] == "agent.tool.skipped"
    assert "blocked_by_user_goal" in messages[-1]["content"]


def test_runtime_tool_request_runner_balances_native_batch_after_user_recovery_stop() -> None:
    calls: list[str] = []
    messages = [
        assistant_message_for_history(
            {
                "content": None,
                "tool_calls": [
                    {"id": "call-permissions", "function": {"name": "workspace.read"}},
                    {"id": "call-search", "function": {"name": "workspace.list"}},
                ],
            }
        )
    ]
    stage_tool_result_messages(messages)

    def call_agent_tool(tool_request, *_args, **_kwargs):
        calls.append(str(tool_request.get("tool") or ""))
        return {
            "ok": True,
            "recovery_actions": [
                {"tool": "system.settings_open", "input": {"target": "automation"}}
            ],
        }

    _runner(call_agent_tool=call_agent_tool).run(
        [
            {
                "protocol": "tool_calls",
                "tool_call_id": "call-permissions",
                "tool": "workspace.read",
                "input": {"path": "permissions.json"},
            },
            {
                "protocol": "tool_calls",
                "tool_call_id": "call-search",
                "tool": "workspace.list",
                "input": {"path": "."},
            },
        ],
        ["workspace.read", "workspace.list"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        budget=FakeBudget(),
    )

    assert calls == ["workspace.read"]
    assert [message["role"] for message in messages] == ["assistant", "tool", "tool"]
    assert json.loads(messages[1]["content"])["ok"] is True
    assert json.loads(messages[2]["content"])["error"] == (
        "tool_batch_interrupted_before_execution"
    )


def test_runtime_tool_request_runner_previews_live_foreground_tools_by_policy() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在当前应用里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []
    runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: calls.append("call_agent_tool") or {"ok": True},
        run_events=run_events,
    )

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {"mode": "preview"},
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    result = skipped["result"]
    assert calls == []
    assert budget.claims == [("desktop.safe_type_text", False)]
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["status"] == "provider_required"
    assert result["execution_mode"] == "supervised_live"
    assert result["keyboard_mouse_capture"] is True
    assert result["desktop_execution_policy"] == {"mode": "preview"}
    assert result["sandbox_provider"]["status"] == "provider_required"
    assert result["sandbox_provider"]["blocking_conditions"] == [
        "sandbox_desktop_provider_required"
    ]
    assert result["desktop_execution_route"]["status"] == "provider_required"
    assert result["desktop_execution_route"]["can_execute"] is False
    assert result["desktop_execution_route"]["fallback_mode"] == "supervised_live"
    assert result["blocking_conditions"] == ["sandbox_desktop_provider_required"]
    assert [action["tool"] for action in result["recovery_actions"]] == [
        "desktop.provider_session.start",
        "desktop.active_window",
        "desktop.ui_elements",
        "screen.capture",
        "desktop.safe_type_text",
    ]
    assert [action["recovery_action_kind"] for action in result["recovery_actions"]] == [
        "desktop_provider_session_start",
        "observe_desktop_state",
        "observe_desktop_controls",
        "sandbox_desktop_handoff",
        "supervised_live_retry",
    ]
    session_action = result["recovery_actions"][0]
    assert session_action["approval_required"] is True
    assert session_action["metadata"]["runtime_retry_source"] == (
        "desktop_provider_session"
    )
    assert session_action["deferred_tool"] == "desktop.safe_type_text"
    sandbox_action = result["recovery_actions"][3]
    assert sandbox_action["desktop_execution_policy"]["mode"] == "sandbox_preferred"
    assert sandbox_action["desktop_execution_route"]["status"] == "provider_required"
    assert sandbox_action["sandbox_provider"]["status"] == "provider_required"
    assert sandbox_action["metadata"]["sandbox_desktop_handoff"] is True
    assert sandbox_action["metadata"]["desktop_execution_route"]["status"] == (
        "provider_required"
    )
    assert sandbox_action["metadata"]["sandbox_provider"]["status"] == "provider_required"
    assert sandbox_action["metadata"]["runtime_replan_auto_start_eligible"] is False
    assert sandbox_action["metadata"]["runtime_replan_auto_start_blockers"] == [
        "sandbox_desktop_provider_required"
    ]
    assert sandbox_action["deferred_continuation"][0]["tool"] == "desktop.safe_type_text"
    assert sandbox_action["deferred_continuation"][0]["input"] == {"text": "hello"}
    assert (
        sandbox_action["deferred_continuation"][0]["desktop_execution_policy"]["mode"]
        == "sandbox_preferred"
    )
    supervised_action = result["recovery_actions"][4]
    assert supervised_action["desktop_execution_policy"]["mode"] == "supervised_live"
    assert supervised_action["metadata"]["runtime_replan_auto_start_eligible"] is False
    assert supervised_action["metadata"]["runtime_replan_auto_start_blockers"] == [
        "desktop_execution_policy",
        "keyboard_mouse_capture",
        "foreground_control",
    ]
    assert run_events[0][1] == "agent.tool.skipped"
    assert run_events[0][2]["result"]["blocked_by_desktop_execution_policy"] is True
    assert "blocked_by_desktop_execution_policy" in messages[-1]["content"]


def test_runtime_tool_request_runner_allows_sandbox_ready_provider_route() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在隔离桌面里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda tool_request, *_args, **_kwargs: captured_requests.append(
            tool_request
        )
        or {"ok": True, "tool": tool_request.get("tool")},
    )

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {"mode": "sandbox_preferred"},
                "sandbox_provider": {
                    "available": True,
                    "adapter_ready": True,
                    "provider_kind": "sandbox_desktop",
                    "provider_id": "sandbox-1",
                    "status": "available",
                    "supported_tools": ["desktop.safe_type_text"],
                },
                "desktop_provider_session": {
                    "running": True,
                    "started": True,
                    "status": "running",
                    "provider_id": "sandbox-1",
                    "url": "http://127.0.0.1:19093",
                    "tool_names": ["desktop.safe_type_text"],
                    "command": ["python", "scripts/run_isolated_desktop_provider.py"],
                    "env": {"OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret"},
                    "provider_manifest_evidence": {
                        "provider_id": "sandbox-1",
                        "ok": True,
                    },
                    "provider_conformance": {
                        "ok": True,
                        "public_release_ready": True,
                    },
                },
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert budget.claims == []
    assert len(captured_requests) == 1
    routed_request = captured_requests[0]
    assert routed_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert routed_request["desktop_execution_route"]["selected_provider_kind"] == (
        "sandbox_desktop"
    )
    assert routed_request["sandbox_provider"]["provider_id"] == "sandbox-1"
    assert not [event for event in timeline if event["event"] == "agent.tool.skipped"]


def test_runtime_tool_request_runner_executes_sandbox_route_through_provider() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在隔离桌面里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    adapter = FakeSandboxDesktopAdapter()
    broker = FakeBroker({"ok": True, "unexpected": True})
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([adapter]),
    )
    runner = _runner(call_agent_tool=executor.execute)

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {"mode": "sandbox_preferred"},
                "sandbox_provider": {
                    "available": True,
                    "adapter_ready": True,
                    "provider_kind": "sandbox_desktop",
                    "provider_id": "sandbox-1",
                    "status": "available",
                    "supported_tools": ["desktop.safe_type_text"],
                },
                "desktop_provider_session": {
                    "running": True,
                    "started": True,
                    "status": "running",
                    "provider_id": "sandbox-1",
                    "url": "http://127.0.0.1:19093",
                    "tool_names": ["desktop.safe_type_text"],
                    "command": ["python", "scripts/run_isolated_desktop_provider.py"],
                    "env": {"OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret"},
                    "provider_manifest_evidence": {
                        "provider_id": "sandbox-1",
                        "ok": True,
                    },
                    "provider_conformance": {
                        "ok": True,
                        "public_release_ready": True,
                    },
                },
            }
        ],
        ["desktop.safe_type_text"],
        broker,
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert len(adapter.calls) == 1
    assert adapter.calls[0]["tool"] == "desktop.safe_type_text"
    assert adapter.calls[0]["payload"] == {"text": "hello"}
    assert adapter.calls[0]["approved"] is False
    route = adapter.calls[0]["route"]
    assert route["route_id"] == "desktop-route:desktop.safe_type_text"
    assert route["tool_name"] == "desktop.safe_type_text"
    assert route["requested_mode"] == "sandbox_preferred"
    assert route["selected_provider_kind"] == "sandbox_desktop"
    assert route["selected_provider_id"] == "sandbox-1"
    assert route["status"] == "sandbox_ready"
    assert route["can_execute"] is True
    assert route["can_auto_start"] is True
    assert route["provider_execution_required"] is True
    assert route["sandbox_required"] is True
    assert route["fallback_mode"] == ""
    assert route["blocking_conditions"] == []
    assert route["source"] == "runtime"
    assert broker.calls == []
    assert budget.claims == [("desktop.safe_type_text", False)]
    assert not [event for event in timeline if event["event"] == "agent.tool.skipped"]
    tool_call = next(event for event in timeline if event["event"] == "agent.tool.call")
    assert tool_call["result"]["desktop_execution_provider_routed"] is True
    assert tool_call["result"]["desktop_execution_provider"]["provider_id"] == "sandbox-1"
    assert tool_call["desktop_provider_session"]["provider_id"] == "sandbox-1"
    assert tool_call["desktop_provider_session"]["running"] is True
    assert tool_call["sandbox_provider"]["provider_manifest_evidence"]["ok"] is True
    assert "command" not in tool_call["desktop_provider_session"]
    assert "env" not in tool_call["desktop_provider_session"]
    assert tool_call["result"]["desktop_provider_session"]["provider_id"] == "sandbox-1"
    assert (
        tool_call["result"]["desktop_provider_session"]["provider_conformance"][
            "public_release_ready"
        ]
        is True
    )
    assert "command" not in tool_call["result"]["desktop_provider_session"]
    assert "env" not in tool_call["result"]["desktop_provider_session"]


def test_runtime_tool_request_runner_executes_explicitly_authorized_local_route() -> None:
    events = FakeToolCallEvents()
    registry = DesktopExecutionProviderRegistry([LocalDesktopExecutionProviderAdapter()])
    executor = _executor(
        tool_call_events=events,
        desktop_provider_registry=registry,
    )
    runner = _runner(call_agent_tool=executor.execute)
    broker = FakeBroker(
        {
            "ok": True,
            "action": "media.music_app_open_and_play",
            "summary": "Playing Music",
            "data": {"app_name": "Music"},
        }
    )
    messages = [{"role": "user", "content": "播放 Apple Music"}]
    timeline: list[dict[str, Any]] = []

    runner.run(
        [
            {
                "tool": "media.music_app_open_and_play",
                "input": {"app_name": "Music"},
                "allow_user_foreground_takeover": True,
                "desktop_execution_policy": {
                    "mode": "allow",
                    "allow_live_foreground": True,
                    "prefer_background_desktop": False,
                    "prefer_isolated_desktop": False,
                    "avoid_user_foreground_takeover": False,
                    "require_sandbox_for_keyboard_mouse": False,
                    "source": "daily_chat",
                },
                "desktop_execution_route": {
                    "route_id": "desktop-route:media.music_app_open_and_play",
                    "tool_name": "media.music_app_open_and_play",
                    "requested_mode": "preview_input",
                    "selected_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                    "selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
                    "status": "provider_ready",
                    "can_execute": True,
                    "can_auto_start": True,
                    "provider_execution_required": True,
                    "sandbox_required": False,
                    "foreground_takeover_allowed": True,
                    "foreground_takeover_required": True,
                    "requires_user_foreground_session": True,
                    "blocking_conditions": [],
                },
                "sandbox_provider": {
                    "available": True,
                    "adapter_ready": True,
                    "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                    "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
                    "status": "available",
                    "supported_tools": ["media.music_app_open_and_play"],
                    "desktop_backend_is_loopback": False,
                    "requires_real_virtual_desktop_backend": False,
                },
            }
        ],
        ["media.music_app_open_and_play"],
        broker,
        messages,
        timeline,
        [],
        next_iteration=2,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert broker.calls == [
        ("media.music_app_open_and_play", {"app_name": "Music"}, False)
    ]
    assert not [event for event in timeline if event["event"] == "agent.tool.skipped"]
    tool_call = _last_event(timeline, "agent.tool.call")
    assert tool_call["result"]["ok"] is True
    assert tool_call["result"]["desktop_execution_provider_routed"] is True
    assert tool_call["result"]["desktop_execution_provider"]["provider_kind"] == (
        LOCAL_DESKTOP_PROVIDER_KIND
    )
    assert tool_call["result"]["local_desktop_provider"]["provider_id"] == (
        LOCAL_DESKTOP_PROVIDER_ID
    )
    assert "simulated_desktop_provider" not in tool_call["result"]


@pytest.mark.parametrize(
    (
        "action_tool",
        "action_input",
        "verifier_tool",
        "verifier_input",
        "result",
        "expected",
    ),
    [
        (
            "app.open",
            {"app_name": "Notes"},
            "desktop.active_window",
            {},
            {"ok": True, "data": {"app_name": "Notes", "launch_verified": True}},
            True,
        ),
        (
            "app.focus",
            {"app_name": "Notes"},
            "desktop.active_window",
            {},
            {"ok": True, "data": {"app_name": "Notes", "focus_verified": True}},
            False,
        ),
        (
            "desktop.focus_app",
            {"app_name": "Notes"},
            "desktop.active_window",
            {},
            {"ok": True, "data": {"app_name": "Notes", "focus_verified": True}},
            False,
        ),
        (
            "desktop.open_path",
            {"path": "~/Downloads"},
            "desktop.verify",
            {},
            {
                "ok": True,
                "action": "desktop.open_path",
                "data": {
                    "path": "~/Downloads",
                    "exists": True,
                    "open_target": "system_open",
                },
            },
            False,
        ),
        (
            "app.focus_window",
            {"app_name": "Slack", "title_contains": "general"},
            "desktop.active_window",
            {},
                {
                    "ok": True,
                    "action": "app.focus_window",
                    "data": {
                        "app_name": "Slack",
                    "title_contains": "general",
                    "matched_window_title": "general - Slack",
                },
            },
            True,
        ),
        (
            "browser.type_text",
            {"selector": "point=120,240", "text": "hello"},
            "browser.current_page",
            {},
            {
                "ok": True,
                "data": {
                    "selector": "point=120,240",
                    "tag": "INPUT",
                    "length": 5,
                },
            },
            False,
        ),
        (
            "browser.click",
            {"selector": "#first-result"},
            "browser.current_page",
            {},
            {
                "ok": True,
                "data": {
                    "selector": "#first-result",
                    "tag": "A",
                },
            },
            False,
        ),
        (
            "media.apple_music_open_and_play",
            {},
            "media.apple_music_status",
            {},
            {
                "ok": True,
                "data": {
                    "control": "play",
                    "playback_ok": True,
                    "playback_state_unverified": True,
                    "player_state": "unknown",
                },
            },
            False,
        ),
        (
            "media.apple_music_open_and_play",
            {},
            "media.apple_music_status",
            {},
            {
                "ok": True,
                "data": {
                    "control": "play",
                    "playback_ok": True,
                    "player_state": "playing",
                },
            },
            True,
        ),
        (
            "desktop.safe_type_text",
            {"text": "hello"},
            "desktop.ui_elements",
            {},
            {"ok": True, "data": {"character_count": 5}},
            False,
        ),
    ],
)
def test_native_postcondition_receipt_only_satisfies_supported_verifier(
    action_tool: str,
    action_input: dict[str, Any],
    verifier_tool: str,
    verifier_input: dict[str, Any],
    result: dict[str, Any],
    expected: bool,
) -> None:
    verifier_request = {
        "tool": verifier_tool,
        "input": verifier_input,
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "depends_on": ["operate"],
    }
    action_event = {
        "event": "agent.tool.call",
        "detail": action_tool,
        "step_id": "operate",
        "input_preview": action_input,
        "result": result,
    }
    intrinsic_state = {
        "app.open": "open",
        "app.focus_window": "fulfilled",
    }.get(action_tool)
    if intrinsic_state:
        verifier_request.update(
            {
                "run_id": "run-intrinsic",
                "plan_id": "plan-intrinsic",
                "step_id": "verify-operate",
                "request_id": "request-verify-operate",
                "tool_call_id": "call-verify-operate",
                "source_step_id": "operate",
                "source_request_id": "request-operate",
                "source_tool_call_id": "call-operate",
            }
        )
        action_event = _runtime_intrinsic_action_event(
            action_tool,
            action_input,
            result,
            run_id="run-intrinsic",
            plan_id="plan-intrinsic",
            step_id="operate",
            request_id="request-operate",
            tool_call_id="call-operate",
        )
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        verifier_request,
        [action_event],
        tool_timeline_start=0,
    )

    assert bool(receipt) is expected
    if expected:
        expected_receipt = {
            "source_tool": action_tool,
            "source_step_id": "operate",
        }
        if intrinsic_state:
            expected_receipt.update(
                {
                    "source_tool_call_id": "call-operate",
                    "source_request_id": "request-operate",
                    "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
                    "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
                    "verified_observed_state": intrinsic_state,
                }
            )
        assert receipt == expected_receipt


@pytest.mark.parametrize(
    ("action_tool", "action_input", "result"),
    [
        pytest.param(
            "app.show",
            {"app_name": "Slack"},
            {
                "ok": True,
                "action": "app.show",
                "postcondition_verified": True,
                "data": {"app_name": "Discord", "show_status": "shown"},
            },
            id="wrong-app",
        ),
        pytest.param(
            "desktop.safe_key",
            {"action": "arrow_down", "repeat_count": 3},
            {
                "ok": True,
                "action": "desktop.safe_key",
                "postcondition_verified": True,
                "data": {"key_action": "escape", "repeat_count": 3},
            },
            id="wrong-key",
        ),
        pytest.param(
            "desktop.safe_key",
            {"action": "arrow_down", "repeat_count": 3},
            {
                "ok": True,
                "action": "desktop.safe_key",
                "postcondition_verified": True,
                "data": {"key_action": "arrow_down", "repeat_count": 1},
            },
            id="wrong-repeat-count",
        ),
        pytest.param(
            "desktop.safe_shortcut",
            {"action": "new_tab"},
            {
                "ok": True,
                "action": "desktop.safe_shortcut",
                "postcondition_verified": True,
                "data": {"shortcut_action": "close_tab"},
            },
            id="wrong-shortcut",
        ),
    ],
)
def test_native_receipt_rejects_wrong_app_key_or_shortcut_identity(
    action_tool: str,
    action_input: dict[str, Any],
    result: dict[str, Any],
) -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.ui_elements",
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": "run-semantic-action",
            "plan_id": "plan-semantic-action",
            "source_step_id": "operate",
            "source_tool_call_id": "call-semantic-action",
            "depends_on": ["operate"],
        },
        [
            {
                "event": "agent.tool.call",
                "detail": action_tool,
                "run_id": "run-semantic-action",
                "plan_id": "plan-semantic-action",
                "step_id": "operate",
                "tool_call_id": "call-semantic-action",
                "input_preview": action_input,
                "result": result,
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


def _semantic_shortcut_provider_claim_fixture(
    action_tool: str,
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    app_scoped = action_tool.startswith("app.")
    action_input: dict[str, Any] = {"action": "new_tab"}
    if app_scoped:
        action_input["app_name"] = "Safari"
    dependency = {
        "tool": action_tool,
        "input": action_input,
        "decision_id": "decision-shortcut-claim",
        "plan_id": "plan-shortcut-claim",
        "tool_plan_id": "tool-plan-shortcut-claim",
        "step_id": "operate-shortcut",
        "request_id": "request-shortcut-claim",
        "tool_call_id": "call-shortcut-claim",
        "requires_post_action_verification": True,
    }
    approval = {
        "tool": "desktop.close_window",
        "decision_id": dependency["decision_id"],
        "plan_id": dependency["plan_id"],
        "tool_plan_id": dependency["tool_plan_id"],
        "step_id": "close-window",
        "request_id": "request-close-window",
        "tool_call_id": "call-close-window",
        "depends_on": [dependency["step_id"]],
    }
    data = {
        "shortcut_action": "new_tab",
        "postcondition_verified": True,
        "verified_observed_state": "new_tab_visible",
    }
    if app_scoped:
        data["app_name"] = "Safari"
    source = {
        "event": "agent.tool.call",
        "tool": action_tool,
        "detail": action_tool,
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "visibility": "internal",
        "run_id": "run-shortcut-claim",
        "decision_id": dependency["decision_id"],
        "plan_id": dependency["plan_id"],
        "tool_plan_id": dependency["tool_plan_id"],
        "step_id": dependency["step_id"],
        "request_id": dependency["request_id"],
        "tool_call_id": dependency["tool_call_id"],
        "input_preview": dict(action_input),
        "action_target": {
            "kind": "desktop_app" if app_scoped else "desktop_ui",
            "action": "keyboard_shortcut",
            "shortcut_action": "new_tab",
            **({"app_name": "Safari"} if app_scoped else {}),
        },
        "result": {
            "ok": True,
            "action": action_tool,
            "postcondition_verified": True,
            "verified_observed_state": "new_tab_visible",
            "data": data,
            "_runtime_execution_provenance": {
                "source": "local_tool_broker",
                "version": 1,
            },
        },
    }
    return dependency, approval, source


@pytest.mark.parametrize(
    "action_tool",
    (
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
    ),
)
def test_semantic_shortcut_provider_claim_cannot_mint_native_verifier_receipt(
    action_tool: str,
) -> None:
    dependency, _approval, source = _semantic_shortcut_provider_claim_fixture(
        action_tool
    )

    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.ui_elements",
            "input": {"app_name": "Safari"} if action_tool.startswith("app.") else {},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": source["run_id"],
            "decision_id": dependency["decision_id"],
            "plan_id": dependency["plan_id"],
            "tool_plan_id": dependency["tool_plan_id"],
            "step_id": "verify-shortcut",
            "request_id": "request-verify-shortcut",
            "tool_call_id": "call-verify-shortcut",
            "source_step_id": dependency["step_id"],
            "source_request_id": dependency["request_id"],
            "source_tool_call_id": dependency["tool_call_id"],
            "depends_on": [dependency["step_id"]],
        },
        [source],
        tool_timeline_start=0,
    )

    assert receipt == {}


@pytest.mark.parametrize(
    "action_tool",
    (
        "desktop.safe_shortcut",
        "app.open_and_safe_shortcut",
        "app.focus_and_safe_shortcut",
    ),
)
def test_semantic_shortcut_provider_claim_cannot_unlock_approval_dependency(
    action_tool: str,
) -> None:
    dependency, approval, source = _semantic_shortcut_provider_claim_fixture(
        action_tool
    )

    status = tool_execution_module._approval_verified_dependency_status(
        dependency["step_id"],
        dependency,
        [source],
        decision_id=dependency["decision_id"],
        approval_request=approval,
        run_id=source["run_id"],
    )

    assert status == "unverified"


@pytest.mark.parametrize(
    ("action_tool", "verifier_tool", "verifier_input", "result"),
    [
        (
            "desktop.show_all_apps",
            "desktop.verify",
            {},
            {
                "ok": True,
                "action": "desktop.show_all_apps",
                "data": {"shown_app_count": 2},
            },
        ),
    ],
)
def test_native_postcondition_receipt_accepts_intrinsic_non_mutation_receipts(
    action_tool: str,
    verifier_tool: str,
    verifier_input: dict[str, Any],
    result: dict[str, Any],
) -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": verifier_tool,
            "input": verifier_input,
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": "run-1",
            "plan_id": "plan-1",
            "source_step_id": "operate",
            "depends_on": ["operate"],
        },
        [
            {
                "event": "agent.tool.call",
                "detail": action_tool,
                "run_id": "run-1",
                "plan_id": "plan-1",
                "step_id": "operate",
                "result": result,
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {"source_tool": action_tool, "source_step_id": "operate"}


def test_native_postcondition_receipt_does_not_short_circuit_system_volume_status(
) -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "system.volume",
            "input": {"action": "status"},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": "run-volume",
            "plan_id": "plan-volume",
            "source_step_id": "operate",
            "source_tool_call_id": "call-volume",
            "depends_on": ["operate"],
        },
        [
            {
                "event": "agent.tool.call",
                "detail": "system.volume",
                "run_id": "run-volume",
                "plan_id": "plan-volume",
                "step_id": "operate",
                "tool_call_id": "call-volume",
                "result": {
                    "ok": True,
                    "data": {
                        "requested_action": "set",
                        "level": 35,
                        "muted": False,
                    },
                },
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


def test_native_postcondition_receipt_repeated_prompt_uses_current_run_and_plan() -> None:
    timeline = [
        {
            "event": "agent.tool.call",
            "detail": "desktop.show_all_apps",
            "run_id": "run-1",
            "plan_id": "plan-1",
            "step_id": "manage-foreground",
            "result": {
                "ok": True,
                "action": "desktop.show_all_apps",
                "data": {"shown_app_count": 1},
            },
        },
        {
            "event": "agent.tool.call",
            "detail": "desktop.show_all_apps",
            "run_id": "run-2",
            "plan_id": "plan-2",
            "step_id": "manage-foreground",
            "result": {
                "ok": True,
                "action": "desktop.show_all_apps",
                "data": {"shown_app_count": 2},
            },
        },
    ]

    current_receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.verify",
            "runtime_stage": "verify",
            "run_id": "run-2",
            "plan_id": "plan-2",
            "source_step_id": "manage-foreground",
            "depends_on": ["manage-foreground"],
        },
        timeline,
        tool_timeline_start=0,
    )
    wrong_run_receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.verify",
            "runtime_stage": "verify",
            "run_id": "run-3",
            "plan_id": "plan-2",
            "source_step_id": "manage-foreground",
            "depends_on": ["manage-foreground"],
        },
        timeline,
        tool_timeline_start=0,
    )

    assert current_receipt == {
        "source_tool": "desktop.show_all_apps",
        "source_step_id": "manage-foreground",
    }
    assert wrong_run_receipt == {}


def test_native_postcondition_receipt_can_cross_runner_batches_within_same_plan() -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.active_window",
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": "run-1",
            "depends_on": ["focus-window"],
            "plan_id": "plan-1",
            "step_id": "verify-focus-window",
            "request_id": "request-verify-focus-window",
            "tool_call_id": "call-verify-focus-window",
            "source_step_id": "focus-window",
            "source_request_id": "request-focus-window",
            "source_tool_call_id": "call-focus-window",
        },
        [
            _runtime_intrinsic_action_event(
                "app.focus_window",
                {"app_name": "Slack", "title_contains": "general"},
                {
                    "ok": True,
                    "data": {"matched_window_title": "general - Slack"},
                },
                run_id="run-1",
                plan_id="plan-1",
                step_id="focus-window",
                request_id="request-focus-window",
                tool_call_id="call-focus-window",
            ),
            {"event": "agent.plan.selection", "plan_id": "plan-1"},
        ],
        tool_timeline_start=2,
    )

    assert receipt == {
        "source_tool": "app.focus_window",
        "source_step_id": "focus-window",
        "source_tool_call_id": "call-focus-window",
        "source_request_id": "request-focus-window",
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "verified_observed_state": "fulfilled",
    }


def test_cross_batch_intrinsic_receipt_binds_executor_call_id_from_request_identity() -> None:
    verifier_request = {
        "tool": "desktop.verify",
        "input": {"app_name": "Apple Music"},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-open-app",
        "plan_id": "plan-open-app",
        "step_id": "verify-open-app",
        "source_step_id": "open-app",
        "source_request_id": "request-open-app",
        "depends_on": ["open-app"],
    }
    timeline = [
        _runtime_intrinsic_action_event(
            "app.open",
            {"app_name": "Apple Music"},
            {
                "ok": True,
                "action": "app.open",
                "postcondition_verified": True,
                "data": {
                    "app_name": "Apple Music",
                    "launch_status": "running",
                    "launch_verified": True,
                },
            },
            run_id="run-open-app",
            plan_id="plan-open-app",
            step_id="open-app",
            request_id="request-open-app",
            tool_call_id="call-open-app",
        )
    ]

    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        verifier_request,
        timeline,
        tool_timeline_start=1,
    )
    forged = tool_execution_module._native_postcondition_receipt_for_verifier(
        {**verifier_request, "source_request_id": "request-other"},
        timeline,
        tool_timeline_start=1,
    )

    assert receipt == {
        "source_tool": "app.open",
        "source_step_id": "open-app",
        "source_tool_call_id": "call-open-app",
        "source_request_id": "request-open-app",
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "verified_observed_state": "open",
    }
    assert forged == {}


def test_native_postcondition_receipt_rejects_another_plan_in_current_batch() -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.active_window",
            "runtime_stage": "verify",
            "plan_id": "plan-a",
            "source_step_id": "open-app",
            "depends_on": ["open-app"],
        },
        [
            {
                "event": "agent.tool.call",
                "detail": "app.open",
                "plan_id": "plan-a",
                "step_id": "open-app",
                "result": {"ok": False, "error": "launch failed"},
            },
            {
                "event": "agent.tool.call",
                "detail": "app.open",
                "plan_id": "plan-b",
                "step_id": "open-app",
                "result": {"ok": True, "launch_verified": True},
            },
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


def _local_focus_action_event() -> dict[str, Any]:
    return {
        "event": "agent.tool.call",
        "detail": "app.focus",
        "run_id": "run-local-focus",
        "decision_id": "decision-local-focus",
        "plan_id": "plan-local-focus",
        "step_id": "focus-app",
        "tool_call_id": "call-focus-app",
        "input_preview": {"app_name": "Slack"},
        "result": {
            "ok": True,
            "action": "app.focus",
            "data": {"app_name": "Slack", "focus_verified": True},
            "desktop_execution_provider_routed": True,
            "desktop_execution_provider": {
                "provider_kind": "local_desktop",
                "provider_id": "local-native-desktop",
                "adapter_registered": True,
            },
        },
    }


def _local_focus_verifier_request() -> dict[str, Any]:
    return {
        "tool": "desktop.verify",
        "input": {"app_name": "Slack"},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-local-focus",
        "decision_id": "decision-local-focus",
        "plan_id": "plan-local-focus",
        "step_id": "verify-focus",
        "source_step_id": "focus-app",
        "source_tool_call_id": "call-focus-app",
        "depends_on": ["focus-app"],
        "sandbox_provider": {
            "provider_kind": "local_desktop",
            "provider_id": "local-native-desktop",
        },
    }


def _local_focus_verifier_result() -> dict[str, Any]:
    return {
        "ok": True,
        "action": "desktop.verify",
        "data": {
            "app_name": "Slack",
            "running": True,
            "focus_verified": True,
        },
        "_runtime_execution_provenance": {
            "source": "local_tool_broker",
            "version": 1,
        },
    }


def _local_app_open_action_event() -> dict[str, Any]:
    return {
        "event": "agent.tool.call",
        "detail": "app.open",
        "run_id": "run-local-open",
        "decision_id": "decision-local-open",
        "plan_id": "plan-local-open",
        "step_id": "open-or-focus-app",
        "request_id": "request-local-open",
        "tool_call_id": "call-local-open",
        "input_preview": {
            "app_name": "Music",
            "requested_app_name": "Apple Music",
            "resolved_app_name": "Music",
        },
        "result": {
            "ok": True,
            "action": "app.open",
            "data": {
                "app_name": "Music",
                "requested_app_name": "Apple Music",
                "resolved_app_name": "Music",
                "launch_verified": True,
            },
            "desktop_execution_provider_routed": True,
            "desktop_execution_provider": {
                "provider_kind": "local_desktop",
                "provider_id": "local-native-desktop",
                "adapter_registered": True,
            },
        },
    }


def _local_app_running_verifier_request() -> dict[str, Any]:
    return {
        "tool": "desktop.verify",
        "input": {
            "app_name": "Music",
            "verification_goal": "app_running",
        },
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-local-open",
        "decision_id": "decision-local-open",
        "plan_id": "plan-local-open",
        "step_id": "verify-desktop-result",
        "source_step_id": "open-or-focus-app",
        "source_request_id": "request-local-open",
        "source_tool_call_id": "call-local-open",
        "depends_on": ["open-or-focus-app"],
        "verification_predicate_kind": "app_window_present",
        "sandbox_provider": {
            "provider_kind": "local_desktop",
            "provider_id": "local-native-desktop",
        },
    }


def _local_app_running_verifier_result() -> dict[str, Any]:
    return {
        "ok": True,
        "action": "desktop.verify",
        "running": True,
        "launch_verified": True,
        "data": {
            "app_name": "Music",
            "running": True,
            "launch_verified": True,
        },
        "_runtime_execution_provenance": {
            "source": "local_tool_broker",
            "version": 1,
        },
    }


def test_trusted_app_running_observation_receipt_binds_alias_provider_plan_and_source_call(
) -> None:
    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        _local_app_running_verifier_request(),
        _local_app_running_verifier_result(),
        [_local_app_open_action_event()],
        tool_timeline_start=0,
        run_id="run-local-open",
    )

    assert receipt == {
        "source_tool": "app.open",
        "source_step_id": "open-or-focus-app",
        "source_tool_call_id": "call-local-open",
        "source_request_id": "request-local-open",
        "run_id": "run-local-open",
        "decision_id": "decision-local-open",
        "plan_id": "plan-local-open",
        "provider_kind": "local_desktop",
        "provider_id": "local-native-desktop",
        "verification_predicate_kind": "app_window_present",
        "verified_observed_state": "open",
        "observed_app_name": "Music",
    }


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        pytest.param("wrong_app", "Finder", id="wrong-app"),
        pytest.param("not_running", False, id="not-running"),
        pytest.param("wrong_provider", "other-provider", id="wrong-provider"),
        pytest.param("wrong_call", "call-other-open", id="wrong-source-call"),
        pytest.param("wrong_goal", "", id="missing-app-running-goal"),
    ],
)
def test_trusted_app_running_observation_receipt_rejects_unbound_or_weak_evidence(
    mutation: str,
    value: Any,
) -> None:
    request = _local_app_running_verifier_request()
    result = _local_app_running_verifier_result()
    if mutation == "wrong_app":
        result["data"]["app_name"] = value
    elif mutation == "not_running":
        result["running"] = value
        result["launch_verified"] = value
        result["data"]["running"] = value
        result["data"]["launch_verified"] = value
    elif mutation == "wrong_provider":
        request["sandbox_provider"]["provider_id"] = value
    elif mutation == "wrong_call":
        request["source_tool_call_id"] = value
    elif mutation == "wrong_goal":
        request["input"]["verification_goal"] = value

    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        request,
        result,
        [_local_app_open_action_event()],
        tool_timeline_start=0,
        run_id="run-local-open",
    )

    assert receipt == {}


def test_trusted_local_focus_observation_receipt_binds_provider_plan_and_source_call(
) -> None:
    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        _local_focus_verifier_request(),
        _local_focus_verifier_result(),
        [_local_focus_action_event()],
        tool_timeline_start=0,
        run_id="run-local-focus",
    )

    assert receipt == {
        "source_tool": "app.focus",
        "source_step_id": "focus-app",
        "source_tool_call_id": "call-focus-app",
        "run_id": "run-local-focus",
        "decision_id": "decision-local-focus",
        "plan_id": "plan-local-focus",
        "provider_kind": "local_desktop",
        "provider_id": "local-native-desktop",
        "verified_observed_state": "focused",
        "observed_app_name": "Slack",
    }


@pytest.mark.parametrize(
    ("mutation", "value"),
    [
        pytest.param("wrong_app", "Discord", id="wrong-app"),
        pytest.param("wrong_state", False, id="wrong-state"),
        pytest.param("wrong_provider", "other-local-provider", id="wrong-provider"),
        pytest.param("wrong_call", "call-another-focus", id="wrong-source-call"),
        pytest.param("wrong_plan", "plan-another-focus", id="wrong-plan"),
        pytest.param("permission_error", True, id="permission-error"),
        pytest.param("ok_only", True, id="ok-alone"),
    ],
)
def test_trusted_local_focus_observation_receipt_rejects_unbound_or_weak_evidence(
    mutation: str,
    value: Any,
) -> None:
    request = _local_focus_verifier_request()
    result = _local_focus_verifier_result()
    if mutation == "wrong_app":
        result["data"]["app_name"] = value
    elif mutation == "wrong_state":
        result["data"]["focus_verified"] = value
    elif mutation == "wrong_provider":
        request["sandbox_provider"]["provider_id"] = value
    elif mutation == "wrong_call":
        request["source_tool_call_id"] = value
    elif mutation == "wrong_plan":
        request["plan_id"] = value
    elif mutation == "permission_error":
        result["permission_error"] = value
    elif mutation == "ok_only":
        result["data"] = {}

    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        request,
        result,
        [_local_focus_action_event()],
        tool_timeline_start=0,
        run_id="run-local-focus",
    )

    assert receipt == {}


def test_trusted_system_volume_status_receipt_requires_exact_read_after_write_state(
) -> None:
    provider = {
        "provider_kind": "local_desktop",
        "provider_id": "local-native-desktop",
    }
    action_event = {
        "event": "agent.tool.call",
        "detail": "system.volume",
        "run_id": "run-volume",
        "decision_id": "decision-volume",
        "plan_id": "plan-volume",
        "step_id": "change-volume",
        "tool_call_id": "call-change-volume",
        "input_preview": {"action": "up"},
        "sandbox_provider": provider,
        "result": {
            "ok": True,
            "action": "system.volume",
            "data": {
                "requested_action": "up",
                "old_level": 40,
                "level": 50,
                "muted": False,
            },
            "_runtime_execution_provenance": {
                "source": "local_tool_broker",
                "version": 1,
            },
        },
    }
    verifier_request = {
        "tool": "system.volume",
        "input": {"action": "status"},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-volume",
        "decision_id": "decision-volume",
        "plan_id": "plan-volume",
        "step_id": "verify-volume",
        "source_step_id": "change-volume",
        "source_tool_call_id": "call-change-volume",
        "depends_on": ["change-volume"],
        "sandbox_provider": provider,
    }
    verifier_result = {
        "ok": True,
        "action": "system.volume",
        "data": {
            "requested_action": "status",
            "level": 50,
            "muted": False,
        },
        "_runtime_execution_provenance": {
            "source": "local_tool_broker",
            "version": 1,
        },
    }

    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        verifier_request,
        verifier_result,
        [action_event],
        tool_timeline_start=0,
        run_id="run-volume",
    )

    assert receipt == {
        "source_tool": "system.volume",
        "source_step_id": "change-volume",
        "source_tool_call_id": "call-change-volume",
        "run_id": "run-volume",
        "decision_id": "decision-volume",
        "plan_id": "plan-volume",
        "provider_kind": "local_desktop",
        "provider_id": "local-native-desktop",
        "verified_observed_state": "fulfilled",
        "observed_state_kind": "volume_state",
        "requested_action": "up",
        "observed_volume_level": 50,
        "observed_muted": False,
    }

    wrong_state = {
        **verifier_result,
        "data": {**verifier_result["data"], "level": 49},
    }
    assert tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        verifier_request,
        wrong_state,
        [action_event],
        tool_timeline_start=0,
        run_id="run-volume",
    ) == {}


def test_stale_search_field_does_not_mint_a_submit_success_receipt() -> None:
    provenance = {
        "source": tool_execution_module.RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
        "version": 1,
    }
    action_event = {
        "event": "agent.tool.call",
        "detail": "desktop.search_submit",
        "runtime_role": "submit_ui",
        "run_id": "run-search-submit",
        "decision_id": "decision-search-submit",
        "plan_id": "plan-search-submit",
        "step_id": "submit-search",
        "tool_call_id": "call-submit-search",
        "action_target": {
            "action": "submit_ui",
            "app_name": "Notes",
            "query": "hello",
        },
        "result": {
            "ok": True,
            "action": "desktop.search_submit",
            "data": {"submitted": True},
            "_runtime_execution_provenance": provenance,
        },
    }
    verifier_request = {
        "tool": "desktop.ui_elements",
        "input": {"app_name": "Notes"},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-search-submit",
        "decision_id": "decision-search-submit",
        "plan_id": "plan-search-submit",
        "step_id": "verify-search-submit",
        "source_step_id": "submit-search",
        "source_tool_call_id": "call-submit-search",
        "depends_on": ["submit-search"],
    }
    verifier_result = {
        "ok": True,
        "action": "desktop.ui_elements",
        "data": {
            "app_name": "Notes",
            "elements": [
                {"role": "AXSearchField", "name": "Search", "value": "hello"}
            ],
        },
        "_runtime_execution_provenance": provenance,
    }

    assert tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        verifier_request,
        verifier_result,
        [action_event],
        tool_timeline_start=0,
        run_id="run-search-submit",
    ) == {}


def _local_provider_context(provider_id: str = "local-native-desktop") -> dict[str, Any]:
    return {
        "desktop_execution_provider_routed": True,
        "desktop_execution_provider": {
            "provider_kind": "local_desktop",
            "provider_id": provider_id,
            "adapter_registered": True,
        },
    }


def _exact_workspace_file_readback_fixture(
    verifier_tool: str = "workspace.read",
) -> tuple[
    str,
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
    dict[str, Any],
]:
    exact_content = "# Analysis\n\n辉夜姬 🌙\n"
    source_request = {
        "tool": "terminal.run",
        "input": {"command": "python analyze.py"},
        "runtime_stage": "operate",
        "run_id": "run-analysis",
        "decision_id": "decision-analysis",
        "plan_id": "plan-analysis",
        "tool_plan_id": "tool-plan-analysis",
        "step_id": "run-analysis",
        "request_id": "request-run-analysis",
        "tool_call_id": "call-run-analysis",
        "action_target": {
            "kind": "workspace_file",
            "action": "analyze",
            "artifact_path": "reports/analysis.md",
        },
    }
    verifier_request = {
        "tool": verifier_tool,
        "input": {"path": "reports/analysis.md"},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-analysis",
        "decision_id": "decision-analysis",
        "plan_id": "plan-analysis",
        "tool_plan_id": "tool-plan-analysis",
        "step_id": "verify-analysis",
        "request_id": "request-verify-analysis",
        "tool_call_id": "call-verify-analysis",
        "depends_on": ["run-analysis"],
    }
    assert tool_execution_module._bind_exact_workspace_file_readback_verifier(
        source_request,
        [verifier_request],
        run_id="run-analysis",
    ) is True
    provenance = {
        "source": tool_execution_module.RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
        "version": tool_execution_module.RUNTIME_EXECUTION_PROVENANCE_VERSION,
    }
    source_event = {
        "event": "agent.tool.call",
        "detail": "terminal.run",
        "run_id": "run-analysis",
        "decision_id": "decision-analysis",
        "plan_id": "plan-analysis",
        "tool_plan_id": "tool-plan-analysis",
        "step_id": "run-analysis",
        "request_id": "request-run-analysis",
        "tool_call_id": "call-run-analysis",
        "action_target": dict(source_request["action_target"]),
        "result": {
            "ok": True,
            "exit_code": 0,
            tool_execution_module.RUNTIME_EXECUTION_PROVENANCE_KEY: provenance,
        },
    }
    verifier_result = {
        "ok": True,
        "path": "reports/analysis.md",
        "content": exact_content,
        "truncated": False,
        "size_bytes": len(exact_content.encode("utf-8")),
        "content_bytes": len(exact_content.encode("utf-8")),
        "decoding_lossy": False,
        tool_execution_module.RUNTIME_EXECUTION_PROVENANCE_KEY: provenance,
    }
    return (
        exact_content,
        source_request,
        verifier_request,
        source_event,
        verifier_result,
    )


@pytest.mark.parametrize(
    "verifier_tool",
    ["workspace.read", "fs.read_file", "file.read"],
)
def test_exact_workspace_file_readback_mints_runtime_receipt_from_bound_source(
    verifier_tool: str,
) -> None:
    (
        exact_content,
        _source_request,
        verifier_request,
        source_event,
        verifier_result,
    ) = _exact_workspace_file_readback_fixture(verifier_tool)
    assert verifier_request["source_tool"] == "terminal.run"
    assert verifier_request["source_step_id"] == "run-analysis"
    assert verifier_request["source_request_id"] == "request-run-analysis"
    assert verifier_request["source_tool_call_id"] == "call-run-analysis"
    assert verifier_request["verification_predicate_kind"] == (
        "exact_file_content_present"
    )

    receipt = (
        tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
            verifier_request,
            verifier_result,
            [source_event],
            tool_timeline_start=0,
            run_id="run-analysis",
        )
    )

    assert receipt == {
        "source_tool": "terminal.run",
        "source_step_id": "run-analysis",
        "source_tool_call_id": "call-run-analysis",
        "source_request_id": "request-run-analysis",
        "run_id": "run-analysis",
        "decision_id": "decision-analysis",
        "plan_id": "plan-analysis",
        "tool_plan_id": "tool-plan-analysis",
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "verification_predicate_kind": "exact_file_content_present",
        "verified_observed_state": "fulfilled",
        "observed_path": "reports/analysis.md",
        "content_sha256": hashlib.sha256(exact_content.encode("utf-8")).hexdigest(),
        "content_length": len(exact_content.encode("utf-8")),
    }


@pytest.mark.parametrize(
    "verifier_path",
    [
        pytest.param("reports/other.md", id="wrong-path"),
        pytest.param("../reports/analysis.md", id="parent-traversal"),
        pytest.param("/tmp/analysis.md", id="absolute-path"),
    ],
)
def test_exact_workspace_file_readback_binding_rejects_wrong_or_unsafe_path(
    verifier_path: str,
) -> None:
    source_request = {
        "tool": "python.run",
        "runtime_stage": "operate",
        "plan_id": "plan-analysis",
        "step_id": "run-analysis",
        "request_id": "request-run-analysis",
        "tool_call_id": "call-run-analysis",
        "action_target": {
            "action": "analyze",
            "output_path": "reports/analysis.md",
        },
    }
    verifier_request = {
        "tool": "workspace.read",
        "input": {"path": verifier_path},
        "runtime_stage": "verify",
        "step_id": "verify-analysis",
        "request_id": "request-verify-analysis",
        "tool_call_id": "call-verify-analysis",
        "plan_id": "plan-analysis",
        "depends_on": ["run-analysis"],
    }

    assert tool_execution_module._bind_exact_workspace_file_readback_verifier(
        source_request,
        [verifier_request],
        run_id="run-analysis",
    ) is False
    assert "verification_predicate_kind" not in verifier_request


@pytest.mark.parametrize(
    "action_target",
    [
        pytest.param(
            {"action": "write_file", "artifact_path": "../analysis.md"},
            id="traversal-artifact",
        ),
        pytest.param(
            {"action": "write_file", "output_path": "/tmp/analysis.md"},
            id="absolute-output",
        ),
        pytest.param(
            {"action": "execute", "path": "reports/analysis.md"},
            id="delegated-terminal-path",
        ),
        pytest.param(
            {"action": "execute", "output_path": "reports/analysis.md"},
            id="delegated-terminal-output-path",
        ),
    ],
)
def test_exact_workspace_file_readback_binding_rejects_unsafe_or_nonproducer_target(
    action_target: dict[str, Any],
) -> None:
    source_request = {
        "tool": "terminal.run",
        "runtime_stage": "operate",
        "plan_id": "plan-analysis",
        "step_id": "run-analysis",
        "request_id": "request-run-analysis",
        "tool_call_id": "call-run-analysis",
        "action_target": action_target,
    }
    verifier_request = {
        "tool": "workspace.read",
        "input": {"path": "reports/analysis.md"},
        "runtime_role": "verify_result",
        "step_id": "verify-analysis",
        "request_id": "request-verify-analysis",
        "tool_call_id": "call-verify-analysis",
        "plan_id": "plan-analysis",
        "depends_on": ["run-analysis"],
    }

    assert tool_execution_module._bind_exact_workspace_file_readback_verifier(
        source_request,
        [verifier_request],
        run_id="run-analysis",
    ) is False


@pytest.mark.parametrize(
    "mismatch",
    [
        "wrong-result-path",
        "empty-content",
        "broker-truncated-over-limit",
        "broker-lossy-invalid-utf8",
        "missing-completeness-metadata",
        "wrong-size",
        "wrong-content-bytes",
        "wrong-run",
        "wrong-plan",
        "wrong-source-call",
        "wrong-provider",
        "wrong-predicate",
    ],
)
def test_exact_workspace_file_readback_rejects_content_or_lineage_mismatch(
    mismatch: str,
) -> None:
    (
        _exact_content,
        _source_request,
        verifier_request,
        source_event,
        verifier_result,
    ) = _exact_workspace_file_readback_fixture()
    if mismatch == "wrong-result-path":
        verifier_result["path"] = "reports/other.md"
    elif mismatch == "empty-content":
        verifier_result["content"] = ""
    elif mismatch == "broker-truncated-over-limit":
        verifier_result.update(
            content="a" * 200_000,
            truncated=True,
            size_bytes=200_001,
            content_bytes=200_000,
        )
    elif mismatch == "broker-lossy-invalid-utf8":
        verifier_result.update(
            content="ok\ufffd",
            decoding_lossy=True,
            size_bytes=3,
            content_bytes=3,
        )
    elif mismatch == "missing-completeness-metadata":
        verifier_result.pop("truncated")
    elif mismatch == "wrong-size":
        verifier_result["size_bytes"] += 1
    elif mismatch == "wrong-content-bytes":
        verifier_result["content_bytes"] -= 1
    elif mismatch == "wrong-run":
        verifier_request["run_id"] = "run-other"
    elif mismatch == "wrong-plan":
        verifier_request["plan_id"] = "plan-other"
    elif mismatch == "wrong-source-call":
        verifier_request["source_tool_call_id"] = "call-other"
    elif mismatch == "wrong-provider":
        verifier_result["local_desktop_provider"] = {
            "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
            "provider_id": "local-other",
        }
    elif mismatch == "wrong-predicate":
        verifier_request["verification_predicate_kind"] = "file_exists"

    assert (
        tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
            verifier_request,
            verifier_result,
            [source_event],
            tool_timeline_start=0,
            run_id="run-analysis",
        )
        == {}
    )


@pytest.mark.parametrize(
    "verifier_tool",
    ["workspace.read", "fs.read_file", "file.read"],
)
def test_raw_read_alias_cannot_forge_exact_file_readback_receipt(
    verifier_tool: str,
) -> None:
    (
        _exact_content,
        _source_request,
        verifier_request,
        source_event,
        verifier_result,
    ) = _exact_workspace_file_readback_fixture(verifier_tool)
    serialized_request = {
        key: value
        for key, value in verifier_request.items()
        if not key.startswith("_runtime_private_")
    }

    assert (
        tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
            serialized_request,
            verifier_result,
            [source_event],
            tool_timeline_start=0,
            run_id="run-analysis",
        )
        == {}
    )


def test_exact_workspace_file_readback_rejects_untrusted_read_alias_even_with_authority(
) -> None:
    (
        _exact_content,
        _source_request,
        verifier_request,
        source_event,
        verifier_result,
    ) = _exact_workspace_file_readback_fixture()
    verifier_request["tool"] = "filesystem.read"

    assert (
        tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
            verifier_request,
            verifier_result,
            [source_event],
            tool_timeline_start=0,
            run_id="run-analysis",
        )
        == {}
    )


@pytest.mark.parametrize(
    "verifier_tool",
    ["workspace.read", "fs.read_file", "file.read"],
)
def test_runner_binds_exact_workspace_readback_only_after_source_success(
    verifier_tool: str,
) -> None:
    exact_content = "runtime-bound output 🌙\n"

    class ExactFileBroker:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            del approved
            self.calls.append(tool_name)
            if tool_name == "terminal.run":
                return {
                    "ok": True,
                    "returncode": 0,
                    "timed_out": False,
                    "stdout": "",
                    "stderr": "",
                }
            assert payload == {"path": "reports/analysis.md"}
            return {
                "ok": True,
                "path": "reports/analysis.md",
                "content": exact_content,
                "truncated": False,
                "size_bytes": len(exact_content.encode("utf-8")),
                "content_bytes": len(exact_content.encode("utf-8")),
                "decoding_lossy": False,
            }

    broker = ExactFileBroker()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        run_events=run_events,
    )
    timeline: list[dict[str, Any]] = []
    requests = [
        {
            "tool": "terminal.run",
            "input": {"command": "python analyze.py"},
            "runtime_stage": "operate",
            "decision_id": "decision-analysis",
            "plan_id": "plan-analysis",
            "tool_plan_id": "tool-plan-analysis",
            "step_id": "run-analysis",
            "request_id": "request-run-analysis",
            "tool_call_id": "call-run-analysis",
            "action_target": {
                "action": "analyze",
                "artifact_path": "reports/analysis.md",
            },
        },
        {
            "tool": verifier_tool,
            "input": {"path": "reports/analysis.md"},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "decision_id": "decision-analysis",
            "plan_id": "plan-analysis",
            "tool_plan_id": "tool-plan-analysis",
            "step_id": "verify-analysis",
            "request_id": "request-verify-analysis",
            "depends_on": ["run-analysis"],
        },
    ]

    _runner(call_agent_tool=executor.execute, run_events=run_events).run(
        requests,
        ["terminal.run", verifier_tool],
        broker,
        [{"role": "user", "content": "Analyze the data"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-analysis",
        budget=FakeBudget(),
    )

    receipt_event = next(
        event
        for event in reversed(timeline)
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == verifier_tool
        and event.get("source") == "runtime_native_postcondition_receipt"
    )
    persisted_receipt_event = next(
        payload
        for _run_id, event_type, payload in run_events
        if event_type == "agent.tool.call"
        and payload.get("tool") == verifier_tool
        and payload.get("source") == "runtime_native_postcondition_receipt"
    )
    receipt = receipt_event["result"]
    assert broker.calls == ["terminal.run", verifier_tool]
    assert persisted_receipt_event["tool_call_id"] != requests[1]["tool_call_id"]
    assert receipt["verification_predicate_kind"] == "exact_file_content_present"
    assert receipt["source_tool_call_id"] == "call-run-analysis"
    assert receipt["observed_path"] == "reports/analysis.md"
    assert receipt["content_sha256"] == hashlib.sha256(
        exact_content.encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize(
    ("observed_text", "observed_app", "provider_id", "expected"),
    [
        pytest.param("\n  辉夜姬 🌙\n", "Slack", "local-native-desktop", True, id="exact"),
        pytest.param("辉夜姬 🌙", "Slack", "local-native-desktop", False, id="wrong-bytes"),
        pytest.param("\n  辉夜姬 🌙\n", "Discord", "local-native-desktop", False, id="wrong-app"),
        pytest.param("\n  辉夜姬 🌙\n", "Slack", "other-provider", False, id="wrong-provider"),
    ],
)
def test_trusted_exact_typed_content_receipt_binds_utf8_app_target_and_provider(
    observed_text: str,
    observed_app: str,
    provider_id: str,
    expected: bool,
) -> None:
    exact_text = "\n  辉夜姬 🌙\n"
    action_event = {
        "event": "agent.tool.call",
        "detail": "app.focus_and_safe_type_text",
        "run_id": "run-type",
        "decision_id": "decision-type",
        "plan_id": "plan-type",
        "step_id": "type-message",
        "tool_call_id": "call-type-message",
        "input_preview": {
            "app_name": "Slack",
            "target": "Message",
            "text": exact_text,
        },
        "result": {
            "ok": True,
            "action": "app.focus_and_safe_type_text",
            "data": {
                "app_name": "Slack",
                "character_count": len(exact_text),
            },
            **_local_provider_context(),
        },
    }
    verifier_request = {
        "tool": "desktop.ui_elements",
        "input": {"app_name": "Slack"},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-type",
        "decision_id": "decision-type",
        "plan_id": "plan-type",
        "step_id": "verify-message",
        "source_step_id": "type-message",
        "source_tool_call_id": "call-type-message",
        "depends_on": ["type-message"],
        "desktop_execution_route": {
            "selected_provider_kind": "local_desktop",
            "selected_provider_id": provider_id,
        },
    }
    verifier_result = {
        "ok": True,
        "action": "desktop.ui_elements",
        "data": {
            "app_name": observed_app,
            "elements": [
                {
                    "role": "AXTextField",
                    "name": "Message",
                    "value": observed_text,
                }
            ],
        },
        **_local_provider_context(provider_id),
    }

    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        verifier_request,
        verifier_result,
        [action_event],
        tool_timeline_start=0,
        run_id="run-type",
    )

    assert bool(receipt) is expected
    if expected:
        assert receipt == {
            "source_tool": "app.focus_and_safe_type_text",
            "source_step_id": "type-message",
            "source_tool_call_id": "call-type-message",
            "run_id": "run-type",
            "decision_id": "decision-type",
            "plan_id": "plan-type",
            "provider_kind": "local_desktop",
            "provider_id": "local-native-desktop",
            "verification_predicate_kind": "exact_typed_content_present",
            "verified_observed_state": "fulfilled",
            "observed_app_name": "Slack",
            "observed_target": "Message",
            "content_sha256": hashlib.sha256(exact_text.encode("utf-8")).hexdigest(),
            "content_length": len(exact_text),
        }


def test_generic_type_dispatch_ack_cannot_short_circuit_content_verifier() -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.ui_elements",
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "plan_id": "plan-type",
            "source_step_id": "type-message",
            "source_tool_call_id": "call-type-message",
            "depends_on": ["type-message"],
        },
        [
            {
                "event": "agent.tool.call",
                "detail": "app.focus_and_safe_type_text",
                "plan_id": "plan-type",
                "step_id": "type-message",
                "tool_call_id": "call-type-message",
                "input_preview": {"app_name": "Slack", "text": "hello"},
                "result": {
                    "ok": True,
                    "postcondition_verified": True,
                    "data": {"character_count": 5},
                },
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


def test_runner_executes_real_ui_readback_before_projecting_exact_content_receipt(
) -> None:
    exact_text = "\n  辉夜姬 🌙\n"
    executed: list[str] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        current_timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        executed.append(tool_name)
        result = (
            {
                "ok": True,
                "action": tool_name,
                "data": {
                    "app_name": "Slack",
                    "character_count": len(exact_text),
                },
                **_local_provider_context(),
            }
            if tool_name == "app.focus_and_safe_type_text"
            else {
                "ok": True,
                "action": tool_name,
                "data": {
                    "app_name": "Slack",
                    "elements": [
                        {
                            "role": "AXTextField",
                            "name": "Message",
                            "value": exact_text,
                        }
                    ],
                },
                **_local_provider_context(),
            }
        )
        current_timeline.append(
            {
                "event": "agent.tool.call",
                "detail": tool_name,
                "run_id": "run-type-integration",
                "decision_id": tool_request.get("decision_id"),
                "plan_id": tool_request.get("plan_id"),
                "step_id": tool_request.get("step_id"),
                "tool_call_id": tool_request.get("tool_call_id"),
                "input_preview": dict(tool_request.get("input") or {}),
                "result": result,
            }
        )
        return result

    _runner(call_agent_tool=call_agent_tool).run(
        [
            {
                "tool": "app.focus_and_safe_type_text",
                "input": {
                    "app_name": "Slack",
                    "target": "Message",
                    "text": exact_text,
                },
                "runtime_stage": "operate",
                "step_id": "type-message",
                "tool_call_id": "call-type-message",
                "decision_id": "decision-type-integration",
                "plan_id": "plan-type-integration",
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"app_name": "Slack"},
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "step_id": "verify-message",
                "depends_on": ["type-message"],
                "decision_id": "decision-type-integration",
                "plan_id": "plan-type-integration",
                "desktop_execution_route": {
                    "selected_provider_kind": "local_desktop",
                    "selected_provider_id": "local-native-desktop",
                },
            },
        ],
        ["app.focus_and_safe_type_text", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Type the exact text into Slack"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-type-integration",
        budget=FakeBudget(),
    )

    assert executed == ["app.focus_and_safe_type_text", "desktop.ui_elements"]
    satisfied = _last_event(timeline, "agent.post_action_verification.satisfied")
    assert satisfied["result"]["verification_predicate_kind"] == (
        "exact_typed_content_present"
    )
    assert satisfied["result"]["source_tool_call_id"] == "call-type-message"
    assert satisfied["result"]["content_sha256"] == hashlib.sha256(
        exact_text.encode("utf-8")
    ).hexdigest()


@pytest.mark.parametrize(
    ("observed_text", "truncated", "expected"),
    [
        pytest.param("\nhello 🌙\n", False, True, id="exact"),
        pytest.param("hello 🌙", False, False, id="wrong-bytes"),
        pytest.param("\nhello 🌙\n", True, False, id="truncated"),
    ],
)
def test_trusted_clipboard_write_receipt_requires_exact_readback_and_lineage(
    observed_text: str,
    truncated: bool,
    expected: bool,
) -> None:
    exact_text = "\nhello 🌙\n"
    provenance = {
        "_runtime_execution_provenance": {
            "source": "local_tool_broker",
            "version": 1,
        }
    }
    action_event = {
        "event": "agent.tool.call",
        "detail": "clipboard.write",
        "run_id": "run-clipboard",
        "decision_id": "decision-clipboard",
        "plan_id": "plan-clipboard",
        "step_id": "write-clipboard",
        "tool_call_id": "call-write-clipboard",
        "input_preview": {"text": exact_text},
        "result": {
            "ok": True,
            "action": "clipboard.write",
            "data": {"text_length": len(exact_text)},
            **provenance,
        },
    }
    verifier_request = {
        "tool": "clipboard.read",
        "input": {},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-clipboard",
        "decision_id": "decision-clipboard",
        "plan_id": "plan-clipboard",
        "step_id": "verify-clipboard-write",
        "source_step_id": "write-clipboard",
        "source_tool_call_id": "call-write-clipboard",
        "depends_on": ["write-clipboard"],
    }
    verifier_result = {
        "ok": True,
        "action": "clipboard.read",
        "data": {
            "text": observed_text,
            "text_length": len(exact_text),
            "truncated": truncated,
        },
        **provenance,
    }

    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        verifier_request,
        verifier_result,
        [action_event],
        tool_timeline_start=0,
        run_id="run-clipboard",
    )

    assert bool(receipt) is expected
    if expected:
        assert receipt["source_tool_call_id"] == "call-write-clipboard"
        assert receipt["plan_id"] == "plan-clipboard"
        assert receipt["provider_kind"] == "local_desktop"
        assert receipt["provider_id"] == "local-native-desktop"
        assert receipt["verification_predicate_kind"] == (
            "exact_clipboard_content_present"
        )
        assert receipt["verified_observed_state"] == "persisted"
        assert receipt["content_sha256"] == hashlib.sha256(
            exact_text.encode("utf-8")
        ).hexdigest()


def test_safe_copy_inserts_clipboard_read_but_does_not_claim_unknown_selection() -> None:
    request = {
        "tool": "desktop.safe_shortcut",
        "input": {"action": "copy"},
        "runtime_stage": "operate",
        "step_id": "copy-selection",
        "request_id": "request-copy-selection",
        "tool_call_id": "call-copy-selection",
        "plan_id": "plan-copy-selection",
        "requires_post_action_verification": True,
    }
    verifier = tool_execution_module._post_action_verification_request(
        "desktop.safe_shortcut",
        request,
        {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "data": {"shortcut_action": "copy"},
        },
        allowed_tools=["desktop.ui_elements", "clipboard.read"],
        remaining_requests=[
            {
                "tool": "desktop.ui_elements",
                "runtime_stage": "verify",
                "step_id": "verify-selection-ui",
                "depends_on": ["copy-selection"],
            }
        ],
        active_window_target={"app_name": "Notes"},
    )

    assert verifier["tool"] == "clipboard.read"
    assert verifier["input"] == {}
    assert verifier["source_step_id"] == "copy-selection"
    assert verifier["source_tool_call_id"] == "call-copy-selection"
    assert verifier["depends_on"] == ["copy-selection"]

    assert tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        {
            **verifier,
            "run_id": "run-copy-selection",
            "plan_id": "plan-copy-selection",
        },
        {
            "ok": True,
            "action": "clipboard.read",
            "data": {"text": "unknown selection", "text_length": 17, "truncated": False},
            "_runtime_execution_provenance": {
                "source": "local_tool_broker",
                "version": 1,
            },
        },
        [
            {
                "event": "agent.tool.call",
                "detail": "desktop.safe_shortcut",
                "run_id": "run-copy-selection",
                "plan_id": "plan-copy-selection",
                "step_id": "copy-selection",
                "tool_call_id": "call-copy-selection",
                "input_preview": {"action": "copy"},
                "result": {
                    "ok": True,
                    "action": "desktop.safe_shortcut",
                    "_runtime_execution_provenance": {
                        "source": "local_tool_broker",
                        "version": 1,
                    },
                },
            }
        ],
        tool_timeline_start=0,
        run_id="run-copy-selection",
    ) == {}


def test_runner_projects_unknown_safe_copy_readback_as_honest_partial() -> None:
    executed: list[str] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        current_timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        executed.append(tool_name)
        result = (
            {
                "ok": True,
                "action": "desktop.safe_shortcut",
                "data": {"shortcut_action": "copy"},
                **_local_provider_context(),
            }
            if tool_name == "desktop.safe_shortcut"
            else {
                "ok": True,
                "action": "clipboard.read",
                "data": {
                    "text": "possibly stale",
                    "text_length": 14,
                    "truncated": False,
                },
                **_local_provider_context(),
            }
        )
        current_timeline.append(
            {
                "event": "agent.tool.call",
                "detail": tool_name,
                "run_id": "run-copy-partial",
                "plan_id": tool_request.get("plan_id"),
                "step_id": tool_request.get("step_id"),
                "tool_call_id": tool_request.get("tool_call_id"),
                "input_preview": dict(tool_request.get("input") or {}),
                "result": result,
            }
        )
        return result

    _runner(call_agent_tool=call_agent_tool).run(
        [
            {
                "tool": "desktop.safe_shortcut",
                "input": {"action": "copy"},
                "runtime_stage": "operate",
                "step_id": "copy-selection",
                "tool_call_id": "call-copy-selection",
                "plan_id": "plan-copy-selection",
                "requires_post_action_verification": True,
            }
        ],
        ["desktop.safe_shortcut", "clipboard.read"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Copy the current selection"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-copy-partial",
        budget=FakeBudget(),
    )

    assert executed == ["desktop.safe_shortcut", "clipboard.read"]
    read_event = next(
        event
        for event in reversed(timeline)
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "clipboard.read"
    )
    assert read_event["result"]["status"] == "partial"
    assert read_event["result"]["reason"] == "clipboard_copy_source_unverified"
    assert read_event["result"]["clipboard_source_verified"] is False
    assert not any(
        event.get("event") == "agent.post_action_verification.satisfied"
        for event in timeline
    )


def test_exact_clipboard_paste_readback_unlocks_only_the_dependent_submit_approval() -> None:
    exact_text = "\n  超时空辉夜姬 🌙\n第二行  "
    timeline: list[dict[str, Any]] = []
    calls: list[tuple[str, dict[str, Any]]] = []
    pending_builder = FakePendingApprovalBuilder()

    def call_agent_tool(
        request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        current_timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(request.get("tool") or "")
        payload = dict(request.get("input") or {})
        calls.append((tool_name, payload))
        if tool_name == "clipboard.read":
            result = {
                "ok": True,
                "action": tool_name,
                "data": {
                    "text": exact_text,
                    "text_length": len(exact_text),
                    "truncated": False,
                    "max_chars": payload["max_chars"],
                },
                **_local_provider_context(),
            }
        elif tool_name == "app.focus_and_safe_shortcut":
            result = {
                "ok": True,
                "action": tool_name,
                "data": {
                    "app_name": "Slack",
                    "pid": 4401,
                    "window_id": 77,
                    "shortcut_action": "paste",
                },
                **_local_provider_context(),
            }
        elif tool_name == "desktop.ui_elements":
            result = {
                "ok": True,
                "action": tool_name,
                "data": {
                    "app_name": "Slack",
                    "pid": 4401,
                    "window_id": 77,
                    "truncated": False,
                    "elements": [
                        {
                            "role": "AXTextArea",
                            "identifier": "slack.message.compose",
                            "name": "Message",
                            "value": exact_text,
                            "enabled": True,
                        }
                    ],
                },
                **_local_provider_context(),
            }
        else:
            result = {
                "ok": False,
                "action": tool_name,
                "approval_required": True,
                "status": "approval_required",
            }
        current_timeline.append(
            {
                "event": "agent.tool.call",
                "detail": tool_name,
                "run_id": "run-exact-paste",
                "decision_id": request.get("decision_id"),
                "plan_id": request.get("plan_id"),
                "tool_plan_id": request.get("tool_plan_id"),
                "step_id": request.get("step_id"),
                "request_id": request.get("request_id"),
                "tool_call_id": request.get("tool_call_id"),
                "input_preview": payload,
                "result": result,
            }
        )
        return result

    requests = [
        {
            "tool": "clipboard.read",
            "input": {"max_chars": 4},
            "runtime_stage": "observe",
            "step_id": "read-clipboard-source",
            "request_id": "request-read-clipboard-source",
            "tool_call_id": "call-read-clipboard-source",
            "decision_id": "decision-exact-paste",
            "plan_id": "plan-exact-paste",
            "tool_plan_id": "tool-plan-exact-paste",
        },
        {
            "tool": "app.focus_and_safe_shortcut",
            "input": {
                "app_name": "Slack",
                "target": "Message",
                "action": "paste",
            },
            "runtime_stage": "operate",
            "step_id": "paste-content",
            "request_id": "request-paste-content",
            "tool_call_id": "call-paste-content",
            "decision_id": "decision-exact-paste",
            "plan_id": "plan-exact-paste",
            "tool_plan_id": "tool-plan-exact-paste",
            "depends_on": ["read-clipboard-source"],
            "requires_post_action_verification": True,
        },
        {
            "tool": "desktop.ui_elements",
            "input": {"app_name": "Slack"},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "step_id": "verify-pasted-content",
            "request_id": "request-verify-pasted-content",
            "tool_call_id": "call-verify-pasted-content",
            "decision_id": "decision-exact-paste",
            "plan_id": "plan-exact-paste",
            "tool_plan_id": "tool-plan-exact-paste",
            "depends_on": ["paste-content"],
        },
        {
            "tool": "desktop.submit_foreground",
            "input": {},
            "step_id": "submit-message",
            "request_id": "request-submit-message",
            "tool_call_id": "call-submit-message",
            "decision_id": "decision-exact-paste",
            "plan_id": "plan-exact-paste",
            "tool_plan_id": "tool-plan-exact-paste",
            "depends_on": ["paste-content"],
            "approval_required": True,
        },
    ]

    with pytest.raises(AgentApprovalRequired) as approval:
        _runner(
            call_agent_tool=call_agent_tool,
            pending_approval_builder=pending_builder,
        ).run(
            requests,
            [
                "clipboard.read",
                "app.focus_and_safe_shortcut",
                "desktop.ui_elements",
                "desktop.submit_foreground",
            ],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Paste clipboard content into Slack and send"}],
            timeline,
            [],
            next_iteration=1,
            run_id="run-exact-paste",
            budget=FakeBudget(),
        )

    assert approval.value.pending_approval["tool"] == "desktop.submit_foreground"
    assert calls == [
        ("clipboard.read", {"max_chars": 12000}),
        (
            "app.focus_and_safe_shortcut",
            {"app_name": "Slack", "target": "Message", "action": "paste"},
        ),
        ("desktop.ui_elements", {"app_name": "Slack"}),
        ("desktop.submit_foreground", {}),
    ]
    receipt_event = next(
        event
        for event in reversed(timeline)
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "desktop.ui_elements"
        and event.get("source") == "runtime_native_postcondition_receipt"
    )
    receipt = receipt_event["result"]
    assert receipt["verification_predicate_kind"] == "exact_pasted_content_present"
    assert receipt["content_sha256"] == hashlib.sha256(
        exact_text.encode("utf-8")
    ).hexdigest()
    assert receipt["clipboard_source_request_id"] == (
        "request-read-clipboard-source"
    )
    assert receipt["clipboard_source_tool_call_id"] == (
        "call-read-clipboard-source"
    )
    assert receipt["target_ui_readback_verified"] is True
    assert receipt["target_ui_editable_verified"] is True
    assert receipt["target_window"] == {
        "app_name": "Slack",
        "pid": 4401,
        "window_id": 77,
    }
    assert receipt["target_ui_identity"] == {
        "role": "textarea",
        "identifier": "slack.message.compose",
        "name": "message",
    }


def test_runtime_executor_mints_exact_paste_receipt_for_one_bound_window_target() -> None:
    exact_text = "runtime executor exact paste 🌙"

    class ExactPasteBroker:
        def __init__(self) -> None:
            self.calls: list[str] = []

        def call(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            del approved
            self.calls.append(tool_name)
            if tool_name == "clipboard.read":
                return {
                    "ok": True,
                    "action": tool_name,
                    "data": {
                        "text": exact_text,
                        "text_length": len(exact_text),
                        "truncated": False,
                        "max_chars": payload["max_chars"],
                    },
                }
            if tool_name == "app.focus_and_safe_shortcut":
                return {
                    "ok": True,
                    "action": tool_name,
                    "data": {
                        "app_name": "Slack",
                        "pid": 4401,
                        "window_id": 77,
                        "shortcut_action": "paste",
                    },
                }
            return {
                "ok": True,
                "action": tool_name,
                "data": {
                    "app_name": "Slack",
                    "pid": 4401,
                    "window_id": 77,
                    "truncated": False,
                    "elements": [
                        {
                            "role": "AXTextArea",
                            "identifier": "slack.message.compose",
                            "name": "Message",
                            "value": exact_text,
                            "enabled": True,
                        }
                    ],
                },
            }

    broker = ExactPasteBroker()
    executor = _executor(tool_call_events=FakeToolCallEvents())
    replay_appended = False

    def execute_tool(
        request: dict[str, Any],
        allowed_tools: list[str],
        broker_arg: Any,
        timeline: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        nonlocal replay_appended
        result = executor.execute(
            request,
            allowed_tools,
            broker_arg,
            timeline,
            approved=True,
            run_id=str(kwargs.get("run_id") or ""),
            budget=kwargs.get("budget"),
        )
        if (
            str(request.get("tool_call_id") or "") == "call-verify-paste"
            and not replay_appended
        ):
            replay_appended = True
            requests.append(dict(request))
        return result

    requests = [
        {
            "tool": "clipboard.read",
            "input": {},
            "runtime_stage": "observe",
            "step_id": "read-source",
            "request_id": "request-read-source",
            "tool_call_id": "call-read-source",
            "decision_id": "decision-runtime-paste",
            "plan_id": "plan-runtime-paste",
            "tool_plan_id": "tool-plan-runtime-paste",
        },
        {
            "tool": "app.focus_and_safe_shortcut",
            "input": {"app_name": "Slack", "target": "Message", "action": "paste"},
            "runtime_stage": "operate",
            "step_id": "paste-source",
            "request_id": "request-paste-source",
            "tool_call_id": "call-paste-source",
            "decision_id": "decision-runtime-paste",
            "plan_id": "plan-runtime-paste",
            "tool_plan_id": "tool-plan-runtime-paste",
            "depends_on": ["read-source"],
            "requires_post_action_verification": True,
        },
        {
            "tool": "desktop.ui_elements",
            "input": {"app_name": "Slack"},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "step_id": "verify-paste",
            "request_id": "request-verify-paste",
            "tool_call_id": "call-verify-paste",
            "decision_id": "decision-runtime-paste",
            "plan_id": "plan-runtime-paste",
            "tool_plan_id": "tool-plan-runtime-paste",
            "depends_on": ["paste-source"],
        },
    ]
    timeline: list[dict[str, Any]] = []
    _runner(call_agent_tool=execute_tool).run(
        requests,
        ["clipboard.read", "app.focus_and_safe_shortcut", "desktop.ui_elements"],
        broker,
        [{"role": "user", "content": "Paste the clipboard into Slack Message"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-runtime-paste",
        budget=FakeBudget(),
    )

    assert broker.calls == [
        "clipboard.read",
        "app.focus_and_safe_shortcut",
        "desktop.ui_elements",
        "desktop.ui_elements",
    ]
    receipts = [
        event["result"]
        for event in timeline
        if event.get("event") == "agent.post_action_verification.satisfied"
        and isinstance(event.get("result"), dict)
        and event["result"].get("verification_predicate_kind")
        == "exact_pasted_content_present"
    ]
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt["content_sha256"] == hashlib.sha256(
        exact_text.encode("utf-8")
    ).hexdigest()
    assert receipt["target_window"]["window_id"] == 77
    assert receipt["target_ui_identity"]["identifier"] == (
        "slack.message.compose"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "wrong_hash",
        "wrong_target_app",
        "wrong_target",
        "wrong_window",
        "empty_target",
        "wrong_provider",
        "wrong_source_call",
        "wrong_plan",
        "wrong_run",
        "truncated",
        "non_editable",
        "public_forgery",
    ],
)
def test_exact_clipboard_paste_receipt_rejects_forged_or_mismatched_evidence(
    mutation: str,
) -> None:
    exact_text = "前后空格  🌙\nline two"
    source_request = {
        "tool": "clipboard.read",
        "input": {},
        "step_id": "read-source",
        "request_id": "request-read-source",
        "tool_call_id": "call-read-source",
        "decision_id": "decision-paste",
        "plan_id": "plan-paste",
        "tool_plan_id": "tool-plan-paste",
        "run_id": "run-paste",
    }
    paste_request = {
        "tool": "app.focus_and_safe_shortcut",
        "input": {"app_name": "Slack", "target": "Message", "action": "paste"},
        "step_id": "paste-source",
        "request_id": "request-paste-source",
        "tool_call_id": "call-paste-source",
        "decision_id": "decision-paste",
        "plan_id": "plan-paste",
        "tool_plan_id": "tool-plan-paste",
        "run_id": "run-paste",
        "depends_on": ["read-source"],
        "requires_post_action_verification": True,
    }
    tool_execution_module._prepare_runtime_private_clipboard_source_requests(
        [source_request, paste_request]
    )
    source_receipt = (
        tool_execution_module._private_clipboard_source_receipt_from_result(
            source_request,
            {
                "ok": True,
                "action": "clipboard.read",
                "data": {
                    "text": exact_text,
                    "text_length": len(exact_text),
                    "truncated": False,
                    "max_chars": 12000,
                },
                **_local_provider_context(),
            },
            run_id="run-paste",
            tool_sequence=1,
        )
    )
    selected_source = tool_execution_module._private_clipboard_source_for_paste(
        paste_request,
        {"call-read-source": source_receipt},
        run_id="run-paste",
        tool_sequence=2,
    )
    binding = tool_execution_module._private_clipboard_paste_binding_from_action(
        selected_source,
        paste_request,
        {
            "ok": True,
            "action": "app.focus_and_safe_shortcut",
            "data": {
                "app_name": "Slack",
                "pid": 4401,
                "window_id": 77,
                "shortcut_action": "paste",
            },
            **_local_provider_context(),
        },
        [
            {
                "tool": "desktop.ui_elements",
                "input": {"app_name": "Slack"},
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "run_id": "run-paste",
                "decision_id": "decision-paste",
                "plan_id": "plan-paste",
                "tool_plan_id": "tool-plan-paste",
                "step_id": "verify-paste",
                "request_id": "request-verify-paste",
                "tool_call_id": "call-verify-paste",
                "depends_on": ["paste-source"],
            }
        ],
        run_id="run-paste",
        tool_sequence=2,
    )
    action_event = {
        "event": "agent.tool.call",
        "detail": "app.focus_and_safe_shortcut",
        "run_id": "run-paste",
        "decision_id": "decision-paste",
        "plan_id": "plan-paste",
        "tool_plan_id": "tool-plan-paste",
        "step_id": "paste-source",
        "request_id": "request-paste-source",
        "tool_call_id": "call-paste-source",
        "input_preview": dict(paste_request["input"]),
        "result": {
            "ok": True,
            "action": "app.focus_and_safe_shortcut",
            "data": {
                "app_name": "Slack",
                "pid": 4401,
                "window_id": 77,
                "shortcut_action": "paste",
            },
            **_local_provider_context(),
        },
    }
    verifier_request = {
        "tool": "desktop.ui_elements",
        "input": {"app_name": "Slack"},
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "run_id": "run-paste",
        "decision_id": "decision-paste",
        "plan_id": "plan-paste",
        "tool_plan_id": "tool-plan-paste",
        "step_id": "verify-paste",
        "request_id": "request-verify-paste",
        "tool_call_id": "call-verify-paste",
        "source_step_id": "paste-source",
        "source_tool_call_id": "call-paste-source",
        "depends_on": ["paste-source"],
    }
    verifier_result = {
        "ok": True,
        "action": "desktop.ui_elements",
        "data": {
            "app_name": "Slack",
            "pid": 4401,
            "window_id": 77,
            "truncated": False,
            "elements": [
                {
                    "role": "AXTextArea",
                    "identifier": "slack.message.compose",
                    "name": "Message",
                    "value": exact_text,
                    "enabled": True,
                }
            ],
        },
        **_local_provider_context(),
    }

    if mutation == "wrong_hash":
        binding = {**binding, "content_sha256": "0" * 64}
    elif mutation == "wrong_target_app":
        verifier_result["data"] = {**verifier_result["data"], "app_name": "Discord"}
    elif mutation == "wrong_target":
        verifier_result["data"] = {
            **verifier_result["data"],
            "elements": [
                {
                    "role": "AXTextArea",
                    "identifier": "slack.other.compose",
                    "name": "Other",
                    "value": exact_text,
                    "enabled": True,
                }
            ],
        }
    elif mutation == "wrong_window":
        verifier_result["data"] = {
            **verifier_result["data"],
            "window_id": 88,
        }
    elif mutation == "empty_target":
        binding = {**binding, "target_ui_element": ""}
    elif mutation == "wrong_provider":
        verifier_result.update(_local_provider_context("other-provider"))
    elif mutation == "wrong_source_call":
        verifier_request["source_tool_call_id"] = "call-other-paste"
    elif mutation == "wrong_plan":
        verifier_request["plan_id"] = "plan-other"
    elif mutation == "wrong_run":
        verifier_request["run_id"] = "run-other"
    elif mutation == "truncated":
        verifier_result["data"] = {**verifier_result["data"], "truncated": True}
    elif mutation == "non_editable":
        verifier_result["data"] = {
            **verifier_result["data"],
            "elements": [
                {"role": "AXStaticText", "name": "Message", "value": exact_text}
            ],
        }
    elif mutation == "public_forgery":
        binding = {
            key: value
            for key, value in binding.items()
            if key != "_authority"
        }

    receipt = tool_execution_module._trusted_postcondition_observation_receipt_for_verifier(
        verifier_request,
        verifier_result,
        [action_event],
        tool_timeline_start=0,
        run_id="run-paste",
        private_clipboard_paste_binding=binding,
    )

    assert receipt == {}


def test_private_clipboard_source_receipt_expires_and_is_single_use() -> None:
    source_request = {
        "tool": "clipboard.read",
        "input": {},
        "step_id": "read-source",
        "request_id": "request-read-source",
        "tool_call_id": "call-read-source",
        "plan_id": "plan-paste",
        "run_id": "run-paste",
    }
    paste_request = {
        "tool": "desktop.safe_shortcut",
        "input": {"app_name": "Slack", "action": "paste"},
        "step_id": "paste-source",
        "request_id": "request-paste-source",
        "tool_call_id": "call-paste-source",
        "plan_id": "plan-paste",
        "run_id": "run-paste",
        "depends_on": ["read-source"],
        "requires_post_action_verification": True,
    }
    tool_execution_module._prepare_runtime_private_clipboard_source_requests(
        [source_request, paste_request]
    )
    receipt = tool_execution_module._private_clipboard_source_receipt_from_result(
        source_request,
        {
            "ok": True,
            "action": "clipboard.read",
            "data": {
                "text": "exact",
                "text_length": 5,
                "truncated": False,
                "max_chars": 12000,
            },
            **_local_provider_context(),
        },
        run_id="run-paste",
        tool_sequence=1,
    )
    receipts = {"call-read-source": receipt}

    selected = tool_execution_module._private_clipboard_source_for_paste(
        paste_request,
        receipts,
        run_id="run-paste",
        tool_sequence=2,
    )
    assert selected
    tool_execution_module._consume_private_clipboard_source_receipt(
        selected,
        receipts,
        paste_tool_call_id="call-paste-source",
    )
    assert tool_execution_module._private_clipboard_source_for_paste(
        paste_request,
        receipts,
        run_id="run-paste",
        tool_sequence=3,
    ) == {}

    fresh_receipts = {"call-read-source": receipt}
    assert tool_execution_module._private_clipboard_source_for_paste(
        paste_request,
        fresh_receipts,
        run_id="run-paste",
        tool_sequence=18,
    ) == {}


def test_native_postcondition_receipt_rejects_legacy_event_with_request_correlation() -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.active_window",
            "runtime_stage": "verify",
            "plan_id": "plan-open",
            "source_request_id": "request-open",
            "source_step_id": "open-app",
            "depends_on": ["open-app"],
        },
        [
            {
                "event": "agent.tool.call",
                "detail": "app.open",
                "request_id": "request-open",
                "step_id": "open-app",
                "result": {"ok": True, "launch_verified": True},
            },
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


def test_native_app_open_receipt_preserves_bound_verifier_lineage_and_predicate() -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.verify",
            "input": {"app_name": "PixelForge", "verification_goal": "app_running"},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": "run-open-app",
            "plan_id": "plan-open-app",
            "tool_plan_id": "tool-plan-open-app",
            "step_id": "verify-desktop-result",
            "planner_step_id": "verify-desktop-result",
            "source_step_id": "open-or-focus-app",
            "source_request_id": "request-open-app",
            "source_tool_call_id": "call-open-app",
            "depends_on": ["open-or-focus-app"],
            "verification_predicate_kind": "app_window_present",
        },
        [
            {
                **_runtime_intrinsic_action_event(
                    "app.open",
                    {"app_name": "PixelForge"},
                    {"ok": True},
                    run_id="run-open-app",
                    plan_id="plan-open-app",
                    step_id="open-or-focus-app",
                    request_id="request-open-app",
                    tool_call_id="call-open-app",
                ),
                "tool_plan_id": "tool-plan-open-app",
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {
        "source_tool": "app.open",
        "source_step_id": "open-or-focus-app",
        "source_tool_call_id": "call-open-app",
        "source_request_id": "request-open-app",
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "verification_predicate_kind": "app_window_present",
        "verified_observed_state": "open",
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "trusted",
        "provider_self_report",
        "wrong_path",
        "wrong_app",
        "missing_identity",
        "wrong_provider",
    ),
)
def test_native_open_path_with_app_receipt_requires_exact_runtime_authority(
    mutation: str,
) -> None:
    source_event = {
        "event": "agent.tool.call",
        "detail": "desktop.open_path_with_app",
        "run_id": "run-open-path",
        "plan_id": "plan-open-path",
        "step_id": "open-selected-discovered-app",
        "request_id": "request-open-path",
        "tool_call_id": "call-open-path",
        "input_preview": {
            "app_name": "PixelForge",
            "path": "Downloads/report.pdf",
        },
        "result": {
            "ok": True,
            "action": "desktop.open_path_with_app",
            "postcondition_verified": True,
            "native_dispatch_verified": True,
            "verified_observed_state": "fulfilled",
            "verification_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
            "verification_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
            "data": {
                "app_name": "PixelForge",
                "path": "Downloads/report.pdf",
                "open_target": "app_open",
                "exists": True,
            },
            **_local_provider_context(),
        },
    }
    if mutation == "provider_self_report":
        source_event["result"].pop("desktop_execution_provider_routed")
        source_event["result"].pop("desktop_execution_provider")
    elif mutation == "wrong_path":
        source_event["result"]["data"]["path"] = "Downloads/other.pdf"
    elif mutation == "wrong_app":
        source_event["result"]["data"]["app_name"] = "OtherForge"
    elif mutation == "missing_identity":
        source_event.pop("request_id")
    elif mutation == "wrong_provider":
        source_event["result"]["verification_provider_id"] = "other-provider"

    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.ui_elements",
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": "run-open-path",
            "plan_id": "plan-open-path",
            "step_id": "verify-desktop-result",
            "source_step_id": "open-selected-discovered-app",
            "source_request_id": "request-open-path",
            "source_tool_call_id": "call-open-path",
            "depends_on": ["open-selected-discovered-app"],
        },
        [source_event],
        tool_timeline_start=0,
    )

    if mutation == "trusted":
        assert receipt == {
            "source_tool": "desktop.open_path_with_app",
            "source_step_id": "open-selected-discovered-app",
            "source_tool_call_id": "call-open-path",
            "source_request_id": "request-open-path",
            "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
            "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
            "verified_observed_state": "fulfilled",
        }
    else:
        assert receipt == {}


@pytest.mark.parametrize(
    "mutation",
    (
        "trusted",
        "no_plan_candidate",
        "duplicate_plan_candidate",
        "multiple_contract_verifiers",
        "wrong_contract_run",
        "wrong_plan",
        "wrong_source_dependency",
    ),
)
def test_declared_open_path_with_app_verifier_requires_unique_goal_plan_lineage(
    mutation: str,
) -> None:
    source_request = {
        "tool": "desktop.open_path_with_app",
        "input": {
            "app_name": "PixelForge",
            "path": "Downloads/report.pdf",
        },
        "run_id": "run-open-path",
        "decision_id": "decision-open-path",
        "plan_id": "plan-open-path",
        "step_id": "open-selected-discovered-app",
        "request_id": "request-open-path",
        "tool_call_id": "call-open-path",
        "capability_id": "file.desktop_access",
        "goal_contract_id": "goal-open-path",
        "goal_criterion_id": "criterion-open-path",
    }
    source_result = {
        "ok": True,
        "action": "desktop.open_path_with_app",
        "postcondition_verified": True,
        "native_dispatch_verified": True,
        "verified_observed_state": "fulfilled",
        "verification_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "verification_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "data": {
            "app_name": "PixelForge",
            "path": "Downloads/report.pdf",
            "open_target": "app_open",
            "exists": True,
        },
        **_local_provider_context(),
    }
    verifier_step_ids = ["verify-desktop-result"]
    if mutation == "multiple_contract_verifiers":
        verifier_step_ids.append("verify-desktop-result-again")
    contract_event = {
        "event": "agent.goal.contract",
        "run_id": "run-open-path",
        "contract_id": "goal-open-path",
        "goal_contract": {
            "contract_id": "goal-open-path",
            "run_id": (
                "run-other" if mutation == "wrong_contract_run" else "run-open-path"
            ),
            "source": "goal_contract",
            "criteria": [
                {
                    "criterion_id": "criterion-open-path",
                    "effectful": True,
                    "expected": {"state": "fulfilled"},
                    "required_capabilities": ["file.desktop_access"],
                    "source_step_ids": ["open-selected-discovered-app"],
                    "verifier_step_ids": verifier_step_ids,
                }
            ],
        },
    }
    plan_event = {
        "event": "agent.plan.step",
        "source": "runtime_planner",
        "decision_id": "decision-open-path",
        "plan_id": "plan-other" if mutation == "wrong_plan" else "plan-open-path",
        "step": {
            "step_id": "verify-desktop-result",
            "tool_name": "desktop.ui_elements",
            "capability_id": "desktop.app_discovery",
            "depends_on": (
                ["other-step"]
                if mutation == "wrong_source_dependency"
                else ["open-selected-discovered-app"]
            ),
            "approval_required": False,
            "execution_mode": {
                "mode": "read_only_observation",
                "keyboard_mouse_capture": False,
            },
        },
    }
    plan_events = [] if mutation == "no_plan_candidate" else [plan_event]
    if mutation == "duplicate_plan_candidate":
        plan_events.append(dict(plan_event))

    verifier = tool_execution_module._trusted_declared_exact_dispatch_verifier(
        "desktop.open_path_with_app",
        source_request,
        source_result,
        allowed_tools=["desktop.open_path_with_app", "desktop.ui_elements"],
        timeline=[contract_event, *plan_events],
    )

    if mutation == "trusted":
        assert verifier == {
            "tool": "desktop.ui_elements",
            "step_id": "verify-desktop-result",
            "capability_id": "desktop.app_discovery",
            "execution_mode": {
                "mode": "read_only_observation",
                "keyboard_mouse_capture": False,
            },
        }
    else:
        assert verifier == {}


def test_trusted_exact_dispatch_strips_provider_self_report_on_schema_mismatch() -> None:
    result = tool_execution_module._tool_result_with_trusted_exact_dispatch(
        "desktop.safe_scroll",
        {
            "input": {"direction": "down", "pages": 2},
            "plan_id": "plan-safe-scroll",
            "step_id": "operate-scroll",
            "request_id": "request-safe-scroll",
            "tool_call_id": "call-safe-scroll",
            "desktop_execution_route": {
                "selected_provider_kind": "background_desktop",
                "selected_provider_id": "provider-scroll",
            },
        },
        {
            "ok": True,
            "action": "desktop.safe_scroll",
            "postcondition_verified": True,
            "native_dispatch_verified": True,
            "verification_passed": True,
            "verified": True,
            "verified_observed_state": "fulfilled",
            "desktop_execution_provider_routed": True,
            "desktop_execution_provider": {
                "provider_kind": "background_desktop",
                "provider_id": "provider-scroll",
                "adapter_registered": True,
            },
            "data": {
                "direction": "down",
                "pages": True,
                "postcondition_verified": True,
                "native_dispatch_verified": True,
                "verified": True,
                "verified_observed_state": "fulfilled",
            },
        },
        run_id="run-safe-scroll",
    )

    assert result.get("postcondition_verified") is None
    assert result.get("native_dispatch_verified") is None
    assert result.get("verification_passed") is None
    assert result.get("verified") is None
    assert result.get("verified_observed_state") is None
    assert result["data"].get("postcondition_verified") is None
    assert result["data"].get("native_dispatch_verified") is None
    assert result["data"].get("verified") is None
    assert result["data"].get("verified_observed_state") is None
    assert result["data"]["pages"] is True
    assert "verification_provider_kind" not in result
    assert "verification_provider_id" not in result


def test_trusted_exact_dispatch_promotes_only_runtime_bound_exact_result() -> None:
    result = tool_execution_module._tool_result_with_trusted_exact_dispatch(
        "desktop.safe_click",
        {
            "input": {"x": 480, "y": 320, "click_count": 2},
            "plan_id": "plan-safe-click",
            "step_id": "operate-click",
            "request_id": "request-safe-click",
            "tool_call_id": "call-safe-click",
        },
        {
            "ok": True,
            "action": "desktop.safe_click",
            "desktop_execution_provider_routed": True,
            "desktop_execution_provider": {
                "provider_kind": "background_desktop",
                "provider_id": "provider-click",
                "adapter_registered": True,
            },
            "data": {
                "x": 480,
                "y": 320,
                "click_count": 2,
            },
        },
        run_id="run-safe-click",
    )

    assert result["postcondition_verified"] is True
    assert result["native_dispatch_verified"] is True
    assert result["verified_observed_state"] == "fulfilled"
    assert result["verification_provider_kind"] == "background_desktop"
    assert result["verification_provider_id"] == "provider-click"
    assert result["data"]["postcondition_verified"] is True
    assert result["data"]["native_dispatch_verified"] is True
    assert result["data"]["verified_observed_state"] == "fulfilled"


@pytest.mark.parametrize(
    ("action_tool", "open_target"),
    (
        ("desktop.open_path", "system_open"),
        ("desktop.reveal_path", "finder_reveal"),
    ),
)
def test_runner_projects_exact_path_dispatch_through_synthetic_verifier(
    action_tool: str,
    open_target: str,
) -> None:
    run_id = f"run-{action_tool.replace('.', '-')}"
    source_step_id = f"{action_tool.replace('.', '-')}--source"
    plan_id = f"plan-{action_tool.replace('.', '-')}"
    path = "Downloads/report.pdf"
    route = {
        "selected_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "selected_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "status": "provider_ready",
        "can_execute": True,
        "provider_execution_required": False,
        "foreground_takeover_allowed": True,
    }
    source_request = {
        "tool": action_tool,
        "input": {"path": path},
        "plan_id": plan_id,
        "step_id": source_step_id,
        "request_id": f"request-{source_step_id}",
        "tool_call_id": f"call-{source_step_id}",
        "runtime_stage": "operate",
        "requires_post_action_verification": True,
        "capability_id": "file.desktop_access",
        "desktop_execution_route": route,
    }
    contract = GoalContract(
        contract_id=f"goal-{action_tool.replace('.', '-')}",
        run_id=run_id,
        original_goal=f"Use {action_tool} for {path}",
        criteria=(
            GoalCriterion(
                criterion_id=f"criterion-{action_tool.replace('.', '-')}",
                description=f"Dispatch {action_tool} to the exact path",
                effectful=True,
                required_capabilities=("file.desktop_access",),
                expected={"state": "fulfilled"},
                source_step_ids=(source_step_id,),
                verifier_step_ids=(f"{source_step_id}:runtime-verify",),
            ),
        ),
    )
    broker = FakeBroker(
        {
            "ok": True,
            "action": action_tool,
            "state": "open",
            "data": {
                "path": path,
                "exists": True,
                "open_target": open_target,
            },
        }
    )
    executor = _executor(tool_call_events=FakeToolCallEvents())
    timeline: list[dict[str, Any]] = []

    _runner(call_agent_tool=executor.execute).run(
        [source_request],
        [action_tool],
        broker,
        [{"role": "user", "content": contract.original_goal}],
        timeline,
        [],
        next_iteration=1,
        run_id=run_id,
        budget=FakeBudget(),
    )

    assert [call[0] for call in broker.calls] == [action_tool]
    source_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == action_tool
    )
    assert source_event["result"]["native_dispatch_verified"] is True
    assert runtime_goal_assessment(contract, [source_event]).completed is False
    verifier_event = next(
        event
        for event in timeline
        if event.get("execution_mode")
        == "native_postcondition_receipt_projection"
    )
    assert verifier_event["source"] == "runtime_native_postcondition_receipt"
    assert verifier_event["source_step_id"] == source_step_id
    assert verifier_event["source_tool_call_id"] == source_request["tool_call_id"]
    assert verifier_event["plan_id"] == plan_id
    assert verifier_event["desktop_execution_route"] == route
    assert verifier_event["desktop_execution_route"] is not route
    assert verifier_event["result"]["source_tool"] == action_tool
    assert verifier_event["result"]["verified_observed_state"] == "fulfilled"
    assert runtime_goal_assessment(contract, timeline).completed is True


@pytest.mark.parametrize(
    ("action_tool", "open_target"),
    (
        ("desktop.open_path", "system_open"),
        ("desktop.reveal_path", "finder_reveal"),
    ),
)
def test_runner_does_not_project_mismatched_exact_path_dispatch(
    action_tool: str,
    open_target: str,
) -> None:
    source_step_id = f"{action_tool.replace('.', '-')}--source"
    source_request = {
        "tool": action_tool,
        "input": {"path": "Downloads/report.pdf"},
        "plan_id": f"plan-{source_step_id}",
        "step_id": source_step_id,
        "request_id": f"request-{source_step_id}",
        "tool_call_id": f"call-{source_step_id}",
        "runtime_stage": "operate",
        "requires_post_action_verification": True,
    }
    broker = FakeBroker(
        {
            "ok": True,
            "action": action_tool,
            "data": {
                "path": "Downloads/other.pdf",
                "exists": True,
                "open_target": open_target,
            },
        }
    )
    timeline: list[dict[str, Any]] = []

    _runner(
        call_agent_tool=_executor(
            tool_call_events=FakeToolCallEvents()
        ).execute
    ).run(
        [source_request],
        [action_tool],
        broker,
        [{"role": "user", "content": "Open the exact report path"}],
        timeline,
        [],
        next_iteration=1,
        run_id=f"run-{source_step_id}",
        budget=FakeBudget(),
    )

    source_event = next(
        event
        for event in timeline
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == action_tool
    )
    assert source_event["result"].get("native_dispatch_verified") is None
    assert not any(
        event.get("source") == "runtime_native_postcondition_receipt"
        for event in timeline
    )


@pytest.mark.parametrize(
    "action_tool",
    ("desktop.open_path", "desktop.reveal_path"),
)
@pytest.mark.parametrize(
    "mutation",
    ("provider_self_report", "wrong_path", "missing_identity", "wrong_provider"),
)
def test_exact_path_native_receipt_fulfilled_state_requires_trusted_promotion(
    action_tool: str,
    mutation: str,
) -> None:
    open_target = (
        "system_open" if action_tool == "desktop.open_path" else "finder_reveal"
    )
    source_event = {
        "event": "agent.tool.call",
        "detail": action_tool,
        "run_id": "run-exact-path",
        "plan_id": "plan-exact-path",
        "step_id": "operate-exact-path",
        "request_id": "request-exact-path",
        "tool_call_id": "call-exact-path",
        "input_preview": {"path": "Downloads/report.pdf"},
        "result": {
            "ok": True,
            "action": action_tool,
            "state": "open",
            "postcondition_verified": True,
            "native_dispatch_verified": True,
            "verified_observed_state": "fulfilled",
            "verification_provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
            "verification_provider_id": LOCAL_DESKTOP_PROVIDER_ID,
            "data": {
                "path": "Downloads/report.pdf",
                "exists": True,
                "open_target": open_target,
            },
            **_local_provider_context(),
        },
    }
    if mutation == "provider_self_report":
        source_event["result"].pop("verification_provider_kind")
        source_event["result"].pop("verification_provider_id")
    elif mutation == "wrong_path":
        source_event["result"]["data"]["path"] = "Downloads/other.pdf"
    elif mutation == "missing_identity":
        source_event.pop("request_id")
    elif mutation == "wrong_provider":
        source_event["result"]["verification_provider_id"] = "other-provider"

    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.verify",
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "run_id": "run-exact-path",
            "plan_id": "plan-exact-path",
            "step_id": "verify-exact-path",
            "source_step_id": "operate-exact-path",
            "source_request_id": "request-exact-path",
            "source_tool_call_id": "call-exact-path",
            "depends_on": ["operate-exact-path"],
        },
        [source_event],
        tool_timeline_start=0,
    )

    assert receipt.get("verified_observed_state") is None


def test_search_submit_native_receipt_preserves_submitted_goal_state() -> None:
    source_step_id = "submit-app-search"
    source_request = {
        "tool": "desktop.search_submit",
        "input": {},
        "plan_id": "plan-app-search",
        "step_id": source_step_id,
        "request_id": "request-app-search",
        "tool_call_id": "call-app-search",
        "runtime_stage": "operate",
        "runtime_role": "submit_ui",
        "requires_post_action_verification": True,
        "capability_id": "desktop.ui_operation",
        "action_target": {
            "kind": "desktop_ui",
            "action": "submit_ui",
        },
    }
    contract = GoalContract(
        contract_id="goal-app-search",
        run_id="run-app-search",
        original_goal="Submit the current app search",
        criteria=(
            GoalCriterion(
                criterion_id="criterion-app-search",
                description="The app search is submitted",
                effectful=True,
                required_capabilities=("desktop.ui_operation",),
                expected={
                    "state": "submitted",
                    "target": {"kind": "desktop_ui", "action": "submit_ui"},
                },
                source_step_ids=(source_step_id,),
                verifier_step_ids=(f"{source_step_id}:runtime-verify",),
            ),
        ),
    )
    broker = FakeBroker(
        {
            "ok": True,
            "action": "desktop.search_submit",
            "state": "submitted",
            "data": {
                "key": "return",
                "modifiers": [],
                "submitted": True,
            },
        }
    )
    timeline: list[dict[str, Any]] = []

    _runner(
        call_agent_tool=_executor(tool_call_events=FakeToolCallEvents()).execute
    ).run(
        [source_request],
        ["desktop.search_submit"],
        broker,
        [{"role": "user", "content": contract.original_goal}],
        timeline,
        [],
        next_iteration=1,
        run_id=contract.run_id,
        budget=FakeBudget(),
    )

    assert [call[0] for call in broker.calls] == ["desktop.search_submit"]
    verifier_event = next(
        event
        for event in timeline
        if event.get("execution_mode")
        == "native_postcondition_receipt_projection"
    )
    assert verifier_event["result"].get("verified_observed_state") is None
    assert runtime_goal_assessment(contract, timeline).completed is True


@pytest.mark.parametrize(
    ("action_tool", "verifier_tool", "verifier_input", "result"),
    [
        pytest.param(
            "browser.click",
            "desktop.active_window",
            {},
            {"ok": True, "data": {"selector": "#result", "tag": "A"}},
            id="browser-rejects-desktop-family",
        ),
        pytest.param(
            "app.open",
            "browser.current_page",
            {},
            {"ok": True, "data": {"app_name": "Notes", "launch_verified": True}},
            id="desktop-rejects-browser-family",
        ),
        pytest.param(
            "browser.click",
            "browser.type_text",
            {"selector": "#search", "text": "mutation"},
            {"ok": True, "data": {"selector": "#result", "tag": "A"}},
            id="browser-rejects-effectful-verifier",
        ),
        pytest.param(
            "system.volume",
            "system.volume",
            {"action": "set", "level": 90},
            {
                "ok": True,
                "data": {"requested_action": "set", "level": 30, "muted": False},
            },
            id="system-rejects-mutating-verifier-mode",
        ),
    ],
)
def test_native_receipt_rejects_wrong_family_or_effectful_verifier(
    action_tool: str,
    verifier_tool: str,
    verifier_input: dict[str, Any],
    result: dict[str, Any],
) -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": verifier_tool,
            "input": verifier_input,
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "source_step_id": "operate",
            "depends_on": ["operate"],
            "source_request_id": "request-action",
            "source_tool_call_id": "call-action",
        },
        [
            {
                "event": "agent.tool.call",
                "detail": action_tool,
                "step_id": "operate",
                "request_id": "request-action",
                "tool_call_id": "call-action",
                "result": result,
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


def test_native_receipt_source_tool_call_id_cannot_fallback_to_request_id() -> None:
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "desktop.active_window",
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "source_step_id": "open-app",
            "depends_on": ["open-app"],
            "source_request_id": "request-open",
            "source_tool_call_id": "call-current",
        },
        [
            {
                "event": "agent.tool.call",
                "detail": "app.open",
                "step_id": "open-app",
                "request_id": "request-open",
                "tool_call_id": "call-prior",
                "result": {
                    "ok": True,
                    "data": {"app_name": "Notes", "launch_verified": True},
                },
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


@pytest.mark.parametrize("observed_value", (None, "other", "hello"))
def test_browser_type_mutation_echo_never_replaces_current_page_observation(
    observed_value: str | None,
) -> None:
    data: dict[str, Any] = {
        "selector": "#search",
        "tag": "INPUT",
        "length": 5,
    }
    if observed_value is not None:
        data["value"] = observed_value
    receipt = tool_execution_module._native_postcondition_receipt_for_verifier(
        {
            "tool": "browser.current_page",
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "source_step_id": "type-query",
            "depends_on": ["type-query"],
            "source_tool_call_id": "call-type-query",
        },
        [
            {
                "event": "agent.tool.call",
                "detail": "browser.type_text",
                "step_id": "type-query",
                "tool_call_id": "call-type-query",
                "input_preview": {"selector": "#search", "text": "hello"},
                "result": {"ok": True, "data": data},
            }
        ],
        tool_timeline_start=0,
    )

    assert receipt == {}


@pytest.mark.parametrize(
    ("action_tool", "action_input", "action_result"),
    [
        (
            "browser.click",
            {"selector": "#result"},
            {"ok": True, "data": {"selector": "#result", "tag": "A"}},
        ),
        (
            "browser.type_text",
            {"selector": "#search", "text": "hello"},
            {
                "ok": True,
                "data": {
                    "selector": "#search",
                    "tag": "INPUT",
                    "length": 5,
                    "value": "hello",
                },
            },
        ),
    ],
)
def test_runner_executes_current_page_without_atomic_browser_receipt(
    action_tool: str,
    action_input: dict[str, Any],
    action_result: dict[str, Any],
) -> None:
    executed: list[str] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        current_timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        executed.append(tool_name)
        result = (
            action_result
            if tool_name == action_tool
            else {
                "ok": True,
                "action": "browser.current_page",
                "data": {
                    "url": "https://example.test/result",
                    "title": "Result",
                    "value": "different",
                },
            }
        )
        current_timeline.append(
            {
                "event": "agent.tool.call",
                "detail": tool_name,
                "step_id": tool_request.get("step_id"),
                "request_id": tool_request.get("request_id"),
                "tool_call_id": tool_request.get("tool_call_id"),
                "input_preview": dict(tool_request.get("input") or {}),
                "result": result,
            }
        )
        return result

    _runner(call_agent_tool=call_agent_tool).run(
        [
            {
                "tool": action_tool,
                "input": action_input,
                "step_id": "browser-action",
                "request_id": "request-browser-action",
                "tool_call_id": "call-browser-action",
            },
            {
                "tool": "browser.current_page",
                "input": {},
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "step_id": "verify-browser-action",
                "source_step_id": "browser-action",
                "depends_on": ["browser-action"],
                "source_request_id": "request-browser-action",
                "source_tool_call_id": "call-browser-action",
            },
        ],
        [action_tool, "browser.current_page"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Click the result and verify the page"}],
        timeline,
        [],
        next_iteration=1,
        budget=FakeBudget(),
    )

    assert executed == [action_tool, "browser.current_page"]
    assert not any(
        event.get("event") == "agent.post_action_verification.satisfied"
        for event in timeline
    )


def test_native_receipt_projection_uses_canonical_source_after_trace_merge() -> None:
    executed: list[str] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        executed.append(str(tool_request.get("tool") or ""))
        return {"ok": True}

    timeline: list[dict[str, Any]] = [
        {
            **_runtime_intrinsic_action_event(
                "app.open",
                {"app_name": "Notes"},
                {"ok": True},
                run_id="run-canonical-source",
                plan_id="plan-1",
                step_id="open-app",
                request_id="request-open-notes",
                tool_call_id="call-open-notes",
            ),
            "source": "runtime_planner",
        }
    ]
    messages = [
        assistant_message_for_history(
            {
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-verify-notes",
                        "function": {
                            "name": "desktop.active_window",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        )
    ]
    stage_tool_result_messages(messages)
    _runner(call_agent_tool=call_agent_tool).run(
        [
            {
                "protocol": "tool_calls",
                "tool_call_id": "call-verify-notes",
                "tool": "desktop.active_window",
                "input": {},
                "source": "runtime_post_action_auto_verify",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "depends_on": ["open-app"],
                "step_id": "verify-app",
                "request_id": "request-verify-notes",
                "plan_id": "plan-1",
                "source_step_id": "open-app",
                "source_request_id": "request-open-notes",
                "source_tool_call_id": "call-open-notes",
            }
        ],
        ["desktop.active_window"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-canonical-source",
        budget=FakeBudget(),
    )

    assert executed == []
    satisfied = next(
        event
        for event in timeline
        if event["event"] == "agent.post_action_verification.satisfied"
    )
    projected = next(
        event
        for event in timeline
        if event.get("execution_mode") == "native_postcondition_receipt_projection"
    )
    assert satisfied["source"] == "runtime_native_postcondition_receipt"
    assert projected["source"] == "runtime_native_postcondition_receipt"
    assert json.loads(messages[1]["content"])["verification_satisfied_by_native_receipt"] is True


@pytest.mark.parametrize(
    ("action_tool", "verifier_tool", "result"),
    [
        (
            "system.volume",
            "system.volume",
            {
                "ok": True,
                "action": "system.volume",
                "data": {
                    "requested_action": "set",
                    "level": 30,
                    "muted": False,
                },
            },
        ),
        (
            "desktop.show_all_apps",
            "desktop.verify",
            {
                "ok": True,
                "action": "desktop.show_all_apps",
                "data": {"shown_app_count": 2},
            },
        ),
    ],
)
def test_runner_repeated_intrinsic_receipts_stay_in_current_run_and_plan(
    action_tool: str,
    verifier_tool: str,
    result: dict[str, Any],
) -> None:
    executed: list[tuple[str, str, str]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        current_timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        executed.append(
            (
                tool_name,
                str(tool_request.get("run_id") or ""),
                str(tool_request.get("plan_id") or ""),
            )
        )
        action_result = dict(result)
        request_input = (
            tool_request.get("input")
            if isinstance(tool_request.get("input"), dict)
            else {}
        )
        if tool_name == "system.volume":
            action_result = {
                **action_result,
                "data": (
                    {"level": 30, "muted": False}
                    if request_input.get("action") == "status"
                    else dict(result.get("data") or {})
                ),
                **_local_provider_context(),
            }
        current_timeline.append(
            {
                "event": "agent.tool.call",
                "detail": tool_name,
                "run_id": tool_request.get("run_id"),
                "decision_id": tool_request.get("decision_id"),
                "plan_id": tool_request.get("plan_id"),
                "step_id": tool_request.get("step_id"),
                "tool_call_id": tool_request.get("tool_call_id"),
                "input_preview": dict(tool_request.get("input") or {}),
                "result": action_result,
            }
        )
        return action_result

    timeline: list[dict[str, Any]] = []
    runner = _runner(call_agent_tool=call_agent_tool)
    for attempt in (1, 2):
        run_id = f"run-{attempt}"
        plan_id = f"plan-{attempt}"
        action_step_id = (
            "control-system-state"
            if action_tool == "system.volume"
            else "manage-foreground"
        )
        verify_step_id = (
            "verify-system-state"
            if action_tool == "system.volume"
            else "verify-desktop-result"
        )
        action_input = (
            {"action": "set", "level": 30}
            if action_tool == "system.volume"
            else {}
        )
        verifier_input = {"action": "status"} if verifier_tool == "system.volume" else {}
        runner.run(
            [
                {
                    "tool": action_tool,
                    "input": action_input,
                    "run_id": run_id,
                    "decision_id": f"decision-{attempt}",
                    "plan_id": plan_id,
                    "step_id": action_step_id,
                    "planner_step_id": action_step_id,
                },
                {
                    "tool": verifier_tool,
                    "input": verifier_input,
                    "source": "runtime_verification",
                    "runtime_stage": "verify",
                    "runtime_role": "verify_result",
                    "requires_observation": True,
                    "requires_post_action_verification": False,
                    "run_id": run_id,
                    "decision_id": f"decision-{attempt}",
                    "plan_id": plan_id,
                    "step_id": verify_step_id,
                    "planner_step_id": verify_step_id,
                    "source_step_id": action_step_id,
                    "depends_on": [action_step_id],
                    "verification_targets": [{"step_id": action_step_id}],
                    "task_verification_targets": [{"step_id": action_step_id}],
                },
            ],
            [action_tool, verifier_tool],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "repeat deterministic desktop action"}],
            timeline,
            [],
            next_iteration=1,
            run_id=run_id,
            budget=FakeBudget(),
        )

    assert executed == [
        call
        for attempt in (1, 2)
        for call in (
            [
                (action_tool, f"run-{attempt}", f"plan-{attempt}"),
                (verifier_tool, f"run-{attempt}", f"plan-{attempt}"),
            ]
            if verifier_tool == "system.volume"
            else [(action_tool, f"run-{attempt}", f"plan-{attempt}")]
        )
    ]
    satisfied = [
        event
        for event in timeline
        if event.get("event") == "agent.post_action_verification.satisfied"
    ]
    assert [event.get("run_id") for event in satisfied] == ["run-1", "run-2"]
    assert [event.get("plan_id") for event in satisfied] == ["plan-1", "plan-2"]
    assert all(
        event.get("result", {}).get("source_tool") == action_tool
        for event in satisfied
    )


def test_runtime_tool_request_runner_enqueues_post_action_verification() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在隔离桌面打开 PixelForge"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_requests.append(tool_request)
        if tool_request.get("tool") == "app.open":
            return {
                "ok": True,
                "tool": "app.open",
                "data": {"app_name": "PixelForge"},
            }
        return {
            "ok": True,
            "tool": tool_request.get("tool"),
            "data": {"app_name": "PixelForge"},
        }

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "PixelForge"},
                "step_id": "open-app",
                "planner_step_id": "open-app",
                "runtime_stage": "operate",
                "runtime_role": "prepare_target_app",
                "requires_post_action_verification": True,
                "task_todo": {
                    "todo_id": "todo-open-app",
                    "title": "Open PixelForge",
                    "status": "pending",
                    "step_id": "open-app",
                },
                "task_checkpoints": [
                    {
                        "checkpoint_id": "checkpoint-open-app",
                        "title": "Verify PixelForge opened",
                        "status": "planned",
                        "after_step_id": "open-app",
                    }
                ],
                "action_target": {
                    "kind": "desktop_app",
                    "action": "open_app",
                    "app_name": "PixelForge",
                },
                "desktop_execution_policy": {
                    "mode": "preview_input",
                    "prefer_isolated_desktop": True,
                    "avoid_user_foreground_takeover": True,
                },
                "desktop_provider_session": {
                    "running": True,
                    "started": True,
                    "status": "running",
                    "provider_id": "sandbox-1",
                    "url": "http://127.0.0.1:19093",
                    "tool_names": ["app.open", "desktop.active_window"],
                    "command": ["python", "scripts/run_isolated_desktop_provider.py"],
                    "env": {"OHA_YACHIYO_DESKTOP_PROVIDER_TOKEN": "secret"},
                },
            }
        ],
        ["app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert [request["tool"] for request in captured_requests] == [
        "app.open",
        "desktop.active_window",
    ]
    verify_request = captured_requests[1]
    assert verify_request["source"] == "runtime_post_action_auto_verify"
    assert verify_request["planning_reason"] == "runtime_post_action_auto_verify"
    assert verify_request["runtime_stage"] == "verify"
    assert verify_request["depends_on"] == ["open-app"]
    assert verify_request["verification_target"] == {
        "app_name": "PixelForge",
        "source_tool": "app.open",
    }
    assert verify_request["task_verification_targets"][0]["step_id"] == "open-app"
    assert verify_request["task_verification_targets"][0]["todo"]["todo_id"] == (
        "todo-open-app"
    )
    assert verify_request["desktop_provider_session"]["provider_id"] == "sandbox-1"
    enqueued = next(
        event
        for event in timeline
        if event["event"] == "agent.post_action_verification.enqueued"
    )
    assert enqueued["verification_tool"] == "desktop.active_window"
    assert enqueued["desktop_provider_session"]["provider_id"] == "sandbox-1"
    assert "command" not in enqueued["desktop_provider_session"]
    assert "env" not in enqueued["desktop_provider_session"]


def test_runtime_auto_verifier_keeps_stateless_background_provider_route() -> None:
    class StatelessBackgroundProvider:
        provider_kind = "background_desktop"
        provider_id = "stateless-background-1"

        def __init__(self) -> None:
            self.calls: list[dict[str, Any]] = []

        def can_execute(
            self,
            tool_name: str,
            route: dict[str, Any],
            tool_request: dict[str, Any],
        ) -> bool:
            del tool_request
            return bool(
                tool_name in {"app.open", "desktop.active_window"}
                and route.get("selected_provider_id") == self.provider_id
            )

        def execute(
            self,
            tool_name: str,
            payload: dict[str, Any],
            *,
            tool_request: dict[str, Any],
            route: dict[str, Any],
            broker: Any,
            approved: bool = False,
        ) -> dict[str, Any]:
            del tool_request, broker, approved
            self.calls.append(
                {
                    "tool": tool_name,
                    "payload": dict(payload),
                    "route": dict(route),
                }
            )
            return {
                "ok": True,
                "tool": tool_name,
                "action": tool_name,
                "data": {"app_name": "Notes"},
            }

    route = {
        "tool_name": "app.open",
        "selected_provider_kind": "background_desktop",
        "selected_provider_id": "stateless-background-1",
        "status": "provider_ready",
        "can_execute": True,
        "provider_execution_required": True,
        "foreground_takeover_allowed": False,
    }
    provider = StatelessBackgroundProvider()
    broker = FakeBroker({"ok": True, "unexpected_local_execution": True})
    executor = _executor(
        tool_call_events=FakeToolCallEvents(),
        desktop_provider_registry=DesktopExecutionProviderRegistry([provider]),
    )

    _runner(call_agent_tool=executor.execute).run(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "Notes"},
                "step_id": "open-notes",
                "requires_post_action_verification": True,
                "desktop_execution_route": route,
            }
        ],
        ["app.open", "desktop.active_window"],
        broker,
        [{"role": "user", "content": "Open Notes in the background desktop"}],
        [],
        [],
        next_iteration=2,
        run_id="run-stateless-background-auto-verify",
        budget=FakeBudget(),
    )

    assert [call["tool"] for call in provider.calls] == [
        "app.open",
        "desktop.active_window",
    ]
    assert provider.calls[1]["route"]["selected_provider_id"] == provider.provider_id
    assert broker.calls == []


def test_runtime_tool_request_runner_reuses_deferred_ui_observation_for_verification() -> None:
    budget = FakeBudget()
    captured_requests: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_requests.append(tool_request)
        if tool_request["tool"] == "app.open":
            return {"ok": True, "data": {"app_name": "PixelForge"}}
        return {
            "ok": True,
            "data": {
                "app_name": "PixelForge",
                "count": 1,
                "elements": [{"role": "AXButton", "name": "Export"}],
            },
        }

    _runner(call_agent_tool=call_agent_tool).run(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "PixelForge"},
                "step_id": "open-app",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.ui_elements",
                "input": {"app_name": "PixelForge"},
                "depends_on": ["open-app"],
                "continue_to_model": True,
                "deferred_tool": "desktop.click_ui_element",
                "requires_observation": True,
            },
        ],
        ["app.open", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "打开 PixelForge 并点击 Export"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-reuse-observation",
        budget=budget,
    )

    assert [request["tool"] for request in captured_requests] == [
        "app.open",
        "desktop.ui_elements",
    ]
    assert not any(
        event.get("event") == "agent.post_action_verification.enqueued"
        for event in timeline
    )


def test_content_mutation_requires_correlated_semantic_ui_verification() -> None:
    assert tool_execution_module._post_action_verification_tool(
        "app.focus_and_safe_type_text",
        allowed_tools=["desktop.active_window", "desktop.ui_elements"],
    ) == "desktop.ui_elements"
    assert tool_execution_module._post_action_verification_tool(
        "desktop.search_submit",
        allowed_tools=["desktop.ui_elements"],
    ) == "desktop.ui_elements"
    assert tool_execution_module._remaining_requests_include_post_action_verification(
        [
            {
                "tool": "desktop.ui_elements",
                "continue_to_model": True,
                "requires_observation": True,
                "depends_on": ["send-message"],
            }
        ],
        source_tool_name="desktop.safe_type_text",
        allowed_tools=["desktop.ui_elements"],
        source_step_id="draft-message",
    ) is False
    assert tool_execution_module._remaining_requests_include_post_action_verification(
        [
            {
                "tool": "desktop.ui_elements",
                "continue_to_model": True,
                "requires_observation": True,
                "depends_on": ["draft-message"],
            }
        ],
        source_tool_name="desktop.safe_type_text",
        allowed_tools=["desktop.ui_elements"],
        source_step_id="draft-message",
    ) is True


@pytest.mark.parametrize(
    ("action_tool", "action_input", "allowed_tools", "verification_tool"),
    [
        (
            "browser.click",
            {"selector": "#first-result"},
            ["browser.current_page"],
            "browser.current_page",
        ),
        (
            "browser.type_text",
            {"selector": "#search", "text": "yachiyo"},
            ["browser.current_page"],
            "browser.current_page",
        ),
        (
            "app.focus_and_click_ui_element",
            {"app_name": "Notes", "target": "Export"},
            ["desktop.ui_elements"],
            "desktop.ui_elements",
        ),
        (
            "app.open_and_click_ui_element",
            {"app_name": "Notes", "target": "Export"},
            ["desktop.read_ui"],
            "desktop.read_ui",
        ),
        (
            "app.focus_and_type_into_ui_element",
            {"app_name": "Notes", "target": "Body", "text": "hello"},
            ["desktop.ui_elements"],
            "desktop.ui_elements",
        ),
        (
            "app.open_and_type_into_ui_element",
            {"app_name": "Notes", "target": "Body", "text": "hello"},
            ["desktop.read_ui"],
            "desktop.read_ui",
        ),
    ],
)
def test_explicit_post_action_contract_builds_capability_scoped_verifier(
    action_tool: str,
    action_input: dict[str, Any],
    allowed_tools: list[str],
    verification_tool: str,
) -> None:
    tool_result: dict[str, Any] = {"ok": True, "action": action_tool}
    if action_tool.startswith("app."):
        tool_result["data"] = {"app_name": action_input["app_name"]}
    request = tool_execution_module._post_action_verification_request(
        action_tool,
        {
            "tool": action_tool,
            "input": action_input,
            "decision_id": "decision-approved-action",
            "plan_id": "plan-approved-action",
            "step_id": "approved-action",
            "request_id": "request-approved-action",
            "tool_call_id": "tool-call-approved-action",
            "approval_id": "approval-approved-action",
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        tool_result,
        allowed_tools=allowed_tools,
        remaining_requests=[],
        active_window_target=None,
    )

    assert request["tool"] == verification_tool
    assert request["approval_required"] is False
    assert request["runtime_stage"] == "verify"
    assert request["runtime_role"] == "verify_result"
    assert request["requires_post_action_verification"] is False
    assert request["decision_id"] == "decision-approved-action"
    assert request["plan_id"] == "plan-approved-action"
    assert request["step_id"] == "approved-action:runtime-verify"
    assert request["source_step_id"] == "approved-action"
    assert request["source_request_id"] == "request-approved-action"
    assert request["source_tool_call_id"] == "tool-call-approved-action"
    assert request["source_approval_id"] == "approval-approved-action"
    assert request["depends_on"] == ["approved-action"]
    assert "tool_call_id" not in request
    assert "approval_id" not in request


def test_approval_resume_post_action_verifier_defensively_copies_provider_route() -> None:
    route = {
        "selected_provider_kind": "background_desktop",
        "selected_provider_id": "approved-background-1",
        "status": "provider_ready",
        "can_execute": True,
        "provider_execution_required": True,
        "foreground_takeover_allowed": False,
    }
    source_request = {
        "tool": "app.open",
        "input": {"app_name": "Notes"},
        "step_id": "approved-open-notes",
        "approval_id": "approval-open-notes",
        "runtime_stage": "operate",
        "requires_post_action_verification": True,
        "desktop_execution_route": route,
    }

    verifier = tool_execution_module._post_action_verification_request(
        "app.open",
        source_request,
        {"ok": True, "action": "app.open", "data": {"app_name": "Notes"}},
        allowed_tools=["desktop.active_window"],
        remaining_requests=[],
        active_window_target=None,
    )

    assert verifier["source_approval_id"] == "approval-open-notes"
    assert verifier["desktop_execution_route"] == route
    assert verifier["desktop_execution_route"] is not route
    verifier["desktop_execution_route"]["selected_provider_id"] = "mutated"
    assert route["selected_provider_id"] == "approved-background-1"


def test_exact_grounded_type_can_use_private_verify_without_trusting_safe_type() -> None:
    allowed_tools = ["desktop.verify", "desktop.ui_elements", "desktop.read_ui"]

    assert tool_execution_module._post_action_verification_tools(
        "desktop.type_into_ui_element",
        allowed_tools=allowed_tools,
    ) == ("desktop.verify", "desktop.ui_elements", "desktop.read_ui")
    assert tool_execution_module._post_action_verification_tools(
        "app.open_and_type_into_ui_element",
        allowed_tools=allowed_tools,
    ) == ("desktop.verify", "desktop.ui_elements", "desktop.read_ui")
    assert tool_execution_module._post_action_verification_tools(
        "desktop.safe_type_text",
        allowed_tools=allowed_tools,
    ) == ("desktop.ui_elements", "desktop.read_ui")


@pytest.mark.parametrize(
    ("action_tool", "allowed_tools"),
    [
        ("network.fetch", ["browser.current_page", "desktop.ui_elements"]),
        ("browser.click", ["desktop.ui_elements"]),
        ("app.focus_and_click_ui_element", ["browser.current_page"]),
        ("app.focus_and_click_ui_element", ["desktop.active_window"]),
    ],
)
def test_explicit_post_action_contract_rejects_unsupported_verifier_capability(
    action_tool: str,
    allowed_tools: list[str],
) -> None:
    request = tool_execution_module._post_action_verification_request(
        action_tool,
        {
            "tool": action_tool,
            "input": {},
            "step_id": "unsupported-action",
            "requires_post_action_verification": True,
        },
        {"ok": True, "action": action_tool},
        allowed_tools=allowed_tools,
        remaining_requests=[],
        active_window_target=None,
    )

    assert request == {}


def test_app_post_action_verifier_prefers_correlated_resolved_result_app_name() -> None:
    request = tool_execution_module._post_action_verification_request(
        "app.focus_and_click_ui_element",
        {
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "微信",
                "selection_source": "desktop.list_apps",
                "query": "微信",
                "target": "第一个结果",
            },
            "decision_id": "decision-wechat",
            "plan_id": "plan-wechat",
            "step_id": "click-first-result",
            "request_id": "request-click-first-result",
            "tool_call_id": "tool-call-click-first-result",
            "approval_id": "approval-click-first-result",
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        {
            "ok": True,
            "action": "app.focus_and_click_ui_element",
            "data": {
                "app_name": "微信",
                "focus_result": {
                    "ok": True,
                    "data": {
                        "app_name": "WeChat",
                        "focus_verified": True,
                    },
                },
            },
        },
        allowed_tools=["desktop.ui_elements"],
        remaining_requests=[],
        active_window_target={"app_name": "微信"},
    )

    assert request["input"] == {"app_name": "WeChat"}
    assert request["verification_target"] == {
        "app_name": "WeChat",
        "source_tool": "app.focus_and_click_ui_element",
    }
    assert request["desktop_loop"]["retry_input"] == {"app_name": "WeChat"}
    assert "selection_source" not in request["input"]
    assert "query" not in request["input"]
    assert request["source_request_id"] == "request-click-first-result"
    assert request["source_tool_call_id"] == "tool-call-click-first-result"
    assert request["source_approval_id"] == "approval-click-first-result"


@pytest.mark.parametrize(
    "tool_result",
    [
        {
            "ok": True,
            "action": "app.focus_and_click_ui_element",
            "data": {
                "app_name": "WeChat",
                "focus_result": {
                    "ok": True,
                    "data": {"app_name": "Slack", "focus_verified": True},
                },
            },
        },
        {
            "ok": True,
            "action": "browser.click",
            "data": {"app_name": "WeChat"},
        },
        {
            "ok": True,
            "action": "app.focus_and_click_ui_element",
            "data": {},
        },
    ],
    ids=["conflicting-apps", "wrong-result-action", "missing-result-app"],
)
def test_app_post_action_verifier_fails_closed_on_untrusted_result_app_identity(
    tool_result: dict[str, Any],
) -> None:
    request = tool_execution_module._post_action_verification_request(
        "app.focus_and_click_ui_element",
        {
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "微信",
                "selection_source": "desktop.list_apps",
                "query": "微信",
                "target": "第一个结果",
            },
            "step_id": "click-first-result",
            "requires_post_action_verification": True,
        },
        tool_result,
        allowed_tools=["desktop.ui_elements"],
        remaining_requests=[],
        active_window_target={"app_name": "微信"},
    )

    assert request == {}


def test_non_app_post_action_verifier_does_not_require_app_identity() -> None:
    request = tool_execution_module._post_action_verification_request(
        "browser.click",
        {
            "tool": "browser.click",
            "input": {"selector": "#first-result"},
            "plan_id": "plan-browser",
            "step_id": "click-browser-result",
            "request_id": "request-browser-result",
            "requires_post_action_verification": True,
        },
        {
            "ok": True,
            "action": "browser.click",
            "data": {"selector": "#first-result", "tag": "A"},
        },
        allowed_tools=["browser.current_page"],
        remaining_requests=[],
        active_window_target=None,
    )

    assert request["tool"] == "browser.current_page"
    assert request["input"] == {}
    assert request["plan_id"] == "plan-browser"
    assert request["source_request_id"] == "request-browser-result"


def test_runtime_tool_request_runner_does_not_enqueue_desktop_verification_for_structured_tools() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "分析 sales.csv"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        captured_requests.append(tool_request)
        return {
            "ok": True,
            "tool": tool_request.get("tool"),
            "rows": 3,
            "columns": 3,
            "artifact_path": "analysis-report.md",
        }

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {
                    "path": "sales.csv",
                    "artifact_path": "analysis-report.md",
                },
                "step_id": "analyze-data-file",
                "planner_step_id": "analyze-data-file",
                "runtime_stage": "operate",
                "runtime_role": "analyze_data",
                "requires_post_action_verification": True,
            }
        ],
        ["data.analyze", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-data-analysis",
        budget=budget,
    )

    assert [request["tool"] for request in captured_requests] == ["data.analyze"]
    assert not any(
        event["event"] == "agent.post_action_verification.enqueued"
        for event in timeline
    )


def test_runtime_tool_request_runner_does_not_duplicate_planned_verification() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "打开 PixelForge 并验证"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda tool_request, *_args, **_kwargs: captured_requests.append(
            tool_request
        )
        or {"ok": True, "tool": tool_request.get("tool"), "data": {"app_name": "PixelForge"}},
    )

    runner.run(
        [
            {
                "tool": "app.open",
                "input": {"app_name": "PixelForge"},
                "step_id": "open-app",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
                "desktop_execution_policy": {"mode": "allow"},
            },
            {
                "tool": "desktop.active_window",
                "input": {},
                "runtime_stage": "verify",
                "depends_on": ["open-app"],
                "task_verification_targets": [{"step_id": "open-app"}],
            },
        ],
        ["app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert [request["tool"] for request in captured_requests] == [
        "app.open",
        "desktop.active_window",
    ]
    assert not [
        event
        for event in timeline
        if event["event"] == "agent.post_action_verification.enqueued"
    ]


def test_runtime_prefers_and_binds_planned_desktop_verifier_lineage() -> None:
    planned_verifier = {
        "tool": "desktop.verify",
        "input": {"app_name": "PixelForge", "verification_goal": "app_running"},
        "step_id": "verify-desktop-result",
        "planner_step_id": "verify-desktop-result",
        "plan_id": "plan-open-app",
        "tool_plan_id": "tool-plan-open-app",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "depends_on": ["open-or-focus-app"],
        "task_verification_targets": [{"step_id": "open-or-focus-app"}],
    }

    inserted = tool_execution_module._post_action_verification_request(
        "app.open",
        {
            "tool": "app.open",
            "input": {"app_name": "PixelForge"},
            "request_id": "request-open-app",
            "tool_call_id": "call-open-app",
            "step_id": "open-or-focus-app",
            "planner_step_id": "open-or-focus-app",
            "plan_id": "plan-open-app",
            "tool_plan_id": "tool-plan-open-app",
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        {
            "ok": True,
            "action": "app.open",
            "data": {
                "app_name": "PixelForge",
                "launch_verified": True,
                "launch_status": "running",
            },
        },
        allowed_tools=["desktop.active_window", "desktop.verify"],
        remaining_requests=[planned_verifier],
        active_window_target={"app_name": "PixelForge"},
    )

    assert inserted == {}
    assert planned_verifier["step_id"] == "verify-desktop-result"
    assert planned_verifier["planner_step_id"] == "verify-desktop-result"
    assert planned_verifier["source_step_id"] == "open-or-focus-app"
    assert planned_verifier["source_request_id"] == "request-open-app"
    assert planned_verifier["source_tool_call_id"] == "call-open-app"
    assert planned_verifier["plan_id"] == "plan-open-app"
    assert planned_verifier["tool_plan_id"] == "tool-plan-open-app"
    assert planned_verifier["verification_predicate_kind"] == "app_window_present"


def test_runtime_upgrades_insufficient_declared_observer_without_losing_step_identity(
) -> None:
    planned_verifier = {
        "tool": "desktop.running_apps",
        "input": {},
        "step_id": "verify-desktop-result",
        "planner_step_id": "verify-desktop-result",
        "plan_id": "plan-show-app",
        "tool_plan_id": "tool-plan-show-app",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "depends_on": ["manage-app"],
        "task_verification_targets": [{"step_id": "manage-app"}],
    }

    inserted = tool_execution_module._post_action_verification_request(
        "app.show",
        {
            "tool": "app.show",
            "input": {"app_name": "Slack"},
            "request_id": "request-show-app",
            "tool_call_id": "call-show-app",
            "step_id": "manage-app",
            "planner_step_id": "manage-app",
            "plan_id": "plan-show-app",
            "tool_plan_id": "tool-plan-show-app",
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        {
            "ok": True,
            "action": "app.show",
            "data": {"app_name": "Slack", "show_status": "shown"},
        },
        allowed_tools=["app.show", "desktop.ui_elements", "desktop.running_apps"],
        remaining_requests=[planned_verifier],
        active_window_target={"app_name": "Slack"},
    )

    assert inserted == {}
    assert planned_verifier["planner_verifier_tool"] == "desktop.running_apps"
    assert planned_verifier["tool"] == "desktop.ui_elements"
    assert planned_verifier["step_id"] == "verify-desktop-result"
    assert planned_verifier["planner_step_id"] == "verify-desktop-result"
    assert planned_verifier["plan_id"] == "plan-show-app"
    assert planned_verifier["source_tool"] == "app.show"
    assert planned_verifier["source_step_id"] == "manage-app"
    assert planned_verifier["source_request_id"] == "request-show-app"
    assert planned_verifier["source_tool_call_id"] == "call-show-app"
    assert "verification_predicate_kind" not in planned_verifier
    assert planned_verifier["source"] == "runtime_post_action_auto_verify"


def test_runtime_does_not_rebind_declared_observer_from_another_plan() -> None:
    wrong_plan_verifier = {
        "tool": "desktop.running_apps",
        "input": {},
        "step_id": "verify-desktop-result",
        "planner_step_id": "verify-desktop-result",
        "plan_id": "plan-other",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "depends_on": ["manage-app"],
    }

    inserted = tool_execution_module._post_action_verification_request(
        "app.show",
        {
            "tool": "app.show",
            "input": {"app_name": "Slack"},
            "request_id": "request-show-app",
            "tool_call_id": "call-show-app",
            "step_id": "manage-app",
            "plan_id": "plan-show-app",
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        {
            "ok": True,
            "action": "app.show",
            "data": {"app_name": "Slack", "show_status": "shown"},
        },
        allowed_tools=["app.show", "desktop.ui_elements", "desktop.running_apps"],
        remaining_requests=[wrong_plan_verifier],
        active_window_target={"app_name": "Slack"},
    )

    assert inserted["step_id"] == "manage-app:runtime-verify"
    assert inserted["plan_id"] == "plan-show-app"
    assert wrong_plan_verifier["tool"] == "desktop.running_apps"
    assert "source_tool_call_id" not in wrong_plan_verifier


def test_runtime_binds_planned_open_path_ui_verifier_without_duplicate() -> None:
    planned_verifier = {
        "tool": "desktop.ui_elements",
        "input": {"limit": 80},
        "step_id": "verify-desktop-result",
        "planner_step_id": "verify-desktop-result",
        "plan_id": "plan-open-path",
        "tool_plan_id": "tool-plan-open-path",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "depends_on": ["open-selected-discovered-app"],
        "task_verification_targets": [
            {"step_id": "open-selected-discovered-app"}
        ],
    }

    inserted = tool_execution_module._post_action_verification_request(
        "desktop.open_path_with_app",
        {
            "tool": "desktop.open_path_with_app",
            "input": {
                "app_name": "PixelForge",
                "path": "Downloads/report.pdf",
            },
            "request_id": "request-open-path",
            "tool_call_id": "call-open-path",
            "step_id": "open-selected-discovered-app",
            "plan_id": "plan-open-path",
            "tool_plan_id": "tool-plan-open-path",
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        {
            "ok": True,
            "action": "desktop.open_path_with_app",
            "data": {
                "app_name": "PixelForge",
                "path": "Downloads/report.pdf",
                "open_target": "app_open",
                "exists": True,
            },
        },
        allowed_tools=["desktop.active_window", "desktop.ui_elements"],
        remaining_requests=[planned_verifier],
        active_window_target={"app_name": "PixelForge"},
    )

    assert inserted == {}
    assert planned_verifier["step_id"] == "verify-desktop-result"
    assert planned_verifier["source_step_id"] == "open-selected-discovered-app"
    assert planned_verifier["source_request_id"] == "request-open-path"
    assert planned_verifier["source_tool_call_id"] == "call-open-path"
    assert planned_verifier["plan_id"] == "plan-open-path"
    assert planned_verifier["tool_plan_id"] == "tool-plan-open-path"
    assert "verification_predicate_kind" not in planned_verifier


@pytest.mark.parametrize(
    ("candidate_overrides", "expected_field", "expected_value"),
    [
        (
            {"source_tool_call_id": "call-other"},
            "source_tool_call_id",
            "call-other",
        ),
        (
            {
                "depends_on": ["other-step"],
                "task_verification_targets": [{"step_id": "other-step"}],
            },
            "depends_on",
            ["other-step"],
        ),
        (
            {"plan_id": "plan-other"},
            "plan_id",
            "plan-other",
        ),
    ],
    ids=["wrong-source", "wrong-step", "wrong-plan"],
)
def test_runtime_does_not_rebind_conflicting_planned_desktop_verifier(
    candidate_overrides: dict[str, Any],
    expected_field: str,
    expected_value: Any,
) -> None:
    planned_verifier = {
        "tool": "desktop.verify",
        "input": {"app_name": "PixelForge", "verification_goal": "app_running"},
        "step_id": "verify-desktop-result",
        "plan_id": "plan-open-app",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "depends_on": ["open-or-focus-app"],
        "task_verification_targets": [{"step_id": "open-or-focus-app"}],
        **candidate_overrides,
    }

    inserted = tool_execution_module._post_action_verification_request(
        "app.open",
        {
            "tool": "app.open",
            "input": {"app_name": "PixelForge"},
            "tool_call_id": "call-open-app",
            "step_id": "open-or-focus-app",
            "plan_id": "plan-open-app",
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        {
            "ok": True,
            "action": "app.open",
            "data": {"app_name": "PixelForge", "launch_verified": True},
        },
        allowed_tools=["desktop.active_window", "desktop.verify"],
        remaining_requests=[planned_verifier],
        active_window_target={"app_name": "PixelForge"},
    )

    assert inserted["tool"] == "desktop.active_window"
    assert inserted["step_id"] == "open-or-focus-app:runtime-verify"
    assert planned_verifier[expected_field] == expected_value


def test_runtime_keeps_planned_exact_type_verifier_step_instead_of_synthetic_one() -> None:
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda tool_request, *_args, **_kwargs: captured_requests.append(
            tool_request
        )
        or {"ok": True, "tool": tool_request.get("tool")},
    )

    runner.run(
        [
            {
                "tool": "desktop.type_into_ui_element",
                "input": {"target": "Body", "text": "hello"},
                "step_id": "type-note",
                "plan_id": "plan-note",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
            },
            {
                "tool": "desktop.verify",
                "input": {},
                "step_id": "verify-note",
                "plan_id": "plan-note",
                "runtime_stage": "verify",
                "depends_on": ["type-note"],
                "task_verification_targets": [{"step_id": "type-note"}],
            },
        ],
        [
            "desktop.type_into_ui_element",
            "desktop.verify",
            "desktop.ui_elements",
        ],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Type hello into the Body field"}],
        timeline,
        [],
        next_iteration=3,
        run_id="run-planned-exact-verify",
        budget=FakeBudget(),
    )

    assert [request["step_id"] for request in captured_requests] == [
        "type-note",
        "verify-note",
    ]
    assert not any(
        str(request.get("step_id") or "").endswith(":runtime-verify")
        for request in captured_requests
    )


def test_runtime_tool_request_runner_routes_running_provider_session() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在隔离桌面里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda tool_request, *_args, **_kwargs: captured_requests.append(
            tool_request
        )
        or {"ok": True, "tool": tool_request.get("tool")},
    )

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {"mode": "sandbox_preferred"},
                "desktop_provider_session": {
                    "running": True,
                    "status": "running",
                    "provider_id": "local-isolated-desktop",
                    "url": "http://127.0.0.1:19093",
                    "tool_names": ["desktop.safe_type_text"],
                },
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert budget.claims == []
    assert len(captured_requests) == 1
    routed_request = captured_requests[0]
    assert routed_request["desktop_execution_route"]["status"] == "sandbox_ready"
    assert routed_request["desktop_execution_route"]["selected_provider_kind"] == (
        "sandbox_desktop"
    )
    assert routed_request["sandbox_provider"]["source"] == "desktop_provider_session"
    assert routed_request["sandbox_provider"]["provider_id"] == "local-isolated-desktop"
    assert routed_request["sandbox_provider"]["desktop_session_isolated"] is True
    assert routed_request["sandbox_provider"]["foreground_takeover_required"] is False
    assert not [event for event in timeline if event["event"] == "agent.tool.skipped"]


def test_runtime_tool_request_runner_blocks_failed_provider_session_fallback() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在隔离桌面里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda tool_request, *_args, **_kwargs: captured_requests.append(
            tool_request
        )
        or {"ok": True, "tool": tool_request.get("tool")},
    )

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {
                    "mode": "preview_input",
                    "require_sandbox_for_keyboard_mouse": True,
                    "avoid_user_foreground_takeover": True,
                },
                "desktop_provider_session": {
                    "ok": False,
                    "needed": True,
                    "auto_start": True,
                    "running": False,
                    "started": False,
                    "status": "start_failed",
                    "reason": "isolated_provider_start_failed",
                    "error": "provider refused to launch",
                    "tool_names": ["desktop.safe_type_text"],
                },
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert captured_requests == []
    assert budget.claims == [("desktop.safe_type_text", False)]
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    result = skipped["result"]
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["desktop_execution_route"]["status"] == "provider_required"
    assert result["desktop_execution_route"]["sandbox_required"] is True
    assert result["sandbox_provider"]["source"] == "desktop_provider_session"
    assert result["sandbox_provider"]["available"] is False


def test_runtime_tool_request_runner_rechecks_stale_ready_route_against_session() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在隔离桌面里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    captured_requests: list[dict[str, Any]] = []
    runner = _runner(
        call_agent_tool=lambda tool_request, *_args, **_kwargs: captured_requests.append(
            tool_request
        )
        or {"ok": True, "tool": tool_request.get("tool")},
    )

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {
                    "mode": "preview_input",
                    "require_sandbox_for_keyboard_mouse": True,
                    "avoid_user_foreground_takeover": True,
                },
                "desktop_execution_route": {
                    "status": "sandbox_ready",
                    "can_execute": True,
                    "selected_provider_kind": "sandbox_desktop",
                    "selected_provider_id": "sandbox-1",
                    "provider_execution_required": True,
                    "sandbox_required": True,
                    "blocking_conditions": [],
                },
                "desktop_provider_session": {
                    "running": True,
                    "status": "running",
                    "provider_id": "sandbox-1",
                    "url": "http://127.0.0.1:19093",
                    "tool_names": ["desktop.safe_type_text"],
                    "keyboard_mouse_capture_supported": False,
                },
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert captured_requests == []
    assert budget.claims == [("desktop.safe_type_text", False)]
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    result = skipped["result"]
    assert result["desktop_execution_route"]["status"] == (
        "sandbox_keyboard_mouse_provider_required"
    )
    assert result["desktop_execution_route"]["can_execute"] is False
    assert result["sandbox_provider"]["source"] == "desktop_provider_session"
    assert result["sandbox_provider"]["keyboard_mouse_capture_supported"] is False


def test_runtime_tool_request_runner_preview_input_policy_allows_media_but_blocks_typing() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "播放音乐，然后在当前应用里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = {"ok": True, "action": tool_name, "summary": "done"}
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    policy = {"mode": "preview_input", "allow_media_control": True}

    runner.run(
        [
            {
                "tool": "media.music_app_open_and_play",
                "input": {"app_name": "Music"},
                "desktop_execution_policy": policy,
            },
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": policy,
            },
        ],
        ["media.music_app_open_and_play", "desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    assert calls == [("media.music_app_open_and_play", {"app_name": "Music"})]
    assert budget.claims == [("desktop.safe_type_text", False)]
    assert skipped["detail"] == "desktop.safe_type_text"
    assert skipped["result"]["blocked_by_desktop_execution_policy"] is True
    assert skipped["result"]["desktop_execution_policy"] == policy
    supervised_action = skipped["result"]["recovery_actions"][4]
    assert supervised_action["tool"] == "desktop.safe_type_text"
    assert supervised_action["input"] == {"text": "hello"}
    assert supervised_action["desktop_execution_policy"]["mode"] == "supervised_live"
    assert "blocked_by_desktop_execution_policy" in messages[-1]["content"]


def test_runtime_tool_request_runner_preview_input_policy_allows_safe_creation_shortcut() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    budget = FakeBudget()
    messages = [{"role": "user", "content": "新建一条笔记"}]
    timeline: list[dict[str, Any]] = []
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = {"ok": True, "action": tool_name, "summary": "done"}
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    policy = {"mode": "preview_input", "allow_media_control": True}

    runner.run(
        [
            {
                "tool": "desktop.safe_shortcut",
                "input": {"action": "new_note"},
                "desktop_execution_policy": policy,
            },
        ],
        ["desktop.safe_shortcut"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    assert calls == []
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    result = skipped["result"]
    assert result["status"] == "provider_required"
    assert result["blocking_conditions"] == ["sandbox_desktop_provider_required"]
    assert result["desktop_execution_route"]["can_execute"] is False
    assert result["recovery_actions"][0]["tool"] == "desktop.provider_session.start"


def test_runtime_tool_request_runner_allow_policy_still_requires_sandbox_for_keyboard_mouse() -> None:
    budget = FakeBudget()
    messages = [{"role": "user", "content": "在当前应用里输入 hello"}]
    timeline: list[dict[str, Any]] = []
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        _timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append((tool_request.get("tool", ""), dict(tool_request.get("input") or {})))
        return {"ok": True, "tool": tool_request.get("tool")}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=[])

    runner.run(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {
                    "mode": "supervised_live",
                    "allow_live_foreground": True,
                    "avoid_user_foreground_takeover": True,
                    "require_sandbox_for_keyboard_mouse": True,
                },
            }
        ],
        ["desktop.safe_type_text"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=3,
        run_id="run-1",
        budget=budget,
    )

    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    result = skipped["result"]
    assert calls == []
    assert budget.claims == [("desktop.safe_type_text", False)]
    assert result["blocked_by_desktop_execution_policy"] is True
    assert result["status"] in {
        "sandbox_keyboard_mouse_provider_required",
        "sandbox_desktop_session_required",
        "provider_required",
    }
    assert result["desktop_execution_policy"]["allow_live_foreground"] is True
    assert result["desktop_execution_policy"]["require_sandbox_for_keyboard_mouse"] is True
    assert result["desktop_execution_route"]["can_execute"] is False
    assert result["desktop_execution_route"]["sandbox_required"] is True
    assert result["blocking_condition"] in result["desktop_execution_route"]["blocking_conditions"]
    recovery_tools = [action["tool"] for action in result["recovery_actions"]]
    assert recovery_tools[0] == "desktop.provider_session.start"
    assert "desktop.active_window" in recovery_tools
    assert "blocked_by_desktop_execution_policy" in messages[-1]["content"]


def test_runtime_tool_request_runner_uses_discovered_app_name_for_followup_tool() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [{"name": "Music", "path": "/Applications/Music.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Apple Music"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Apple Music", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Apple Music"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Apple Music", "limit": 20}),
        ("app.open", {"app_name": "Music"}),
    ]


def test_runtime_tool_request_runner_skips_foreground_mutation_after_inspect_not_ready() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = {
            "ok": False,
            "action": "desktop.inspect_app",
            "summary": "No installed app matched PixelForge",
            "error": "app_not_found",
            "recommended_tools": ["desktop.list_apps", "app.open"],
            "recovery_actions": [
                {
                    "label": "重新发现应用",
                    "tool": "desktop.list_apps",
                    "input": {"query": "PixelForge", "limit": 20},
                    "permission_target": "app_discovery",
                    "risk_level": "low",
                }
            ],
            "data": {
                "app_name": "PixelForge",
                "requested_app_name": "PixelForge",
                "app_found": False,
                "running": False,
                "focus_verified": False,
                "ui_element_count": 0,
                "control_like_count": 0,
                "ready_for_foreground_action": False,
                "checks": {
                    "discovered_app": False,
                    "status_running": False,
                    "focus_verified": False,
                    "named_ui_elements_nonempty": False,
                    "control_like_ui_visible": False,
                    "ready_for_foreground_action": False,
                },
            },
        }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]
    budget = FakeBudget()

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=budget,
    )

    assert calls == [("desktop.inspect_app", {"app_name": "PixelForge"})]
    assert budget.claims == [("app.open_and_click_ui_element", False)]
    assert [event["event"] for event in timeline] == [
        "agent.tool.call",
        "agent.replan.requested",
        "agent.tool.skipped",
        "agent.replan.requested",
    ]
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")["result"]
    assert skipped["blocked_by_runtime_readiness"] is True
    assert skipped["tool"] == "app.open_and_click_ui_element"
    assert skipped["blocking_conditions"] == [
        "app_not_found",
        "app_not_running",
        "foreground_focus_unverified",
        "ui_elements_empty",
        "no_actionable_controls",
        "foreground_not_ready",
    ]
    assert skipped["recommended_tools"] == ["desktop.list_apps", "app.open"]
    assert skipped["recovery_actions"][0]["tool"] == "desktop.list_apps"
    skipped_run_event = next(
        payload for _run_id, event_type, payload in run_events if event_type == "agent.tool.skipped"
    )
    assert skipped_run_event["result"]["blocked_by_runtime_readiness"] is True
    replan_events = [
        event for event in timeline if event["event"] == "agent.replan.requested"
    ]
    assert [event["payload"]["source_tool_name"] for event in replan_events] == [
        "desktop.inspect_app",
        "app.open_and_click_ui_element",
    ]
    assert all(event["payload"]["trigger"] == "tool_unavailable" for event in replan_events)
    assert replan_events[0]["payload"]["fallback_tools"] == ["desktop.list_apps", "app.open"]
    assert replan_events[0]["payload"]["metadata"]["recovery_actions"][0]["tool"] == "desktop.list_apps"
    assert replan_events[1]["payload"]["fallback_tools"] == ["desktop.list_apps", "app.open"]
    assert replan_events[1]["payload"]["metadata"]["recovery_actions"][0]["tool"] == "desktop.list_apps"
    run_replan_event = next(
        payload for _run_id, event_type, payload in run_events if event_type == "agent.replan.requested"
    )
    assert run_replan_event["request_id"] == replan_events[0]["payload"]["request_id"]
    assert "blocked_by_runtime_readiness" in messages[-1]["content"]


def test_runtime_tool_request_runner_continues_planned_recovery_after_inspect_not_ready() -> None:
    calls: list[str] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append(tool_name)
        if tool_name == "desktop.inspect_app":
            result = {
                "ok": False,
                "action": "desktop.inspect_app",
                "summary": "No installed app matched PixelForge",
                "error": "app_not_found",
                "recommended_tools": ["desktop.list_apps"],
                "recovery_actions": [
                    {
                        "label": "重新发现应用",
                        "tool": "desktop.list_apps",
                        "input": {"query": "PixelForge", "limit": 20},
                        "permission_target": "app_discovery",
                        "risk_level": "low",
                    }
                ],
                "data": {
                    "app_name": "PixelForge",
                    "requested_app_name": "PixelForge",
                    "app_found": False,
                    "running": False,
                    "ready_for_foreground_action": False,
                    "checks": {
                        "discovered_app": False,
                        "status_running": False,
                        "ready_for_foreground_action": False,
                    },
                },
            }
        elif tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload.get("query"),
                    "apps": [{"name": "PixelForge", "path": "/Applications/PixelForge.app"}],
                },
            }
        elif tool_name == "app.open_and_click_ui_element":
            result = {
                "ok": True,
                "action": "app.open_and_click_ui_element",
                "data": {
                    "app_name": payload.get("app_name"),
                    "target": payload.get("target"),
                },
            }
        else:
            raise AssertionError(f"unexpected call: {tool_name}")
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {"tool": "desktop.list_apps", "input": {"query": "PixelForge", "limit": 20}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "desktop.list_apps", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        "desktop.inspect_app",
        "desktop.list_apps",
        "app.open_and_click_ui_element",
    ]
    assert [event["event"] for event in timeline] == [
        "agent.tool.call",
        "agent.replan.requested",
        "agent.tool.call",
        "agent.desktop.readiness_recovered",
        "agent.tool.call",
    ]
    assert timeline[1]["payload"]["source_tool_name"] == "desktop.inspect_app"
    assert timeline[1]["payload"]["fallback_tools"] == ["desktop.list_apps"]
    assert timeline[3]["recovery_tool"] == "desktop.list_apps"
    assert "blocked_by_runtime_readiness" not in messages[-1]["content"]


def test_runtime_tool_request_runner_keeps_readiness_blocker_after_failed_recovery() -> None:
    calls: list[str] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append(tool_name)
        if tool_name == "desktop.inspect_app":
            result = {
                "ok": False,
                "action": "desktop.inspect_app",
                "summary": "No installed app matched PixelForge",
                "error": "app_not_found",
                "data": {
                    "app_name": "PixelForge",
                    "requested_app_name": "PixelForge",
                    "app_found": False,
                    "running": False,
                    "ready_for_foreground_action": False,
                    "checks": {
                        "discovered_app": False,
                        "status_running": False,
                        "ready_for_foreground_action": False,
                    },
                },
            }
        elif tool_name == "app.open":
            result = {
                "ok": False,
                "action": "app.open",
                "summary": "Application not found",
                "error": "app_not_found",
                "data": {"app_name": payload.get("app_name")},
            }
        else:
            raise AssertionError(f"unexpected call: {tool_name}")
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]
    budget = FakeBudget()

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {"tool": "app.open", "input": {"app_name": "PixelForge"}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "app.open", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=budget,
    )

    assert calls == ["desktop.inspect_app", "app.open"]
    skipped = next(
        event
        for event in timeline
        if event["event"] == "agent.tool.skipped"
        and event["detail"] == "app.open_and_click_ui_element"
    )
    assert skipped["result"]["blocked_by_runtime_readiness"] is True
    assert any(event["event"] == "agent.replan.requested" for event in timeline)
    assert budget.claims == [("app.open_and_click_ui_element", False)]


def test_runtime_tool_request_runner_replans_failed_recovery_with_parent_context() -> None:
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        result = {
            "ok": False,
            "error": "script failed",
            "returncode": 1,
        }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    request = {
        "tool": "terminal.run",
        "input": {"command": "python analyze_sales.py"},
        "source": "agent_studio_replan_recovery",
        "step_id": "analyze-data-file",
        "task_id": "task-1",
        "workflow_run_id": "workflow-run-1",
        "replan_request_id": "replan-parent-1",
        "replan_recovery_action_id": "replan-parent-1:action:1:terminal.run",
        "replan_trigger": "tool_failure",
        "replan_triggers": ["tool_failure"],
        "replan_signal_ids": ["signal-analyze"],
        "recovery_action_label": "Run fallback analysis script",
        "source_step_id": "analyze-data-file",
        "source_tool_name": "data.analyze",
        "target_capability_id": "data.analysis",
        "task_verification_targets": [
            {"step_id": "analyze-data-file", "todo_id": "todo-analyze"}
        ],
    }

    with pytest.raises(AgentRuntimeError):
        runner.run(
            [request],
            ["terminal.run"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Analyze sales.csv"}],
            timeline,
            [],
            next_iteration=1,
            run_id="workflow-run-1",
            budget=FakeBudget(),
        )

    replan_event = next(
        event
        for event in timeline
        if event["event"] == "workflow.run.replan.requested"
    )
    payload = replan_event["payload"]
    assert payload["source"] == "runtime_tool_request_runner"
    assert payload["trigger"] == "tool_failure"
    assert payload["source_tool_name"] == "terminal.run"
    assert payload["target_capability_id"] == "data.analysis"
    metadata = payload["metadata"]
    assert metadata["replan_recovery_failed"] is True
    assert metadata["parent_replan_request_id"] == "replan-parent-1"
    assert metadata["parent_replan_trigger"] == "tool_failure"
    assert metadata["failed_recovery_action_id"] == (
        "replan-parent-1:action:1:terminal.run"
    )
    assert metadata["failed_recovery_action_label"] == "Run fallback analysis script"
    assert metadata["failed_recovery_tool"] == "terminal.run"
    assert metadata["failed_recovery_input"] == {"command": "python analyze_sales.py"}
    assert metadata["failed_recovery_source"] == "agent_studio_replan_recovery"
    assert metadata["original_source_tool_name"] == "data.analyze"
    assert metadata["replan_signal_ids"] == ["signal-analyze"]
    assert metadata["failed_recovery_verification_targets"][0]["step_id"] == (
        "analyze-data-file"
    )
    assert metadata["failed_recovery_result_preview"]["error"] == "script failed"
    run_replan_event = next(
        event for event in run_events if event[1] == "workflow.run.replan.requested"
    )
    assert run_replan_event[2]["metadata"]["parent_replan_request_id"] == "replan-parent-1"


def test_runtime_tool_request_runner_stops_after_failed_nonfatal_replan_recovery() -> None:
    timeline: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    calls: list[str] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(str(tool_request.get("tool") or ""))
        if tool_request["tool"] == "app.open":
            return {
                "ok": False,
                "error": "app not found",
                "status": "failed",
            }
        return {"ok": True, "content": "should not run"}

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    recovery_request = {
        "tool": "app.open",
        "input": {"app_name": "PixelForge"},
        "source": "agent_studio_replan_recovery",
        "step_id": "open-pixelforge",
        "task_id": "task-1",
        "replan_request_id": "replan-parent-1",
        "replan_recovery_action_id": "replan-parent-1:action:1:app.open",
        "replan_trigger": "verification_failed",
        "replan_triggers": ["verification_failed"],
        "recovery_action_label": "Open target app",
        "source_step_id": "verify-pixelforge",
        "source_tool_name": "desktop.verify",
        "target_capability_id": "desktop.app",
    }

    runner.run(
        [
            recovery_request,
            {"tool": "workspace.read", "input": {"path": "README.md"}},
        ],
        ["app.open", "workspace.read"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Recover PixelForge launch"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-recovery-failed",
        budget=FakeBudget(),
    )

    assert calls == ["app.open"]
    replan_event = next(event for event in timeline if event["event"] == "agent.replan.requested")
    payload = replan_event["payload"]
    assert payload["trigger"] == "verification_failed"
    assert payload["source_tool_name"] == "app.open"
    assert payload["metadata"]["replan_recovery_failed"] is True
    assert payload["metadata"]["parent_replan_request_id"] == "replan-parent-1"
    assert payload["metadata"]["failed_recovery_tool"] == "app.open"
    assert any(event_type == "agent.replan.requested" for _run_id, event_type, _payload in run_events)


def test_runtime_tool_request_runner_clears_app_not_found_blocker_after_discovery() -> None:
    calls: list[str] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append(tool_name)
        if tool_name == "desktop.inspect_app":
            result = {
                "ok": False,
                "action": "desktop.inspect_app",
                "summary": "No installed app matched PixelForge",
                "error": "app_not_found",
                "data": {
                    "app_name": "PixelForge",
                    "requested_app_name": "PixelForge",
                    "app_found": False,
                    "running": False,
                    "ready_for_foreground_action": False,
                    "checks": {
                        "discovered_app": False,
                        "status_running": False,
                        "ready_for_foreground_action": False,
                    },
                },
            }
        elif tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload.get("query"),
                    "apps": [{"name": "PixelForge", "path": "/Applications/PixelForge.app"}],
                },
            }
        elif tool_name == "app.open_and_click_ui_element":
            result = {
                "ok": True,
                "action": "app.open_and_click_ui_element",
                "data": {
                    "app_name": payload.get("app_name"),
                    "target": payload.get("target"),
                },
            }
        else:
            raise AssertionError(f"unexpected call: {tool_name}")
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 PixelForge 并点击登录"}]

    runner.run(
        [
            {"tool": "desktop.inspect_app", "input": {"app_name": "PixelForge"}},
            {"tool": "desktop.list_apps", "input": {"query": "PixelForge", "limit": 20}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {"app_name": "PixelForge", "target": "登录"},
            },
        ],
        ["desktop.inspect_app", "desktop.list_apps", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        "desktop.inspect_app",
        "desktop.list_apps",
        "app.open_and_click_ui_element",
    ]
    assert [event["event"] for event in timeline] == [
        "agent.tool.call",
        "agent.tool.call",
        "agent.desktop.readiness_recovered",
        "agent.tool.call",
    ]
    recovered = timeline[2]
    assert recovered["detail"] == "desktop.list_apps"
    assert recovered["tool"] == "desktop.list_apps"
    assert recovered["recovery_tool"] == "desktop.list_apps"
    assert recovered["status"] == "recovered"
    assert recovered["app_name"] == "PixelForge"
    assert recovered["blocking_conditions"] == [
        "app_not_found",
        "app_not_running",
        "foreground_not_ready",
    ]
    assert run_events[-1][1] == "agent.desktop.readiness_recovered"
    assert run_events[-1][2]["recovery_tool"] == "desktop.list_apps"
    assert "blocked_by_runtime_readiness" not in messages[-1]["content"]


def test_runtime_tool_request_runner_records_discovered_app_name_resolution() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [{"name": "Music", "path": "/Applications/Music.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        run_events.append(
            (
                "run-1",
                "agent.tool.call",
                {
                    "tool_call_id": str(tool_request.get("tool_call_id") or ""),
                    "tool": tool_name,
                    "input_preview": payload,
                    "result": result,
                },
            )
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 Apple Music"}]

    runner.run(
        [
            {
                "tool": "desktop.list_apps",
                "tool_call_id": "call-list-music",
                "input": {"query": "Apple Music", "limit": 20},
            },
            {
                "tool": "app.open",
                "tool_call_id": "call-open-music",
                "input": {"app_name": "Apple Music"},
            },
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Apple Music", "limit": 20}),
        ("app.open", {"app_name": "Music"}),
    ]
    resolution_payload = {
        "tool": "app.open",
        "field": "app_name",
        "requested_app_name": "Apple Music",
        "resolved_app_name": "Music",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Music.app",
        "tool_call_id": "call-open-music",
    }
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.open",
            **resolution_payload,
        }
    ]
    assert ("run-1", "agent.tool.input_resolved", resolution_payload) in run_events
    app_open_events = [
        (event_type, payload)
        for _run_id, event_type, payload in run_events
        if payload.get("tool") == "app.open"
    ]
    assert {payload["tool_call_id"] for _event_type, payload in app_open_events} == {
        "call-open-music"
    }
    calls_from_events = tool_call_snapshots_from_events(
        [
            PublicRunEvent(
                run_id="run-1",
                sequence=sequence,
                event_type=event_type,
                detail="app.open",
                payload=payload,
            )
            for sequence, (event_type, payload) in enumerate(app_open_events, start=1)
        ]
    )
    assert len(calls_from_events) == 1
    assert calls_from_events[0].tool_call_id == "call-open-music"


def test_runtime_tool_request_runner_resolves_named_app_marked_from_discovery() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Pixel Forge Pro",
                        "path": "/Applications/Pixel Forge Pro.app",
                        "match_score": 91,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {"app_name": payload["app_name"]},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开 PixelForge"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "PixelForge", "limit": 20}},
            {
                "tool": "app.open",
                "input": {
                    "app_name": "PixelForge",
                    "selection_source": "desktop.list_apps",
                    "query": "PixelForge",
                },
            },
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-named-discovered-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "PixelForge", "limit": 20}),
        ("app.open", {"app_name": "Pixel Forge Pro"}),
    ]
    resolution_payload = {
        "tool": "app.open",
        "field": "app_name",
        "requested_app_name": "PixelForge",
        "resolved_app_name": "Pixel Forge Pro",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Pixel Forge Pro.app",
        "app_resolution_score": "91",
        "app_resolution_confidence": "high",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.open",
            **resolution_payload,
        }
    ]
    assert ("run-named-discovered-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_discovered_app_placeholder() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Pixelmator Pro",
                        "path": "/Applications/Pixelmator Pro.app",
                        "match_score": 94,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {
                    "app_name": payload["app_name"],
                    "target": payload["target"],
                },
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开一个能编辑图片的应用，然后点击导出"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "image", "limit": 20}},
            {
                "tool": "app.focus_and_click_ui_element",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "image",
                    "target": "导出",
                    "limit": 80,
                },
            },
        ],
        ["desktop.list_apps", "app.focus_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "image", "limit": 20}),
        (
            "app.focus_and_click_ui_element",
            {
                "app_name": "Pixelmator Pro",
                "target": "导出",
                "limit": 80,
            },
        ),
    ]
    resolution_payload = {
        "tool": "app.focus_and_click_ui_element",
        "field": "app_name",
        "requested_app_name": "image",
        "resolved_app_name": "Pixelmator Pro",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Pixelmator Pro.app",
        "app_resolution_score": "94",
        "app_resolution_confidence": "high",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.focus_and_click_ui_element",
            **resolution_payload,
        }
    ]
    assert ("run-selected-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_app_without_query_for_media_playback() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Music",
                        "path": "/Applications/Music.app",
                        "match_score": 96,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {"app_name": payload["app_name"]},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "找个音乐应用播放超时空辉夜姬"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "music", "limit": 20}},
            {
                "tool": "media.music_app_open_and_play",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                },
            },
        ],
        ["desktop.list_apps", "media.music_app_open_and_play"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-media-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "music", "limit": 20}),
        ("media.music_app_open_and_play", {"app_name": "Music"}),
    ]
    resolution_payload = {
        "tool": "media.music_app_open_and_play",
        "field": "app_name",
        "requested_app_name": "<selected app from desktop.list_apps>",
        "resolved_app_name": "Music",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Music.app",
        "app_resolution_score": "96",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "latest_desktop.list_apps_selection",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "media.music_app_open_and_play",
            **resolution_payload,
        }
    ]
    assert ("run-selected-media-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_running_app_placeholder(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    monkeypatch.setattr(
        "apps.shell.agent.tools.desktop._installed_app_match_candidates",
        lambda query: [
            {
                "name": "Numbers",
                "path": "/System/Applications/Numbers.app",
                "match_score": 92,
                "match_confidence": "high",
                "match_reason": f"capability_{query}",
            }
        ],
    )

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.running_apps":
            result = {
                "ok": True,
                "action": "desktop.running_apps",
                "data": {
                    "apps": [
                        {"name": "Finder", "frontmost": False},
                        {"name": "Numbers", "frontmost": True},
                    ],
                    "frontmost": "Numbers",
                },
            }
        else:
            result = {
                "ok": True,
                "action": tool_name,
                "data": {"app_name": payload["app_name"]},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "在当前打开的表格应用里粘贴结果"}]

    runner.run(
        [
            {"tool": "desktop.running_apps", "input": {}},
            {
                "tool": "app.focus_and_safe_shortcut",
                "input": {
                    "app_name": "<selected app from desktop.running_apps>",
                    "selection_source": "desktop.running_apps",
                    "query": "spreadsheet",
                    "action": "paste",
                },
            },
        ],
        ["desktop.running_apps", "app.focus_and_safe_shortcut"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-running-app",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.running_apps", {}),
        ("app.focus_and_safe_shortcut", {"app_name": "Numbers", "action": "paste"}),
    ]
    resolution_payload = {
        "tool": "app.focus_and_safe_shortcut",
        "field": "app_name",
        "requested_app_name": "spreadsheet",
        "resolved_app_name": "Numbers",
        "source_tool": "desktop.running_apps",
        "resolved_app_path": "/System/Applications/Numbers.app",
        "app_resolution_score": "92",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "capability_spreadsheet",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.focus_and_safe_shortcut",
            **resolution_payload,
        }
    ]
    assert ("run-selected-running-app", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_top_level_app_candidates() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "apps": [
                    {
                        "name": "Typora",
                        "path": "/Applications/Typora.app",
                        "score": 88,
                        "confidence": "high",
                        "reason": "document:markdown",
                    }
                ],
            }
        else:
            result = {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "markdown", "limit": 20}},
            {
                "tool": "app.open",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "markdown",
                },
            },
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "打开一个能写 markdown 的应用"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-top-level-app-candidates",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "markdown", "limit": 20}),
        ("app.open", {"app_name": "Typora"}),
    ]
    resolution_payload = {
        "tool": "app.open",
        "field": "app_name",
        "requested_app_name": "markdown",
        "resolved_app_name": "Typora",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Typora.app",
        "app_resolution_score": "88",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "document:markdown",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "app.open",
            **resolution_payload,
        }
    ]
    assert (
        "run-top-level-app-candidates",
        "agent.tool.input_resolved",
        resolution_payload,
    ) in run_events


def test_runtime_tool_request_runner_resolves_selected_app_for_desktop_windows() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Arc Browser",
                        "path": "/Applications/Arc Browser.app",
                        "match_score": 100,
                        "match_confidence": "high",
                        "match_reason": "exact_name",
                        "matched_name": "Arc Browser",
                        "matched_name_source": "bundle_metadata",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": "desktop.windows",
                "data": {"app_name": payload["app_name"], "windows": []},
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc Browser", "limit": 20}},
            {
                "tool": "desktop.windows",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "Arc Browser",
                },
            },
        ],
        ["desktop.list_apps", "desktop.windows"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "查看 Arc Browser 的窗口"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-app-windows",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc Browser", "limit": 20}),
        ("desktop.windows", {"app_name": "Arc Browser"}),
    ]
    resolution_payload = {
        "tool": "desktop.windows",
        "field": "app_name",
        "requested_app_name": "Arc Browser",
        "resolved_app_name": "Arc Browser",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Arc Browser.app",
        "app_resolution_score": "100",
        "app_resolution_confidence": "high",
        "app_resolution_reason": "exact_name",
        "app_resolution_matched_name": "Arc Browser",
        "app_resolution_matched_name_source": "bundle_metadata",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "desktop.windows",
            **resolution_payload,
        }
    ]
    assert (
        "run-selected-app-windows",
        "agent.tool.input_resolved",
        resolution_payload,
    ) in run_events


def test_runtime_tool_request_runner_scopes_windows_to_recent_foreground_app() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
            if tool_name == "app.open"
            else {
                "ok": True,
                "action": "desktop.windows",
                "data": {"app_name": payload["app_name"], "windows": []},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {"tool": "app.open", "input": {"app_name": "Notes"}},
            {"tool": "desktop.windows", "input": {}},
        ],
        ["app.open", "desktop.windows"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "打开 Notes 后看它的窗口"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-foreground-windows",
        budget=FakeBudget(),
    )

    assert calls == [
        ("app.open", {"app_name": "Notes"}),
        ("desktop.windows", {"app_name": "Notes"}),
    ]


def test_runtime_tool_request_runner_resolves_selected_app_for_desktop_verify() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    app_status_calls: list[str] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    class StatusBroker:
        def app_status(self, app_name: str) -> dict[str, Any]:
            app_status_calls.append(app_name)
            return {
                "ok": True,
                "action": "app.status",
                "summary": f"{app_name} is running",
                "data": {
                    "app_name": app_name,
                    "running": True,
                    "status": "running",
                },
            }

    status_broker = StatusBroker()

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Pixelmator Pro",
                        "path": "/Applications/Pixelmator Pro.app",
                        "match_score": 94,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = dispatch_tool_call(status_broker, tool_name, payload)
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "image editor", "limit": 20}},
            {
                "tool": "desktop.verify",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "image editor",
                    "verification_goal": "app_running",
                    "role_filter": "button",
                    "limit": 80,
                },
            },
        ],
        ["desktop.list_apps", "desktop.verify"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "找一个图片编辑应用并验证它的界面"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-app-verify",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "image editor", "limit": 20}),
        (
            "desktop.verify",
            {
                "app_name": "Pixelmator Pro",
                "verification_goal": "app_running",
                "role_filter": "button",
                "limit": 80,
            },
        ),
    ]
    assert app_status_calls == ["Pixelmator Pro"]
    resolution_payload = {
        "tool": "desktop.verify",
        "field": "app_name",
        "requested_app_name": "image editor",
        "resolved_app_name": "Pixelmator Pro",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/Applications/Pixelmator Pro.app",
        "app_resolution_score": "94",
        "app_resolution_confidence": "high",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "desktop.verify",
            **resolution_payload,
        }
    ]
    assert (
        "run-selected-app-verify",
        "agent.tool.input_resolved",
        resolution_payload,
    ) in run_events


def test_runtime_tool_request_runner_scopes_list_windows_to_recent_foreground_app() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "app.focus",
                "data": {"app_name": payload["app_name"], "focus_status": "frontmost"},
            }
            if tool_name == "app.focus"
            else {
                "ok": True,
                "action": "desktop.list_windows",
                "data": {"app_name": payload["app_name"], "windows": []},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {"tool": "app.focus", "input": {"app_name": "Notes"}},
            {"tool": "desktop.list_windows", "input": {}},
        ],
        ["app.focus", "desktop.list_windows"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "聚焦 Notes 后看它的窗口"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-foreground-list-windows",
        budget=FakeBudget(),
    )

    assert calls == [
        ("app.focus", {"app_name": "Notes"}),
        ("desktop.list_windows", {"app_name": "Notes"}),
    ]


def test_runtime_tool_request_runner_normalizes_discovered_app_open_path_input() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        ToolDescriptorRegistry.validate_payload(tool_name, payload)
        calls.append((tool_name, payload))
        if tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "best_match": {
                        "name": "Preview",
                        "path": "/System/Applications/Preview.app",
                        "match_score": 100,
                        "match_confidence": "high",
                    },
                },
            }
        else:
            result = {
                "ok": True,
                "action": "desktop.open_path_with_app",
                "data": {
                    "app_name": payload["app_name"],
                    "path": payload["path"],
                },
            }
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)
    messages = [{"role": "user", "content": "打开一个能编辑 PDF 的应用并打开 Downloads/report.pdf"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "pdf", "limit": 20}},
            {
                "tool": "desktop.open_path_with_app",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "selection_source": "desktop.list_apps",
                    "query": "pdf",
                    "target_path": "Downloads/report.pdf",
                    "action": "open_path_with_selected_app",
                },
            },
        ],
        ["desktop.list_apps", "desktop.open_path_with_app"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-open-path",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "pdf", "limit": 20}),
        (
            "desktop.open_path_with_app",
            {"app_name": "Preview", "path": "Downloads/report.pdf"},
        ),
    ]
    resolution_payload = {
        "tool": "desktop.open_path_with_app",
        "field": "app_name",
        "requested_app_name": "pdf",
        "resolved_app_name": "Preview",
        "source_tool": "desktop.list_apps",
        "resolved_app_path": "/System/Applications/Preview.app",
        "app_resolution_score": "100",
        "app_resolution_confidence": "high",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "desktop.open_path_with_app",
            **resolution_payload,
        }
    ]
    assert ("run-selected-open-path", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_workspace_file_from_previous_list() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    seen_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        seen_requests.append(tool_request)
        result = (
            {
                "ok": True,
                "path": "Downloads",
                "entries": [
                    {"name": "old.csv", "type": "file", "mtime": 10},
                    {"name": "latest.csv", "type": "file", "mtime": 20},
                ],
            }
            if tool_name == "workspace.list"
            else {"ok": True, "path": payload["path"], "artifact": {"path": "analysis-report.md"}}
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "workspace.list",
                "input": {
                    "path": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "include_metadata": True,
                },
            },
            {
                "tool": "data.analyze",
                "input": {
                    "path": "<selected file from workspace.list>",
                    "selection_source": "workspace.list",
                    "selection": "最近",
                    "source_scope": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "source_kind": "csv",
                    "artifact_path": "analysis-report.md",
                },
                "source": "runtime_planner",
                "step_id": "analyze-discovered-data",
                "capability_id": "data.analysis",
            },
        ],
        ["workspace.list", "data.analyze"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "分析 Downloads 里最新的 CSV"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-workspace-file",
        budget=FakeBudget(),
    )

    assert calls == [
        (
            "workspace.list",
            {
                "path": "Downloads",
                "pattern": "*.csv",
                "file_type": "csv",
                "include_metadata": True,
            },
        ),
        (
            "data.analyze",
            {
                "path": "Downloads/latest.csv",
                "source_kind": "csv",
                "artifact_path": "analysis-report.md",
            },
        ),
    ]
    assert seen_requests[-1]["input_resolution"]["resolved_path"] == "Downloads/latest.csv"
    resolution_payload = {
        "tool": "data.analyze",
        "field": "path",
        "requested_path": "<selected file from workspace.list>",
        "resolved_path": "Downloads/latest.csv",
        "source_tool": "workspace.list",
        "source_path": "Downloads",
        "resolved_file_name": "latest.csv",
        "selection": "最近",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "data.analyze",
            **resolution_payload,
        }
    ]
    assert ("run-selected-workspace-file", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_resolves_selected_workspace_files_from_previous_list() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    seen_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        seen_requests.append(tool_request)
        result = (
            {
                "ok": True,
                "path": "Downloads",
                "entries": [
                    {"name": "east.csv", "type": "file", "mtime": 10},
                    {"name": "west.csv", "type": "file", "mtime": 20},
                ],
            }
            if tool_name == "workspace.list"
            else {"ok": True, "paths": payload["paths"], "artifact": {"path": "analysis-report.md"}}
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "workspace.list",
                "input": {
                    "path": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "selection": "all",
                },
            },
            {
                "tool": "data.analyze",
                "input": {
                    "path": "<selected files from workspace.list>",
                    "selection_source": "workspace.list",
                    "selection": "all",
                    "source_scope": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                    "source_kind": "csv",
                    "artifact_path": "analysis-report.md",
                },
                "source": "runtime_planner",
                "step_id": "analyze-discovered-data",
                "capability_id": "data.analysis",
            },
        ],
        ["workspace.list", "data.analyze"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "合并 Downloads 里的所有 CSV 并输出报告"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-selected-workspace-files",
        budget=FakeBudget(),
    )

    assert calls == [
        (
            "workspace.list",
            {
                "path": "Downloads",
                "pattern": "*.csv",
                "file_type": "csv",
                "selection": "all",
            },
        ),
        (
            "data.analyze",
            {
                "paths": ["Downloads/east.csv", "Downloads/west.csv"],
                "source_kind": "csv",
                "artifact_path": "analysis-report.md",
            },
        ),
    ]
    assert seen_requests[-1]["input_resolution"]["resolved_paths"] == [
        "Downloads/east.csv",
        "Downloads/west.csv",
    ]
    resolution_payload = {
        "tool": "data.analyze",
        "field": "path",
        "requested_path": "<selected files from workspace.list>",
        "resolved_path": "Downloads/east.csv",
        "resolved_paths": ["Downloads/east.csv", "Downloads/west.csv"],
        "resolved_file_count": 2,
        "source_tool": "workspace.list",
        "source_path": "Downloads",
        "resolved_file_names": ["east.csv", "west.csv"],
        "resolved_file_name": "east.csv",
        "selection": "all",
    }
    resolution_payload["tool_call_id"] = _input_resolution_tool_call_id(timeline)
    assert [
        event for event in timeline if event["event"] == "agent.tool.input_resolved"
    ] == [
        {
            "event": "agent.tool.input_resolved",
            "detail": "data.analyze",
            **resolution_payload,
        }
    ]
    assert ("run-selected-workspace-files", "agent.tool.input_resolved", resolution_payload) in run_events


def test_runtime_tool_request_runner_skips_unresolved_selected_workspace_file() -> None:
    calls: list[dict[str, Any]] = []
    timeline = [
        _timeline(
            "agent.tool.call",
            "workspace.list",
            input_preview={"path": "Downloads", "pattern": "*.csv", "file_type": "csv"},
            result={
                "ok": True,
                "path": "Downloads",
                "entries": [
                    {"name": "sales.csv", "type": "file"},
                    {"name": "inventory.csv", "type": "file"},
                ],
            },
        )
    ]

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(tool_request)
        return {"ok": True}

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "data.analyze",
                "input": {
                    "path": "<selected file from workspace.list>",
                    "selection_source": "workspace.list",
                    "source_scope": "Downloads",
                    "pattern": "*.csv",
                    "file_type": "csv",
                },
            },
        ],
        ["data.analyze"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "分析 Downloads 里的 CSV"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-unresolved-file",
        budget=FakeBudget(),
    )

    assert calls == []
    skipped = next(event for event in timeline if event["event"] == "agent.tool.skipped")
    assert skipped["detail"] == "data.analyze"
    assert skipped["result"]["blocked_by_file_resolution"] is True
    assert skipped["result"]["recommended_tools"] == ["workspace.list"]
    assert skipped["result"]["recovery_actions"][0]["input"] == {
        "path": "Downloads",
        "pattern": "*.csv",
        "file_type": "csv",
    }


def test_runtime_tool_request_runner_resolves_selected_app_and_workspace_file() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    seen_requests: list[dict[str, Any]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        seen_requests.append(tool_request)
        if tool_name == "workspace.list":
            result = {
                "ok": True,
                "path": "Downloads",
                "entries": [{"name": "report.pdf", "type": "file", "mtime": 100}],
            }
        elif tool_name == "desktop.list_apps":
            result = {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {
                            "name": "Preview",
                            "path": "/System/Applications/Preview.app",
                            "match_score": 100,
                        }
                    ],
                },
            }
        else:
            result = {"ok": True, "action": tool_name, "data": payload}
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool, run_events=run_events)

    runner.run(
        [
            {
                "tool": "workspace.list",
                "input": {
                    "path": "Downloads",
                    "pattern": "*.pdf",
                    "file_type": "pdf",
                    "include_metadata": True,
                },
            },
            {"tool": "desktop.list_apps", "input": {"query": "pdf", "limit": 20}},
            {
                "tool": "desktop.open_path_with_app",
                "input": {
                    "app_name": "<selected app from desktop.list_apps>",
                    "query": "pdf",
                    "target_path": "<selected file from workspace.list>",
                    "selection_source": "workspace.list",
                    "selection": "最近",
                    "source_scope": "Downloads",
                    "pattern": "*.pdf",
                    "file_type": "pdf",
                },
            },
        ],
        ["workspace.list", "desktop.list_apps", "desktop.open_path_with_app"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "用能打开 PDF 的应用打开最新 PDF"}],
        timeline,
        [],
        next_iteration=1,
        run_id="run-app-file-resolution",
        budget=FakeBudget(),
    )

    assert calls[-1] == (
        "desktop.open_path_with_app",
        {"app_name": "Preview", "path": "Downloads/report.pdf"},
    )
    open_resolution = seen_requests[-1]["input_resolution"]
    assert open_resolution["source_tool"] == "desktop.list_apps"
    assert open_resolution["file_resolution_source_tool"] == "workspace.list"
    assert open_resolution["resolved_path"] == "Downloads/report.pdf"
    assert [
        event["field"]
        for event in timeline
        if event["event"] == "agent.tool.input_resolved"
    ] == ["app_name", "target_path"]
    assert any(
        event_type == "agent.tool.input_resolved"
        and payload.get("resolved_path") == "Downloads/report.pdf"
        for _run_id, event_type, payload in run_events
    )


def test_runtime_tool_request_runner_records_best_match_resolution_evidence() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline_arg: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {
                            "name": "Archive Utility",
                            "path": "/System/Applications/Utilities/Archive Utility.app",
                            "match_score": 80,
                            "match_confidence": "medium",
                        }
                    ],
                    "best_match": {
                        "name": "Arc Browser",
                        "path": "/Applications/Arc Browser.app",
                        "match_score": 100,
                        "match_confidence": "high",
                        "match_reason": "exact_name",
                        "matched_name": "Arc Browser",
                        "matched_name_source": "bundle_metadata",
                    },
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline_arg.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Arc Browser"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc Browser", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Arc"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc Browser", "limit": 20}),
        ("app.open", {"app_name": "Arc Browser"}),
    ]
    resolution = next(event for event in timeline if event["event"] == "agent.tool.input_resolved")
    assert resolution["resolved_app_name"] == "Arc Browser"
    assert resolution["app_resolution_score"] == "100"
    assert resolution["app_resolution_confidence"] == "high"
    assert resolution["app_resolution_reason"] == "exact_name"
    assert resolution["app_resolution_matched_name"] == "Arc Browser"
    assert resolution["app_resolution_matched_name_source"] == "bundle_metadata"
    assert resolution["resolved_app_path"] == "/Applications/Arc Browser.app"


def test_runtime_tool_request_runner_uses_related_discovered_app_match_name() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "matches": [{"name": "Arc Browser", "path": "/Applications/Arc Browser.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Arc"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc Browser", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Arc"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc Browser", "limit": 20}),
        ("app.open", {"app_name": "Arc Browser"}),
    ]


def test_runtime_tool_request_runner_prefers_related_app_match_over_first_candidate() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {"name": "Archive Utility", "path": "/System/Applications/Utilities/Archive Utility.app"},
                        {"name": "Arc Browser", "path": "/Applications/Arc Browser.app"},
                    ],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open",
                "data": {"app_name": payload["app_name"], "launch_verified": True},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Arc"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Arc", "limit": 20}},
            {"tool": "app.open", "input": {"app_name": "Arc"}},
        ],
        ["desktop.list_apps", "app.open"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Arc", "limit": 20}),
        ("app.open", {"app_name": "Arc Browser"}),
    ]


def test_runtime_tool_request_runner_does_not_rewrite_low_confidence_app_match() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [
                        {
                            "name": "企业微信",
                            "path": "/Applications/企业微信.app",
                            "match_score": 80,
                        },
                    ],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.focus",
                "data": {"app_name": payload["app_name"]},
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "在微信搜索文件传输助手"}]
    timeline: list[dict[str, Any]] = []

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "微信", "limit": 20}},
            {"tool": "app.focus", "input": {"app_name": "微信"}},
        ],
        ["desktop.list_apps", "app.focus"],
        FakeBroker({"ok": True}),
        messages,
        timeline,
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "微信", "limit": 20}),
        ("app.focus", {"app_name": "微信"}),
    ]
    assert not any(event["event"] == "agent.tool.input_resolved" for event in timeline)


def test_runtime_tool_request_runner_uses_discovered_app_name_for_combined_app_tool() -> None:
    calls: list[tuple[str, dict[str, Any]]] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        payload = tool_request.get("input") if isinstance(tool_request.get("input"), dict) else {}
        calls.append((tool_name, payload))
        result = (
            {
                "ok": True,
                "action": "desktop.list_apps",
                "data": {
                    "query": payload["query"],
                    "apps": [{"name": "Music", "path": "/Applications/Music.app"}],
                },
            }
            if tool_name == "desktop.list_apps"
            else {
                "ok": True,
                "action": "app.open_and_click_ui_element",
                "data": {
                    "app_name": payload["app_name"],
                    "target": payload["target"],
                    "launch_verified": True,
                },
            }
        )
        timeline.append(
            _timeline("agent.tool.call", tool_name, input_preview=payload, result=result)
        )
        return result

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "打开 Apple Music 并点击资料库"}]

    runner.run(
        [
            {"tool": "desktop.list_apps", "input": {"query": "Apple Music", "limit": 20}},
            {
                "tool": "app.open_and_click_ui_element",
                "input": {
                    "app_name": "Apple Music",
                    "target": "资料库",
                    "role_filter": "button",
                    "limit": 80,
                    "click_count": 1,
                },
            },
        ],
        ["desktop.list_apps", "app.open_and_click_ui_element"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert calls == [
        ("desktop.list_apps", {"query": "Apple Music", "limit": 20}),
        (
            "app.open_and_click_ui_element",
            {
                "app_name": "Music",
                "target": "资料库",
                "role_filter": "button",
                "limit": 80,
                "click_count": 1,
            },
        ),
    ]


def test_runtime_tool_request_runner_raises_pending_approval_with_remaining_requests() -> None:
    pending_builder = FakePendingApprovalBuilder()
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "terminal.run",
            "risk_level": "high",
            "policy_reason": "Terminal commands need review.",
            "plugin_id": "ops",
        },
    )
    messages = [{"role": "user", "content": "run command"}]
    requests = [
        {"tool": "terminal.run", "input": {"command": "echo hi"}},
        {"tool": "workspace.read", "input": {"path": "README.md"}},
    ]

    with pytest.raises(AgentApprovalRequired) as exc:
        runner.run(
            requests,
            ["terminal.run", "workspace.read"],
            FakeBroker({"ok": True}),
            messages,
            [],
            [],
            next_iteration=7,
            run_id="run-1",
            budget=FakeBudget(),
        )

    assert exc.value.pending_approval["approval_id"] == "approval-1"
    assert exc.value.pending_approval["next_iteration"] == 7
    assert exc.value.pending_approval["remaining_tool_requests"] == [requests[1]]
    assert exc.value.pending_approval["risk_level"] == "high"
    assert exc.value.pending_approval["policy_reason"] == "Terminal commands need review."
    assert exc.value.pending_approval["plugin_id"] == "ops"


def test_runtime_tool_request_runner_sanitizes_browser_type_text_before_approval() -> None:
    seen_inputs: list[dict[str, Any]] = []
    pending_builder = ToolPendingApprovalBuilder(
        approval_id_factory=lambda: "approval-browser-type-text",
        now=lambda: "2026-07-15T10:00:00Z",
    )

    def request_approval(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        seen_inputs.append(dict(tool_request.get("input") or {}))
        return {
            "ok": False,
            "approval_required": True,
            "tool": "browser.type_text",
        }

    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=request_approval,
    )
    requests = [
        {
            "tool": "browser.type_text",
            "input": {
                "selector": "input[aria-label='Search']",
                "text": "Lost in Starlight",
                "fallback_x": 360,
                "fallback_y": 140,
            },
        },
        {
            "tool": "browser.type_text",
            "input": {
                "selector": "textarea",
                "text": "next",
                "fallback_x": 400,
                "fallback_y": 240,
            },
        },
    ]

    with pytest.raises(AgentApprovalRequired) as exc_info:
        runner.run(
            requests,
            ["browser.type_text"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "search for a song"}],
            [],
            [],
            next_iteration=4,
            run_id="run-browser-type-text",
            budget=FakeBudget(),
        )

    expected_input = {
        "selector": "input[aria-label='Search']",
        "text": "Lost in Starlight",
    }
    pending = exc_info.value.pending_approval
    assert seen_inputs == [expected_input]
    assert pending["input"] == expected_input
    assert pending["tool_request"]["input"] == expected_input
    assert pending["remaining_tool_requests"][0]["input"] == {
        "selector": "textarea",
        "text": "next",
    }


@pytest.mark.parametrize(
    ("dependency_kind", "prepare_request", "prepare_result", "user_goal"),
    (
        ("missing", None, None, "send the prepared message"),
        (
            "skipped",
            {
                "tool": "terminal.run",
                "input": {"command": "prepare-message"},
                "step_id": "prepare-message",
            },
            None,
            "send the prepared message with no commands",
        ),
        (
            "failed",
            {
                "tool": "workspace.read",
                "input": {"path": "message.txt"},
                "step_id": "prepare-message",
            },
            {"ok": False, "error": "message preparation failed"},
            "send the prepared message",
        ),
        (
            "unverified",
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "hello"},
                "step_id": "prepare-message",
                "requires_post_action_verification": True,
            },
            {
                "ok": True,
                "action": "desktop.safe_type_text",
                "data": {"explicit_user_text": True},
            },
            "send the prepared message",
        ),
    ),
)
def test_runtime_tool_request_runner_blocks_approval_when_dependency_is_not_successful(
    dependency_kind: str,
    prepare_request: dict[str, Any] | None,
    prepare_result: dict[str, Any] | None,
    user_goal: str,
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        calls.append(tool_name)
        result = (
            {
                "ok": False,
                "approval_required": True,
                "tool": "desktop.submit_foreground",
                "risk_level": "high",
                "policy_reason": "Sending requires approval.",
            }
            if tool_name == "desktop.submit_foreground"
            else dict(prepare_result or {"ok": True})
        )
        timeline.append(
            _timeline(
                "agent.tool.call",
                tool_name,
                step_id=str(tool_request.get("step_id") or ""),
                result=result,
            )
        )
        return result

    requests = [
        *([dict(prepare_request)] if prepare_request is not None else []),
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "step_id": "send-message",
            "depends_on": ["prepare-message"],
            "approval_required": True,
        },
    ]
    allowed_tools = [
        "terminal.run",
        "workspace.read",
        "desktop.safe_type_text",
        "desktop.submit_foreground",
    ]

    with pytest.raises(
        AgentDirectOutcomeUnverified,
        match="prepare-message",
    ) as exc_info:
        _runner(
            pending_approval_builder=pending_builder,
            call_agent_tool=call_agent_tool,
            run_events=run_events,
        ).run(
            requests,
            allowed_tools,
            FakeBroker({"ok": True}),
            [{"role": "user", "content": user_goal}],
            timeline,
            [],
            next_iteration=7,
            run_id="run-dependent-approval",
            budget=FakeBudget(),
        )

    assert exc_info.value.reason == "approval_dependency_unverified"
    assert exc_info.value.tool_name == "desktop.submit_foreground"
    assert pending_builder.calls == []
    skipped = _last_event(timeline, "agent.tool.skipped")
    assert skipped["detail"] == "desktop.submit_foreground"
    assert skipped["status"] == "blocked"
    assert skipped["result"]["blocked_by_approval_dependency"] is True
    assert skipped["result"]["dependency_statuses"] == {
        "prepare-message": dependency_kind,
    }
    assert skipped["result"][f"{dependency_kind}_dependency_step_ids"] == [
        "prepare-message"
    ]
    assert any(
        event_type == "agent.tool.skipped"
        and isinstance(payload.get("result"), dict)
        and payload["result"].get("blocked_by_approval_dependency") is True
        for _run_id, event_type, payload in run_events
    )


def test_runtime_tool_request_runner_allows_approval_after_dependency_succeeded_before_resume(
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.safe_type_text",
            step_id="prepare-message",
            decision_id="decision-resumed-message",
            result={"ok": True, "action": "desktop.safe_type_text"},
        )
    ]
    request = {
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
        "step_id": "send-message",
        "decision_id": "decision-resumed-message",
        "depends_on": ["prepare-message"],
        "approval_required": True,
    }
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "desktop.submit_foreground",
        },
    )

    with pytest.raises(AgentApprovalRequired):
        runner.run(
            [request],
            ["desktop.submit_foreground"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "send the prepared message"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-resumed-dependent-approval",
            budget=FakeBudget(),
        )

    assert len(pending_builder.calls) == 1
    assert not any(
        event.get("event") == "agent.tool.skipped"
        and event.get("detail") == "desktop.submit_foreground"
        for event in timeline
    )


@pytest.mark.parametrize(
    ("expected_app_name", "active_window_result", "expected_exception"),
    (
        pytest.param(
            "Typora",
            {
                "ok": True,
                "action": "desktop.active_window",
                "data": {"app_name": "Typora"},
            },
            AgentDirectOutcomeUnverified,
            id="matching-app-with-incomplete-runtime-identity-fails-closed",
        ),
        pytest.param(
            "Typora",
            {
                "ok": True,
                "action": "desktop.active_window",
                "data": {"app_name": "Safari"},
            },
            AgentDirectOutcomeUnverified,
            id="different-foreground-app",
        ),
        pytest.param(
            "Notes",
            {
                "ok": True,
                "action": "desktop.active_window",
                "data": {
                    "app_name": "Notes Helper",
                    "focus_verified": True,
                },
            },
            AgentDirectOutcomeUnverified,
            id="substring-collision-cannot-bypass-strict-identity",
        ),
        pytest.param(
            "Typora",
            {
                "ok": False,
                "action": "desktop.active_window",
                "data": {"app_name": "Typora"},
            },
            AgentDirectOutcomeUnverified,
            id="failed-active-window-observation",
        ),
        pytest.param(
            "",
            {
                "ok": True,
                "action": "desktop.active_window",
                "data": {"app_name": "Typora"},
            },
            AgentDirectOutcomeUnverified,
            id="missing-expected-app-identity",
        ),
    ),
)
def test_runtime_tool_request_runner_uses_correlated_active_window_identity_for_dependency_verification(
    expected_app_name: str,
    active_window_result: dict[str, Any],
    expected_exception: type[Exception],
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    decision_id = "decision-composite-foreground"
    dependency_step_id = "open-selected-discovered-app"
    timeline = [
        _timeline(
            "agent.tool.call",
            "app.open_and_safe_shortcut",
            step_id=dependency_step_id,
            decision_id=decision_id,
            result={
                "ok": True,
                "action": "app.open_and_safe_shortcut",
                "data": {
                    "app_name": "Typora",
                    "foreground_action": "safe_shortcut",
                    "shortcut_action": "new_document",
                },
            },
        ),
        _timeline(
            "agent.tool.call",
            "desktop.active_window",
            step_id=f"{dependency_step_id}:runtime-verify",
            source_step_id=dependency_step_id,
            decision_id=decision_id,
            result=active_window_result,
        ),
    ]
    requests = [
        {
            "tool": "app.focus_and_safe_type_text",
            "input": {"app_name": expected_app_name or "Typora", "text": "周报"},
            "step_id": "type-selected-text",
            "decision_id": decision_id,
            "depends_on": [dependency_step_id],
            "approval_required": True,
        },
        {
            "tool": "app.open_and_safe_shortcut",
            "input": {"app_name": expected_app_name, "action": "new_document"},
            "step_id": dependency_step_id,
            "decision_id": decision_id,
            "requires_post_action_verification": True,
        },
    ]
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "app.focus_and_safe_type_text",
        },
    )

    with pytest.raises(expected_exception):
        runner.run(
            requests,
            ["app.focus_and_safe_type_text", "app.open_and_safe_shortcut"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Open Typora, create a document, and type 周报"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-composite-foreground-dependency",
            budget=FakeBudget(),
        )

    if expected_exception is AgentApprovalRequired:
        assert len(pending_builder.calls) == 1
    else:
        assert pending_builder.calls == []
        blocked = _last_event(timeline, "agent.tool.skipped")["result"]
        assert blocked["dependency_statuses"] == {dependency_step_id: "unverified"}


@pytest.mark.parametrize(
    ("approval_app_name", "expected_exception"),
    (
        (
            "WeChat",
            AgentDirectOutcomeUnverified,
        ),
        ("Slack", AgentDirectOutcomeUnverified),
        ("", AgentDirectOutcomeUnverified),
    ),
)
def test_runtime_tool_request_runner_inherits_app_identity_from_approval_action_context(
    approval_app_name: str,
    expected_exception: type[Exception],
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    decision_id = "decision-app-scoped-submit"
    dependency_step_id = "focus-submit-app"
    timeline = [
        _timeline(
            "agent.tool.call",
            "app.focus",
            step_id=dependency_step_id,
            decision_id=decision_id,
            result={
                "ok": True,
                "action": "app.focus",
                "data": {"app_name": "WeChat", "focus_status": "focused"},
            },
        ),
        _timeline(
            "agent.tool.call",
            "desktop.active_window",
            step_id=f"{dependency_step_id}:runtime-verify",
            source_step_id=dependency_step_id,
            decision_id=decision_id,
            result={
                "ok": True,
                "action": "desktop.active_window",
                "data": {"app_name": "WeChat"},
            },
        ),
    ]
    approval_request = {
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
        "step_id": "send-message",
        "decision_id": decision_id,
        "depends_on": [dependency_step_id],
        "approval_required": True,
        "action_target": {
            "kind": "desktop_app",
            "action": "dispatch_submit",
            "app_name": approval_app_name,
        },
    }
    dependency_request = {
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
        "step_id": dependency_step_id,
        "decision_id": decision_id,
        "requires_post_action_verification": True,
    }
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "desktop.submit_foreground",
        },
    )

    with pytest.raises(expected_exception):
        runner.run(
            [approval_request, dependency_request],
            ["desktop.submit_foreground", "app.focus"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Send the current WeChat message"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-app-scoped-submit",
            budget=FakeBudget(),
        )

    if expected_exception is AgentApprovalRequired:
        assert len(pending_builder.calls) == 1
    else:
        assert pending_builder.calls == []


@pytest.mark.parametrize(
    ("remaining_requests", "expected"),
    (
        pytest.param(
            [
                {
                    "tool": "desktop.active_window",
                    "source_step_id": "prepare-app",
                    "depends_on": ["prepare-app"],
                    "runtime_stage": "verify",
                },
                {
                    "tool": "app.focus_and_safe_type_text",
                    "depends_on": ["prepare-app"],
                    "approval_required": True,
                    "runtime_stage": "operate",
                    "verification_targets": [{"step_id": "prepare-app"}],
                },
            ],
            True,
            id="verifier-before-dependent-step",
        ),
        pytest.param(
            [
                {
                    "tool": "app.focus_and_safe_type_text",
                    "depends_on": ["prepare-app"],
                    "approval_required": True,
                    "runtime_stage": "operate",
                    "verification_targets": [{"step_id": "prepare-app"}],
                },
                {
                    "tool": "desktop.ui_elements",
                    "runtime_stage": "verify",
                    "verification_targets": [{"step_id": "prepare-app"}],
                },
            ],
            False,
            id="dependent-step-before-deferred-verifier",
        ),
    ),
)
def test_post_action_verification_is_not_deferred_past_a_dependent_step(
    remaining_requests: list[dict[str, Any]],
    expected: bool,
) -> None:
    assert tool_execution_module._remaining_requests_include_post_action_verification(
        remaining_requests,
        source_tool_name="app.open",
        allowed_tools=["desktop.active_window", "desktop.ui_elements"],
        source_step_id="prepare-app",
    ) is expected


@pytest.mark.parametrize(
    ("verifier_identity", "expected"),
    [
        ({"source_request_id": "request-action"}, False),
        ({"source_tool_call_id": "call-action"}, True),
        (
            {
                "source_request_id": "request-action",
                "source_tool_call_id": "call-action",
            },
            True,
        ),
        (
            {
                "source_request_id": "request-action",
                "source_tool_call_id": "call-other",
            },
            False,
        ),
        ({"source_request_id": "request-other"}, False),
        ({}, False),
    ],
)
def test_step_less_post_action_verification_requires_strong_source_identity(
    verifier_identity: dict[str, str],
    expected: bool,
) -> None:
    assert tool_execution_module._remaining_requests_include_post_action_verification(
        [
            {
                "tool": "desktop.ui_elements",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                **verifier_identity,
            }
        ],
        source_tool_name="desktop.safe_type_text",
        allowed_tools=["desktop.ui_elements"],
        source_step_id="",
        source_request_id="request-action",
        source_tool_call_id="call-action",
    ) is expected


def test_step_less_post_action_verification_is_not_deferred_past_mutation() -> None:
    assert tool_execution_module._remaining_requests_include_post_action_verification(
        [
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "second mutation"},
                "runtime_stage": "operate",
                "runtime_role": "execute_action",
                "source_request_id": "request-action",
            },
            {
                "tool": "desktop.ui_elements",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "source_request_id": "request-action",
                "source_tool_call_id": "call-action",
            },
        ],
        source_tool_name="desktop.safe_type_text",
        allowed_tools=["desktop.ui_elements"],
        source_step_id="",
        source_request_id="request-action",
        source_tool_call_id="call-action",
    ) is False


def test_step_correlated_verifier_rejects_conflicting_source_identity() -> None:
    assert tool_execution_module._remaining_requests_include_post_action_verification(
        [
            {
                "tool": "desktop.active_window",
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "depends_on": ["prepare-app"],
                "source_request_id": "request-prior-action",
            }
        ],
        source_tool_name="app.open",
        allowed_tools=["desktop.active_window"],
        source_step_id="prepare-app",
        source_request_id="request-current-action",
        source_tool_call_id="call-current-action",
    ) is False


def test_step_less_post_action_verifier_reuse_is_immediate_and_correlated() -> None:
    action_request = {
        "tool": "browser.click",
        "input": {"selector": "#first-result"},
        "request_id": "request-action",
        "tool_call_id": "call-action",
        "runtime_stage": "operate",
        "requires_post_action_verification": True,
    }
    action_result = {
        "ok": True,
        "action": "browser.click",
        "data": {"selector": "#first-result"},
    }
    correlated_verifier = {
        "tool": "browser.current_page",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "source_request_id": "request-action",
        "source_tool_call_id": "call-action",
    }

    assert tool_execution_module._post_action_verification_request(
        "browser.click",
        action_request,
        action_result,
        allowed_tools=["browser.current_page"],
        remaining_requests=[correlated_verifier],
        active_window_target=None,
    ) == {}

    inserted = tool_execution_module._post_action_verification_request(
        "browser.click",
        action_request,
        action_result,
        allowed_tools=["browser.current_page"],
        remaining_requests=[
            {
                "tool": "browser.type_text",
                "input": {"selector": "#search", "text": "next mutation"},
                "runtime_stage": "operate",
            },
            correlated_verifier,
        ],
        active_window_target=None,
    )
    assert inserted["tool"] == "browser.current_page"
    assert inserted["source_request_id"] == "request-action"
    assert inserted["source_tool_call_id"] == "call-action"


@pytest.mark.parametrize(
    (
        "action_tool",
        "action_input",
        "action_result",
        "allowed_tools",
        "source_step_id",
        "candidate_verifier",
        "expected_verifier_tool",
    ),
    [
        pytest.param(
            "browser.click",
            {"selector": "#first-result"},
            {"ok": True, "action": "browser.click"},
            ["browser.current_page", "desktop.active_window"],
            "",
            {"tool": "desktop.active_window"},
            "browser.current_page",
            id="step-less-browser-rejects-desktop-verifier",
        ),
        pytest.param(
            "browser.click",
            {"selector": "#first-result"},
            {"ok": True, "action": "browser.click"},
            ["browser.current_page", "desktop.safe_type_text"],
            "",
            {
                "tool": "desktop.safe_type_text",
                "input": {"text": "unrelated mutation"},
            },
            "browser.current_page",
            id="step-less-browser-rejects-effectful-desktop-tool",
        ),
        pytest.param(
            "desktop.safe_type_text",
            {"text": "hello"},
            {"ok": True, "action": "desktop.safe_type_text"},
            ["desktop.ui_elements", "browser.current_page"],
            "type-message",
            {"tool": "browser.current_page", "depends_on": ["type-message"]},
            "desktop.ui_elements",
            id="step-correlated-foreground-rejects-browser-verifier",
        ),
        pytest.param(
            "browser.click",
            {"selector": "#first-result"},
            {"ok": True, "action": "browser.click"},
            ["browser.current_page", "browser.type_text"],
            "click-result",
            {
                "tool": "browser.type_text",
                "input": {"selector": "#search", "text": "mutation"},
                "depends_on": ["click-result"],
            },
            "browser.current_page",
            id="step-correlated-rejects-effectful-same-domain-tool",
        ),
    ],
)
def test_existing_post_action_verifier_must_match_read_only_capability(
    action_tool: str,
    action_input: dict[str, Any],
    action_result: dict[str, Any],
    allowed_tools: list[str],
    source_step_id: str,
    candidate_verifier: dict[str, Any],
    expected_verifier_tool: str,
) -> None:
    action_request = {
        "tool": action_tool,
        "input": action_input,
        "request_id": "request-action",
        "tool_call_id": "call-action",
        "runtime_stage": "operate",
        "requires_post_action_verification": True,
    }
    if source_step_id:
        action_request["step_id"] = source_step_id
    verifier = {
        **candidate_verifier,
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "source_request_id": "request-action",
        "source_tool_call_id": "call-action",
    }

    inserted = tool_execution_module._post_action_verification_request(
        action_tool,
        action_request,
        action_result,
        allowed_tools=allowed_tools,
        remaining_requests=[verifier],
        active_window_target=None,
    )

    assert inserted["tool"] == expected_verifier_tool
    assert inserted["source_request_id"] == "request-action"
    assert inserted["source_tool_call_id"] == "call-action"


@pytest.mark.parametrize(
    ("fact_decision_id", "fact_tool_call_id"),
    (
        ("", "call-prepare-current"),
        ("decision-prior-message", "call-prepare-current"),
        ("decision-current-message", ""),
        ("decision-current-message", "call-prepare-prior"),
    ),
)
def test_runtime_tool_request_runner_blocks_approval_from_stale_dependency_facts(
    fact_decision_id: str,
    fact_tool_call_id: str,
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.safe_type_text",
            step_id="prepare-message",
            decision_id=fact_decision_id,
            tool_call_id=fact_tool_call_id,
            result={"ok": True, "action": "desktop.safe_type_text"},
        )
    ]
    requests = [
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "step_id": "send-message",
            "decision_id": "decision-current-message",
            "depends_on": ["prepare-message"],
            "approval_required": True,
        },
        {
            "tool": "desktop.safe_type_text",
            "tool_call_id": "call-prepare-current",
            "input": {"text": "hello"},
            "step_id": "prepare-message",
            "decision_id": "decision-current-message",
        },
    ]
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "desktop.submit_foreground",
        },
    )

    with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
        runner.run(
            requests,
            ["desktop.submit_foreground", "desktop.safe_type_text"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "send the prepared message"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-stale-dependent-approval",
            budget=FakeBudget(),
        )

    assert exc_info.value.reason == "approval_dependency_unverified"
    assert pending_builder.calls == []
    blocked = _last_event(timeline, "agent.tool.skipped")["result"]
    assert blocked["dependency_statuses"] == {"prepare-message": "unverified"}


def test_approval_mutation_dependency_edge_is_not_a_verifier() -> None:
    dependency = {
        "tool": "desktop.inspect_app",
        "step_id": "inspect-compose-ui",
        "request_id": "request-inspect-compose-ui",
    }
    approval_mutation = _timeline(
        "agent.tool.call",
        "app.focus_and_type_into_ui_element",
        runtime_stage="operate",
        runtime_role="execute",
        step_id="fill-recipient",
        request_id="request-fill-recipient",
        depends_on=["inspect-compose-ui"],
        result={
            "ok": False,
            "approval_required": True,
            "action": "app.focus_and_type_into_ui_element",
        },
    )

    assert tool_execution_module._approval_dependency_verifier_correlates(
        "inspect-compose-ui",
        dependency,
        approval_mutation,
        approval_mutation,
    ) is False

    declared_verifier = _timeline(
        "agent.tool.call",
        "desktop.ui_elements",
        runtime_stage="verify",
        runtime_role="verify_result",
        step_id="verify-compose-ui",
        request_id="request-verify-compose-ui",
        source_request_id="request-inspect-compose-ui",
        source_step_id="inspect-compose-ui",
        depends_on=["inspect-compose-ui"],
        result={"ok": True, "action": "desktop.ui_elements"},
    )
    assert tool_execution_module._approval_dependency_verifier_correlates(
        "inspect-compose-ui",
        dependency,
        declared_verifier,
        declared_verifier,
    ) is True


def _intrinsic_focus_approval_dependency_events() -> tuple[dict, dict, list[dict]]:
    dependency = {
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
        "decision_id": "decision-focus-approval",
        "plan_id": "plan-focus-approval",
        "tool_plan_id": "tool-plan-focus-approval",
        "step_id": "focus-app",
        "request_id": "request-focus-app",
        "tool_call_id": "call-focus-app",
        "requires_post_action_verification": True,
    }
    approval = {
        "tool": "desktop.close_window",
        "decision_id": dependency["decision_id"],
        "plan_id": dependency["plan_id"],
        "tool_plan_id": dependency["tool_plan_id"],
        "step_id": "close-window",
        "request_id": "request-close-window",
        "tool_call_id": "call-close-window",
        "depends_on": [dependency["step_id"]],
    }
    source = {
        "event": "agent.tool.call",
        "tool": dependency["tool"],
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "visibility": "internal",
        "run_id": "run-focus-approval",
        "decision_id": dependency["decision_id"],
        "plan_id": dependency["plan_id"],
        "tool_plan_id": dependency["tool_plan_id"],
        "step_id": dependency["step_id"],
        "request_id": dependency["request_id"],
        "tool_call_id": dependency["tool_call_id"],
        "input_preview": dict(dependency["input"]),
        "action_target": {
            "kind": "desktop_app",
            "action": "focus_app",
            "app_name": "微信",
        },
        "result": {
            "ok": True,
            "action": "app.focus",
            "postcondition_verified": True,
            "_runtime_execution_provenance": {
                "source": "local_tool_broker",
                "version": 1,
            },
            "data": {
                "app_name": "WeChat",
                "focus_verified": True,
                "focus_status": "frontmost",
                "frontmost_app": "WeChat",
                "postcondition_verified": True,
            },
        },
    }
    receipt = {
        "event": "agent.tool.call",
        "tool": "desktop.active_window",
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "visibility": "internal",
        "source": "runtime_native_postcondition_receipt",
        "run_id": source["run_id"],
        "decision_id": dependency["decision_id"],
        "plan_id": dependency["plan_id"],
        "tool_plan_id": dependency["tool_plan_id"],
        "step_id": "verify-focus-app",
        "request_id": "request-verify-focus-app",
        "tool_call_id": "call-verify-focus-app",
        "source_step_id": dependency["step_id"],
        "source_request_id": dependency["request_id"],
        "source_tool_call_id": dependency["tool_call_id"],
        "result": {
            "ok": True,
            "action": "desktop.active_window",
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "source_tool": dependency["tool"],
            "source_step_id": dependency["step_id"],
            "source_request_id": dependency["request_id"],
            "source_tool_call_id": dependency["tool_call_id"],
            "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
            "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
            "verified_observed_state": "focused",
        },
    }
    return dependency, approval, [source, receipt]


def test_exact_intrinsic_native_receipt_unlocks_approval_dependency() -> None:
    dependency, approval, timeline = _intrinsic_focus_approval_dependency_events()

    status = tool_execution_module._approval_verified_dependency_status(
        dependency["step_id"],
        dependency,
        timeline,
        decision_id=dependency["decision_id"],
        approval_request=approval,
        run_id="run-focus-approval",
    )

    assert status == "verified"


def test_trusted_observation_receipt_projection_preserves_source_request_id() -> None:
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    runner = _runner(call_agent_tool=lambda *_args, **_kwargs: {"ok": True}, run_events=run_events)
    tool_request = {
        "tool": "desktop.active_window",
        "input": {"app_name": "PixelForge"},
        "run_id": "run-open-path",
        "decision_id": "decision-open-path",
        "plan_id": "plan-open-path",
        "tool_plan_id": "tool-plan-open-path",
        "step_id": "verify-open-path",
        "request_id": "request-verify-open-path",
        "tool_call_id": "call-verify-open-path",
    }
    tool_result = {
        "ok": True,
        "action": "desktop.active_window",
        "postcondition_verified": True,
        "verification_satisfied_by_native_receipt": True,
        "source_tool": "desktop.open_path_with_app",
        "source_step_id": "open-selected-discovered-app",
        "source_request_id": "request-open-path",
        "source_tool_call_id": "call-open-path",
        "verified_observed_state": "fulfilled",
    }
    receipt = {
        "source_tool": "desktop.open_path_with_app",
        "source_step_id": "open-selected-discovered-app",
        "source_request_id": "request-open-path",
        "source_tool_call_id": "call-open-path",
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "verified_observed_state": "fulfilled",
    }
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.active_window",
            run_id="run-open-path",
            decision_id="decision-open-path",
            plan_id="plan-open-path",
            tool_plan_id="tool-plan-open-path",
            step_id="verify-open-path",
            request_id="request-verify-open-path",
            tool_call_id="call-verify-open-path",
            source="native_runtime",
            visibility="internal",
            result={"ok": True, "action": "desktop.active_window"},
        )
    ]

    runner._append_trusted_observation_receipt_projection(
        tool_request,
        tool_name="desktop.active_window",
        tool_result=tool_result,
        receipt=receipt,
        timeline=timeline,
        run_id="run-open-path",
    )

    upgraded = timeline[0]
    assert upgraded["source"] == "runtime_native_postcondition_receipt"
    assert upgraded["source_request_id"] == "request-open-path"
    assert upgraded["result"]["source_request_id"] == "request-open-path"

    projected = timeline[-1]
    assert projected["event"] == "agent.tool.call"
    assert projected["source_request_id"] == "request-open-path"
    assert projected["result"]["source_request_id"] == "request-open-path"


@pytest.mark.parametrize(
    ("field", "forged_value"),
    (
        ("source_request_id", "request-foreign"),
        ("source_tool_call_id", "call-foreign"),
        ("source_step_id", "step-foreign"),
        ("provider_id", "provider-foreign"),
        ("verified_observed_state", "fulfilled"),
    ),
)
def test_forged_intrinsic_native_receipt_cannot_unlock_approval_dependency(
    field: str,
    forged_value: str,
) -> None:
    dependency, approval, timeline = _intrinsic_focus_approval_dependency_events()
    receipt = timeline[-1]
    receipt["result"] = {**receipt["result"], field: forged_value}
    if field in {"source_request_id", "source_tool_call_id", "source_step_id"}:
        receipt[field] = forged_value

    status = tool_execution_module._approval_verified_dependency_status(
        dependency["step_id"],
        dependency,
        timeline,
        decision_id=dependency["decision_id"],
        approval_request=approval,
        run_id="run-focus-approval",
    )

    assert status == "unverified"


@pytest.mark.parametrize(
    ("intended_text", "observed_element", "expected_exception"),
    (
        pytest.param(
            "hello",
            {"role": "AXTextArea", "name": "Message", "value": "different draft"},
            AgentDirectOutcomeUnverified,
            id="wrong-editable-value",
        ),
        pytest.param(
            "hello",
            {"role": "AXButton", "name": "hello"},
            AgentDirectOutcomeUnverified,
            id="short-button-label-only",
        ),
        pytest.param(
            "Atlas launch review: confirm the desktop Agent release checklist.",
            {
                "role": "AXButton",
                "name": "Atlas launch review: confirm the desktop Agent release checklist.",
            },
            AgentDirectOutcomeUnverified,
            id="long-button-label-only",
        ),
        pytest.param(
            "hello",
            {"role": "AXTextField", "name": "Message", "value": "hello"},
            AgentApprovalRequired,
            id="short-editable-exact",
        ),
        pytest.param(
            "Atlas launch review: confirm the desktop Agent release checklist.",
            {
                "role": "AXTextArea",
                "name": "Message",
                "value": "Atlas launch review: confirm the desktop Agent release checklist.",
            },
            AgentApprovalRequired,
            id="long-editable-anchor",
        ),
    ),
)
def test_runtime_tool_request_runner_requires_typed_content_semantic_verification(
    intended_text: str,
    observed_element: dict[str, Any],
    expected_exception: type[Exception],
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.safe_type_text",
            step_id="prepare-message",
            decision_id="decision-typed-message",
            tool_call_id="call-prepare-message",
            result={"ok": True, "action": "desktop.safe_type_text"},
        ),
        _timeline(
            "agent.tool.call",
            "desktop.ui_elements",
            step_id="verify-prepare-message",
            source_step_id="prepare-message",
            source_request_id="request-prepare-message",
            decision_id="decision-typed-message",
            tool_call_id="call-verify-message",
            result={
                "ok": True,
                "action": "desktop.ui_elements",
                "data": {
                    "app_name": "WeChat",
                    "count": 1,
                    "elements": [observed_element],
                },
            },
        ),
        _timeline(
            "agent.task.todo.updated",
            "Prepare message",
            step_id="prepare-message",
            decision_id="decision-typed-message",
            status="completed",
            verified_by_step_id="verify-prepare-message",
            verification_tool="desktop.ui_elements",
        ),
    ]
    requests = [
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "step_id": "send-message",
            "decision_id": "decision-typed-message",
            "depends_on": ["prepare-message"],
            "approval_required": True,
        },
        {
            "tool": "desktop.safe_type_text",
            "tool_call_id": "call-prepare-message",
            "request_id": "request-prepare-message",
            "input": {"text": intended_text},
            "step_id": "prepare-message",
            "decision_id": "decision-typed-message",
            "requires_post_action_verification": True,
        },
    ]
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "desktop.submit_foreground",
        },
    )

    with pytest.raises(expected_exception):
        runner.run(
            requests,
            ["desktop.submit_foreground", "desktop.safe_type_text"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": f"send {intended_text}"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-semantic-dependent-approval",
            budget=FakeBudget(),
        )

    if expected_exception is AgentDirectOutcomeUnverified:
        assert pending_builder.calls == []
        blocked = _last_event(timeline, "agent.tool.skipped")["result"]
        assert blocked["dependency_statuses"] == {"prepare-message": "unverified"}
    else:
        assert len(pending_builder.calls) == 1


@pytest.mark.parametrize(
    ("observed_element", "expected_exception"),
    (
        pytest.param(
            {"role": "AXButton", "name": "Cancel"},
            AgentDirectOutcomeUnverified,
            id="unrelated-target",
        ),
        pytest.param(
            {"role": "AXButton", "name": "Send"},
            AgentApprovalRequired,
            id="matching-target-and-role",
        ),
    ),
)
def test_runtime_tool_request_runner_requires_click_target_semantic_verification(
    observed_element: dict[str, Any],
    expected_exception: type[Exception],
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline = [
        _timeline(
            "agent.tool.call",
            "desktop.search_submit",
            step_id="prepare-search-results",
            decision_id="decision-click-target",
            tool_call_id="call-search-submit",
            result={"ok": True, "action": "desktop.search_submit"},
        ),
        _timeline(
            "agent.tool.call",
            "desktop.ui_elements",
            step_id="verify-search-results",
            source_step_id="prepare-search-results",
            source_request_id="request-search-submit",
            decision_id="decision-click-target",
            tool_call_id="call-verify-search-results",
            result={
                "ok": True,
                "action": "desktop.ui_elements",
                "data": {
                    "app_name": "WeChat",
                    "count": 1,
                    "elements": [observed_element],
                },
            },
        ),
        _timeline(
            "agent.task.checkpoint.updated",
            "Search results ready",
            step_id="prepare-search-results",
            decision_id="decision-click-target",
            status="completed",
            verified_by_step_id="verify-search-results",
            verification_tool="desktop.ui_elements",
        ),
    ]
    requests = [
        {
            "tool": "desktop.click_ui_element",
            "input": {
                "target": "Send",
                "role_filter": "button",
                "click_count": 1,
            },
            "step_id": "click-send",
            "decision_id": "decision-click-target",
            "depends_on": ["prepare-search-results"],
            "approval_required": True,
        },
        {
            "tool": "desktop.search_submit",
            "tool_call_id": "call-search-submit",
            "request_id": "request-search-submit",
            "input": {},
            "step_id": "prepare-search-results",
            "decision_id": "decision-click-target",
            "requires_post_action_verification": True,
        },
    ]
    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "approval_required": True,
            "tool": "desktop.click_ui_element",
        },
    )

    with pytest.raises(expected_exception):
        runner.run(
            requests,
            ["desktop.click_ui_element", "desktop.search_submit"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "click Send"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-click-target-dependent-approval",
            budget=FakeBudget(),
        )

    if expected_exception is AgentDirectOutcomeUnverified:
        assert pending_builder.calls == []
        blocked = _last_event(timeline, "agent.tool.skipped")["result"]
        assert blocked["dependency_statuses"] == {
            "prepare-search-results": "unverified"
        }
    else:
        assert len(pending_builder.calls) == 1


@pytest.mark.parametrize(
    ("observed_element", "expected_exception"),
    (
        pytest.param(
            {"role": "AXTextField", "name": "Search", "value": ""},
            AgentApprovalRequired,
            id="matching-search-field-pauses-before-type",
        ),
        pytest.param(
            {"role": "AXTextField", "name": "Address", "value": ""},
            AgentDirectOutcomeUnverified,
            id="wrong-field-never-reaches-approval-or-type",
        ),
    ),
)
def test_app_search_click_requires_observed_target_before_approval_and_type(
    observed_element: dict[str, Any],
    expected_exception: type[Exception],
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline: list[dict[str, Any]] = []
    calls: list[str] = []
    decision_id = "decision-explicit-search-click"

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(tool_request.get("tool") or "")
        calls.append(tool_name)
        if tool_name == "desktop.inspect_app":
            result = {
                "ok": True,
                "action": "desktop.inspect_app",
                "data": {
                    "app_name": "Google Chrome",
                    "ready_for_foreground_action": True,
                    "count": 1,
                    "elements": [observed_element],
                },
            }
            timeline.append(
                _timeline(
                    "agent.tool.call",
                    tool_name,
                    step_id="inspect-app-search-field",
                    decision_id=decision_id,
                    tool_call_id=str(tool_request.get("tool_call_id") or ""),
                    result=result,
                )
            )
            return result
        if tool_name == "app.focus_and_click_ui_element":
            return {
                "ok": False,
                "approval_required": True,
                "tool": tool_name,
                "risk_level": "medium",
                "policy_reason": "Semantic UI clicks require approval.",
            }
        raise AssertionError(f"typing/verification ran before click approval: {tool_name}")

    requests = [
        {
            "tool": "desktop.inspect_app",
            "input": {
                "app_name": "Google Chrome",
                "open_if_needed": False,
                "focus": True,
                "role_filter": "text",
                "limit": 80,
            },
            "step_id": "inspect-app-search-field",
            "decision_id": decision_id,
            "runtime_stage": "discover",
            "requires_observation": True,
        },
        {
            "tool": "app.focus_and_click_ui_element",
            "input": {
                "app_name": "Google Chrome",
                "target": "Search",
                "role_filter": "text",
                "click_count": 1,
                "limit": 80,
            },
            "step_id": "focus-app-search-field",
            "decision_id": decision_id,
            "depends_on": ["inspect-app-search-field"],
            "approval_required": True,
            "action_target": {
                "kind": "desktop_app",
                "action": "click_ui",
                "app_name": "Google Chrome",
                "query": "yachiyo",
                "target": "Search",
                "role_filter": "text",
            },
        },
        {
            "tool": "desktop.safe_type_text",
            "input": {"text": "yachiyo"},
            "step_id": "type-app-search-query",
            "decision_id": decision_id,
            "depends_on": ["focus-app-search-field"],
            "action_target": {
                "kind": "desktop_app",
                "action": "type_ui",
                "app_name": "Google Chrome",
                "query": "yachiyo",
                "target": "Search",
                "role_filter": "text",
            },
        },
        {
            "tool": "desktop.ui_elements",
            "input": {
                "app_name": "Google Chrome",
                "role_filter": "text",
                "limit": 80,
            },
            "step_id": "verify-desktop-result",
            "decision_id": decision_id,
            "depends_on": ["type-app-search-query"],
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "task_verification_targets": [
                {"step_id": "type-app-search-query"},
            ],
        },
    ]

    with pytest.raises(expected_exception):
        _runner(
            pending_approval_builder=pending_builder,
            call_agent_tool=call_agent_tool,
        ).run(
            requests,
            [
                "desktop.inspect_app",
                "app.focus_and_click_ui_element",
                "desktop.safe_type_text",
                "desktop.ui_elements",
            ],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Chrome click Search then type yachiyo"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-explicit-search-click",
            budget=FakeBudget(),
        )

    assert calls == ["desktop.inspect_app", "app.focus_and_click_ui_element"]
    if expected_exception is AgentApprovalRequired:
        assert len(pending_builder.calls) == 1
        assert [
            request["tool"]
            for request in pending_builder.calls[0]["remaining_tool_requests"]
        ] == ["desktop.safe_type_text", "desktop.ui_elements"]
    else:
        assert pending_builder.calls == []


def test_runtime_tool_request_runner_blocks_click_approval_when_target_preparation_is_missing(
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline: list[dict[str, Any]] = []
    request = {
        "tool": "desktop.click_ui_element",
        "input": {"target": "first result", "click_count": 1},
        "step_id": "click-search-result",
        "depends_on": ["prepare-search-results"],
        "approval_required": True,
    }

    def request_approval(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = {"ok": False, "approval_required": True}
        timeline.append(
            _timeline(
                "agent.tool.call",
                str(tool_request.get("tool") or ""),
                step_id=str(tool_request.get("step_id") or ""),
                result=result,
            )
        )
        return result

    runner = _runner(
        pending_approval_builder=pending_builder,
        call_agent_tool=request_approval,
    )

    with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
        runner.run(
            [request],
            ["desktop.click_ui_element"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "click the first search result"}],
            timeline,
            [],
            next_iteration=2,
            run_id="run-click-dependent-approval",
            budget=FakeBudget(),
        )

    assert exc_info.value.tool_name == "desktop.click_ui_element"
    assert pending_builder.calls == []
    blocked = _last_event(timeline, "agent.tool.skipped")["result"]
    assert blocked["dependency_statuses"] == {"prepare-search-results": "missing"}


def test_runtime_tool_request_runner_adds_active_window_target_after_app_control() -> None:
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(tool_request, *_args, **_kwargs):
        seen_requests.append(tool_request)
        if tool_request["tool"] == "app.open":
            return {
                "ok": True,
                "data": {"app_name": str(tool_request["input"].get("app_name") or "")},
            }
        if tool_request["tool"] == "desktop.active_window":
            return {"ok": True, "data": {"app_name": "Safari"}}
        raise AssertionError(f"unexpected tool: {tool_request['tool']}")

    runner = _runner(call_agent_tool=call_agent_tool)
    messages = [{"role": "user", "content": "open safari"}]

    runner.run(
        [
            {"tool": "app.open", "input": {"app_name": "Safari"}},
            {"tool": "desktop.active_window", "input": {}},
        ],
        ["app.open", "desktop.active_window"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=1,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert seen_requests[1]["input"] == {}
    assert seen_requests[1]["verification_target"] == {
        "app_name": "Safari",
        "source_tool": "app.open",
    }


def test_runtime_tool_request_runner_adds_active_window_target_after_open_path_with_app() -> None:
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(tool_request, *_args, **_kwargs):
        seen_requests.append(tool_request)
        if tool_request["tool"] == "desktop.open_path_with_app":
            return {
                "ok": True,
                "data": {
                    "app_name": str(tool_request["input"].get("app_name") or ""),
                    "path": str(tool_request["input"].get("path") or ""),
                },
            }
        if tool_request["tool"] == "desktop.active_window":
            return {"ok": True, "data": {"app_name": "Preview"}}
        raise AssertionError(f"unexpected tool: {tool_request['tool']}")

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "desktop.open_path_with_app",
                "input": {"app_name": "Preview", "path": "Downloads/report.pdf"},
            },
            {"tool": "desktop.active_window", "input": {}},
        ],
        ["desktop.open_path_with_app", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open pdf"}],
        [],
        [],
        next_iteration=1,
        run_id="run-open-path-target",
        budget=FakeBudget(),
    )

    assert seen_requests[1]["input"] == {}
    assert seen_requests[1]["verification_target"] == {
        "app_name": "Preview",
        "source_tool": "desktop.open_path_with_app",
    }


def test_runtime_tool_request_runner_tracks_app_open_path_with_app_alias() -> None:
    seen_requests: list[dict[str, Any]] = []

    def call_agent_tool(tool_request, *_args, **_kwargs):
        seen_requests.append(tool_request)
        if tool_request["tool"] == "app.open_path_with_app":
            return {
                "ok": True,
                "data": {
                    "app_name": str(tool_request["input"].get("app_name") or ""),
                    "path": str(tool_request["input"].get("path") or ""),
                },
            }
        if tool_request["tool"] == "desktop.active_window":
            return {"ok": True, "data": {"app_name": "Preview"}}
        raise AssertionError(f"unexpected tool: {tool_request['tool']}")

    runner = _runner(call_agent_tool=call_agent_tool)

    runner.run(
        [
            {
                "tool": "app.open_path_with_app",
                "input": {"app_name": "Preview", "path": "Downloads/report.pdf"},
            },
            {"tool": "desktop.active_window", "input": {}},
        ],
        ["app.open_path_with_app", "desktop.active_window"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "open pdf"}],
        [],
        [],
        next_iteration=1,
        run_id="run-open-path-alias-target",
        budget=FakeBudget(),
    )

    assert seen_requests[1]["input"] == {}
    assert seen_requests[1]["verification_target"] == {
        "app_name": "Preview",
        "source_tool": "app.open_path_with_app",
    }


def test_runtime_tool_request_runner_projects_fatal_failures_and_success_messages() -> None:
    first_runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "returncode": 1,
            "error": "failed",
        },
    )
    fatal_timeline: list[dict[str, Any]] = []
    with pytest.raises(AgentRuntimeError, match="terminal.run 执行失败"):
        first_runner.run(
            [
                {
                    "tool": "terminal.run",
                    "tool_call_id": "call-fatal-terminal",
                    "input": {"command": "npm test"},
                }
            ],
            ["terminal.run"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "run command"}],
            fatal_timeline,
            [],
            next_iteration=1,
            run_id="run-1",
            budget=FakeBudget(),
        )
    assert fatal_timeline == [
        {
            "event": "agent.tool.failed",
            "detail": "terminal.run",
            "input_preview": {"command": "npm test"},
            "result": {"ok": False, "returncode": 1, "error": "failed"},
            "status": "failed",
            "tool_call_id": "call-fatal-terminal",
            "run_id": "run-1",
            "actor": "native_runtime",
            "visibility": "internal",
            "execution_authority": "runtime_tool_executor",
        }
    ]

    messages = [{"role": "user", "content": "read file"}]
    second_runner = _runner(
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True, "content": "hello"},
    )
    second_runner.run(
        [{"tool": "workspace.read", "input": {"path": "README.md"}}],
        ["workspace.read"],
        FakeBroker({"ok": True}),
        messages,
        [],
        [],
        next_iteration=2,
        run_id="run-1",
        budget=FakeBudget(),
    )

    assert messages[-1] == {
        "role": "user",
        "content": 'Tool result for workspace.read: {"ok": true, "content": "hello"}',
    }


def test_native_runtime_uses_split_tool_request_runner(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolRequestRunner is RuntimeToolRequestRunner
        assert isinstance(service.tool_request_runner, RuntimeToolRequestRunner)
    finally:
        service.close()


def _trusted_preapproval_ui_result(
    *,
    app_name: str = "Google Chrome",
    role: str = "AXButton",
    label: str = "Send",
) -> dict[str, Any]:
    return {
        "ok": True,
        "action": "desktop.read_ui",
        "_runtime_execution_provenance": {
            "source": "local_tool_broker",
            "version": 1,
        },
        "data": {
            "app_name": app_name,
            "count": 1,
            "elements": [{"role": role, "name": label, "enabled": True}],
        },
    }


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_run",
        "wrong_decision",
        "wrong_plan",
        "wrong_request",
        "wrong_call",
        "wrong_provider",
        "wrong_app",
        "wrong_role",
        "wrong_label",
        "model_source",
        "public_actor",
        "missing_authority",
    ),
)
def test_preapproval_ui_observation_rejects_forged_or_mismatched_receipts(
    mutation: str,
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline: list[dict[str, Any]] = []
    run_id = "run-preapproval-ui"
    decision_id = "decision-preapproval-ui"
    plan_id = "plan-preapproval-ui"
    tool_plan_id = "tool-plan-preapproval-ui"
    observation_request = {
        "tool": "desktop.read_ui",
        "input": {"app_name": "Google Chrome", "role_filter": "button", "limit": 80},
        "step_id": "read-current-ui",
        "decision_id": decision_id,
        "plan_id": plan_id,
        "tool_plan_id": tool_plan_id,
        "request_id": "request-read-current-ui",
        "tool_call_id": "call-read-current-ui",
        "source": "runtime_planner",
        "requires_observation": True,
    }
    approval_request = {
        "tool": "desktop.click_ui_element",
        "input": {
            "target": "Send",
            "role_filter": "button",
            "click_count": 1,
            "limit": 80,
        },
        "step_id": "click-send",
        "decision_id": decision_id,
        "plan_id": plan_id,
        "tool_plan_id": tool_plan_id,
        "request_id": "request-click-send",
        "tool_call_id": "call-click-send",
        "source": "runtime_planner",
        "depends_on": ["read-current-ui"],
        "approval_required": True,
        "action_target": {
            "kind": "desktop_app",
            "action": "click_ui",
            "app_name": "Google Chrome",
            "target": "Send",
            "role_filter": "button",
        },
    }

    def call_agent_tool(
        request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(request.get("tool") or "")
        if tool_name == "desktop.click_ui_element":
            return {
                "ok": False,
                "approval_required": True,
                "tool": tool_name,
            }
        result = _trusted_preapproval_ui_result(
            app_name="Safari" if mutation == "wrong_app" else "Google Chrome",
            role="AXTextField" if mutation == "wrong_role" else "AXButton",
            label="Cancel" if mutation == "wrong_label" else "Send",
        )
        if mutation == "wrong_provider":
            result.update(
                {
                    "desktop_execution_provider": {
                        "provider_id": "provider-a",
                        "provider_kind": "sandbox_desktop",
                    },
                    "desktop_execution_route": {
                        "selected_provider_id": "provider-b",
                        "selected_provider_kind": "sandbox_desktop",
                    },
                }
            )
        event = _timeline(
            "agent.tool.call",
            tool_name,
            run_id="another-run" if mutation == "wrong_run" else run_id,
            decision_id=("another-decision" if mutation == "wrong_decision" else decision_id),
            plan_id="another-plan" if mutation == "wrong_plan" else plan_id,
            tool_plan_id=tool_plan_id,
            step_id="read-current-ui",
            request_id=(
                "another-request" if mutation == "wrong_request" else "request-read-current-ui"
            ),
            tool_call_id=(
                "another-call" if mutation == "wrong_call" else "call-read-current-ui"
            ),
            source="model_followup" if mutation == "model_source" else "runtime_planner",
            actor="public_client" if mutation == "public_actor" else "native_runtime",
            visibility="internal",
            execution_authority=(
                "" if mutation == "missing_authority" else "runtime_tool_executor"
            ),
            result=result,
        )
        timeline.append(event)
        return result

    with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
        _runner(
            pending_approval_builder=pending_builder,
            call_agent_tool=call_agent_tool,
        ).run(
            [observation_request, approval_request],
            ["desktop.read_ui", "desktop.click_ui_element"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Click Send in the current Chrome UI"}],
            timeline,
            [],
            next_iteration=2,
            run_id=run_id,
            budget=FakeBudget(),
        )

    assert exc_info.value.reason == "approval_dependency_unverified"
    assert pending_builder.calls == []
    assert _last_event(timeline, "agent.tool.skipped")["result"][
        "dependency_statuses"
    ] == {"read-current-ui": "unverified"}


def test_preapproval_ui_observation_with_exact_runtime_identity_reaches_approval_only() -> None:
    pending_builder = FakePendingApprovalBuilder()
    timeline: list[dict[str, Any]] = []
    run_id = "run-preapproval-ui-positive"
    requests = [
        {
            "tool": "desktop.read_ui",
            "input": {"app_name": "Google Chrome", "role_filter": "button", "limit": 80},
            "step_id": "read-current-ui",
            "decision_id": "decision-preapproval-ui-positive",
            "plan_id": "plan-preapproval-ui-positive",
            "tool_plan_id": "tool-plan-preapproval-ui-positive",
            "request_id": "request-read-current-ui-positive",
            "tool_call_id": "call-read-current-ui-positive",
            "source": "runtime_planner",
            "requires_observation": True,
        },
        {
            "tool": "desktop.click_ui_element",
            "input": {
                "target": "Send",
                "role_filter": "button",
                "click_count": 1,
                "limit": 80,
            },
            "step_id": "click-send",
            "decision_id": "decision-preapproval-ui-positive",
            "plan_id": "plan-preapproval-ui-positive",
            "tool_plan_id": "tool-plan-preapproval-ui-positive",
            "request_id": "request-click-send-positive",
            "tool_call_id": "call-click-send-positive",
            "source": "runtime_planner",
            "depends_on": ["read-current-ui"],
            "approval_required": True,
            "action_target": {
                "kind": "desktop_app",
                "action": "click_ui",
                "app_name": "Google Chrome",
                "target": "Send",
                "role_filter": "button",
            },
        },
    ]

    def call_agent_tool(request: dict[str, Any], *_args: Any, **_kwargs: Any) -> dict[str, Any]:
        tool_name = str(request.get("tool") or "")
        if tool_name == "desktop.click_ui_element":
            return {"ok": False, "approval_required": True, "tool": tool_name}
        result = _trusted_preapproval_ui_result()
        timeline.append(
            _timeline(
                "agent.tool.call",
                tool_name,
                run_id=run_id,
                decision_id="decision-preapproval-ui-positive",
                plan_id="plan-preapproval-ui-positive",
                tool_plan_id="tool-plan-preapproval-ui-positive",
                step_id="read-current-ui",
                request_id="request-read-current-ui-positive",
                tool_call_id="call-read-current-ui-positive",
                source="runtime_planner",
                actor="native_runtime",
                visibility="internal",
                execution_authority="runtime_tool_executor",
                result=result,
            )
        )
        return result

    with pytest.raises(AgentApprovalRequired):
        _runner(
            pending_approval_builder=pending_builder,
            call_agent_tool=call_agent_tool,
        ).run(
            requests,
            ["desktop.read_ui", "desktop.click_ui_element"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Click Send in the current Chrome UI"}],
            timeline,
            [],
            next_iteration=2,
            run_id=run_id,
            budget=FakeBudget(),
        )

    assert len(pending_builder.calls) == 1
    assert pending_builder.calls[0]["tool"] == "desktop.click_ui_element"


@pytest.mark.parametrize(
    "mutation",
    (
        "wrong_app",
        "wrong_window",
        "wrong_plan",
        "wrong_source_call",
        "wrong_provider",
        "model_source",
        "public_actor",
    ),
)
def test_app_scoped_close_approval_rejects_mismatched_active_window_receipts(
    mutation: str,
) -> None:
    pending_builder = FakePendingApprovalBuilder()
    run_id = "run-close-scoped"
    decision_id = "decision-close-scoped"
    plan_id = "plan-close-scoped"
    tool_plan_id = "tool-plan-close-scoped"
    focus_request = {
        "tool": "app.focus",
        "input": {"app_name": "WeChat"},
        "step_id": "focus-target-app",
        "decision_id": decision_id,
        "plan_id": plan_id,
        "tool_plan_id": tool_plan_id,
        "request_id": "request-focus-target-app",
        "tool_call_id": "call-focus-target-app",
        "source": "runtime_planner",
        "requires_post_action_verification": True,
    }
    approval_request = {
        "tool": "desktop.close_window",
        "input": {},
        "step_id": "close-target-window",
        "decision_id": decision_id,
        "plan_id": plan_id,
        "tool_plan_id": tool_plan_id,
        "request_id": "request-close-target-window",
        "tool_call_id": "call-close-target-window",
        "source": "runtime_planner",
        "depends_on": ["focus-target-app"],
        "approval_required": True,
        "action_target": {
            "kind": "desktop_app",
            "action": "dispatch_management",
            "app_name": "WeChat",
            "window_title": "Conversation",
        },
    }
    active_result = {
        "ok": True,
        "action": "desktop.active_window",
        "_runtime_execution_provenance": {
            "source": "local_tool_broker",
            "version": 1,
        },
        "data": {
            "app_name": "Slack" if mutation == "wrong_app" else "WeChat",
            "active_app_name": "Slack" if mutation == "wrong_app" else "WeChat",
            "title": "Settings" if mutation == "wrong_window" else "Conversation",
            "focus_verified": mutation != "wrong_app",
        },
    }
    if mutation == "wrong_provider":
        active_result.update(
            {
                "desktop_execution_provider": {
                    "provider_id": "provider-a",
                    "provider_kind": "sandbox_desktop",
                },
                "desktop_execution_route": {
                    "selected_provider_id": "provider-b",
                    "selected_provider_kind": "sandbox_desktop",
                },
            }
        )
    timeline = [
        _timeline(
            "agent.tool.call",
            "app.focus",
            run_id=run_id,
            decision_id=decision_id,
            plan_id=plan_id,
            tool_plan_id=tool_plan_id,
            step_id="focus-target-app",
            request_id="request-focus-target-app",
            tool_call_id="call-focus-target-app",
            source="runtime_planner",
            actor="native_runtime",
            visibility="internal",
            execution_authority="runtime_tool_executor",
            result={
                "ok": True,
                "action": "app.focus",
                "data": {"app_name": "WeChat", "focus_verified": True},
            },
        ),
        _timeline(
            "agent.tool.call",
            "desktop.active_window",
            run_id=run_id,
            decision_id=decision_id,
            plan_id="another-plan" if mutation == "wrong_plan" else plan_id,
            tool_plan_id=tool_plan_id,
            step_id="focus-target-app:runtime-verify",
            source_step_id="focus-target-app",
            source_request_id="request-focus-target-app",
            source_tool_call_id=(
                "another-call" if mutation == "wrong_source_call" else "call-focus-target-app"
            ),
            tool_call_id="call-active-window",
            source="model_followup" if mutation == "model_source" else "runtime_verification",
            actor="public_client" if mutation == "public_actor" else "native_runtime",
            visibility="internal",
            execution_authority="runtime_tool_executor",
            result=active_result,
        ),
    ]

    with pytest.raises(AgentDirectOutcomeUnverified) as exc_info:
        _runner(
            pending_approval_builder=pending_builder,
            call_agent_tool=lambda *_args, **_kwargs: {
                "ok": False,
                "approval_required": True,
                "tool": "desktop.close_window",
            },
        ).run(
            [approval_request, focus_request],
            ["desktop.close_window", "app.focus"],
            FakeBroker({"ok": True}),
            [{"role": "user", "content": "Close the WeChat Conversation window"}],
            timeline,
            [],
            next_iteration=2,
            run_id=run_id,
            budget=FakeBudget(),
        )

    assert exc_info.value.reason == "approval_dependency_unverified"
    assert pending_builder.calls == []


def _exact_submit_requests(*, action: str = "send") -> list[dict[str, Any]]:
    plan_id = "plan-exact-submit"
    source_step_id = "submit-message"
    source_request_id = f"{plan_id}:request:1:desktop.submit_foreground"
    source_tool_call_id = "call-exact-submit"
    return [
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": action},
            "run_id": "public-run-claim-is-not-authority",
            "decision_id": "decision-exact-submit",
            "plan_id": plan_id,
            "tool_plan_id": "tool-plan-exact-submit",
            "step_id": source_step_id,
            "request_id": source_request_id,
            "tool_call_id": source_tool_call_id,
            "runtime_stage": "operate",
            "requires_post_action_verification": True,
        },
        {
            "tool": "desktop.ui_elements",
            "input": {},
            "decision_id": "decision-exact-submit",
            "plan_id": plan_id,
            "tool_plan_id": "tool-plan-exact-submit",
            "step_id": "verify-submit-message",
            "request_id": f"{plan_id}:request:2:desktop.ui_elements",
            "tool_call_id": "call-verify-exact-submit",
            "source_tool": "desktop.submit_foreground",
            "source_step_id": source_step_id,
            "source_request_id": source_request_id,
            "source_tool_call_id": source_tool_call_id,
            "depends_on": [source_step_id],
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "verification_predicate_kind": "exact_submit_dispatch_receipt",
            "verification_targets": [{"step_id": source_step_id}],
        },
    ]


@pytest.mark.parametrize(
    ("pre_window_id", "pre_value", "expected_dispatches", "expected_receipt"),
    (
        pytest.param(
            77,
            "release target binding 🌙",
            1,
            True,
            id="exact-target-clears-after-return",
        ),
        pytest.param(
            88,
            "release target binding 🌙",
            0,
            False,
            id="wrong-window-blocks-return",
        ),
        pytest.param(
            77,
            "tampered draft",
            0,
            False,
            id="wrong-content-hash-blocks-return",
        ),
    ),
)
def test_runtime_executor_atomically_revalidates_prepared_target_before_submit(
    pre_window_id: int,
    pre_value: str,
    expected_dispatches: int,
    expected_receipt: bool,
) -> None:
    exact_text = "release target binding 🌙"

    class ExactSubmitBroker:
        def __init__(self) -> None:
            self.calls: list[str] = []
            self.dispatches = 0
            self.ui_reads = 0

        @staticmethod
        def _snapshot(*, window_id: int, value: str) -> dict[str, Any]:
            return {
                "ok": True,
                "action": "desktop.ui_elements",
                "data": {
                    "app_name": "Slack",
                    "pid": 4401,
                    "window_id": window_id,
                    "truncated": False,
                    "elements": [
                        {
                            "role": "AXTextArea",
                            "identifier": "slack.message.compose",
                            "name": "Message",
                            "value": value,
                            "enabled": True,
                        }
                    ],
                },
            }

        def call(
            self,
            tool_name: str,
            _payload: dict[str, Any],
            *,
            approved: bool = False,
        ) -> dict[str, Any]:
            del approved
            self.calls.append(tool_name)
            if tool_name == "desktop.type_into_ui_element":
                return {
                    "ok": True,
                    "action": tool_name,
                    "action_dispatched": True,
                    "data": {
                        "app_name": "Slack",
                        "pid": 4401,
                        "window_id": 77,
                        "grounded_element": {
                            "role": "AXTextArea",
                            "identifier": "slack.message.compose",
                            "name": "Message",
                            "pid": 4401,
                            "window_id": 77,
                        },
                    },
                }
            self.ui_reads += 1
            return self._snapshot(window_id=77, value=exact_text)

        def runtime_exact_submit_foreground(
            self,
            action: str,
            *,
            validate_pre: Any,
            observe_post: Any,
        ) -> dict[str, Any]:
            pre = self._snapshot(window_id=pre_window_id, value=pre_value)
            if not validate_pre(pre):
                return {
                    "ok": False,
                    "action": "desktop.submit_foreground",
                    "status": "blocked",
                    "error": "prepared_submit_target_revalidation_failed",
                }
            self.dispatches += 1
            observe_post(self._snapshot(window_id=77, value=""))
            return {
                "ok": True,
                "action": "desktop.submit_foreground",
                "data": {
                    "key": "return",
                    "modifiers": [],
                    "submit_action": action,
                },
            }

    requests = [
        {
            "tool": "desktop.type_into_ui_element",
            "input": {
                "app_name": "Slack",
                "target": "Message",
                "text": exact_text,
            },
            "runtime_stage": "operate",
            "decision_id": "decision-atomic-submit",
            "plan_id": "plan-atomic-submit",
            "tool_plan_id": "tool-plan-atomic-submit",
            "step_id": "prepare-message",
            "request_id": "request-prepare-message",
            "tool_call_id": "call-prepare-message",
            "requires_post_action_verification": True,
        },
        {
            "tool": "desktop.ui_elements",
            "input": {"app_name": "Slack"},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "decision_id": "decision-atomic-submit",
            "plan_id": "plan-atomic-submit",
            "tool_plan_id": "tool-plan-atomic-submit",
            "step_id": "verify-prepared-message",
            "request_id": "request-verify-prepared-message",
            "tool_call_id": "call-verify-prepared-message",
            "depends_on": ["prepare-message"],
        },
        {
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "runtime_stage": "operate",
            "decision_id": "decision-atomic-submit",
            "plan_id": "plan-atomic-submit",
            "tool_plan_id": "tool-plan-atomic-submit",
            "step_id": "submit-message",
            "request_id": "request-submit-message",
            "tool_call_id": "call-submit-message",
            "depends_on": ["prepare-message"],
            "requires_post_action_verification": True,
        },
        {
            "tool": "desktop.ui_elements",
            "input": {},
            "runtime_stage": "verify",
            "runtime_role": "verify_result",
            "decision_id": "decision-atomic-submit",
            "plan_id": "plan-atomic-submit",
            "tool_plan_id": "tool-plan-atomic-submit",
            "step_id": "verify-submit-message",
            "request_id": "request-verify-submit-message",
            "tool_call_id": "call-verify-submit-message",
            "source_tool": "desktop.submit_foreground",
            "source_step_id": "submit-message",
            "source_request_id": "request-submit-message",
            "source_tool_call_id": "call-submit-message",
            "depends_on": ["submit-message"],
            "verification_targets": [{"step_id": "submit-message"}],
            "verification_predicate_kind": "exact_submit_dispatch_receipt",
        },
    ]
    broker = ExactSubmitBroker()
    executor = _executor(tool_call_events=FakeToolCallEvents())

    def execute_tool(
        request: dict[str, Any],
        allowed_tools: list[str],
        broker_arg: Any,
        timeline: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return executor.execute(
            request,
            allowed_tools,
            broker_arg,
            timeline,
            approved=True,
            run_id=str(kwargs.get("run_id") or ""),
            budget=kwargs.get("budget"),
        )

    timeline: list[dict[str, Any]] = []
    _runner(call_agent_tool=execute_tool).run(
        requests,
        [
            "desktop.type_into_ui_element",
            "desktop.ui_elements",
            "desktop.submit_foreground",
        ],
        broker,
        [{"role": "user", "content": "Prepare and send the Slack message"}],
        timeline,
        [],
        next_iteration=2,
        run_id="run-atomic-submit",
        budget=FakeBudget(),
    )

    assert broker.dispatches == expected_dispatches
    exact_receipts = [
        event["result"]
        for event in timeline
        if event.get("event") == "agent.post_action_verification.satisfied"
        and isinstance(event.get("result"), dict)
        and event["result"].get("verification_predicate_kind")
        == "exact_submit_dispatch_receipt"
    ]
    assert bool(exact_receipts) is expected_receipt
    if exact_receipts:
        receipt = exact_receipts[-1]
        assert receipt["content_sha256"] == hashlib.sha256(
            exact_text.encode("utf-8")
        ).hexdigest()
        assert receipt["target_window"]["window_id"] == 77
        assert receipt["post_observation_status"] == (
            "prepared_target_state_changed"
        )
        assert receipt["verified_observed_state"] == "submitted"
        assert "delivered" not in receipt


@pytest.mark.parametrize("submit_action", ("send", "confirm"))
def test_runner_rejects_native_submit_without_private_prepared_target(
    submit_action: str,
) -> None:
    tool_events = FakeToolCallEvents()
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    executor = _executor(tool_call_events=tool_events, run_events=run_events)
    broker = FakeBroker(
        {
            "ok": True,
            "action": "desktop.submit_foreground",
            "data": {
                "key": "return",
                "modifiers": [],
                "submit_action": submit_action,
            },
        }
    )

    def call_agent_tool(
        request: dict[str, Any],
        allowed_tools: list[str],
        broker_arg: Any,
        timeline: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return executor.execute(
            request,
            allowed_tools,
            broker_arg,
            timeline,
            artifacts=kwargs.get("artifacts"),
            approved=True,
            run_id=str(kwargs.get("run_id") or ""),
            budget=kwargs.get("budget"),
        )

    timeline: list[dict[str, Any]] = []
    messages = [{"role": "user", "content": "Send the prepared message"}]
    _runner(call_agent_tool=call_agent_tool, run_events=run_events).run(
        _exact_submit_requests(action=submit_action),
        ["desktop.submit_foreground", "desktop.ui_elements"],
        broker,
        messages,
        timeline,
        [],
        next_iteration=2,
        run_id="run-exact-submit",
        budget=FakeBudget(),
    )

    assert broker.calls == []
    blocked = _last_event(timeline, "agent.tool.skipped")["result"]
    assert blocked["reason"] == "prepared_submit_target_revalidation_failed"
    assert not any(
        event.get("event") == "agent.post_action_verification.satisfied"
        for event in timeline
    )


def test_runner_rejects_provider_self_reported_exact_submit_receipt() -> None:
    calls: list[str] = []

    def call_agent_tool(
        request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        tool_name = str(request.get("tool") or "")
        calls.append(tool_name)
        result = (
            {
                "ok": True,
                "action": "desktop.submit_foreground",
                "data": {
                    "key": "return",
                    "modifiers": [],
                    "submit_action": "send",
                },
                "desktop_execution_provider_routed": True,
                "desktop_execution_provider": {
                    "adapter_registered": True,
                    "provider_kind": "background_desktop",
                    "provider_id": "provider-self-report",
                },
            }
            if tool_name == "desktop.submit_foreground"
            else {"ok": True, "action": tool_name, "data": {"elements": []}}
        )
        timeline.append(
            _timeline(
                "agent.tool.call",
                tool_name,
                run_id=str(request.get("run_id") or ""),
                decision_id=str(request.get("decision_id") or ""),
                plan_id=str(request.get("plan_id") or ""),
                tool_plan_id=str(request.get("tool_plan_id") or ""),
                step_id=str(request.get("step_id") or ""),
                request_id=str(request.get("request_id") or ""),
                tool_call_id=str(request.get("tool_call_id") or ""),
                input_preview=dict(request.get("input") or {}),
                result=result,
            )
        )
        return result

    timeline: list[dict[str, Any]] = []
    _runner(call_agent_tool=call_agent_tool).run(
        _exact_submit_requests(),
        ["desktop.submit_foreground", "desktop.ui_elements"],
        FakeBroker({"ok": True}),
        [{"role": "user", "content": "Send the prepared message"}],
        timeline,
        [],
        next_iteration=2,
        run_id="run-exact-submit",
        budget=FakeBudget(),
    )

    assert calls == []
    assert not any(
        event.get("event") == "agent.post_action_verification.satisfied"
        and isinstance(event.get("result"), dict)
        and event["result"].get("verification_predicate_kind")
        == "exact_submit_dispatch_receipt"
        for event in timeline
    )


@pytest.mark.parametrize(
    ("mutation", "source_action", "result_data"),
    (
        pytest.param(
            "generic-ok",
            "send",
            {},
            id="generic-ok-is-not-a-dispatch-receipt",
        ),
        pytest.param(
            "wrong-action",
            "send",
            {"key": "return", "modifiers": [], "submit_action": "confirm"},
            id="wrong-submit-action",
        ),
        pytest.param(
            "unsupported-submit-action",
            "submit",
            {"key": "return", "modifiers": [], "submit_action": "submit"},
            id="submit-is-not-send-or-confirm",
        ),
        pytest.param(
            "wrong-key",
            "send",
            {"key": "space", "modifiers": [], "submit_action": "send"},
            id="wrong-dispatch-key",
        ),
        pytest.param(
            "wrong-modifiers",
            "confirm",
            {
                "key": "return",
                "modifiers": ["command"],
                "submit_action": "confirm",
            },
            id="wrong-dispatch-modifiers",
        ),
        pytest.param(
            "wrong-source-call",
            "send",
            {"key": "return", "modifiers": [], "submit_action": "send"},
            id="wrong-source-call",
        ),
        pytest.param(
            "wrong-plan",
            "send",
            {"key": "return", "modifiers": [], "submit_action": "send"},
            id="wrong-plan",
        ),
    ),
)
def test_runner_exact_submit_dispatch_receipt_negative_matrix(
    mutation: str,
    source_action: str,
    result_data: dict[str, Any],
) -> None:
    requests = _exact_submit_requests(action=source_action)
    if mutation == "wrong-source-call":
        requests[1]["source_tool_call_id"] = "call-another-submit"
    if mutation == "wrong-plan":
        requests[1]["plan_id"] = "plan-another-submit"
    executor = _executor(tool_call_events=FakeToolCallEvents())
    broker = FakeBroker(
        {
            "ok": True,
            "action": "desktop.submit_foreground",
            **({"data": dict(result_data)} if result_data else {}),
        }
    )

    def call_agent_tool(
        request: dict[str, Any],
        allowed_tools: list[str],
        broker_arg: Any,
        timeline: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return executor.execute(
            request,
            allowed_tools,
            broker_arg,
            timeline,
            approved=True,
            run_id=str(kwargs.get("run_id") or ""),
            budget=kwargs.get("budget"),
        )

    timeline: list[dict[str, Any]] = []
    _runner(call_agent_tool=call_agent_tool).run(
        requests,
        ["desktop.submit_foreground", "desktop.ui_elements"],
        broker,
        [{"role": "user", "content": "Send the prepared message"}],
        timeline,
        [],
        next_iteration=2,
        run_id="run-exact-submit",
        budget=FakeBudget(),
    )

    called_tools = [call[0] for call in broker.calls]
    assert called_tools == []
    assert not any(
        event.get("event") == "agent.post_action_verification.satisfied"
        and isinstance(event.get("result"), dict)
        and event["result"].get("verification_predicate_kind")
        == "exact_submit_dispatch_receipt"
        for event in timeline
    )


def test_private_exact_submit_receipt_rejects_wrong_run_and_provider_route() -> None:
    verifier = _exact_submit_requests()[1]
    receipt = {
        "_authority": (
            tool_execution_module._RUNTIME_PRIVATE_EXACT_SUBMIT_RECEIPT_AUTHORITY
        ),
        "run_id": "run-exact-submit",
        "decision_id": verifier["decision_id"],
        "plan_id": verifier["plan_id"],
        "tool_plan_id": verifier["tool_plan_id"],
        "source_tool": "desktop.submit_foreground",
        "source_step_id": verifier["source_step_id"],
        "source_request_id": verifier["source_request_id"],
        "source_tool_call_id": verifier["source_tool_call_id"],
        "provider_kind": LOCAL_DESKTOP_PROVIDER_KIND,
        "provider_id": LOCAL_DESKTOP_PROVIDER_ID,
        "submitted_action": "send",
        "verifier_step_id": verifier["step_id"],
        "verifier_request_id": verifier["request_id"],
        "verifier_tool_call_id": verifier["tool_call_id"],
    }
    receipts = {verifier["source_tool_call_id"]: receipt}

    assert tool_execution_module._private_exact_submit_dispatch_receipt_for_verifier(
        verifier,
        receipts,
        run_id="run-another-submit",
    ) == {}
    assert tool_execution_module._private_exact_submit_dispatch_receipt_for_verifier(
        {
            **verifier,
            "desktop_execution_route": {
                "selected_provider_kind": "background_desktop",
                "selected_provider_id": "provider-another-submit",
            },
        },
        receipts,
        run_id="run-exact-submit",
    ) == {}


def test_exact_submit_dispatch_receipt_cannot_replay_from_persisted_timeline() -> None:
    tool_events = FakeToolCallEvents()
    executor = _executor(tool_call_events=tool_events)
    broker = FakeBroker(
        {
            "ok": True,
            "action": "desktop.submit_foreground",
            "data": {
                "key": "return",
                "modifiers": [],
                "submit_action": "send",
            },
        }
    )

    def execute_tool(
        request: dict[str, Any],
        allowed_tools: list[str],
        broker_arg: Any,
        timeline: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        return executor.execute(
            request,
            allowed_tools,
            broker_arg,
            timeline,
            approved=True,
            run_id=str(kwargs.get("run_id") or ""),
            budget=kwargs.get("budget"),
        )

    timeline: list[dict[str, Any]] = []
    runner = _runner(call_agent_tool=execute_tool)
    runner.run(
        _exact_submit_requests(),
        ["desktop.submit_foreground", "desktop.ui_elements"],
        broker,
        [{"role": "user", "content": "Send the prepared message"}],
        timeline,
        [],
        next_iteration=2,
        run_id="run-exact-submit",
        budget=FakeBudget(),
    )
    calls_after_first_run = len(broker.calls)

    runner.run(
        [_exact_submit_requests()[1]],
        ["desktop.ui_elements"],
        broker,
        [{"role": "user", "content": "Verify the prepared message"}],
        timeline,
        [],
        next_iteration=3,
        run_id="run-exact-submit",
        budget=FakeBudget(),
    )

    assert len(broker.calls) == calls_after_first_run + 1
    assert broker.calls[-1][0] == "desktop.ui_elements"
    assert sum(
        1
        for event in timeline
        if event.get("event") == "agent.post_action_verification.satisfied"
        and isinstance(event.get("result"), dict)
        and event["result"].get("verification_predicate_kind")
        == "exact_submit_dispatch_receipt"
    ) == 0
