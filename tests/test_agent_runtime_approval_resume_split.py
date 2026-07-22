"""Tests for approval resume coordinator split out of the legacy runtime."""

from __future__ import annotations

from copy import deepcopy
import hashlib
from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_resume import (
    ApprovalResumeCoordinator,
    _approval_resume_conflicting_pending_artifact,
    _approval_resume_permission_recovery_payload,
    _approval_resume_remaining_requests_after_tool,
    _daily_desktop_native_receipt_verification_evidence,
    _daily_desktop_resume_result_after_remaining_tools,
    _daily_desktop_tool_result_phrase,
)
from apps.shell.agent.runtime.errors import (
    AgentApprovalRequired,
    AgentDirectOutcomeUnverified,
    AgentRuntimeError,
)
from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.goal_runtime import runtime_goal_assessment
from apps.shell.agent.runtime.tool_execution import (
    RuntimeToolCallExecutor,
    RuntimeToolRequestRunner,
)
from apps.shell.agent.runtime.tool_loop import RuntimeToolLoopProjectionBuilder
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalResumeContext,
    approval_request_fingerprint,
)


def test_approval_resume_coordinator_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.ApprovalResumeCoordinator is ApprovalResumeCoordinator


@pytest.mark.parametrize(
    ("mode", "expected_closes"),
    [("completed", 1), ("failed", 1), ("approval_required", 0)],
)
def test_approval_resume_releases_browser_target_only_after_terminal_projection(
    mode: str,
    expected_closes: int,
) -> None:
    class _ClosableBroker:
        def __init__(self) -> None:
            self.closes = 0

        def close_owned_browser_target(self) -> None:
            self.closes += 1

    broker = _ClosableBroker()
    context = ToolApprovalResumeContext(
        run_id="run-browser-resume",
        timeline=[],
        artifacts=[],
        broker=broker,
        allowed_tools=["terminal.run"],
        budget={"events": 1},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={"tool": "terminal.run", "input": {"command": "printf ok"}},
        tool_name="terminal.run",
        input_preview={"command": "printf ok"},
        remaining_requests=[],
        next_iteration=2,
    )

    def continue_agent(*_args: Any, **_kwargs: Any) -> str:
        if mode == "failed":
            raise RuntimeError("failed")
        if mode == "approval_required":
            raise AgentApprovalRequired({"approval_id": "approval-next"})
        return "done"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True},
        fatal_tool_failure_detail=lambda *_args, **_kwargs: "",
        append_tool_result_message=lambda *_args, **_kwargs: None,
        run_tool_requests=lambda *_args, **_kwargs: None,
        timeline_factory=lambda event, detail, **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        continue_custom_api_agent=continue_agent,
    )

    result = coordinator.continue_and_project_after_approved_tool(
        agent={"agent_id": "agent-1"},
        context=context,
        project_completed=lambda _context, text: {
            "status": "completed",
            "result": text,
        },
        project_required=lambda _context, pending: {
            "status": "approval_required",
            "pending": pending,
        },
        project_failed=lambda _context, error: {
            "status": "failed",
            "error": error,
        },
        redact_error=lambda _error: "safe failure",
    )

    assert result["status"] == mode
    assert broker.closes == expected_closes


def test_approval_resume_sequence_verifies_approved_action_before_remaining_action(
) -> None:
    context = ToolApprovalResumeContext(
        run_id="run-sequence-verifier",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=[
            "app.open_and_hotkey",
            "desktop.safe_shortcut",
            "desktop.active_window",
        ],
        budget={"events": 4},
        messages=[],
        tool_request={
            "tool": "app.open_and_hotkey",
            "input": {"app_name": "Notes", "key": "l", "modifiers": ["command"]},
            "source": "runtime_planner",
            "step_id": "open-and-hotkey",
            "requires_post_action_verification": True,
            "task_todo": {"step_id": "open-and-hotkey"},
        },
        tool_name="app.open_and_hotkey",
        input_preview={"app_name": "Notes", "key": "l"},
        remaining_requests=[
            {
                "tool": "desktop.safe_shortcut",
                "input": {"action": "copy"},
                "source": "runtime_planner",
                "step_id": "copy-selection",
                "runtime_stage": "operate",
                "requires_post_action_verification": True,
                "task_todo": {"step_id": "copy-selection"},
            }
        ],
        next_iteration=2,
    )

    requests = _approval_resume_remaining_requests_after_tool(
        context,
        {
            "ok": True,
            "action": "app.open_and_hotkey",
            "data": {"app_name": "Notes"},
        },
    )

    assert [request["tool"] for request in requests] == [
        "desktop.active_window",
        "desktop.safe_shortcut",
    ]
    verifier = requests[0]
    assert verifier["depends_on"] == ["open-and-hotkey"]
    assert [
        target["step_id"] for target in verifier["task_verification_targets"]
    ] == ["open-and-hotkey"]
    assert verifier["desktop_loop"]["verification_target_step_ids"] == [
        "open-and-hotkey",
    ]


def test_approval_resume_reuses_existing_exact_post_action_verifier() -> None:
    existing_verifier = {
        "tool": "desktop.ui_elements",
        "input": {"app_name": "Notes"},
        "source": "runtime_post_action_auto_verify",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "source_step_id": "submit-message",
        "step_id": "submit-message:runtime-verify",
        "depends_on": ["submit-message"],
        "task_verification_targets": [{"step_id": "submit-message"}],
    }
    context = ToolApprovalResumeContext(
        run_id="run-existing-verifier",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.hotkey", "desktop.ui_elements"],
        budget={"events": 4},
        messages=[],
        tool_request={
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
            "source": "runtime_planner",
            "request_id": "request-submit",
            "step_id": "submit-message",
            "requires_post_action_verification": True,
        },
        tool_name="desktop.hotkey",
        input_preview={"key": "return", "modifiers": []},
        remaining_requests=[
            {
                "tool": "desktop.hotkey",
                "input": {"key": "a", "modifiers": ["command"]},
                "source": "runtime_planner",
                "step_id": "select-all",
                "runtime_stage": "operate",
            },
            existing_verifier,
        ],
        next_iteration=2,
    )

    requests = _approval_resume_remaining_requests_after_tool(
        context,
        {"ok": True, "action": "desktop.hotkey"},
    )

    assert requests == [
        {
            **existing_verifier,
            "source_tool": "desktop.hotkey",
            "source_request_id": "request-submit",
            "verifier_step_id": "submit-message:runtime-verify",
        },
        context.remaining_requests[0],
    ]
    assert sum(
        request.get("step_id") == "submit-message:runtime-verify"
        for request in requests
    ) == 1


class _ExactFileApprovalBudget:
    def claim_tool_call(
        self,
        _tool_name: str,
        *,
        terminal_execution: bool = False,
    ) -> None:
        del terminal_execution


class _ExactFileApprovalRuntimeEvents:
    def __getattr__(self, _name: str) -> Any:
        return lambda *_args, **_kwargs: None


class _ExactFileApprovalBroker:
    def __init__(self, content: str) -> None:
        self.content = content
        self.calls: list[tuple[str, bool]] = []

    def call(
        self,
        tool_name: str,
        payload: dict[str, Any],
        *,
        approved: bool = False,
    ) -> dict[str, Any]:
        self.calls.append((tool_name, approved))
        if tool_name == "terminal.run":
            return {
                "ok": True,
                "returncode": 0,
                "timed_out": False,
                "stdout": "",
                "stderr": "",
            }
        assert tool_name == "workspace.read"
        assert payload == {"path": "reports/analysis.md"}
        return {
            "ok": True,
            "path": "reports/analysis.md",
            "content": self.content,
            "truncated": False,
            "size_bytes": len(self.content.encode("utf-8")),
            "content_bytes": len(self.content.encode("utf-8")),
            "decoding_lossy": False,
        }


def _exact_file_approval_resume_runtime(
    *,
    forge_public_marker: bool = False,
) -> tuple[ToolApprovalResumeContext, _ExactFileApprovalBroker, GoalContract]:
    content = "approved analysis output 🌙\n"
    run_id = "run-approved-analysis"
    plan_id = "plan-approved-analysis"
    contract = GoalContract(
        contract_id="goal-approved-analysis",
        run_id=run_id,
        original_goal="Analyze the data and write reports/analysis.md",
        criteria=(
            GoalCriterion(
                criterion_id="analysis-output",
                description="The exact analysis output file is present",
                effectful=True,
                required_capabilities=("data.analysis",),
                expected={
                    "state": "fulfilled",
                    "target": {
                        "kind": "data_analysis",
                        "action": "analyze",
                        "artifact_path": "reports/analysis.md",
                    },
                },
                source_step_ids=("run-analysis",),
                verifier_step_ids=("verify-analysis",),
            ),
        ),
    )
    source_request = {
        "tool": "terminal.run",
        "input": {"command": "python analyze.py"},
        "source": "runtime_planner",
        "runtime_stage": "operate",
        "decision_id": "decision-approved-analysis",
        "plan_id": plan_id,
        "tool_plan_id": "tool-plan-approved-analysis",
        "step_id": "run-analysis",
        "request_id": "request-run-analysis",
        "tool_call_id": "call-run-analysis",
        "capability_id": "data.analysis",
        "goal_contract_id": contract.contract_id,
        "goal_criterion_id": "analysis-output",
        "root_goal_unchanged": True,
        "action_target": {
            "kind": "data_analysis",
            "action": "analyze",
            "artifact_path": "reports/analysis.md",
        },
    }
    verifier_request = {
        "tool": "workspace.read",
        "input": {"path": "reports/analysis.md"},
        "source": "runtime_verification",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "decision_id": "decision-approved-analysis",
        "plan_id": plan_id,
        "tool_plan_id": "tool-plan-approved-analysis",
        "step_id": "verify-analysis",
        "request_id": "request-verify-analysis",
        "depends_on": ["run-analysis"],
    }
    budget = _ExactFileApprovalBudget()
    broker = _ExactFileApprovalBroker(content)
    runtime_events = _ExactFileApprovalRuntimeEvents()
    executor = RuntimeToolCallExecutor(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        validate_tool_payload=lambda _tool_name, _payload: None,
        limit_tool_result=lambda result: result,
        timeline_factory=_timeline,
        tool_call_events=runtime_events,
        trace_events=runtime_events,
        append_run_event=lambda *_args, **_kwargs: None,
    )
    runner = RuntimeToolRequestRunner(
        normalize_tool_name=lambda value: str(value or "").strip(),
        input_preview=lambda value: value,
        run_budget=lambda _run_id, _timeline: budget,
        user_goal_from_messages=lambda _messages: contract.original_goal,
        goal_disallows_tool=lambda _goal, _tool: "",
        timeline_factory=_timeline,
        append_run_event=lambda *_args, **_kwargs: None,
        tool_loop_projection=RuntimeToolLoopProjectionBuilder(),
        pending_approval_builder=object(),
        call_agent_tool=executor.execute,
    )

    def run_remaining(requests: list[dict[str, Any]], *args: Any, **kwargs: Any) -> None:
        if forge_public_marker:
            for request in requests:
                private_keys = [
                    key
                    for key in request
                    if str(key).startswith("_runtime_private_exact_file")
                ]
                assert len(private_keys) == 1
                request[private_keys[0]] = "public-serialized-marker"
        runner.run(requests, *args, **kwargs)

    context = ToolApprovalResumeContext(
        run_id=run_id,
        timeline=[],
        artifacts=[],
        broker=broker,
        allowed_tools=["terminal.run", "workspace.read"],
        budget=budget,
        messages=[{"role": "user", "content": contract.original_goal}],
        tool_request=source_request,
        tool_name="terminal.run",
        input_preview=dict(source_request["input"]),
        remaining_requests=[verifier_request],
        next_iteration=2,
        goal_contract=contract,
    )
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=executor.execute,
        fatal_tool_failure_detail=lambda *_args, **_kwargs: "",
        append_tool_result_message=lambda *_args, **_kwargs: None,
        run_tool_requests=run_remaining,
        timeline_factory=_timeline,
    )

    coordinator.execute_approved_tool(context)
    return context, broker, contract


def test_approval_resume_mints_exact_file_readback_receipt_after_approved_source(
) -> None:
    context, broker, contract = _exact_file_approval_resume_runtime()

    receipt_event = next(
        event
        for event in reversed(context.timeline)
        if event.get("event") == "agent.tool.call"
        and event.get("detail") == "workspace.read"
        and event.get("source") == "runtime_native_postcondition_receipt"
    )
    receipt = receipt_event["result"]
    assessment = runtime_goal_assessment(contract, context.timeline)

    assert broker.calls == [("terminal.run", True), ("workspace.read", False)]
    assert receipt["verification_predicate_kind"] == "exact_file_content_present"
    assert receipt["source_tool_call_id"] == "call-run-analysis"
    assert receipt["observed_path"] == "reports/analysis.md"
    assert receipt["content_sha256"] == hashlib.sha256(
        broker.content.encode("utf-8")
    ).hexdigest()
    assert assessment.completed is True


def test_approval_resume_rejects_serialized_exact_file_readback_marker() -> None:
    context, broker, contract = _exact_file_approval_resume_runtime(
        forge_public_marker=True,
    )

    assert broker.calls == [("terminal.run", True), ("workspace.read", False)]
    assert not any(
        event.get("event") == "agent.tool.call"
        and event.get("detail") == "workspace.read"
        and event.get("source") == "runtime_native_postcondition_receipt"
        for event in context.timeline
    )
    assert runtime_goal_assessment(contract, context.timeline).completed is False


def _approval_resume_native_receipt_fixture(
) -> tuple[ToolApprovalResumeContext, dict[str, Any]]:
    run_id = "run-native-receipt"
    plan_id = "plan-native-receipt"
    contract_id = "contract-native-receipt"
    criterion_id = "criterion-submit"
    source_request = {
        "tool": "desktop.submit_foreground",
        "input": {"action": "send"},
        "source": "runtime_planner",
        "request_id": "request-submit",
        "tool_call_id": "call-submit",
        "plan_id": plan_id,
        "step_id": "submit-foreground-ui",
        "goal_contract_id": contract_id,
        "goal_criterion_id": criterion_id,
        "root_goal_unchanged": True,
    }
    source_event = {
        "event": "agent.tool.call",
        "detail": "desktop.submit_foreground",
        "source": "runtime_planner",
        "approved": True,
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "visibility": "internal",
        "run_id": run_id,
        "request_id": "request-submit",
        "tool_call_id": "call-submit",
        "plan_id": plan_id,
        "step_id": "submit-foreground-ui",
        "goal_contract_id": contract_id,
        "goal_criterion_id": criterion_id,
        "root_goal_unchanged": True,
        "result": {
            "ok": True,
            "action": "desktop.submit_foreground",
            "desktop_execution_evidence": {
                "provider_kind": "local_desktop",
                "provider_id": "local-native-desktop",
            },
        },
    }
    verifier_event = {
        "event": "agent.tool.call",
        "detail": "desktop.ui_elements",
        "source": "runtime_native_postcondition_receipt",
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "execution_mode": "native_postcondition_receipt_projection",
        "visibility": "internal",
        "run_id": run_id,
        "request_id": "request-verify",
        "tool_call_id": "call-verify",
        "plan_id": plan_id,
        "step_id": "verify-desktop-result",
        "source_request_id": "request-submit",
        "source_tool_call_id": "call-submit",
        "source_step_id": "submit-foreground-ui",
        "goal_contract_id": contract_id,
        "goal_criterion_id": criterion_id,
        "root_goal_unchanged": True,
        "desktop_execution_route": {
            "selected_provider_kind": "local_desktop",
            "selected_provider_id": "local-native-desktop",
        },
        "result": {
            "ok": True,
            "action": "desktop.ui_elements",
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "verification_predicate_kind": "exact_submit_dispatch_receipt",
            "source_tool": "desktop.submit_foreground",
            "source_tool_call_id": "call-submit",
            "source_step_id": "submit-foreground-ui",
        },
    }
    contract = GoalContract(
        contract_id=contract_id,
        run_id=run_id,
        original_goal="send the prepared message",
        intent_kind="daily_desktop",
        criteria=(
            GoalCriterion(
                criterion_id=criterion_id,
                description="submit the prepared foreground message",
                effectful=True,
                source_step_ids=("submit-foreground-ui",),
                verifier_step_ids=("verify-desktop-result",),
            ),
        ),
    )
    context = ToolApprovalResumeContext(
        run_id=run_id,
        timeline=[source_event, verifier_event],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.submit_foreground", "desktop.ui_elements"],
        budget={"events": 4},
        messages=[],
        tool_request=source_request,
        tool_name="desktop.submit_foreground",
        input_preview={"action": "send"},
        remaining_requests=[],
        next_iteration=2,
        goal_contract=contract,
    )
    return context, verifier_event


def test_approval_resume_projects_only_exact_native_receipt_verification() -> None:
    context, verifier_event = _approval_resume_native_receipt_fixture()

    evidence = _daily_desktop_native_receipt_verification_evidence(
        context,
        [verifier_event],
    )

    assert evidence["verification_status"] == "verified"
    assert evidence["receipt_status"] == "satisfied"
    assert evidence["verification_satisfied_by_native_receipt"] is True
    assert evidence["verification_source_request_id"] == "request-submit"
    assert evidence["verification_source_tool_call_id"] == "call-submit"
    assert evidence["verification_source_step_id"] == "submit-foreground-ui"
    assert evidence["verification_step_id"] == "verify-desktop-result"
    assert evidence["verification_plan_id"] == "plan-native-receipt"
    assert evidence["goal_criterion_id"] == "criterion-submit"


@pytest.mark.parametrize(
    "variant",
    [
        "ordinary_ok",
        "wrong_source_call",
        "wrong_source_request",
        "wrong_plan",
        "wrong_source_step",
        "wrong_verifier_step",
        "wrong_run",
        "wrong_provider",
        "wrong_predicate",
        "public_projection",
        "model_projection",
    ],
)
def test_approval_resume_does_not_upgrade_untrusted_or_mismatched_verifier(
    variant: str,
) -> None:
    context, original_verifier = _approval_resume_native_receipt_fixture()
    verifier = deepcopy(original_verifier)
    context.timeline[-1] = verifier
    result = verifier["result"]
    if variant == "ordinary_ok":
        result.pop("postcondition_verified")
        result.pop("verification_satisfied_by_native_receipt")
    elif variant == "wrong_source_call":
        verifier["source_tool_call_id"] = "call-other"
        result["source_tool_call_id"] = "call-other"
    elif variant == "wrong_source_request":
        verifier["source_request_id"] = "request-other"
    elif variant == "wrong_plan":
        verifier["plan_id"] = "plan-other"
    elif variant == "wrong_source_step":
        verifier["source_step_id"] = "other-step"
        result["source_step_id"] = "other-step"
    elif variant == "wrong_verifier_step":
        verifier["step_id"] = "undeclared-verifier"
    elif variant == "wrong_run":
        verifier["run_id"] = "run-other"
    elif variant == "wrong_provider":
        verifier["desktop_execution_route"] = {
            "selected_provider_kind": "sandbox_desktop",
            "selected_provider_id": "other-provider",
        }
    elif variant == "wrong_predicate":
        result["verification_predicate_kind"] = "app_window_present"
    elif variant == "public_projection":
        verifier["visibility"] = "public"
    elif variant == "model_projection":
        verifier["actor"] = "model"

    evidence = _daily_desktop_native_receipt_verification_evidence(
        context,
        [verifier],
    )

    assert evidence == {}


def test_approval_resume_drops_only_exact_duplicate_of_approved_composite() -> None:
    approved_request = {
        "tool": "app.focus_and_click_ui_element",
        "input": {
            "app_name": "Google Chrome",
            "target": "搜索",
            "role_filter": "text",
            "limit": 80,
            "click_count": 1,
        },
        "decision_id": "decision-search",
        "plan_id": "plan-search",
        "step_id": "focus-search-field",
        "request_id": "request-focus-search-field",
        "tool_call_id": "call-focus-search-field",
        "action_target": {
            "kind": "desktop_app",
            "action": "click_ui",
            "app_name": "Google Chrome",
            "target": "搜索",
        },
    }
    new_approval_generation = {
        **approved_request,
        "input": {**approved_request["input"], "target": "账户"},
        "request_id": "request-focus-account-field",
        "tool_call_id": "call-focus-account-field",
        "action_target": {
            **approved_request["action_target"],
            "target": "账户",
        },
    }
    type_request = {
        "tool": "desktop.safe_type_text",
        "input": {"text": "yachiyo"},
        "decision_id": "decision-search",
        "plan_id": "plan-search",
        "step_id": "type-search-query",
        "request_id": "request-type-search-query",
        "tool_call_id": "call-type-search-query",
    }
    context = ToolApprovalResumeContext(
        run_id="run-composite-approval",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=[
            "app.focus_and_click_ui_element",
            "desktop.safe_type_text",
        ],
        budget={"events": 4},
        messages=[],
        tool_request=dict(approved_request),
        tool_name="app.focus_and_click_ui_element",
        input_preview=dict(approved_request["input"]),
        remaining_requests=[
            dict(approved_request),
            new_approval_generation,
            type_request,
        ],
        next_iteration=2,
    )

    requests = _approval_resume_remaining_requests_after_tool(
        context,
        {"ok": True, "action": "app.focus_and_click_ui_element"},
    )

    assert requests == [new_approval_generation, type_request]


def test_approval_resume_continuation_receives_canonical_approved_result() -> None:
    context = _structured_approval_resume_context()
    persisted_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    continued_events: list[dict[str, Any]] = []

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **scope: Any,
    ) -> None:
        persisted_events.append((run_id, event_type, dict(payload), dict(scope)))

    def continue_custom_api_agent(
        _agent: dict[str, Any],
        _user_goal: str,
        _broker: Any,
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> str:
        continued_events.extend(
            event
            for event in timeline
            if event.get("approval_resume_result_canonical") is True
        )
        return "continued after approved browser click"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "action": "browser.click",
            "data": {"selector": "#first-result"},
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
        append_run_event=append_run_event,
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool({}, context)

    assert result == "continued after approved browser click"
    assert len(continued_events) == 1
    canonical = continued_events[0]
    assert canonical["event"] == "agent.tool.call"
    assert canonical["detail"] == "browser.click"
    assert canonical["approved"] is True
    assert canonical["approval_id"] == "approval-browser-click"
    assert canonical["run_id"] == "run-structured-approval"
    assert canonical["decision_id"] == "decision-search"
    assert canonical["plan_id"] == "plan-search"
    assert canonical["tool_plan_id"] == "tool-plan-search"
    assert canonical["step_id"] == "click-first-result"
    assert canonical["request_id"] == "request-click-first-result"
    assert canonical["tool_call_id"] == "tool-call-click-first-result"
    assert canonical["tool"] == "browser.click"
    assert canonical["actor"] == "native_runtime"
    assert canonical["execution_authority"] == "runtime_tool_executor"
    assert canonical["execution_mode"] == "approved_result_canonical_projection"
    assert canonical["provider_kind"] == "runtime_tool_broker"
    assert canonical["provider_id"] == "builtins.dict"
    assert canonical["approval_request_fingerprint"] == approval_request_fingerprint(
        context.tool_request
    )
    assert canonical["approval_generation_id"] == "approval-browser-click"
    assert canonical["approval_claim_id"]
    assert canonical["result"] == {
        "ok": True,
        "action": "browser.click",
        "data": {"selector": "#first-result"},
    }
    assert [event[1] for event in persisted_events] == [
        "agent.tool.call",
        "agent.tool.outcome",
    ]
    assert persisted_events[0] == (
        "run-structured-approval",
        "agent.tool.call",
        {
            key: canonical[key]
            for key in (
                "approval_resume_result_canonical",
                "approved",
                "approval_id",
                "approval_generation_id",
                "approval_claim_id",
                "approval_request_fingerprint",
                "run_id",
                "decision_id",
                "plan_id",
                "tool_plan_id",
                "step_id",
                "request_id",
                "tool_call_id",
                "tool",
                "provider_kind",
                "provider_id",
                "actor",
                "execution_authority",
                "execution_mode",
                "input_preview",
                "result",
            )
        },
        {
            "actor": "native_runtime",
            "visibility": "internal",
            "sensitivity": "private",
        },
    )
    assert persisted_events[1] == (
        "run-structured-approval",
        "agent.tool.outcome",
        {
            "tool": "browser.click",
            "capabilities": ["browser.research"],
            "status": "success",
            "reason": "ok",
            "retryable": False,
            "effects": [],
            "verification": "not_required",
            "recovery_hints": [],
            "provenance": {},
            "approval_id": "approval-browser-click",
            "approval_generation_id": "approval-browser-click",
            "approval_claim_id": canonical["approval_claim_id"],
            "approval_request_fingerprint": canonical[
                "approval_request_fingerprint"
            ],
            "run_id": "run-structured-approval",
            "decision_id": "decision-search",
            "plan_id": "plan-search",
            "tool_plan_id": "tool-plan-search",
            "step_id": "click-first-result",
            "request_id": "request-click-first-result",
            "tool_call_id": "tool-call-click-first-result",
            "provider_kind": "runtime_tool_broker",
            "provider_id": "builtins.dict",
            "approved": True,
            "visibility": "internal",
        },
        {
            "actor": "native_runtime",
            "visibility": "internal",
            "sensitivity": "private",
        },
    )
    assert "result" not in persisted_events[1][2]
    assert "input_preview" not in persisted_events[1][2]


def test_approval_resume_reuses_canonical_result_without_duplicate_event() -> None:
    context = _structured_approval_resume_context()
    tool_calls: list[str] = []
    persisted_events: list[str] = []

    def call_agent_tool(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        tool_calls.append("browser.click")
        return {"ok": True, "action": "browser.click"}

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=call_agent_tool,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        append_run_event=lambda _run_id, event_type, _payload, **_kwargs: (
            persisted_events.append(event_type)
        ),
    )

    coordinator.execute_approved_tool(context)
    coordinator.execute_approved_tool(context)

    canonical_events = [
        event
        for event in context.timeline
        if event.get("approval_resume_result_canonical") is True
    ]
    assert tool_calls == ["browser.click"]
    assert len(canonical_events) == 1
    assert persisted_events == ["agent.tool.call", "agent.tool.outcome"]


def test_approval_resume_does_not_correlate_previous_canonical_generation_in_same_plan(
) -> None:
    executed_selectors: list[str] = []

    def call_agent_tool(
        tool_request: dict[str, Any],
        *_args: Any,
        **_kwargs: Any,
    ) -> dict[str, Any]:
        selector = str((tool_request.get("input") or {}).get("selector") or "")
        executed_selectors.append(selector)
        return {
            "ok": True,
            "action": "browser.click",
            "data": {"selector": selector},
        }

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=call_agent_tool,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
    )
    previous = _structured_approval_resume_context()
    coordinator.execute_approved_tool(previous)

    current_request = {
        **previous.tool_request,
        "input": {"selector": "#second-result"},
        "request_id": "request-click-second-result",
        "tool_call_id": "tool-call-click-second-result",
    }
    current = ToolApprovalResumeContext(
        run_id=previous.run_id,
        timeline=deepcopy(previous.timeline),
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["browser.click"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need next approval"}],
        tool_request=current_request,
        tool_name="browser.click",
        input_preview={"selector": "#second-result"},
        remaining_requests=[],
        next_iteration=3,
        approval_id="approval-browser-click-next",
    )

    coordinator.execute_approved_tool(current)

    canonical_events = [
        event
        for event in current.timeline
        if event.get("approval_resume_result_canonical") is True
    ]
    assert executed_selectors == ["#first-result", "#second-result"]
    assert len(canonical_events) == 2
    previous_canonical, current_canonical = canonical_events
    for field in (
        "run_id",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "step_id",
        "tool",
    ):
        assert current_canonical[field] == previous_canonical[field]
    for field in (
        "approval_id",
        "approval_generation_id",
        "approval_claim_id",
        "approval_request_fingerprint",
        "request_id",
        "tool_call_id",
    ):
        assert current_canonical[field] != previous_canonical[field]
    assert current_canonical["approval_request_fingerprint"] == (
        approval_request_fingerprint(current_request)
    )
    assert current_canonical["result"] == {
        "ok": True,
        "action": "browser.click",
        "data": {"selector": "#second-result"},
    }


def test_approval_resume_rejects_mismatched_canonical_result_identity() -> None:
    context = _structured_approval_resume_context()
    canonical = _structured_runtime_canonical_result()
    canonical["plan_id"] = "wrong-plan"
    context.timeline.append(canonical)
    tool_calls: list[str] = []
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: tool_calls.append("unexpected") or {},
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
    )

    with pytest.raises(AgentRuntimeError, match="approval_resume_result_identity_mismatch"):
        coordinator.execute_approved_tool(context)

    assert tool_calls == []


def test_approval_resume_rejects_canonical_result_without_runtime_actor() -> None:
    context = _structured_approval_resume_context()
    context.timeline.append(
        _timeline(
            "agent.tool.call",
            "browser.click",
            approval_resume_result_canonical=True,
            approved=True,
            approval_id="approval-browser-click",
            run_id="run-structured-approval",
            decision_id="decision-search",
            plan_id="plan-search",
            tool_plan_id="tool-plan-search",
            step_id="click-first-result",
            request_id="request-click-first-result",
            tool_call_id="tool-call-click-first-result",
            tool="browser.click",
            result={"ok": True, "action": "browser.click"},
        )
    )
    tool_calls: list[str] = []
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: tool_calls.append("unexpected") or {},
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
    )

    with pytest.raises(AgentRuntimeError, match="approval_resume_result_authority_mismatch"):
        coordinator.execute_approved_tool(context)

    assert tool_calls == []


@pytest.mark.parametrize(
    ("field", "untrusted_value"),
    [
        ("approved", False),
        ("actor", "model"),
        ("execution_authority", "desktop_provider"),
        ("execution_mode", "provider_reported_result"),
        ("visibility", "user"),
        ("sensitivity", "public"),
    ],
)
def test_approval_resume_rejects_untrusted_canonical_result_authority_field(
    field: str,
    untrusted_value: Any,
) -> None:
    source_context = _structured_approval_resume_context()
    source_coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "action": "browser.click",
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
    )
    source_coordinator.execute_approved_tool(source_context)
    canonical = deepcopy(
        next(
            event
            for event in source_context.timeline
            if event.get("approval_resume_result_canonical") is True
        )
    )
    canonical[field] = untrusted_value
    context = _structured_approval_resume_context()
    context.timeline.append(canonical)
    tool_calls: list[str] = []
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: tool_calls.append("unexpected") or {},
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
    )

    with pytest.raises(AgentRuntimeError, match="approval_resume_result_authority_mismatch"):
        coordinator.execute_approved_tool(context)

    assert tool_calls == []


@pytest.mark.parametrize(
    "field",
    [
        "approved",
        "actor",
        "execution_authority",
        "execution_mode",
        "visibility",
        "sensitivity",
        "approval_id",
        "approval_generation_id",
        "approval_claim_id",
        "approval_request_fingerprint",
        "run_id",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "step_id",
        "request_id",
        "tool_call_id",
        "tool",
        "provider_kind",
        "provider_id",
    ],
)
def test_approval_resume_rejects_canonical_result_missing_required_field(
    field: str,
) -> None:
    canonical = _structured_runtime_canonical_result()
    canonical.pop(field)
    context = _structured_approval_resume_context()
    context.timeline.append(canonical)
    tool_calls: list[str] = []

    with pytest.raises(
        AgentRuntimeError,
        match=(
            "approval_resume_result_authority_mismatch"
            if field
            in {
                "approved",
                "actor",
                "execution_authority",
                "execution_mode",
                "visibility",
                "sensitivity",
            }
            else "approval_resume_result_identity_mismatch"
        ),
    ):
        _structured_approval_resume_coordinator(tool_calls).execute_approved_tool(
            context
        )

    assert tool_calls == []


@pytest.mark.parametrize(
    "field",
    [
        "approval_id",
        "approval_generation_id",
        "approval_claim_id",
        "approval_request_fingerprint",
        "run_id",
        "decision_id",
        "plan_id",
        "tool_plan_id",
        "step_id",
        "request_id",
        "tool_call_id",
        "tool",
        "provider_kind",
        "provider_id",
    ],
)
def test_approval_resume_rejects_canonical_result_wrong_exact_identity(
    field: str,
) -> None:
    canonical = _structured_runtime_canonical_result()
    canonical[field] = f"wrong-{field}"
    context = _structured_approval_resume_context()
    context.timeline.append(canonical)
    tool_calls: list[str] = []

    with pytest.raises(
        AgentRuntimeError,
        match="approval_resume_result_identity_mismatch",
    ):
        _structured_approval_resume_coordinator(tool_calls).execute_approved_tool(
            context
        )

    assert tool_calls == []


def test_approval_resume_rejects_canonical_replay_after_claim_is_inactive() -> None:
    context = _structured_approval_resume_context()
    context.timeline.append(_structured_runtime_canonical_result())
    context.assert_resume_active = lambda *_args: (_ for _ in ()).throw(
        AgentRuntimeError("approval_resume_inactive")
    )
    tool_calls: list[str] = []
    result_consumers: list[str] = []
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: tool_calls.append("unexpected") or {},
        fatal_tool_failure_detail=lambda *_args: result_consumers.append("fatal-check")
        or "",
        append_tool_result_message=lambda *_args: result_consumers.append("message"),
        run_tool_requests=lambda *_args, **_kwargs: result_consumers.append("followup"),
        timeline_factory=_timeline,
    )

    with pytest.raises(AgentRuntimeError, match="approval_resume_inactive"):
        coordinator.execute_approved_tool(context)

    assert tool_calls == []
    assert result_consumers == []


def test_ordinary_approval_contract_identity_does_not_claim_recovery_authority() -> None:
    context = _structured_approval_resume_context()
    context.tool_request.update(
        {
            "source": "runtime_planner",
            "goal_contract_id": "contract-search",
            "goal_criterion_id": "criterion-click-result",
        }
    )
    tool_calls: list[str] = []

    _structured_approval_resume_coordinator(tool_calls).execute_approved_tool(
        context
    )

    assert tool_calls == ["browser.click"]


def test_approval_resume_does_not_publish_result_through_legacy_event_callback() -> None:
    context = _structured_approval_resume_context()
    public_events: list[tuple[str, str, dict[str, Any]]] = []
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "action": "browser.click",
            "data": {"private_selector": "#first-result"},
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: public_events.append(
            (run_id, event_type, payload)
        ),
    )

    coordinator.execute_approved_tool(context)

    canonical = next(
        event
        for event in context.timeline
        if event.get("approval_resume_result_canonical") is True
    )
    assert canonical["visibility"] == "internal"
    assert canonical["sensitivity"] == "private"
    assert public_events == []


def test_daily_desktop_approval_resume_result_omits_observations_and_localizes_click(
) -> None:
    context = ToolApprovalResumeContext(
        run_id="run-click",
        timeline=[
            _timeline(
                "agent.tool.call",
                "app.open",
                result={
                    "ok": True,
                    "action": "app.open",
                    "data": {"app_name": "PixelForge"},
                },
            ),
            _timeline(
                "agent.tool.call",
                "desktop.ui_elements",
                result={
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "summary": "Read PixelForge export controls",
                },
            ),
            _timeline(
                "agent.tool.call",
                "desktop.click_ui_element",
                result={
                    "ok": True,
                    "action": "desktop.click_ui_element",
                    "summary": "Clicked Export",
                    "data": {"matched_label": "Export", "target": "Export"},
                },
            ),
            _timeline(
                "agent.tool.call",
                "desktop.ui_elements",
                runtime_stage="verify",
                result={
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "summary": "Verified PixelForge export controls",
                },
            ),
        ],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=[
            "app.open",
            "desktop.click_ui_element",
            "desktop.ui_elements",
        ],
        budget={"events": 4},
        messages=[],
        tool_request={
            "tool": "desktop.click_ui_element",
            "input": {"target": "Export"},
            "source": "runtime_planner",
        },
        tool_name="desktop.click_ui_element",
        input_preview={"target": "Export"},
        remaining_requests=[],
        next_iteration=2,
    )

    result = _daily_desktop_resume_result_after_remaining_tools(
        context,
        resume_timeline_start=2,
    )

    assert result == "已打开 PixelForge。 已点击前台控件：Export。"


def test_daily_desktop_approval_resume_localizes_search_first_result() -> None:
    url = "https://example.com/search?q=yachiyo"
    context = ToolApprovalResumeContext(
        run_id="run-browser-first-result",
        timeline=[
            _timeline(
                "agent.tool.call",
                "browser.open_url",
                input_preview={"url": url},
                result={
                    "ok": True,
                    "action": "browser.open_url",
                    "summary": "Opened browser page with internal routing details",
                    "data": {"url": url},
                },
            ),
            _timeline(
                "agent.tool.call",
                "browser.click",
                input_preview={"selector": "#first-result"},
                result={
                    "ok": True,
                    "action": "browser.click",
                    "summary": "Clicked browser selector using internal CDP session",
                    "data": {
                        "label": "Yachiyo 首页",
                        "selector": "#first-result",
                        "tag": "A",
                    },
                },
            ),
        ],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["browser.open_url", "browser.click"],
        budget={"events": 2},
        messages=[],
        tool_request={
            "tool": "browser.click",
            "input": {"selector": "#first-result"},
            "source": "runtime_planner",
        },
        tool_name="browser.click",
        input_preview={"selector": "#first-result"},
        remaining_requests=[],
        next_iteration=2,
    )

    result = _daily_desktop_resume_result_after_remaining_tools(
        context,
        resume_timeline_start=1,
    )

    assert result == f"已打开网页：{url}。 已点击网页元素：Yachiyo 首页。"
    assert "internal" not in result
    assert "CDP" not in result


@pytest.mark.parametrize(
    ("tool_name", "result", "input_preview", "expected", "private_text"),
    [
        (
            "browser.click",
            {
                "ok": True,
                "action": "browser.click",
                "data": {"selector": "point=120,240", "x": 120, "y": 240},
            },
            {"selector": "point=120,240"},
            "已点击网页位置：120, 240。",
            "",
        ),
        (
            "browser.type_text",
            {
                "ok": True,
                "action": "browser.type_text",
                "data": {
                    "selector": (
                        'input[type="search"], input[name="q"], textarea[name="q"], '
                        'input[aria-label*="搜索" i], input[placeholder*="搜索" i], '
                        'input[aria-label*="search" i], input[placeholder*="search" i]'
                    ),
                    "length": 7,
                },
            },
            {
                "selector": 'input[type="search"], input[name="q"]',
                "text": "private-yachiyo",
            },
            "已在网页搜索框输入文字（7 个字符）。",
            "private-yachiyo",
        ),
        (
            "browser.type_text",
            {
                "ok": True,
                "action": "browser.type_text",
                "data": {"selector": "point=120,240", "length": 5},
            },
            {"selector": "point=120,240", "text": "hello"},
            "已在网页位置：120, 240 输入文字（5 个字符）。",
            "hello",
        ),
    ],
)
def test_daily_desktop_approval_resume_preserves_browser_target_without_input_text(
    tool_name: str,
    result: dict[str, Any],
    input_preview: dict[str, Any],
    expected: str,
    private_text: str,
) -> None:
    summary = _daily_desktop_tool_result_phrase(
        tool_name,
        result,
        input_preview=input_preview,
    )

    assert summary == expected
    if private_text:
        assert private_text not in summary


def test_daily_desktop_approval_resume_localizes_search_submit_summary() -> None:
    raw_summary = "Submitted foreground search query"

    summary = _daily_desktop_tool_result_phrase(
        "desktop.search_submit",
        {
            "ok": True,
            "action": "desktop.search_submit",
            "summary": raw_summary,
            "data": {"submit_action": "search"},
        },
        input_preview={"action": "search"},
    )

    assert summary == "已提交前台搜索。"
    assert raw_summary not in summary


def test_daily_desktop_browser_click_fallback_omits_raw_summary() -> None:
    context = ToolApprovalResumeContext(
        run_id="run-browser-click-fallback",
        timeline=[
            _timeline(
                "agent.tool.call",
                "browser.click",
                result={
                    "ok": True,
                    "action": "browser.click",
                    "summary": "Clicked sk-secret-value through private session-42",
                    "data": {},
                },
            )
        ],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["browser.click"],
        budget={"events": 1},
        messages=[],
        tool_request={
            "tool": "browser.click",
            "input": {},
            "source": "runtime_planner",
        },
        tool_name="browser.click",
        input_preview={},
        remaining_requests=[],
        next_iteration=2,
    )

    result = _daily_desktop_resume_result_after_remaining_tools(context)

    assert result == "已发送网页点击指令。"
    assert "sk-secret-value" not in result
    assert "session-42" not in result


def test_runtime_planner_terminal_approval_resume_finishes_without_model() -> None:
    context = ToolApprovalResumeContext(
        run_id="run-terminal-direct",
        timeline=[
            _timeline(
                "agent.tool.call",
                "terminal.run",
                input_preview={"command": "ls"},
                result={
                    "ok": True,
                    "returncode": 0,
                    "stdout": "Desktop\n",
                    "stderr": "",
                },
            )
        ],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 1},
        messages=[],
        tool_request={
            "tool": "terminal.run",
            "input": {"command": "ls"},
            "source": "runtime_planner",
        },
        tool_name="terminal.run",
        input_preview={"command": "ls"},
        remaining_requests=[],
        next_iteration=2,
    )

    result = _daily_desktop_resume_result_after_remaining_tools(context)

    assert result == "已运行命令：ls。\n输出：Desktop"


def test_approval_resume_completes_single_runtime_planner_desktop_action_without_model() -> None:
    context = ToolApprovalResumeContext(
        run_id="run-submit",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.submit_foreground", "desktop.ui_elements"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
        },
        tool_name="desktop.submit_foreground",
        input_preview={"action": "send"},
        remaining_requests=[
            {
                "tool": "desktop.ui_elements",
                "input": {},
                "runtime_stage": "verify",
            }
        ],
        next_iteration=2,
    )

    def submit_foreground(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = {
            "ok": True,
            "action": "desktop.submit_foreground",
            "summary": "Submitted foreground send action",
            "data": {"submit_action": "send"},
        }
        timeline.append(
            _timeline(
                "agent.tool.call",
                str(tool_request.get("tool") or ""),
                result=result,
            )
        )
        return result

    def verify_foreground(
        requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        assert requests[0]["tool"] == "desktop.ui_elements"
        timeline.append(
            _timeline(
                "agent.tool.call",
                "desktop.ui_elements",
                runtime_stage="verify",
                result={
                    "ok": True,
                    "action": "desktop.ui_elements",
                    "summary": "Read foreground UI",
                },
            )
        )

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=submit_foreground,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=verify_foreground,
        timeline_factory=_timeline,
        continue_custom_api_agent=lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("single direct desktop action should not call the model")
        ),
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool({}, context)

    assert result == "已向前台发送“发送”指令。"
    completion = next(
        event for event in context.timeline if event["event"] == "agent.desktop.intent_completed"
    )
    assert completion["tools"] == [
        "desktop.submit_foreground",
        "desktop.ui_elements",
    ]
    assert completion["steps"][-1]["tool"] == "desktop.ui_elements"
    assert completion["steps"][-1]["runtime_stage"] == "verify"


def test_approval_resume_synthesizes_final_desktop_post_action_verification() -> None:
    source_step_id = "operate-foreground-ui-followup-return"
    source_request_id = "runtime-plan-1:request:5:desktop.hotkey"
    context = ToolApprovalResumeContext(
        run_id="run-final-return",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.hotkey", "desktop.ui_elements"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
            "source": "runtime_planner",
            "request_id": source_request_id,
            "step_id": source_step_id,
            "requires_post_action_verification": True,
            "action_target": {
                "kind": "desktop_foreground",
                "action": "keyboard_shortcut",
                "key": "return",
                "target_scope": "foreground",
                "step_id": source_step_id,
            },
            "observation_retry": {
                "tool": "desktop.ui_elements",
                "from_tool": "desktop.ui_elements",
                "reason": "observe_foreground_ui",
            },
        },
        tool_name="desktop.hotkey",
        input_preview={"key": "return", "modifiers": []},
        remaining_requests=[],
        next_iteration=3,
    )
    captured_requests: list[list[dict[str, Any]]] = []

    def approved_return(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = {
            "ok": True,
            "action": "desktop.hotkey",
            "summary": "Sent hotkey",
            "data": {"key": "return", "modifiers": []},
        }
        timeline.append(
            _timeline(
                "agent.tool.call",
                "desktop.hotkey",
                request_id=tool_request.get("request_id"),
                step_id=tool_request.get("step_id"),
                requires_post_action_verification=True,
                action_target=tool_request.get("action_target"),
                result=result,
            )
        )
        return result

    def run_verification(
        requests: list[dict[str, Any]],
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        captured_requests.append(requests)

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=approved_return,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=run_verification,
        timeline_factory=_timeline,
    )

    coordinator.execute_approved_tool(context)

    assert len(captured_requests) == 1
    assert len(captured_requests[0]) == 1
    verification = captured_requests[0][0]
    assert verification["tool"] == "desktop.ui_elements"
    assert verification["runtime_stage"] == "verify"
    assert verification["step_id"] == f"{source_step_id}:runtime-verify"
    assert verification["source_step_id"] == source_step_id
    assert verification["source_request_id"] == source_request_id
    assert verification["depends_on"] == [source_step_id]
    assert verification["task_verification_targets"][0]["step_id"] == source_step_id


def test_approval_resume_does_not_complete_when_required_verifier_is_unavailable() -> None:
    source_step_id = "operate-foreground-ui-followup-return"
    context = ToolApprovalResumeContext(
        run_id="run-final-return-without-verifier",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.hotkey"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.hotkey",
            "input": {"key": "return", "modifiers": []},
            "source": "runtime_planner",
            "step_id": source_step_id,
            "requires_post_action_verification": True,
        },
        tool_name="desktop.hotkey",
        input_preview={"key": "return", "modifiers": []},
        remaining_requests=[],
        next_iteration=3,
    )
    continuation_calls: list[bool] = []

    def approved_return(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = {
            "ok": True,
            "action": "desktop.hotkey",
            "summary": "Sent hotkey",
            "data": {"key": "return", "modifiers": []},
        }
        timeline.append(
            _timeline(
                "agent.tool.call",
                "desktop.hotkey",
                step_id=tool_request.get("step_id"),
                requires_post_action_verification=True,
                result=result,
            )
        )
        return result

    def continue_without_false_completion(*_args: Any, **_kwargs: Any) -> str:
        continuation_calls.append(True)
        return "Continuation handled missing desktop verification."

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=approved_return,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_without_false_completion,
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool({}, context)

    assert result == "Continuation handled missing desktop verification."
    assert continuation_calls == [True]
    assert not any(
        event["event"] == "agent.desktop.intent_completed"
        for event in context.timeline
    )


def test_approval_resume_does_not_complete_from_stale_success_after_current_failure() -> None:
    context = ToolApprovalResumeContext(
        run_id="run-blocked-submit",
        timeline=[
            _timeline(
                "agent.tool.call",
                "app.open",
                runtime_stage="operate",
                result={
                    "ok": True,
                    "action": "app.open",
                    "data": {"app_name": "Notes"},
                },
            )
        ],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.submit_foreground"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.submit_foreground",
            "input": {"action": "send"},
            "source": "runtime_planner",
            "step_id": "submit-foreground-ui",
            "replan_triggers": ["verification_failed"],
        },
        tool_name="desktop.submit_foreground",
        input_preview={"action": "send"},
        remaining_requests=[],
        next_iteration=2,
    )
    continuation_calls: list[bool] = []

    def blocked_submit(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        result = {
            "ok": False,
            "status": "provider_required",
            "blocked_by_desktop_execution_policy": True,
            "summary": "Desktop provider is required",
        }
        timeline.append(
            _timeline(
                "agent.tool.skipped",
                str(tool_request.get("tool") or ""),
                result=result,
            )
        )
        return result

    def continue_after_replan(*_args: Any, **_kwargs: Any) -> str:
        continuation_calls.append(True)
        return "Replanned after the blocked action."

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=blocked_submit,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_after_replan,
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool({}, context)

    assert result == "Replanned after the blocked action."
    assert continuation_calls == [True]
    assert not any(
        event["event"] == "agent.desktop.intent_completed" for event in context.timeline
    )


@pytest.mark.parametrize(
    ("approved_path", "approved_step", "pending_path", "pending_step", "expected"),
    [
        ("out.txt", "apply-out", "report.md", "write-report", {}),
        (
            "./reports/../report.md",
            "apply-out",
            "report.md",
            "write-report",
            {"tool": "artifact.write", "path": "report.md"},
        ),
        (
            "out.txt",
            "write-report",
            "report.md",
            "write-report",
            {"tool": "artifact.write", "path": "report.md"},
        ),
    ],
)
def test_approval_resume_only_marks_same_artifact_intent_as_conflicting(
    approved_path: str,
    approved_step: str,
    pending_path: str,
    pending_step: str,
    expected: dict[str, str],
) -> None:
    context = ToolApprovalResumeContext(
        run_id="run-artifact-conflict",
        timeline=[
            _timeline(
                "agent.model.followup_context",
                "planner_full_plan_report_generation",
                source="runtime_planner",
                pending_execution_requests=[
                    {
                        "request_id": "pending-report",
                        "step_id": pending_step,
                        "tool_name": "artifact.write",
                        "input_preview": {"path": pending_path},
                    }
                ],
            )
        ],
        artifacts=[],
        broker={},
        allowed_tools=["workspace.write_patch", "artifact.write"],
        budget={},
        messages=[],
        tool_request={
            "protocol": "tool_calls",
            "tool": "workspace.write_patch",
            "request_id": "approved-write",
            "step_id": approved_step,
            "input": {"path": approved_path, "patch": "patch"},
        },
        tool_name="workspace.write_patch",
        input_preview={"path": approved_path, "patch": "patch"},
        remaining_requests=[],
        next_iteration=2,
    )

    assert _approval_resume_conflicting_pending_artifact(context) == expected


def test_approval_resume_keeps_unrelated_pending_artifact_after_model_write() -> None:
    context = ToolApprovalResumeContext(
        run_id="run-model-write",
        timeline=[
            _timeline(
                "agent.model.followup_context",
                "planner_full_plan_report_generation",
                source="runtime_planner",
                planning_reason="planner_full_plan_report_generation",
                content_snapshot={
                    "source_tool": "workspace.read",
                    "ok": True,
                    "text": "before",
                },
                pending_execution_requests=[
                    {
                        "request_id": "plan-report:request:2:artifact.write",
                        "step_id": "write-report-artifact",
                        "tool_name": "artifact.write",
                        "input_preview": {
                            "path": "report.md",
                            "body_source": "model_generated_content",
                        },
                    }
                ],
            )
        ],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["workspace.write_patch", "artifact.write"],
        budget={"events": 4},
        messages=[
            {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call-write",
                        "type": "function",
                        "function": {
                            "name": "workspace_write_patch",
                            "arguments": "{}",
                        },
                    }
                ],
            }
        ],
        tool_request={
            "protocol": "tool_calls",
            "tool": "workspace.write_patch",
            "function_name": "workspace_write_patch",
            "tool_call_id": "call-write",
            "input": {"path": "out.txt", "patch": "patch"},
        },
        tool_name="workspace.write_patch",
        input_preview={"path": "out.txt", "patch": "patch"},
        remaining_requests=[],
        next_iteration=2,
    )
    continuation_contexts: list[dict[str, Any]] = []

    def continue_custom_api_agent(
        _agent: dict[str, Any],
        _user_goal: str,
        _broker: Any,
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> str:
        latest_followup = next(
            event
            for event in reversed(timeline)
            if event["event"] == "agent.model.followup_context"
        )
        continuation_contexts.append(latest_followup)
        if latest_followup.get("pending_execution_requests"):
            return "已生成文件：report.md。"
        return "Main chat write complete"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=_approved_tool_call,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool({}, context)

    assert result == "已生成文件：report.md。"
    assert len(continuation_contexts) == 1
    assert continuation_contexts[0]["pending_execution_requests"][0][
        "input_preview"
    ]["path"] == "report.md"
    assert continuation_contexts[0].get("status") != "superseded"


def test_approval_resume_records_runtime_task_progress_events() -> None:
    task_core = {
        "core_id": "core-approval",
        "workspace": {"workspace_id": "workspace-1", "title": "Approval task"},
        "todos": [
            {
                "todo_id": "todo-click",
                "step_id": "operate-foreground-ui",
                "title": "Click export",
                "status": "pending",
            },
            {
                "todo_id": "todo-artifact",
                "step_id": "write-artifact",
                "title": "Write artifact",
                "status": "pending",
            },
        ],
        "checkpoints": [
            {
                "checkpoint_id": "checkpoint-click",
                "after_step_id": "operate-foreground-ui",
                "title": "Export clicked",
                "status": "planned",
            },
            {
                "checkpoint_id": "checkpoint-artifact",
                "after_step_id": "write-artifact",
                "title": "Artifact written",
                "status": "planned",
            },
        ],
    }
    timeline = [
        _timeline(
            "agent.plan.created",
            "plan",
            decision_id="decision-1",
            plan_id="plan-1",
            plan={
                "plan_id": "plan-1",
                "tool_plan": {
                    "steps": [
                        {
                            "step_id": "operate-foreground-ui",
                            "tool_name": "desktop.click_ui_element",
                        },
                        {
                            "step_id": "write-artifact",
                            "tool_name": "artifact.write",
                        },
                    ]
                },
            },
        ),
        _timeline(
            "agent.task_core.created",
            "task core",
            decision_id="decision-1",
            plan_id="plan-1",
            core_id="core-approval",
            task_id="task-approval",
            group_run_id="group-run-approval",
            workflow_run_id="workflow-run-approval",
            task_core=task_core,
        ),
        _timeline(
            "agent.task.todo.updated",
            "Click export",
            decision_id="decision-1",
            step_id="operate-foreground-ui",
            todo_id="todo-click",
            status="blocked",
        ),
        _timeline(
            "agent.task.checkpoint.updated",
            "Export clicked",
            decision_id="decision-1",
            step_id="operate-foreground-ui",
            checkpoint_id="checkpoint-click",
            status="waiting_approval",
        ),
    ]
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval",
        timeline=timeline,
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.click_ui_element", "artifact.write"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.click_ui_element",
            "input": {"target": "Export"},
        },
        tool_name="desktop.click_ui_element",
        input_preview={"target": "Export"},
        remaining_requests=[
            {"tool": "artifact.write", "input": {"path": "ok.md"}},
        ],
        next_iteration=3,
    )
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=_approved_tool_call,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            (run_id, event_type, payload)
        ),
    )

    coordinator.execute_approved_tool(context)

    completed_todos = [
        event
        for event in context.timeline
        if event["event"] == "workflow.run.task.todo.updated"
        and event.get("status") == "completed"
    ]
    completed_checkpoints = [
        event
        for event in context.timeline
        if event["event"] == "workflow.run.task.checkpoint.updated"
        and event.get("status") == "completed"
    ]
    assert {event["step_id"] for event in completed_todos} == {
        "operate-foreground-ui",
        "write-artifact",
    }
    assert {event["step_id"] for event in completed_checkpoints} == {
        "operate-foreground-ui",
        "write-artifact",
    }
    click_todo = next(
        event
        for event in completed_todos
        if event["step_id"] == "operate-foreground-ui"
    )
    click_checkpoint = next(
        event
        for event in completed_checkpoints
        if event["step_id"] == "operate-foreground-ui"
    )
    assert click_todo["previous_status"] == "blocked"
    assert click_checkpoint["previous_status"] == "waiting_approval"
    assert click_todo["task_id"] == "task-approval"
    assert click_todo["group_run_id"] == "group-run-approval"
    assert click_todo["workflow_run_id"] == "workflow-run-approval"
    assert click_todo["planner_event_type"] == "agent.task.todo.updated"
    assert click_todo["planner_scope"] == "workflow.run"
    assert {
        (run_id, event_type)
        for run_id, event_type, _payload in run_events
    } >= {
        ("run-approval", "workflow.run.task.todo.updated"),
        ("run-approval", "workflow.run.task.checkpoint.updated"),
    }


def test_approval_resume_skips_terminal_remaining_runtime_requests() -> None:
    captured_requests: list[list[dict[str, Any]]] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.open_app", "desktop.active_window", "artifact.write"],
        budget={"events": 0},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.open_app",
            "input": {"app_name": "PixelForge"},
            "step_id": "open-or-focus-app",
        },
        tool_name="desktop.open_app",
        input_preview={"app_name": "PixelForge"},
        remaining_requests=[
            {
                "tool": "desktop.list_apps",
                "input": {"query": "PixelForge"},
                "step_id": "discover-desktop-state",
                "status": "completed",
            },
            {
                "tool": "desktop.active_window",
                "input": {"app_name": "PixelForge"},
                "step_id": "verify-desktop-result",
                "status": "planned",
            },
            {
                "tool": "artifact.write",
                "input": {"path": "blocked.md"},
                "step_id": "write-blocked-artifact",
                "status": "denied",
            },
            {
                "tool": "artifact.write",
                "input": {"path": "needs-approval.md"},
                "step_id": "write-approved-artifact",
                "status": "waiting_approval",
                "approval_required": True,
            },
        ],
        next_iteration=3,
    )

    def run_tool_requests(
        requests: list[dict[str, Any]],
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        captured_requests.append(requests)

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=_approved_tool_call,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=run_tool_requests,
        timeline_factory=_timeline,
    )

    coordinator.execute_approved_tool(context)

    assert [[request["step_id"] for request in requests] for requests in captured_requests] == [
        ["verify-desktop-result", "write-approved-artifact"]
    ]
    assert context.remaining_requests == captured_requests[0]


def test_approval_resume_replans_policy_blocked_desktop_tool_without_running_remaining_requests() -> None:
    task_core = {
        "core_id": "core-desktop-approval",
        "workspace": {"workspace_id": "workspace-1", "title": "Desktop task"},
        "todos": [
            {
                "todo_id": "todo-type",
                "step_id": "type-into-foreground",
                "title": "Type into app",
                "status": "pending",
            },
            {
                "todo_id": "todo-artifact",
                "step_id": "write-artifact",
                "title": "Write artifact",
                "status": "pending",
            },
        ],
        "checkpoints": [
            {
                "checkpoint_id": "checkpoint-type",
                "after_step_id": "type-into-foreground",
                "title": "Text entered",
                "status": "planned",
            }
        ],
    }
    timeline = [
        _timeline(
            "agent.plan.created",
            "plan",
            decision_id="decision-desktop",
            plan_id="plan-desktop",
            plan={
                "plan_id": "plan-desktop",
                "tool_plan": {
                    "steps": [
                        {
                            "step_id": "type-into-foreground",
                            "tool_name": "desktop.safe_type_text",
                        },
                        {
                            "step_id": "write-artifact",
                            "tool_name": "artifact.write",
                        },
                    ]
                },
            },
        ),
        _timeline(
            "agent.task_core.created",
            "task core",
            decision_id="decision-desktop",
            plan_id="plan-desktop",
            core_id="core-desktop-approval",
            task_id="task-desktop",
            group_run_id="group-run-desktop",
            workflow_run_id="workflow-run-desktop",
            task_core=task_core,
        ),
    ]
    tool_result = {
        "ok": False,
        "status": "provider_required",
        "error": "desktop_execution_policy_blocked",
        "summary": "Desktop foreground execution was blocked by policy.",
        "blocked_by_desktop_execution_policy": True,
        "recovery_actions": [
            {
                "label": "Prepare sandbox desktop handoff",
                "tool": "screen.capture",
                "input": {"reason": "sandbox_desktop_handoff"},
                "recovery_action_kind": "sandbox_desktop_handoff",
            }
        ],
    }
    captured_requests: list[list[dict[str, Any]]] = []
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    context = ToolApprovalResumeContext(
        run_id="run-desktop-approval",
        timeline=timeline,
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.safe_type_text", "artifact.write", "screen.capture"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "step_id": "type-into-foreground",
            "capability_id": "desktop.keyboard_input",
            "decision_id": "decision-desktop",
            "plan_id": "plan-desktop",
            "core_id": "core-desktop-approval",
            "workspace_id": "workspace-1",
            "task_id": "task-desktop",
            "group_run_id": "group-run-desktop",
            "workflow_run_id": "workflow-run-desktop",
        },
        tool_name="desktop.safe_type_text",
        input_preview={"text": "hello"},
        remaining_requests=[
            {"tool": "artifact.write", "input": {"path": "should-not-run.md"}},
        ],
        next_iteration=3,
    )

    def call_agent_tool(
        tool_request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        run_timeline: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        run_timeline.append(
            _timeline(
                "agent.tool.skipped",
                str(tool_request.get("tool") or ""),
                input_preview=tool_request.get("input") or {},
                result=tool_result,
                status="skipped",
            )
        )
        return tool_result

    def run_tool_requests(
        requests: list[dict[str, Any]],
        *_args: Any,
        **_kwargs: Any,
    ) -> None:
        captured_requests.append(requests)

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=call_agent_tool,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=run_tool_requests,
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            (run_id, event_type, payload)
        ),
    )

    coordinator.execute_approved_tool(context)

    replan_event = next(
        event
        for event in context.timeline
        if event["event"] == "workflow.run.replan.requested"
    )
    replan_payload = replan_event["payload"]
    blocked_todo = next(
        event
        for event in context.timeline
        if event["event"] == "workflow.run.task.todo.updated"
        and event.get("step_id") == "type-into-foreground"
    )
    blocked_checkpoint = next(
        event
        for event in context.timeline
        if event["event"] == "workflow.run.task.checkpoint.updated"
        and event.get("checkpoint_id") == "checkpoint-type"
    )

    assert captured_requests == [[]]
    assert context.remaining_requests == []
    assert replan_payload["failure_event_type"] == "agent.tool.skipped"
    assert replan_payload["source_tool_name"] == "desktop.safe_type_text"
    assert replan_payload["source_step_id"] == "type-into-foreground"
    assert replan_payload["recovery_actions"][0]["tool"] == "screen.capture"
    assert blocked_todo["status"] == "blocked"
    assert blocked_checkpoint["status"] == "blocked"
    assert {
        (run_id, event_type)
        for run_id, event_type, _payload in run_events
    } >= {
        ("run-desktop-approval", "workflow.run.replan.requested"),
        ("run-desktop-approval", "workflow.run.task.todo.updated"),
        ("run-desktop-approval", "workflow.run.task.checkpoint.updated"),
    }


@pytest.mark.parametrize(
    "tool_result",
    [
        {
            "ok": False,
            "status": "provider_required",
            "error": "desktop_execution_provider_required",
            "recovery_actions": [
                {
                    "tool": "screen.capture",
                    "input": {"reason": "provider_handoff"},
                }
            ],
        },
        {
            "ok": False,
            "status": "blocked",
            "error": "desktop_execution_policy_blocked",
            "blocked_by_desktop_execution_policy": True,
            "recovery_actions": [
                {
                    "tool": "screen.capture",
                    "input": {"reason": "policy_handoff"},
                }
            ],
        },
    ],
    ids=["provider-required", "policy-blocked"],
)
def test_approval_resume_fresh_recoverable_result_keeps_replan_enabled(
    tool_result: dict[str, Any],
) -> None:
    flags: list[bool] = []
    context = ToolApprovalResumeContext(
        run_id="run-fresh-replan",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["desktop.safe_type_text", "screen.capture"],
        budget={"events": 2},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "desktop.safe_type_text",
            "input": {"text": "hello"},
            "step_id": "type-into-foreground",
            "replan_triggers": ["tool_failure"],
            "fallback_tools": ["screen.capture"],
        },
        tool_name="desktop.safe_type_text",
        input_preview={"text": "hello"},
        remaining_requests=[],
        next_iteration=2,
    )

    def continue_custom_api_agent(
        _agent: dict[str, Any],
        _user_goal: str,
        _broker: Any,
        handoff_timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        *,
        resume_after_approved_tool: bool,
        **_kwargs: Any,
    ) -> str:
        flags.append(resume_after_approved_tool)
        assert any(
            event["event"] == "agent.replan.requested"
            for event in handoff_timeline
        )
        return "recover through fresh replan"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: dict(tool_result),
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool(
        {"agent_id": "agent-fresh-replan"},
        context,
    )

    assert result == "recover through fresh replan"
    assert flags == [False]


def test_approval_resume_success_skips_only_stale_replan() -> None:
    flags: list[bool] = []
    context = ToolApprovalResumeContext(
        run_id="run-stale-replan",
        timeline=[
            _timeline(
                "agent.replan.requested",
                "old request",
                status="requested",
                payload={
                    "request_id": "old-replan",
                    "source": "runtime_tool_request_runner",
                },
            )
        ],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 1},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "terminal.run",
            "input": {"command": "printf ok"},
        },
        tool_name="terminal.run",
        input_preview={"command": "printf ok"},
        remaining_requests=[],
        next_iteration=2,
    )

    def continue_custom_api_agent(
        *_args: Any,
        resume_after_approved_tool: bool,
        **_kwargs: Any,
    ) -> str:
        flags.append(resume_after_approved_tool)
        return "consume fresh tool result"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {"ok": True, "stdout": "ok"},
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool(
        {"agent_id": "agent-stale-replan"},
        context,
    )

    assert result == "consume fresh tool result"
    assert flags == [True]


def test_approval_resume_records_replan_and_blocked_progress_for_failed_tool() -> None:
    task_core = {
        "core_id": "core-approval",
        "workspace": {"workspace_id": "workspace-1", "title": "Approval task"},
        "todos": [
            {
                "todo_id": "todo-analysis",
                "step_id": "run-analysis",
                "title": "Run analysis",
                "status": "pending",
            }
        ],
        "checkpoints": [
            {
                "checkpoint_id": "checkpoint-analysis",
                "after_step_id": "run-analysis",
                "title": "Analysis completed",
                "status": "planned",
            }
        ],
    }
    timeline = [
        _timeline(
            "agent.plan.created",
            "plan",
            decision_id="decision-1",
            plan_id="plan-1",
            plan={
                "plan_id": "plan-1",
                "tool_plan": {
                    "steps": [
                        {
                            "step_id": "run-analysis",
                            "tool_name": "terminal.run",
                        }
                    ]
                },
            },
        ),
        _timeline(
            "agent.task_core.created",
            "task core",
            decision_id="decision-1",
            plan_id="plan-1",
            core_id="core-approval",
            task_id="task-approval",
            group_run_id="group-run-approval",
            workflow_run_id="workflow-run-approval",
            task_core=task_core,
        ),
    ]
    run_events: list[tuple[str, str, dict[str, Any]]] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval",
        timeline=timeline,
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run", "python.run"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "terminal.run",
            "input": {"command": "python analyze.py"},
            "step_id": "run-analysis",
            "capability_id": "terminal.execution",
            "decision_id": "decision-1",
            "plan_id": "plan-1",
            "core_id": "core-approval",
            "workspace_id": "workspace-1",
            "task_id": "task-approval",
            "group_run_id": "group-run-approval",
            "workflow_run_id": "workflow-run-approval",
            "fallback_tools": ["python.run"],
            "replan_triggers": ["tool_failure"],
            "replan_signal_ids": ["replan-run-analysis"],
        },
        tool_name="terminal.run",
        input_preview={"command": "python analyze.py"},
        remaining_requests=[],
        next_iteration=3,
    )
    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "script failed",
        },
        fatal_tool_failure_detail=lambda *_args: "terminal.run failed fatally",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        append_run_event=lambda run_id, event_type, payload: run_events.append(
            (run_id, event_type, payload)
        ),
    )

    with pytest.raises(AgentRuntimeError):
        coordinator.execute_approved_tool(context)

    blocked_todo = next(
        event
        for event in context.timeline
        if event["event"] == "workflow.run.task.todo.updated"
        and event.get("status") == "blocked"
    )
    blocked_checkpoint = next(
        event
        for event in context.timeline
        if event["event"] == "workflow.run.task.checkpoint.updated"
        and event.get("status") == "blocked"
    )
    replan_event = next(
        event
        for event in context.timeline
        if event["event"] == "workflow.run.replan.requested"
    )
    replan_payload = replan_event["payload"]

    assert blocked_todo["task_id"] == "task-approval"
    assert blocked_todo["group_run_id"] == "group-run-approval"
    assert blocked_todo["workflow_run_id"] == "workflow-run-approval"
    assert blocked_todo["planner_event_type"] == "agent.task.todo.updated"
    assert blocked_todo["planner_scope"] == "workflow.run"
    assert blocked_checkpoint["task_id"] == "task-approval"
    assert replan_payload["planner_event_type"] == "agent.replan.requested"
    assert replan_payload["planner_scope"] == "workflow.run"
    assert replan_payload["source_step_id"] == "run-analysis"
    assert replan_payload["source_tool_name"] == "terminal.run"
    assert replan_payload["fallback_tools"] == ["python.run"]
    assert replan_payload["task_id"] == "task-approval"
    assert replan_payload["group_run_id"] == "group-run-approval"
    assert replan_payload["workflow_run_id"] == "workflow-run-approval"
    assert {
        (run_id, event_type)
        for run_id, event_type, _payload in run_events
    } >= {
        ("run-approval", "workflow.run.task.todo.updated"),
        ("run-approval", "workflow.run.task.checkpoint.updated"),
        ("run-approval", "workflow.run.replan.requested"),
    }


def test_approval_resume_continues_runtime_replan_after_failed_approved_tool() -> None:
    timeline = [
        _timeline(
            "agent.plan.created",
            "plan",
            decision_id="decision-1",
            plan_id="plan-1",
            plan={
                "plan_id": "plan-1",
                "tool_plan": {
                    "steps": [
                        {
                            "step_id": "run-analysis",
                            "tool_name": "terminal.run",
                        }
                    ]
                },
            },
        )
    ]
    continued: list[dict[str, Any]] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval",
        timeline=timeline,
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run", "python.run"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "terminal.run",
            "input": {"command": "python analyze.py"},
            "step_id": "run-analysis",
            "capability_id": "terminal.execution",
            "decision_id": "decision-1",
            "plan_id": "plan-1",
            "fallback_tools": ["python.run"],
            "replan_triggers": ["tool_failure"],
        },
        tool_name="terminal.run",
        input_preview={"command": "python analyze.py"},
        remaining_requests=[],
        next_iteration=3,
    )

    def continue_custom_api_agent(
        agent: dict[str, Any],
        user_goal: str,
        broker: Any,
        handoff_timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        messages: list[dict[str, Any]],
        start_iteration: int,
        run_id: str,
        budget: Any,
        resume_after_approved_tool: bool,
    ) -> str:
        replan_event = next(
            event
            for event in handoff_timeline
            if event["event"] == "agent.replan.requested"
        )
        continued.append(
            {
                "agent": agent,
                "user_goal": user_goal,
                "broker": broker,
                "artifacts": artifacts,
                "messages": messages,
                "start_iteration": start_iteration,
                "run_id": run_id,
                "budget": budget,
                "resume_after_approved_tool": resume_after_approved_tool,
                "replan": replan_event["payload"],
            }
        )
        return "Recovered through runtime replan."

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "error": "script failed",
        },
        fatal_tool_failure_detail=lambda *_args: "terminal.run failed fatally",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
    )

    result = coordinator.continue_and_project_after_approved_tool(
        agent={"agent_id": "agent-1"},
        context=context,
        project_completed=lambda _context, text: {"status": "completed", "result": text},
        project_required=lambda *_args: {"status": "approval_required"},
        project_failed=lambda _context, error: {"status": "failed", "error": error},
    )

    assert result == {
        "status": "completed",
        "result": "Recovered through runtime replan.",
    }
    assert len(continued) == 1
    assert continued[0]["start_iteration"] == 3
    assert continued[0]["run_id"] == "run-approval"
    assert continued[0]["resume_after_approved_tool"] is False
    assert continued[0]["replan"]["source_step_id"] == "run-analysis"
    assert continued[0]["replan"]["source_tool_name"] == "terminal.run"
    assert continued[0]["replan"]["fallback_tools"] == ["python.run"]


def test_approval_resume_partial_result_forces_a_fresh_model_replan() -> None:
    flags: list[bool] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval-partial",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 2},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "terminal.run",
            "tool_call_id": "approved-terminal-partial",
            "input": {"command": "printf partial"},
        },
        tool_name="terminal.run",
        input_preview={"command": "printf partial"},
        remaining_requests=[],
        next_iteration=2,
    )

    def continue_custom_api_agent(
        *_args: Any,
        resume_after_approved_tool: bool,
        **_kwargs: Any,
    ) -> str:
        flags.append(resume_after_approved_tool)
        return "Replanned after partial approved result."

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "status": "partial",
            "returncode": 0,
            "stdout": "partial",
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
    )

    result = coordinator.continue_custom_api_agent_after_approved_tool({}, context)

    assert result == "Replanned after partial approved result."
    assert flags == [False]
    assert not any(
        event.get("event") == "agent.desktop.intent_completed"
        for event in context.timeline
    )


def test_approval_resume_nonretryable_denial_projects_failure_without_model() -> None:
    continuation_calls = 0
    context = ToolApprovalResumeContext(
        run_id="run-approval-denied",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 2},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "terminal.run",
            "tool_call_id": "approved-terminal-denied",
            "input": {"command": "printf denied"},
        },
        tool_name="terminal.run",
        input_preview={"command": "printf denied"},
        remaining_requests=[],
        next_iteration=2,
    )

    def continue_custom_api_agent(*_args: Any, **_kwargs: Any) -> str:
        nonlocal continuation_calls
        continuation_calls += 1
        return "must not complete"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": True,
            "status": "denied",
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
    )

    result = coordinator.continue_and_project_after_approved_tool(
        agent={},
        context=context,
        project_completed=lambda _context, text: {
            "status": "completed",
            "result": text,
        },
        project_required=lambda _context, pending: {
            "status": "approval_required",
            "pending": pending,
        },
        project_failed=lambda _context, error: {
            "status": "failed",
            "error": error,
        },
    )

    assert result["status"] == "failed"
    assert "denied" in str(result["error"]).lower()
    assert continuation_calls == 0
    assert not any(
        event.get("event") == "agent.desktop.intent_completed"
        for event in context.timeline
    )


def test_approval_resume_permission_required_stops_without_model_completion() -> None:
    continuation_calls = 0
    projected_errors: list[Exception] = []
    persisted_events: list[tuple[str, str, dict[str, Any], dict[str, Any]]] = []
    secret = "sk-approval-resume-secret-123456789"
    context = ToolApprovalResumeContext(
        run_id="run-approval-permission",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 2},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "terminal.run",
            "tool_call_id": "approved-terminal-permission",
            "input": {
                "command": "printf permission",
                "api_key": secret,
            },
        },
        tool_name="terminal.run",
        input_preview={
            "command": "printf permission",
            "api_key": secret,
        },
        remaining_requests=[],
        next_iteration=2,
    )

    def continue_custom_api_agent(*_args: Any, **_kwargs: Any) -> str:
        nonlocal continuation_calls
        continuation_calls += 1
        return "must not complete"

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **event_fields: Any,
    ) -> dict[str, Any]:
        persisted_events.append(
            (run_id, event_type, deepcopy(payload), deepcopy(event_fields))
        )
        return {"event_type": event_type}

    def redact_error(error: Exception) -> str:
        projected_errors.append(error)
        return "safe permission failure"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "status": "permission_required",
            "permission_error": True,
            "missing_permissions": ["accessibility"],
            "recovery_hints": [
                "Open System Settings",
                f"api_key={secret}",
            ],
            "recovery_actions": [
                {
                    "action_id": "open-accessibility-settings",
                    "label": "Open Accessibility settings",
                    "tool": "system.settings_open",
                    "input": {
                        "target": "accessibility",
                        "api_key": secret,
                    },
                    "permission_target": "accessibility",
                    "risk_level": "low",
                },
                {
                    "action_id": "unsafe-terminal-action",
                    "label": "Run privileged command",
                    "tool": "terminal.run",
                    "input": {"command": "sudo true"},
                    "permission_target": "accessibility",
                    "risk_level": "high",
                    "approval_required": True,
                },
            ],
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
        append_run_event=append_run_event,
    )

    result = coordinator.continue_and_project_after_approved_tool(
        agent={},
        context=context,
        project_completed=lambda _context, text: {
            "status": "completed",
            "result": text,
        },
        project_required=lambda *_args: pytest.fail(
            "OS permission recovery must not create another approval"
        ),
        project_failed=lambda _context, error: {
            "status": "failed",
            "error": error,
        },
        redact_error=redact_error,
    )

    assert result["status"] == "failed"
    assert result["error"] == "safe permission failure"
    assert len(projected_errors) == 1
    assert isinstance(projected_errors[0], AgentDirectOutcomeUnverified)
    assert projected_errors[0].reason == "permission_required"
    assert continuation_calls == 0
    recovery_event = next(
        event
        for event in context.timeline
        if event.get("event") == "agent.desktop.permission_recovery"
    )
    assert recovery_event["source"] == "approval_resume"
    assert recovery_event["status"] == "permission_recovery_available"
    assert recovery_event["permission_error"] is True
    assert recovery_event["permission_targets"] == ["accessibility"]
    # Provider-suggested actions are intentionally not promoted across this
    # permission boundary; the consumer can use the target diagnostics and a
    # fresh, server-validated retry instead.
    assert "recovery_actions" not in recovery_event
    assert "unsafe-terminal-action" not in repr(recovery_event)
    assert secret not in repr(recovery_event)
    assert "[redacted]" in repr(recovery_event)
    persisted_recovery = next(
        payload
        for _run_id, event_type, payload, _fields in persisted_events
        if event_type == "agent.desktop.permission_recovery"
    )
    assert persisted_recovery == {
        key: value
        for key, value in recovery_event.items()
        if key not in {"event", "detail"}
    }
    assert not any(
        "approval_required" in event_type
        for _run_id, event_type, _payload, _fields in persisted_events
    )
    assert not any(
        event.get("event") == "agent.desktop.intent_completed"
        for event in context.timeline
    )


def test_approval_resume_generic_action_required_is_not_permission_recovery() -> None:
    continuation_calls = 0
    context = ToolApprovalResumeContext(
        run_id="run-approval-generic-action",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 2},
        messages=[],
        tool_request={
            "tool": "terminal.run",
            "tool_call_id": "approved-terminal-generic-action",
            "input": {"command": "printf action"},
        },
        tool_name="terminal.run",
        input_preview={"command": "printf action"},
        remaining_requests=[],
        next_iteration=2,
    )

    def continue_custom_api_agent(*_args: Any, **_kwargs: Any) -> str:
        nonlocal continuation_calls
        continuation_calls += 1
        return "must not complete"

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "status": "action_required",
            "user_action_required": True,
            "action_targets": ["choose_account"],
            "recovery_actions": [
                {
                    "label": "Choose account",
                    "tool": "app.open",
                    "input": {"app_name": "Settings"},
                    "risk_level": "low",
                }
            ],
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=continue_custom_api_agent,
    )

    result = coordinator.continue_and_project_after_approved_tool(
        agent={},
        context=context,
        project_completed=lambda _context, text: {
            "status": "completed",
            "result": text,
        },
        project_required=lambda *_args: pytest.fail(
            "generic action must not create another approval"
        ),
        project_failed=lambda _context, error: {
            "status": "failed",
            "error": error,
        },
    )

    assert result["status"] == "failed"
    assert "action_required" in result["error"]
    assert continuation_calls == 0
    assert not any(
        event.get("event") == "agent.desktop.permission_recovery"
        for event in context.timeline
    )


def test_approval_resume_requires_raw_permission_signal_for_recovery_event() -> None:
    class _Value:
        pass

    user_action = _Value()
    user_action.required = True
    user_action.kind = "permission"
    user_action.targets = ("accessibility",)
    outcome = _Value()
    outcome.user_action = user_action
    outcome.tool_name = "terminal.run"
    outcome.recovery_hints = ("Open System Settings",)
    outcome.raw = {"recovery_hints": ["Open System Settings"]}
    action_required = _Value()
    action_required.outcome = outcome
    action_required.source_tool_call_id = "forged-permission-action"
    context = ToolApprovalResumeContext(
        run_id="run-forged-permission-action",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 1},
        messages=[],
        tool_request={
            "tool": "terminal.run",
            "tool_call_id": "forged-permission-action",
            "input": {"command": "printf permission"},
        },
        tool_name="terminal.run",
        input_preview={"command": "printf permission"},
        remaining_requests=[],
        next_iteration=2,
    )

    assert (
        _approval_resume_permission_recovery_payload(
            context,
            action_required,
        )
        == {}
    )


def test_approval_resume_permission_recovery_is_discarded_when_run_cas_loses() -> None:
    persisted_events: list[tuple[str, str, dict[str, Any]]] = []
    context = ToolApprovalResumeContext(
        run_id="run-approval-permission-cas-lost",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["terminal.run"],
        budget={"events": 2},
        messages=[],
        tool_request={
            "tool": "terminal.run",
            "tool_call_id": "approved-terminal-permission-cas-lost",
            "input": {"command": "printf permission"},
        },
        tool_name="terminal.run",
        input_preview={"command": "printf permission"},
        remaining_requests=[],
        next_iteration=2,
    )

    def append_run_event(
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        **_event_fields: Any,
    ) -> dict[str, Any]:
        persisted_events.append((run_id, event_type, deepcopy(payload)))
        return {"event_type": event_type}

    def project_failed(
        working_context: ToolApprovalResumeContext,
        _error: str,
    ) -> dict[str, Any]:
        setattr(working_context, "_approval_resume_projection_state", "cas_lost")
        return {
            "status": "running",
            "updated_at": "2026-07-17T10:00:00Z",
        }

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: {
            "ok": False,
            "status": "permission_required",
            "permission_error": True,
            "missing_permissions": ["accessibility"],
        },
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
        continue_custom_api_agent=lambda *_args, **_kwargs: pytest.fail(
            "permission gate must not call the model"
        ),
        append_run_event=append_run_event,
    )

    result = coordinator.continue_and_project_after_approved_tool(
        agent={},
        context=context,
        project_completed=lambda *_args: pytest.fail(
            "permission gate must not complete"
        ),
        project_required=lambda *_args: pytest.fail(
            "permission gate must not create another approval"
        ),
        project_failed=project_failed,
    )

    assert result == {
        "status": "running",
        "updated_at": "2026-07-17T10:00:00Z",
    }
    assert context.timeline == []
    assert context.messages == []
    assert persisted_events == []


def _approved_tool_call(
    tool_request: dict[str, Any],
    _allowed_tools: list[str],
    _broker: Any,
    timeline: list[dict[str, Any]],
    *,
    artifacts: list[dict[str, Any]],
    approved: bool,
    run_id: str,
    budget: Any,
) -> dict[str, Any]:
    result = {"ok": True, "summary": "Clicked export"}
    timeline.append(
        _timeline(
            "agent.tool.call",
            str(tool_request.get("tool") or ""),
            input_preview=tool_request.get("input") or {},
            result=result,
            approved=approved,
            run_id=run_id,
            budget=budget,
            artifact_count=len(artifacts),
        )
    )
    return result


def _structured_approval_resume_context() -> ToolApprovalResumeContext:
    return ToolApprovalResumeContext(
        run_id="run-structured-approval",
        timeline=[],
        artifacts=[],
        broker={"broker": True},
        allowed_tools=["browser.click"],
        budget={"events": 4},
        messages=[{"role": "assistant", "content": "Need approval"}],
        tool_request={
            "tool": "browser.click",
            "input": {"selector": "#first-result"},
            "decision_id": "decision-search",
            "plan_id": "plan-search",
            "tool_plan_id": "tool-plan-search",
            "step_id": "click-first-result",
            "request_id": "request-click-first-result",
            "tool_call_id": "tool-call-click-first-result",
        },
        tool_name="browser.click",
        input_preview={"selector": "#first-result"},
        remaining_requests=[],
        next_iteration=2,
        approval_id="approval-browser-click",
    )


def _structured_approval_resume_coordinator(
    tool_calls: list[str],
) -> ApprovalResumeCoordinator:
    return ApprovalResumeCoordinator(
        call_agent_tool=lambda *_args, **_kwargs: tool_calls.append("browser.click")
        or {"ok": True, "action": "browser.click"},
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=_append_free_text_tool_result_message,
        run_tool_requests=_run_remaining_tool_requests,
        timeline_factory=_timeline,
    )


def _structured_runtime_canonical_result() -> dict[str, Any]:
    context = _structured_approval_resume_context()
    _structured_approval_resume_coordinator([]).execute_approved_tool(context)
    return deepcopy(
        next(
            event
            for event in context.timeline
            if event.get("approval_resume_result_canonical") is True
        )
    )


def _append_free_text_tool_result_message(
    messages: list[dict[str, Any]],
    tool_request: dict[str, Any],
    tool_result: dict[str, Any],
) -> None:
    messages.append(
        {
            "role": "user",
            "content": f"Tool result for {tool_request['tool']}: {tool_result}",
        }
    )


def _append_tool_result_message(
    messages: list[dict[str, Any]],
    tool_request: dict[str, Any],
    tool_result: dict[str, Any],
) -> None:
    messages.append(
        {
            "role": "tool",
            "name": str(tool_request.get("tool") or ""),
            "content": str(tool_result),
        }
    )


def _run_remaining_tool_requests(
    requests: list[dict[str, Any]],
    _allowed_tools: list[str],
    _broker: Any,
    _messages: list[dict[str, Any]],
    timeline: list[dict[str, Any]],
    artifacts: list[dict[str, Any]],
    *,
    next_iteration: int,
    run_id: str,
    budget: Any,
) -> None:
    for request in requests:
        result = {"ok": True, "summary": "Artifact written"}
        artifacts.append({"path": "ok.md"})
        timeline.append(
            _timeline(
                "agent.tool.call",
                str(request.get("tool") or ""),
                input_preview=request.get("input") or {},
                result=result,
                next_iteration=next_iteration,
                run_id=run_id,
                budget=budget,
            )
        )


def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
    return {"event": event, "detail": detail, **extra}
