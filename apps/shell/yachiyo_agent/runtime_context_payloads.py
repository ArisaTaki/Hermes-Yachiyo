"""Shared runtime execution context projection helpers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from apps.shell.agent.runtime.events import redact_run_event_payload

from .contracts import RuntimeExecutionEnvelopeSnapshot

_ENVELOPE_KEYS = (
    "runtime_execution_envelope",
    "yachiyo_execution_envelope",
    "execution_envelope",
)
_METADATA_MARKERS = (
    "yachiyo_runtime_planner",
    "runtime_execution_envelope",
    "yachiyo_execution_envelope",
    "execution_envelope",
    "decision_id",
    "plan_id",
    "intent_kind",
    "planner_decision_id",
    "runtime_plan_id",
)


def runtime_execution_metadata_from_payloads(
    *payloads: Mapping[str, Any] | None,
) -> dict[str, Any]:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        metadata = _redacted_mapping(payload.get("runtime_execution_metadata"))
        if metadata:
            return metadata
        metadata = _redacted_mapping(payload.get("metadata"))
        if metadata and _looks_like_runtime_metadata(metadata):
            return metadata
    return {}


def runtime_execution_envelope_from_payloads(
    *payloads: Mapping[str, Any] | None,
    runtime_execution_metadata: Mapping[str, Any] | None = None,
) -> RuntimeExecutionEnvelopeSnapshot | None:
    for payload in payloads:
        if not isinstance(payload, Mapping):
            continue
        for key in _ENVELOPE_KEYS:
            envelope = _runtime_execution_envelope(payload.get(key))
            if envelope is not None:
                return envelope
    metadata = runtime_execution_metadata or {}
    for key in _ENVELOPE_KEYS:
        envelope = _runtime_execution_envelope(metadata.get(key))
        if envelope is not None:
            return envelope
    return None


def _runtime_execution_envelope(value: Any) -> RuntimeExecutionEnvelopeSnapshot | None:
    if isinstance(value, RuntimeExecutionEnvelopeSnapshot):
        value = value.model_dump(mode="json")
    payload = _redacted_envelope_mapping(value)
    if not payload:
        return None
    try:
        return RuntimeExecutionEnvelopeSnapshot.model_validate(payload)
    except Exception:
        return None


def _redacted_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_run_event_payload(dict(value))
    return dict(redacted) if isinstance(redacted, Mapping) else {}


def _redacted_envelope_mapping(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        return {}
    redacted = redact_run_event_payload({"runtime_execution_envelope": dict(value)})
    if not isinstance(redacted, Mapping):
        return {}
    envelope = redacted.get("runtime_execution_envelope")
    return dict(envelope) if isinstance(envelope, Mapping) else {}


def _looks_like_runtime_metadata(metadata: Mapping[str, Any]) -> bool:
    return any(metadata.get(key) for key in _METADATA_MARKERS)
