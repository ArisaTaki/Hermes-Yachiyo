"""Run cancellation orchestration for Agent Runtime."""

from __future__ import annotations

from contextlib import nullcontext
import threading
from typing import Any, Callable

from apps.shell.agent.runtime.cancellation import (
    RunCancellationProjection,
    pending_approval_cancelled_event_payload,
)
from apps.shell.agent.runtime.errors import AgentRuntimeError


class _RunCancellationCasLost(Exception):
    """The Run changed after cancellation read its source snapshot."""


def _canonical_run_kind(value: Any) -> str:
    normalized = (
        str(value or "")
        .strip()
        .casefold()
        .replace("-", "_")
        .replace(" ", "_")
    )
    compact = normalized.replace("_", "")
    if normalized == "workflow" or compact == "workflowrun":
        return "workflow_run"
    if normalized == "agent" or compact == "agentrun":
        return "agent_run"
    if normalized == "main_chat" or compact == "mainchatrun":
        return "main_chat_run"
    return normalized


class RuntimeRunCancellationService:
    """Cancels plain Runs and Workflow Runs while preserving legacy projections."""

    def __init__(
        self,
        *,
        get_run: Callable[[str], dict[str, Any]],
        update_run: Callable[..., dict[str, Any] | None],
        append_run_event: Callable[..., Any],
        timeline_factory: Callable[..., dict[str, Any]],
        workflow_cancellation: Any,
        workflow_run_is_group_root: Callable[[dict[str, Any]], bool],
        project_cancelled_workflow_group_if_root: Callable[
            [dict[str, Any], dict[str, Any]],
            dict[str, Any] | None,
        ],
        resume_parent_workflows_after_child_update: Callable[[dict[str, Any]], Any],
        project_child_run_transition: Callable[[dict[str, Any]], dict[str, Any]],
        final_statuses: set[str],
        close_run_owned_browser_target: Callable[[dict[str, Any]], Any] | None = None,
        transaction_scope: Callable[[], Any] | None = None,
        project_agent_run_group_if_root: Callable[[dict[str, Any]], Any] | None = None,
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
        self._close_run_owned_browser_target = (
            close_run_owned_browser_target or (lambda _run: None)
        )
        self._transaction_scope = transaction_scope
        self._project_agent_run_group_if_root = project_agent_run_group_if_root

    def cancel_once(self, run_id: str) -> dict[str, Any]:
        run = self._get_run(run_id)
        if run["status"] in self._final_statuses:
            if str(run.get("status") or "").strip().casefold() in {
                "cancelled",
                "canceled",
            }:
                return self._repair_post_commit_projection(run)
            return run
        expected_status = str(run.get("status") or "")
        expected_updated_at = str(run.get("updated_at") or "")
        approval_cancelled: dict[str, Any] = {}
        result: dict[str, Any] | None = None
        projected_root: dict[str, Any] | None = None
        root_workflow = False
        scope = (
            self._transaction_scope()
            if self._transaction_scope is not None
            else nullcontext()
        )
        try:
            # Workflow cancellation may cancel a waiting child Run while it
            # builds the parent projection. Keep that work in the same unit of
            # work as the parent CAS so a lost race rolls every cancellation
            # write back before returning the winner's fresh Run.
            with scope:
                timeline = [*run["timeline"]]
                source_run_kind = _canonical_run_kind(run.get("kind"))
                if source_run_kind == "workflow_run":
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
                approval_cancelled = pending_approval_cancelled_event_payload(
                    run_id,
                    {**run, "kind": source_run_kind},
                    reason=projection.result_text,
                )
                result = self._update_run(
                    run_id,
                    **projection.update_fields(),
                    expected_status=expected_status,
                    expected_updated_at=expected_updated_at,
                )
                if result is None:
                    raise _RunCancellationCasLost
                run_kind = _canonical_run_kind(result.get("kind"))
                root_workflow = bool(
                    run_kind == "workflow_run"
                    and self._workflow_run_is_group_root(result)
                )
                cancel_event_type = {
                    "workflow_run": "workflow.run.cancelled",
                    "agent_run": "agent.run.cancelled",
                }.get(run_kind, "run.cancelled")
                event_fence = {
                    "expected_status": "cancelled",
                    "expected_updated_at": str(result.get("updated_at") or ""),
                }
                if approval_cancelled:
                    _require_run_event(
                        self._append_run_event(
                            run_id,
                            "approval.cancelled",
                            approval_cancelled,
                            **event_fence,
                        )
                    )
                _require_run_event(
                    self._append_run_event(
                        run_id,
                        cancel_event_type,
                        {
                            "kind": run_kind,
                            "result": result.get("result") or "",
                            "status": "cancelled",
                        },
                        **event_fence,
                    )
                )
                if root_workflow:
                    # The root Group terminal fact follows the canonical Run
                    # event (and its compatibility aliases), while remaining
                    # inside this same transaction. Any Group CAS/event fault
                    # therefore rolls the Run row and earlier events back.
                    projected_root = self._project_cancelled_workflow_group_if_root(
                        run,
                        result,
                    )
                    if projected_root is None:
                        raise _RunCancellationCasLost
                if (
                    run_kind == "agent_run"
                    and self._project_agent_run_group_if_root is not None
                ):
                    # Root Agent Run groups are part of the same authoritative
                    # terminal fact. The compatibility child projection below
                    # may retry this after commit, but that retry is a strict
                    # idempotent no-op.
                    self._project_agent_run_group_if_root(result)
        except _RunCancellationCasLost:
            # The terminal/completing writer won. Never emit stale cancel
            # events, close its resources, or project workflow relationships.
            return self._get_run(run_id)

        assert result is not None
        if result.get("status") == "cancelled":
            try:
                self._close_run_owned_browser_target(run)
            except Exception:
                # Cancellation is already durable. Browser cleanup must never
                # turn it back into an application-level failure.
                pass
        if root_workflow:
            assert projected_root is not None
        return self._repair_post_commit_projection(
            result,
            projected_root=projected_root,
        )

    def _repair_post_commit_projection(
        self,
        run: dict[str, Any],
        *,
        projected_root: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Finish idempotent relationship projections after cancellation commits."""

        run_kind = _canonical_run_kind(run.get("kind"))
        root_workflow = bool(
            run_kind == "workflow_run"
            and self._workflow_run_is_group_root(run)
        )
        if root_workflow:
            repaired_root = projected_root
            if repaired_root is None:
                repaired_root = self._project_cancelled_workflow_group_if_root(
                    run,
                    run,
                )
            if repaired_root is None:
                raise AgentRuntimeError("run_group_projection_cas_lost")
            self._resume_parent_workflows_after_child_update(repaired_root)
            return repaired_root
        return self._project_child_run_transition(run)


def _require_run_event(event: Any) -> None:
    if event is None:
        raise AgentRuntimeError("run_event_fence_mismatch")


class RuntimeRunCancellationCoordinator:
    """Serializes cancellation requests per Run id before projecting cancellation."""

    def __init__(
        self,
        *,
        cancel_once: Callable[[str], dict[str, Any]],
        run_cancel_locks: dict[str, threading.RLock],
        run_cancel_locks_guard: threading.RLock,
    ) -> None:
        self._cancel_once = cancel_once
        self._run_cancel_locks = run_cancel_locks
        self._run_cancel_locks_guard = run_cancel_locks_guard

    def cancel(self, run_id: str) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        with self._run_cancel_locks_guard:
            lock = self._run_cancel_locks.setdefault(clean_run_id, threading.RLock())
        try:
            with lock:
                return self._cancel_once(clean_run_id)
        finally:
            with self._run_cancel_locks_guard:
                if self._run_cancel_locks.get(clean_run_id) is lock:
                    self._run_cancel_locks.pop(clean_run_id, None)
