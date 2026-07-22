from __future__ import annotations

import pytest

from apps.shell.agent.runtime import custom_api_agent
from apps.shell.agent.runtime.dispatch_semantics import (
    intrinsic_native_postcondition_state,
    is_semantic_safe_shortcut,
    semantic_safe_shortcut_effect,
)
from apps.shell.agent.runtime.outcome_evaluator import evaluate_main_chat_outcome
from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    VerificationStatus,
    from_tool_result,
)
from apps.shell.yachiyo_agent import planner_execution, runtime_execution, runtime_planner


SEMANTIC_SHORTCUT_ACTIONS = (
    "paste",
    "undo",
    "new_reminder",
    "new_event",
    "bookmark_page",
    "lock_screen",
    "force_quit_dialog",
    "future_unknown_action",
    "copy",
)


def test_intrinsic_app_state_requires_exact_structured_status() -> None:
    assert (
        intrinsic_native_postcondition_state(
            "app.show",
            {"app_name": "Slack"},
            {
                "ok": True,
                "action": "app.show",
                "postcondition_verified": True,
                "data": {"app_name": "Slack", "show_status": "shown"},
            },
        )
        == "fulfilled"
    )
    assert (
        intrinsic_native_postcondition_state(
            "desktop.safe_shortcut",
            {"action": "new_window"},
            {
                "ok": True,
                "action": "desktop.safe_shortcut",
                "postcondition_verified": True,
                "data": {"shortcut_action": "new_window"},
            },
        )
        == ""
    )


@pytest.mark.parametrize(
    ("action", "observed_state"),
    (
        ("find", "find_ui_visible"),
        ("new_document", "new_document_visible"),
        ("new_tab", "new_tab_visible"),
        ("spotlight_search", "spotlight_visible"),
    ),
)
def test_semantic_shortcut_provider_claimed_action_specific_state_fails_closed(
    action: str,
    observed_state: str,
) -> None:
    assert (
        intrinsic_native_postcondition_state(
            "desktop.safe_shortcut",
            {"action": action},
            {
                "ok": True,
                "action": "desktop.safe_shortcut",
                "postcondition_verified": True,
                "verified_observed_state": observed_state,
                "data": {"shortcut_action": action},
            },
        )
        == ""
    )


@pytest.mark.parametrize(
    ("action", "observed_state"),
    (
        ("future_unknown_action", "future_unknown_action_visible"),
        ("find", "fulfilled"),
        ("find", "new_tab_visible"),
        ("copy", "copy_observed"),
        ("paste", "paste_observed"),
        ("toggle_full_screen", "full_screen_visible"),
    ),
)
def test_semantic_shortcut_unknown_or_mismatched_state_fails_closed(
    action: str,
    observed_state: str,
) -> None:
    assert (
        intrinsic_native_postcondition_state(
            "desktop.safe_shortcut",
            {"action": action},
            {
                "ok": True,
                "action": "desktop.safe_shortcut",
                "postcondition_verified": True,
                "verified_observed_state": observed_state,
                "data": {"shortcut_action": action},
            },
        )
        == ""
    )


@pytest.mark.parametrize("action", SEMANTIC_SHORTCUT_ACTIONS)
def test_semantic_safe_shortcuts_never_become_dispatch_only_receipts(
    action: str,
) -> None:
    request = {
        "tool": "desktop.safe_shortcut",
        "input": {"action": action},
        "requires_post_action_verification": True,
        "task_todo": {
            "metadata": {
                "action": "dispatch_shortcut",
                "requires_post_action_verification": True,
            }
        },
    }

    assert is_semantic_safe_shortcut(request["tool"], request["input"]) is True
    assert planner_execution._planner_dispatch_action_for_tool_input(
        request["tool"], request["input"]
    ) == ""
    assert runtime_execution._dispatch_action_for_tool_input(
        request["tool"], request["input"]
    ) == ""
    assert runtime_planner._runtime_dispatch_receipt_action(
        request["tool"], request["input"]
    ) == ""
    assert custom_api_agent._dispatch_tool_input_signature(
        request["tool"], request["input"]
    ) == ()
    assert custom_api_agent._approved_tool_has_exact_dispatch_receipt(
        {
            "step_id": "operate-shortcut",
            "action_target": {
                "action": "dispatch_shortcut",
                "step_id": "operate-shortcut",
            },
        },
        tool_name=request["tool"],
        input_preview=request["input"],
        result={
            "ok": True,
            "action": request["tool"],
            "data": {"shortcut_action": action},
        },
    ) is False

    normalized = planner_execution._request_with_explicit_dispatch_contract(request)
    assert normalized["requires_post_action_verification"] is True
    assert normalized["task_todo"]["metadata"][
        "requires_post_action_verification"
    ] is True


def test_raw_hotkey_dispatch_contract_remains_receipt_only() -> None:
    request_input = {"key": "l", "modifiers": ["command"]}

    assert planner_execution._planner_dispatch_action_for_tool_input(
        "desktop.hotkey", request_input
    ) == "dispatch_shortcut"
    assert runtime_execution._dispatch_action_for_tool_input(
        "desktop.hotkey", request_input
    ) == "dispatch_shortcut"
    assert runtime_planner._runtime_dispatch_receipt_action(
        "desktop.hotkey", request_input
    ) == "dispatch_shortcut"


@pytest.mark.parametrize("action", SEMANTIC_SHORTCUT_ACTIONS)
def test_semantic_safe_shortcut_cannot_cross_model_verifier_boundary(
    action: str,
) -> None:
    verifier = {
        "tool": "desktop.ui_elements",
        "input": {},
        "step_id": "verify-effect",
        "runtime_stage": "verify",
        "runtime_role": "verify_result",
        "continue_to_model": True,
        "verification_targets": [{"step_id": "source-effect"}],
        "depends_on": ["source-effect"],
    }
    semantic_effect = {
        "tool": "desktop.safe_shortcut",
        "input": {"action": action},
        "step_id": "shortcut-after-verifier",
        "depends_on": ["verify-effect"],
        "requires_post_action_verification": False,
        "task_todo": {"metadata": {"action": "dispatch_shortcut"}},
    }

    assert planner_execution._execution_prefix_through_model_followup(
        [verifier, semantic_effect]
    ) == [verifier]


@pytest.mark.parametrize("action", SEMANTIC_SHORTCUT_ACTIONS)
def test_shortcut_keystroke_receipt_is_partial_until_semantic_effect_is_verified(
    action: str,
) -> None:
    result = {
        "ok": True,
        "action": "desktop.safe_shortcut",
        "data": {
            "shortcut_action": action,
            "key": "x",
            "modifiers": ["command"],
        },
    }

    outcome = from_tool_result("desktop.safe_shortcut", result)

    assert semantic_safe_shortcut_effect("desktop.safe_shortcut", result) == (
        f"shortcut_dispatched:{action}"
    )
    assert outcome.status is OutcomeStatus.PARTIAL
    assert outcome.reason == "unverified_effect"
    assert outcome.effects == (f"shortcut_dispatched:{action}",)
    assert outcome.verification is VerificationStatus.UNVERIFIED


@pytest.mark.parametrize("action", SEMANTIC_SHORTCUT_ACTIONS)
def test_main_chat_fails_closed_when_shortcut_has_only_keystroke_receipt(
    action: str,
) -> None:
    evaluation = evaluate_main_chat_outcome(
        {},
        [
            {
                "event_type": "agent.tool.call",
                "payload": {
                    "decision_id": "decision-shortcut",
                    "plan_id": "plan-shortcut",
                    "request_id": "request-shortcut",
                    "step_id": "operate-shortcut",
                    "tool": "desktop.safe_shortcut",
                    "input_preview": {"action": action},
                    # A stale planner projection must not grant verification.
                    "requires_post_action_verification": False,
                    "result": {
                        "ok": True,
                        "action": "desktop.safe_shortcut",
                        "data": {"shortcut_action": action},
                    },
                },
            }
        ],
    )

    assert evaluation.kind == "failed"
    assert evaluation.reason == "desktop_verification_missing"


def test_copy_receipt_only_proves_command_c_was_dispatched() -> None:
    """Copy still needs clipboard evidence; the key receipt is not the effect."""

    unverified = from_tool_result(
        "desktop.safe_shortcut",
        {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "data": {
                "shortcut_action": "copy",
                "key": "c",
                "modifiers": ["command"],
            },
        },
    )
    verified = from_tool_result(
        "desktop.safe_shortcut",
        {
            "ok": True,
            "action": "desktop.safe_shortcut",
            "data": {
                "shortcut_action": "copy",
                "key": "c",
                "modifiers": ["command"],
                "postcondition_verified": True,
            },
        },
    )

    assert unverified.status is OutcomeStatus.PARTIAL
    assert unverified.verification is VerificationStatus.UNVERIFIED
    assert verified.status is OutcomeStatus.SUCCESS
    assert verified.verification is VerificationStatus.UNVERIFIED


def test_semantic_followup_waits_for_preceding_effect_verification() -> None:
    decision = runtime_planner.RuntimePlanner().decision(
        "打开 Notes，输入 hello，再复制",
        allowed_tools=[
            "desktop.list_apps",
            "app.open_and_safe_type_text",
            "desktop.safe_shortcut",
            "desktop.ui_elements",
        ],
    )

    steps = decision.plan.tool_plan.steps
    assert [step.step_id for step in steps] == [
        "discover-desktop-state",
        "operate-foreground-ui",
        "verify-desktop-result",
        "operate-foreground-ui-followup",
        "verify-desktop-result-2",
    ]
    copy_step = next(
        step for step in steps if step.step_id == "operate-foreground-ui-followup"
    )
    assert copy_step.action == "shortcut"
    assert copy_step.depends_on == ["verify-desktop-result"]
