"""Parent Workflow resume orchestration after child Run updates."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.workflow_outcomes import (
    WorkflowChildRunProjection,
    WorkflowChildStatusProjection,
    WorkflowParentResumeFailureProjection,
)


class WorkflowParentResumeCoordinator:
    """Coordinates parent Workflow updates after a child Run changes state."""

    def __init__(
        self,
        *,
        parent_runs_waiting_for_child: Any,
        workflow_run_is_group_root: Any,
        workflow_child_node_context: Any,
        merge_workflow_child_run_outcome: Any,
        workflow_for_run_resume: Any,
        workflow_resume_start_index: Any,
        continue_workflow_run: Any,
        timeline_factory: Any,
        append_run_event: Any,
        update_run: Any,
        update_run_group: Any,
        workflow_next_node_id: Any | None = None,
    ) -> None:
        self._parent_runs_waiting_for_child = parent_runs_waiting_for_child
        self._workflow_run_is_group_root = workflow_run_is_group_root
        self._workflow_child_node_context = workflow_child_node_context
        self._merge_workflow_child_run_outcome = merge_workflow_child_run_outcome
        self._workflow_for_run_resume = workflow_for_run_resume
        self._workflow_resume_start_index = workflow_resume_start_index
        self._workflow_next_node_id = workflow_next_node_id or (
            lambda _workflow, _node_id, _context: ""
        )
        self._continue_workflow_run = continue_workflow_run
        self._timeline = timeline_factory
        self._append_run_event = append_run_event
        self._update_run = update_run
        self._update_run_group = update_run_group

    def mark_child_running(self, child_run: dict[str, Any]) -> None:
        for workflow_run in self._parent_runs_waiting_for_child(child_run):
            self._mark_parent_child_running(workflow_run, child_run)

    def resume_after_child_update(self, child_run: dict[str, Any]) -> None:
        queue = [child_run]
        seen: set[tuple[str, str, str]] = set()
        while queue:
            current_child = queue.pop(0)
            current_child_id = str(current_child.get("run_id") or "")
            current_status = str(current_child.get("status") or "")
            current_result = str(current_child.get("result") or "")
            key = (current_child_id, current_status, current_result)
            if not current_child_id or key in seen:
                continue
            seen.add(key)
            for workflow_run in self._parent_runs_waiting_for_child(current_child):
                result = self.resume_parent_after_child_update(workflow_run, current_child)
                result_run_id = str(result.get("run_id") or "")
                if result_run_id and result_run_id != current_child_id:
                    queue.append(result)

    @staticmethod
    def _timeline_has_child_event(
        timeline: list[dict[str, Any]],
        event_name: str,
        child_run_id: str,
    ) -> bool:
        if not child_run_id:
            return False
        return any(
            event.get("event") == event_name
            and str(event.get("child_run_id") or "") == child_run_id
            for event in timeline
            if isinstance(event, dict)
        )

    def _append_child_agent_state_event(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
        child_node_info: dict[str, str],
        artifacts: list[dict[str, Any]],
    ) -> None:
        projection = WorkflowChildRunProjection.from_child_run(
            child_run,
            child_node_info,
            artifacts,
        )
        if projection is None:
            return
        node_kind = str(child_node_info.get("workflow_node_kind") or "").strip()
        event_type = "workflow.node.workflow" if node_kind == "workflow" else "workflow.node.agent"
        self._append_run_event(
            str(workflow_run["run_id"]),
            event_type,
            projection.agent_event_payload(),
        )

    def _mark_parent_child_running(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> None:
        root_group = self._workflow_run_is_group_root(workflow_run)
        timeline = [
            event
            for event in workflow_run.get("timeline") or []
            if isinstance(event, dict)
        ]
        artifacts = [item for item in workflow_run.get("artifacts") or [] if isinstance(item, dict)]
        child_label, child_node_info = self._workflow_child_node_context(timeline, child_run)
        child_run_id = str(child_run.get("run_id") or "")
        self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, child_label)
        status_projection = WorkflowChildStatusProjection.from_child_run(
            child_run,
            child_node_info,
            artifacts,
        )
        child_resumed_payload = status_projection.status_event_payload("running")
        already_child_resumed = self._timeline_has_child_event(
            timeline,
            "workflow.run.child_resumed",
            child_run_id,
        )
        if not already_child_resumed:
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            timeline.append(
                self._timeline(
                    "workflow.run.child_resumed",
                    f"{child_label} approved and resumed",
                    **child_resumed_payload,
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                "workflow.run.child_resumed",
                child_resumed_payload,
            )
        result_text = f"{child_label} 已批准，正在继续执行"
        result = self._update_run(
            str(workflow_run["run_id"]),
            status="running",
            result=result_text,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=None,
        )
        if root_group:
            self._update_run_group(
                str(result.get("run_group_id") or ""),
                status="running",
                summary=result_text,
            )

    def resume_parent_after_child_update(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> dict[str, Any]:
        root_group = self._workflow_run_is_group_root(workflow_run)
        timeline = [
            event
            for event in workflow_run.get("timeline") or []
            if isinstance(event, dict)
        ]
        artifacts = [item for item in workflow_run.get("artifacts") or [] if isinstance(item, dict)]
        child_status = str(child_run.get("status") or "")
        child_result = str(child_run.get("result") or "")
        child_run_id = str(child_run.get("run_id") or "")
        run_group_id = str(workflow_run.get("run_group_id") or "")
        if child_status == "completed" and self._timeline_has_child_event(
            timeline,
            "workflow.run.resumed",
            child_run_id,
        ):
            return workflow_run
        if child_status == "approval_required" and self._timeline_has_child_event(
            timeline,
            "workflow.run.approval_required",
            child_run_id,
        ):
            if (
                str(workflow_run.get("status") or "") == "approval_required"
                and str(workflow_run.get("result") or "") == child_result
            ):
                return workflow_run
        terminal_child_status = "cancelled" if child_status == "cancelled" else "failed"
        if child_status not in {"completed", "approval_required"} and self._timeline_has_child_event(
            timeline,
            f"workflow.run.{terminal_child_status}",
            child_run_id,
        ):
            return workflow_run
        child_label, child_node_info = self._workflow_child_node_context(timeline, child_run)
        self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, child_label)
        status_projection = WorkflowChildStatusProjection.from_child_run(
            child_run,
            child_node_info,
            artifacts,
        )
        if child_status == "approval_required":
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            event_payload = status_projection.status_event_payload("approval_required")
            timeline.append(
                self._timeline(
                    "workflow.run.approval_required",
                    child_label,
                    **event_payload,
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                "workflow.run.approval_required",
                event_payload,
            )
            result = self._update_run(
                str(workflow_run["run_id"]),
                status="approval_required",
                result=child_result,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(
                    run_group_id,
                    status="approval_required",
                    summary=child_result,
                )
            return result
        if child_status != "completed":
            status = terminal_child_status
            detail = (
                f"{child_run.get('runnable_name') or child_run.get('runnable_id')}: "
                f"{child_result}"
            )
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            timeline.append(
                self._timeline(
                    f"workflow.run.{status}",
                    detail,
                    **status_projection.status_event_payload(child_status),
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                f"workflow.run.{status}",
                status_projection.result_event_payload(child_status),
            )
            result = self._update_run(
                str(workflow_run["run_id"]),
                status=status,
                result=child_result,
                timeline=timeline,
                artifacts=artifacts,
            )
            if root_group:
                self._update_run_group(run_group_id, status=status, summary=child_result)
            return result
        try:
            workflow = self._workflow_for_run_resume(workflow_run)
            start_index = self._workflow_resume_start_index(workflow, workflow_run, child_run_id)
            start_node_id = ""
            resume_context = child_result
            current_node_id = str(child_node_info.get("workflow_node_id") or "")
            parent_node_id = str(child_node_info.get("workflow_parent_node_id") or "")
            parent_node_kind = str(child_node_info.get("workflow_parent_node_kind") or "")
            if parent_node_id and parent_node_kind == "parallel":
                start_node_id = parent_node_id
                resume_context = str(
                    child_node_info.get("workflow_parent_node_context") or child_result
                )
            elif current_node_id:
                start_node_id = str(
                    self._workflow_next_node_id(workflow, current_node_id, child_result) or ""
                )
            if start_index is None:
                if not start_node_id:
                    return workflow_run
                start_index = 0
            self._append_child_agent_state_event(
                workflow_run,
                child_run,
                child_node_info,
                artifacts,
            )
            resumed_payload = status_projection.status_event_payload("running")
            timeline.append(
                self._timeline(
                    "workflow.run.resumed",
                    "Workflow resumed after child Agent approval",
                    **resumed_payload,
                )
            )
            self._append_run_event(
                str(workflow_run["run_id"]),
                "workflow.run.resumed",
                resumed_payload,
            )
            continue_kwargs = {
                "context": resume_context,
                "timeline": timeline,
                "artifacts": artifacts,
                "start_index": start_index,
                "root_group": root_group,
            }
            if start_node_id:
                continue_kwargs["start_node_id"] = start_node_id
            return self._continue_workflow_run(
                workflow_run,
                workflow,
                **continue_kwargs,
            )
        except Exception as exc:
            failure = WorkflowParentResumeFailureProjection.from_error(
                exc,
                child_run_id=child_run_id,
                child_status=child_status,
                child_node_info=child_node_info,
            )
            timeline.append(failure.timeline_event(self._timeline))
            result = self._update_run(
                str(workflow_run["run_id"]),
                **failure.update_fields(timeline=timeline, artifacts=artifacts),
            )
            if root_group:
                self._update_run_group(run_group_id, status="failed", summary=failure.safe_error)
            return result
