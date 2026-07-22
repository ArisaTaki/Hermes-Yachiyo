from __future__ import annotations

import json
from copy import deepcopy
from typing import Any

import pytest

from apps.shell.agent.runtime.custom_api_agent import (
    RuntimeCustomApiAgentLoop,
    _CustomApiRecoveryRuntimePort,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_EXECUTION_PROVENANCE_VERSION,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.goal_runtime import (
    goal_contract_event_payload,
    runtime_goal_assessment,
)
from apps.shell.agent.runtime.outcome_loop import (
    OutcomeLoopDisposition,
    OutcomeLoopResult,
)
from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionExecutionMode,
    RecoveryActionDisposition,
    RecoveryActionRegistry,
    RecoveryActionResult,
    RecoveryToolBatch,
    RecoveryToolResult,
)
from apps.shell.agent.runtime.recovery_adapters import BackgroundWindowRecoveryAdapter
from apps.shell.agent.runtime.recovery_policies import assess_latest_tool_recovery
from apps.shell.agent.runtime.recovery_policies import RecoveryAssessment
from apps.shell.agent.runtime.recovery_lineage import (
    RUNTIME_PRIVATE_RECOVERY_AUTHORITY,
    RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY,
    rehydrate_private_recovery_context,
    trusted_recovery_trace_fields,
)
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalResumeContext,
    ToolPendingApprovalBuilder,
)
from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    ToolOutcome,
    VerificationStatus,
)


class _Projection:
    def artifact_completion(self, *_args: Any, **_kwargs: Any) -> str:
        return ""

    def loop_limit_detail(self, *_args: Any, **_kwargs: Any) -> str:
        return "limit"


def _loop(
    recovery_action_registry: RecoveryActionRegistry | None = None,
) -> RuntimeCustomApiAgentLoop:
    return RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://example.invalid",
            "model": "test",
            "api_key": "test",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": []},
        },
        run_budget=lambda _run_id, _timeline: object(),
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda _allowed: [],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=3,
        operating_doctrine="test",
        memory_tool_names=(),
        future_task_tool_names=(),
        call_model=lambda *_args, **_kwargs: {},
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(message.get("content") or ""),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda _message, _content: [],
        timeline_factory=lambda event, detail, **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_Projection(),
        run_tool_requests=lambda *_args, **_kwargs: None,
        error_type=RuntimeError,
        recovery_action_registry=recovery_action_registry,
    )


def _effect_contract() -> GoalContract:
    return GoalContract(
        contract_id="goal-effect-1",
        run_id="run-effect-1",
        original_goal="Apply the requested change",
        criteria=(
            GoalCriterion(
                criterion_id="apply",
                description="The requested change is applied",
                effectful=True,
                required_capabilities=("demo.effect",),
                expected={
                    "state": "applied",
                    "target": {"kind": "demo", "action": "apply"},
                },
                source_step_ids=("apply-demo",),
            ),
        ),
    )


def _runtime_owned_terminal_event(contract: GoalContract, event: dict[str, Any]) -> dict[str, Any]:
    shaped = dict(event)
    tool_name = str(shaped.get("tool") or shaped.get("detail") or "").strip()
    call_id = str(shaped.get("tool_call_id") or "").strip()
    shaped.setdefault("run_id", contract.run_id)
    shaped.setdefault("actor", "native_runtime")
    shaped.setdefault("execution_authority", "runtime_tool_executor")
    shaped.setdefault("plan_id", f"plan-{contract.contract_id}")
    shaped.setdefault("step_id", f"step-{call_id}")
    shaped.setdefault("request_id", f"request-{call_id}")
    result = dict(shaped.get("result") or {})
    provider = (
        dict(result.get("desktop_execution_provider") or {})
        if isinstance(result.get("desktop_execution_provider"), dict)
        else {}
    )
    if provider.get("provider_kind") and provider.get("provider_id"):
        provider["adapter_registered"] = True
        result["tool"] = tool_name
        result["desktop_execution_provider_routed"] = True
        result["desktop_execution_provider"] = provider
        result["desktop_execution_route"] = {
            "selected_provider_kind": provider["provider_kind"],
            "selected_provider_id": provider["provider_id"],
        }
        result.setdefault(
            "desktop_execution_provider_evidence",
            {"tool": tool_name, "executor_receipt": True},
        )
    else:
        result[RUNTIME_EXECUTION_PROVENANCE_KEY] = {
            "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
            "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
        }
    shaped["result"] = result
    return shaped


def test_model_prose_cannot_complete_effectful_goal_without_runtime_evidence() -> None:
    loop = _loop()
    messages = [{"role": "user", "content": "Apply the requested change"}]
    timeline: list[dict[str, Any]] = []

    result = loop._goal_gated_model_output(
        "Done",
        {"role": "assistant", "content": "Done"},
        contract=_effect_contract(),
        messages=messages,
        timeline=timeline,
        run_id="run-effect-1",
    )

    assert result is None
    assert messages[-1]["role"] == "user"
    assert "original goal is not complete" in messages[-1]["content"]
    assert any(event["event"] == "agent.goal.replan_required" for event in timeline)


def test_verified_correlated_tool_receipt_allows_effectful_goal_output() -> None:
    loop = _loop()
    contract = _effect_contract()
    messages = [{"role": "user", "content": "Apply the requested change"}]
    timeline = [
        _runtime_owned_terminal_event(contract, {
            "event": "agent.tool.call",
            "detail": "demo.apply",
            "tool_call_id": "call-apply-1",
            "step_id": "apply-demo",
            "capability_id": "demo.effect",
            "action_target": {"kind": "demo", "action": "apply"},
            "result": {"ok": True, "postcondition_verified": True},
        })
    ]

    result = loop._goal_gated_model_output(
        "Done",
        {"role": "assistant", "content": "Done"},
        contract=contract,
        messages=messages,
        timeline=timeline,
        run_id="run-effect-1",
    )

    assert result == "Done"
    assessment_event = next(
        event for event in timeline if event["event"] == "agent.goal.assessed"
    )
    assert assessment_event["status"] == "completed"


def _structured_recovery_fixture() -> tuple[
    GoalContract,
    RecoveryAssessment,
    list[dict[str, Any]],
]:
    contract = GoalContract(
        contract_id="goal-recovery-1",
        run_id="run-recovery-1",
        original_goal="Play the requested track",
        criteria=(
            GoalCriterion(
                criterion_id="playback",
                description="The requested track is actively playing",
                effectful=True,
                required_capabilities=("media.playback",),
                source_step_ids=("control-media-playback",),
            ),
        ),
    )
    source_result = {
        "ok": True,
        "desktop_execution_provider": {
            "provider_kind": "background_desktop",
            "provider_id": "media-provider-1",
        },
        "data": {
            "status": "not_found",
            "outcome": "partial",
            "playback_started": False,
        },
    }
    source_event = _runtime_owned_terminal_event(contract, {
        "event": "agent.tool.call",
        "run_id": contract.run_id,
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "plan_id": "plan-media-recovery",
        "step_id": "control-media-playback",
        "detail": "media.catalog_play",
        "tool_call_id": "source-play-1",
        "capability_id": "media.playback",
        "result": source_result,
    })
    source_result = dict(source_event["result"])
    outcome = ToolOutcome(
        tool_name="media.catalog_play",
        capabilities=("media.playback",),
        status=OutcomeStatus.PARTIAL,
        reason="not_found",
        retryable=True,
        effects=(),
        verification=VerificationStatus.UNVERIFIED,
        user_action=None,
        recovery_hints=("entity_not_found",),
        provenance={},
        raw=source_result,
    )
    assessment = RecoveryAssessment(
        outcome=outcome,
        plan=RecoveryPlan(
            strategy_id="resolve-entity-alias",
            action="resolve_entity_alias",
            recovery_hint="entity_not_found",
            required_capabilities=(
                "browser.research",
                "information.capture",
                "media.playback",
            ),
            source_status=OutcomeStatus.PARTIAL,
            source_reason="not_found",
            scope_id="tool-attempt:test",
        ),
        tool_call_id="source-play-1",
    )
    timeline = [
        {
            "event": "agent.goal.contract",
            "detail": contract.contract_id,
            **goal_contract_event_payload(contract),
        },
        source_event,
    ]
    return contract, assessment, timeline


def test_recovery_plan_opens_subgoal_bound_to_unsatisfied_root_criterion() -> None:
    class Adapter:
        action = "resolve_entity_alias"
        execution_mode = RecoveryActionExecutionMode.OBSERVATION_ONLY

        def supports(self, _context: Any) -> bool:
            return True

        def execute(self, _context: Any) -> RecoveryActionResult:
            return RecoveryActionResult.not_handled(reason="test_stop")

        def reconcile_completed_attempt(self, _batch: Any) -> RecoveryActionResult:
            return RecoveryActionResult.not_handled(reason="test_stop")

    contract, assessment, timeline = _structured_recovery_fixture()
    loop = _loop(RecoveryActionRegistry((Adapter(),)))

    result = loop._execute_runtime_recovery_plan(
        assessment,
        model_config={},
        allowed_tools=[
            "media.catalog_play",
            "browser.search",
            "browser.extract_text",
        ],
        broker=object(),
        messages=[{"role": "user", "content": contract.original_goal}],
        timeline=timeline,
        artifacts=[],
        budget=object(),
        iteration=0,
        run_id=contract.run_id,
    )

    assert result.reason == "test_stop"
    subgoal_event = next(
        event for event in timeline if event["event"] == "agent.goal.subgoal.opened"
    )
    assert subgoal_event["contract_id"] == contract.contract_id
    assert subgoal_event["criterion_id"] == "playback"
    assert subgoal_event["subgoal"]["action"] == "resolve_entity_alias"
    assert json.loads(subgoal_event["subgoal_json"]) == subgoal_event["subgoal"]
    recovery_event = next(
        event for event in timeline if event["event"] == "agent.recovery.planned"
    )
    assert recovery_event["goal_contract_id"] == contract.contract_id
    assert recovery_event["goal_criterion_id"] == "playback"
    assert recovery_event["root_goal_unchanged"] is True


def test_structured_goal_defers_effectful_recovery_to_main_loop() -> None:
    class Adapter:
        action = "resolve_entity_alias"
        execution_mode = RecoveryActionExecutionMode.EFFECTFUL

        def __init__(self) -> None:
            self.execute_calls = 0

        def supports(self, _context: Any) -> bool:
            return True

        def execute(self, _context: Any) -> RecoveryActionResult:
            self.execute_calls += 1
            return RecoveryActionResult.complete("must not execute")

    contract, assessment, timeline = _structured_recovery_fixture()
    adapter = Adapter()
    loop = _loop(RecoveryActionRegistry((adapter,)))

    result = loop._execute_runtime_recovery_plan(
        assessment,
        model_config={},
        allowed_tools=[
            "media.catalog_play",
            "browser.search",
            "browser.extract_text",
        ],
        broker=object(),
        messages=[{"role": "user", "content": contract.original_goal}],
        timeline=timeline,
        artifacts=[],
        budget=object(),
        iteration=0,
        run_id=contract.run_id,
    )

    assert result.reason == "effectful_recovery_deferred_to_goal_loop"
    assert adapter.execute_calls == 0
    assert not any(
        str(event.get("event") or "").startswith("agent.recovery.")
        for event in timeline
    )


def test_structured_goal_allows_only_goal_bounded_background_window_effectful_recovery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract = GoalContract(
        contract_id="goal-background-window-1",
        run_id="run-background-window-1",
        original_goal="Open the agent-owned editor window",
        criteria=(
            GoalCriterion(
                criterion_id="editor_ready",
                description="The owned editor window is materialized and ready",
                effectful=True,
                required_capabilities=("desktop.app_control",),
                source_step_ids=("open-owned-editor",),
            ),
        ),
    )
    source_result = {
        "ok": False,
        "action": "app.open",
        "error": "cua_background_window_not_ready",
        "retryable": True,
        "agent_owned_target": True,
        "pid": 731011,
        "self_activation_suppressed": True,
        "desktop_execution_provider_transport": {
            "provider_kind": "background_desktop",
            "provider_id": "cua-driver",
            "transport": "electron_bridge",
            "delivery_mode": "background",
            "foreground_takeover_required": False,
            "mcp_tool": "launch_app",
        },
    }
    source_event = _runtime_owned_terminal_event(
        contract,
        {
            "event": "agent.tool.failed",
            "run_id": contract.run_id,
            "actor": "native_runtime",
            "execution_authority": "runtime_tool_executor",
            "plan_id": "plan-background-window",
            "step_id": "open-owned-editor",
            "detail": "app.open",
            "tool": "app.open",
            "tool_call_id": "open-owned-app-1",
            "capability_id": "desktop.app_control",
            "result": source_result,
        },
    )
    assessment = assess_latest_tool_recovery(
        (source_event,),
        start_index=0,
        allowed_tools=("app.open", "desktop.safe_shortcut", "desktop.read_ui"),
        attempt_lineage=(),
    )
    assert assessment is not None and assessment.plan is not None
    assert assessment.plan.action == "materialize_background_window"

    timeline = [
        {
            "event": "agent.goal.contract",
            "detail": contract.contract_id,
            **goal_contract_event_payload(contract),
        },
        source_event,
    ]
    loop = _loop(RecoveryActionRegistry((BackgroundWindowRecoveryAdapter(),)))
    calls: list[dict[str, Any]] = []

    def fake_execute_tools(
        self: _CustomApiRecoveryRuntimePort,
        tool_requests: list[dict[str, Any]],
        *,
        allowed_tools: list[str],
        next_iteration: int,
    ) -> RecoveryToolBatch:
        shaped_requests = tuple(
            self._request_with_recovery_identity(request) for request in tool_requests
        )
        calls.append(
            {
                "requests": shaped_requests,
                "allowed_tools": tuple(allowed_tools),
                "next_iteration": next_iteration,
            }
        )
        result_by_tool = {
            "desktop.safe_shortcut": {
                "ok": True,
                "action_dispatched": True,
                "delivery_dispatched": True,
                "delivery_verified": False,
                "window_materialization_pending": True,
                "postcondition_verified": False,
                "requires_postcondition_verification": True,
                "desktop_execution_provider_transport": {
                    "provider_kind": "background_desktop",
                    "delivery_mode": "background",
                    "foreground_takeover_required": False,
                },
            },
            "desktop.read_ui": {
                "ok": True,
                "data": {
                    "pid": 731011,
                    "window_id": 1911,
                    "agent_owned_target": True,
                    "target_bound": True,
                },
                "desktop_execution_provider_transport": {
                    "provider_kind": "background_desktop",
                    "delivery_mode": "background",
                    "foreground_takeover_required": False,
                },
            },
        }
        return RecoveryToolBatch(
            requests=shaped_requests,
            results=tuple(
                RecoveryToolResult(
                    tool_call_id=str(request["tool_call_id"]),
                    result=result_by_tool[str(request["tool"])],
                )
                for request in shaped_requests
            ),
        )

    monkeypatch.setattr(
        _CustomApiRecoveryRuntimePort,
        "execute_tools",
        fake_execute_tools,
    )

    result = loop._execute_runtime_recovery_plan(
        assessment,
        model_config={},
        allowed_tools=["app.open"],
        broker=object(),
        messages=[{"role": "user", "content": contract.original_goal}],
        timeline=timeline,
        artifacts=[],
        budget=object(),
        iteration=0,
        run_id=contract.run_id,
    )

    assert result.reason == "background_window_materialized"
    assert result.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    assert len(calls) == 1
    assert calls[0]["allowed_tools"] == ("desktop.safe_shortcut", "desktop.read_ui")
    assert calls[0]["next_iteration"] == 1
    assert [request["tool"] for request in calls[0]["requests"]] == [
        "desktop.safe_shortcut",
        "desktop.read_ui",
    ]
    for request in calls[0]["requests"]:
        assert request["goal_contract_id"] == contract.contract_id
        assert request["goal_criterion_id"] == "editor_ready"
        assert request["goal_subgoal_id"]
        assert request["root_goal_unchanged"] is True
        assert request["plan_id"] == "plan-background-window"
        assert request["source_step_id"] == "open-owned-editor"
        assert request["step_id"] == "open-owned-editor"
    assert len(
        [
            event
            for event in timeline
            if event["event"] == "agent.goal.subgoal.opened"
        ]
    ) == 1


def _background_window_dependency_fixture(
    *,
    step_chain: tuple[dict[str, Any], ...],
) -> tuple[GoalContract, RecoveryAssessment, list[dict[str, Any]], str]:
    contract = GoalContract(
        contract_id="goal-background-window-dependency-1",
        run_id="run-background-window-dependency-1",
        original_goal="Type into the agent-owned editor window",
        criteria=(
            GoalCriterion(
                criterion_id="editor_text_inserted",
                description="The owned editor window accepts the requested text",
                effectful=True,
                required_capabilities=("desktop.ui_operation",),
                source_step_ids=("type-owned-editor-document",),
            ),
        ),
    )
    plan_id = "plan-background-window-dependency"
    source_event = _runtime_owned_terminal_event(
        contract,
        {
            "event": "agent.tool.failed",
            "run_id": contract.run_id,
            "actor": "native_runtime",
            "execution_authority": "runtime_tool_executor",
            "plan_id": plan_id,
            "step_id": "open-owned-editor",
            "detail": "app.open",
            "tool": "app.open",
            "tool_call_id": "open-owned-app-dependency-1",
            "capability_id": "desktop.app_control",
            "result": {
                "ok": False,
                "action": "app.open",
                "error": "cua_background_window_not_ready",
                "retryable": True,
                "agent_owned_target": True,
                "pid": 731011,
                "self_activation_suppressed": True,
                "desktop_execution_provider_transport": {
                    "provider_kind": "background_desktop",
                    "provider_id": "cua-driver",
                    "transport": "electron_bridge",
                    "delivery_mode": "background",
                    "foreground_takeover_required": False,
                    "mcp_tool": "launch_app",
                },
            },
        },
    )
    assessment = assess_latest_tool_recovery(
        (source_event,),
        start_index=0,
        allowed_tools=("app.open", "desktop.safe_shortcut", "desktop.read_ui"),
        attempt_lineage=(),
    )
    assert assessment is not None and assessment.plan is not None
    assert assessment.plan.action == "materialize_background_window"
    timeline = [
        {
            "event": "agent.goal.contract",
            "detail": contract.contract_id,
            **goal_contract_event_payload(contract),
        },
        {
            "event": "agent.plan.selection",
            "detail": plan_id,
            "run_id": contract.run_id,
            "plan_id": plan_id,
            "selected_source": "runtime_execution_envelope",
            "yachiyo_execution_envelope": {
                "envelope_id": "execution-envelope-background-window-dependency",
                "intent_kind": "desktop_operation",
                "requests": list(step_chain),
            },
        },
        source_event,
    ]
    return contract, assessment, timeline, plan_id


def _install_background_window_fake_batch(
    monkeypatch: pytest.MonkeyPatch,
) -> list[dict[str, Any]]:
    calls: list[dict[str, Any]] = []

    def fake_execute_tools(
        self: _CustomApiRecoveryRuntimePort,
        tool_requests: list[dict[str, Any]],
        *,
        allowed_tools: list[str],
        next_iteration: int,
    ) -> RecoveryToolBatch:
        shaped_requests = tuple(
            self._request_with_recovery_identity(request) for request in tool_requests
        )
        calls.append(
            {
                "requests": shaped_requests,
                "allowed_tools": tuple(allowed_tools),
                "next_iteration": next_iteration,
            }
        )
        result_by_tool = {
            "desktop.safe_shortcut": {
                "ok": True,
                "action_dispatched": True,
                "delivery_dispatched": True,
                "delivery_verified": False,
                "window_materialization_pending": True,
                "postcondition_verified": False,
                "requires_postcondition_verification": True,
                "desktop_execution_provider_transport": {
                    "provider_kind": "background_desktop",
                    "delivery_mode": "background",
                    "foreground_takeover_required": False,
                },
            },
            "desktop.read_ui": {
                "ok": True,
                "data": {
                    "pid": 731011,
                    "window_id": 1911,
                    "agent_owned_target": True,
                    "target_bound": True,
                },
                "desktop_execution_provider_transport": {
                    "provider_kind": "background_desktop",
                    "delivery_mode": "background",
                    "foreground_takeover_required": False,
                },
            },
        }
        return RecoveryToolBatch(
            requests=shaped_requests,
            results=tuple(
                RecoveryToolResult(
                    tool_call_id=str(request["tool_call_id"]),
                    result=result_by_tool[str(request["tool"])],
                )
                for request in shaped_requests
            ),
        )

    monkeypatch.setattr(
        _CustomApiRecoveryRuntimePort,
        "execute_tools",
        fake_execute_tools,
    )
    return calls


def test_structured_goal_background_window_recovery_accepts_declared_dependency_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, assessment, timeline, plan_id = _background_window_dependency_fixture(
        step_chain=(
            {
                "request_id": "request-open-owned-editor",
                "step_id": "open-owned-editor",
                "tool_name": "app.open",
                "input": {"app_name": "TextEdit", "bring_to_front": False},
                "status": "planned",
                "source": "runtime_planner",
            },
            {
                "request_id": "request-type-owned-editor-document",
                "step_id": "type-owned-editor-document",
                "tool_name": "desktop.safe_type_text",
                "input": {"text": "hello from runtime"},
                "depends_on": ["open-owned-editor"],
                "status": "planned",
                "source": "runtime_planner",
            },
        ),
    )
    loop = _loop(RecoveryActionRegistry((BackgroundWindowRecoveryAdapter(),)))
    calls = _install_background_window_fake_batch(monkeypatch)

    result = loop._execute_runtime_recovery_plan(
        assessment,
        model_config={},
        allowed_tools=["app.open"],
        broker=object(),
        messages=[{"role": "user", "content": contract.original_goal}],
        timeline=timeline,
        artifacts=[],
        budget=object(),
        iteration=0,
        run_id=contract.run_id,
    )

    assert result.reason == "background_window_materialized"
    assert result.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    assert len(calls) == 1
    assert calls[0]["allowed_tools"] == ("desktop.safe_shortcut", "desktop.read_ui")
    assert calls[0]["next_iteration"] == 1
    assert [request["tool"] for request in calls[0]["requests"]] == [
        "desktop.safe_shortcut",
        "desktop.read_ui",
    ]
    assert calls[0]["requests"][0]["input"] == {"action": "new_document"}
    assert calls[0]["requests"][1]["input"] == {}
    for request in calls[0]["requests"]:
        assert request["goal_contract_id"] == contract.contract_id
        assert request["goal_criterion_id"] == "editor_text_inserted"
        assert request["goal_subgoal_id"]
        assert request["root_goal_unchanged"] is True
        assert request["plan_id"] == plan_id
        assert request["source_step_id"] == "open-owned-editor"
        assert request["step_id"] == "open-owned-editor"
    assert not any(
        event["event"] == "agent.goal.replan_required" for event in timeline
    )


def test_structured_goal_background_window_recovery_requires_declared_dependency_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, assessment, timeline, _plan_id = _background_window_dependency_fixture(
        step_chain=(
            {
                "request_id": "request-open-owned-editor",
                "step_id": "open-owned-editor",
                "tool_name": "app.open",
                "input": {"app_name": "TextEdit", "bring_to_front": False},
                "status": "planned",
                "source": "runtime_planner",
            },
            {
                "request_id": "request-observe-owned-editor",
                "step_id": "observe-owned-editor",
                "tool_name": "desktop.read_ui",
                "input": {},
                "depends_on": ["open-owned-editor"],
                "status": "planned",
                "source": "runtime_planner",
            },
            {
                "request_id": "request-type-owned-editor-document",
                "step_id": "type-owned-editor-document",
                "tool_name": "desktop.safe_type_text",
                "input": {"text": "hello from runtime"},
                "depends_on": ["some-other-step"],
                "status": "planned",
                "source": "runtime_planner",
            },
        ),
    )
    loop = _loop(RecoveryActionRegistry((BackgroundWindowRecoveryAdapter(),)))
    calls = _install_background_window_fake_batch(monkeypatch)

    result = loop._execute_runtime_recovery_plan(
        assessment,
        model_config={},
        allowed_tools=["app.open"],
        broker=object(),
        messages=[{"role": "user", "content": contract.original_goal}],
        timeline=timeline,
        artifacts=[],
        budget=object(),
        iteration=0,
        run_id=contract.run_id,
    )

    assert result.disposition is RecoveryActionDisposition.NOT_HANDLED
    assert result.reason == "goal_criterion_unmatched"
    assert calls == []
    assert not any(
        event["event"] == "agent.goal.subgoal.opened" for event in timeline
    )


def test_structured_goal_background_window_recovery_accepts_transitive_dependency_path(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    contract, assessment, timeline, plan_id = _background_window_dependency_fixture(
        step_chain=(
            {
                "request_id": "request-open-owned-editor",
                "step_id": "open-owned-editor",
                "tool_name": "app.open",
                "input": {"app_name": "TextEdit", "bring_to_front": False},
                "status": "planned",
                "source": "runtime_planner",
            },
            {
                "request_id": "request-observe-owned-editor",
                "step_id": "observe-owned-editor",
                "tool_name": "desktop.read_ui",
                "input": {},
                "depends_on": ["open-owned-editor"],
                "status": "planned",
                "source": "runtime_planner",
            },
            {
                "request_id": "request-type-owned-editor-document",
                "step_id": "type-owned-editor-document",
                "tool_name": "desktop.safe_type_text",
                "input": {"text": "hello from runtime"},
                "depends_on": ["observe-owned-editor"],
                "status": "planned",
                "source": "runtime_planner",
            },
        ),
    )
    loop = _loop(RecoveryActionRegistry((BackgroundWindowRecoveryAdapter(),)))
    calls = _install_background_window_fake_batch(monkeypatch)

    result = loop._execute_runtime_recovery_plan(
        assessment,
        model_config={},
        allowed_tools=["app.open"],
        broker=object(),
        messages=[{"role": "user", "content": contract.original_goal}],
        timeline=timeline,
        artifacts=[],
        budget=object(),
        iteration=0,
        run_id=contract.run_id,
    )

    assert result.reason == "background_window_materialized"
    assert result.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    assert len(calls) == 1
    for request in calls[0]["requests"]:
        assert request["goal_contract_id"] == contract.contract_id
        assert request["goal_criterion_id"] == "editor_text_inserted"
        assert request["plan_id"] == plan_id
        assert request["source_step_id"] == "open-owned-editor"
        assert request["step_id"] == "open-owned-editor"


def test_recovery_port_authorizes_only_the_root_return_tool() -> None:
    port = _CustomApiRecoveryRuntimePort(
        owner=_loop(),
        model_config={},
        allowed_tools=["media.catalog_play", "browser.search"],
        broker=object(),
        messages=[],
        timeline=[],
        artifacts=[],
        budget=object(),
        run_id="run-recovery-authority",
        source_tool_call_id="source-play",
        source_tool_name="media.catalog_play",
        recovery_action="resolve_entity_alias",
        recovery_scope_id="scope-play",
        recovery_goal_identity={
            "goal_contract_id": "goal-play",
            "goal_criterion_id": "criterion-play",
            "goal_subgoal_id": "subgoal-play",
            "root_goal_unchanged": True,
            "root_plan_id": "plan-play",
            "root_source_step_id": "control-media-playback",
        },
    )

    retry = port._request_with_recovery_identity(
        {
            "tool": "media.catalog_play",
            "tool_call_id": "retry-play",
            "input": {"query": "canonical alias"},
        }
    )
    discovery = port._request_with_recovery_identity(
        {
            "tool": "browser.search",
            "tool_call_id": "search-alias",
            "input": {"query": "alias"},
        }
    )

    private_context = retry[RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY]
    assert private_context["_authority"] is RUNTIME_PRIVATE_RECOVERY_AUTHORITY
    assert private_context["return_to_root"] is True
    assert private_context["plan_id"] == "plan-play"
    assert private_context["source_step_id"] == "control-media-playback"
    assert private_context["recovery_suggested_tool"] == "media.catalog_play"
    assert retry["goal_subgoal_id"] == "subgoal-play"
    assert retry["plan_id"] == "plan-play"
    assert retry["source_step_id"] == "control-media-playback"
    assert retry["recovery_suggested_tool"] == "media.catalog_play"
    assert trusted_recovery_trace_fields(
        "media.catalog_play",
        retry,
        private_context,
        run_id="run-recovery-authority",
    ) == {"recovery_context_trusted": True}
    for key, forged in (
        ("plan_id", "forged-plan"),
        ("source_step_id", "forged-step"),
        ("recovery_suggested_tool", "browser.search"),
    ):
        assert trusted_recovery_trace_fields(
            "media.catalog_play",
            {**retry, key: forged},
            private_context,
            run_id="run-recovery-authority",
        ) == {}
    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in discovery


def test_goal_loop_recovery_port_mints_independent_observation_authority() -> None:
    port = _CustomApiRecoveryRuntimePort(
        owner=_loop(),
        model_config={},
        allowed_tools=["workspace.list", "app.open"],
        broker=object(),
        messages=[],
        timeline=[],
        artifacts=[],
        budget=object(),
        run_id="run-recovery-observation",
        source_tool_call_id="source-read",
        source_tool_name="workspace.read",
        recovery_action="resolve_file_location",
        recovery_scope_id="scope-read",
        recovery_goal_identity={
            "goal_contract_id": "goal-read",
            "goal_criterion_id": "criterion-read",
            "goal_subgoal_id": "subgoal-read",
            "root_goal_unchanged": True,
            "root_plan_id": "plan-read",
            "root_source_step_id": "read-workspace-file",
        },
        observation_only=True,
    )

    observation = port._request_with_recovery_identity(
        {
            "tool": "workspace.list",
            "tool_call_id": "list-workspace",
            "input": {"path": "."},
            "action_target": {"path": "forged"},
            "postcondition_verified": True,
        }
    )

    assert observation["observation_only"] is True
    assert observation["goal_completion_authority"] is False
    assert observation["source_step_id"] == "read-workspace-file"
    assert observation["step_id"].startswith(
        "runtime-recovery-observation-step-"
    )
    assert observation["step_id"] != observation["source_step_id"]
    assert "action_target" not in observation
    assert "postcondition_verified" not in observation
    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in observation

    with pytest.raises(
        ValueError,
        match="Goal-loop recovery may execute only trusted observation tools",
    ):
        port.execute_tools(
            (
                {
                    "tool": "app.open",
                    "tool_call_id": "open-effectfully",
                    "input": {"app_name": "Example"},
                },
            ),
            allowed_tools=("app.open",),
            next_iteration=1,
        )


def _verification_repair_binding_fixture() -> tuple[
    GoalContract,
    list[dict[str, Any]],
    dict[str, Any],
    list[dict[str, Any]],
]:
    run_id = "run-verifier-repair-authority"
    plan_id = "plan-verifier-repair-authority"
    contract = GoalContract(
        contract_id="goal-verifier-repair-authority",
        run_id=run_id,
        original_goal="Repair the file and verify it",
        criteria=(
            GoalCriterion(
                criterion_id="criterion-verifier-repair-authority",
                description="The exact repair passes verification",
                effectful=True,
                required_capabilities=("file.workspace_write",),
                source_step_ids=("apply-code-changes",),
                verifier_step_ids=("verify-code-changes",),
            ),
        ),
    )
    provenance = {
        "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
        "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
    }
    common = {
        "event": "agent.tool.call",
        "run_id": run_id,
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "plan_id": plan_id,
    }
    timeline = [
        {
            **common,
            "detail": "workspace.write_patch",
            "step_id": "apply-code-changes",
            "request_id": "request-root-patch",
            "tool_call_id": "call-root-patch",
            "capability_id": "file.workspace_write",
            "result": {
                "ok": True,
                "state": "persisted",
                RUNTIME_EXECUTION_PROVENANCE_KEY: provenance,
            },
        },
        {
            **common,
            "detail": "terminal.run",
            "step_id": "verify-code-changes",
            "request_id": "request-failed-verifier",
            "tool_call_id": "call-failed-verifier",
            "capability_id": "terminal.execution",
            "result": {
                "ok": False,
                "exit_code": 1,
                "error": "tests failed",
                RUNTIME_EXECUTION_PROVENANCE_KEY: provenance,
            },
        },
    ]
    followup = {
        "planning_reason": "planner_replan_after_verification_failed",
        "plan_id": plan_id,
        "replan_requests": [
            _runtime_owned_terminal_event(contract, {
                "request_id": "replan-verifier-repair-authority",
                "trigger": "verification_failed",
                "source": "runtime_tool_request_runner",
                "run_id": run_id,
                "plan_id": plan_id,
                "source_step_id": "verify-code-changes",
                "source_tool_name": "terminal.run",
            })
        ],
    }
    requests = [
        {
            "tool": "workspace.write_patch",
            "input": {"path": "app.py", "patch": "--- app.py\n+++ app.py\n"},
            "plan_id": plan_id,
            "step_id": "repair-after-verification",
            "request_id": "request-repair-after-verification",
            "tool_call_id": "call-repair-after-verification",
            "runtime_stage": "operate",
            "replan_trigger": "verification_failed",
            "replan_request_id": "replan-verifier-repair-authority",
            "approval_required": True,
        }
    ]
    return contract, timeline, followup, requests


def test_verifier_repair_binding_defers_private_authority_until_approval() -> None:
    contract, timeline, followup, requests = _verification_repair_binding_fixture()

    bound = _loop()._bind_runtime_goal_recovery_lineage(
        requests,
        followup_context=followup,
        contract=contract,
        timeline=timeline,
        run_id=contract.run_id,
    )

    assert len(bound) == 1
    request = bound[0]
    assert "recovery_context_trusted" not in request
    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in request
    assert request["goal_contract_id"] == contract.contract_id
    assert request["goal_criterion_id"] == contract.criteria[0].criterion_id
    assert request["root_source_tool_call_id"] == "call-root-patch"
    assert request["recovery_origin_tool_call_id"] == "call-failed-verifier"


def test_approved_verifier_repair_remints_private_authority_and_completes_root_goal() -> None:
    contract, timeline, followup, _requests = _verification_repair_binding_fixture()
    timeline.insert(
        0,
        {
            "event": "agent.goal.contract",
            "detail": contract.contract_id,
            **goal_contract_event_payload(contract),
        },
    )
    repair_step_id = "repair-after-verification"
    repair_request_id = "request-approved-repair"
    verify_request_id = "request-approved-reverify"
    bound = _loop()._bind_runtime_goal_recovery_lineage(
        [
            {
                "tool": "workspace.write_patch",
                "input": {
                    "path": "app.py",
                    "patch": "--- app.py\n+++ app.py\n",
                },
                "plan_id": "plan-verifier-repair-authority",
                "step_id": repair_step_id,
                "request_id": repair_request_id,
                "tool_call_id": "call-approved-repair",
                "runtime_stage": "operate",
                "replan_trigger": "verification_failed",
                "replan_request_id": "replan-verifier-repair-authority",
                "approval_required": True,
            },
            {
                "tool": "terminal.run",
                "input": {"command": "python -m pytest"},
                "plan_id": "plan-verifier-repair-authority",
                "step_id": "verify-code-changes",
                "request_id": verify_request_id,
                "tool_call_id": "call-approved-reverify",
                "depends_on": [repair_step_id],
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "replan_trigger": "verification_failed",
                "replan_request_id": "replan-verifier-repair-authority",
                "approval_required": False,
            },
        ],
        followup_context=followup,
        contract=contract,
        timeline=timeline,
        run_id=contract.run_id,
    )
    repair_request, reverify_request = bound
    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in repair_request
    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY in reverify_request

    timeline.append(
        {
            "event": "agent.tool.call",
            "detail": repair_request["tool"],
            "run_id": contract.run_id,
            "actor": "native_runtime",
            "execution_authority": "runtime_tool_executor",
            "plan_id": repair_request["plan_id"],
            "step_id": repair_request["step_id"],
            "request_id": repair_request["request_id"],
            "tool_call_id": repair_request["tool_call_id"],
            "result": {
                "ok": False,
                "status": "approval_required",
                "approval_required": True,
            },
        }
    )
    pending = ToolPendingApprovalBuilder(
        approval_id_factory=lambda: "approval-verifier-repair",
        now=lambda: "2026-07-17T00:00:00Z",
    ).build(
        repair_request,
        messages=[{"role": "assistant", "content": "Repair requires approval"}],
        next_iteration=3,
        remaining_tool_requests=[reverify_request],
    )

    def contains_private_authority(value: Any) -> bool:
        if isinstance(value, dict):
            return bool(
                RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY in value
                or "recovery_context_trusted" in value
                or any(contains_private_authority(item) for item in value.values())
            )
        if isinstance(value, list):
            return any(contains_private_authority(item) for item in value)
        return False

    assert not contains_private_authority(pending)

    active_approval = {"id": "", "status": "pending"}

    def claim_pending_approval(
        run_id: str,
        _pending: dict[str, Any],
        *,
        expected_approval_id: str,
    ) -> bool:
        assert run_id == contract.run_id
        assert expected_approval_id == pending["approval_id"]
        if active_approval["status"] != "pending":
            return False
        active_approval.update(id=expected_approval_id, status="approved")
        return True

    def assert_resume_active(run_id: str, approval_id: str) -> None:
        assert run_id == contract.run_id
        assert active_approval == {"id": approval_id, "status": "approved"}

    context = ToolApprovalResumeContext.from_run(
        {
            "run_id": contract.run_id,
            "user_goal": contract.original_goal,
            "timeline": timeline,
            "artifacts": [],
        },
        pending,
        broker={"broker": True},
        allowed_tools=["workspace.write_patch", "terminal.run"],
        budget={"events": 8},
        assert_resume_active=assert_resume_active,
    )
    executed_requests: list[dict[str, Any]] = []
    provider = {
        "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
        "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
    }

    def append_terminal(
        request: dict[str, Any],
        target_timeline: list[dict[str, Any]],
        result: dict[str, Any],
        *,
        approved: bool = False,
        event_source: str = "",
    ) -> None:
        projection = dict(request)
        private_context = projection.pop(
            RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY,
            None,
        )
        projection.pop("recovery_context_trusted", None)
        projection.update(
            trusted_recovery_trace_fields(
                str(projection.get("tool") or ""),
                projection,
                private_context,
                run_id=contract.run_id,
            )
        )
        # The Runtime trace projection excludes approval policy input; an
        # approved success must not be reclassified as the earlier pause.
        projection.pop("approval_required", None)
        if event_source:
            projection["source"] = event_source
        target_timeline.append(
            {
                "event": "agent.tool.call",
                "detail": projection["tool"],
                "run_id": contract.run_id,
                "actor": "native_runtime",
                "execution_authority": "runtime_tool_executor",
                "approved": approved,
                **projection,
                "result": result,
            }
        )

    def call_agent_tool(
        request: dict[str, Any],
        _allowed_tools: list[str],
        _broker: Any,
        target_timeline: list[dict[str, Any]],
        **kwargs: Any,
    ) -> dict[str, Any]:
        assert kwargs["approved"] is True
        executed_requests.append(dict(request))
        result = {
            "ok": True,
            "state": "persisted",
            RUNTIME_EXECUTION_PROVENANCE_KEY: provider,
        }
        append_terminal(
            request,
            target_timeline,
            result,
            approved=True,
        )
        return result

    def run_remaining_requests(
        requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        _messages: list[dict[str, Any]],
        target_timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> None:
        assert len(requests) == 1
        request = requests[0]
        executed_requests.append(dict(request))
        result = {
            "ok": True,
            "exit_code": 0,
            "postcondition_verified": True,
            "verification_satisfied_by_native_receipt": True,
            "source_tool_call_id": request["source_tool_call_id"],
            "source_tool": "workspace.write_patch",
            "source_step_id": repair_step_id,
            "plan_id": "plan-verifier-repair-authority",
            "provider_kind": "local_desktop",
            "provider_id": "local-native-desktop",
            RUNTIME_EXECUTION_PROVENANCE_KEY: provider,
        }
        append_terminal(
            request,
            target_timeline,
            result,
            event_source="runtime_native_postcondition_receipt",
        )

    def continue_agent(
        _agent: dict[str, Any],
        _user_goal: str,
        _broker: Any,
        handoff_timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> str:
        assessment = runtime_goal_assessment(contract, handoff_timeline)
        assert assessment.completed
        return "Root goal completed after approved repair and re-verification."

    coordinator = ApprovalResumeCoordinator(
        call_agent_tool=call_agent_tool,
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=lambda *_args: None,
        run_tool_requests=run_remaining_requests,
        timeline_factory=lambda event, detail, **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        claim_pending_approval=claim_pending_approval,
        approve_tool_run=lambda run_id, **_kwargs: {
            "run_id": run_id,
            "status": "running",
        },
        continue_custom_api_agent=continue_agent,
        get_current_run=lambda run_id: {"run_id": run_id, "status": "running"},
    )
    result = coordinator.resume_approved_tool_run(
        run_id=contract.run_id,
        pending=pending,
        context=context,
        agent={"agent_id": "coder"},
        resumed_detail="Approved repair resumed",
        running_result="Repairing",
        expected_approval_id=pending["approval_id"],
        project_completed=lambda _context, text: {
            "status": "completed",
            "result": text,
        },
        project_required=lambda *_args: {"status": "approval_required"},
        project_failed=lambda _context, error: {
            "status": "failed",
            "error": error,
        },
        get_current_run=lambda run_id: {"run_id": run_id, "status": "running"},
    )

    assert result == {
        "status": "completed",
        "result": "Root goal completed after approved repair and re-verification.",
    }
    assert len(executed_requests) == 2
    assert all(
        RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY in request
        for request in executed_requests
    )
    assert not contains_private_authority(context.tool_request)
    assert not contains_private_authority(context.remaining_requests)


def _approved_recovery_remaining_remint_fixture() -> tuple[
    GoalContract,
    ToolApprovalResumeContext,
    dict[str, Any],
]:
    contract, timeline, followup, _requests = _verification_repair_binding_fixture()
    timeline.insert(
        0,
        {
            "event": "agent.goal.contract",
            "detail": contract.contract_id,
            **goal_contract_event_payload(contract),
        },
    )
    repair_step_id = "repair-after-verification"
    repair_request, reverify_request = _loop()._bind_runtime_goal_recovery_lineage(
        [
            {
                "tool": "workspace.write_patch",
                "input": {"path": "app.py", "patch": "--- app.py\n+++ app.py\n"},
                "plan_id": "plan-verifier-repair-authority",
                "step_id": repair_step_id,
                "request_id": "request-approved-repair-negative",
                "tool_call_id": "call-approved-repair-negative",
                "runtime_stage": "operate",
                "replan_trigger": "verification_failed",
                "replan_request_id": "replan-verifier-repair-authority",
                "approval_required": True,
            },
            {
                "tool": "terminal.run",
                "input": {"command": "python -m pytest"},
                "plan_id": "plan-verifier-repair-authority",
                "step_id": "verify-code-changes",
                "request_id": "request-approved-reverify-negative",
                "tool_call_id": "call-approved-reverify-negative",
                "depends_on": [repair_step_id],
                "runtime_stage": "verify",
                "runtime_role": "verify_result",
                "replan_trigger": "verification_failed",
                "replan_request_id": "replan-verifier-repair-authority",
                "approval_required": False,
            },
        ],
        followup_context=followup,
        contract=contract,
        timeline=timeline,
        run_id=contract.run_id,
    )
    timeline.append(
        {
            "event": "agent.tool.call",
            "detail": repair_request["tool"],
            "run_id": contract.run_id,
            "actor": "native_runtime",
            "execution_authority": "runtime_tool_executor",
            "plan_id": repair_request["plan_id"],
            "step_id": repair_request["step_id"],
            "request_id": repair_request["request_id"],
            "tool_call_id": repair_request["tool_call_id"],
            "result": {
                "ok": False,
                "status": "approval_required",
                "approval_required": True,
            },
        }
    )
    pending = ToolPendingApprovalBuilder(
        approval_id_factory=lambda: "approval-verifier-repair-negative",
        now=lambda: "2026-07-17T00:00:00Z",
    ).build(
        repair_request,
        messages=[{"role": "assistant", "content": "Repair requires approval"}],
        next_iteration=3,
        remaining_tool_requests=[reverify_request],
    )
    context = ToolApprovalResumeContext.from_run(
        {
            "run_id": contract.run_id,
            "user_goal": contract.original_goal,
            "timeline": timeline,
            "artifacts": [],
        },
        pending,
        broker={"broker": True},
        allowed_tools=["workspace.write_patch", "terminal.run"],
        budget={"events": 8},
    )
    private_context = rehydrate_private_recovery_context(
        context.tool_request,
        context.timeline,
        run_id=context.run_id,
        goal_contract=context.goal_contract,
    )
    assert private_context
    projection = dict(context.tool_request)
    projection.update(
        trusted_recovery_trace_fields(
            str(projection.get("tool") or ""),
            projection,
            private_context,
            run_id=context.run_id,
        )
    )
    projection.pop("approval_required", None)
    context.timeline.append(
        {
            "event": "agent.tool.call",
            "detail": projection["tool"],
            "run_id": contract.run_id,
            "actor": "native_runtime",
            "execution_authority": "runtime_tool_executor",
            "approved": True,
            **projection,
            "result": {
                "ok": True,
                "state": "persisted",
                RUNTIME_EXECUTION_PROVENANCE_KEY: {
                    "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
                    "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
                },
            },
        }
    )
    return contract, context, dict(context.remaining_requests[0])


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("step_id", "verify-some-other-step"),
        ("tool", "python.run"),
        ("depends_on", ["some-other-repair"]),
    ],
)
def test_approved_recovery_does_not_remint_mutated_remaining_verifier(
    field: str,
    replacement: Any,
) -> None:
    contract, context, request = _approved_recovery_remaining_remint_fixture()
    request[field] = replacement

    assert rehydrate_private_recovery_context(
        request,
        context.timeline,
        run_id=contract.run_id,
        goal_contract=context.goal_contract,
    ) == {}


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("goal_subgoal_id", "subgoal-forged"),
        ("recovery_scope_id", "recovery-scope-forged"),
        ("root_plan_id", "plan-forged"),
    ],
)
def test_approved_recovery_does_not_remint_mutated_remaining_lineage(
    field: str,
    replacement: Any,
) -> None:
    contract, context, request = _approved_recovery_remaining_remint_fixture()
    request[field] = replacement

    assert rehydrate_private_recovery_context(
        request,
        context.timeline,
        run_id=contract.run_id,
        goal_contract=context.goal_contract,
    ) == {}


@pytest.mark.parametrize("provider_mode", ["missing", "mismatched"])
def test_approved_recovery_does_not_remint_unattested_remaining_provider(
    provider_mode: str,
) -> None:
    contract, context, request = _approved_recovery_remaining_remint_fixture()
    timeline = deepcopy(context.timeline)
    for event in timeline:
        if (
            event.get("event") == "agent.tool.call"
            and event.get("tool_call_id") == request["source_tool_call_id"]
            and isinstance(event.get("result"), dict)
            and event["result"].get("ok") is True
        ):
            event["result"].pop(RUNTIME_EXECUTION_PROVENANCE_KEY, None)
            if provider_mode == "mismatched":
                event["result"]["desktop_execution_provider"] = {
                    "provider_kind": "background_desktop",
                    "provider_id": "forged-provider",
                }

    assert rehydrate_private_recovery_context(
        request,
        timeline,
        run_id=contract.run_id,
        goal_contract=context.goal_contract,
    ) == {}


def _nonexecuting_recovery_resume_coordinator(
    *,
    claim_pending_approval: Any,
    executed: list[dict[str, Any]],
) -> ApprovalResumeCoordinator:
    return ApprovalResumeCoordinator(
        call_agent_tool=lambda request, *_args, **_kwargs: (
            executed.append(dict(request)) or {"ok": True}
        ),
        fatal_tool_failure_detail=lambda *_args: "",
        append_tool_result_message=lambda *_args: None,
        run_tool_requests=lambda *_args, **_kwargs: None,
        timeline_factory=lambda event, detail, **payload: {
            "event": event,
            "detail": detail,
            **payload,
        },
        claim_pending_approval=claim_pending_approval,
        approve_tool_run=lambda run_id, **_kwargs: {
            "run_id": run_id,
            "status": "running",
        },
        continue_custom_api_agent=lambda *_args, **_kwargs: "unexpected",
    )


@pytest.mark.parametrize("terminal_status", ["rejected", "cancelled", "running"])
def test_rejected_cancelled_or_replayed_claim_cannot_remint_recovery_authority(
    terminal_status: str,
) -> None:
    contract, context, _request = _approved_recovery_remaining_remint_fixture()
    executed: list[dict[str, Any]] = []
    coordinator = _nonexecuting_recovery_resume_coordinator(
        claim_pending_approval=lambda *_args, **_kwargs: False,
        executed=executed,
    )

    result = coordinator.resume_approved_tool_run(
        run_id=contract.run_id,
        pending={"approval_id": context.approval_id},
        context=context,
        agent={"agent_id": "coder"},
        resumed_detail="Recovery resumed",
        running_result="Recovering",
        expected_approval_id=context.approval_id,
        project_completed=lambda *_args: {"status": "completed"},
        project_required=lambda *_args: {"status": "approval_required"},
        project_failed=lambda *_args: {"status": "failed"},
        get_current_run=lambda run_id: {
            "run_id": run_id,
            "status": terminal_status,
        },
    )

    assert result["status"] == terminal_status
    assert executed == []


def test_wrong_approval_generation_cannot_enter_recovery_resume() -> None:
    contract, context, _request = _approved_recovery_remaining_remint_fixture()
    executed: list[dict[str, Any]] = []
    coordinator = _nonexecuting_recovery_resume_coordinator(
        claim_pending_approval=lambda *_args, **_kwargs: True,
        executed=executed,
    )

    with pytest.raises(AgentRuntimeError, match="approval_generation_mismatch"):
        coordinator.resume_approved_tool_run(
            run_id=contract.run_id,
            pending={"approval_id": context.approval_id},
            context=context,
            agent={"agent_id": "coder"},
            resumed_detail="Recovery resumed",
            running_result="Recovering",
            expected_approval_id="approval-forged-generation",
            project_completed=lambda *_args: {"status": "completed"},
            project_required=lambda *_args: {"status": "approval_required"},
            project_failed=lambda *_args: {"status": "failed"},
            get_current_run=lambda run_id: {"run_id": run_id, "status": "running"},
        )

    assert executed == []


def test_mutated_approval_fingerprint_cannot_remint_recovery_authority() -> None:
    _contract, context, _request = _approved_recovery_remaining_remint_fixture()
    executed: list[dict[str, Any]] = []
    context.tool_request["input"]["patch"] = "forged patch"
    coordinator = _nonexecuting_recovery_resume_coordinator(
        claim_pending_approval=lambda *_args, **_kwargs: True,
        executed=executed,
    )

    with pytest.raises(
        AgentRuntimeError,
        match="approval_request_fingerprint_mismatch",
    ):
        coordinator.execute_approved_tool(context)

    assert executed == []


@pytest.mark.parametrize(
    ("missing_field", "replacement"),
    [
        ("run_id", ""),
        ("plan_id", ""),
        ("actor", "model"),
        ("execution_authority", "model_tool_call"),
        ("provider", {}),
    ],
)
def test_verifier_repair_rejects_untrusted_source_provenance(
    missing_field: str,
    replacement: Any,
) -> None:
    contract, timeline, followup, requests = _verification_repair_binding_fixture()
    source = timeline[0]
    if missing_field == "provider":
        source["result"] = {
            key: value
            for key, value in source["result"].items()
            if key != RUNTIME_EXECUTION_PROVENANCE_KEY
        }
    else:
        source[missing_field] = replacement

    bound = _loop()._bind_runtime_goal_recovery_lineage(
        requests,
        followup_context=followup,
        contract=contract,
        timeline=timeline,
        run_id=contract.run_id,
    )

    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in bound[0]
    assert "recovery_context_trusted" not in bound[0]


def test_verifier_repair_uses_first_terminal_winner_for_source_call_id() -> None:
    contract, timeline, followup, requests = _verification_repair_binding_fixture()
    conflicting_first = {
        **timeline[0],
        "actor": "model",
        "result": {
            "ok": False,
            "error": "forged first terminal",
        },
    }
    timeline.insert(0, conflicting_first)

    bound = _loop()._bind_runtime_goal_recovery_lineage(
        requests,
        followup_context=followup,
        contract=contract,
        timeline=timeline,
        run_id=contract.run_id,
    )

    assert RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY not in bound[0]
    assert "recovery_context_trusted" not in bound[0]


def test_terminal_recovery_output_cannot_bypass_root_goal_verification() -> None:
    recovery_result = RecoveryActionResult.complete("Recovered")
    loop_result = OutcomeLoopResult(
        disposition=OutcomeLoopDisposition.COMPLETED,
        outcome=ToolOutcome(
            tool_name="demo.apply",
            capabilities=("demo.effect",),
            status=OutcomeStatus.SUCCESS,
            reason="completed",
            retryable=False,
            effects=(),
            verification=VerificationStatus.VERIFIED,
            user_action=None,
            recovery_hints=(),
            provenance={},
            raw={"ok": True, "postcondition_verified": True},
        ),
        recovery_plan=None,
        source_tool_call_id="call-apply-1",
        recovery_action_result=recovery_result,
        terminal_output="Recovered",
    )
    contract = _effect_contract()

    blocked = _loop()._terminal_recovery_output(
        (loop_result,),
        goal_contract=contract,
        timeline=[],
    )
    completed = _loop()._terminal_recovery_output(
        (loop_result,),
        goal_contract=contract,
        timeline=[
            _runtime_owned_terminal_event(contract, {
                "event": "agent.tool.call",
                "run_id": contract.run_id,
                "detail": "demo.apply",
                "tool_call_id": "call-apply-1",
                "step_id": "apply-demo",
                "capability_id": "demo.effect",
                "action_target": {"kind": "demo", "action": "apply"},
                "result": {"ok": True, "postcondition_verified": True},
            })
        ],
    )

    assert blocked == ""
    assert completed == "Recovered"
