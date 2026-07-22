"""Run timeline, event, group, and artifact access for Agent Runtime."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class BufferedRunEventBatch:
    """Run-scoped event writes held until an authoritative Run CAS wins."""

    def __init__(self, run_id: str, append_event: Any) -> None:
        self.run_id = str(run_id or "").strip()
        self._append_event = append_event
        self._records: list[tuple[str, dict[str, Any] | None, dict[str, Any]]] = []

    def append(
        self,
        event_type: str,
        payload: dict[str, Any] | None,
        **event_fields: Any,
    ) -> dict[str, Any]:
        payload_snapshot = deepcopy(payload) if isinstance(payload, dict) else None
        self._records.append(
            (event_type, payload_snapshot, deepcopy(event_fields))
        )
        return {
            "run_id": self.run_id,
            "event_type": event_type,
            "payload": deepcopy(payload_snapshot) if payload_snapshot is not None else {},
            "sequence": 0,
            "buffered": True,
        }

    def flush(
        self,
        *,
        expected_status: str = "",
        expected_updated_at: str = "",
    ) -> None:
        fence = (
            {
                "expected_status": expected_status,
                "expected_updated_at": expected_updated_at,
            }
            if expected_status and expected_updated_at
            else {}
        )
        for event_type, payload, event_fields in list(self._records):
            fields = {**event_fields, **fence}
            event = self._append_event(
                self.run_id,
                event_type,
                payload,
                **fields,
            )
            if fence and event is None:
                raise AgentRuntimeError("run_event_fence_mismatch")
        self._records.clear()

    def append_durable(
        self,
        event_type: str,
        payload: dict[str, Any],
        **event_fields: Any,
    ) -> dict[str, Any] | None:
        """Bypass deferral for an already-observed external side effect."""

        return self._append_event(
            self.run_id,
            event_type,
            deepcopy(payload),
            **deepcopy(event_fields),
        )

    def discard(self) -> None:
        self._records.clear()


class RuntimeRunTimelineService:
    """Read and append Run Timeline surfaces without owning persistence."""

    def __init__(
        self,
        *,
        runs: Any,
        run_groups: Any,
        runtime_events: Any,
        run_artifacts: Any,
    ) -> None:
        self._runs = runs
        self._run_groups = run_groups
        self._runtime_events = runtime_events
        self._run_artifacts = run_artifacts
        self._buffered_events: ContextVar[BufferedRunEventBatch | None] = ContextVar(
            f"runtime_run_event_buffer_{id(self)}",
            default=None,
        )

    @contextmanager
    def buffer_events(self, run_id: str):
        batch = BufferedRunEventBatch(run_id, self._runtime_events.append)
        token = self._buffered_events.set(batch)
        try:
            yield batch
        finally:
            self._buffered_events.reset(token)

    def list_runs(self, limit: int = 50) -> dict[str, Any]:
        return self._runs.list(limit)

    def list_run_groups(self, limit: int = 50) -> dict[str, Any]:
        return self._run_groups.list(limit)

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return self._run_groups.get(run_group_id)

    def list_group_events(
        self,
        run_group_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        group = self._run_groups.get(run_group_id)
        safe_after_sequence, safe_limit = _normalize_event_page_request(
            after_sequence,
            limit,
            max_limit=500,
        )
        child_runs = self._ordered_child_runs(group, run_group_id)
        events: list[dict[str, Any]] = []
        for run in child_runs:
            run_id = str(run.get("run_id") or "").strip()
            if not run_id:
                continue
            for event in self._events_for_run(
                run_id,
                include_internal=include_internal,
            ):
                if not isinstance(event, dict) or not _is_group_event(event):
                    continue
                events.append(
                    _group_scoped_event(
                        event,
                        group_run_id=run_group_id,
                        sequence=len(events) + 1,
                    )
                )

        filtered_events = [
            event for event in events if int(event.get("sequence") or 0) > safe_after_sequence
        ]
        page_events = filtered_events[:safe_limit]
        next_after_sequence = max(
            [int(event.get("sequence") or 0) for event in page_events]
            or [safe_after_sequence]
        )
        return {
            "ok": True,
            "run_id": run_group_id,
            "after_sequence": safe_after_sequence,
            "limit": safe_limit,
            "next_after_sequence": next_after_sequence,
            "has_more": len(filtered_events) > safe_limit,
            "events": page_events,
        }

    def run_group_source(self, run_group_id: str) -> str:
        return self._run_groups.source(run_group_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self._runs.get(run_id)

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
        expected_status: str | None = None,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any] | None:
        append_kwargs = {
            "actor": actor,
            "visibility": visibility,
            "sensitivity": sensitivity,
        }
        if expected_status is not None:
            append_kwargs["expected_status"] = expected_status
        if expected_updated_at is not None:
            append_kwargs["expected_updated_at"] = expected_updated_at
        buffered = self._buffered_events.get()
        if buffered is not None and buffered.run_id == str(run_id or "").strip():
            if (
                str(expected_status or "").strip().lower()
                in {"cancelled", "canceled", "completed", "failed"}
                and str(expected_updated_at or "").strip()
            ):
                # A separately fenced terminal writer (most importantly user
                # cancellation) is authoritative, not speculative resume
                # output. Never let the losing resume discard that audit.
                return buffered.append_durable(
                    event_type,
                    payload or {},
                    **append_kwargs,
                )
            return buffered.append(event_type, payload, **append_kwargs)
        return self._runtime_events.append(
            run_id,
            event_type,
            payload,
            **append_kwargs,
        )

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        safe_after_sequence, safe_limit = _normalize_event_page_request(
            after_sequence,
            limit,
            max_limit=1000,
        )
        return self._runtime_events.list(
            run_id,
            after_sequence=safe_after_sequence,
            limit=safe_limit,
            include_internal=include_internal,
        )

    def read_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return self._run_artifacts.read(run_id, artifact_path)

    def _ordered_child_runs(
        self,
        group: dict[str, Any],
        run_group_id: str,
    ) -> list[dict[str, Any]]:
        child_runs = self._run_groups.runs(run_group_id)
        child_order = [
            str(run_id)
            for run_id in group.get("child_run_ids") or []
            if str(run_id).strip()
        ]
        if not child_order:
            return child_runs
        by_run_id = {
            str(run.get("run_id") or ""): run
            for run in child_runs
            if str(run.get("run_id") or "")
        }
        ordered = [by_run_id[run_id] for run_id in child_order if run_id in by_run_id]
        seen = {str(run.get("run_id") or "") for run in ordered}
        ordered.extend(
            run
            for run in child_runs
            if str(run.get("run_id") or "") not in seen
        )
        return ordered

    def _events_for_run(
        self,
        run_id: str,
        *,
        include_internal: bool,
    ) -> list[dict[str, Any]]:
        events: list[dict[str, Any]] = []
        after_sequence = 0
        while True:
            page = self._runtime_events.list(
                run_id,
                after_sequence=after_sequence,
                limit=500,
                include_internal=include_internal,
            )
            page_events = [
                event for event in page.get("events") or [] if isinstance(event, dict)
            ]
            events.extend(page_events)
            next_after_sequence = int(page.get("next_after_sequence") or after_sequence)
            if not page.get("has_more") or next_after_sequence <= after_sequence:
                break
            after_sequence = next_after_sequence
        return events


def _is_group_event(event: dict[str, Any]) -> bool:
    event_type = str(event.get("event_type") or event.get("event") or "").strip()
    return event_type.startswith("group.")


def _normalize_event_page_request(
    after_sequence: int,
    limit: int,
    *,
    max_limit: int,
) -> tuple[int, int]:
    safe_after_sequence = max(0, int(after_sequence or 0))
    safe_limit = max(1, min(int(limit or 200), max_limit))
    return safe_after_sequence, safe_limit


def _group_scoped_event(
    event: dict[str, Any],
    *,
    group_run_id: str,
    sequence: int,
) -> dict[str, Any]:
    source_run_id = str(event.get("run_id") or "").strip()
    source_sequence = int(event.get("sequence") or 0)
    item = dict(event)
    payload = dict(item.get("payload") or {}) if isinstance(item.get("payload"), dict) else {}
    if source_run_id:
        payload.setdefault("source_run_id", source_run_id)
    if source_sequence:
        payload.setdefault("source_sequence", source_sequence)
    if item.get("event_id"):
        payload.setdefault("source_event_id", str(item.get("event_id")))
    payload.setdefault("group_run_id", group_run_id)
    payload.setdefault("run_group_id", group_run_id)
    item["run_id"] = group_run_id
    item["sequence"] = sequence
    item["payload"] = payload
    return item
