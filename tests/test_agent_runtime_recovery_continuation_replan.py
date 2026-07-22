"""Focused tests for recovery-observation continuation into canonical replan."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import replace
from typing import Any

import pytest

from apps.shell.agent.runtime import custom_api_agent as custom_api_agent_module
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.errors import AgentDirectOutcomeUnverified
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_EXECUTION_PROVENANCE_VERSION,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.goal_contract import GoalContract, GoalCriterion
from apps.shell.agent.runtime.outcome_loop import (
    OutcomeLoopDisposition,
    OutcomeLoopResult,
)
from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionRegistry,
    RecoveryActionResult,
    RecoveryToolBatch,
    RecoveryToolResult,
)
from apps.shell.agent.runtime.recovery_adapters import (
    DesktopAppResolutionAdapter,
    WorkspaceFileResolutionAdapter,
)
from apps.shell.agent.runtime.tool_capabilities import capability_ids_for_tool
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus, from_tool_result


def _provider_result(result: dict[str, Any]) -> dict[str, Any]:
    return {
        **result,
        RUNTIME_EXECUTION_PROVENANCE_KEY: {
            "source": RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
            "version": RUNTIME_EXECUTION_PROVENANCE_VERSION,
        },
    }


def _executor_event(
    tool: str,
    tool_call_id: str,
    result: dict[str, Any],
    *,
    run_id: str,
    request_id: str,
    input_preview: dict[str, Any],
    **extra: Any,
) -> dict[str, Any]:
    return {
        "event": "agent.tool.call",
        "detail": tool,
        "tool_call_id": tool_call_id,
        "request_id": request_id,
        "run_id": run_id,
        "actor": "native_runtime",
        "execution_authority": "runtime_tool_executor",
        "visibility": "internal",
        "input_preview": dict(input_preview),
        "result": result,
        **extra,
    }


def _loop() -> RuntimeCustomApiAgentLoop:
    loop = object.__new__(RuntimeCustomApiAgentLoop)
    loop._timeline = lambda event, detail="", **extra: {
        "event": event,
        "detail": detail,
        **extra,
    }
    loop._append_run_event = None
    return loop


class _Budget:
    def __init__(self) -> None:
        self.model_calls = 0

    def claim_model_call(self) -> None:
        self.model_calls += 1

    def claim_tool_call(self, *_args: Any, **_kwargs: Any) -> None:
        return None


class _Projection:
    @staticmethod
    def assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
        return {"role": "assistant", "content": message.get("content", "")}

    @staticmethod
    def artifact_completion(
        _timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
    ) -> None:
        return None

    @staticmethod
    def loop_limit_detail(_timeline: list[dict[str, Any]]) -> str:
        return "test loop limit"


def _append_runtime_result(
    timeline: list[dict[str, Any]],
    request: dict[str, Any],
    result: dict[str, Any],
    *,
    run_id: str,
) -> None:
    custom_api_agent_module.ensure_tool_call_id(request)
    request.setdefault(
        "request_id",
        f"request-{str(request.get('tool_call_id') or '').strip()}",
    )
    metadata = custom_api_agent_module._request_observability_metadata(request)
    for key in (
        "request_id",
        "tool_call_id",
        "source_request_id",
        "source_tool_call_id",
        "plan_id",
        "step_id",
        "planner_step_id",
        "source",
        "recovery_link_kind",
        "recovery_action",
        "recovery_scope_id",
    ):
        value = request.get(key)
        if value not in (None, ""):
            metadata[key] = value
    timeline.append(
        {
            "event": "agent.tool.call",
            "detail": str(request.get("tool") or ""),
            "input_preview": (
                dict(request.get("input"))
                if isinstance(request.get("input"), dict)
                else {}
            ),
            "result": _provider_result(result),
            "run_id": run_id,
            "actor": "native_runtime",
            "execution_authority": "runtime_tool_executor",
            "visibility": "internal",
            **metadata,
        }
    )


def _file_read_goal_contract(*, run_id: str) -> GoalContract:
    return GoalContract(
        contract_id="goal-contract-read-missing-report",
        run_id=run_id,
        original_goal="查看 reports/missing.md",
        intent_kind="file_access",
        criteria=(
            GoalCriterion(
                criterion_id="goal-criterion-read-missing-report",
                description="Read the requested workspace file.",
                effectful=True,
                required_capabilities=("file.workspace_read",),
                expected={
                    "state": "fulfilled",
                    "target": {
                        "kind": "workspace_file",
                        "action": "read",
                        "path": "reports/missing.md",
                    },
                },
                source_step_ids=("read-missing-report",),
            ),
        ),
    )


def _file_recovery_loop(
    *,
    call_model: Any,
    max_tool_iterations: int,
) -> tuple[RuntimeCustomApiAgentLoop, _Budget, list[list[dict[str, Any]]]]:
    budget = _Budget()
    tool_batches: list[list[dict[str, Any]]] = []

    def run_tool_requests(
        tool_requests: list[dict[str, Any]],
        _allowed_tools: list[str],
        _broker: Any,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        _artifacts: list[dict[str, Any]],
        **kwargs: Any,
    ) -> None:
        tool_batches.append([dict(request) for request in tool_requests])
        for request in tool_requests:
            tool = str(request.get("tool") or "")
            if tool == "workspace.read":
                path = str(request.get("input", {}).get("path") or "")
                if path == "reports/final-report.md":
                    result = {
                        "ok": True,
                        "path": path,
                        "content": "The final grounded report.",
                        "postcondition_verified": True,
                    }
                else:
                    result = {
                        "ok": False,
                        "path": path or "reports/missing.md",
                        "error": "路径不存在",
                        "hint": (
                            "请先用 workspace.list 查看父目录，"
                            "确认要读取的文件相对路径。"
                        ),
                    }
            elif tool == "workspace.list":
                result = {
                    "ok": True,
                    "path": "reports",
                    "entries": [
                        {
                            "name": "final-report.md",
                            "path": "reports/final-report.md",
                            "type": "file",
                        }
                    ],
                }
            elif tool == "app.open":
                app_name = str(request.get("input", {}).get("app_name") or "")
                if app_name == "PixelForge Studio":
                    result = {
                        "ok": True,
                        "action": "app.open",
                        "postcondition_verified": True,
                        "data": {
                            "app_name": app_name,
                            "launch_verified": True,
                            "postcondition_verified": True,
                        },
                    }
                else:
                    result = {
                        "ok": False,
                        "action": "app.open",
                        "error": f"No application matched {app_name}",
                        "error_code": "app_not_found",
                        "data": {"app_name": app_name},
                        "permission_error": False,
                        "fallback_used": False,
                    }
            elif tool == "desktop.list_apps":
                result = {
                    "ok": True,
                    "data": {
                        "apps": [
                            {
                                "name": "PixelForge Studio",
                                "bundle_id": "dev.example.pixelforge",
                            }
                        ]
                    },
                }
            elif tool == "desktop.active_window":
                result = {
                    "ok": True,
                    "data": {
                        "active_app_name": "PixelForge Studio",
                        "focus_verified": True,
                    },
                }
            else:
                raise AssertionError(f"unexpected tool: {tool}")
            _append_runtime_result(
                timeline,
                request,
                result,
                run_id=str(kwargs.get("run_id") or ""),
            )
            messages.append(
                {
                    "role": "user",
                    "content": f"Tool result for {tool}: {result}",
                }
            )

    loop = RuntimeCustomApiAgentLoop(
        agent_model_config_private=lambda _agent: {
            "base_url": "https://model.invalid",
            "model": "test-model",
            "api_key": "test-key",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {
                "allowed_tools": [
                    "workspace.read",
                    "workspace.list",
                    "app.open",
                    "desktop.list_apps",
                    "desktop.active_window",
                ]
            }
        },
        run_budget=lambda _run_id, _timeline: budget,
        check_context_budget=lambda _budget, _messages: None,
        tool_schemas=lambda tools: [{"name": tool} for tool in tools],
        normalize_tool_iteration=lambda value: int(value or 0),
        max_tool_iterations=max_tool_iterations,
        operating_doctrine="Use grounded observations.",
        memory_tool_names=set(),
        future_task_tool_names=set(),
        call_model=call_model,
        coalesce_model_message=lambda value: value,
        message_visible_content_text=lambda message: str(
            message.get("content") or ""
        ),
        model_message_metadata=lambda _message: {},
        tool_requests_from_message=lambda message, _content: [
            dict(request)
            for request in message.get("requests", [])
            if isinstance(request, dict)
        ],
        timeline_factory=lambda event, detail="", **extra: {
            "event": event,
            "detail": detail,
            **extra,
        },
        limit_model_output=lambda value: (str(value), False),
        model_output_text_factory=lambda value, **_kwargs: str(value),
        tool_loop_projection=_Projection(),
        run_tool_requests=run_tool_requests,
        error_type=RuntimeError,
        recovery_action_registry=RecoveryActionRegistry(
            (
                WorkspaceFileResolutionAdapter(),
                DesktopAppResolutionAdapter(),
            )
        ),
    )
    return loop, budget, tool_batches


def _continuation_fixture() -> tuple[
    OutcomeLoopResult,
    list[dict[str, Any]],
    str,
]:
    run_id = "run-file-resolution-continuation"
    source_call_id = "call-read-missing-report"
    observation_call_id = "call-list-report-directory"
    source_result = _provider_result(
        {
            "ok": False,
            "path": "reports/missing.md",
            "error": "路径不存在",
            "hint": "请先用 workspace.list 查看父目录，确认要读取的文件相对路径。",
        }
    )
    observation_result = _provider_result(
        {
            "ok": True,
            "path": "reports",
            "entries": [
                {
                    "name": "final-report.md",
                    "path": "reports/final-report.md",
                    "type": "file",
                }
            ],
        }
    )
    source_outcome = from_tool_result(
        "workspace.read",
        source_result,
        capability_ids_for_tool("workspace.read"),
    )
    assert source_outcome.status is OutcomeStatus.FAILED
    plan = RecoveryPlan(
        strategy_id="resolve-file-location",
        action="resolve_file_location",
        recovery_hint="file_resolution_failed",
        required_capabilities=("file.workspace_read",),
        source_status=source_outcome.status,
        source_reason=source_outcome.reason,
        scope_id="scope-file-resolution",
        metadata={
            "goal_contract_id": "goal-contract-read-missing-report",
            "goal_criterion_id": "goal-criterion-read-missing-report",
        },
    )
    observation_request = {
        "protocol": "json_fallback",
        "tool": "workspace.list",
        "tool_call_id": observation_call_id,
        "request_id": "runtime-recovery-request-list-report",
        "input": {"path": "reports"},
        "source": "runtime_internal_recovery",
        "source_tool_call_id": source_call_id,
        "recovery_link_kind": "coordinator_action",
        "recovery_action": plan.action,
        "recovery_scope_id": plan.scope_id,
    }
    batch = RecoveryToolBatch(
        requests=(observation_request,),
        results=(
            RecoveryToolResult(
                tool_call_id=observation_call_id,
                result=observation_result,
                event_type="agent.tool.call",
            ),
        ),
    )
    result = OutcomeLoopResult(
        disposition=OutcomeLoopDisposition.CONTINUE_PLAN,
        outcome=source_outcome,
        recovery_plan=plan,
        source_tool_call_id=source_call_id,
        recovery_action_result=RecoveryActionResult.continue_plan(
            reason="discovery_completed",
            attempts=(batch,),
        ),
        reason="discovery_completed",
    )
    timeline = [
        _executor_event(
            "workspace.read",
            source_call_id,
            source_result,
            run_id=run_id,
            request_id="request-read-missing-report",
            input_preview={"path": "reports/missing.md"},
            source="model_tool_call",
            plan_id="plan-read-report",
            step_id="read-missing-report",
            goal_contract_id="goal-contract-read-missing-report",
            goal_criterion_id="goal-criterion-read-missing-report",
        ),
        _executor_event(
            "workspace.list",
            observation_call_id,
            observation_result,
            run_id=run_id,
            request_id=observation_request["request_id"],
            input_preview=observation_request["input"],
            source="runtime_internal_recovery",
            source_tool_call_id=source_call_id,
            recovery_link_kind="coordinator_action",
            recovery_action=plan.action,
            recovery_scope_id=plan.scope_id,
            plan_id="plan-read-report",
            step_id="read-missing-report",
            goal_contract_id="goal-contract-read-missing-report",
            goal_criterion_id="goal-criterion-read-missing-report",
        ),
    ]
    return result, timeline, run_id


def test_grounded_recovery_continuation_records_one_replan_and_followup() -> None:
    result, timeline, run_id = _continuation_fixture()
    loop = _loop()

    first = loop._record_recovery_continuation_replan_events(
        (result,),
        timeline=timeline,
        run_id=run_id,
    )
    second = loop._record_recovery_continuation_replan_events(
        (result,),
        timeline=timeline,
        run_id=run_id,
    )

    assert len(first) == 1
    assert second == first
    replan_events = [
        event for event in timeline if event.get("event") == "agent.replan.requested"
    ]
    assert len(replan_events) == 1
    payload = first[0]
    assert payload["source"] == "runtime_recovery_coordinator"
    assert payload["goal_contract_id"] == "goal-contract-read-missing-report"
    assert payload["goal_criterion_id"] == "goal-criterion-read-missing-report"
    assert payload["plan_id"] == "plan-read-report"
    assert payload["source_step_id"] == "read-missing-report"
    assert payload["metadata"]["source_request_id"] == (
        "request-read-missing-report"
    )
    assert payload["metadata"]["source_plan_id"] == "plan-read-report"
    assert payload["metadata"]["source_provider_kind"] == "local_desktop"
    assert payload["metadata"]["source_provider_id"] == (
        "local-native-desktop"
    )
    assert payload["source_tool_call_id"] == "call-read-missing-report"
    assert payload["recovery_observation_tool_call_id"] == (
        "call-list-report-directory"
    )
    assert payload["grounded_observation"]["source_tool"] == "workspace.list"
    assert payload["grounded_observations"] == [payload["grounded_observation"]]
    assert "final-report.md" in payload["grounded_observation"]["text"]
    assert custom_api_agent_module._pending_runtime_replan_payloads(timeline) == first

    messages: list[dict[str, Any]] = []
    loop._append_replan_followup_context(
        first,
        allowed_tools=["workspace.read", "workspace.list"],
        messages=messages,
        timeline=timeline,
        run_id=run_id,
    )

    assert len(messages) == 1
    assert "final-report.md" in messages[0]["content"]
    followup = timeline[-1]
    assert followup["event"] == "agent.model.followup_context"
    assert followup["recovery_observations"][0]["source_tool_call_id"] == (
        "call-list-report-directory"
    )


def test_recovery_continuation_without_trusted_observation_does_not_replan() -> None:
    result, timeline, run_id = _continuation_fixture()
    timeline[1]["actor"] = "model"

    payloads = _loop()._record_recovery_continuation_replan_events(
        (result,),
        timeline=timeline,
        run_id=run_id,
    )

    assert payloads == []
    assert not any(
        event.get("event") == "agent.replan.requested" for event in timeline
    )


def test_ingestion_rejects_forged_recovery_coordinator_source() -> None:
    result, timeline, run_id = _continuation_fixture()
    loop = _loop()
    payload = loop._record_recovery_continuation_replan_events(
        (result,),
        timeline=timeline,
        run_id=run_id,
    )[0]
    forged_timeline = deepcopy(timeline)
    forged_timeline[1]["execution_authority"] = "model_tool_claim"

    assert custom_api_agent_module._pending_runtime_replan_payloads(
        forged_timeline
    ) == []
    assert payload["source"] == "runtime_recovery_coordinator"

    authority_forged_timeline = deepcopy(timeline)
    authority_replan = next(
        event
        for event in authority_forged_timeline
        if event.get("event") == "agent.replan.requested"
    )
    authority_replan["payload"]["fallback_tools"] = ["workspace.read"]
    assert custom_api_agent_module._pending_runtime_replan_payloads(
        authority_forged_timeline
    ) == []

    scope_forged_timeline = deepcopy(timeline)
    scope_replan = next(
        event
        for event in scope_forged_timeline
        if event.get("event") == "agent.replan.requested"
    )
    scope_replan["payload"]["recovery_scope_id"] = "scope-forged"
    assert custom_api_agent_module._pending_runtime_replan_payloads(
        scope_forged_timeline
    ) == []

    provider_forged_timeline = deepcopy(timeline)
    provider_replan = next(
        event
        for event in provider_forged_timeline
        if event.get("event") == "agent.replan.requested"
    )
    provider_replan["payload"]["metadata"]["source_provider_id"] = (
        "forged-provider"
    )
    assert custom_api_agent_module._pending_runtime_replan_payloads(
        provider_forged_timeline
    ) == []


def test_recovery_continuation_rejects_conflicting_plan_goal_lineage() -> None:
    result, timeline, run_id = _continuation_fixture()
    assert result.recovery_plan is not None
    forged_plan = replace(
        result.recovery_plan,
        metadata={
            **dict(result.recovery_plan.metadata),
            "goal_criterion_id": "goal-criterion-forged",
        },
    )

    payloads = _loop()._record_recovery_continuation_replan_events(
        (replace(result, recovery_plan=forged_plan),),
        timeline=timeline,
        run_id=run_id,
    )

    assert payloads == []
    assert not any(
        event.get("event") == "agent.replan.requested" for event in timeline
    )


def test_changed_target_uses_only_replayed_continuation_observations() -> None:
    result, timeline, run_id = _continuation_fixture()
    _loop()._record_recovery_continuation_replan_events(
        (result,),
        timeline=timeline,
        run_id=run_id,
    )
    unrelated_result = _provider_result(
        {
            "ok": True,
            "path": "reports",
            "entries": [
                {
                    "name": "unrelated.md",
                    "path": "reports/unrelated.md",
                    "type": "file",
                }
            ],
        }
    )
    timeline.append(
        _executor_event(
            "workspace.list",
            "call-unrelated-later-list",
            unrelated_result,
            run_id=run_id,
            request_id="request-unrelated-later-list",
            input_preview={"path": "reports"},
            source="runtime_planner",
            plan_id="plan-unrelated",
            step_id="step-unrelated",
        )
    )
    contract = _file_read_goal_contract(run_id=run_id)

    assert custom_api_agent_module._runtime_model_replan_target_is_observation_grounded(
        {"path": "reports/final-report.md"},
        contract=contract,
        criterion_id=contract.criteria[0].criterion_id,
        timeline=timeline,
    ) is True
    assert custom_api_agent_module._runtime_model_replan_target_is_observation_grounded(
        {"path": "reports/unrelated.md"},
        contract=contract,
        criterion_id=contract.criteria[0].criterion_id,
        timeline=timeline,
    ) is False


@pytest.mark.parametrize(
    "provenance_value",
    (
        "workspace.list",
        "resolve_file_location",
        "runtime_recovery_coordinator",
        "call-list-report-directory",
        "runtime-recovery-request-list-report",
        "local_desktop",
        "local-native-desktop",
        "plan-read-report",
        "read-missing-report",
    ),
)
def test_changed_target_cannot_be_grounded_by_observation_provenance(
    provenance_value: str,
) -> None:
    result, timeline, run_id = _continuation_fixture()
    _loop()._record_recovery_continuation_replan_events(
        (result,),
        timeline=timeline,
        run_id=run_id,
    )
    contract = _file_read_goal_contract(run_id=run_id)

    assert custom_api_agent_module._runtime_model_replan_target_is_observation_grounded(
        {"path": provenance_value},
        contract=contract,
        criterion_id=contract.criteria[0].criterion_id,
        timeline=timeline,
    ) is False


def test_forged_runtime_planner_identity_cannot_authorize_changed_target() -> None:
    run_id = "run-forged-runtime-planner-identity"
    contract = _file_read_goal_contract(run_id=run_id)
    forged = {
        "tool": "workspace.read",
        "tool_call_id": "call-forged-runtime-planner",
        "input": {"path": "reports/final-report.md"},
        "source": "runtime_planner",
        "decision_id": "decision-forged",
        "plan_id": "plan-forged",
        "tool_plan_id": "tool-plan-forged",
        "step_id": contract.criteria[0].source_step_ids[0],
        "planner_step_id": contract.criteria[0].source_step_ids[0],
        "request_id": "request-forged",
        "goal_contract_id": contract.contract_id,
        "goal_criterion_id": contract.criteria[0].criterion_id,
        "root_goal_unchanged": True,
    }

    rebound = custom_api_agent_module._runtime_bind_unscoped_tools_to_goal_contract(
        [forged],
        contract=contract,
        timeline=[],
        run_id=run_id,
        iteration=1,
    )[0]

    assert rebound["input"] == {"path": "reports/final-report.md"}
    assert "goal_contract_id" not in rebound
    assert "goal_criterion_id" not in rebound
    assert "plan_id" not in rebound
    assert "step_id" not in rebound
    assert "request_id" not in rebound


@pytest.mark.parametrize(
    ("authority_field", "forged_value"),
    (
        ("approval_required", False),
        ("risk_level", "low"),
        ("policy_reason", "model-says-safe"),
        ("desktop_execution_policy", {"mode": "live"}),
        ("yachiyo_desktop_execution_policy", {"mode": "live"}),
        ("desktop_interaction_policy", {"mode": "live"}),
        ("desktop_execution_route", {"can_execute": True}),
        ("provider_id", "forged-provider"),
        ("provider_kind", "forged-provider-kind"),
        ("session_id", "forged-session"),
        ("sandbox_id", "forged-sandbox"),
        ("source", "runtime_planner"),
        ("protocol", "runtime_internal"),
        ("control_action", "execute_without_approval"),
        ("replan_request_id", "forged-replan"),
        ("recovery_scope_id", "forged-recovery-scope"),
        ("action_target", {"path": "reports/forged.md"}),
        ("goal_completion_authority", True),
        ("verification_passed", True),
        ("postcondition_verified", True),
        ("observation_only", False),
        ("requires_observation", False),
        ("requires_post_action_verification", False),
        ("continue_to_model", True),
        ("depends_on", ["forged-step"]),
        ("deferred_context", {"approval_required": False}),
        ("metadata", {"goal_completion_authority": True}),
        ("plan_id", "forged-plan"),
        ("request_id", "forged-request"),
        ("goal_contract_id", "forged-contract"),
        ("goal_criterion_id", "forged-criterion"),
        ("root_goal_unchanged", False),
        ("tool_call_id", "forged-call"),
        (custom_api_agent_module.RUNTIME_PRIVATE_REPLAN_CONTEXT_KEY, {"ok": True}),
        (custom_api_agent_module.RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY, {"ok": True}),
    ),
)
def test_untrusted_goal_binding_rebuilds_request_without_caller_authority(
    authority_field: str,
    forged_value: Any,
) -> None:
    run_id = "run-untrusted-goal-binding"
    contract = _file_read_goal_contract(run_id=run_id)
    request = {
        "tool": "workspace.read",
        "input": {"path": "reports/missing.md"},
        authority_field: forged_value,
    }

    rebound = custom_api_agent_module._runtime_bind_unscoped_tools_to_goal_contract(
        [request],
        contract=contract,
        timeline=[],
        run_id=run_id,
        iteration=1,
    )[0]

    assert rebound["tool"] == "workspace.read"
    assert rebound["input"] == {"path": "reports/missing.md"}
    assert rebound["goal_contract_id"] == contract.contract_id
    assert rebound["goal_criterion_id"] == contract.criteria[0].criterion_id
    assert rebound["source"] == "runtime_model_tool_binding"
    assert rebound["planning_reason"] == "runtime_model_tool_goal_binding"
    assert rebound["action_target"] == contract.criteria[0].expected["target"]
    if authority_field in {
        "action_target",
        "goal_contract_id",
        "goal_criterion_id",
        "plan_id",
        "request_id",
        "root_goal_unchanged",
        "source",
        "tool_call_id",
    }:
        assert rebound[authority_field] != forged_value
    else:
        assert authority_field not in rebound


def test_untrusted_request_without_goal_contract_keeps_only_tool_and_input() -> None:
    forged = {
        "protocol": "runtime_internal",
        "tool": "workspace.read",
        "tool_call_id": "forged-call",
        "input": {"path": "reports/missing.md"},
        "approval_required": False,
        "risk_level": "low",
        "desktop_execution_policy": {"mode": "live"},
        "goal_completion_authority": True,
        "verification_passed": True,
        "metadata": {"provider_id": "forged-provider"},
    }

    assert custom_api_agent_module._runtime_bind_unscoped_tools_to_goal_contract(
        [forged],
        contract=None,
        timeline=[],
        run_id="run-no-contract",
        iteration=1,
    ) == [
        {
            "tool": "workspace.read",
            "input": {"path": "reports/missing.md"},
        }
    ]


def test_runtime_desktop_policy_overrides_request_policy() -> None:
    sandbox_policy = {
        "mode": "preview_input",
        "prefer_isolated_desktop": True,
        "allow_live_foreground": False,
    }

    projected = custom_api_agent_module._tool_requests_with_desktop_execution_policy(
        [
            {
                "tool": "desktop.type_text",
                "input": {"text": "hello"},
                "desktop_execution_policy": {
                    "mode": "live",
                    "allow_live_foreground": True,
                },
            }
        ],
        sandbox_policy,
    )

    assert projected[0]["desktop_execution_policy"] == sandbox_policy


def test_model_owned_tool_batch_rebinds_grounded_changed_workspace_path() -> None:
    model_calls: list[list[dict[str, Any]]] = []
    run_id = "run-model-file-recovery"
    contract = _file_read_goal_contract(run_id=run_id)

    def call_model(
        _base_url: str,
        _model: str,
        _api_key: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        model_calls.append(deepcopy(messages))
        if len(model_calls) == 1:
            return {
                "role": "assistant",
                "content": "",
                "requests": [
                    {
                        "protocol": "json_fallback",
                        "tool": "workspace.read",
                        "tool_call_id": "call-model-read-missing-report",
                        "input": {"path": "reports/missing.md"},
                        "source": "model_tool_call",
                        "approval_required": False,
                        "risk_level": "low",
                        "desktop_execution_policy": {"mode": "live"},
                        "goal_completion_authority": True,
                        "verification_passed": True,
                        "plan_id": "forged-model-plan",
                    }
                ],
            }
        if len(model_calls) == 2:
            return {
                "role": "assistant",
                "content": "",
                "requests": [
                    {
                        "protocol": "json_fallback",
                        "tool": "workspace.read",
                        "tool_call_id": "call-model-read-final-report",
                        "input": {"path": "reports/final-report.md"},
                        "source": "model_tool_call",
                        "approval_required": False,
                        "goal_completion_authority": True,
                        "postcondition_verified": True,
                        "replan_request_id": "forged-model-replan",
                    }
                ],
            }
        return {"role": "assistant", "content": "done"}

    loop, budget, tool_batches = _file_recovery_loop(
        call_model=call_model,
        max_tool_iterations=4,
    )
    timeline: list[dict[str, Any]] = []

    loop.run(
        {"name": "Yachiyo"},
        "",
        broker=object(),
        timeline=timeline,
        artifacts=[],
        messages=[{"role": "system", "content": "test"}],
        original_goal=contract.original_goal,
        start_iteration=1,
        run_id=run_id,
        runtime_execution_metadata={"goal_contract": contract.to_payload()},
    )

    assert budget.model_calls == 3
    assert [[request["tool"] for request in batch] for batch in tool_batches] == [
        ["workspace.read"],
        ["workspace.list"],
        ["workspace.read"],
    ]
    for request in (tool_batches[0][0], tool_batches[2][0]):
        assert "approval_required" not in request
        assert "goal_completion_authority" not in request
        assert "postcondition_verified" not in request
        assert "verification_passed" not in request
        assert request.get("desktop_execution_policy") != {"mode": "live"}
    assert tool_batches[0][0]["plan_id"] != "forged-model-plan"
    assert "final-report.md" in model_calls[1][-1]["content"]
    rebound = tool_batches[2][0]
    assert rebound["input"] == {"path": "reports/final-report.md"}
    assert rebound["goal_contract_id"] == contract.contract_id
    assert rebound["goal_criterion_id"] == contract.criteria[0].criterion_id
    assert rebound["step_id"] == contract.criteria[0].source_step_ids[0]
    assert rebound["planner_step_id"] == contract.criteria[0].source_step_ids[0]
    assert rebound["root_goal_unchanged"] is True
    assert rebound["replan_request_id"].startswith(
        "runtime-recovery-continuation-"
    )
    assert rebound["replan_request_id"] != "forged-model-replan"
    replan_events = [
        event
        for event in timeline
        if event.get("event") == "agent.replan.requested"
        and event.get("payload", {}).get("source")
        == "runtime_recovery_coordinator"
    ]
    assert len(replan_events) == 1
    assert replan_events[0]["payload"]["source_tool_call_id"] == (
        "call-model-read-missing-report"
    )


def test_direct_runtime_plan_rebinds_grounded_changed_app_name() -> None:
    model_calls: list[list[dict[str, Any]]] = []

    def call_model(
        _base_url: str,
        _model: str,
        _api_key: str,
        messages: list[dict[str, Any]],
        **_kwargs: Any,
    ) -> dict[str, Any]:
        model_calls.append(deepcopy(messages))
        if len(model_calls) == 1:
            return {
                "role": "assistant",
                "content": "",
                "requests": [
                    {
                        "protocol": "json_fallback",
                        "tool": "app.open",
                        "tool_call_id": "call-model-open-pixelforge-studio",
                        "input": {"app_name": "PixelForge Studio"},
                        "source": "model_tool_call",
                    }
                ],
            }
        return {"role": "assistant", "content": "done"}

    loop, budget, tool_batches = _file_recovery_loop(
        call_model=call_model,
        max_tool_iterations=3,
    )
    timeline: list[dict[str, Any]] = []
    direct_request = {
        "protocol": "json_fallback",
        "tool": "app.open",
        "tool_call_id": "call-direct-open-pixelforge",
        "input": {"app_name": "PixelForge"},
        "source": "daily_desktop_intent",
        "planning_reason": "explicit_full_plan",
    }

    with pytest.raises(RuntimeError, match="工具循环超过上限"):
        loop.run(
            {"name": "Yachiyo"},
            "打开 PixelForge。",
            broker=object(),
            timeline=timeline,
            artifacts=[],
            direct_tool_requests=[direct_request],
            run_id="run-direct-file-recovery",
        )

    assert budget.model_calls == 3
    assert [[request["tool"] for request in batch] for batch in tool_batches] == [
        ["desktop.list_apps", "app.open", "desktop.active_window"],
        ["desktop.list_apps"],
        ["app.open", "desktop.active_window"],
    ]
    assert any(
        "PixelForge Studio" in str(message.get("content") or "")
        for call_messages in model_calls
        for message in call_messages
    )
    rebound = tool_batches[2][0]
    assert rebound["input"] == {"app_name": "PixelForge Studio"}
    assert rebound["goal_contract_id"]
    assert rebound["goal_criterion_id"]
    assert rebound["step_id"] == "open-or-focus-app"
    assert rebound["planner_step_id"] == "open-or-focus-app"
    assert rebound["root_goal_unchanged"] is True
    verifier = tool_batches[2][1]
    assert verifier["tool"] == "desktop.active_window"
    assert verifier["source"] == "runtime_verification"
    assert any(
        event.get("event") == "agent.model.followup_context"
        and event.get("recovery_observations", [{}])[0].get("source_tool")
        == "desktop.list_apps"
        for event in timeline
    )
    continuation_replans = [
        event
        for event in timeline
        if event.get("event") == "agent.replan.requested"
        and event.get("payload", {}).get("source")
        == "runtime_recovery_coordinator"
    ]
    assert len(continuation_replans) == 1


def test_continuation_does_not_mask_an_independent_terminal_failure() -> None:
    continuation, _timeline, _run_id = _continuation_fixture()
    failed_outcome = from_tool_result(
        "app.open",
        _provider_result(
            {
                "ok": False,
                "error": "policy blocked",
                "retryable": False,
            }
        ),
        capability_ids_for_tool("app.open"),
    )
    failed = OutcomeLoopResult(
        disposition=OutcomeLoopDisposition.FAILED,
        outcome=failed_outcome,
        recovery_plan=None,
        source_tool_call_id="call-policy-blocked",
        reason="policy_blocked",
    )
    loop = _loop()

    assert loop._terminal_recovery_output((continuation, failed)) == ""
    assert loop._outcome_results_require_model_turn((continuation, failed)) is True
    with pytest.raises(AgentDirectOutcomeUnverified):
        loop._raise_terminal_outcome_blocker(
            (continuation, failed),
            (
                {
                    "tool": "app.open",
                    "tool_call_id": "call-policy-blocked",
                    "input": {"app_name": "Blocked App"},
                },
            ),
        )
