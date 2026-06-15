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

    def __init__(self, engine: Any) -> None:
        self._engine = engine

    def completed(
        self,
        run: dict[str, Any],
        projection: WorkflowRunCompletionProjection,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
    ) -> dict[str, Any]:
        engine = self._engine
        run_id = str(run["run_id"])
        run_group_id = str(run.get("run_group_id") or "")
        timeline.append(projection.timeline_event(engine._timeline))
        engine.append_run_event(run_id, "workflow.run.completed", projection.event_payload())
        result = engine._update_run(
            run_id,
            **projection.update_fields(timeline=timeline, artifacts=artifacts),
        )
        if root_group:
            engine._update_run_group(run_group_id, status="completed", summary=projection.result_text)
            result = engine.get_run(result["run_id"])
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
        engine = self._engine
        run_id = str(run["run_id"])
        run_group_id = str(run.get("run_group_id") or "")
        timeline.append(projection.timeline_event(engine._timeline))
        engine.append_run_event(run_id, "workflow.run.failed", projection.event_payload())
        result = engine._update_run(
            run_id,
            **projection.update_fields(timeline=timeline, artifacts=artifacts),
        )
        if root_group:
            engine._update_run_group(run_group_id, status="failed", summary=projection.safe_error)
            result = engine.get_run(result["run_id"])
        return result

    def background_failed(
        self,
        run: dict[str, Any],
        *,
        timeline: list[dict[str, Any]],
        error: Any,
        root_group: bool,
    ) -> dict[str, Any]:
        engine = self._engine
        run_id = str(run["run_id"])
        safe_error = redact_secrets(error)
        failed_timeline = [
            *timeline,
            engine._timeline("workflow.run.failed", safe_error, status="failed"),
        ]
        failed = engine._update_run(
            run_id,
            status="failed",
            result=safe_error,
            timeline=failed_timeline,
            artifacts=[],
            pending_approval=None,
        )
        engine.append_run_event(run_id, "workflow.run.failed", {"error": safe_error})
        if root_group:
            engine._update_run_group(
                str(run.get("run_group_id") or ""),
                status="failed",
                summary=safe_error,
            )
        return failed
