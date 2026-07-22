"""Compatibility bridge between canonical recovery and legacy replans."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from typing import Any

from apps.shell.agent.runtime.event_scopes import (
    runtime_progress_base_event_type,
    runtime_replan_base_event_type,
)
from apps.shell.agent.runtime.recovery import RecoveryPlan
from apps.shell.agent.runtime.tool_capabilities import capability_ids_for_tool


class RecoveryOwnershipStatus(str, Enum):
    """Whether the coordinator may own a matching legacy replan."""

    UNRELATED = "unrelated"
    CLAIMABLE = "claimable"
    ALREADY_HANDLED = "already_handled"
    CONFLICT = "conflict"


@dataclass(frozen=True, slots=True)
class LegacyReplanOwnership:
    """One source-correlated legacy replan ownership decision."""

    status: RecoveryOwnershipStatus
    request_id: str = ""
    action_id: str = ""

    @property
    def coordinator_may_execute(self) -> bool:
        return self.status in {
            RecoveryOwnershipStatus.UNRELATED,
            RecoveryOwnershipStatus.CLAIMABLE,
        }

    def event_fields(self) -> dict[str, str]:
        if self.status is not RecoveryOwnershipStatus.CLAIMABLE:
            return {}
        fields = {"replan_request_id": self.request_id}
        if self.action_id:
            fields["replan_recovery_action_id"] = self.action_id
        return fields


def resolve_legacy_replan_ownership(
    timeline: Sequence[Mapping[str, Any]],
    *,
    source_tool_call_id: str,
    source_tool_name: str,
    plan: RecoveryPlan,
) -> LegacyReplanOwnership:
    """Claim only an unstarted replan produced by the exact source attempt."""

    call_id = str(source_tool_call_id or "").strip()
    tool_name = str(source_tool_name or "").strip()
    if not call_id or not tool_name:
        return LegacyReplanOwnership(RecoveryOwnershipStatus.UNRELATED)

    candidates: list[tuple[int, Mapping[str, Any]]] = []
    for index, event in enumerate(timeline):
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        if runtime_replan_base_event_type(event_type) != "agent.replan.requested":
            continue
        payload = _event_payload(event)
        if str(payload.get("source") or "").strip() != "runtime_tool_request_runner":
            continue
        if str(payload.get("source_tool_call_id") or "").strip() != call_id:
            continue
        if str(payload.get("source_tool_name") or "").strip() != tool_name:
            continue
        candidates.append((index, payload))

    if not candidates:
        return LegacyReplanOwnership(RecoveryOwnershipStatus.UNRELATED)
    if len(candidates) != 1:
        return LegacyReplanOwnership(RecoveryOwnershipStatus.CONFLICT)
    candidate_index, candidate_payload = candidates[0]
    request_id = str(candidate_payload.get("request_id") or "").strip()
    if not request_id:
        return LegacyReplanOwnership(RecoveryOwnershipStatus.UNRELATED)
    match_status, action_ids = _matching_recovery_action_ids(
        candidate_payload,
        plan,
        request_id=request_id,
    )
    if match_status is RecoveryOwnershipStatus.CONFLICT:
        return LegacyReplanOwnership(
            RecoveryOwnershipStatus.CONFLICT,
            request_id=request_id,
        )
    action_id = action_ids[0] if len(action_ids) == 1 else ""
    if match_status is RecoveryOwnershipStatus.CLAIMABLE and _replan_has_started(
        timeline[candidate_index + 1 :],
        request_id=request_id,
        action_id=action_id,
    ):
        return LegacyReplanOwnership(
            RecoveryOwnershipStatus.ALREADY_HANDLED,
            request_id=request_id,
            action_id=action_id,
        )
    if match_status is RecoveryOwnershipStatus.UNRELATED:
        return LegacyReplanOwnership(RecoveryOwnershipStatus.UNRELATED)
    return LegacyReplanOwnership(
        RecoveryOwnershipStatus.CLAIMABLE,
        request_id=request_id,
        action_id=action_id,
    )


def _event_payload(event: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = event.get("payload")
    return payload if isinstance(payload, Mapping) else event


def _matching_recovery_action_ids(
    payload: Mapping[str, Any],
    plan: RecoveryPlan,
    *,
    request_id: str,
) -> tuple[RecoveryOwnershipStatus, tuple[str, ...]]:
    actions = payload.get("recovery_actions")
    if not isinstance(actions, list):
        metadata = payload.get("metadata")
        actions = metadata.get("recovery_actions") if isinstance(metadata, Mapping) else None
    if not isinstance(actions, list):
        return RecoveryOwnershipStatus.UNRELATED, ()

    expected_tool = _coordinator_discovery_tool(plan)
    if expected_tool:
        matches = _recovery_action_ids_for_tool(
            actions,
            expected_tool=expected_tool,
            request_id=request_id,
        )
        if len(matches) > 1:
            return RecoveryOwnershipStatus.CONFLICT, ()
        if matches:
            if len(actions) == 1 or _is_exact_app_discovery_legacy_chain(
                payload,
                actions,
                expected_tool=expected_tool,
            ):
                return RecoveryOwnershipStatus.CLAIMABLE, matches
            return RecoveryOwnershipStatus.CONFLICT, ()
        if expected_tool == "desktop.list_apps" and _is_exact_app_not_found_legacy_chain(
            payload,
            actions,
        ):
            # Old app-not-found replans contain only foreground actions. Claiming the
            # request (without one action id) prevents that obsolete chain from starting.
            return RecoveryOwnershipStatus.CLAIMABLE, ()
        return RecoveryOwnershipStatus.UNRELATED, ()

    required = set(plan.required_capabilities)
    matches: list[str] = []
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping):
            continue
        tool_name = str(action.get("tool") or action.get("tool_name") or "").strip()
        if not tool_name or not required.issubset(capability_ids_for_tool(tool_name)):
            continue
        action_id = str(
            action.get("action_id")
            or action.get("id")
            or f"{request_id}:action:{index + 1}:{tool_name}"
        ).strip()
        if action_id:
            matches.append(action_id)
    if len(matches) > 1:
        return RecoveryOwnershipStatus.CONFLICT, ()
    if matches:
        return RecoveryOwnershipStatus.CLAIMABLE, tuple(matches)
    return RecoveryOwnershipStatus.UNRELATED, ()


def _coordinator_discovery_tool(plan: RecoveryPlan) -> str:
    contract = (
        plan.strategy_id,
        plan.action,
        plan.recovery_hint,
        tuple(plan.required_capabilities),
        plan.source_status.value,
    )
    contracts = {
        (
            "resolve-file-location",
            "resolve_file_location",
            "file_resolution_failed",
            ("file.workspace_read",),
            "failed",
        ): "workspace.list",
        (
            "resolve-app-identity",
            "resolve_app_identity",
            "app_resolution_failed",
            ("desktop.app_discovery",),
            "failed",
        ): "desktop.list_apps",
    }
    return contracts.get(contract, "")


def _recovery_action_ids_for_tool(
    actions: Sequence[Any],
    *,
    expected_tool: str,
    request_id: str,
) -> tuple[str, ...]:
    matches: list[str] = []
    for index, action in enumerate(actions):
        if not isinstance(action, Mapping):
            continue
        tool_name = str(action.get("tool") or action.get("tool_name") or "").strip()
        if tool_name != expected_tool:
            continue
        action_id = str(
            action.get("action_id")
            or action.get("id")
            or f"{request_id}:action:{index + 1}:{tool_name}"
        ).strip()
        if action_id:
            matches.append(action_id)
    return tuple(matches)


def _is_exact_app_discovery_legacy_chain(
    payload: Mapping[str, Any],
    actions: Sequence[Any],
    *,
    expected_tool: str,
) -> bool:
    if expected_tool != "desktop.list_apps":
        return False
    source_tool = str(payload.get("source_tool_name") or "").strip()
    query = _legacy_app_query(payload)
    if source_tool not in {"app.open", "desktop.open_app"} or not query:
        return False
    return _actions_match(
        actions,
        (
            ("desktop.list_apps", {"query": query, "limit": 20}),
            ("app.open", {"app_name": query}),
            ("desktop.active_window", {}),
        ),
    )


def _is_exact_app_not_found_legacy_chain(
    payload: Mapping[str, Any],
    actions: Sequence[Any],
) -> bool:
    source_tool = str(payload.get("source_tool_name") or "").strip()
    query = _legacy_app_query(payload)
    if not query:
        return False
    if source_tool in {"app.open", "desktop.open_app"}:
        return _actions_match(
            actions,
            (
                ("desktop.open_path", {"path": "/Applications"}),
                ("app.open", {"app_name": "App Store"}),
            ),
            permission_target="app_not_found",
        )
    if source_tool in {"app.focus", "desktop.focus_app"}:
        return _actions_match(
            actions,
            (
                ("desktop.running_apps", {}),
                ("app.open", {"app_name": query}),
                ("desktop.active_window", {}),
                ("screen.capture", {"reason": "recover failed desktop tool"}),
            ),
        )
    return False


def _legacy_app_query(payload: Mapping[str, Any]) -> str:
    input_preview = payload.get("input_preview")
    if not isinstance(input_preview, Mapping):
        metadata = payload.get("metadata")
        input_preview = (
            metadata.get("input_preview") if isinstance(metadata, Mapping) else {}
        )
    if not isinstance(input_preview, Mapping):
        return ""
    return str(
        input_preview.get("app_name")
        or input_preview.get("target_app_name")
        or ""
    ).strip()


def _actions_match(
    actions: Sequence[Any],
    expected: Sequence[tuple[str, Mapping[str, Any]]],
    *,
    permission_target: str = "",
) -> bool:
    if len(actions) != len(expected):
        return False
    for action, (expected_tool, expected_input) in zip(actions, expected, strict=True):
        if not isinstance(action, Mapping):
            return False
        tool_name = str(action.get("tool") or action.get("tool_name") or "").strip()
        raw_input = action.get("input")
        if tool_name != expected_tool or not isinstance(raw_input, Mapping):
            return False
        if dict(raw_input) != dict(expected_input):
            return False
        if str(action.get("risk_level") or "").strip() not in {"", "low"}:
            return False
        if permission_target and str(action.get("permission_target") or "").strip() != (
            permission_target
        ):
            return False
    return True


def _replan_has_started(
    events: Sequence[Mapping[str, Any]],
    *,
    request_id: str,
    action_id: str,
) -> bool:
    blocking_event_types = {
        "agent.deferred_continuation.enqueued",
        "agent.recovery.planned",
        "agent.replan.recovery.updated",
        "agent.tool.call",
        "agent.tool.failed",
        "agent.tool.skipped",
    }
    for event in events:
        if not isinstance(event, Mapping):
            continue
        event_type = str(event.get("event") or event.get("event_type") or "").strip()
        base_event_type = runtime_progress_base_event_type(event_type)
        if base_event_type not in blocking_event_types:
            continue
        payload = _event_payload(event)
        if _container_references_replan(event, request_id=request_id, action_id=action_id):
            return True
        if payload is not event and _container_references_replan(
            payload,
            request_id=request_id,
            action_id=action_id,
        ):
            return True
    return False


def _container_references_replan(
    container: Mapping[str, Any],
    *,
    request_id: str,
    action_id: str,
) -> bool:
    referenced_request = str(
        container.get("replan_request_id") or container.get("request_id") or ""
    ).strip()
    if referenced_request == request_id:
        return True
    if action_id:
        referenced_action = str(
            container.get("replan_recovery_action_id") or container.get("action_id") or ""
        ).strip()
        if referenced_action == action_id:
            return True
        raw_action_ids = container.get("replan_recovery_action_ids")
        if isinstance(raw_action_ids, (list, tuple, set, frozenset)) and action_id in {
            str(value).strip() for value in raw_action_ids
        }:
            return True
    return False


__all__ = [
    "LegacyReplanOwnership",
    "RecoveryOwnershipStatus",
    "resolve_legacy_replan_ownership",
]
