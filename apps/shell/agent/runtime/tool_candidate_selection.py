"""Deterministic, Runtime-owned ranking for trusted tool candidates.

The selector never grants execution authority.  A candidate is eligible only
when it is allowed by the current run and has both a concrete schema and a
dispatch handler.  Capability constraints additionally use the explicit
capability registry; planner prefix classification is deliberately ignored.
"""

from __future__ import annotations

import re
from collections.abc import Iterable, Iterator, Mapping
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any

from apps.shell.agent.runtime.tool_capabilities import (
    action_ids_for_tool,
    capability_ids_for_tool,
)
from apps.shell.agent.tools.policy import (
    HIGH_RISK_AGENT_TOOLS,
    HIGH_RISK_DESKTOP_TOOL_NAMES,
    LOW_RISK_BROWSER_TOOL_NAMES,
    LOW_RISK_DESKTOP_TOOL_NAMES,
    MEDIUM_RISK_BROWSER_TOOL_NAMES,
    MEDIUM_RISK_DESKTOP_TOOL_NAMES,
    TOOL_DESCRIPTORS,
)
from apps.shell.agent.tools.registry import TOOL_DISPATCH_REGISTRY
from apps.shell.yachiyo_agent.capability_registry import CAPABILITY_DEFINITIONS

_READY_STATUSES = frozenset(
    {
        "available",
        "connected",
        "healthy",
        "ok",
        "provider_ready",
        "ready",
        "running",
        "sandbox_ready",
        "supported",
        "usable",
    }
)
_UNKNOWN_STATUSES = frozenset(
    {
        "",
        "deferred",
        "not_checked",
        "pending",
        "unchecked",
        "unknown",
        "unverified",
    }
)
_BLOCKED_STATUSES = frozenset(
    {
        "blocked",
        "denied",
        "disabled",
        "error",
        "failed",
        "missing",
        "not_available",
        "not_configured",
        "not_supported",
        "offline",
        "permission_denied",
        "provider_capability_mismatch",
        "sandbox_tool_not_supported",
        "tool_unavailable",
        "unavailable",
        "unhealthy",
        "unsupported",
    }
)

_READ_ONLY_TOOLS = frozenset(
    {
        "browser.current_page",
        "browser.extract",
        "browser.extract_text",
        "browser.open_url_and_extract_text",
        "browser.open_url_and_screenshot",
        "browser.screenshot",
        "browser.search",
        "clipboard.read",
        "desktop.active_window",
        "desktop.inspect_app",
        "desktop.list_apps",
        "desktop.list_windows",
        "desktop.permissions",
        "desktop.permissions.verify",
        "desktop.read_ui",
        "desktop.running_apps",
        "desktop.ui_elements",
        "desktop.verify",
        "desktop.windows",
        "file.read",
        "file.search",
        "fs.find_files",
        "fs.read_file",
        "future_task.list",
        "media.apple_music_status",
        "screen.capture",
        "skill.read",
        "workspace.list",
        "workspace.read",
    }
)

_GENERIC_FALLBACK_TOOLS = frozenset(
    {
        "browser.click",
        "browser.type_text",
        "desktop.click",
        "desktop.hotkey",
        "desktop.search_submit",
        "desktop.shortcut",
        "desktop.submit_foreground",
        "desktop.type",
        "desktop.type_text",
        "python.run",
        "terminal.run",
    }
)
_GENERIC_FALLBACK_PREFIXES = (
    "app.focus_and_",
    "app.open_and_",
    "desktop.safe_",
)
_FOREGROUND_TOOL_PREFIXES = (
    "app.focus_and_",
    "app.open_and_",
    "desktop.safe_",
)
_FOREGROUND_TOOLS = frozenset(
    {
        "app.focus",
        "app.focus_window",
        "app.open",
        "desktop.click",
        "desktop.click_ui_element",
        "desktop.focus_app",
        "desktop.hotkey",
        "desktop.open_app",
        "desktop.search_submit",
        "desktop.shortcut",
        "desktop.submit_foreground",
        "desktop.type",
        "desktop.type_into_ui_element",
        "desktop.type_text",
    }
)

_LOW_RISK_POLICY_TOOLS = frozenset(
    {*LOW_RISK_DESKTOP_TOOL_NAMES, *LOW_RISK_BROWSER_TOOL_NAMES}
)
_MEDIUM_RISK_POLICY_TOOLS = frozenset(
    {*MEDIUM_RISK_DESKTOP_TOOL_NAMES, *MEDIUM_RISK_BROWSER_TOOL_NAMES}
)
_HIGH_RISK_POLICY_TOOLS = frozenset(
    {*HIGH_RISK_AGENT_TOOLS, *HIGH_RISK_DESKTOP_TOOL_NAMES}
)
_RISK_RANK = {"none": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
_CAPABILITY_BY_ID = {
    definition.capability_id: definition for definition in CAPABILITY_DEFINITIONS
}
_STATIC_CAPABILITY_TOOL_NAMES = frozenset(
    tool_name
    for definition in CAPABILITY_DEFINITIONS
    for tool_name in definition.tools
)


@dataclass(frozen=True)
class ToolReadinessFacts:
    """Normalised, optional route/readiness evidence for one tool."""

    status: str = "unknown"
    configured: bool | None = None
    available: bool | None = None
    adapter_ready: bool | None = None
    health_checked: bool | None = None
    health_ok: bool | None = None
    blocked: bool | None = None
    blockers: tuple[str, ...] = ()
    structured: bool | None = None
    tool_native: bool | None = None
    read_only: bool | None = None
    background_safe: bool | None = None
    desktop_session_isolated: bool | None = None
    foreground_takeover_required: bool | None = None
    approval_required: bool | None = None
    risk_level: str = ""


@dataclass(frozen=True)
class RankedToolCandidate:
    """An eligible candidate plus its auditable deterministic rank facts."""

    tool_name: str
    capability_ids: tuple[str, ...]
    original_index: int
    readiness_status: str
    readiness_class: str
    blocked: bool
    structured: bool
    tool_native: bool
    read_only: bool
    background_safe: bool
    foreground_takeover_required: bool
    approval_required: bool
    risk_level: str
    rank_key: tuple[int, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ToolCandidateSelection:
    """Immutable ranking result consumed by Runtime planners and replanners."""

    selected_tool: str | None
    ranked_candidates: tuple[RankedToolCandidate, ...]
    alternatives: tuple[str, ...]
    blocked_tools: tuple[str, ...]
    reason_codes: tuple[str, ...]


@dataclass(frozen=True)
class ToolCandidateSelectionContext:
    """Context-local defaults used while migrating legacy planner call sites."""

    readiness_by_tool: tuple[tuple[str, ToolReadinessFacts], ...] = ()
    prefer_background: bool | None = None


_SELECTION_CONTEXT: ContextVar[ToolCandidateSelectionContext] = ContextVar(
    "agent_runtime_tool_candidate_selection_context",
    default=ToolCandidateSelectionContext(),
)


def _optional_bool(value: Any) -> bool | None:
    return value if isinstance(value, bool) else None


def _first_optional_bool(source: Mapping[str, Any], *keys: str) -> bool | None:
    for key in keys:
        value = _optional_bool(source.get(key))
        if value is not None:
            return value
    return None


def _normalise_status(value: Any) -> str:
    return re.sub(r"[\s.-]+", "_", str(value or "").strip().lower()) or "unknown"


def _normalise_action(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")


def _normalise_readiness(
    value: ToolReadinessFacts | Mapping[str, Any] | None,
) -> ToolReadinessFacts:
    if isinstance(value, ToolReadinessFacts):
        return value
    source = value if isinstance(value, Mapping) else {}
    raw_blockers = source.get("blockers")
    if isinstance(raw_blockers, (list, tuple, set, frozenset)):
        blockers = tuple(
            dict.fromkeys(
                text
                for item in raw_blockers
                if (text := str(item or "").strip())
            )
        )
    else:
        blocker = str(raw_blockers or "").strip()
        blockers = (blocker,) if blocker else ()
    return ToolReadinessFacts(
        status=_normalise_status(
            source.get("status")
            or source.get("readiness_status")
            or source.get("route_status")
            or source.get("provider_status")
        ),
        configured=_first_optional_bool(source, "configured", "provider_configured"),
        available=_first_optional_bool(source, "available", "provider_available"),
        adapter_ready=_first_optional_bool(source, "adapter_ready", "provider_adapter_ready"),
        health_checked=_first_optional_bool(source, "health_checked", "provider_health_checked"),
        health_ok=_first_optional_bool(source, "health_ok", "provider_health_ok"),
        blocked=_first_optional_bool(source, "blocked", "route_blocked"),
        blockers=blockers,
        structured=_first_optional_bool(source, "structured", "structured_tool"),
        tool_native=_first_optional_bool(source, "tool_native", "native_tool"),
        read_only=_first_optional_bool(source, "read_only", "observation_only"),
        background_safe=_first_optional_bool(
            source,
            "background_safe",
            "background_execution_safe",
        ),
        desktop_session_isolated=_first_optional_bool(source, "desktop_session_isolated"),
        foreground_takeover_required=_first_optional_bool(source, "foreground_takeover_required"),
        approval_required=_first_optional_bool(source, "approval_required"),
        risk_level=str(source.get("risk_level") or "").strip().lower(),
    )


def _normalise_readiness_map(
    value: Mapping[str, ToolReadinessFacts | Mapping[str, Any]] | None,
) -> dict[str, ToolReadinessFacts]:
    if not isinstance(value, Mapping):
        return {}
    return {
        name: _normalise_readiness(facts)
        for raw_name, facts in value.items()
        if (name := str(raw_name or "").strip())
    }


@contextmanager
def tool_candidate_selection_context(
    *,
    readiness_by_tool: Mapping[str, ToolReadinessFacts | Mapping[str, Any]] | None = None,
    prefer_background: bool | None = None,
) -> Iterator[ToolCandidateSelectionContext]:
    """Temporarily provide selection defaults without changing legacy signatures.

    Nested contexts overlay per-tool facts and are restored with the ContextVar
    token, so concurrent tasks and threads cannot leak route state into one
    another.
    """

    current = _SELECTION_CONTEXT.get()
    merged = dict(current.readiness_by_tool)
    merged.update(_normalise_readiness_map(readiness_by_tool))
    context = ToolCandidateSelectionContext(
        readiness_by_tool=tuple(merged.items()),
        prefer_background=(
            current.prefer_background if prefer_background is None else bool(prefer_background)
        ),
    )
    token = _SELECTION_CONTEXT.set(context)
    try:
        yield context
    finally:
        _SELECTION_CONTEXT.reset(token)


def current_tool_candidate_selection_context() -> ToolCandidateSelectionContext:
    """Return the immutable defaults active in the current execution context."""

    return _SELECTION_CONTEXT.get()


def _canonical_names(values: Iterable[str]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            name for value in values if (name := str(value or "").strip())
        )
    )


def _capability_declares_action(capability_id: str, action: str) -> bool:
    definition = _CAPABILITY_BY_ID.get(capability_id)
    if definition is None:
        return False
    declared = {
        _normalise_action(item)
        for item in (*definition.discovery_actions, *definition.execution_actions)
    }
    return action in declared


def _descriptor_action_values(tool_name: str) -> frozenset[str]:
    descriptor = TOOL_DESCRIPTORS.get(tool_name)
    properties = getattr(descriptor, "properties", None)
    action_schema = properties.get("action") if isinstance(properties, Mapping) else None
    raw_enum = action_schema.get("enum") if isinstance(action_schema, Mapping) else None
    if not isinstance(raw_enum, (list, tuple, set, frozenset)):
        return frozenset()
    return frozenset(_normalise_action(value) for value in raw_enum)


def _action_affinity(tool_name: str, action: str) -> int:
    if not action:
        return 0
    if action in {
        _normalise_action(action_id)
        for action_id in action_ids_for_tool(tool_name)
    }:
        return 0
    if action in _descriptor_action_values(tool_name):
        return 0
    tool_tokens = tuple(token for token in re.split(r"[._]+", tool_name.lower()) if token)
    action_tokens = tuple(token for token in action.split("_") if token)
    if action_tokens and all(token in tool_tokens for token in action_tokens):
        return 1
    return 2


def _readiness_class(facts: ToolReadinessFacts) -> str:
    status = _normalise_status(facts.status)
    explicitly_blocked = (
        status in _BLOCKED_STATUSES
        or facts.blocked is True
        or facts.configured is False
        or facts.available is False
        or facts.adapter_ready is False
        or facts.health_ok is False
        or bool(facts.blockers)
    )
    if explicitly_blocked:
        return "blocked"
    if status in _UNKNOWN_STATUSES:
        # "not_checked" is intentionally not converted into a failure, even
        # when partial route flags happen to be present.
        return "unknown"
    if status in _READY_STATUSES or facts.available is True or facts.adapter_ready is True:
        return "ready"
    return "unknown"


def _generic_fallback(tool_name: str) -> bool:
    return tool_name in _GENERIC_FALLBACK_TOOLS or tool_name.startswith(
        _GENERIC_FALLBACK_PREFIXES
    )


def _foreground_by_default(tool_name: str) -> bool:
    return tool_name in _FOREGROUND_TOOLS or tool_name.startswith(_FOREGROUND_TOOL_PREFIXES)


def _capability_risk_and_approval(
    capability_ids: tuple[str, ...],
    required_capability: str,
) -> tuple[str, bool]:
    if required_capability:
        definitions = tuple(
            definition
            for capability_id in (required_capability,)
            if (definition := _CAPABILITY_BY_ID.get(capability_id)) is not None
        )
    else:
        definitions = tuple(
            definition
            for capability_id in capability_ids
            if (definition := _CAPABILITY_BY_ID.get(capability_id)) is not None
        )
    if not definitions:
        return "medium", False
    risk = min(
        (str(definition.risk_level or "medium").strip().lower() for definition in definitions),
        key=lambda value: _RISK_RANK.get(value, _RISK_RANK["medium"]),
    )
    # Without an explicit capability, the least-privileged declared route is
    # the relevant default.  With one, this is simply that capability's gate.
    approval_required = all(definition.approval_required for definition in definitions)
    return risk, approval_required


def _tool_risk_and_approval(
    tool_name: str,
    capability_ids: tuple[str, ...],
    required_capability: str,
    facts: ToolReadinessFacts,
) -> tuple[str, bool]:
    risk, approval_required = _capability_risk_and_approval(
        capability_ids,
        required_capability,
    )
    if tool_name in _LOW_RISK_POLICY_TOOLS:
        risk, approval_required = "low", False
    if tool_name in _MEDIUM_RISK_POLICY_TOOLS:
        risk, approval_required = "medium", True
    if tool_name in _HIGH_RISK_POLICY_TOOLS:
        risk, approval_required = "high", True
    if facts.risk_level:
        risk = facts.risk_level if facts.risk_level in _RISK_RANK else "medium"
    if facts.approval_required is not None:
        approval_required = facts.approval_required
    return risk, approval_required


def _rank_candidate(
    tool_name: str,
    *,
    original_index: int,
    capability_ids: tuple[str, ...],
    required_capability: str,
    required_action: str,
    facts: ToolReadinessFacts,
    prefer_background: bool,
) -> RankedToolCandidate:
    readiness_class = _readiness_class(facts)
    generic_fallback = _generic_fallback(tool_name)
    structured = facts.structured if facts.structured is not None else not generic_fallback
    tool_native = facts.tool_native if facts.tool_native is not None else not generic_fallback
    read_only = facts.read_only if facts.read_only is not None else tool_name in _READ_ONLY_TOOLS
    foreground_takeover = (
        facts.foreground_takeover_required
        if facts.foreground_takeover_required is not None
        else _foreground_by_default(tool_name)
    )
    if facts.background_safe is not None:
        background_safe = facts.background_safe
    elif facts.desktop_session_isolated is True and not foreground_takeover:
        background_safe = True
    else:
        background_safe = not foreground_takeover
    risk_level, approval_required = _tool_risk_and_approval(
        tool_name,
        capability_ids,
        required_capability,
        facts,
    )
    readiness_rank = {"ready": 0, "unknown": 1, "blocked": 2}[readiness_class]
    action_rank = _action_affinity(tool_name, required_action)
    background_rank = 0 if background_safe else 1
    foreground_rank = 1 if foreground_takeover else 0
    # Read-only is a safety preference only for discovery/unspecified actions;
    # it must not outrank the adapter that can perform an effectful action.
    required_definition = _CAPABILITY_BY_ID.get(required_capability)
    action_is_effectful = bool(
        required_action
        and required_definition is not None
        and required_action
        in {_normalise_action(item) for item in required_definition.execution_actions}
    )
    read_only_rank = 0 if action_is_effectful or read_only else 1
    risk_rank = _RISK_RANK.get(risk_level, _RISK_RANK["medium"])
    rank_key = (
        readiness_rank,
        action_rank,
        0 if structured else 1,
        0 if tool_native else 1,
        *( (background_rank,) if prefer_background else () ),
        read_only_rank,
        foreground_rank,
        *( () if prefer_background else (background_rank,) ),
        1 if approval_required else 0,
        risk_rank,
        original_index,
    )
    reasons = [
        f"readiness_{readiness_class}",
        "structured" if structured else "generic_fallback",
        "tool_native" if tool_native else "non_native_fallback",
        "read_only" if read_only else "effectful",
        "background_safe" if background_safe else "background_not_proven",
        "foreground_takeover_required" if foreground_takeover else "no_foreground_takeover",
        "approval_required" if approval_required else "no_approval_required",
        f"risk_{risk_level}",
    ]
    if required_capability:
        reasons.append("required_capability_match")
    if required_action:
        reasons.append("exact_action_match" if action_rank < 2 else "capability_action_match")
    return RankedToolCandidate(
        tool_name=tool_name,
        capability_ids=capability_ids,
        original_index=original_index,
        readiness_status=_normalise_status(facts.status),
        readiness_class=readiness_class,
        blocked=readiness_class == "blocked",
        structured=structured,
        tool_native=tool_native,
        read_only=read_only,
        background_safe=background_safe,
        foreground_takeover_required=foreground_takeover,
        approval_required=approval_required,
        risk_level=risk_level,
        rank_key=rank_key,
        reason_codes=tuple(reasons),
    )


def select_tool_candidate(
    candidates: Iterable[str],
    allowed_tools: Iterable[str],
    *,
    required_capability: str | None = None,
    required_action: str | None = None,
    readiness_by_tool: Mapping[str, ToolReadinessFacts | Mapping[str, Any]] | None = None,
    prefer_background: bool | None = None,
) -> ToolCandidateSelection:
    """Rank trusted candidates without widening the current execution authority."""

    names = _canonical_names(candidates)
    allowed = frozenset(_canonical_names(allowed_tools))
    capability = str(required_capability or "").strip()
    action = _normalise_action(required_action)
    context = _SELECTION_CONTEXT.get()
    readiness = dict(context.readiness_by_tool)
    readiness.update(_normalise_readiness_map(readiness_by_tool))
    background_preference = (
        bool(context.prefer_background)
        if prefer_background is None
        else bool(prefer_background)
    )

    selection_reasons: list[str] = []

    def record(reason: str) -> None:
        if reason not in selection_reasons:
            selection_reasons.append(reason)

    eligible: list[RankedToolCandidate] = []
    for index, tool_name in enumerate(names):
        if tool_name not in allowed:
            record("candidate_not_allowed")
            continue
        if tool_name not in TOOL_DESCRIPTORS:
            record("candidate_missing_descriptor")
            continue
        if tool_name not in TOOL_DISPATCH_REGISTRY:
            record("candidate_missing_dispatch")
            continue
        capability_ids = capability_ids_for_tool(tool_name)
        if not capability_ids:
            record("candidate_missing_capability_authority")
            if capability:
                record("candidate_missing_required_capability")
            continue
        if capability and capability not in capability_ids:
            record("candidate_missing_required_capability")
            continue
        if action:
            action_capabilities = (capability,) if capability else capability_ids
            if not any(
                _capability_declares_action(capability_id, action)
                for capability_id in action_capabilities
            ):
                record("candidate_missing_required_action")
                continue
            # Static adapters inherit the action surface of their checked-in
            # capability definition. Dynamically registered adapters do not:
            # they must explicitly bind each action they are allowed to serve.
            # A capability-only plugin binding therefore cannot silently gain
            # execution authority for every action in that capability.
            if (
                tool_name not in _STATIC_CAPABILITY_TOOL_NAMES
                and action not in {
                    _normalise_action(action_id)
                    for action_id in action_ids_for_tool(tool_name)
                }
            ):
                record("candidate_missing_explicit_action_binding")
                continue
        eligible.append(
            _rank_candidate(
                tool_name,
                original_index=index,
                capability_ids=capability_ids,
                required_capability=capability,
                required_action=action,
                facts=readiness.get(tool_name, ToolReadinessFacts()),
                prefer_background=background_preference,
            )
        )

    ranked = tuple(sorted(eligible, key=lambda candidate: candidate.rank_key))
    selected_tool = ranked[0].tool_name if ranked else None
    alternatives = tuple(candidate.tool_name for candidate in ranked[1:])
    blocked_tools = tuple(candidate.tool_name for candidate in ranked if candidate.blocked)
    if not ranked:
        record("no_eligible_tools")
    else:
        selected = ranked[0]
        record(f"selected_{selected.readiness_class}_readiness")
        if blocked_tools and len(blocked_tools) == len(ranked):
            record("all_eligible_tools_blocked")
        if selected.blocked:
            record("selected_tool_blocked")
        if len(ranked) > 1 and ranked[0].rank_key[:-1] == ranked[1].rank_key[:-1]:
            record("stable_original_order_tiebreak")
    return ToolCandidateSelection(
        selected_tool=selected_tool,
        ranked_candidates=ranked,
        alternatives=alternatives,
        blocked_tools=blocked_tools,
        reason_codes=tuple(selection_reasons),
    )


def select_trusted_tool_candidate(
    candidates: Iterable[str],
    allowed_tools: Iterable[str],
    **kwargs: Any,
) -> ToolCandidateSelection:
    """Explicitly named alias for callers outside the legacy planner."""

    return select_tool_candidate(candidates, allowed_tools, **kwargs)


__all__ = [
    "RankedToolCandidate",
    "ToolCandidateSelection",
    "ToolCandidateSelectionContext",
    "ToolReadinessFacts",
    "current_tool_candidate_selection_context",
    "select_tool_candidate",
    "select_trusted_tool_candidate",
    "tool_candidate_selection_context",
]
