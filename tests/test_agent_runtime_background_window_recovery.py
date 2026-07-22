"""Focused policy and adapter tests for owned Cua background-window recovery."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from apps.shell.agent.runtime.cua_background_provider import CUA_BACKGROUND_PROVIDER_KIND
from apps.shell.agent.runtime.recovery_actions import (
    RecoveryActionContext,
    RecoveryActionDisposition,
    RecoveryActionRegistry,
    RecoveryActionScope,
    RecoveryToolBatch,
    RecoveryToolResult,
)
from apps.shell.agent.runtime.recovery_adapters import BackgroundWindowRecoveryAdapter
from apps.shell.agent.runtime.recovery_policies import assess_latest_tool_recovery
from apps.shell.agent.tools.policy import TOOL_DESCRIPTORS

_SOURCE_PID = 731011
_ALLOWED_TOOLS = ("app.open", "desktop.safe_shortcut", "desktop.read_ui")


def _transport() -> dict[str, Any]:
    return {
        "provider_kind": CUA_BACKGROUND_PROVIDER_KIND,
        "delivery_mode": "background",
        "foreground_takeover_required": False,
        "mcp_tool": "launch_app",
        "transport": "electron_bridge",
    }


def _source_result(**overrides: Any) -> dict[str, Any]:
    result = {
        "ok": False,
        "action": "app.open",
        "error": "cua_background_window_not_ready",
        "retryable": True,
        "agent_owned_target": True,
        "pid": _SOURCE_PID,
        "self_activation_suppressed": True,
        "desktop_execution_provider_transport": _transport(),
    }
    result.update(overrides)
    return result


def _assessment(
    result: Mapping[str, Any] | None = None,
    *,
    allowed_tools: Sequence[str] = _ALLOWED_TOOLS,
    lineage: Sequence[Any] = (),
):
    return assess_latest_tool_recovery(
        (
            {
                "event": "agent.tool.failed",
                "tool": "app.open",
                "tool_call_id": "open-owned-app",
                "result": dict(result or _source_result()),
            },
        ),
        start_index=0,
        allowed_tools=allowed_tools,
        attempt_lineage=lineage,
    )


def _context(
    runtime: Any,
    *,
    assessment: Any | None = None,
    iteration: int = 1,
) -> RecoveryActionContext:
    assessment = assessment or _assessment()
    assert assessment is not None and assessment.plan is not None
    return RecoveryActionContext(
        plan=assessment.plan,
        source_outcome=assessment.outcome,
        source_tool_call_id=assessment.tool_call_id,
        scope=RecoveryActionScope(
            allowed_tools=frozenset(_ALLOWED_TOOLS),
            iteration=iteration,
        ),
        runtime=runtime,
    )


class _Runtime:
    def __init__(self, results: Sequence[RecoveryToolResult]) -> None:
        self.results = tuple(results)
        self.calls: list[tuple[tuple[Mapping[str, Any], ...], tuple[str, ...], int]] = []

    def execute_tools(
        self,
        tool_requests: Sequence[Mapping[str, Any]],
        *,
        allowed_tools: Sequence[str],
        next_iteration: int,
    ) -> RecoveryToolBatch:
        requests = tuple(tool_requests)
        self.calls.append((requests, tuple(allowed_tools), next_iteration))
        return RecoveryToolBatch(requests=requests, results=self.results)


def _success_results(context: RecoveryActionContext) -> tuple[RecoveryToolResult, ...]:
    identity = context.plan.scope_id
    # IDs are deterministic from this exact recovery lineage; take them from a
    # dry expected request shape by matching the adapter's documented prefixes.
    import hashlib

    digest = hashlib.sha256(
        f"{identity}\0{context.source_tool_call_id}".encode("utf-8")
    ).hexdigest()[:16]
    shortcut_id = f"background-window-shortcut-{context.scope.iteration}-{digest}"
    inspect_id = f"background-window-observe-{context.scope.iteration}-{digest}"
    return (
        RecoveryToolResult(
            tool_call_id=shortcut_id,
            result={
                "ok": True,
                "action_dispatched": True,
                "delivery_dispatched": True,
                "delivery_verified": False,
                "window_materialization_pending": True,
                "postcondition_verified": False,
                "requires_postcondition_verification": True,
                "desktop_execution_provider_transport": _transport(),
            },
        ),
        RecoveryToolResult(
            tool_call_id=inspect_id,
            result={
                "ok": True,
                "data": {
                    "pid": _SOURCE_PID,
                    "window_id": 1911,
                    "agent_owned_target": True,
                    "target_bound": True,
                },
                "desktop_execution_provider_transport": _transport(),
            },
        ),
    )


def test_policy_recognizes_only_exact_owned_background_window_failure() -> None:
    assessment = _assessment()

    assert assessment is not None and assessment.plan is not None
    assert assessment.plan.action == "materialize_background_window"
    assert assessment.plan.recovery_hint == "materialize_background_window"
    assert assessment.plan.required_capabilities == (
        "desktop.ui_operation",
        "desktop.app_discovery",
    )


def test_policy_rejects_background_window_false_positives() -> None:
    variants = (
        {"self_activation_suppressed": False},
        {"agent_owned_target": False},
        {"pid": 0},
        {"error": "cua_mcp_transport_failed"},
        {"desktop_execution_provider_transport": {**_transport(), "delivery_mode": "foreground"}},
        {"desktop_execution_provider_transport": {**_transport(), "foreground_takeover_required": True}},
    )

    for override in variants:
        assessment = _assessment(_source_result(**override))
        assert assessment is not None
        assert assessment.plan is None


def test_policy_exact_owned_failure_mints_fixed_private_recovery_grant() -> None:
    assessment = _assessment(allowed_tools=("app.open", "desktop.safe_shortcut"))

    assert assessment is not None and assessment.plan is not None
    assert assessment.plan.action == "materialize_background_window"


def test_adapter_runs_one_background_only_batch_and_continues_on_same_pid_window() -> None:
    bootstrap = _Runtime(())
    context = _context(bootstrap)
    runtime = _Runtime(_success_results(context))
    context = _context(runtime)

    result = RecoveryActionRegistry((BackgroundWindowRecoveryAdapter(),)).execute(context)

    assert result.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    assert len(runtime.calls) == 1
    requests, allowed_tools, iteration = runtime.calls[0]
    assert allowed_tools == ("desktop.safe_shortcut", "desktop.read_ui")
    assert iteration == 2
    assert [request["tool"] for request in requests] == [
        "desktop.safe_shortcut",
        "desktop.read_ui",
    ]
    assert requests[0]["input"] == {"action": "new_document"}
    assert requests[1]["input"] == {}
    for request in requests:
        TOOL_DESCRIPTORS[request["tool"]].validate_payload(dict(request["input"]))


def test_adapter_fails_when_shortcut_fails() -> None:
    bootstrap = _Runtime(())
    context = _context(bootstrap)
    results = list(_success_results(context))
    results[0] = RecoveryToolResult(
        tool_call_id=results[0].tool_call_id,
        result={"ok": False, "error": "shortcut_failed"},
        event_type="agent.tool.failed",
    )
    result = RecoveryActionRegistry((BackgroundWindowRecoveryAdapter(),)).execute(
        _context(_Runtime(results))
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "background_window_shortcut_failed"


def test_adapter_fails_when_observation_does_not_match_owned_pid() -> None:
    bootstrap = _Runtime(())
    context = _context(bootstrap)
    results = list(_success_results(context))
    observed = dict(results[1].result)
    observed["data"] = {**observed["data"], "pid": _SOURCE_PID + 1}
    results[1] = RecoveryToolResult(tool_call_id=results[1].tool_call_id, result=observed)
    result = RecoveryActionRegistry((BackgroundWindowRecoveryAdapter(),)).execute(
        _context(_Runtime(results))
    )

    assert result.disposition is RecoveryActionDisposition.EXECUTION_FAILED
    assert result.reason == "background_window_observation_mismatch"


def test_policy_limits_background_window_recovery_to_one_lineage_attempt() -> None:
    first = _assessment()
    assert first is not None and first.plan is not None

    second = _assessment(lineage=(first.plan,))

    assert second is not None
    assert second.plan is None


def test_adapter_reconciles_a_completed_batch_from_an_earlier_iteration() -> None:
    earlier_context = _context(_Runtime(()), iteration=1)
    earlier_results = _success_results(earlier_context)
    earlier_runtime = _Runtime(earlier_results)
    execution = BackgroundWindowRecoveryAdapter().execute(
        _context(earlier_runtime, iteration=1)
    )
    assert execution.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    earlier_batch = RecoveryToolBatch(
        requests=earlier_runtime.calls[0][0],
        results=earlier_results,
    )

    result = BackgroundWindowRecoveryAdapter().reconcile_completed_attempt(
        _context(_Runtime(()), iteration=4),
        earlier_batch,
    )

    assert result.disposition is RecoveryActionDisposition.CONTINUE_PLAN
    assert result.reason == "background_window_materialized"
    assert result.attempts == (earlier_batch,)


def test_adapter_rejects_mismatched_or_forged_completed_batches() -> None:
    earlier_context = _context(_Runtime(()), iteration=1)
    earlier_results = _success_results(earlier_context)
    earlier_runtime = _Runtime(earlier_results)
    BackgroundWindowRecoveryAdapter().execute(
        _context(earlier_runtime, iteration=1)
    )
    shape_mismatch = [dict(request) for request in earlier_runtime.calls[0][0]]
    shape_mismatch[0]["input"] = {"action": "close_window"}
    forged_identity = [dict(request) for request in earlier_runtime.calls[0][0]]
    forged_call_id = "background-window-shortcut-1-forged00000000000"
    forged_identity[0]["tool_call_id"] = forged_call_id
    missing_identity = [dict(request) for request in earlier_runtime.calls[0][0]]
    missing_identity[0].pop("recovery_scope_id")
    mismatched_identity = [dict(request) for request in earlier_runtime.calls[0][0]]
    mismatched_identity[1]["source_tool_call_id"] = "another-source-call"
    forged_results = (
        RecoveryToolResult(
            tool_call_id=forged_call_id,
            result=earlier_results[0].result,
        ),
        earlier_results[1],
    )
    mismatched_batches = (
        RecoveryToolBatch(
            requests=tuple(shape_mismatch),
            results=earlier_results,
        ),
        RecoveryToolBatch(
            requests=tuple(forged_identity),
            results=forged_results,
        ),
        RecoveryToolBatch(
            requests=tuple(missing_identity),
            results=earlier_results,
        ),
        RecoveryToolBatch(
            requests=tuple(mismatched_identity),
            results=earlier_results,
        ),
    )

    for batch in mismatched_batches:
        result = BackgroundWindowRecoveryAdapter().reconcile_completed_attempt(
            _context(_Runtime(()), iteration=4),
            batch,
        )

        assert result.disposition is RecoveryActionDisposition.NOT_HANDLED
        assert result.reason == "background_window_attempt_uncorrelated"
