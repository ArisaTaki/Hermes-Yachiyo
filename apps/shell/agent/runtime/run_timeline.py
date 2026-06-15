"""Run timeline, event, group, and artifact access for Agent Runtime."""

from __future__ import annotations

from typing import Any


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

    def list_runs(self, limit: int = 50) -> dict[str, Any]:
        return self._runs.list(limit)

    def list_run_groups(self, limit: int = 50) -> dict[str, Any]:
        return self._run_groups.list(limit)

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return self._run_groups.get(run_group_id)

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
    ) -> dict[str, Any]:
        return self._runtime_events.append(
            run_id,
            event_type,
            payload,
            actor=actor,
            visibility=visibility,
            sensitivity=sensitivity,
        )

    def list_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        return self._runtime_events.list(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
            include_internal=include_internal,
        )

    def read_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return self._run_artifacts.read(run_id, artifact_path)
