from __future__ import annotations

import pytest

from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.recovery_ownership import (
    RecoveryOwnershipStatus,
    resolve_legacy_replan_ownership,
)
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus


def _plan() -> RecoveryPlan:
    return RecoveryPlan(
        strategy_id="resolve-file-location",
        action="resolve_file_location",
        recovery_hint="file_resolution_failed",
        required_capabilities=("file.workspace_read",),
        source_status=OutcomeStatus.FAILED,
        source_reason="path_not_found",
        scope_id="scope-1",
    )


def _app_plan() -> RecoveryPlan:
    return RecoveryPlan(
        strategy_id="resolve-app-identity",
        action="resolve_app_identity",
        recovery_hint="app_resolution_failed",
        required_capabilities=("desktop.app_discovery",),
        source_status=OutcomeStatus.FAILED,
        source_reason="app_not_found",
        scope_id="scope-app",
    )


def _request_event(
    *,
    tool_call_id: str = "source-1",
    tool_name: str = "workspace.read",
) -> dict[str, object]:
    return {
        "event": "agent.replan.requested",
        "payload": {
            "request_id": "runtime-replan:file",
            "source": "runtime_tool_request_runner",
            "source_tool_call_id": tool_call_id,
            "source_tool_name": tool_name,
            "recovery_actions": [
                {
                    "label": "List workspace directory",
                    "tool": "workspace.list",
                    "input": {"path": "."},
                }
            ],
        },
    }


def test_exact_unstarted_replan_is_claimable_with_stable_action_id() -> None:
    decision = resolve_legacy_replan_ownership(
        [_request_event()],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.CLAIMABLE
    assert decision.coordinator_may_execute is True
    assert decision.request_id == "runtime-replan:file"
    assert decision.action_id == "runtime-replan:file:action:1:workspace.list"
    assert decision.event_fields() == {
        "replan_request_id": "runtime-replan:file",
        "replan_recovery_action_id": "runtime-replan:file:action:1:workspace.list",
    }


@pytest.mark.parametrize(
    "progress_event",
    [
        {
            "event": "agent.tool.call",
            "replan_request_id": "runtime-replan:file",
            "detail": "workspace.list",
        },
        {
            "event": "agent.deferred_continuation.enqueued",
            "payload": {"replan_request_id": "runtime-replan:file"},
        },
        {
            "event": "agent.replan.recovery.updated",
            "payload": {"request_id": "runtime-replan:file"},
        },
        {
            "event": "agent.recovery.planned",
            "payload": {
                "recovery_owner": "coordinator",
                "replan_request_id": "runtime-replan:file",
            },
        },
    ],
    ids=("tool-call", "deferred", "updated", "coordinator-claim"),
)
def test_started_replan_cannot_be_claimed_again(progress_event: dict[str, object]) -> None:
    decision = resolve_legacy_replan_ownership(
        [_request_event(), progress_event],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.ALREADY_HANDLED
    assert decision.coordinator_may_execute is False


def test_unrelated_or_legacy_uncorrelated_replan_does_not_block_coordinator() -> None:
    wrong_source = resolve_legacy_replan_ownership(
        [_request_event(tool_call_id="other-source")],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )
    uncorrelated_legacy = _request_event()
    del uncorrelated_legacy["payload"]["source_tool_call_id"]  # type: ignore[index]
    old_shape = resolve_legacy_replan_ownership(
        [uncorrelated_legacy],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert wrong_source.status is RecoveryOwnershipStatus.UNRELATED
    assert wrong_source.coordinator_may_execute is True
    assert old_shape.status is RecoveryOwnershipStatus.UNRELATED
    assert old_shape.coordinator_may_execute is True


def test_ambiguous_capability_actions_fail_closed_without_consuming_request() -> None:
    event = _request_event()
    event["payload"]["recovery_actions"].append(  # type: ignore[index,union-attr]
        {"tool": "file.search", "input": {"path": "."}}
    )

    decision = resolve_legacy_replan_ownership(
        [event],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.CONFLICT
    assert decision.coordinator_may_execute is False
    assert decision.action_id == ""
    assert decision.event_fields() == {}


def test_duplicate_matching_actions_with_same_explicit_id_are_conflict() -> None:
    event = _request_event()
    actions = event["payload"]["recovery_actions"]  # type: ignore[index]
    actions[0]["action_id"] = "same-action"  # type: ignore[index]
    actions.append(  # type: ignore[union-attr]
        {
            "action_id": "same-action",
            "tool": "workspace.list",
            "input": {"path": "."},
        }
    )

    decision = resolve_legacy_replan_ownership(
        [event],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.CONFLICT
    assert decision.coordinator_may_execute is False


def _app_request_event(
    source_tool: str,
    actions: list[dict[str, object]],
) -> dict[str, object]:
    return {
        "event": "agent.replan.requested",
        "payload": {
            "request_id": f"runtime-replan:{source_tool}",
            "source": "runtime_tool_request_runner",
            "source_tool_call_id": "app-source-1",
            "source_tool_name": source_tool,
            "input_preview": {"app_name": "Missing Writer"},
            "recovery_actions": actions,
        },
    }


@pytest.mark.parametrize("source_tool", ["app.focus", "desktop.focus_app"])
def test_real_focus_not_found_foreground_chain_is_claimed_at_request_level(
    source_tool: str,
) -> None:
    event = _app_request_event(
        source_tool,
        [
            {"tool": "desktop.running_apps", "input": {}, "risk_level": "low"},
            {
                "tool": "app.open",
                "input": {"app_name": "Missing Writer"},
                "risk_level": "low",
            },
            {"tool": "desktop.active_window", "input": {}, "risk_level": "low"},
            {
                "tool": "screen.capture",
                "input": {"reason": "recover failed desktop tool"},
                "risk_level": "low",
            },
        ],
    )

    decision = resolve_legacy_replan_ownership(
        [event],
        source_tool_call_id="app-source-1",
        source_tool_name=source_tool,
        plan=_app_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.CLAIMABLE
    assert decision.action_id == ""
    assert decision.event_fields() == {
        "replan_request_id": f"runtime-replan:{source_tool}"
    }


@pytest.mark.parametrize("source_tool", ["app.open", "desktop.open_app"])
def test_real_app_open_not_found_foreground_chain_is_claimed_at_request_level(
    source_tool: str,
) -> None:
    event = _app_request_event(
        source_tool,
        [
            {
                "tool": "desktop.open_path",
                "input": {"path": "/Applications"},
                "permission_target": "app_not_found",
                "risk_level": "low",
            },
            {
                "tool": "app.open",
                "input": {"app_name": "App Store"},
                "permission_target": "app_not_found",
                "risk_level": "low",
            },
        ],
    )

    decision = resolve_legacy_replan_ownership(
        [event],
        source_tool_call_id="app-source-1",
        source_tool_name=source_tool,
        plan=_app_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.CLAIMABLE
    assert decision.action_id == ""
    assert decision.event_fields() == {
        "replan_request_id": f"runtime-replan:{source_tool}"
    }


def test_normalized_app_discovery_action_is_claimable_without_broad_conflict() -> None:
    event = _app_request_event(
        "app.open",
        [
            {
                "tool": "desktop.list_apps",
                "input": {"query": "Missing Writer", "limit": 20},
                "risk_level": "low",
            }
        ],
    )

    decision = resolve_legacy_replan_ownership(
        [event],
        source_tool_call_id="app-source-1",
        source_tool_name="app.open",
        plan=_app_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.CLAIMABLE
    assert decision.action_id == "runtime-replan:app.open:action:1:desktop.list_apps"


@pytest.mark.parametrize(
    "event_type",
    [
        "group.run.replan.recovery.updated",
        "workflow.run.replan.recovery.updated",
    ],
)
def test_scoped_event_type_only_progress_blocks_replay(event_type: str) -> None:
    decision = resolve_legacy_replan_ownership(
        [
            _request_event(),
            {
                "event_type": event_type,
                "payload": {"request_id": "runtime-replan:file"},
            },
        ],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.ALREADY_HANDLED
    assert decision.coordinator_may_execute is False


def test_replan_without_a_semantically_matching_action_is_unrelated() -> None:
    event = _request_event()
    event["payload"]["recovery_actions"] = [  # type: ignore[index]
        {"tool": "calendar.create_event", "input": {"title": "unrelated"}}
    ]

    decision = resolve_legacy_replan_ownership(
        [event],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.UNRELATED
    assert decision.coordinator_may_execute is True
    assert decision.event_fields() == {}


def test_multiple_exact_source_replans_fail_closed() -> None:
    first = _request_event()
    second = _request_event()
    second["payload"]["request_id"] = "runtime-replan:file:second"  # type: ignore[index]

    decision = resolve_legacy_replan_ownership(
        [first, second],
        source_tool_call_id="source-1",
        source_tool_name="workspace.read",
        plan=_plan(),
    )

    assert decision.status is RecoveryOwnershipStatus.CONFLICT
    assert decision.coordinator_may_execute is False
