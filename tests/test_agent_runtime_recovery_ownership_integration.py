from __future__ import annotations

import pytest

from apps.shell.agent.runtime.custom_api_agent import (
    _handled_runtime_replan_request_identities,
    _pending_runtime_replan_payloads,
)
from apps.shell.agent.runtime.tool_execution import (
    _runtime_replan_request_payload_for_tool_result,
)


def _correlated_replan_payload() -> dict[str, object]:
    return _runtime_replan_request_payload_for_tool_result(
        {
            "tool": "workspace.read",
            "tool_call_id": "workspace-read-1",
            "input": {"path": "docs/missing.md"},
            "replan_triggers": ["tool_failure"],
        },
        {
            "event": "agent.tool.call",
            "detail": "workspace.read",
            "status": "failed",
            "result": {"ok": False, "error": "路径不存在"},
        },
        run_id="run-1",
    )


def test_legacy_replan_payload_carries_exact_source_tool_call_id() -> None:
    payload = _correlated_replan_payload()

    assert payload["source_tool_call_id"] == "workspace-read-1"
    assert payload["source_tool_name"] == "workspace.read"


def test_coordinator_claim_marks_matching_legacy_replan_handled() -> None:
    payload = _correlated_replan_payload()
    request_id = str(payload["request_id"])
    timeline = [
        {
            "event": "agent.replan.requested",
            "payload": payload,
        },
        {
            "event": "agent.recovery.planned",
            "visibility": "internal",
            "recovery_owner": "coordinator",
            "replan_request_id": request_id,
            "payload": {
                "visibility": "internal",
                "recovery_owner": "coordinator",
                "replan_request_id": request_id,
            },
        },
    ]

    assert _handled_runtime_replan_request_identities(timeline) == {request_id}
    assert _pending_runtime_replan_payloads(timeline) == []


def test_persisted_coordinator_claim_marks_matching_legacy_replan_handled() -> None:
    payload = _correlated_replan_payload()
    request_id = str(payload["request_id"])
    timeline = [
        {"event_type": "agent.replan.requested", "payload": payload},
        {
            "event_type": "agent.recovery.planned",
            "payload": {
                "visibility": "internal",
                "recovery_owner": "coordinator",
                "replan_request_id": request_id,
            },
        },
    ]

    assert _handled_runtime_replan_request_identities(timeline) == {request_id}
    assert _pending_runtime_replan_payloads(timeline) == []


def test_unclaimed_legacy_replan_remains_pending() -> None:
    payload = _correlated_replan_payload()

    assert _pending_runtime_replan_payloads(
        [{"event": "agent.replan.requested", "payload": payload}]
    ) == [payload]


@pytest.mark.parametrize(
    "event_type",
    [
        "group.run.replan.recovery.updated",
        "workflow.run.replan.recovery.updated",
    ],
)
def test_scoped_persisted_recovery_update_marks_request_handled(
    event_type: str,
) -> None:
    payload = _correlated_replan_payload()
    request_id = str(payload["request_id"])
    timeline = [
        {"event_type": "agent.replan.requested", "payload": payload},
        {"event_type": event_type, "payload": {"request_id": request_id}},
    ]

    assert _handled_runtime_replan_request_identities(timeline) == {request_id}
    assert _pending_runtime_replan_payloads(timeline) == []
