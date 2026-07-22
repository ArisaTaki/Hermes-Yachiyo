"""Crash-safe reconciliation for persisted runs at application startup."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any

from apps.shell.agent.runtime.clock import parse_iso_utc
from apps.shell.agent.runtime.events import (
    canonical_run_event_aliases,
    redact_run_event_payload,
    task_run_event_payload,
)
from apps.shell.agent.runtime.group_orchestration import (
    group_run_status_from_child_runs,
    group_run_summary_from_child_runs,
)

_RECOVERY_EVENT_TYPE = "run.recovery.interrupted"
_ACTIVE_RUN_STATUSES = ("created", "pending", "processing", "running")
_ACTIVE_GROUP_STATUSES = {
    "created",
    "pending",
    "queued",
    "running",
    "processing",
    "approval_required",
    "waiting_approval",
}
_TERMINAL_GROUP_STATUSES = {"completed", "failed", "cancelled", "canceled"}
_AGENT_GROUP_SOURCES = {"agent", "agent_group"}
_GROUP_CLEANUP_REQUESTED_EVENT_TYPE = "group.cleanup.requested"
_RECOVERY_FAILURE_MESSAGE = (
    "应用重启后无法安全恢复此前执行；"
    "为避免重复操作，未自动重放工具，请重试。"
)
_LEASE_EXPIRED_MESSAGE = (
    "执行进程心跳已失效，为避免重复操作已停止；请重试。"
)
_GROUP_CLEANUP_RECOVERY_MESSAGE = (
    "群组启动未完成，已停止此成员以完成一致性恢复。"
)
_MAX_INTEGRITY_ERROR_CODE_LENGTH = 120


class StartupReconciliationIntegrityError(RuntimeError):
    """A deterministic persisted-state invariant violation during recovery."""

    def __init__(self, code: str) -> None:
        clean_code = "".join(
            character
            if character.isalnum() or character in {"_", "-", "."}
            else "_"
            for character in str(code or "startup_reconciliation_integrity_error")
        )[:_MAX_INTEGRITY_ERROR_CODE_LENGTH]
        self.code = clean_code or "startup_reconciliation_integrity_error"
        super().__init__(self.code)


class RuntimeStartupReconciler:
    """Reconcile runs that may have been interrupted by a prior process."""

    def __init__(self, conn: Any, db_lock: Any) -> None:
        self._conn = conn
        self._db_lock = db_lock

    def reconcile(
        self,
        cutoff: str,
        *,
        observed_at: str | None = None,
    ) -> dict[str, Any]:
        clean_cutoff = str(cutoff or "")
        cutoff_at = parse_iso_utc(clean_cutoff)
        if cutoff_at is None:
            raise ValueError("startup_reconciliation_cutoff_invalid")
        clean_observed_at = str(observed_at or clean_cutoff)
        observed_at_utc = parse_iso_utc(clean_observed_at)
        if observed_at_utc is None:
            raise ValueError("startup_reconciliation_observed_at_invalid")
        preserved_approval_run_ids: list[str] = []
        failed_run_ids: list[str] = []
        deferred_lease_run_ids: list[str] = []
        deferred_lease_expiries: list[datetime] = []
        preserved_workflow_parent_run_ids: list[str] = []
        affected_group_ids: set[str] = set()
        with self._db_lock:
            approval_rows = self._conn.execute(
                """
                SELECT run_id, run_group_id, project_root_group
                 FROM runs
                 WHERE status='approval_required'
                 ORDER BY run_id
                """,
            ).fetchall()
            active_rows = self._conn.execute(
                """
                SELECT run_id, run_group_id, project_root_group
                 FROM runs
                 WHERE status IN ('created', 'pending', 'processing', 'running')
                 ORDER BY run_id
                """,
            ).fetchall()
            group_rows = self._conn.execute(
                """
                SELECT run_group_id, created_at, status, source
                  FROM run_groups
                 WHERE status IN (
                    'created', 'pending', 'queued', 'running', 'processing',
                    'approval_required', 'waiting_approval'
                 )
                   AND (
                       source IN ('agent', 'agent_group')
                       OR EXISTS (
                           SELECT 1
                             FROM runs
                            WHERE runs.run_group_id=run_groups.run_group_id
                              AND runs.project_root_group=1
                       )
                   )
                 ORDER BY run_group_id
                """,
            ).fetchall()
            cleanup_rows = self._agent_group_cleanup_candidate_rows_locked()
        cleanup_failed_ids: set[str] = set()
        for row in cleanup_rows:
            run_id = str(row["run_id"])
            if self._reconcile_group_cleanup_run(
                run_id,
                recovered_at=clean_observed_at,
                cutoff_at=cutoff_at,
            ) != "failed":
                continue
            cleanup_failed_ids.add(run_id)
            failed_run_ids.append(run_id)
            _add_group_id(affected_group_ids, row["run_group_id"])
        for row in approval_rows:
            if str(row["run_id"]) in cleanup_failed_ids:
                continue
            outcome = self._reconcile_approval(
                str(row["run_id"]),
                cutoff_at,
                clean_observed_at,
            )
            if outcome == "preserved":
                preserved_approval_run_ids.append(str(row["run_id"]))
                _add_owned_group_id(affected_group_ids, row)
            elif outcome == "preserved_workflow_parent":
                preserved_workflow_parent_run_ids.append(str(row["run_id"]))
                _add_owned_group_id(affected_group_ids, row)
            elif outcome == "failed":
                failed_run_ids.append(str(row["run_id"]))
                _add_owned_group_id(affected_group_ids, row)
        for row in active_rows:
            run_id = str(row["run_id"])
            if run_id in cleanup_failed_ids:
                continue
            outcome, lease_expiry = self._reconcile_active(
                run_id,
                cutoff_at,
                observed_at_utc,
                clean_observed_at,
            )
            if outcome == "failed":
                failed_run_ids.append(run_id)
                _add_owned_group_id(affected_group_ids, row)
            elif outcome == "deferred":
                deferred_lease_run_ids.append(run_id)
                if lease_expiry is not None:
                    deferred_lease_expiries.append(lease_expiry)
            elif outcome == "preserved_workflow_parent":
                preserved_workflow_parent_run_ids.append(run_id)
                _add_owned_group_id(affected_group_ids, row)
        for row in group_rows:
            if (
                str(row["status"] or "") in _ACTIVE_GROUP_STATUSES
                and _eligible_at_cutoff(row["created_at"], cutoff_at)
            ):
                _add_group_id(affected_group_ids, row["run_group_id"])
        for group_id in sorted(affected_group_ids):
            self._reconcile_group_projection(group_id, recovered_at=clean_observed_at)
        return {
            "ok": True,
            "cutoff": clean_cutoff,
            "observed_at": clean_observed_at,
            "failed_run_ids": failed_run_ids,
            "preserved_approval_run_ids": preserved_approval_run_ids,
            "deferred_lease_run_ids": deferred_lease_run_ids,
            "preserved_workflow_parent_run_ids": preserved_workflow_parent_run_ids,
            "terminal_tasks": self._terminal_tasks_for_runs(failed_run_ids),
            "reconciled_group_ids": sorted(affected_group_ids),
            "next_lease_expiry_at": (
                min(deferred_lease_expiries).isoformat()
                if deferred_lease_expiries
                else ""
            ),
        }

    def reconcile_runtime_leases(self, observed_at: str) -> dict[str, Any]:
        """Fail expired leases and settle durable partial-Group cleanup intents."""
        clean_observed_at = str(observed_at or "")
        observed_at_utc = parse_iso_utc(clean_observed_at)
        if observed_at_utc is None:
            raise ValueError("runtime_lease_watchdog_observed_at_invalid")
        with self._db_lock:
            rows = self._conn.execute(
                """
                SELECT run_id, run_group_id, project_root_group
                  FROM runs
                 WHERE status='running' AND async_lease_owner_token!=''
                 ORDER BY run_id
                """,
            ).fetchall()
            cleanup_rows = self._agent_group_cleanup_candidate_rows_locked()
            active_agent_group_rows = self._conn.execute(
                """
                SELECT run_group_id
                  FROM run_groups
                 WHERE source IN ('agent', 'agent_group')
                   AND status IN (
                       'created', 'pending', 'queued', 'running', 'processing',
                       'approval_required', 'waiting_approval'
                   )
                 ORDER BY run_group_id
                """
            ).fetchall()
        failed_run_ids: list[str] = []
        deferred_lease_run_ids: list[str] = []
        deferred_lease_expiries: list[datetime] = []
        affected_group_ids: set[str] = set()
        cleanup_failed_ids: set[str] = set()
        for row in cleanup_rows:
            run_id = str(row["run_id"])
            if self._reconcile_group_cleanup_run(
                run_id,
                recovered_at=clean_observed_at,
            ) != "failed":
                continue
            cleanup_failed_ids.add(run_id)
            failed_run_ids.append(run_id)
            _add_group_id(affected_group_ids, row["run_group_id"])
        for row in rows:
            run_id = str(row["run_id"])
            if run_id in cleanup_failed_ids:
                continue
            outcome, lease_expiry = self._reconcile_runtime_lease(
                run_id,
                observed_at=observed_at_utc,
                recovered_at=clean_observed_at,
            )
            if outcome == "failed":
                failed_run_ids.append(run_id)
                self._add_recoverable_group_id(affected_group_ids, row)
            elif outcome == "deferred":
                deferred_lease_run_ids.append(run_id)
                if lease_expiry is not None:
                    deferred_lease_expiries.append(lease_expiry)
        for row in active_agent_group_rows:
            _add_group_id(affected_group_ids, row["run_group_id"])
        for group_id in sorted(affected_group_ids):
            self._reconcile_group_projection(group_id, recovered_at=clean_observed_at)
        return {
            "ok": True,
            "observed_at": clean_observed_at,
            "failed_run_ids": failed_run_ids,
            "deferred_lease_run_ids": deferred_lease_run_ids,
            "terminal_tasks": self._terminal_tasks_for_runs(failed_run_ids),
            "reconciled_group_ids": sorted(affected_group_ids),
            "next_lease_expiry_at": (
                min(deferred_lease_expiries).isoformat()
                if deferred_lease_expiries
                else ""
            ),
        }

    def _terminal_tasks_for_runs(
        self,
        run_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        clean_run_ids = list(
            dict.fromkeys(
                str(run_id or "").strip()
                for run_id in run_ids
                if str(run_id or "").strip()
            )
        )
        if not clean_run_ids:
            return {}
        result: dict[str, dict[str, Any]] = {}
        with self._db_lock:
            for offset in range(0, len(clean_run_ids), 400):
                batch = clean_run_ids[offset : offset + 400]
                placeholders = ",".join("?" for _ in batch)
                rows = self._conn.execute(
                    f"""
                    SELECT links.task_id, links.run_id, links.session_id,
                           runs.status, runs.result, runs.updated_at
                      FROM task_run_links AS links
                      JOIN runs ON runs.run_id=links.run_id
                     WHERE links.run_id IN ({placeholders})
                    """,
                    tuple(batch),
                ).fetchall()
                for row in rows:
                    task_id = str(row["task_id"] or "")
                    if not task_id:
                        continue
                    result[task_id] = {
                        "task_id": task_id,
                        "run_id": str(row["run_id"] or ""),
                        "session_id": str(row["session_id"] or ""),
                        "status": str(row["status"] or ""),
                        "result": str(row["result"] or ""),
                        "updated_at": str(row["updated_at"] or ""),
                    }
        return result

    def _agent_group_cleanup_candidate_rows_locked(self) -> list[Any]:
        return self._conn.execute(
            """
            SELECT runs.run_id, runs.run_group_id, runs.project_root_group
              FROM runs
              JOIN run_groups
                ON run_groups.run_group_id=runs.run_group_id
             WHERE run_groups.source IN ('agent', 'agent_group')
               AND run_groups.status IN (
                   'created', 'pending', 'queued', 'running', 'processing',
                   'approval_required', 'waiting_approval'
               )
               AND runs.status IN (
                   'created', 'pending', 'processing', 'running',
                   'approval_required'
               )
             ORDER BY runs.run_id
            """
        ).fetchall()

    def _reconcile_group_cleanup_run(
        self,
        run_id: str,
        *,
        recovered_at: str,
        cutoff_at: datetime | None = None,
    ) -> str:
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT * FROM runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if row is None or str(row["status"] or "") not in {
                    "created",
                    "pending",
                    "processing",
                    "running",
                    "approval_required",
                }:
                    self._conn.commit()
                    return "untouched"
                if cutoff_at is not None and not _eligible_at_cutoff(
                    row["updated_at"],
                    cutoff_at,
                ):
                    self._conn.commit()
                    return "untouched"
                if self._group_cleanup_intent_for_run_locked(row) is None:
                    self._conn.commit()
                    return "untouched"
                changed = self._fail_locked(
                    row,
                    recovered_at=recovered_at,
                    reason_code="group_partial_start_cleanup_requested",
                    message=_GROUP_CLEANUP_RECOVERY_MESSAGE,
                )
                self._conn.commit()
                return "failed" if changed else "untouched"
            except Exception:
                self._conn.rollback()
                raise

    def _group_cleanup_intent_for_run_locked(
        self,
        row: Any,
    ) -> dict[str, Any] | None:
        group_id = str(row["run_group_id"] or "").strip()
        if not group_id:
            return None
        group = self._conn.execute(
            "SELECT * FROM run_groups WHERE run_group_id=?",
            (group_id,),
        ).fetchone()
        if group is None or str(group["source"] or "") not in _AGENT_GROUP_SOURCES:
            return None
        child_run_ids = [
            str(item)
            for item in _json_list(group["child_run_ids_json"])
            if str(item).strip()
        ]
        if str(row["run_id"] or "") not in child_run_ids:
            return None
        return self._group_cleanup_intent_locked(group_id, child_run_ids)

    def _group_cleanup_intent_locked(
        self,
        group_id: str,
        child_run_ids: list[str],
    ) -> dict[str, Any] | None:
        if not child_run_ids:
            return None
        placeholders = ",".join("?" for _ in child_run_ids)
        rows = self._conn.execute(
            f"""
            SELECT payload_json
              FROM run_events
             WHERE run_id IN ({placeholders})
               AND event_type=?
             ORDER BY created_at DESC, sequence DESC
            """,
            (*child_run_ids, _GROUP_CLEANUP_REQUESTED_EVENT_TYPE),
        ).fetchall()
        for event in rows:
            payload = _json_object(event["payload_json"])
            if str(
                payload.get("run_group_id") or payload.get("group_run_id") or ""
            ) != group_id:
                continue
            if str(payload.get("cleanup_status") or "") != "requested":
                continue
            if str(payload.get("intended_terminal_status") or "") != "failed":
                continue
            return payload
        return None

    def _add_recoverable_group_id(self, target: set[str], row: Any) -> None:
        if bool(row["project_root_group"]):
            _add_group_id(target, row["run_group_id"])
            return
        group_id = str(row["run_group_id"] or "").strip()
        if not group_id:
            return
        with self._db_lock:
            group = self._conn.execute(
                "SELECT source FROM run_groups WHERE run_group_id=?",
                (group_id,),
            ).fetchone()
        if group is not None and str(group["source"] or "") in _AGENT_GROUP_SOURCES:
            _add_group_id(target, group_id)

    def _reconcile_approval(
        self,
        run_id: str,
        cutoff_at: datetime,
        recovered_at: str,
    ) -> str:
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT * FROM runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if (
                    row is None
                    or str(row["status"] or "") != "approval_required"
                    or not _eligible_at_cutoff(row["updated_at"], cutoff_at)
                ):
                    self._conn.commit()
                    return "untouched"

                if self._workflow_parent_waits_on_valid_approval_locked(
                    row,
                    cutoff_at=cutoff_at,
                ):
                    if not self._clear_preserved_approval_lease_locked(row):
                        self._conn.commit()
                        return "untouched"
                    self._conn.commit()
                    return "preserved_workflow_parent"
                pending = _json_object(row["pending_approval_json"])
                approval_id = str(pending.get("approval_id") or "").strip()
                approval = None
                if approval_id:
                    approval = self._conn.execute(
                        """
                        SELECT status
                          FROM run_approvals
                         WHERE run_id=? AND approval_id=?
                        """,
                        (run_id, approval_id),
                    ).fetchone()
                if approval is not None and str(approval["status"] or "") == "pending":
                    if not self._clear_preserved_approval_lease_locked(
                        row,
                        approval_id=approval_id,
                    ):
                        self._conn.commit()
                        return "untouched"
                    self._conn.commit()
                    return "preserved"

                reason_code = (
                    "restart_approval_resume_interrupted"
                    if approval is not None
                    else "restart_approval_state_invalid"
                )
                changed = self._fail_locked(
                    row,
                    recovered_at=recovered_at,
                    reason_code=reason_code,
                )
                self._conn.commit()
                return "failed" if changed else "untouched"
            except Exception:
                self._conn.rollback()
                raise

    def _clear_preserved_approval_lease_locked(
        self,
        row: Any,
        *,
        approval_id: str = "",
    ) -> bool:
        owner_token = str(row["async_lease_owner_token"] or "")
        expires_at = str(row["async_lease_expires_at"] or "")
        heartbeat_at = str(row["async_lease_heartbeat_at"] or "")
        if not any((owner_token, expires_at, heartbeat_at)):
            return True
        run_id = str(row["run_id"] or "")
        clean_approval_id = str(approval_id or "").strip()
        cursor = self._conn.execute(
            """
            UPDATE runs
               SET async_lease_owner_token='',
                   async_lease_expires_at='',
                   async_lease_heartbeat_at=''
             WHERE run_id=?
               AND status=?
               AND updated_at=?
               AND pending_approval_json=?
               AND async_lease_generation=?
               AND async_lease_owner_token=?
               AND async_lease_expires_at=?
               AND async_lease_heartbeat_at=?
               AND (
                    ?=''
                    OR EXISTS (
                        SELECT 1
                          FROM run_approvals
                         WHERE run_id=?
                           AND approval_id=?
                           AND status='pending'
                    )
               )
            """,
            (
                run_id,
                str(row["status"] or ""),
                str(row["updated_at"] or ""),
                str(row["pending_approval_json"] or "{}"),
                int(row["async_lease_generation"] or 0),
                owner_token,
                expires_at,
                heartbeat_at,
                clean_approval_id,
                run_id,
                clean_approval_id,
            ),
        )
        return int(cursor.rowcount or 0) == 1

    def _reconcile_active(
        self,
        run_id: str,
        cutoff_at: datetime,
        observed_at: datetime,
        recovered_at: str,
    ) -> tuple[str, datetime | None]:
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT * FROM runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if (
                    row is None
                    or str(row["status"] or "") not in _ACTIVE_RUN_STATUSES
                    or not _eligible_at_cutoff(row["updated_at"], cutoff_at)
                ):
                    self._conn.commit()
                    return "untouched", None
                if self._workflow_parent_waits_on_valid_approval_locked(
                    row,
                    cutoff_at=cutoff_at,
                ):
                    self._conn.commit()
                    return "preserved_workflow_parent", None
                owner_token = str(row["async_lease_owner_token"] or "").strip()
                lease_expires_at = str(row["async_lease_expires_at"] or "").strip()
                lease_expires_at_utc = parse_iso_utc(lease_expires_at)
                if (
                    owner_token
                    and lease_expires_at_utc is not None
                    and lease_expires_at_utc > observed_at
                ):
                    self._conn.commit()
                    return "deferred", lease_expires_at_utc

                if owner_token:
                    changed = self._fail_locked(
                        row,
                        recovered_at=recovered_at,
                        reason_code="restart_execution_lease_expired",
                        message=_LEASE_EXPIRED_MESSAGE,
                    )
                    self._conn.commit()
                    return ("failed" if changed else "untouched"), None

                started = self._conn.execute(
                    """
                    SELECT 1
                      FROM run_events
                     WHERE run_id=? AND event_type IN (
                        'agent.run.started',
                        'workflow.run.started',
                        'main_chat.run.started',
                        'run.started'
                     )
                     LIMIT 1
                    """,
                    (run_id,),
                ).fetchone()
                changed = self._fail_locked(
                    row,
                    recovered_at=recovered_at,
                    reason_code=(
                        "restart_execution_interrupted"
                        if started is not None
                        else "restart_dispatch_interrupted"
                    ),
                )
                self._conn.commit()
                return ("failed" if changed else "untouched"), None
            except Exception:
                self._conn.rollback()
                raise

    def _workflow_parent_waits_on_valid_approval_locked(
        self,
        row: Any,
        *,
        cutoff_at: datetime,
    ) -> bool:
        if str(row["kind"] or "") != "workflow_run":
            return False
        run_id = str(row["run_id"] or "")
        group_id = str(row["run_group_id"] or "").strip()
        if not run_id or not group_id:
            return False
        group = self._conn.execute(
            "SELECT child_run_ids_json FROM run_groups WHERE run_group_id=?",
            (group_id,),
        ).fetchone()
        if group is None:
            return False
        member_ids = {
            str(item)
            for item in _json_list(group["child_run_ids_json"])
            if str(item).strip()
        }
        if run_id not in member_ids:
            return False
        marker_child_ids = {
            str(event.get("child_run_id") or "").strip()
            for event in _json_list(row["timeline_json"])
            if isinstance(event, dict)
            and str(event.get("event") or "") == "workflow.run.approval_required"
            and str(event.get("child_run_id") or "").strip()
        }
        for child_id in sorted(member_ids - {run_id}):
            child = self._conn.execute(
                "SELECT * FROM runs WHERE run_id=? AND run_group_id=?",
                (child_id, group_id),
            ).fetchone()
            if (
                child is None
                or str(child["status"] or "") != "approval_required"
                or not _eligible_at_cutoff(child["updated_at"], cutoff_at)
            ):
                continue
            pending = _json_object(child["pending_approval_json"])
            parent_id = str(pending.get("workflow_run_id") or "").strip()
            if parent_id and parent_id != run_id:
                continue
            if parent_id != run_id and child_id not in marker_child_ids:
                continue
            approval_id = str(pending.get("approval_id") or "").strip()
            if not approval_id:
                continue
            approval = self._conn.execute(
                """
                SELECT status
                  FROM run_approvals
                 WHERE run_id=? AND approval_id=?
                """,
                (child_id, approval_id),
            ).fetchone()
            if approval is not None and str(approval["status"] or "") == "pending":
                return True
        return False

    def _reconcile_runtime_lease(
        self,
        run_id: str,
        *,
        observed_at: datetime,
        recovered_at: str,
    ) -> tuple[str, datetime | None]:
        for _attempt in range(2):
            with self._db_lock:
                try:
                    self._conn.execute("BEGIN IMMEDIATE")
                    row = self._conn.execute(
                        "SELECT * FROM runs WHERE run_id=?",
                        (run_id,),
                    ).fetchone()
                    if (
                        row is None
                        or str(row["status"] or "") != "running"
                        or not str(row["async_lease_owner_token"] or "").strip()
                    ):
                        self._conn.commit()
                        return "untouched", None
                    lease_expiry = parse_iso_utc(row["async_lease_expires_at"])
                    if lease_expiry is not None and lease_expiry > observed_at:
                        self._conn.commit()
                        return "deferred", lease_expiry
                    changed = self._fail_locked(
                        row,
                        recovered_at=recovered_at,
                        reason_code="restart_execution_lease_expired",
                        message=_LEASE_EXPIRED_MESSAGE,
                    )
                    self._conn.commit()
                    if changed:
                        return "failed", None
                except Exception:
                    self._conn.rollback()
                    raise
        return "untouched", None

    def _reconcile_group_projection(self, group_id: str, *, recovered_at: str) -> None:
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                group = self._conn.execute(
                    "SELECT * FROM run_groups WHERE run_group_id=?",
                    (group_id,),
                ).fetchone()
                if group is None:
                    self._conn.commit()
                    return
                root_rows = self._conn.execute(
                    """
                    SELECT *
                      FROM runs
                     WHERE run_group_id=? AND project_root_group=1
                     ORDER BY created_at, run_id
                    """,
                    (group_id,),
                ).fetchall()
                group_source = str(group["source"] or "")
                ownerless_agent_group = (
                    not root_rows and group_source in _AGENT_GROUP_SOURCES
                )
                if not root_rows and not ownerless_agent_group:
                    self._conn.commit()
                    return
                if len(root_rows) > 1:
                    raise StartupReconciliationIntegrityError(
                        "recovery_root_group_owner_ambiguous"
                    )
                rows = self._conn.execute(
                    """
                    SELECT *
                      FROM runs
                     WHERE run_group_id=?
                     ORDER BY created_at, run_id
                    """,
                    (group_id,),
                ).fetchall()
                if ownerless_agent_group:
                    child_run_ids = [
                        str(item)
                        for item in _json_list(group["child_run_ids_json"])
                        if str(item).strip()
                    ]
                    rows_by_id = {str(row["run_id"]): row for row in rows}
                    if not child_run_ids or any(
                        run_id not in rows_by_id for run_id in child_run_ids
                    ):
                        raise StartupReconciliationIntegrityError(
                            "recovery_agent_group_child_missing"
                        )
                    ordered_rows = [rows_by_id[run_id] for run_id in child_run_ids]
                    anchor = ordered_rows[0]
                    root = None
                    cleanup_intent = self._group_cleanup_intent_locked(
                        group_id,
                        child_run_ids,
                    )
                else:
                    root = root_rows[0]
                    ordered_rows = rows
                    anchor = root
                    cleanup_intent = None
                child_runs = [dict(row) for row in ordered_rows]
                root_status = (
                    _normalize_group_status(root["status"])
                    if root is not None
                    else ""
                )
                if root is not None and root_status in _TERMINAL_GROUP_STATUSES:
                    projected_status = root_status
                else:
                    projected_status = group_run_status_from_child_runs(child_runs)
                if (
                    cleanup_intent is not None
                    and projected_status in {"completed", "failed", "cancelled"}
                ):
                    projected_status = _normalize_group_status(
                        cleanup_intent.get("intended_terminal_status")
                    )
                if not projected_status:
                    self._conn.commit()
                    return
                summary = str(group["summary"] or "")
                if projected_status in {"completed", "failed", "cancelled"}:
                    if cleanup_intent is not None:
                        summary = str(cleanup_intent.get("summary") or "") or summary
                    elif root is not None and root_status in _TERMINAL_GROUP_STATUSES:
                        summary = str(root["result"] or "") or summary
                    else:
                        summary = group_run_summary_from_child_runs(child_runs) or summary
                current_status = _normalize_group_status(group["status"])
                group_event_recorded = self._group_terminal_event_recorded_locked(
                    group_id,
                    child_runs,
                    status=projected_status,
                    summary=(
                        str(group["summary"] or "")
                        if current_status in _TERMINAL_GROUP_STATUSES
                        else summary
                    ),
                )
                if current_status in _TERMINAL_GROUP_STATUSES:
                    if current_status != _normalize_group_status(projected_status):
                        raise StartupReconciliationIntegrityError(
                            "recovery_root_group_terminal_outcome_conflict"
                        )
                    if (
                        projected_status in {"completed", "failed", "cancelled"}
                        and not group_event_recorded
                    ):
                        sequence = self._append_recovery_event_locked(
                            str(anchor["run_id"]),
                            f"group.run.{projected_status}",
                            self._group_terminal_event_payload(
                                group,
                                group_id=group_id,
                                child_runs=child_runs,
                                status=projected_status,
                                summary=str(group["summary"] or summary),
                            ),
                            created_at=recovered_at,
                            expected_status=str(anchor["status"] or ""),
                            expected_updated_at=str(anchor["updated_at"] or ""),
                            fingerprint_seed=(
                                f"group-repair\0{group_id}\0{projected_status}"
                            ),
                        )
                        self._sync_task_projection_locked(
                            str(anchor["run_id"]),
                            status=str(anchor["status"] or ""),
                            sequence=sequence,
                            updated_at=recovered_at,
                        )
                    self._conn.commit()
                    return
                if (
                    projected_status == current_status
                    and summary == str(group["summary"] or "")
                ):
                    self._conn.commit()
                    return
                cursor = self._conn.execute(
                    """
                    UPDATE run_groups
                       SET status=?, summary=?, updated_at=?
                     WHERE run_group_id=? AND status=? AND updated_at=?
                    """,
                    (
                        projected_status,
                        summary,
                        recovered_at,
                        group_id,
                        str(group["status"] or ""),
                        str(group["updated_at"] or ""),
                    ),
                )
                if int(cursor.rowcount or 0) != 1:
                    raise StartupReconciliationIntegrityError(
                        "recovery_root_group_projection_cas_lost"
                    )
                if (
                    projected_status in {"completed", "failed", "cancelled"}
                    and not group_event_recorded
                ):
                    sequence = self._append_recovery_event_locked(
                        str(anchor["run_id"]),
                        f"group.run.{projected_status}",
                        self._group_terminal_event_payload(
                            group,
                            group_id=group_id,
                            child_runs=child_runs,
                            status=projected_status,
                            summary=summary,
                        ),
                        created_at=recovered_at,
                        expected_status=str(anchor["status"] or ""),
                        expected_updated_at=str(anchor["updated_at"] or ""),
                        fingerprint_seed=(
                            f"group-repair\0{group_id}\0{projected_status}"
                        ),
                    )
                    self._sync_task_projection_locked(
                        str(anchor["run_id"]),
                        status=str(anchor["status"] or ""),
                        sequence=sequence,
                        updated_at=recovered_at,
                    )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def _fail_locked(
        self,
        row: Any,
        *,
        recovered_at: str,
        reason_code: str,
        message: str = _RECOVERY_FAILURE_MESSAGE,
    ) -> bool:
        run_id = str(row["run_id"])
        previous_status = str(row["status"] or "")
        generation = int(row["async_lease_generation"] or 0)
        root_group = self._root_group_recovery_projection_locked(row, message=message)
        payload = {
            "reason_code": reason_code,
            "previous_status": previous_status,
            "recovered_at": recovered_at,
            "lease_generation": generation,
        }
        timeline = _json_list(row["timeline_json"])
        timeline.append(
            {
                "time": recovered_at,
                "event": _RECOVERY_EVENT_TYPE,
                "detail": message,
                "status": "failed",
                **payload,
            }
        )
        cursor = self._conn.execute(
            """
            UPDATE runs
               SET status='failed',
                   result=?,
                   timeline_json=?,
                   pending_approval_json='{}',
                   async_lease_owner_token='',
                   async_lease_expires_at='',
                   async_lease_heartbeat_at='',
                   updated_at=?
             WHERE run_id=?
               AND status=?
               AND updated_at=?
               AND pending_approval_json=?
               AND async_lease_generation=?
               AND async_lease_owner_token=?
               AND async_lease_expires_at=?
               AND async_lease_heartbeat_at=?
            """,
            (
                message,
                _json_dump(timeline),
                recovered_at,
                run_id,
                previous_status,
                str(row["updated_at"] or ""),
                str(row["pending_approval_json"] or "{}"),
                generation,
                str(row["async_lease_owner_token"] or ""),
                str(row["async_lease_expires_at"] or ""),
                str(row["async_lease_heartbeat_at"] or ""),
            ),
        )
        if int(cursor.rowcount or 0) != 1:
            return False

        event_fingerprint = "\0".join(
            (
                run_id,
                previous_status,
                str(row["updated_at"] or ""),
                str(generation),
                str(row["async_lease_expires_at"] or ""),
            )
        )
        event_id = "event_recovery_" + hashlib.sha256(
            event_fingerprint.encode("utf-8")
        ).hexdigest()[:16]
        sequence = self._append_recovery_event_locked(
            run_id,
            _RECOVERY_EVENT_TYPE,
            payload,
            created_at=recovered_at,
            expected_status="failed",
            expected_updated_at=recovered_at,
            fingerprint_seed=event_fingerprint,
            event_id=event_id,
        )
        for event_type, event_payload in self._terminal_failure_events_locked(
            row,
            message=message,
        ):
            sequence = self._append_recovery_event_locked(
                run_id,
                event_type,
                event_payload,
                created_at=recovered_at,
                expected_status="failed",
                expected_updated_at=recovered_at,
                fingerprint_seed=event_fingerprint,
            )
        if root_group is not None:
            group = root_group["group"]
            group_id = str(group["run_group_id"] or "")
            if root_group["needs_update"]:
                group_cursor = self._conn.execute(
                    """
                    UPDATE run_groups
                       SET status='failed', summary=?, updated_at=?
                     WHERE run_group_id=? AND status=? AND updated_at=?
                    """,
                    (
                        message,
                        recovered_at,
                        group_id,
                        str(group["status"] or ""),
                        str(group["updated_at"] or ""),
                    ),
                )
                if int(group_cursor.rowcount or 0) != 1:
                    raise StartupReconciliationIntegrityError(
                        "recovery_root_group_projection_cas_lost"
                    )
            if not root_group["event_recorded"]:
                child_runs = [
                    {
                        "run_id": child_id,
                        "status": "failed" if child_id == run_id else "",
                    }
                    for child_id in root_group["child_run_ids"]
                ]
                sequence = self._append_recovery_event_locked(
                    run_id,
                    "group.run.failed",
                    self._group_terminal_event_payload(
                        group,
                        group_id=group_id,
                        child_runs=child_runs,
                        status="failed",
                        summary=message,
                    ),
                    created_at=recovered_at,
                    expected_status="failed",
                    expected_updated_at=recovered_at,
                    fingerprint_seed=event_fingerprint,
                )
        self._sync_task_projection_locked(
            run_id,
            status="failed",
            sequence=sequence,
            updated_at=recovered_at,
        )
        self._conn.execute(
            """
            UPDATE run_approvals
               SET status='failed', resolved_at=?, updated_at=?
             WHERE run_id=? AND status='pending'
            """,
            (recovered_at, recovered_at, run_id),
        )
        return True

    def _root_group_recovery_projection_locked(
        self,
        row: Any,
        *,
        message: str,
    ) -> dict[str, Any] | None:
        if not bool(row["project_root_group"]):
            return None
        run_id = str(row["run_id"] or "")
        group_id = str(row["run_group_id"] or "").strip()
        if not group_id:
            raise StartupReconciliationIntegrityError(
                "recovery_root_group_missing"
            )
        group = self._conn.execute(
            "SELECT * FROM run_groups WHERE run_group_id=?",
            (group_id,),
        ).fetchone()
        if group is None:
            raise StartupReconciliationIntegrityError(
                "recovery_root_group_missing"
            )
        child_run_ids = [
            str(item)
            for item in _json_list(group["child_run_ids_json"])
            if str(item).strip()
        ]
        if run_id not in child_run_ids:
            raise StartupReconciliationIntegrityError(
                "recovery_root_group_owner_not_member"
            )
        current_status = _normalize_group_status(group["status"])
        needs_update = current_status not in _TERMINAL_GROUP_STATUSES
        if not needs_update and not (
            current_status == "failed"
            and str(group["summary"] or "") == str(message or "")
        ):
            raise StartupReconciliationIntegrityError(
                "recovery_root_group_terminal_outcome_conflict"
            )
        child_runs = [{"run_id": child_id} for child_id in child_run_ids]
        return {
            "group": group,
            "child_run_ids": child_run_ids,
            "event_recorded": self._group_terminal_event_recorded_locked(
                group_id,
                child_runs,
                status="failed",
                summary=message,
            ),
            "needs_update": needs_update,
        }

    def _terminal_failure_events_locked(
        self,
        row: Any,
        *,
        message: str,
    ) -> list[tuple[str, dict[str, Any]]]:
        run_id = str(row["run_id"] or "")
        kind = str(row["kind"] or "")
        if kind == "agent_run":
            canonical = [("agent.run.failed", {"error": message})]
        elif kind == "workflow_run":
            canonical = [("workflow.run.failed", {"error": message})]
        elif kind == "main_chat_run":
            link = self._conn.execute(
                "SELECT task_id, session_id FROM task_run_links WHERE run_id=?",
                (run_id,),
            ).fetchone()
            canonical = [
                (
                    "task.failed",
                    task_run_event_payload(
                        task_id=str(link["task_id"] or "") if link is not None else "",
                        run_id=run_id,
                        session_id=(
                            str(link["session_id"] or "") if link is not None else ""
                        ),
                        status="failed",
                        error=message,
                    ),
                ),
                ("run.failed", {"error": message}),
            ]
        else:
            canonical = [("run.failed", {"error": message})]
        events: list[tuple[str, dict[str, Any]]] = []
        for event_type, event_payload in canonical:
            events.append((event_type, event_payload))
            events.extend(
                (alias, event_payload)
                for alias in canonical_run_event_aliases(event_type, event_payload)
            )
        return events

    def _append_recovery_event_locked(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any],
        *,
        created_at: str,
        expected_status: str,
        expected_updated_at: str,
        fingerprint_seed: str,
        event_id: str = "",
    ) -> int:
        sequence_row = self._conn.execute(
            "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
            "FROM run_events WHERE run_id=?",
            (run_id,),
        ).fetchone()
        sequence = int(sequence_row["next_sequence"] if sequence_row is not None else 1)
        clean_event_id = str(event_id or "") or (
            "event_recovery_"
            + hashlib.sha256(
                "\0".join(
                    (fingerprint_seed, str(event_type or ""), str(sequence))
                ).encode("utf-8")
            ).hexdigest()[:20]
        )
        cursor = self._conn.execute(
            """
            INSERT INTO run_events (
                event_id, run_id, sequence, schema_version, event_type,
                actor, visibility, sensitivity, payload_json, created_at
            )
            SELECT ?, ?, ?, 1, ?, 'runtime_startup_recovery',
                   'user', 'public', ?, ?
             WHERE EXISTS (
                SELECT 1
                  FROM runs
                 WHERE run_id=? AND status=? AND updated_at=?
             )
            """,
            (
                clean_event_id,
                run_id,
                sequence,
                str(event_type or ""),
                _json_dump(redact_run_event_payload(payload)),
                created_at,
                run_id,
                expected_status,
                expected_updated_at,
            ),
        )
        if int(cursor.rowcount or 0) != 1:
            raise StartupReconciliationIntegrityError(
                "recovery_run_event_fence_mismatch"
            )
        return sequence

    def _group_terminal_event_recorded_locked(
        self,
        group_id: str,
        child_runs: list[dict[str, Any]],
        *,
        status: str,
        summary: str,
    ) -> bool:
        run_ids = [
            str(run.get("run_id") or "")
            for run in child_runs
            if str(run.get("run_id") or "")
        ]
        if not run_ids:
            return False
        event_type = f"group.run.{_normalize_group_status(status)}"
        placeholders = ",".join("?" for _ in run_ids)
        rows = self._conn.execute(
            f"""
            SELECT payload_json
              FROM run_events
             WHERE run_id IN ({placeholders}) AND event_type=?
            """,
            (*run_ids, event_type),
        ).fetchall()
        expected_status = _normalize_group_status(status)
        expected_members = frozenset(run_ids)
        for event in rows:
            payload = _json_object(event["payload_json"])
            claimed_group_ids = {
                str(payload.get(key) or "").strip()
                for key in ("run_group_id", "group_run_id")
                if str(payload.get(key) or "").strip()
            }
            raw_child_run_ids = payload.get("child_run_ids")
            child_run_ids = (
                list(raw_child_run_ids)
                if isinstance(raw_child_run_ids, list)
                else _json_list(raw_child_run_ids)
            )
            claimed_members = frozenset(
                str(run_id or "").strip()
                for run_id in child_run_ids
                if str(run_id or "").strip()
            )
            if (
                claimed_group_ids == {group_id}
                and _normalize_group_status(payload.get("status")) == expected_status
                and str(payload.get("summary") or "") == str(summary or "")
                and claimed_members == expected_members
            ):
                continue
            raise StartupReconciliationIntegrityError(
                "recovery_root_group_terminal_event_conflict"
            )
        return bool(rows)

    @staticmethod
    def _group_terminal_event_payload(
        group: Any,
        *,
        group_id: str,
        child_runs: list[dict[str, Any]],
        status: str,
        summary: str,
    ) -> dict[str, Any]:
        child_run_ids = [
            str(run.get("run_id") or "")
            for run in child_runs
            if str(run.get("run_id") or "")
        ]
        title = str(group["title"] or "")
        source = str(group["source"] or "")
        return {
            "child_run_ids": child_run_ids,
            "group_run_id": group_id,
            "objective": str(summary or title),
            "participant_count": len(child_run_ids),
            "run_group_id": group_id,
            "source": source,
            "status": _normalize_group_status(status),
            "summary": str(summary or ""),
            "title": title,
        }

    def _sync_task_projection_locked(
        self,
        run_id: str,
        *,
        status: str,
        sequence: int,
        updated_at: str,
    ) -> None:
        self._conn.execute(
            """
            UPDATE task_run_links
               SET run_status=?,
                   last_event_sequence=CASE
                       WHEN last_event_sequence < ? THEN ?
                       ELSE last_event_sequence
                   END,
                   updated_at=?
             WHERE run_id=?
            """,
            (status, sequence, sequence, updated_at, run_id),
        )


def _json_object(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(str(value or "{}"))
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _json_list(value: Any) -> list[Any]:
    try:
        parsed = json.loads(str(value or "[]"))
    except (TypeError, ValueError):
        return []
    return list(parsed) if isinstance(parsed, list) else []


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _eligible_at_cutoff(value: Any, cutoff_at: datetime) -> bool:
    parsed = parse_iso_utc(value)
    return parsed is None or parsed <= cutoff_at


def _normalize_group_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    return "cancelled" if status == "canceled" else status


def _add_group_id(target: set[str], value: Any) -> None:
    group_id = str(value or "").strip()
    if group_id:
        target.add(group_id)


def _add_owned_group_id(target: set[str], row: Any) -> None:
    if bool(row["project_root_group"]):
        _add_group_id(target, row["run_group_id"])
