"""Execution-environment strategy projection for runtime plans."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from .contracts import (
    RuntimeExecutionStrategySnapshot,
    TaskIntentSnapshot,
    ToolPlanStepSnapshot,
)
from .desktop_execution_policy import (
    desktop_execution_policy_mode,
    desktop_execution_policy_payload,
    is_local_low_risk_foreground_tool,
    user_foreground_takeover_allowed,
)
from .planner_primitives import stable_planner_id, unique_planner_strings


def execution_strategy_snapshot(
    intent: TaskIntentSnapshot,
    steps: Iterable[ToolPlanStepSnapshot],
    metadata: Mapping[str, Any] | None,
) -> RuntimeExecutionStrategySnapshot:
    step_list = list(steps)
    policy = _planner_desktop_execution_policy(metadata)
    policy_mode = desktop_execution_policy_mode(policy)
    decision_context: dict[str, Any] = {}
    if isinstance(metadata, Mapping):
        decision_context.update(metadata)
    decision_context.update(policy)
    foreground_takeover_allowed = user_foreground_takeover_allowed(decision_context)
    background_desktop_preferred = _strategy_truthy(
        decision_context,
        "prefer_background_desktop",
    )
    isolated_desktop_preferred = _strategy_truthy(
        decision_context,
        "prefer_isolated_desktop",
        "require_sandbox_for_keyboard_mouse",
    )
    foreground_control_count = sum(
        1 for step in step_list if _step_execution_mode_flag(step, "foreground_control")
    )
    keyboard_mouse_count = sum(
        1 for step in step_list if _step_execution_mode_flag(step, "keyboard_mouse_capture")
    )
    sandbox_recommended_count = sum(
        1 for step in step_list if _step_execution_mode_flag(step, "sandbox_recommended")
    )
    handoff_count = sum(
        1 for step in step_list if _step_execution_mode_flag(step, "user_handoff_recommended")
    )
    approval_count = sum(
        1
        for step in step_list
        if step.approval_required or _step_execution_mode_flag(step, "approval_recommended")
    )
    read_only_count = sum(
        1
        for step in step_list
        if _step_execution_mode_value(step, "mode") == "read_only_observation"
    )
    local_foreground_fallback_allowed = _strategy_local_foreground_fallback_allowed(
        step_list,
        foreground_control_count=foreground_control_count,
        keyboard_mouse_count=keyboard_mouse_count,
    )
    if (
        not foreground_takeover_allowed
        and (background_desktop_preferred or isolated_desktop_preferred)
    ):
        local_foreground_fallback_allowed = False
    if (
        sandbox_recommended_count
        and not foreground_takeover_allowed
        and not background_desktop_preferred
    ):
        isolated_desktop_preferred = True
    sandbox_required = bool(
        keyboard_mouse_count
        and (
            _strategy_truthy(decision_context, "require_sandbox_for_keyboard_mouse")
            or (
                sandbox_recommended_count
                and not foreground_takeover_allowed
                and not background_desktop_preferred
            )
        )
    )
    if handoff_count:
        preferred_environment = "user_handoff"
        interaction_mode = "handoff"
    elif foreground_control_count or keyboard_mouse_count:
        if isolated_desktop_preferred:
            preferred_environment = "isolated_desktop"
            interaction_mode = "foreground"
        elif background_desktop_preferred:
            preferred_environment = "background_desktop"
            interaction_mode = "background"
        elif foreground_takeover_allowed:
            preferred_environment = "user_foreground"
            interaction_mode = "foreground"
        else:
            preferred_environment = "user_handoff"
            interaction_mode = "handoff"
    elif read_only_count and background_desktop_preferred:
        preferred_environment = "background_desktop"
        interaction_mode = "read_only"
    elif read_only_count and isolated_desktop_preferred:
        preferred_environment = "isolated_desktop"
        interaction_mode = "read_only"
    elif read_only_count:
        preferred_environment = "structured_runtime"
        interaction_mode = "read_only"
    else:
        preferred_environment = "structured_runtime"
        interaction_mode = "background"
    user_foreground_takeover_risk = bool(
        (foreground_control_count or keyboard_mouse_count)
        and foreground_takeover_allowed
    )
    provider_auto_start_recommended = _strategy_provider_auto_start_recommended(
        preferred_environment=preferred_environment,
        sandbox_required=sandbox_required,
        local_foreground_fallback_allowed=local_foreground_fallback_allowed,
        foreground_control_count=foreground_control_count,
        keyboard_mouse_count=keyboard_mouse_count,
        sandbox_recommended_count=sandbox_recommended_count,
        approval_count=approval_count,
        handoff_count=handoff_count,
    )
    reasons = _execution_strategy_reasons(
        step_count=len(step_list),
        background_desktop_preferred=background_desktop_preferred,
        isolated_desktop_preferred=isolated_desktop_preferred,
        foreground_control_count=foreground_control_count,
        keyboard_mouse_count=keyboard_mouse_count,
        sandbox_recommended_count=sandbox_recommended_count,
        approval_count=approval_count,
        handoff_count=handoff_count,
        user_foreground_takeover_risk=user_foreground_takeover_risk,
        provider_auto_start_recommended=provider_auto_start_recommended,
        local_foreground_fallback_allowed=local_foreground_fallback_allowed,
    )
    mitigations = _execution_strategy_mitigations(
        preferred_environment=preferred_environment,
        interaction_mode=interaction_mode,
        foreground_takeover_allowed=foreground_takeover_allowed,
        keyboard_mouse_count=keyboard_mouse_count,
        read_only_count=read_only_count,
        provider_auto_start_recommended=provider_auto_start_recommended,
        local_foreground_fallback_allowed=local_foreground_fallback_allowed,
    )
    return RuntimeExecutionStrategySnapshot(
        strategy_id=stable_planner_id(
            "execution-strategy",
            intent.kind,
            f"{intent.user_goal}:{preferred_environment}:{interaction_mode}",
        ),
        preferred_environment=preferred_environment,
        interaction_mode=interaction_mode,
        policy_mode=policy_mode,
        background_desktop_preferred=background_desktop_preferred,
        isolated_desktop_preferred=isolated_desktop_preferred,
        foreground_takeover_allowed=foreground_takeover_allowed,
        user_foreground_takeover_risk=user_foreground_takeover_risk,
        sandbox_required=sandbox_required,
        provider_auto_start_recommended=provider_auto_start_recommended,
        local_foreground_fallback_allowed=local_foreground_fallback_allowed,
        foreground_control_step_count=foreground_control_count,
        keyboard_mouse_step_count=keyboard_mouse_count,
        sandbox_recommended_step_count=sandbox_recommended_count,
        approval_step_count=approval_count,
        handoff_step_count=handoff_count,
        reasons=reasons,
        mitigations=mitigations,
    )


def runtime_planner_preflight_ui_before_action(
    metadata: Mapping[str, Any] | None,
) -> bool:
    if not isinstance(metadata, Mapping):
        return False
    if _strategy_truthy(
        metadata,
        "runtime_planner_preflight_ui_before_action",
        "desktop_preflight_ui_before_action",
        "preflight_ui_before_action",
    ):
        return True
    policy = _planner_desktop_execution_policy(metadata)
    return _strategy_truthy(
        policy,
        "runtime_planner_preflight_ui_before_action",
        "desktop_preflight_ui_before_action",
        "preflight_ui_before_action",
    )


def _planner_desktop_execution_policy(
    metadata: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if not isinstance(metadata, Mapping):
        return {}
    for key in (
        "desktop_execution_policy",
        "yachiyo_desktop_execution_policy",
        "desktop_interaction_policy",
    ):
        policy = desktop_execution_policy_payload(metadata.get(key))
        if policy:
            return policy
    return {}


def _step_execution_mode_flag(step: ToolPlanStepSnapshot, key: str) -> bool:
    mode = step.execution_mode
    if isinstance(mode, Mapping):
        return bool(mode.get(key))
    return bool(getattr(mode, key, False))


def _step_execution_mode_value(step: ToolPlanStepSnapshot, key: str) -> str:
    mode = step.execution_mode
    if isinstance(mode, Mapping):
        return str(mode.get(key) or "").strip()
    return str(getattr(mode, key, "") or "").strip()


def _strategy_truthy(source: Mapping[str, Any], *keys: str) -> bool:
    for key in keys:
        value = source.get(key)
        if isinstance(value, bool):
            if value:
                return True
            continue
        if str(value or "").strip().lower() in {"1", "true", "yes", "on"}:
            return True
    return False


def _strategy_local_foreground_fallback_allowed(
    steps: Iterable[ToolPlanStepSnapshot],
    *,
    foreground_control_count: int,
    keyboard_mouse_count: int,
) -> bool:
    if not foreground_control_count or keyboard_mouse_count:
        return False
    foreground_tools = [
        str(step.tool_name or "").strip()
        for step in steps
        if _step_execution_mode_flag(step, "foreground_control")
    ]
    return bool(foreground_tools) and all(
        is_local_low_risk_foreground_tool(tool_name)
        for tool_name in foreground_tools
    )


def _strategy_provider_auto_start_recommended(
    *,
    preferred_environment: str,
    sandbox_required: bool,
    local_foreground_fallback_allowed: bool,
    foreground_control_count: int,
    keyboard_mouse_count: int,
    sandbox_recommended_count: int,
    approval_count: int,
    handoff_count: int,
) -> bool:
    if preferred_environment != "isolated_desktop":
        return False
    if local_foreground_fallback_allowed:
        return False
    if approval_count or handoff_count:
        return False
    return bool(
        keyboard_mouse_count
        or foreground_control_count
        or sandbox_required
        or sandbox_recommended_count
    )


def _execution_strategy_reasons(
    *,
    step_count: int,
    background_desktop_preferred: bool,
    isolated_desktop_preferred: bool,
    foreground_control_count: int,
    keyboard_mouse_count: int,
    sandbox_recommended_count: int,
    approval_count: int,
    handoff_count: int,
    user_foreground_takeover_risk: bool,
    provider_auto_start_recommended: bool,
    local_foreground_fallback_allowed: bool,
) -> list[str]:
    reasons: list[str] = []
    if not step_count:
        reasons.append("no_executable_steps_planned")
    if background_desktop_preferred:
        reasons.append("policy_prefers_background_desktop")
    if isolated_desktop_preferred:
        reasons.append("policy_prefers_isolated_desktop")
    if foreground_control_count:
        reasons.append("foreground_control_planned")
    if keyboard_mouse_count:
        reasons.append("keyboard_mouse_capture_planned")
    if sandbox_recommended_count:
        reasons.append("sandbox_recommended_by_tool_modes")
    if approval_count:
        reasons.append("approval_required_for_risky_steps")
    if handoff_count:
        reasons.append("user_handoff_recommended")
    if user_foreground_takeover_risk:
        reasons.append("user_foreground_takeover_allowed")
    if provider_auto_start_recommended:
        reasons.append("isolated_provider_auto_start_recommended")
    if local_foreground_fallback_allowed:
        reasons.append("local_low_risk_foreground_fallback_allowed")
    return unique_planner_strings(reasons)


def _execution_strategy_mitigations(
    *,
    preferred_environment: str,
    interaction_mode: str,
    foreground_takeover_allowed: bool,
    keyboard_mouse_count: int,
    read_only_count: int,
    provider_auto_start_recommended: bool,
    local_foreground_fallback_allowed: bool,
) -> list[str]:
    mitigations: list[str] = []
    if preferred_environment == "background_desktop":
        mitigations.append("run_in_background_desktop_provider")
    if preferred_environment == "isolated_desktop":
        mitigations.append("run_in_controlled_desktop_provider")
    if interaction_mode in {"foreground", "handoff"}:
        mitigations.append("verify_after_desktop_action")
    if keyboard_mouse_count:
        mitigations.append("apply_risk_policy_before_keyboard_mouse")
    if not foreground_takeover_allowed:
        mitigations.append("do_not_take_over_user_foreground_session")
    if provider_auto_start_recommended:
        mitigations.append("auto_start_or_prompt_isolated_desktop_provider")
    if local_foreground_fallback_allowed:
        mitigations.append("limit_local_fallback_to_low_risk_app_activation")
    if read_only_count:
        mitigations.append("observe_before_operate")
    return unique_planner_strings(mitigations)
