"""Approval RunEvent correlation helper regressions."""

from __future__ import annotations

from apps.shell.yachiyo_agent.approval_event_correlation import (
    ApprovalEventCorrelationTracker,
    approval_correlation_keys,
)
from apps.shell.yachiyo_agent.approvals import approval_card_from_payload


def test_approval_correlation_matches_explicit_resolution_id() -> None:
    tracker = ApprovalEventCorrelationTracker()
    pending = approval_card_from_payload(
        {
            "approval_id": "approval-1",
            "tool": "terminal.run",
            "input_preview": {"command": "npm test"},
        },
        run_id="run-1",
    )
    pending_keys, pending_weak_key = approval_correlation_keys(
        {
            "approval_id": "approval-1",
            "tool": "terminal.run",
        },
        pending,
    )
    tracker.register_pending(0, pending_keys, pending_weak_key)

    resolved = approval_card_from_payload(
        {
            "approval_id": "approval-1",
            "tool": "terminal.run",
            "status": "approved",
        },
        run_id="run-1",
    )
    resolved_keys, resolved_weak_key = approval_correlation_keys(
        {
            "approval_id": "approval-1",
            "tool": "terminal.run",
        },
        resolved,
    )

    assert tracker.active_index(
        resolved_keys,
        resolved_weak_key,
        allow_weak=True,
    ) == 0


def test_approval_correlation_does_not_guess_ambiguous_weak_resolution() -> None:
    tracker = ApprovalEventCorrelationTracker()
    first = approval_card_from_payload(
        {
            "approval_id": "run-1:tool.approval_required:1",
            "tool": "terminal.run",
            "input_preview": {"command": "npm test"},
        },
        run_id="run-1",
    )
    second = approval_card_from_payload(
        {
            "approval_id": "run-1:tool.approval_required:2",
            "tool": "terminal.run",
            "input_preview": {"command": "npm run lint"},
        },
        run_id="run-1",
    )
    first_keys, first_weak_key = approval_correlation_keys({"tool": "terminal.run"}, first)
    second_keys, second_weak_key = approval_correlation_keys({"tool": "terminal.run"}, second)
    tracker.register_pending(0, first_keys, first_weak_key)
    tracker.register_pending(1, second_keys, second_weak_key)

    resolved = approval_card_from_payload(
        {
            "approval_id": "run-1:tool.approved:3",
            "tool": "terminal.run",
            "status": "approved",
        },
        run_id="run-1",
    )
    resolved_keys, resolved_weak_key = approval_correlation_keys(
        {"tool": "terminal.run"},
        resolved,
    )

    assert tracker.active_index(
        resolved_keys,
        resolved_weak_key,
        allow_weak=True,
    ) is None
