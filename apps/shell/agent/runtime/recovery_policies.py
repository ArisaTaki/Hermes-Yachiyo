"""Capability-level recovery policy catalog for canonical tool outcomes."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from pathlib import PurePosixPath
from typing import Any

from apps.shell.agent.runtime.cua_background_provider import CUA_BACKGROUND_PROVIDER_KIND
from apps.shell.agent.runtime.event_scopes import runtime_event_payload
from apps.shell.agent.runtime.events import (
    RUNTIME_EXECUTION_PROVENANCE_KEY,
    RUNTIME_EXECUTION_PROVENANCE_VERSION,
    RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE,
)
from apps.shell.agent.runtime.recovery import (
    CapabilityRecoveryStrategy,
    RecoveryContext,
    RecoveryCoordinator,
    RecoveryPlan,
)
from apps.shell.agent.runtime.tool_capabilities import (
    available_capability_ids,
    capability_ids_for_tool,
    known_capability_ids,
)
from apps.shell.agent.runtime.tool_outcomes import (
    OutcomeStatus,
    ToolOutcome,
    from_tool_result,
)

_ENTITY_MISSING_REASONS = frozenset({"no_match", "not_found"})
_ENTITY_ALIAS_HINT = "entity_not_found"
_FILE_READ_TOOLS = frozenset({"workspace.read", "fs.read_file", "file.read"})
_FILE_RESOLUTION_HINT = "file_resolution_failed"
_FILE_RESOLUTION_STRATEGY_ID = "resolve-file-location"
_FILE_RESOLUTION_ACTION = "resolve_file_location"
_FILE_RESOLUTION_CAPABILITIES = ("file.workspace_read",)
_FILE_RESOLUTION_DISCOVERY_TOOL = "workspace.list"
_FILE_MISSING_ERROR = "路径不存在"
_FILE_MISSING_HINT = "请先用 workspace.list 查看父目录，确认要读取的文件相对路径。"
_FILE_DIRECTORY_ERROR = "workspace.read 只能读取文件"
_FILE_DIRECTORY_HINT = (
    "这是一个目录；请改用 workspace.list 查看目录内容，"
    "或选择目录中的具体文件再读取。"
)
_APP_CONTROL_TOOLS = frozenset(
    {"app.open", "desktop.open_app", "app.focus", "desktop.focus_app"}
)
_APP_FOCUS_TOOLS = frozenset({"app.focus", "desktop.focus_app"})
_APP_RESOLUTION_HINT = "app_resolution_failed"
_APP_RESOLUTION_STRATEGY_ID = "resolve-app-identity"
_APP_RESOLUTION_ACTION = "resolve_app_identity"
_APP_RESOLUTION_CAPABILITIES = ("desktop.app_discovery",)
_APP_RESOLUTION_DISCOVERY_TOOL = "desktop.list_apps"
_BACKGROUND_WINDOW_SOURCE_TOOLS = frozenset({"app.open", "desktop.open_app"})
_BACKGROUND_WINDOW_HINT = "materialize_background_window"
_BACKGROUND_WINDOW_STRATEGY_ID = "materialize-background-window"
_BACKGROUND_WINDOW_ACTION = "materialize_background_window"
_BACKGROUND_WINDOW_SOURCE_CAPABILITIES = ("desktop.app_control",)
_BACKGROUND_WINDOW_REQUIRED_CAPABILITIES = (
    "desktop.ui_operation",
    "desktop.app_discovery",
)
_BACKGROUND_WINDOW_RECOVERY_TOOLS = (
    "desktop.safe_shortcut",
    "desktop.read_ui",
)
_TERMINAL_TOOL_EVENT_TYPES = frozenset(
    {"agent.tool.call", "agent.tool.failed", "agent.tool.skipped"}
)


@dataclass(frozen=True, slots=True)
class FileResolutionSource:
    """Validated workspace-read miss and the directory safe to inspect."""

    path: str
    listing_path: str
    kind: str


@dataclass(frozen=True, slots=True)
class AppResolutionSource:
    """Validated explicit application-name miss."""

    query: str


@dataclass(frozen=True, slots=True)
class BackgroundWindowSource:
    """Trusted owned Cua process whose initial background window was unavailable."""

    pid: int


@dataclass(frozen=True, slots=True)
class RecoveryAssessment:
    """Canonical latest-attempt facts plus an optional automatic plan."""

    outcome: ToolOutcome
    plan: RecoveryPlan | None
    tool_call_id: str = ""

    @property
    def preserves_partial_result(self) -> bool:
        return self.outcome.status is OutcomeStatus.PARTIAL


def _default_coordinator() -> RecoveryCoordinator:
    return RecoveryCoordinator(
        (
            CapabilityRecoveryStrategy(
                strategy_id="resolve-entity-alias",
                action="resolve_entity_alias",
                trigger_capabilities=("media.playback",),
                trigger_hints=(_ENTITY_ALIAS_HINT,),
                required_capabilities=(
                    "browser.research",
                    "information.capture",
                    "media.playback",
                ),
                statuses=(OutcomeStatus.PARTIAL,),
                priority=100,
                metadata={
                    "evidence_required": True,
                    "max_attempts": 1,
                },
            ),
            CapabilityRecoveryStrategy(
                strategy_id=_BACKGROUND_WINDOW_STRATEGY_ID,
                action=_BACKGROUND_WINDOW_ACTION,
                trigger_capabilities=_BACKGROUND_WINDOW_SOURCE_CAPABILITIES,
                trigger_hints=(_BACKGROUND_WINDOW_HINT,),
                required_capabilities=_BACKGROUND_WINDOW_REQUIRED_CAPABILITIES,
                statuses=(OutcomeStatus.FAILED,),
                priority=95,
                metadata={"max_attempts": 1, "background_only": True},
            ),
            CapabilityRecoveryStrategy(
                strategy_id=_FILE_RESOLUTION_STRATEGY_ID,
                action=_FILE_RESOLUTION_ACTION,
                trigger_capabilities=_FILE_RESOLUTION_CAPABILITIES,
                trigger_hints=(_FILE_RESOLUTION_HINT,),
                required_capabilities=_FILE_RESOLUTION_CAPABILITIES,
                statuses=(OutcomeStatus.FAILED,),
                priority=90,
                metadata={"max_attempts": 1, "read_only": True},
            ),
            CapabilityRecoveryStrategy(
                strategy_id=_APP_RESOLUTION_STRATEGY_ID,
                action=_APP_RESOLUTION_ACTION,
                trigger_capabilities=("desktop.app_control",),
                trigger_hints=(_APP_RESOLUTION_HINT,),
                required_capabilities=_APP_RESOLUTION_CAPABILITIES,
                statuses=(OutcomeStatus.FAILED,),
                priority=80,
                metadata={"max_attempts": 1, "read_only": True},
            ),
        ),
        known_capabilities=known_capability_ids(),
        max_total_attempts=2,
        max_attempts_per_strategy=1,
    )


def _outcome_with_capability_hints(outcome: ToolOutcome) -> ToolOutcome:
    hints = list(outcome.recovery_hints)
    retryable = outcome.retryable
    if file_resolution_source(outcome) is not None:
        retryable = True
        if _FILE_RESOLUTION_HINT not in hints:
            hints.append(_FILE_RESOLUTION_HINT)
    if app_resolution_source(outcome) is not None:
        retryable = True
        if _APP_RESOLUTION_HINT not in hints:
            hints.append(_APP_RESOLUTION_HINT)
    if background_window_source(outcome) is not None:
        retryable = True
        if _BACKGROUND_WINDOW_HINT not in hints:
            hints.append(_BACKGROUND_WINDOW_HINT)
    if (
        outcome.status in {OutcomeStatus.FAILED, OutcomeStatus.PARTIAL}
        and outcome.reason in _ENTITY_MISSING_REASONS
        and "media.playback" in outcome.capabilities
        and _ENTITY_ALIAS_HINT not in hints
    ):
        hints.append(_ENTITY_ALIAS_HINT)
    return replace(outcome, retryable=retryable, recovery_hints=tuple(hints))


def file_resolution_source(outcome: ToolOutcome) -> FileResolutionSource | None:
    """Recognize only the workspace broker's exact read-miss contracts."""

    if (
        outcome.tool_name not in _FILE_READ_TOOLS
        or outcome.status is not OutcomeStatus.FAILED
        or outcome.capabilities != _FILE_RESOLUTION_CAPABILITIES
        or not isinstance(outcome.raw, Mapping)
    ):
        return None
    raw = outcome.raw
    path = str(raw.get("path") or "").strip()
    if raw.get("ok") is not False or not path or "\x00" in path:
        return None
    if raw.get("error") == _FILE_MISSING_ERROR and raw.get("hint") == _FILE_MISSING_HINT:
        parent = PurePosixPath(path).parent.as_posix()
        return FileResolutionSource(
            path=path,
            listing_path=parent or ".",
            kind="missing_path",
        )
    if (
        raw.get("error") == _FILE_DIRECTORY_ERROR
        and raw.get("hint") == _FILE_DIRECTORY_HINT
        and raw.get("suggested_tool") == "workspace.list"
    ):
        return FileResolutionSource(
            path=path,
            listing_path=path,
            kind="directory_read",
        )
    return None


def app_resolution_source(outcome: ToolOutcome) -> AppResolutionSource | None:
    """Recognize only explicit not-found results from app control adapters."""

    if (
        outcome.tool_name not in _APP_CONTROL_TOOLS
        or outcome.status is not OutcomeStatus.FAILED
        or outcome.capabilities != ("desktop.app_control",)
        or not isinstance(outcome.raw, Mapping)
    ):
        return None
    raw = outcome.raw
    provenance = raw.get(RUNTIME_EXECUTION_PROVENANCE_KEY)
    if not isinstance(provenance, Mapping) or (
        provenance.get("source") != RUNTIME_LOCAL_TOOL_BROKER_PROVENANCE_SOURCE
        or provenance.get("version") != RUNTIME_EXECUTION_PROVENANCE_VERSION
    ):
        return None
    if (
        raw.get("ok") is not False
        or raw.get("action") != outcome.tool_name
        or raw.get("permission_error") is not False
    ):
        return None
    direct_query = _explicit_app_not_found_query(raw, expected_action=outcome.tool_name)
    if direct_query:
        return AppResolutionSource(query=direct_query)
    if outcome.tool_name not in _APP_FOCUS_TOOLS or raw.get("fallback_used") is not False:
        return None
    fallback = raw.get("fallback_result")
    if not isinstance(fallback, Mapping):
        return None
    fallback_query = _explicit_app_not_found_query(fallback, expected_action="app.open")
    return AppResolutionSource(query=fallback_query) if fallback_query else None


def background_window_source(outcome: ToolOutcome) -> BackgroundWindowSource | None:
    """Recognize only the owned Cua background launch window-readiness contract."""

    if (
        outcome.tool_name not in _BACKGROUND_WINDOW_SOURCE_TOOLS
        or outcome.status is not OutcomeStatus.FAILED
        or not outcome.retryable
        or outcome.capabilities != _BACKGROUND_WINDOW_SOURCE_CAPABILITIES
        or not isinstance(outcome.raw, Mapping)
    ):
        return None
    raw = outcome.raw
    pid = _positive_int(raw.get("pid"))
    if (
        raw.get("ok") is not False
        or raw.get("action") != outcome.tool_name
        or raw.get("error") != "cua_background_window_not_ready"
        or raw.get("agent_owned_target") is not True
        or raw.get("self_activation_suppressed") is not True
        or raw.get("foreground_takeover_detected") is True
        or any(
            raw.get(key) is True
            for key in (
                "fallback_used",
                "foreground_fallback",
                "foreground_fallback_used",
            )
        )
        or pid is None
        or not _is_safe_cua_background_transport(
            raw.get("desktop_execution_provider_transport")
        )
    ):
        return None
    return BackgroundWindowSource(pid=pid)


def background_window_runtime_recovery_tools(
    outcome: ToolOutcome,
) -> tuple[str, ...]:
    """Return the fixed private tool grant for one exact owned-window failure.

    This is a Runtime planning grant, not an addition to the request/model
    allowlist.  The execution port independently admits this exact pair only
    after GoalContract lineage and subgoal-budget validation.
    """

    return (
        _BACKGROUND_WINDOW_RECOVERY_TOOLS
        if background_window_source(outcome) is not None
        else ()
    )


def _positive_int(value: Any) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value > 0 else None


def _is_safe_cua_background_transport(value: Any) -> bool:
    if not isinstance(value, Mapping):
        return False
    return bool(
        value.get("provider_kind") == CUA_BACKGROUND_PROVIDER_KIND
        and value.get("delivery_mode") == "background"
        and value.get("foreground_takeover_required") is False
        and value.get("foreground_takeover_detected") is not True
    )


def _explicit_app_not_found_query(
    payload: Mapping[str, Any],
    *,
    expected_action: str,
) -> str:
    data = payload.get("data")
    if (
        payload.get("ok") is not False
        or payload.get("action") != expected_action
        or payload.get("error_code") != "app_not_found"
        or payload.get("permission_error") is not False
        or payload.get("fallback_used") is not False
        or not isinstance(payload.get("error"), str)
        or not str(payload.get("error") or "").strip()
        or not isinstance(data, Mapping)
    ):
        return ""
    return str(data.get("app_name") or "").strip()


def assess_latest_tool_recovery(
    timeline: Sequence[Mapping[str, Any]],
    *,
    start_index: int,
    allowed_tools: Iterable[str],
    attempt_lineage: Iterable[RecoveryPlan] = (),
) -> RecoveryAssessment | None:
    """Assess only the latest terminal tool attempt in the current batch."""

    allowed_tool_ids = frozenset(
        str(tool_name or "").strip()
        for tool_name in allowed_tools
        if str(tool_name or "").strip()
    )
    safe_start = max(0, int(start_index or 0))
    latest_event: Mapping[str, Any] | None = None
    latest_event_index = -1
    for event_index in range(len(timeline) - 1, safe_start - 1, -1):
        event = timeline[event_index]
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        if event_type not in _TERMINAL_TOOL_EVENT_TYPES:
            continue
        latest_event = _terminal_tool_event_payload(event)
        if latest_event is None:
            return None
        latest_event_index = event_index
        break
    if latest_event is None:
        return None

    tool_name = str(latest_event.get("tool") or latest_event.get("detail") or "").strip()
    tool_call_id = str(latest_event.get("tool_call_id") or "").strip()
    result = latest_event.get("result")
    outcome = _outcome_with_capability_hints(
        from_tool_result(
            tool_name,
            result,
            capabilities=capability_ids_for_tool(tool_name),
        )
    )
    runtime_internal_tools = background_window_runtime_recovery_tools(outcome)
    context = RecoveryContext(
        outcome=outcome,
        available_capabilities=available_capability_ids(
            (*allowed_tool_ids, *runtime_internal_tools)
        ),
        attempt_lineage=tuple(attempt_lineage),
        scope_id=_recovery_scope_id(
            tool_name=tool_name,
            tool_call_id=tool_call_id,
            event_index=latest_event_index,
        ),
    )
    plan = _default_coordinator().plan(context)
    if plan is not None:
        required_recovery_tools = {
            _FILE_RESOLUTION_ACTION: _FILE_RESOLUTION_DISCOVERY_TOOL,
            _APP_RESOLUTION_ACTION: _APP_RESOLUTION_DISCOVERY_TOOL,
            _BACKGROUND_WINDOW_ACTION: _BACKGROUND_WINDOW_RECOVERY_TOOLS,
        }.get(plan.action)
        if required_recovery_tools:
            required_tool_ids = set(
                (required_recovery_tools,)
                if isinstance(required_recovery_tools, str)
                else required_recovery_tools
            )
            exact_private_background_grant = bool(
                plan.action == _BACKGROUND_WINDOW_ACTION
                and tuple(runtime_internal_tools)
                == _BACKGROUND_WINDOW_RECOVERY_TOOLS
                and required_tool_ids == set(runtime_internal_tools)
            )
            if (
                not exact_private_background_grant
                and not required_tool_ids.issubset(allowed_tool_ids)
            ):
                plan = None
    if plan is not None and plan.action in {
        _FILE_RESOLUTION_ACTION,
        _APP_RESOLUTION_ACTION,
        _BACKGROUND_WINDOW_ACTION,
    } and not tool_call_id:
        plan = None
    return RecoveryAssessment(
        outcome=outcome,
        plan=plan,
        tool_call_id=tool_call_id,
    )


def _terminal_tool_event_payload(
    event: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    """Normalize only canonical in-memory or persisted terminal tool events."""

    in_memory_event_type = str(event.get("event") or "").strip()
    if in_memory_event_type:
        payload: Mapping[str, Any] = event
    else:
        persisted_payload = event.get("payload")
        if not isinstance(persisted_payload, Mapping):
            return None
        payload = runtime_event_payload(event)
        if (
            not str(persisted_payload.get("tool") or "").strip()
            or not str(persisted_payload.get("tool_call_id") or "").strip()
            or "result" not in persisted_payload
        ):
            return None
    if (
        not str(payload.get("tool") or payload.get("detail") or "").strip()
        or "result" not in payload
    ):
        return None
    return payload


def recovery_attempt_lineage_from_timeline(
    timeline: Sequence[Mapping[str, Any]],
) -> tuple[RecoveryPlan, ...]:
    """Rebuild accepted internal recovery attempts for run-level budgeting."""

    lineage: list[RecoveryPlan] = []
    for event in timeline:
        payload = _internal_recovery_event_payload(event)
        if payload is None:
            continue
        raw_capabilities = payload.get("required_capabilities")
        if not isinstance(raw_capabilities, (list, tuple, set, frozenset)):
            continue
        try:
            lineage.append(
                RecoveryPlan(
                    strategy_id=str(payload.get("strategy_id") or "").strip(),
                    action=str(payload.get("action") or "").strip(),
                    recovery_hint=str(payload.get("recovery_hint") or "").strip(),
                    required_capabilities=tuple(
                        str(value).strip() for value in raw_capabilities if str(value).strip()
                    ),
                    source_status=OutcomeStatus(str(payload.get("source_status") or "").strip()),
                    source_reason=str(payload.get("source_reason") or "").strip(),
                    scope_id=str(payload.get("scope_id") or "").strip(),
                )
            )
        except (TypeError, ValueError):
            continue
    return tuple(lineage)


def _internal_recovery_event_payload(
    event: Mapping[str, Any],
) -> Mapping[str, Any] | None:
    event_type = str(event.get("event") or event.get("event_type") or "").strip()
    if event_type != "agent.recovery.planned":
        return None
    nested_payload = event.get("payload")
    payload = nested_payload if isinstance(nested_payload, Mapping) else event
    visibility = str(event.get("visibility") or payload.get("visibility") or "").strip()
    return payload if visibility == "internal" else None


def _recovery_scope_id(
    *,
    tool_name: str,
    tool_call_id: str,
    event_index: int,
) -> str:
    stable_source = tool_call_id or f"event-index:{event_index}"
    source_identity = f"{tool_name}\0{stable_source}"
    return f"tool-attempt:{hashlib.sha256(source_identity.encode('utf-8')).hexdigest()[:24]}"


def plan_latest_tool_recovery(
    timeline: Sequence[Mapping[str, Any]],
    *,
    start_index: int,
    allowed_tools: Iterable[str],
    attempt_lineage: Iterable[RecoveryPlan] = (),
) -> RecoveryPlan | None:
    assessment = assess_latest_tool_recovery(
        timeline,
        start_index=start_index,
        allowed_tools=allowed_tools,
        attempt_lineage=attempt_lineage,
    )
    return assessment.plan if assessment is not None else None


__all__ = [
    "AppResolutionSource",
    "BackgroundWindowSource",
    "FileResolutionSource",
    "RecoveryAssessment",
    "app_resolution_source",
    "background_window_source",
    "background_window_runtime_recovery_tools",
    "assess_latest_tool_recovery",
    "file_resolution_source",
    "plan_latest_tool_recovery",
    "recovery_attempt_lineage_from_timeline",
]
