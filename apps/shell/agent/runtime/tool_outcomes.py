"""Canonical, application-agnostic outcomes for Agent tool execution."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from enum import Enum
from types import MappingProxyType
from typing import Any

from apps.shell.agent.runtime.dispatch_semantics import (
    is_semantic_safe_shortcut,
    semantic_safe_shortcut_effect,
)


class OutcomeStatus(str, Enum):
    """Runtime-level terminal state of one tool attempt."""

    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"
    ACTION_REQUIRED = "action_required"


class VerificationStatus(str, Enum):
    """Whether claimed postconditions are backed by tool evidence."""

    VERIFIED = "verified"
    UNVERIFIED = "unverified"
    FAILED = "failed"
    NOT_REQUIRED = "not_required"


_PARTIAL_SEMANTIC_MARKERS = frozenset({"incomplete", "no_match", "not_found", "partial"})
_FAILED_SEMANTIC_MARKERS = frozenset(
    {
        "blocked",
        "cancelled",
        "canceled",
        "denied",
        "error",
        "failed",
        "rejected",
        "unavailable",
    }
)
_SUCCESS_SEMANTIC_MARKERS = frozenset({"completed", "ok", "ready", "success", "succeeded"})
_MEDIA_PLAYBACK_STATE_ALIASES = {
    "not_found": "not_found",
    "no_match": "not_found",
    "not_running": "stopped",
    "pause": "paused",
    "paused": "paused",
    "play": "playing",
    "played": "playing",
    "playing": "playing",
    "stop": "stopped",
    "stopped": "stopped",
}


@dataclass(frozen=True)
class UserAction:
    """Sanitized description of a user gate, never the executable raw input."""

    required: bool
    kind: str
    targets: tuple[str, ...] = ()
    labels: tuple[str, ...] = ()

    def to_event_payload(self) -> dict[str, Any]:
        return {
            "required": self.required,
            "kind": self.kind,
            "targets": list(self.targets),
            "labels": list(self.labels),
        }


@dataclass(frozen=True)
class ToolOutcome:
    """Immutable canonical view over a provider-owned raw tool result."""

    tool_name: str
    capabilities: tuple[str, ...]
    status: OutcomeStatus
    reason: str
    retryable: bool
    effects: tuple[str, ...]
    verification: VerificationStatus
    user_action: UserAction | None
    recovery_hints: tuple[str, ...]
    provenance: Mapping[str, Any]
    raw: Any

    def to_event_payload(self) -> dict[str, Any]:
        """Return a JSON-safe projection without copying provider-owned raw data."""

        payload = {
            "tool": self.tool_name,
            "capabilities": list(self.capabilities),
            "status": self.status.value,
            "reason": self.reason,
            "retryable": self.retryable,
            "effects": list(self.effects),
            "verification": self.verification.value,
            "recovery_hints": list(self.recovery_hints),
            "provenance": dict(self.provenance),
        }
        if self.user_action is not None:
            payload["user_action"] = self.user_action.to_event_payload()
        return payload


def from_tool_result(
    tool_name: str,
    result: Any,
    capabilities: Iterable[str] = (),
) -> ToolOutcome:
    """Normalize one provider result while retaining the untouched raw value."""

    canonical_capabilities = tuple(
        dict.fromkeys(
            str(capability).strip() for capability in capabilities if str(capability).strip()
        )
    )
    clean_tool_name = str(tool_name).strip()
    nested = result.get("data") if isinstance(result, Mapping) else None
    task_result = nested if isinstance(nested, Mapping) else result
    effects = _effects_from_result(result, task_result)
    shortcut_effect = semantic_safe_shortcut_effect(clean_tool_name, result)
    if shortcut_effect and shortcut_effect not in effects:
        effects = (*effects, shortcut_effect)
    successful_permission_diagnostic = is_successful_permission_diagnostic_result(
        clean_tool_name,
        result,
    )
    diagnostic_user_action = (
        _permission_user_action(result, task_result)
        if successful_permission_diagnostic
        and _permission_advisory_present(result, task_result)
        else None
    )
    if not successful_permission_diagnostic and _permission_required(result, task_result):
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.ACTION_REQUIRED,
            reason="permission_required",
            retryable=False,
            effects=effects,
            verification=VerificationStatus.UNVERIFIED,
            user_action=_permission_user_action(result, task_result),
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    if not successful_permission_diagnostic and _action_required(result, task_result):
        action_kind = "approval" if _approval_required(result, task_result) else "action"
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.ACTION_REQUIRED,
            reason=_reason_from_candidates(
                result,
                task_result,
                default=("approval_required" if action_kind == "approval" else "action_required"),
            ),
            retryable=False,
            effects=effects,
            verification=VerificationStatus.UNVERIFIED,
            user_action=_generic_user_action(result, task_result, kind=action_kind),
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    if _verification_failed(result, task_result):
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.FAILED,
            reason="verification_failed",
            retryable=_explicit_retryable(result, task_result, default=True),
            effects=effects,
            verification=VerificationStatus.FAILED,
            user_action=None,
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    if _skipped(result, task_result):
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.SKIPPED,
            reason=_reason_from_candidates(result, task_result, default="skipped"),
            retryable=_explicit_retryable(result, task_result, default=True),
            effects=(),
            verification=VerificationStatus.NOT_REQUIRED,
            user_action=None,
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    semantic_marker = _semantic_marker(result, task_result)
    if semantic_marker in _PARTIAL_SEMANTIC_MARKERS:
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.PARTIAL,
            reason=_semantic_reason(result, task_result, default=semantic_marker),
            retryable=_explicit_retryable(result, task_result, default=True),
            effects=effects,
            verification=VerificationStatus.UNVERIFIED,
            user_action=None,
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    if semantic_marker in _FAILED_SEMANTIC_MARKERS:
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.FAILED,
            reason=_semantic_reason(result, task_result, default=semantic_marker),
            retryable=_explicit_retryable(result, task_result, default=False),
            effects=effects,
            verification=VerificationStatus.NOT_REQUIRED,
            user_action=None,
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    semantic_shortcut = is_semantic_safe_shortcut(clean_tool_name)
    raw_verification_passed = bool(
        media_playback_verification_passed(
            result,
            task_result,
            capabilities=canonical_capabilities,
        )
        if "media.playback" in canonical_capabilities
        else _verification_passed(result, task_result)
    )
    verification_passed = bool(raw_verification_passed and not semantic_shortcut)
    if (
        semantic_shortcut
        and raw_verification_passed
        and isinstance(result, Mapping)
        and result.get("ok") is True
    ):
        # Preserve one accepted source attempt so an exact correlated Runtime
        # verifier can attach Goal evidence to it, but never let the shortcut
        # provider's generic verification flag prove the semantic effect.
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.SUCCESS,
            reason="unverified_effect",
            retryable=True,
            effects=effects,
            verification=VerificationStatus.UNVERIFIED,
            user_action=None,
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    if (
        isinstance(result, Mapping)
        and (
            result.get("ok") is True
            or (result.get("ok") is not False and semantic_marker in _SUCCESS_SEMANTIC_MARKERS)
        )
        and effects
        and not verification_passed
    ):
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.PARTIAL,
            reason="unverified_effect",
            retryable=_explicit_retryable(result, task_result, default=True),
            effects=effects,
            verification=VerificationStatus.UNVERIFIED,
            user_action=None,
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    if isinstance(result, Mapping) and (
        result.get("ok") is True
        or (result.get("ok") is not False and semantic_marker in _SUCCESS_SEMANTIC_MARKERS)
    ):
        verified = verification_passed
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.SUCCESS,
            reason=_success_reason(result, task_result),
            retryable=False,
            effects=effects,
            verification=(
                VerificationStatus.VERIFIED if verified else VerificationStatus.NOT_REQUIRED
            ),
            user_action=diagnostic_user_action,
            recovery_hints=_recovery_hints(result, task_result),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    if isinstance(result, Mapping) and (
        result.get("ok") is False or result.get("error") not in (None, "")
    ):
        return ToolOutcome(
            tool_name=clean_tool_name,
            capabilities=canonical_capabilities,
            status=OutcomeStatus.FAILED,
            reason=_stable_reason(result, default="tool_error"),
            retryable=result.get("retryable") is True,
            effects=(),
            verification=VerificationStatus.NOT_REQUIRED,
            user_action=None,
            recovery_hints=_string_tuple(result.get("recovery_hints")),
            provenance=_provenance_from_result(result),
            raw=result,
        )
    return ToolOutcome(
        tool_name=clean_tool_name,
        capabilities=canonical_capabilities,
        status=OutcomeStatus.FAILED,
        reason=("unknown_result" if isinstance(result, Mapping) else "non_mapping_result"),
        retryable=False,
        effects=(),
        verification=VerificationStatus.NOT_REQUIRED,
        user_action=None,
        recovery_hints=(),
        provenance=MappingProxyType({}),
        raw=result,
    )


def _provenance_from_result(result: Any) -> Mapping[str, Any]:
    if not isinstance(result, Mapping):
        return MappingProxyType({})
    candidate = result.get("_runtime_execution_provenance")
    if not isinstance(candidate, Mapping):
        return MappingProxyType({})
    safe: dict[str, Any] = {}
    source = candidate.get("source")
    if isinstance(source, str) and source.strip():
        safe["source"] = source.strip()
    version = candidate.get("version")
    if isinstance(version, (int, float, str)) and not isinstance(version, bool):
        safe["version"] = version
    return MappingProxyType(safe)


def _stable_reason(result: Mapping[str, Any], *, default: str) -> str:
    for key in ("reason", "error_code", "code", "error"):
        value = result.get(key)
        if not isinstance(value, str):
            continue
        candidate = value.strip().lower().replace("-", "_").replace(".", "_")
        if (
            candidate
            and len(candidate) <= 80
            and all(character.isalnum() or character == "_" for character in candidate)
        ):
            return candidate
    return default


def _string_tuple(value: Any) -> tuple[str, ...]:
    items = value if isinstance(value, (list, tuple, set, frozenset)) else [value]
    return tuple(
        dict.fromkeys(str(item).strip() for item in items if isinstance(item, str) and item.strip())
    )


def is_permission_diagnostic_tool(tool_name: Any) -> bool:
    """Return whether the tool observes permission state instead of consuming it."""

    clean_name = str(tool_name or "").strip().lower()
    return clean_name.endswith((".permissions", ".permissions.verify"))


def is_successful_permission_diagnostic_result(tool_name: Any, result: Any) -> bool:
    """Separate a successful permission observation from an execution gate."""

    return bool(
        is_permission_diagnostic_tool(tool_name)
        and isinstance(result, Mapping)
        and result.get("ok") is True
        and result.get("approval_required") is not True
        and not _explicit_diagnostic_failure(result)
    )


def _explicit_diagnostic_failure(result: Mapping[str, Any]) -> bool:
    if any(result.get(key) not in (None, "", False) for key in ("error", "error_code")):
        return True
    failed_statuses = {
        "blocked",
        "cancelled",
        "canceled",
        "denied",
        "error",
        "failed",
        "rejected",
        "skipped",
        "unavailable",
        "verification_failed",
    }
    if str(result.get("status") or "").strip().lower() in failed_statuses:
        return True
    if result.get("verification_failed") is True:
        return True
    for candidate in (result, result.get("data")):
        if not isinstance(candidate, Mapping):
            continue
        diagnostic_status = str(candidate.get("diagnostic_status") or "").strip().lower()
        if diagnostic_status in failed_statuses:
            return True
    return False


def _permission_advisory_present(result: Any, task_result: Any) -> bool:
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("permission_error") is True:
            return True
        if any(
            candidate.get(key)
            for key in (
                "missing_permissions",
                "permission_targets",
                "recovery_actions",
            )
        ):
            return True
        if candidate.get("user_action_required") is True:
            return True
        if str(candidate.get("status") or "").strip().lower() == "permission_required":
            return True
    return False


def _permission_required(result: Any, task_result: Any) -> bool:
    successful_fallback = (
        isinstance(result, Mapping)
        and result.get("ok") is True
        and result.get("fallback_used") is True
        and result.get("permission_error") is not True
    )
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("permission_error") is True:
            return True
        if _string_tuple(candidate.get("missing_permissions")) and not successful_fallback:
            return True
        status = str(candidate.get("status") or "").strip().lower()
        if status == "permission_required":
            return True
    return False


def _permission_user_action(result: Any, task_result: Any) -> UserAction:
    targets: list[str] = []
    labels: list[str] = []
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        for key in ("missing_permissions", "permission_targets"):
            targets.extend(_string_tuple(candidate.get(key)))
        actions = candidate.get("recovery_actions")
        if isinstance(actions, (list, tuple)):
            labels.extend(
                str(action.get("label") or "").strip()
                for action in actions
                if isinstance(action, Mapping) and str(action.get("label") or "").strip()
            )
    return UserAction(
        required=True,
        kind="permission",
        targets=tuple(dict.fromkeys(targets)),
        labels=tuple(dict.fromkeys(labels)),
    )


def _action_required(result: Any, task_result: Any) -> bool:
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("user_action_required") is True:
            return True
        if candidate.get("approval_required") is True:
            return True
        status = str(candidate.get("status") or "").strip().lower()
        if status in {"action_required", "approval_required"}:
            return True
    return False


def _approval_required(result: Any, task_result: Any) -> bool:
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("approval_required") is True:
            return True
        if str(candidate.get("status") or "").strip().lower() == "approval_required":
            return True
    return False


def _generic_user_action(
    result: Any,
    task_result: Any,
    *,
    kind: str,
) -> UserAction:
    targets: list[str] = []
    labels: list[str] = []
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        for key in ("action_targets", "user_action_targets", "approval_targets"):
            targets.extend(_string_tuple(candidate.get(key)))
        actions = candidate.get("recovery_actions")
        if isinstance(actions, (list, tuple)):
            labels.extend(
                str(action.get("label") or "").strip()
                for action in actions
                if isinstance(action, Mapping) and str(action.get("label") or "").strip()
            )
    return UserAction(
        required=True,
        kind=kind,
        targets=tuple(dict.fromkeys(targets)),
        labels=tuple(dict.fromkeys(labels)),
    )


def _recovery_hints(result: Any, task_result: Any) -> tuple[str, ...]:
    hints: list[str] = []
    for candidate in (task_result, result):
        if isinstance(candidate, Mapping):
            hints.extend(_string_tuple(candidate.get("recovery_hints")))
    return tuple(dict.fromkeys(hints))


def _verification_failed(result: Any, task_result: Any) -> bool:
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("verification_failed") is True:
            return True
        if str(candidate.get("status") or "").strip().lower() == "verification_failed":
            return True
        verification = candidate.get("verification")
        if isinstance(verification, Mapping):
            status = str(verification.get("status") or "").strip().lower()
            if status in {"failed", "failure", "verification_failed"}:
                return True
    return False


def _effects_from_result(result: Any, task_result: Any) -> tuple[str, ...]:
    effects: list[str] = []
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        for key in ("effects", "side_effects"):
            effects.extend(_string_tuple(candidate.get(key)))
    return tuple(dict.fromkeys(effects))


def _explicit_retryable(result: Any, task_result: Any, *, default: bool) -> bool:
    for candidate in (task_result, result):
        if isinstance(candidate, Mapping) and isinstance(candidate.get("retryable"), bool):
            return bool(candidate["retryable"])
    return default


def _skipped(result: Any, task_result: Any) -> bool:
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        if candidate.get("skipped") is True:
            return True
        if str(candidate.get("status") or "").strip().lower() == "skipped":
            return True
    return False


def _reason_from_candidates(result: Any, task_result: Any, *, default: str) -> str:
    for candidate in (task_result, result):
        if isinstance(candidate, Mapping):
            reason = _stable_reason(candidate, default="")
            if reason:
                return reason
    return default


def _verification_passed(result: Any, task_result: Any) -> bool:
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        for key, value in candidate.items():
            if value is True and (
                str(key) in {"verified", "verification_passed", "postcondition_verified"}
                or str(key).endswith("_verified")
            ):
                return True
        verification = candidate.get("verification")
        if isinstance(verification, Mapping):
            if verification.get("verified") is True or verification.get("passed") is True:
                return True
            status = str(verification.get("status") or "").strip().lower()
            if status in {"passed", "success", "verified"}:
                return True
    return False


def canonical_media_playback_state(result: Any, task_result: Any = None) -> str:
    """Normalize structured media provider state without trusting success booleans."""

    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        for key in ("playback_state", "player_state", "state", "status"):
            raw_state = str(candidate.get(key) or "").strip().casefold()
            state = _MEDIA_PLAYBACK_STATE_ALIASES.get(raw_state, "")
            if state:
                return state
    if any(
        candidate.get("playback_started") is True
        for candidate in (task_result, result)
        if isinstance(candidate, Mapping)
    ):
        return "playing"
    return ""


def media_track_change_verified(result: Any, task_result: Any = None) -> bool:
    """Require an explicit change receipt or correlated before/after identity."""

    sources: list[Mapping[str, Any]] = [
        candidate
        for candidate in (task_result, result)
        if isinstance(candidate, Mapping)
    ]
    for source in tuple(sources):
        for key in ("verification", "track_identity", "media_identity"):
            nested = source.get(key)
            if isinstance(nested, Mapping):
                sources.append(nested)
    if any(
        source.get(key) is True
        for source in sources
        for key in ("track_changed", "track_identity_changed")
    ):
        return True
    for before_key, after_key in (
        ("previous_track", "track"),
        ("previous_track", "current_track"),
        ("previous_track_id", "track_id"),
        ("previous_track_id", "current_track_id"),
        ("before_track", "after_track"),
        ("before_track_id", "after_track_id"),
    ):
        for source in sources:
            before = str(source.get(before_key) or "").strip().casefold()
            after = str(source.get(after_key) or "").strip().casefold()
            if before and after and before != after:
                return True
    return bool(
        any(source.get("track_identity_verified") is True for source in sources)
        and any(
            str(source.get(key) or "").strip()
            for source in sources
            for key in ("track", "current_track", "track_id", "current_track_id")
        )
        and any(
            source.get(key) is True
            for source in sources
            for key in ("postcondition_verified", "verification_passed", "verified")
        )
    )


def media_playback_verification_passed(
    result: Any,
    task_result: Any,
    *,
    capabilities: Iterable[str],
) -> bool:
    """Verify media effects from a read-after-write state receipt.

    This protocol is capability-scoped and application agnostic.  ``ok=true``
    or ``playback_ok=true`` alone is never enough; the provider must also
    report a compatible canonical player state and must not report an explicit
    unverified or identity-conflict marker.
    """

    if "media.playback" not in {
        str(capability or "").strip() for capability in capabilities
    }:
        return False
    sources = tuple(
        candidate
        for candidate in (task_result, result)
        if isinstance(candidate, Mapping)
    )
    if not sources:
        return False
    if any(
        source.get(key) is True
        for source in sources
        for key in (
            "playback_state_unverified",
            "playback_unverified",
            "identity_changed_before_play",
        )
    ):
        return False
    if any(
        key in source and source.get(key) is False
        for source in sources
        for key in (
            "catalog_match_verified",
            "open_ok",
            "playback_ok",
            "track_identity_verified",
        )
    ):
        return False
    state = canonical_media_playback_state(result, task_result)
    if not state or state == "not_found":
        return False
    explicit_state = any(
        _MEDIA_PLAYBACK_STATE_ALIASES.get(
            str(source.get(key) or "").strip().casefold(),
            "",
        )
        for source in sources
        for key in ("playback_state", "player_state", "state", "status")
    )
    explicit_verification = _verification_passed(result, task_result)
    control = ""
    for source in sources:
        for key in ("control", "requested_control", "media_control"):
            control = str(source.get(key) or "").strip().casefold()
            if control:
                break
        if control:
            break
    if control in {"play", "resume"}:
        return bool(state == "playing" and (explicit_state or explicit_verification))
    if control == "pause":
        return state == "paused"
    if control == "stop":
        return state == "stopped"
    if control in {"next", "previous"}:
        return media_track_change_verified(result, task_result)
    if control == "toggle":
        return state in {"playing", "paused", "stopped"}
    return bool(
        state == "playing"
        and (explicit_state or explicit_verification)
        and any(
            source.get("playback_ok") is True
            or source.get("playback_started") is True
            or source.get("track_identity_verified") is True
            for source in sources
        )
    )


def _success_reason(result: Any, task_result: Any) -> str:
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        for key in ("outcome", "status"):
            marker = str(candidate.get(key) or "").strip().lower()
            if marker in _SUCCESS_SEMANTIC_MARKERS:
                return marker
    return "ok"


def _semantic_marker(result: Any, task_result: Any) -> str:
    markers: list[str] = []
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        for key in ("status", "outcome"):
            marker = str(candidate.get(key) or "").strip().lower()
            if marker:
                markers.append(marker)
    # Providers often use a domain-specific status such as
    # ``playback_unverified`` together with the portable ``outcome=partial``.
    # Rank recognized terminal semantics across both fields before falling
    # back to an opaque provider status, otherwise ``ok=true`` can accidentally
    # promote an explicitly partial/failed operation to success.
    for marker_group in (
        _FAILED_SEMANTIC_MARKERS,
        _PARTIAL_SEMANTIC_MARKERS,
        _SUCCESS_SEMANTIC_MARKERS,
    ):
        for marker in markers:
            if marker in marker_group:
                return marker
    return markers[0] if markers else ""


def _semantic_reason(result: Any, task_result: Any, *, default: str) -> str:
    stable = _reason_from_candidates(result, task_result, default="")
    if stable:
        return stable
    for candidate in (task_result, result):
        if not isinstance(candidate, Mapping):
            continue
        status = str(candidate.get("status") or "").strip().lower()
        if status:
            return status
    return default
