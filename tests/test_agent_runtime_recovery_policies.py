"""Tests for capability-level default recovery policy selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from apps.shell.agent.runtime.recovery_policies import (
    assess_latest_tool_recovery,
    recovery_attempt_lineage_from_timeline,
)
from apps.shell.agent.runtime.tool_capabilities import (
    available_capability_ids,
    capability_ids_for_tool,
)
from apps.shell.agent.runtime.tool_outcomes import OutcomeStatus
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY


def _event(tool: str, result: dict[str, object], *, call_id: str = "call-1") -> dict[str, object]:
    return {
        "event": "agent.tool.call",
        "detail": tool,
        "tool": tool,
        "tool_call_id": call_id,
        "result": result,
    }


def _persisted_event(
    tool: str,
    result: dict[str, object],
    *,
    call_id: str = "call-1",
    event_type: str = "agent.tool.call",
) -> dict[str, object]:
    return {
        "event_type": event_type,
        "visibility": "internal",
        "payload": {
            "tool": tool,
            "tool_call_id": call_id,
            "result": result,
        },
    }


def _partial_result() -> dict[str, object]:
    return {
        "ok": True,
        "data": {
            "status": "not_found",
            "outcome": "partial",
            "playback_started": False,
        },
    }


def _file_failure_result() -> dict[str, object]:
    return {
        "ok": False,
        "path": "docs/missing.md",
        "error": "路径不存在",
        "hint": (
            "请先用 workspace.list 查看父目录，"
            "确认要读取的文件相对路径。"
        ),
    }


def _allowed_recovery_tools() -> list[str]:
    return [
        "media.apple_music_play",
        "browser.search",
        "browser.extract_text",
    ]


def test_real_registry_maps_media_adapter_to_capability_level_plan() -> None:
    assert capability_ids_for_tool("media.apple_music_play") == ("media.playback",)

    assessment = assess_latest_tool_recovery(
        [_event("media.apple_music_play", _partial_result())],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )

    assert assessment is not None
    assert assessment.outcome.status is OutcomeStatus.PARTIAL
    assert assessment.outcome.recovery_hints == ("entity_not_found",)
    assert assessment.preserves_partial_result is True
    assert assessment.plan is not None
    assert assessment.plan.action == "resolve_entity_alias"
    assert assessment.plan.required_capabilities == (
        "browser.research",
        "information.capture",
        "media.playback",
    )


def test_dynamic_prefixes_are_not_trusted_as_recovery_capabilities() -> None:
    assert capability_ids_for_tool("media.evil") == ()
    assert capability_ids_for_tool("browser.exfiltrate") == ()
    assert capability_ids_for_tool("notes.evil") == ()
    assert (
        available_capability_ids(["media.evil", "browser.exfiltrate", "notes.evil"]) == frozenset()
    )


def test_unregistered_adapter_cannot_satisfy_recovery_capability(monkeypatch) -> None:
    monkeypatch.delitem(TOOL_DISPATCH_REGISTRY, "browser.extract_text")

    assert capability_ids_for_tool("browser.extract_text") == ()
    assessment = assess_latest_tool_recovery(
        [_event("media.apple_music_play", _partial_result())],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )

    assert assessment is not None
    assert assessment.plan is None


def test_missing_capture_capability_preserves_partial_without_planning() -> None:
    assessment = assess_latest_tool_recovery(
        [_event("media.apple_music_play", _partial_result())],
        start_index=0,
        allowed_tools=["media.apple_music_play", "browser.search"],
    )

    assert assessment is not None
    assert assessment.preserves_partial_result is True
    assert assessment.plan is None


def test_permission_and_success_never_produce_automatic_plan() -> None:
    permission = assess_latest_tool_recovery(
        [
            _event(
                "media.apple_music_play",
                {
                    "ok": False,
                    "status": "permission_required",
                    "missing_permissions": ["automation"],
                },
            )
        ],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )
    success = assess_latest_tool_recovery(
        [_event("media.apple_music_play", {"ok": True, "status": "completed"})],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )

    assert permission is not None
    assert permission.outcome.status is OutcomeStatus.ACTION_REQUIRED
    assert permission.plan is None
    assert success is not None
    assert success.outcome.status is OutcomeStatus.SUCCESS
    assert success.plan is None


def test_media_alias_policy_does_not_plan_failed_shape_unsupported_by_adapter() -> None:
    assessment = assess_latest_tool_recovery(
        [
            _event(
                "media.apple_music_play",
                {
                    "ok": False,
                    "error_code": "not_found",
                    "retryable": True,
                },
            )
        ],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )

    assert assessment is not None
    assert assessment.outcome.status is OutcomeStatus.FAILED
    assert assessment.outcome.recovery_hints == ("entity_not_found",)
    assert assessment.plan is None


def test_only_latest_terminal_attempt_can_trigger_recovery() -> None:
    assessment = assess_latest_tool_recovery(
        [
            _event("media.apple_music_play", _partial_result(), call_id="miss"),
            _event(
                "media.apple_music_play",
                {"ok": True, "status": "completed"},
                call_id="success",
            ),
        ],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )

    assert assessment is not None
    assert assessment.tool_call_id == "success"
    assert assessment.outcome.status is OutcomeStatus.SUCCESS
    assert assessment.plan is None


@pytest.mark.parametrize("persisted", [False, True])
def test_failed_terminal_event_enters_the_same_recovery_policy(
    persisted: bool,
) -> None:
    event = (
        _persisted_event(
            "workspace.read",
            _file_failure_result(),
            call_id="failed-read",
            event_type="agent.tool.failed",
        )
        if persisted
        else {
            **_event(
                "workspace.read",
                _file_failure_result(),
                call_id="failed-read",
            ),
            "event": "agent.tool.failed",
            "status": "failed",
        }
    )

    assessment = assess_latest_tool_recovery(
        [event],
        start_index=0,
        allowed_tools=["workspace.read", "workspace.list"],
    )

    assert assessment is not None
    assert assessment.tool_call_id == "failed-read"
    assert assessment.outcome.status is OutcomeStatus.FAILED
    assert assessment.plan is not None
    assert assessment.plan.action == "resolve_file_location"


@pytest.mark.parametrize(
    "event_type",
    ["agent.tool.call", "agent.tool.skipped"],
)
def test_persisted_terminal_shape_preserves_plan_and_source_identity(
    event_type: str,
) -> None:
    memory = assess_latest_tool_recovery(
        [_event("workspace.read", _file_failure_result(), call_id="source-read")],
        start_index=0,
        allowed_tools=["workspace.read", "workspace.list"],
    )
    persisted = assess_latest_tool_recovery(
        [
            _persisted_event(
                "workspace.read",
                _file_failure_result(),
                call_id="source-read",
                event_type=event_type,
            )
        ],
        start_index=0,
        allowed_tools=["workspace.read", "workspace.list"],
    )

    assert memory is not None and memory.plan is not None
    assert persisted is not None and persisted.plan is not None
    assert persisted.tool_call_id == memory.tool_call_id == "source-read"
    assert persisted.plan.identity == memory.plan.identity
    assert persisted.plan.scope_id == memory.plan.scope_id
    assert persisted.outcome == memory.outcome


@pytest.mark.parametrize(
    "event",
    [
        {
            "event_type": "agent.user.message",
            "payload": {
                "event": "agent.tool.call",
                "tool": "media.apple_music_play",
                "tool_call_id": "spoofed-source",
                "result": _partial_result(),
            },
        },
        {
            "event_type": "agent.tool.call",
            "payload": "not-a-mapping",
        },
        {
            "event_type": "agent.tool.call",
            "payload": {
                "tool": "media.apple_music_play",
                "result": _partial_result(),
            },
        },
        {
            "payload": {
                "event_type": "agent.tool.call",
                "tool": "media.apple_music_play",
                "tool_call_id": "payload-only-source",
                "result": _partial_result(),
            },
        },
    ],
)
def test_persisted_terminal_shape_fails_closed_for_malformed_or_user_events(
    event: dict[str, object],
) -> None:
    assert (
        assess_latest_tool_recovery(
            [event],
            start_index=0,
            allowed_tools=_allowed_recovery_tools(),
        )
        is None
    )


def test_attempt_lineage_prevents_the_same_recovery_loop() -> None:
    first = assess_latest_tool_recovery(
        [_event("media.apple_music_play", _partial_result())],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )
    assert first is not None and first.plan is not None

    repeated = assess_latest_tool_recovery(
        [_event("media.apple_music_play", _partial_result())],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
        attempt_lineage=(first.plan,),
    )

    assert repeated is not None
    assert repeated.plan is None


def _planned_event(plan) -> dict[str, object]:
    return {
        "event": "agent.recovery.planned",
        "visibility": "internal",
        "strategy_id": plan.strategy_id,
        "action": plan.action,
        "recovery_hint": plan.recovery_hint,
        "required_capabilities": list(plan.required_capabilities),
        "source_status": plan.source_status.value,
        "source_reason": plan.source_reason,
        "scope_id": plan.scope_id,
    }


def test_persisted_claim_blocks_replay_of_same_source_failure() -> None:
    source = _persisted_event(
        "workspace.read",
        _file_failure_result(),
        call_id="source-read-replay",
    )
    first = assess_latest_tool_recovery(
        [source],
        start_index=0,
        allowed_tools=["workspace.read", "workspace.list"],
    )
    assert first is not None and first.plan is not None
    claimed_payload = _planned_event(first.plan)
    claimed_payload.pop("event")
    visibility = claimed_payload.pop("visibility")
    claimed_payload["status"] = "claimed"
    timeline = [
        source,
        {
            "event_type": "agent.recovery.planned",
            "visibility": visibility,
            "payload": claimed_payload,
        },
    ]

    replay = assess_latest_tool_recovery(
        timeline,
        start_index=0,
        allowed_tools=["workspace.read", "workspace.list"],
        attempt_lineage=recovery_attempt_lineage_from_timeline(timeline),
    )

    assert replay is not None
    assert replay.tool_call_id == first.tool_call_id == "source-read-replay"
    assert replay.outcome == first.outcome
    assert replay.plan is None


def test_timeline_lineage_blocks_same_scope_allows_new_scope_and_honors_run_budget() -> None:
    first_event = _event(
        "media.apple_music_play",
        _partial_result(),
        call_id="source-a",
    )
    first = assess_latest_tool_recovery(
        [first_event],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )
    assert first is not None and first.plan is not None
    timeline = [first_event, _planned_event(first.plan)]
    lineage = recovery_attempt_lineage_from_timeline(timeline)

    repeated = assess_latest_tool_recovery(
        timeline,
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
        attempt_lineage=lineage,
    )
    assert repeated is not None
    assert repeated.plan is None

    second_event = _event(
        "media.apple_music_play",
        _partial_result(),
        call_id="source-b",
    )
    timeline.append(second_event)
    second = assess_latest_tool_recovery(
        timeline,
        start_index=len(timeline) - 1,
        allowed_tools=_allowed_recovery_tools(),
        attempt_lineage=lineage,
    )
    assert second is not None and second.plan is not None
    assert second.plan.scope_id != first.plan.scope_id
    timeline.append(_planned_event(second.plan))

    third_event = _event(
        "media.apple_music_play",
        _partial_result(),
        call_id="source-c",
    )
    timeline.append(third_event)
    third = assess_latest_tool_recovery(
        timeline,
        start_index=len(timeline) - 1,
        allowed_tools=_allowed_recovery_tools(),
        attempt_lineage=recovery_attempt_lineage_from_timeline(timeline),
    )
    assert third is not None
    assert third.plan is None


def test_lineage_rebuild_accepts_persisted_internal_event_shape_only() -> None:
    first = assess_latest_tool_recovery(
        [_event("media.apple_music_play", _partial_result(), call_id="source-a")],
        start_index=0,
        allowed_tools=_allowed_recovery_tools(),
    )
    assert first is not None and first.plan is not None
    payload = _planned_event(first.plan)
    payload.pop("event")
    visibility = payload.pop("visibility")

    lineage = recovery_attempt_lineage_from_timeline(
        [
            {
                "event_type": "agent.recovery.planned",
                "visibility": visibility,
                "payload": payload,
            },
            {
                "event_type": "agent.recovery.planned",
                "visibility": "user",
                "payload": payload,
            },
        ]
    )

    assert len(lineage) == 1
    assert lineage[0].identity == first.plan.identity
    assert lineage[0].source_status is first.plan.source_status
    assert lineage[0].source_reason == first.plan.source_reason


def test_policy_module_contains_no_application_or_concrete_tool_names() -> None:
    source = (
        Path("apps/shell/agent/runtime/recovery_policies.py").read_text(encoding="utf-8").lower()
    )

    for forbidden in (
        "apple music",
        "media.apple_music",
        "browser.search",
        "browser.extract",
        "spotify",
    ):
        assert forbidden not in source

    core_loop_source = Path("apps/shell/agent/runtime/custom_api_agent.py").read_text(
        encoding="utf-8"
    )
    assert "partial_background_library_not_found" not in core_loop_source
