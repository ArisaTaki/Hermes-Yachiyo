"""Canonical action-target ontology shared by planning and verification.

The planner, execution envelope, and GoalContract must describe one action in
the same vocabulary.  This module intentionally knows capability and tool
semantics, but no product/application-specific branches.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from apps.shell.agent.runtime.app_aliases import APP_ALIASES, compact_app_alias


_TOOL_ACTIONS = {
    "app.focus": "focus_app",
    "app.focus_window": "focus_app_window",
    "app.hide": "hide_app",
    "app.minimize": "minimize_app",
    "app.open": "open_app",
    "app.quit": "quit_app",
    "app.show": "show_app",
    "app.status": "status_app",
    "desktop.active_window": "read_active_window",
    "desktop.focus_app": "focus_app",
    "desktop.inspect_app": "inspect_app",
    "desktop.list_apps": "discover_apps",
    "desktop.list_windows": "list_windows",
    "desktop.open_app": "open_app",
    "desktop.read_ui": "read_ui",
    "desktop.running_apps": "list_running_apps",
    "desktop.ui_elements": "read_ui",
    "desktop.windows": "list_windows",
    "screen.capture": "capture_screen",
}

_DESKTOP_ACTION_ALIASES = {
    "click": "click_ui",
    "safe_click": "click_ui",
    "type": "type_ui",
    "safe_type": "type_ui",
    "type_text": "type_ui",
    "submit": "submit_ui",
    "shortcut": "keyboard_shortcut",
    "safe_shortcut": "keyboard_shortcut",
    "hotkey": "keyboard_shortcut",
    "key": "keyboard_key",
    "safe_key": "keyboard_key",
    "scroll": "scroll_ui",
    "safe_scroll": "scroll_ui",
    "read_running_apps": "list_running_apps",
}

_DESKTOP_APP_SCOPED_ACTIONS = frozenset(
    {
        "click_ui",
        "focus_app",
        "focus_app_window",
        "inspect_app",
        "keyboard_key",
        "keyboard_shortcut",
        "open_app",
        "open_path_with_app",
        "scroll_ui",
        "submit_ui",
        "type_ui",
    }
)

_DESKTOP_DISCOVERY_ACTIONS = frozenset(
    {
        "capture_screen",
        "discover_apps",
        "list_running_apps",
        "list_windows",
        "read_active_window",
        "read_ui",
        "verify_after_action",
    }
)

_DESKTOP_STATE_ENUMERATION_ACTIONS = frozenset(
    {
        "capture_screen",
        "discover_apps",
        "list_running_apps",
        "list_windows",
        "read_active_window",
    }
)

_DESKTOP_DISCOVERY_TOOLS = frozenset(
    {
        "desktop.active_window",
        "desktop.list_apps",
        "desktop.list_windows",
        "desktop.running_apps",
        "desktop.windows",
        "screen.capture",
    }
)

_SHORTCUT_ACTION_ALIASES = frozenset({"dispatch_shortcut", "keyboard_shortcut"})
_SEMANTIC_SHORTCUT_SIGNATURES = {
    "copy": ("c", ("command",)),
    "cut": ("x", ("command",)),
    "paste": ("v", ("command",)),
    "select_all": ("a", ("command",)),
}
_SHORTCUT_MODIFIER_ALIASES = {
    "cmd": "command",
    "command": "command",
    "meta": "command",
    "ctrl": "control",
    "control": "control",
    "alt": "option",
    "option": "option",
    "shift": "shift",
}
_SHORTCUT_MODIFIER_ORDER = ("command", "control", "option", "shift")


def canonical_action_name(
    action: Any,
    *,
    tool_name: str = "",
    capability_id: str = "",
    runtime_stage: str = "",
) -> str:
    """Return the capability-level action used from plan through receipt."""

    clean_action = str(action or "").strip()
    clean_tool = str(tool_name or "").strip()
    clean_capability = str(capability_id or "").strip()
    if str(runtime_stage or "").strip() == "verify" and (
        clean_capability.startswith("desktop.")
        or clean_tool.startswith(("app.", "desktop.", "screen."))
    ):
        return "verify_after_action"
    if clean_action.startswith("dispatch_"):
        return clean_action
    if clean_capability.startswith("desktop.") or clean_tool.startswith(
        ("app.", "desktop.", "screen.")
    ):
        if clean_tool in _TOOL_ACTIONS:
            return _TOOL_ACTIONS[clean_tool]
        if clean_tool in {"desktop.search_submit", "desktop.submit_foreground"}:
            return "submit_ui"
        if "click" in clean_tool:
            return "click_ui"
        if "type" in clean_tool:
            return "type_ui"
        if "shortcut" in clean_tool or "hotkey" in clean_tool:
            return "keyboard_shortcut"
        if "key" in clean_tool:
            return "keyboard_key"
        if "scroll" in clean_tool:
            return "scroll_ui"
        return _DESKTOP_ACTION_ALIASES.get(clean_action, clean_action)
    return clean_action


def canonical_action_target(
    target: Mapping[str, Any] | None,
    *,
    capability_id: str = "",
    step_id: str = "",
    tool_name: str = "",
    runtime_stage: str = "",
) -> dict[str, Any]:
    """Canonicalize one target without inventing authority outside its step."""

    if not isinstance(target, Mapping) or not target:
        return {}
    result = {
        str(key): value
        for key, value in target.items()
        if value not in (None, "", [], {})
    }
    action = canonical_action_name(
        result.get("action"),
        tool_name=tool_name,
        capability_id=capability_id,
        runtime_stage=runtime_stage,
    )
    if action:
        result["action"] = action
    if action in _SHORTCUT_ACTION_ALIASES or result.get("shortcut_action"):
        result = _canonical_shortcut_target(result)

    clean_capability = str(capability_id or "").strip()
    clean_tool = str(tool_name or "").strip()
    app_name = str(result.get("app_name") or "").strip()
    target_kind = str(result.get("kind") or "").strip()
    selection_source = str(result.get("selection_source") or "").strip()
    has_owned_app_scope = bool(
        app_name
        or selection_source
        in {"desktop.list_apps", "desktop.running_apps", "direct_app_name"}
    )
    if str(runtime_stage or "").strip() == "verify" and app_name:
        result["kind"] = "desktop_app"
    elif clean_tool in _DESKTOP_DISCOVERY_TOOLS or (
        clean_capability == "desktop.app_discovery"
        and action in _DESKTOP_STATE_ENUMERATION_ACTIONS
        and target_kind in {"desktop_app", "desktop_discovery", "desktop_ui"}
    ):
        result["kind"] = "desktop_discovery"
        if clean_tool in _DESKTOP_DISCOVERY_TOOLS:
            result.setdefault("selection_source", clean_tool)
    elif (
        has_owned_app_scope
        and (
            clean_capability in {"desktop.ui_operation", "desktop.app_discovery"}
            or clean_tool.startswith(("app.", "desktop."))
        )
        and action not in _DESKTOP_STATE_ENUMERATION_ACTIONS
        and target_kind
        in {"desktop_app", "desktop_discovery", "desktop_foreground", "desktop_ui"}
    ):
        result["kind"] = "desktop_app"
    elif (
        clean_capability == "desktop.ui_operation"
        and action in _DESKTOP_APP_SCOPED_ACTIONS
        and app_name
        and target_kind in {"desktop_app", "desktop_ui"}
    ):
        result["kind"] = "desktop_app"
    if (
        app_name
        and result.get("kind") == "desktop_app"
        and clean_tool.startswith(("app.", "desktop."))
    ):
        result.setdefault("selection_source", "direct_app_name")
        result.setdefault("query", app_name)
    if step_id:
        result["step_id"] = str(step_id).strip()
    return result


def action_target_matches(
    expected: Mapping[str, Any],
    observed: Mapping[str, Any],
    *,
    capability_ids: Iterable[str] = (),
    source_step_id: str = "",
) -> bool:
    """Match aliases only when capability/step semantics prove equivalence."""

    capabilities = tuple(
        dict.fromkeys(
            str(value or "").strip()
            for value in capability_ids
            if str(value or "").strip()
        )
    )
    capability = capabilities[0] if len(capabilities) == 1 else ""
    expected_target = canonical_action_target(
        expected,
        capability_id=capability,
        step_id=str(expected.get("step_id") or source_step_id or "").strip(),
    )
    observed_target = canonical_action_target(
        observed,
        capability_id=capability,
        step_id=str(observed.get("step_id") or source_step_id or "").strip(),
    )
    expected_action = str(expected_target.get("action") or "").strip()
    for key, value in expected_target.items():
        if key not in observed_target:
            return False
        observed_value = observed_target[key]
        if key == "kind":
            if not _target_kinds_equivalent(
                str(value or "").strip(),
                str(observed_value or "").strip(),
                capability_id=capability,
                action=expected_action,
                source_step_id=source_step_id,
            ):
                return False
            continue
        if key == "app_name":
            if not _app_identity_matches(value, observed_value):
                return False
            continue
        if key == "selection_source":
            if not _selection_sources_equivalent(
                value,
                observed_value,
                expected_target,
                observed_target,
            ):
                return False
            continue
        if key == "query" and _query_is_app_identity(
            value,
            expected_target,
        ) and _query_is_app_identity(observed_value, observed_target):
            if not _app_identity_matches(value, observed_value):
                return False
            continue
        if not _value_matches(value, observed_value):
            return False
    return True


def bind_planned_action_target(
    planned: Mapping[str, Any],
    projected: Mapping[str, Any],
    *,
    capability_id: str,
    source_step_id: str,
    tool_name: str = "",
    runtime_stage: str = "",
) -> dict[str, Any]:
    """Validate a projection, then return the planner-owned canonical target."""

    canonical_planned = canonical_action_target(
        planned,
        capability_id=capability_id,
        step_id=source_step_id,
        tool_name=tool_name,
        runtime_stage=runtime_stage,
    )
    canonical_projected = canonical_action_target(
        projected,
        capability_id=capability_id,
        step_id=source_step_id,
        tool_name=tool_name,
        runtime_stage=runtime_stage,
    )
    if canonical_projected and not _projection_matches_planned_target(
        canonical_planned,
        canonical_projected,
        capability_id=capability_id,
        source_step_id=source_step_id,
    ):
        raise ValueError("runtime_execution_action_target_conflict")
    merged = {**canonical_planned, **canonical_projected}
    if {
        str(canonical_planned.get("action") or "").strip(),
        str(canonical_projected.get("action") or "").strip(),
    } == set(_SHORTCUT_ACTION_ALIASES):
        # The execution projection supplies the concrete keyboard identity,
        # while the immutable plan owns the bounded dispatch semantics.
        merged["action"] = canonical_planned["action"]
    if (
        canonical_planned.get("selection_source")
        and canonical_projected.get("selection_source")
        and canonical_planned.get("selection_source")
        != canonical_projected.get("selection_source")
        and _selection_sources_equivalent(
            canonical_planned.get("selection_source"),
            canonical_projected.get("selection_source"),
            canonical_planned,
            canonical_projected,
        )
    ):
        # A concrete discovery receipt may refine how the app was resolved,
        # but it must not rewrite the immutable planner-owned target identity.
        merged["selection_source"] = canonical_planned["selection_source"]
    if (
        canonical_planned.get("query")
        and not _query_is_app_identity(
            canonical_planned.get("query"),
            canonical_planned,
        )
        and (
            _query_is_app_identity(
                canonical_projected.get("query"),
                canonical_projected,
            )
            or _query_is_app_selection_scope(
                canonical_projected.get("query"),
                canonical_projected,
            )
        )
    ):
        # A concrete projection may refine the app selection source, but its
        # app-name/capability query must not erase the semantic query bound by
        # the immutable planner contract.  Preserve both meanings explicitly.
        merged["selection_query"] = canonical_projected["query"]
        merged["query"] = canonical_planned["query"]
    return merged


def _projection_matches_planned_target(
    planned: Mapping[str, Any],
    projected: Mapping[str, Any],
    *,
    capability_id: str,
    source_step_id: str,
) -> bool:
    """Reject contradictions without requiring a projection to restate the plan.

    Execution adapters often know only the concrete application scope.  The
    planner remains authoritative for operation details such as a semantic UI
    label, role, and click count, so absence of those fields is not a conflict.
    Any overlapping field must still identify the same action and target.
    """

    planned_action = str(planned.get("action") or "").strip()
    for key in planned.keys() & projected.keys():
        expected = planned[key]
        observed = projected[key]
        if key == "action" and {str(expected), str(observed)} == set(
            _SHORTCUT_ACTION_ALIASES
        ):
            if not _shortcut_dispatch_targets_equivalent(
                planned,
                projected,
                capability_id=capability_id,
                source_step_id=source_step_id,
            ):
                return False
            continue
        if key == "kind":
            if not _target_kinds_equivalent(
                str(expected or "").strip(),
                str(observed or "").strip(),
                capability_id=capability_id,
                action=planned_action,
                source_step_id=source_step_id,
            ):
                return False
            continue
        if key in {"app_name", "query"} and _query_or_app_is_identity(
            key,
            expected,
            planned,
        ) and _query_or_app_is_identity(key, observed, projected):
            if not _app_identity_matches(expected, observed):
                return False
            continue
        if (
            key == "query"
            and not _query_is_app_identity(expected, planned)
            and (
                _query_is_app_identity(observed, projected)
                or _query_is_app_selection_scope(observed, projected)
            )
        ):
            # The execution projection may carry either an exact app identity
            # or a discovery/capability selector.  Both are app-scope evidence,
            # not a competing in-app search query.
            if _query_is_app_selection_scope(observed, projected):
                continue
            planned_app = str(planned.get("app_name") or "").strip()
            projected_app = str(projected.get("app_name") or "").strip()
            if planned_app and projected_app and _app_identity_matches(
                planned_app,
                projected_app,
            ):
                continue
            return False
        if key == "selection_source":
            if not _selection_sources_equivalent(
                expected,
                observed,
                planned,
                projected,
            ):
                return False
            continue
        if not _value_matches(expected, observed):
            return False
    return True


def _canonical_shortcut_target(target: Mapping[str, Any]) -> dict[str, Any]:
    result = dict(target)
    shortcut_action = str(result.get("shortcut_action") or "").strip().lower()
    if shortcut_action:
        result["shortcut_action"] = shortcut_action
    signature = _SEMANTIC_SHORTCUT_SIGNATURES.get(shortcut_action)
    if signature is not None:
        key, modifiers = signature
        result.setdefault("key", key)
        result.setdefault("modifiers", list(modifiers))
    key = str(result.get("key") or "").strip().lower()
    if key:
        result["key"] = key
    raw_modifiers = result.get("modifiers")
    if isinstance(raw_modifiers, str):
        raw_modifier_values: Iterable[Any] = raw_modifiers.replace("+", " ").split()
    elif isinstance(raw_modifiers, Iterable) and not isinstance(
        raw_modifiers,
        (bytes, Mapping),
    ):
        raw_modifier_values = raw_modifiers
    else:
        raw_modifier_values = ()
    normalized_modifiers = {
        _SHORTCUT_MODIFIER_ALIASES.get(
            str(value or "").strip().lower(),
            str(value or "").strip().lower(),
        )
        for value in raw_modifier_values
        if str(value or "").strip()
    }
    if normalized_modifiers:
        result["modifiers"] = [
            modifier
            for modifier in _SHORTCUT_MODIFIER_ORDER
            if modifier in normalized_modifiers
        ] + sorted(normalized_modifiers - set(_SHORTCUT_MODIFIER_ORDER))
    return result


def _shortcut_dispatch_targets_equivalent(
    planned: Mapping[str, Any],
    projected: Mapping[str, Any],
    *,
    capability_id: str,
    source_step_id: str,
) -> bool:
    if not str(capability_id or "").strip() or not str(source_step_id or "").strip():
        return False
    if any(
        str(target.get("step_id") or "").strip() != str(source_step_id or "").strip()
        for target in (planned, projected)
    ):
        return False
    if not str(planned.get("shortcut_action") or "").strip():
        return False
    if not str(projected.get("shortcut_action") or "").strip():
        return False
    for key in ("shortcut_action", "key", "modifiers", "target", "window_title"):
        if not _value_matches(planned.get(key), projected.get(key)):
            return False
    planned_app = str(planned.get("app_name") or "").strip()
    projected_app = str(projected.get("app_name") or "").strip()
    if bool(planned_app) != bool(projected_app):
        return False
    return not planned_app or _app_identity_matches(planned_app, projected_app)


def _target_kinds_equivalent(
    expected: str,
    observed: str,
    *,
    capability_id: str,
    action: str,
    source_step_id: str,
) -> bool:
    if expected == observed:
        return True
    if not source_step_id:
        return False
    pair = {expected, observed}
    if capability_id == "desktop.ui_operation" and action in {
        *_DESKTOP_APP_SCOPED_ACTIONS,
        "observe_ui_target",
        "read_ui",
    }:
        return pair.issubset(
            {"desktop_app", "desktop_foreground", "desktop_ui"}
        )
    if capability_id == "desktop.app_discovery" and action in {
        "inspect_app",
        "read_ui",
    }:
        return pair.issubset(
            {"desktop_app", "desktop_discovery", "desktop_foreground", "desktop_ui"}
        )
    if (
        capability_id == "desktop.app_discovery"
        and action in _DESKTOP_STATE_ENUMERATION_ACTIONS
    ):
        # A planner may own the whole desktop state while the execution
        # adapter narrows that same read to the current discovery/foreground
        # surface.  Step + capability + canonical action still have to match;
        # this does not make an app-scoped mutation interchangeable.
        return pair.issubset(
            {"desktop", "desktop_discovery", "desktop_foreground"}
        )
    if capability_id.startswith("communication.") and action in {
        *_DESKTOP_APP_SCOPED_ACTIONS,
        "read_ui",
    }:
        return pair.issubset(
            {"desktop_app", "desktop_foreground", "desktop_ui"}
        )
    return False


def _app_identity_matches(left: Any, right: Any) -> bool:
    left_text = str(left or "").strip()
    right_text = str(right or "").strip()
    if not left_text or not right_text:
        return False
    if left_text.startswith("<selected app from ") or right_text.startswith(
        "<selected app from "
    ):
        return left_text.casefold() == right_text.casefold()
    left_compact = compact_app_alias(left_text)
    right_compact = compact_app_alias(right_text)
    left_name = APP_ALIASES.get(left_compact, left_text)
    right_name = APP_ALIASES.get(right_compact, right_text)
    return compact_app_alias(left_name) == compact_app_alias(right_name)


def _query_is_app_identity(value: Any, target: Mapping[str, Any]) -> bool:
    query = str(value or "").strip()
    app_name = str(target.get("app_name") or "").strip()
    return bool(query and app_name and _app_identity_matches(query, app_name))


def _query_is_app_selection_scope(
    value: Any,
    target: Mapping[str, Any],
) -> bool:
    """Identify a discovery selector without treating it as an in-app query."""

    query = str(value or "").strip()
    selection_source = str(target.get("selection_source") or "").strip()
    app_name = str(target.get("app_name") or "").strip()
    if not query or selection_source not in {
        "desktop.list_apps",
        "desktop.running_apps",
    }:
        return False
    return bool(
        app_name.startswith(f"<selected app from {selection_source}")
        or not app_name
        or not _app_identity_matches(query, app_name)
    )


def _query_or_app_is_identity(
    key: str,
    value: Any,
    target: Mapping[str, Any],
) -> bool:
    return key == "app_name" or (
        key == "query" and _query_is_app_identity(value, target)
    )


def _selection_sources_equivalent(
    expected: Any,
    observed: Any,
    expected_target: Mapping[str, Any],
    observed_target: Mapping[str, Any],
) -> bool:
    expected_source = str(expected or "").strip()
    observed_source = str(observed or "").strip()
    if expected_source == observed_source:
        return True
    discovery_sources = {
        "desktop.list_apps",
        "desktop.running_apps",
    }
    if "direct_app_name" not in {expected_source, observed_source}:
        return False
    if not ({expected_source, observed_source} & discovery_sources):
        return False
    expected_app = str(expected_target.get("app_name") or "").strip()
    observed_app = str(observed_target.get("app_name") or "").strip()
    if not expected_app or not observed_app:
        return False
    if expected_app.startswith("<selected app from ") or observed_app.startswith(
        "<selected app from "
    ):
        return False
    return _app_identity_matches(expected_app, observed_app)


def _value_matches(expected: Any, observed: Any) -> bool:
    if isinstance(expected, Mapping):
        return isinstance(observed, Mapping) and all(
            key in observed and _value_matches(value, observed[key])
            for key, value in expected.items()
        )
    if isinstance(expected, (list, tuple)):
        return isinstance(observed, (list, tuple)) and len(expected) == len(
            observed
        ) and all(
            _value_matches(left, right)
            for left, right in zip(expected, observed)
        )
    if isinstance(expected, str) and isinstance(observed, str):
        return " ".join(expected.split()).casefold() == " ".join(
            observed.split()
        ).casefold()
    return expected == observed


__all__ = [
    "action_target_matches",
    "bind_planned_action_target",
    "canonical_action_name",
    "canonical_action_target",
]
