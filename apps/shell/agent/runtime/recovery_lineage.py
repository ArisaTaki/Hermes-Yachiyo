"""Process-private authority for binding recovery retries to a root goal."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from typing import Any

from apps.shell.agent.runtime.goal_contract import GoalContract


RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY = "_runtime_private_recovery_context"
RUNTIME_PRIVATE_RECOVERY_CONTEXT_VERSION = 1
RUNTIME_PRIVATE_RECOVERY_AUTHORITY = object()

RUNTIME_PRIVATE_REPLAN_CONTEXT_KEY = "_runtime_private_replan_context"
RUNTIME_PRIVATE_REPLAN_CONTEXT_VERSION = 1
RUNTIME_PRIVATE_REPLAN_AUTHORITY = object()

_REPLAN_BINDING_KEYS = (
    "run_id",
    "replan_request_id",
    "source_tool_call_id",
    "source_request_id",
    "source_plan_id",
    "source_step_id",
    "source_tool",
    "source_provider_kind",
    "source_provider_id",
    "goal_contract_id",
    "goal_criterion_id",
)


class RuntimeAuthorizedReplanPayload(dict[str, Any]):
    """JSON-safe live payload with authority outside its public mapping."""

    def __init__(
        self,
        payload: Mapping[str, Any],
        *,
        private_context: Mapping[str, Any],
    ) -> None:
        super().__init__(payload)
        self._private_context = private_context


def copy_live_replan_payload(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    """Copy a live payload without promoting private state to public keys."""

    public_payload = dict(payload)
    if not isinstance(payload, RuntimeAuthorizedReplanPayload):
        return public_payload
    private_context = getattr(payload, "_private_context", None)
    if not isinstance(private_context, Mapping):
        return public_payload
    return RuntimeAuthorizedReplanPayload(
        public_payload,
        private_context=private_context,
    )


_IDENTITY_KEYS = (
    "goal_contract_id",
    "goal_criterion_id",
    "goal_subgoal_id",
    "source_tool_call_id",
    "recovery_source_tool",
    "recovery_action",
    "recovery_scope_id",
    "tool_call_id",
)

_ROOT_RETURN_IDENTITY_KEYS = (
    "plan_id",
    "source_step_id",
    "recovery_suggested_tool",
)

_VERIFIER_REPAIR_IDENTITY_KEYS = (
    "root_source_tool_call_id",
    "root_source_step_id",
    "root_verifier_step_id",
    "root_plan_id",
    "recovery_origin_tool_call_id",
)

_RECOVERY_AUTHORITY_CLAIM_KEYS = frozenset(
    {
        "recovery_link_kind",
        "goal_contract_id",
        "goal_criterion_id",
        "goal_subgoal_id",
        "recovery_action",
        "recovery_scope_id",
        "replan_recovery_identity",
        "recovery_source_tool",
        "recovery_origin_tool_call_id",
        "root_source_tool_call_id",
        "root_source_step_id",
        "root_verifier_step_id",
        "root_plan_id",
        "recovery_suggested_tool",
        "recovery_context_trusted",
        RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY,
    }
)


def recovery_request_claims_runtime_authority(
    tool_request: Mapping[str, Any],
) -> bool:
    """Return whether a public request claims coordinator recovery lineage."""

    return any(key in tool_request for key in _RECOVERY_AUTHORITY_CLAIM_KEYS)


def canonical_replan_action_signature(
    tool_name: str,
    request_input: Mapping[str, Any],
    *,
    action_id: str = "",
) -> str:
    """Return a stable identity for one Runtime-authorized recovery effect."""

    clean_tool = str(tool_name or "").strip()
    if not clean_tool or not isinstance(request_input, Mapping):
        return ""
    try:
        canonical_input = json.dumps(
            dict(request_input),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
    except (TypeError, ValueError):
        return ""
    encoded = "\0".join(
        (clean_tool, canonical_input, str(action_id or "").strip())
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def mint_private_replan_context(
    *,
    binding: Mapping[str, Any],
    action_signatures: Sequence[str],
) -> dict[str, Any]:
    """Mint non-serializable authority for the exact in-process replan."""

    identity = {
        key: str(binding.get(key) or "").strip()
        for key in _REPLAN_BINDING_KEYS
    }
    signatures = tuple(
        dict.fromkeys(
            str(signature or "").strip()
            for signature in action_signatures
            if str(signature or "").strip()
        )
    )
    if any(not value for value in identity.values()) or not signatures:
        return {}
    return {
        "version": RUNTIME_PRIVATE_REPLAN_CONTEXT_VERSION,
        "_authority": RUNTIME_PRIVATE_REPLAN_AUTHORITY,
        **identity,
        "action_signatures": signatures,
    }


def trusted_private_replan_action_signatures(
    payload: Mapping[str, Any],
    *,
    binding: Mapping[str, Any],
) -> frozenset[str]:
    """Validate one live replan capability against every exact lineage field."""

    if not isinstance(payload, RuntimeAuthorizedReplanPayload):
        return frozenset()
    context = getattr(payload, "_private_context", None)
    if not isinstance(context, Mapping):
        return frozenset()
    if (
        context.get("_authority") is not RUNTIME_PRIVATE_REPLAN_AUTHORITY
        or context.get("version") != RUNTIME_PRIVATE_REPLAN_CONTEXT_VERSION
    ):
        return frozenset()
    for key in _REPLAN_BINDING_KEYS:
        expected = str(binding.get(key) or "").strip()
        if not expected or str(context.get(key) or "").strip() != expected:
            return frozenset()
    signatures = context.get("action_signatures")
    if (
        not isinstance(signatures, tuple)
        or not signatures
        or any(not isinstance(item, str) or not item for item in signatures)
    ):
        return frozenset()
    return frozenset(signatures)


def rehydrate_private_recovery_context(
    tool_request: Mapping[str, Any],
    timeline: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    goal_contract: GoalContract | None,
) -> dict[str, Any]:
    """Re-mint process authority for one exact persisted recovery request.

    Approval persistence retains only public lineage.  This function accepts
    that lineage only when the immutable Goal contract, validated Runtime
    subgoal, first terminal facts, and provider identity all still agree.
    """

    if not recovery_request_claims_runtime_authority(tool_request):
        return {}
    clean_run_id = str(run_id or "").strip()
    if (
        not clean_run_id
        or not isinstance(goal_contract, GoalContract)
        or goal_contract.run_id != clean_run_id
    ):
        return {}
    request = dict(tool_request)
    request.pop(RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY, None)
    request.pop("recovery_context_trusted", None)
    tool_name = str(request.get("tool") or request.get("tool_name") or "").strip()
    identity = {
        key: str(request.get(key) or "").strip()
        for key in (
            "goal_contract_id",
            "goal_criterion_id",
            "goal_subgoal_id",
            "source_tool_call_id",
            "recovery_source_tool",
            "recovery_action",
            "recovery_scope_id",
            "tool_call_id",
            "plan_id",
            "source_step_id",
            "recovery_suggested_tool",
            "root_source_tool_call_id",
            "root_source_step_id",
            "root_verifier_step_id",
            "root_plan_id",
            "recovery_origin_tool_call_id",
        )
    }
    if (
        not tool_name
        or any(not value for value in identity.values())
        or str(request.get("source") or "").strip()
        != "runtime_internal_recovery"
        or str(request.get("recovery_link_kind") or "").strip()
        != "coordinator_action"
        or request.get("root_goal_unchanged") is not True
        or identity["goal_contract_id"] != goal_contract.contract_id
        or identity["recovery_scope_id"]
        != str(request.get("replan_recovery_identity") or "").strip()
        or identity["plan_id"] != identity["root_plan_id"]
        or identity["source_step_id"] != identity["root_source_step_id"]
        or identity["recovery_suggested_tool"] != tool_name
    ):
        return {}
    criterion = goal_contract.criterion(identity["goal_criterion_id"])
    if (
        criterion is None
        or identity["root_source_step_id"] not in criterion.source_step_ids
        or identity["root_verifier_step_id"] not in criterion.verifier_step_ids
    ):
        return {}

    from apps.shell.agent.runtime import goal_runtime

    winners = _runtime_terminal_winners(
        timeline,
        run_id=clean_run_id,
        goal_contract=goal_contract,
    )
    root_event = winners.get(identity["root_source_tool_call_id"])
    failed_event = winners.get(identity["recovery_origin_tool_call_id"])
    root_result = _event_result(root_event)
    failed_result = _event_result(failed_event)
    if (
        root_event is None
        or failed_event is None
        or root_result.get("ok") is not True
        or failed_result.get("ok") is not False
        or str(root_event.get("plan_id") or "").strip()
        != identity["root_plan_id"]
        or str(failed_event.get("plan_id") or "").strip()
        != identity["root_plan_id"]
        or _event_step_id(root_event) != identity["root_source_step_id"]
        or _event_step_id(failed_event) != identity["root_verifier_step_id"]
        or not goal_runtime._runtime_owned_terminal_event(
            root_event,
            root_result,
            run_id=clean_run_id,
            plan_id=identity["root_plan_id"],
        )
        or not goal_runtime._runtime_owned_terminal_event(
            failed_event,
            failed_result,
            run_id=clean_run_id,
            plan_id=identity["root_plan_id"],
        )
    ):
        return {}
    root_provider = goal_runtime._runtime_execution_provider_identity(root_result)
    if (
        not root_provider
        or goal_runtime._runtime_execution_provider_identity(failed_result)
        != root_provider
    ):
        return {}

    assessment = goal_runtime.runtime_goal_assessment(goal_contract, timeline)
    subgoal = next(
        (
            item
            for item in assessment.subgoals
            if item.subgoal_id == identity["goal_subgoal_id"]
        ),
        None,
    )
    if (
        subgoal is None
        or subgoal.contract_id != goal_contract.contract_id
        or subgoal.criterion_id != identity["goal_criterion_id"]
        or subgoal.source_tool_call_id
        != identity["recovery_origin_tool_call_id"]
        or subgoal.action != identity["recovery_action"]
    ):
        return {}
    opener = _matching_subgoal_opener(
        timeline,
        run_id=clean_run_id,
        identity=identity,
        provider=root_provider,
    )
    if opener is None:
        return {}

    failed_tool = str(
        failed_event.get("tool") or failed_event.get("detail") or ""
    ).strip()
    source_call_id = identity["source_tool_call_id"]
    if source_call_id == identity["recovery_origin_tool_call_id"]:
        if identity["recovery_source_tool"] != failed_tool:
            return {}
    else:
        source_event = winners.get(source_call_id)
        source_result = _event_result(source_event)
        source_step_id = (
            _event_step_id(source_event)
            if isinstance(source_event, Mapping)
            else ""
        )
        dependencies = tuple(
            str(item or "").strip()
            for item in (
                request.get("depends_on")
                if isinstance(request.get("depends_on"), (list, tuple))
                else ()
            )
            if str(item or "").strip()
        )
        exact_source_lineage_keys = (
            "goal_contract_id",
            "goal_criterion_id",
            "goal_subgoal_id",
            "recovery_action",
            "recovery_scope_id",
        )
        optional_root_lineage_keys = (
            "root_source_tool_call_id",
            "root_source_step_id",
            "root_verifier_step_id",
            "root_plan_id",
            "recovery_origin_tool_call_id",
        )
        if (
            source_event is None
            or source_result.get("ok") is not True
            or source_event.get("recovery_context_trusted") is not True
            or str(source_event.get("source") or "").strip()
            != "runtime_internal_recovery"
            or source_event.get("root_goal_unchanged") is not True
            or str(source_event.get("replan_recovery_identity") or "").strip()
            != identity["recovery_scope_id"]
            or str(source_event.get("plan_id") or "").strip()
            != identity["root_plan_id"]
            or str(request.get("runtime_stage") or "").strip() != "verify"
            or str(request.get("runtime_role") or "").strip()
            != "verify_result"
            or _event_step_id(request) != identity["root_verifier_step_id"]
            or tool_name != identity["recovery_source_tool"]
            or tool_name != failed_tool
            or dependencies != (source_step_id,)
            or not source_step_id
            or str(request.get("replan_trigger") or "").strip()
            != "verification_failed"
            or str(request.get("replan_request_id") or "").strip()
            != str(source_event.get("replan_request_id") or "").strip()
            or goal_runtime._runtime_execution_provider_identity(source_result)
            != root_provider
            or not goal_runtime._runtime_owned_terminal_event(
                source_event,
                source_result,
                run_id=clean_run_id,
                plan_id=identity["root_plan_id"],
            )
            or any(
                str(source_event.get(key) or "").strip() != identity[key]
                for key in exact_source_lineage_keys
            )
            or any(
                str(source_event.get(key) or "").strip()
                and str(source_event.get(key) or "").strip() != identity[key]
                for key in optional_root_lineage_keys
            )
        ):
            return {}

    return {
        "version": RUNTIME_PRIVATE_RECOVERY_CONTEXT_VERSION,
        "_authority": RUNTIME_PRIVATE_RECOVERY_AUTHORITY,
        "run_id": clean_run_id,
        "return_to_root": True,
        "root_goal_unchanged": True,
        **identity,
    }


def _runtime_terminal_winners(
    timeline: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    goal_contract: GoalContract,
) -> dict[str, dict[str, Any]]:
    from apps.shell.agent.runtime import goal_runtime

    winners: dict[str, dict[str, Any]] = {}
    approval_pauses: dict[str, dict[str, Any]] = {}
    for raw_event in timeline:
        if not isinstance(raw_event, Mapping):
            continue
        event = _flatten_event(raw_event)
        if str(event.get("event") or event.get("event_type") or "").strip() not in {
            "agent.tool.call",
            "agent.tool.failed",
            "agent.tool.skipped",
        }:
            continue
        if str(event.get("run_id") or "").strip() != run_id:
            continue
        call_id = str(event.get("tool_call_id") or "").strip()
        result = _event_result(event)
        if not call_id or not result:
            continue
        if goal_runtime._nonterminal_tool_pause_event(event, result):
            if goal_runtime._explicit_approval_pause_event(event, result):
                approval_pauses.setdefault(call_id, event)
            continue
        if call_id in winners:
            continue
        pause = approval_pauses.get(call_id)
        if pause is not None and not goal_runtime._trusted_approval_terminal_after_pause(
            pause,
            event,
            result,
            contract=goal_contract,
        ):
            continue
        winners[call_id] = event
    return winners


def _matching_subgoal_opener(
    timeline: Sequence[Mapping[str, Any]],
    *,
    run_id: str,
    identity: Mapping[str, str],
    provider: Mapping[str, str],
) -> dict[str, Any] | None:
    for raw_event in timeline:
        if not isinstance(raw_event, Mapping):
            continue
        event = _flatten_event(raw_event)
        if (
            str(event.get("event") or event.get("event_type") or "").strip()
            != "agent.goal.subgoal.opened"
            or str(event.get("run_id") or "").strip() != run_id
            or str(event.get("status") or "").strip() != "opened"
            or str(event.get("visibility") or "").strip() != "internal"
            or str(event.get("source") or "").strip()
            != "runtime_goal_coordinator"
            or str(event.get("actor") or "").strip() != "native_runtime"
            or str(event.get("execution_authority") or "").strip()
            != "runtime_goal_coordinator"
        ):
            continue
        subgoal = event.get("subgoal")
        if not isinstance(subgoal, Mapping):
            try:
                subgoal = json.loads(str(event.get("subgoal_json") or ""))
            except (TypeError, ValueError, json.JSONDecodeError):
                subgoal = None
        if not isinstance(subgoal, Mapping):
            continue
        expected_event = {
            "contract_id": identity["goal_contract_id"],
            "criterion_id": identity["goal_criterion_id"],
            "source_tool_call_id": identity["recovery_origin_tool_call_id"],
            "recovery_origin_tool_call_id": identity[
                "recovery_origin_tool_call_id"
            ],
            "root_source_tool_call_id": identity["root_source_tool_call_id"],
            "root_source_step_id": identity["root_source_step_id"],
            "root_verifier_step_id": identity["root_verifier_step_id"],
            "root_plan_id": identity["root_plan_id"],
            "root_provider_kind": str(provider.get("provider_kind") or ""),
            "root_provider_id": str(provider.get("provider_id") or ""),
        }
        if any(
            str(event.get(key) or "").strip() != value
            for key, value in expected_event.items()
        ):
            continue
        if (
            str(subgoal.get("subgoal_id") or "").strip()
            != identity["goal_subgoal_id"]
            or str(subgoal.get("contract_id") or "").strip()
            != identity["goal_contract_id"]
            or str(subgoal.get("criterion_id") or "").strip()
            != identity["goal_criterion_id"]
            or str(subgoal.get("source_tool_call_id") or "").strip()
            != identity["recovery_origin_tool_call_id"]
            or str(subgoal.get("action") or "").strip()
            != identity["recovery_action"]
        ):
            continue
        return event
    return None


def _flatten_event(event: Mapping[str, Any]) -> dict[str, Any]:
    payload = event.get("payload")
    return (
        {**dict(payload), **dict(event)}
        if isinstance(payload, Mapping)
        else dict(event)
    )


def _event_result(event: Mapping[str, Any] | None) -> dict[str, Any]:
    if not isinstance(event, Mapping):
        return {}
    result = event.get("result")
    return dict(result) if isinstance(result, Mapping) else {}


def _event_step_id(event: Mapping[str, Any]) -> str:
    return str(event.get("step_id") or event.get("planner_step_id") or "").strip()


def trusted_recovery_trace_fields(
    tool_name: str,
    tool_request: Mapping[str, Any],
    private_context: Any,
    *,
    run_id: str,
) -> dict[str, Any]:
    """Return one trusted public marker only for an exact Runtime-owned retry."""

    if not isinstance(private_context, Mapping):
        return {}
    if (
        private_context.get("_authority") is not RUNTIME_PRIVATE_RECOVERY_AUTHORITY
        or private_context.get("version")
        != RUNTIME_PRIVATE_RECOVERY_CONTEXT_VERSION
        or private_context.get("return_to_root") is not True
        or str(private_context.get("run_id") or "").strip()
        != str(run_id or "").strip()
        or not str(run_id or "").strip()
        or str(tool_request.get("source") or "").strip()
        != "runtime_internal_recovery"
        or str(tool_request.get("recovery_link_kind") or "").strip()
        != "coordinator_action"
        or tool_request.get("root_goal_unchanged") is not True
    ):
        return {}
    request_tool = str(tool_name or "").strip()
    source_tool = str(private_context.get("recovery_source_tool") or "").strip()
    if not request_tool or not source_tool:
        return {}
    for key in _IDENTITY_KEYS:
        expected = str(private_context.get(key) or "").strip()
        observed = str(tool_request.get(key) or "").strip()
        if not expected or observed != expected:
            return {}
    root_return_values = tuple(
        str(private_context.get(key) or "").strip()
        for key in _ROOT_RETURN_IDENTITY_KEYS
    )
    if any(root_return_values):
        if not all(root_return_values):
            return {}
        for key, expected in zip(
            _ROOT_RETURN_IDENTITY_KEYS,
            root_return_values,
            strict=True,
        ):
            if str(tool_request.get(key) or "").strip() != expected:
                return {}
        if request_tool != root_return_values[-1]:
            return {}
    elif request_tool != source_tool:
        return {}
    verifier_repair_values = tuple(
        str(private_context.get(key) or "").strip()
        for key in _VERIFIER_REPAIR_IDENTITY_KEYS
    )
    if any(verifier_repair_values):
        if not all(verifier_repair_values):
            return {}
        for key, expected in zip(
            _VERIFIER_REPAIR_IDENTITY_KEYS,
            verifier_repair_values,
            strict=True,
        ):
            if str(tool_request.get(key) or "").strip() != expected:
                return {}
    scope_id = str(private_context.get("recovery_scope_id") or "").strip()
    if str(tool_request.get("replan_recovery_identity") or "").strip() != scope_id:
        return {}
    return {"recovery_context_trusted": True}


__all__ = [
    "RuntimeAuthorizedReplanPayload",
    "RUNTIME_PRIVATE_REPLAN_AUTHORITY",
    "RUNTIME_PRIVATE_REPLAN_CONTEXT_KEY",
    "RUNTIME_PRIVATE_REPLAN_CONTEXT_VERSION",
    "RUNTIME_PRIVATE_RECOVERY_AUTHORITY",
    "RUNTIME_PRIVATE_RECOVERY_CONTEXT_KEY",
    "RUNTIME_PRIVATE_RECOVERY_CONTEXT_VERSION",
    "canonical_replan_action_signature",
    "copy_live_replan_payload",
    "mint_private_replan_context",
    "recovery_request_claims_runtime_authority",
    "rehydrate_private_recovery_context",
    "trusted_private_replan_action_signatures",
    "trusted_recovery_trace_fields",
]
