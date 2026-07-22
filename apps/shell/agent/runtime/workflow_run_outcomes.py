"""Workflow Run outcome projection helpers."""

from __future__ import annotations

from contextlib import nullcontext
from typing import Any

from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.errors import AgentRuntimeError
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
        get_run_group: Any | None = None,
        transaction_scope: Any | None = None,
    ) -> None:
        self._engine = engine
        self._timeline_callback = timeline_factory
        self._append_run_event_callback = append_run_event
        self._update_run_callback = update_run
        self._update_run_group_callback = update_run_group
        self._get_run_callback = get_run
        self._get_run_group_callback = get_run_group
        self._transaction_scope = transaction_scope

    def _timeline(self, event: str, detail: str = "", **payload: Any) -> dict[str, Any]:
        if self._timeline_callback is not None:
            return self._timeline_callback(event, detail, **payload)
        return self._engine._timeline(event, detail, **payload)

    def _append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        expected_status: str | None = None,
        expected_updated_at: str | None = None,
    ) -> Any:
        event_fence = {
            "expected_status": expected_status,
            "expected_updated_at": expected_updated_at,
        }
        fence_requested = expected_status is not None or expected_updated_at is not None
        if self._append_run_event_callback is not None:
            if fence_requested and supports_keyword(
                self._append_run_event_callback,
                "expected_status",
            ):
                return self._append_run_event_callback(
                    run_id,
                    event_type,
                    payload,
                    **event_fence,
                )
            result = self._append_run_event_callback(run_id, event_type, payload)
            return True if fence_requested and result is None else result
        if fence_requested and supports_keyword(self._engine.append_run_event, "expected_status"):
            return self._engine.append_run_event(
                run_id,
                event_type,
                payload,
                **event_fence,
            )
        result = self._engine.append_run_event(run_id, event_type, payload)
        return True if fence_requested and result is None else result

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

    def _get_run_group(self, run_group_id: str) -> dict[str, Any]:
        if self._get_run_group_callback is not None:
            return self._get_run_group_callback(run_group_id)
        return self._engine.get_run_group(run_group_id)

    @staticmethod
    def _group_cas_fields(group: dict[str, Any] | None) -> dict[str, Any]:
        if not group:
            return {}
        status = str(group.get("status") or "")
        updated_at = str(group.get("updated_at") or "")
        if not status or not updated_at:
            return {}
        return {
            "expected_status": status,
            "expected_updated_at": updated_at,
        }

    def completed(
        self,
        run: dict[str, Any],
        projection: WorkflowRunCompletionProjection,
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        root_group: bool,
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        run_group_id = str(run.get("run_group_id") or "")
        next_timeline = [*timeline, projection.timeline_event(self._timeline)]
        cas_fields = (
            {
                "expected_status": "running",
                "expected_updated_at": expected_updated_at,
            }
            if expected_updated_at is not None
            else {}
        )
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            group = self._root_group_snapshot(root_group, run_group_id)
            result = self._update_run(
                run_id,
                **projection.update_fields(timeline=next_timeline, artifacts=artifacts),
                **cas_fields,
            )
            if result is None:
                return self._get_run(run_id)
            self._require_terminal_event(
                self._append_run_event(
                    run_id,
                    "workflow.run.completed",
                    projection.event_payload(),
                    expected_status="completed",
                    expected_updated_at=str(result.get("updated_at") or ""),
                )
            )
            self._project_root_group(
                root_group=root_group,
                run_group_id=run_group_id,
                group=group,
                status="completed",
                summary=projection.result_text,
            )
        timeline[:] = next_timeline
        if root_group:
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
        expected_updated_at: str | None = None,
    ) -> dict[str, Any]:
        run_id = str(run["run_id"])
        run_group_id = str(run.get("run_group_id") or "")
        next_timeline = [*timeline, projection.timeline_event(self._timeline)]
        cas_fields = (
            {
                "expected_status": "running",
                "expected_updated_at": expected_updated_at,
            }
            if expected_updated_at is not None
            else {}
        )
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            group = self._root_group_snapshot(root_group, run_group_id)
            result = self._update_run(
                run_id,
                **projection.update_fields(timeline=next_timeline, artifacts=artifacts),
                **cas_fields,
            )
            if result is None:
                return self._get_run(run_id)
            self._require_terminal_event(
                self._append_run_event(
                    run_id,
                    "workflow.run.failed",
                    projection.event_payload(),
                    expected_status="failed",
                    expected_updated_at=str(result.get("updated_at") or ""),
                )
            )
            self._project_root_group(
                root_group=root_group,
                run_group_id=run_group_id,
                group=group,
                status="failed",
                summary=projection.safe_error,
            )
        timeline[:] = next_timeline
        if root_group:
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
        run_group_id = str(run.get("run_group_id") or "")
        failed_timeline = [
            *timeline,
            self._timeline("workflow.run.failed", safe_error, status="failed"),
        ]
        expected_updated_at = str(run.get("updated_at") or "").strip()
        cas_fields = (
            {
                "expected_status": str(run.get("status") or "running"),
                "expected_updated_at": expected_updated_at,
                "expected_pending_approval_absent": True,
            }
            if expected_updated_at
            else {}
        )
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            group = self._root_group_snapshot(root_group, run_group_id)
            failed = self._update_run(
                run_id,
                status="failed",
                result=safe_error,
                timeline=failed_timeline,
                artifacts=[],
                pending_approval=None,
                **cas_fields,
            )
            if failed is None:
                return self._get_run(run_id)
            self._require_terminal_event(
                self._append_run_event(
                    run_id,
                    "workflow.run.failed",
                    {"error": safe_error},
                    expected_status="failed",
                    expected_updated_at=str(failed.get("updated_at") or ""),
                )
            )
            self._project_root_group(
                root_group=root_group,
                run_group_id=run_group_id,
                group=group,
                status="failed",
                summary=safe_error,
            )
        return failed

    def _root_group_snapshot(
        self,
        root_group: bool,
        run_group_id: str,
    ) -> dict[str, Any] | None:
        if not root_group or not run_group_id:
            return None
        try:
            return self._get_run_group(run_group_id)
        except (AttributeError, KeyError):
            return None

    def _project_root_group(
        self,
        *,
        root_group: bool,
        run_group_id: str,
        group: dict[str, Any] | None,
        status: str,
        summary: str,
    ) -> None:
        if not root_group:
            return
        if group is not None:
            if _group_projection_matches(
                group,
                status=status,
                summary=summary,
            ):
                return
            if _is_terminal_group_status(group.get("status")):
                raise AgentRuntimeError("run_group_terminal_outcome_conflict")
        updated = self._update_run_group(
            run_group_id,
            status=status,
            summary=summary,
            **self._group_cas_fields(group),
        )
        if group is None or updated is not None:
            return
        try:
            winner = self._get_run_group(run_group_id)
        except (AttributeError, KeyError) as exc:
            raise AgentRuntimeError("run_group_projection_cas_lost") from exc
        if _group_projection_matches(
            winner,
            status=status,
            summary=summary,
        ):
            return
        if _is_terminal_group_status(winner.get("status")):
            raise AgentRuntimeError("run_group_terminal_outcome_conflict")
        raise AgentRuntimeError("run_group_projection_cas_lost")

    @staticmethod
    def _require_terminal_event(event: Any) -> None:
        if event is None:
            raise AgentRuntimeError("run_event_fence_mismatch")


def _group_projection_matches(
    group: dict[str, Any],
    *,
    status: str,
    summary: str,
) -> bool:
    return (
        _normalize_group_status(group.get("status"))
        == _normalize_group_status(status)
        and str(group.get("summary") or "") == redact_secrets(summary)
    )


def _normalize_group_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return "cancelled" if status == "canceled" else status


def _is_terminal_group_status(value: Any) -> bool:
    return _normalize_group_status(value) in {
        "completed",
        "failed",
        "cancelled",
    }
