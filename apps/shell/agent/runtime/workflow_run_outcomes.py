"""Workflow Run outcome projection helpers."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.events import redact_secrets
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowContinuationFailureProjection,
    WorkflowRunCompletionProjection,
)


class WorkflowRunOutcomeProjector:
    """Applies Workflow Run outcome projections to events, run rows, and root groups."""

    def __init__(
        self,
        engine: Any,
        *,
        timeline_factory: Any | None = None,
        append_run_event: Any | None = None,
        update_run: Any | None = None,
        update_run_group: Any | None = None,
        get_run: Any | None = None,
    ) -> None:
        self._engine = engine
        self._timeline_callback = timeline_factory
        self._append_run_event_callback = append_run_event
        self._update_run_callback = update_run
        self._update_run_group_callback = update_run_group
        self._get_run_callback = get_run

    def _timeline(self, event: str, detail: str = "", **payload: Any) -> dict[str, Any]:
        if self._timeline_callback is not None:
            return self._timeline_callback(event, detail, **payload)
        return self._engine._timeline(event, detail, **payload)

    def _append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
    ) -> Any:
        if self._append_run_event_callback is not None:
            return self._append_run_event_callback(run_id, event_type, payload)
        return self._engine.append_run_event(run_id, event_type, payload)

    def _update_run(self, run_id: str, **fields: Any) -> dict[str, Any]:
        if self._update_run_callback is not None:
            return self._update_run_callback(run_id, **fields)
        return self._engine._update_run(run_id, **fields)

    def _update_run_group(self, run_group_id: str, **fields: Any) -> Any:
        if self._update_run_group_callback is not None:
            return self._update_run_group_callback(run_group_id, **fields)
        return self._engine._update_run_group(run_group_id, **fields)

    def _get_run(self, run_id: str) -> dict[str, Any]:
        if self._get_run_callback is not None:
            return self._get_run_callback(run_id)
        return self._engine.get_run(run_id)

    def completed(
        self,
        run: dict[str, Any],
        projection: WorkflowRunCompletionProjection,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        run_group_id = str(run.get("run_group_id") or "")
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(run_id, "workflow.run.completed", projection.event_payload())
        result = self._update_run(
            run_id,
            **projection.update_fields(timeline=timeline, artifacts=artifacts),
        )
        if root_group:
            self._update_run_group(run_group_id, status="completed", summary=projection.result_text)
            result = self._get_run(result["run_id"])
        return result

    def failed(
        self,
        run: dict[str, Any],
        projection: WorkflowContinuationFailureProjection,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        run_group_id = str(run.get("run_group_id") or "")
        timeline.append(projection.timeline_event(self._timeline))
        self._append_run_event(run_id, "workflow.run.failed", projection.event_payload())
        result = self._update_run(
            run_id,
            **projection.update_fields(timeline=timeline, artifacts=artifacts),
        )
        if root_group:
            self._update_run_group(run_group_id, status="failed", summary=projection.safe_error)
            result = self._get_run(result["run_id"])
        return result

    def background_failed(
        self,
        run: dict[str, Any],
        *,
        timeline: list[dict[str, Any]],
        error: Any,
        root_group: bool,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        safe_error = redact_secrets(error)
        failed_timeline = [
            *timeline,
            self._timeline("workflow.run.failed", safe_error, status="failed"),
        ]
        failed = self._update_run(
            run_id,
            status="failed",
            result=safe_error,
            timeline=failed_timeline,
            artifacts=[],
            pending_approval=None,
        )
        self._append_run_event(run_id, "workflow.run.failed", {"error": safe_error})
        if root_group:
            self._update_run_group(
                str(run.get("run_group_id") or ""),
                status="failed",
                summary=safe_error,
            )
        return failed
