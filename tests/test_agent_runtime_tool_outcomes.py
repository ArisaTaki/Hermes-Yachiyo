from __future__ import annotations

import json
from dataclasses import FrozenInstanceError

import pytest

from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    UserAction,
    VerificationStatus,
    from_tool_result,
)


def test_plain_success_is_canonical_and_event_payload_does_not_repeat_raw() -> None:
    raw = {
        "ok": True,
        "value": 42,
        "private_response": "this stays available only through raw",
    }

    outcome = from_tool_result("workspace.read", raw, capabilities=("workspace.read",))

    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.reason == "ok"
    assert outcome.retryable is False
    assert outcome.effects == ()
    assert outcome.verification is VerificationStatus.NOT_REQUIRED
    assert outcome.user_action is None
    assert outcome.recovery_hints == ()
    assert outcome.raw is raw

    payload = outcome.to_event_payload()
    assert payload == {
        "tool": "workspace.read",
        "capabilities": ["workspace.read"],
        "status": "success",
        "reason": "ok",
        "retryable": False,
        "effects": [],
        "verification": "not_required",
        "recovery_hints": [],
        "provenance": {},
    }
    assert "raw" not in payload
    assert "private_response" not in json.dumps(payload)
    json.dumps(payload)

    with pytest.raises(FrozenInstanceError):
        outcome.status = OutcomeStatus.FAILED  # type: ignore[misc]


def test_media_not_found_is_partial_and_retryable_without_claiming_playback() -> None:
    raw = {
        "ok": True,
        "action": "media.apple_music_play",
        "data": {
            "status": "not_found",
            "outcome": "partial",
            "query": "超时空辉夜姬",
            "library_search_completed": True,
            "playback_started": False,
            "user_action_required": False,
        },
        "_runtime_execution_provenance": {
            "source": "local_tool_broker",
            "version": 1,
        },
    }

    outcome = from_tool_result(
        "media.apple_music_play",
        raw,
        capabilities=("media.search", "media.playback"),
    )

    assert outcome.status is OutcomeStatus.PARTIAL
    assert outcome.reason == "not_found"
    assert outcome.retryable is True
    assert outcome.effects == ()
    assert outcome.verification is VerificationStatus.UNVERIFIED
    assert outcome.user_action is None
    assert dict(outcome.provenance) == {
        "source": "local_tool_broker",
        "version": 1,
    }
    assert outcome.raw is raw
    assert "query" not in json.dumps(outcome.to_event_payload())


@pytest.mark.parametrize(
    "provider_status",
    [
        "playback_unverified",
        "foreground_observation_unverified",
        "catalog_playback_unverified",
    ],
)
def test_portable_partial_outcome_overrides_provider_specific_status(
    provider_status: str,
) -> None:
    raw = {
        "ok": True,
        "data": {
            "status": provider_status,
            "outcome": "partial",
            "playback_started": False,
        },
    }

    outcome = from_tool_result(
        "media.apple_music_play",
        raw,
        capabilities=("media.playback",),
    )

    assert outcome.status is OutcomeStatus.PARTIAL
    assert outcome.reason == provider_status
    assert outcome.retryable is True
    assert outcome.verification is VerificationStatus.UNVERIFIED


def test_workspace_error_uses_stable_reason_and_preserves_recovery_guidance() -> None:
    raw = {
        "ok": False,
        "action": "workspace.read",
        "error": "The requested path does not exist.",
        "error_code": "workspace_path_not_found",
        "retryable": False,
        "recovery_hints": ["Check the path and choose an existing workspace file."],
    }

    outcome = from_tool_result("workspace.read", raw, capabilities=("workspace.read",))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.reason == "workspace_path_not_found"
    assert outcome.retryable is False
    assert outcome.verification is VerificationStatus.NOT_REQUIRED
    assert outcome.recovery_hints == ("Check the path and choose an existing workspace file.",)
    assert outcome.raw is raw
    assert "The requested path" not in json.dumps(outcome.to_event_payload())


def test_permission_required_becomes_structured_user_action() -> None:
    raw = {
        "ok": False,
        "action": "screen.capture",
        "permission_error": True,
        "error": "screen recording permission denied",
        "missing_permissions": ["screen_recording"],
        "permission_targets": ["screen_recording"],
        "recovery_hints": ["Grant Screen Recording permission in System Settings."],
        "recovery_actions": [
            {
                "label": "Open Screen Recording settings",
                "tool": "system.settings_open",
                "input": {"target": "screen_recording", "api_key": "do-not-copy"},
            }
        ],
    }

    outcome = from_tool_result("screen.capture", raw, capabilities=("screen.observe",))

    assert outcome.status is OutcomeStatus.ACTION_REQUIRED
    assert outcome.reason == "permission_required"
    assert outcome.retryable is False
    assert outcome.verification is VerificationStatus.UNVERIFIED
    assert outcome.user_action == UserAction(
        required=True,
        kind="permission",
        targets=("screen_recording",),
        labels=("Open Screen Recording settings",),
    )
    assert outcome.recovery_hints == ("Grant Screen Recording permission in System Settings.",)

    payload = outcome.to_event_payload()
    assert payload["user_action"] == {
        "required": True,
        "kind": "permission",
        "targets": ["screen_recording"],
        "labels": ["Open Screen Recording settings"],
    }
    assert "api_key" not in json.dumps(payload)
    assert "do-not-copy" not in json.dumps(payload)


@pytest.mark.parametrize(
    "tool_name",
    ("desktop.permissions", "desktop.permissions.verify"),
)
def test_successful_permission_diagnostic_reports_advisory_user_action(
    tool_name: str,
) -> None:
    raw = {
        "ok": True,
        "action": tool_name,
        "data": {
            "checked": True,
            "diagnostic_status": "verified",
            "ready": False,
            "missing_permissions": {
                "media.playback": ["music_app", "automation"],
            },
        },
        "permission_error": True,
        "missing_permissions": ["music_app", "automation"],
        "permission_targets": ["music_app", "automation"],
        "recovery_actions": [
            {
                "label": "Open Automation settings",
                "tool": "system.settings_open",
            }
        ],
    }

    outcome = from_tool_result(tool_name, raw)

    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.reason == "ok"
    assert outcome.user_action == UserAction(
        required=True,
        kind="permission",
        targets=("music_app", "automation"),
        labels=("Open Automation settings",),
    )
    assert outcome.to_event_payload()["user_action"]["required"] is True


@pytest.mark.parametrize(
    "failure_evidence",
    (
        {"error": "probe_failed"},
        {"error_code": "probe_failed"},
        {"status": "failed"},
        {"approval_required": True},
    ),
)
def test_permission_diagnostic_with_explicit_failure_is_not_success(
    failure_evidence: dict[str, object],
) -> None:
    outcome = from_tool_result(
        "desktop.permissions",
        {
            "ok": True,
            "permission_error": True,
            "permission_targets": ["automation"],
            **failure_evidence,
        },
    )

    assert outcome.status is not OutcomeStatus.SUCCESS


def test_verification_failure_is_retryable_failure_with_claimed_effects_only() -> None:
    raw = {
        "ok": False,
        "status": "verification_failed",
        "verification_failed": True,
        "retryable": True,
        "side_effects": ["open_request_dispatched"],
        "verification": {"status": "failed", "private_evidence": "window title"},
        "error": "postcondition was not observed",
    }

    outcome = from_tool_result("app.open", raw, capabilities=("app.launch",))

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.reason == "verification_failed"
    assert outcome.retryable is True
    assert outcome.effects == ("open_request_dispatched",)
    assert outcome.verification is VerificationStatus.FAILED
    assert outcome.user_action is None
    assert "private_evidence" not in json.dumps(outcome.to_event_payload())


@pytest.mark.parametrize("raw", ["done", 1, ["ok"], None])
def test_non_mapping_result_is_never_assumed_success(raw: object) -> None:
    outcome = from_tool_result("extension.unknown", raw)

    assert outcome.status is OutcomeStatus.FAILED
    assert outcome.reason == "non_mapping_result"
    assert outcome.retryable is False
    assert outcome.effects == ()
    assert outcome.verification is VerificationStatus.NOT_REQUIRED
    assert outcome.raw is raw


def test_permission_gate_preserves_effects_that_happened_before_the_gate() -> None:
    raw = {
        "ok": False,
        "permission_error": True,
        "missing_permissions": ["automation"],
        "side_effects": ["open_request_dispatched"],
    }

    outcome = from_tool_result("desktop.control", raw)

    assert outcome.status is OutcomeStatus.ACTION_REQUIRED
    assert outcome.effects == ("open_request_dispatched",)
    assert outcome.user_action is not None
    assert "raw" not in outcome.to_event_payload()
    json.dumps(outcome.to_event_payload())


def test_successful_transport_does_not_waive_permission_gate_for_action() -> None:
    outcome = from_tool_result(
        "media.apple_music_play",
        {
            "ok": True,
            "permission_error": True,
            "missing_permissions": ["automation"],
            "permission_targets": ["automation"],
        },
    )

    assert outcome.status is OutcomeStatus.ACTION_REQUIRED
    assert outcome.reason == "permission_required"
    assert outcome.user_action is not None


def test_success_with_advisory_permission_targets_is_not_a_permission_gate() -> None:
    raw = {
        "ok": True,
        "data": {"status": "completed"},
        "permission_targets": ["accessibility"],
        "recovery_actions": [
            {
                "label": "Open Accessibility settings",
                "tool": "system.settings_open",
            }
        ],
    }

    outcome = from_tool_result("desktop.verify", raw)

    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.user_action is None


@pytest.mark.parametrize(
    ("tool_name", "fallback"),
    [
        ("browser.click", "desktop.click"),
        ("browser.type_text", "desktop.type_text"),
        ("browser.screenshot", "screen.capture"),
    ],
)
def test_successful_browser_fallback_reports_degraded_capability_without_permission_gate(
    tool_name: str,
    fallback: str,
) -> None:
    raw = {
        "ok": True,
        "action": tool_name,
        "fallback_used": True,
        "fallback": fallback,
        "permission_error": False,
        "missing_permissions": ["chrome_cdp"],
        "permission_targets": ["chrome_cdp"],
    }

    outcome = from_tool_result(tool_name, raw)

    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.reason == "ok"
    assert outcome.user_action is None


def test_missing_permission_without_successful_fallback_remains_a_gate() -> None:
    outcome = from_tool_result(
        "browser.click",
        {
            "ok": True,
            "fallback_used": False,
            "permission_error": False,
            "missing_permissions": ["chrome_cdp"],
        },
    )

    assert outcome.status is OutcomeStatus.ACTION_REQUIRED
    assert outcome.reason == "permission_required"


def test_skipped_tool_is_distinct_from_execution_failure() -> None:
    raw = {
        "ok": False,
        "status": "skipped",
        "skipped": True,
        "error": "tool_batch_interrupted_before_execution",
    }

    outcome = from_tool_result("workspace.write", raw, capabilities=("workspace.write",))

    assert outcome.status is OutcomeStatus.SKIPPED
    assert outcome.reason == "tool_batch_interrupted_before_execution"
    assert outcome.retryable is True
    assert outcome.effects == ()
    assert outcome.verification is VerificationStatus.NOT_REQUIRED


def test_unverified_side_effect_cannot_be_normalized_as_success() -> None:
    raw = {
        "ok": True,
        "status": "success",
        "effects": ["message_dispatch_requested"],
    }

    outcome = from_tool_result("mail.send", raw, capabilities=("mail.send",))

    assert outcome.status is OutcomeStatus.PARTIAL
    assert outcome.reason == "unverified_effect"
    assert outcome.retryable is True
    assert outcome.effects == ("message_dispatch_requested",)
    assert outcome.verification is VerificationStatus.UNVERIFIED


def test_verified_side_effect_is_success_with_verification_evidence() -> None:
    raw = {
        "ok": True,
        "status": "completed",
        "effects": ["message_sent"],
        "verification": {"status": "verified", "receipt_id": "private-receipt"},
    }

    outcome = from_tool_result("mail.send", raw, capabilities=("mail.send",))

    assert outcome.status is OutcomeStatus.SUCCESS
    assert outcome.reason == "completed"
    assert outcome.retryable is False
    assert outcome.effects == ("message_sent",)
    assert outcome.verification is VerificationStatus.VERIFIED
    assert "private-receipt" not in json.dumps(outcome.to_event_payload())


def test_generic_user_action_is_not_mislabeled_as_permission() -> None:
    raw = {
        "ok": False,
        "status": "action_required",
        "reason": "authentication_required",
        "user_action_required": True,
        "action_targets": ["music_account"],
        "recovery_actions": [{"label": "Sign in to the account"}],
    }

    outcome = from_tool_result("media.catalog_search", raw)

    assert outcome.status is OutcomeStatus.ACTION_REQUIRED
    assert outcome.reason == "authentication_required"
    assert outcome.user_action == UserAction(
        required=True,
        kind="action",
        targets=("music_account",),
        labels=("Sign in to the account",),
    )


def test_provider_provenance_is_not_promoted_without_runtime_ownership() -> None:
    raw = {
        "ok": True,
        "provenance": {"source": "provider-claimed-local", "version": 999},
    }

    outcome = from_tool_result("extension.read", raw)

    assert dict(outcome.provenance) == {}
    assert outcome.to_event_payload()["provenance"] == {}


@pytest.mark.parametrize(
    ("raw", "expected_status", "expected_reason", "expected_retryable"),
    [
        ({"status": "success"}, OutcomeStatus.SUCCESS, "success", False),
        (
            {"status": "partial", "reason": "incomplete_result"},
            OutcomeStatus.PARTIAL,
            "incomplete_result",
            True,
        ),
        (
            {"status": "failed", "reason": "service_unavailable", "retryable": True},
            OutcomeStatus.FAILED,
            "service_unavailable",
            True,
        ),
    ],
)
def test_status_only_results_use_canonical_status_contract(
    raw: dict[str, object],
    expected_status: OutcomeStatus,
    expected_reason: str,
    expected_retryable: bool,
) -> None:
    outcome = from_tool_result("extension.status_only", raw)

    assert outcome.status is expected_status
    assert outcome.reason == expected_reason
    assert outcome.retryable is expected_retryable
