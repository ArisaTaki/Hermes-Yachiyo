"""Parent Workflow resume orchestration after child Run updates."""

from __future__ import annotations

from contextlib import nullcontext
from copy import deepcopy
from typing import Any

from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.errors import AgentRuntimeError
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseCoordinator,
    is_workflow_projection_integrity_error,
)
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
        get_run: Any | None = None,
        get_run_group: Any | None = None,
        transaction_scope: Any | None = None,
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
        self._get_run = get_run
        self._get_run_group = get_run_group
        self._transaction_scope = transaction_scope
        self._approval_pause = WorkflowApprovalPauseCoordinator(
            timeline_factory=timeline_factory,
            append_run_event=append_run_event,
            update_run=update_run,
            update_run_group=update_run_group,
            get_run=get_run,
            get_run_group=get_run_group,
            transaction_scope=transaction_scope,
        )

    def _append_run_event_if_active(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        expected_status: str = "",
        expected_updated_at: str = "",
    ) -> bool:
        kwargs = {}
        if expected_status and supports_keyword(self._append_run_event, "expected_status"):
            kwargs = {
                "expected_status": expected_status,
                "expected_updated_at": expected_updated_at,
            }
        result = self._append_run_event(run_id, event_type, payload, **kwargs)
        return result is not None if kwargs else True

    def _run_group_snapshot(
        self,
        run_group_id: str,
        *,
        root_group: bool,
    ) -> dict[str, Any] | None:
        if not root_group or not run_group_id or not callable(self._get_run_group):
            return None
        try:
            return self._get_run_group(run_group_id)
        except KeyError:
            return None

    def _terminal_group_snapshot(
        self,
        run_group_id: str,
        *,
        root_group: bool,
    ) -> dict[str, Any] | None:
        group: dict[str, Any] | None = None
        if run_group_id and callable(self._get_run_group):
            try:
                group = self._get_run_group(run_group_id)
            except KeyError as exc:
                # A Workflow Run that names a missing group has lost durable
                # ownership context, even when it was a nested member. Never
                # commit a terminal row from that ambiguous state.
                raise AgentRuntimeError("run_group_projection_missing") from exc
        if not root_group:
            return None
        if not run_group_id:
            raise AgentRuntimeError("run_group_projection_missing")
        if not callable(self._get_run_group):
            # Compatibility for isolated legacy/unit coordinators. Production
            # always injects the durable reader and therefore fails closed.
            return None
        return group

    @staticmethod
    def _group_projection_matches(
        group: dict[str, Any],
        *,
        status: str,
        summary: str,
    ) -> bool:
        return (
            _normalize_terminal_status(group.get("status"))
            == _normalize_terminal_status(status)
            and str(group.get("summary") or "") == str(summary or "")
        )

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
        if not callable(self._get_run_group):
            # See _terminal_group_snapshot: retain compatibility for old
            # injected coordinators while the native Runtime remains strict.
            self._update_run_group(
                run_group_id,
                status=status,
                summary=summary,
            )
            return
        if group is None:
            raise AgentRuntimeError("run_group_projection_missing")
        if self._group_projection_matches(group, status=status, summary=summary):
            return
        if _is_terminal_status(group.get("status")):
            raise AgentRuntimeError("run_group_terminal_outcome_conflict")
        group_status = str(group.get("status") or "")
        group_updated_at = str(group.get("updated_at") or "")
        group_cas = (
            {
                "expected_status": group_status,
                "expected_updated_at": group_updated_at,
            }
            if group_status and group_updated_at
            else {}
        )
        updated = self._update_run_group(
            run_group_id,
            status=status,
            summary=summary,
            **group_cas,
        )
        if updated is not None:
            return
        try:
            winner = self._get_run_group(run_group_id)
        except KeyError as exc:
            raise AgentRuntimeError("run_group_projection_cas_lost") from exc
        if self._group_projection_matches(winner, status=status, summary=summary):
            return
        if _is_terminal_status(winner.get("status")):
            raise AgentRuntimeError("run_group_terminal_outcome_conflict")
        raise AgentRuntimeError("run_group_projection_cas_lost")

    def _fresh_run(self, workflow_run: dict[str, Any]) -> dict[str, Any]:
        if callable(self._get_run):
            return self._get_run(str(workflow_run.get("run_id") or ""))
        return workflow_run

    def _owns_root_group(self, run: dict[str, Any]) -> bool:
        if "project_root_group" in run:
            return run.get("project_root_group") is True
        # Compatibility for old injected rows. Native rows persist authority.
        return bool(self._workflow_run_is_group_root(run))

    def _project_parent_running_transition(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
        *,
        event_type: str,
        event_detail: str,
        result_text: str,
    ) -> tuple[
        dict[str, Any],
        list[dict[str, Any]],
        list[dict[str, Any]],
        dict[str, str],
        bool,
    ]:
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._fresh_run(workflow_run)
            current_status = _normalize_terminal_status(current.get("status"))
            if _is_terminal_status(current_status) or current.get("pending_approval"):
                return current, [], [], {}, False
            timeline = [
                deepcopy(event)
                for event in current.get("timeline") or []
                if isinstance(event, dict)
            ]
            artifacts = [
                deepcopy(item)
                for item in current.get("artifacts") or []
                if isinstance(item, dict)
            ]
            child_run_id = str(child_run.get("run_id") or "")
            if self._timeline_has_child_event(timeline, event_type, child_run_id):
                return current, timeline, artifacts, {}, False
            child_label, child_node_info = self._workflow_child_node_context(
                timeline,
                child_run,
            )
            self._merge_workflow_child_run_outcome(
                timeline,
                artifacts,
                child_run,
                child_label,
            )
            status_projection = WorkflowChildStatusProjection.from_child_run(
                child_run,
                child_node_info,
                artifacts,
            )
            effective_result = result_text or (
                f"{child_label} 已批准，正在继续执行"
                if event_type == "workflow.run.child_resumed"
                else str(child_run.get("result") or "")
            )
            effective_detail = event_detail or (
                f"{child_label} approved and resumed"
            )
            resumed_payload = status_projection.status_event_payload("running")
            next_timeline = [
                *timeline,
                self._timeline(event_type, effective_detail, **resumed_payload),
            ]
            owns_root_group = self._owns_root_group(current)
            run_group_id = str(current.get("run_group_id") or "")
            group = self._terminal_group_snapshot(
                run_group_id,
                root_group=owns_root_group,
            )
            result = self._update_run(
                str(current["run_id"]),
                status="running",
                result=effective_result,
                timeline=next_timeline,
                artifacts=artifacts,
                pending_approval=None,
                expected_status=str(current.get("status") or ""),
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if result is None:
                winner = self._fresh_run(current)
                return winner, timeline, artifacts, child_node_info, False
            event_version = str(result.get("updated_at") or "")
            if not self._append_child_agent_state_event(
                result,
                child_run,
                child_node_info,
                artifacts,
                expected_status="running",
                expected_updated_at=event_version,
            ):
                raise AgentRuntimeError("run_event_fence_mismatch")
            if not self._append_run_event_if_active(
                str(result["run_id"]),
                event_type,
                resumed_payload,
                expected_status="running",
                expected_updated_at=event_version,
            ):
                raise AgentRuntimeError("run_event_fence_mismatch")
            self._project_root_group(
                root_group=owns_root_group,
                run_group_id=run_group_id,
                group=group,
                status="running",
                summary=effective_result,
            )
        return result, next_timeline, artifacts, child_node_info, True

    def _project_terminal_child_outcome(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
        *,
        status: str,
    ) -> dict[str, Any]:
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._fresh_run(workflow_run)
            current_status = _normalize_terminal_status(current.get("status"))
            if _is_terminal_status(current_status):
                return current

            root_group = self._workflow_run_is_group_root(current)
            run_group_id = str(current.get("run_group_id") or "")
            group = self._terminal_group_snapshot(
                run_group_id,
                root_group=root_group,
            )
            timeline = [
                deepcopy(event)
                for event in current.get("timeline") or []
                if isinstance(event, dict)
            ]
            artifacts = [
                deepcopy(item)
                for item in current.get("artifacts") or []
                if isinstance(item, dict)
            ]
            child_label, child_node_info = self._workflow_child_node_context(
                timeline,
                child_run,
            )
            self._merge_workflow_child_run_outcome(
                timeline,
                artifacts,
                child_run,
                child_label,
            )
            status_projection = WorkflowChildStatusProjection.from_child_run(
                child_run,
                child_node_info,
                artifacts,
            )
            child_status = str(child_run.get("status") or "")
            child_result = str(child_run.get("result") or "")
            detail = (
                f"{child_run.get('runnable_name') or child_run.get('runnable_id')}: "
                f"{child_result}"
            )
            next_timeline = [
                *timeline,
                self._timeline(
                    f"workflow.run.{status}",
                    detail,
                    **status_projection.status_event_payload(child_status),
                ),
            ]
            result = self._update_run(
                str(current["run_id"]),
                status=status,
                result=child_result,
                timeline=next_timeline,
                artifacts=artifacts,
                expected_status=str(current.get("status") or ""),
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if result is None:
                return self._fresh_run(current)
            event_version = str(result.get("updated_at") or "")
            if not self._append_child_agent_state_event(
                result,
                child_run,
                child_node_info,
                artifacts,
                expected_status=status,
                expected_updated_at=event_version,
            ):
                raise AgentRuntimeError("run_event_fence_mismatch")
            if not self._append_run_event_if_active(
                str(result["run_id"]),
                f"workflow.run.{status}",
                status_projection.result_event_payload(child_status),
                expected_status=status,
                expected_updated_at=event_version,
            ):
                raise AgentRuntimeError("run_event_fence_mismatch")
            self._project_root_group(
                root_group=root_group,
                run_group_id=run_group_id,
                group=group,
                status=status,
                summary=child_result,
            )
        return result

    def _project_resume_failure(
        self,
        workflow_run: dict[str, Any],
        *,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        failure: WorkflowParentResumeFailureProjection,
    ) -> dict[str, Any]:
        scope = self._transaction_scope() if self._transaction_scope else nullcontext()
        with scope:
            current = self._fresh_run(workflow_run)
            current_status = _normalize_terminal_status(current.get("status"))
            if _is_terminal_status(current_status):
                return current
            root_group = self._workflow_run_is_group_root(current)
            run_group_id = str(current.get("run_group_id") or "")
            group = self._terminal_group_snapshot(
                run_group_id,
                root_group=root_group,
            )
            next_timeline = [*timeline, failure.timeline_event(self._timeline)]
            result = self._update_run(
                str(current["run_id"]),
                **failure.update_fields(timeline=next_timeline, artifacts=artifacts),
                expected_status=str(current.get("status") or ""),
                expected_updated_at=str(current.get("updated_at") or ""),
                expected_pending_approval_absent=True,
            )
            if result is None:
                return self._fresh_run(current)
            if not self._append_run_event_if_active(
                str(result["run_id"]),
                "workflow.run.failed",
                failure.event_payload,
                expected_status="failed",
                expected_updated_at=str(result.get("updated_at") or ""),
            ):
                raise AgentRuntimeError("run_event_fence_mismatch")
            self._project_root_group(
                root_group=root_group,
                run_group_id=run_group_id,
                group=group,
                status="failed",
                summary=failure.safe_error,
            )
        return result

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
        *,
        expected_status: str = "",
        expected_updated_at: str = "",
    ) -> bool:
        projection = WorkflowChildRunProjection.from_child_run(
            child_run,
            child_node_info,
            artifacts,
        )
        if projection is None:
            return True
        node_kind = str(child_node_info.get("workflow_node_kind") or "").strip()
        event_type = "workflow.node.workflow" if node_kind == "workflow" else "workflow.node.agent"
        return self._append_run_event_if_active(
            str(workflow_run["run_id"]),
            event_type,
            projection.agent_event_payload(),
            expected_status=expected_status,
            expected_updated_at=expected_updated_at,
        )

    def _mark_parent_child_running(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> None:
        self._project_parent_running_transition(
            workflow_run,
            child_run,
            event_type="workflow.run.child_resumed",
            event_detail="",
            result_text="",
        )

    def resume_parent_after_child_update(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> dict[str, Any]:
        if callable(self._get_run):
            workflow_run = self._get_run(str(workflow_run.get("run_id") or ""))
        root_group = self._workflow_run_is_group_root(workflow_run)
        timeline = [
            deepcopy(event)
            for event in workflow_run.get("timeline") or []
            if isinstance(event, dict)
        ]
        artifacts = [
            deepcopy(item)
            for item in workflow_run.get("artifacts") or []
            if isinstance(item, dict)
        ]
        child_status = str(child_run.get("status") or "")
        child_result = str(child_run.get("result") or "")
        child_run_id = str(child_run.get("run_id") or "")
        run_group_id = str(workflow_run.get("run_group_id") or "")
        resume_checkpointed = (
            child_status == "completed"
            and self._timeline_has_child_event(
                timeline,
                "workflow.run.resumed",
                child_run_id,
            )
        )
        if resume_checkpointed and (
            _normalize_terminal_status(workflow_run.get("status")) != "running"
            or workflow_run.get("pending_approval")
        ):
            return workflow_run
        # ``workflow.run.resumed`` is the durable hand-off checkpoint, not
        # proof that the continuation itself committed. A process fault or a
        # downstream projection rollback may leave the parent running at this
        # boundary. In that one state, continue from the persisted timeline;
        # terminal and paused generations were rejected above.
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
        if child_status not in {"completed", "approval_required"}:
            return self._project_terminal_child_outcome(
                workflow_run,
                child_run,
                status=terminal_child_status,
            )
        child_label, child_node_info = self._workflow_child_node_context(timeline, child_run)
        if child_status == "approval_required":
            self._merge_workflow_child_run_outcome(
                timeline,
                artifacts,
                child_run,
                child_label,
            )
            status_projection = WorkflowChildStatusProjection.from_child_run(
                child_run,
                child_node_info,
                artifacts,
            )
            event_payload = status_projection.status_event_payload("approval_required")
            child_projection = WorkflowChildRunProjection.from_child_run(
                child_run,
                child_node_info,
                artifacts,
            )
            node_kind = str(child_node_info.get("workflow_node_kind") or "").strip()
            child_event_type = (
                "workflow.node.workflow"
                if node_kind == "workflow"
                else "workflow.node.agent"
            )
            approval_run = workflow_run
            if (
                "project_root_group" not in approval_run
                and root_group
                and callable(self._get_run_group)
            ):
                approval_run = {**approval_run, "project_root_group": True}
            return self._approval_pause.pause_for_child(
                approval_run,
                result_text=child_result,
                timeline_event=self._timeline(
                    "workflow.run.approval_required",
                    child_label,
                    **event_payload,
                ),
                event_type="workflow.run.approval_required",
                event_payload=status_projection.result_event_payload(child_status),
                timeline=timeline,
                artifacts=artifacts,
                child_event_type=child_event_type,
                child_event_payload=(
                    child_projection.agent_event_payload()
                    if child_projection is not None
                    else None
                ),
                child_pending_approval=(
                    child_run.get("pending_approval")
                    if isinstance(child_run.get("pending_approval"), dict)
                    else None
                ),
            )
        if not resume_checkpointed:
            (
                workflow_run,
                timeline,
                artifacts,
                child_node_info,
                claimed_resume,
            ) = self._project_parent_running_transition(
                workflow_run,
                child_run,
                event_type="workflow.run.resumed",
                event_detail="Workflow resumed after child Agent approval",
                result_text=child_result,
            )
            if not claimed_resume:
                return workflow_run
        root_group = self._owns_root_group(workflow_run)
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
            if is_workflow_projection_integrity_error(exc):
                raise
            failure = WorkflowParentResumeFailureProjection.from_error(
                exc,
                child_run_id=child_run_id,
                child_status=child_status,
                child_node_info=child_node_info,
            )
            return self._project_resume_failure(
                workflow_run,
                timeline=timeline,
                artifacts=artifacts,
                failure=failure,
            )


def _normalize_terminal_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return "cancelled" if status == "canceled" else status


def _is_terminal_status(value: Any) -> bool:
    return _normalize_terminal_status(value) in {
        "completed",
        "failed",
        "cancelled",
    }
