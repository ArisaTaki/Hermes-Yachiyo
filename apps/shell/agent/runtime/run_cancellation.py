"""Run cancellation orchestration for Agent Runtime."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.cancellation import RunCancellationProjection


class RuntimeRunCancellationService:
    """Cancels plain Runs and Workflow Runs while preserving legacy projections."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        update_run: Callable[..., dict[str, Any]],
        append_run_event: Callable[[str, str, dict[str, Any]], Any],
        timeline_factory: Callable[..., dict[str, Any]],
        workflow_cancellation: Any,
        workflow_run_is_group_root: Callable[[dict[str, Any]], bool],
        project_cancelled_workflow_group_if_root: Callable[
            [dict[str, Any], dict[str, Any]],
            dict[str, Any],
        ],
        resume_parent_workflows_after_child_update: Callable[[dict[str, Any]], Any],
        project_child_run_transition: Callable[[dict[str, Any]], dict[str, Any]],
        final_statuses: set[str],
    ) -> None:
        self._get_run = get_run
        self._update_run = update_run
        self._append_run_event = append_run_event
        self._timeline = timeline_factory
        self._workflow_cancellation = workflow_cancellation
        self._workflow_run_is_group_root = workflow_run_is_group_root
        self._project_cancelled_workflow_group_if_root = (
            project_cancelled_workflow_group_if_root
        )
        self._resume_parent_workflows_after_child_update = (
            resume_parent_workflows_after_child_update
        )
        self._project_child_run_transition = project_child_run_transition
        self._final_statuses = set(final_statuses)

    def cancel_once(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        if run["status"] in self._final_statuses:
            return run
        timeline = [*run["timeline"]]
        if run.get("kind") == "workflow_run":
            workflow_timeline, artifacts, result_text = (
                self._workflow_cancellation.project_cancelled_workflow_run(
                    run_id,
                    run,
                    timeline,
                )
            )
            projection = RunCancellationProjection.workflow(
                workflow_timeline,
                artifacts,
                result_text,
            )
        else:
            projection = RunCancellationProjection.plain(timeline, self._timeline)
        result = self._update_run(
            run_id,
            **projection.update_fields(),
        )
        cancel_event_type = (
            "workflow.run.cancelled"
            if result.get("kind") == "workflow_run"
            else "run.cancelled"
        )
        self._append_run_event(
            run_id,
            cancel_event_type,
            {
                "kind": result.get("kind"),
                "result": result.get("result") or "",
                "status": "cancelled",
            },
        )
        if result.get("kind") == "workflow_run" and self._workflow_run_is_group_root(
            result
        ):
            projected = self._project_cancelled_workflow_group_if_root(run, result)
            self._resume_parent_workflows_after_child_update(projected)
            return projected
        return self._project_child_run_transition(result)
