"""Approval projection persistence for Agent runtime runs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.repositories.sqlite import repository_transaction


class ApprovalRepository:
    """Projection store for user-visible and idempotent run approvals."""

    def __init__(
        self,
        conn: Any,
        db_lock: Any,
        *,
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        json_load: Callable[[Any, Any], Any],
        public_pending_approval: Callable[[Any], dict[str, Any]],
        error_type: type[Exception],
    ) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._now = now
        self._json_dump = json_dump
        self._json_load = json_load
        self._public_pending_approval = public_pending_approval
        self._error_type = error_type

    def sync(self, run_id: str, *, status: str, pending_approval: dict[str, Any]) -> None:
        if pending_approval:
            self.upsert_pending(run_id, pending_approval)
            return
        self.resolve_pending(run_id, status=status)

    def upsert_pending(self, run_id: str, pending_approval: dict[str, Any]) -> None:
        public = self._public_pending_approval(pending_approval)
        approval_id = str(pending_approval.get("approval_id") or f"approval_{run_id}").strip()
        requested_at = str(pending_approval.get("requested_at") or self._now())
        cursor = self._conn.execute(
            """
            INSERT INTO run_approvals (
                approval_id, run_id, status, tool, input_preview_json, payload_json,
                requested_at, resolved_at, updated_at
            ) VALUES (?, ?, 'pending', ?, ?, ?, ?, '', ?)
            ON CONFLICT(approval_id) DO UPDATE SET
                status='pending',
                tool=excluded.tool,
                input_preview_json=excluded.input_preview_json,
                payload_json=excluded.payload_json,
                requested_at=excluded.requested_at,
                resolved_at='',
                updated_at=excluded.updated_at
            WHERE run_approvals.run_id=excluded.run_id
              AND run_approvals.status='pending'
            """,
            (
                approval_id,
                run_id,
                str(public.get("tool") or "")[:120],
                self._json_dump(public.get("input_preview") or {}),
                self._json_dump(public),
                requested_at,
                self._now(),
            ),
        )
        if int(cursor.rowcount or 0) != 1:
            self._conn.rollback()
            raise self._error_type("approval_generation_conflict")

    def claim_pending_approval(
        self,
        run_id: str,
        pending_approval: dict[str, Any],
        *,
        expected_approval_id: str,
    ) -> bool:
        return self._claim_pending_decision(
            run_id,
            pending_approval,
            expected_approval_id=expected_approval_id,
            claimed_status="approved",
        )

    def claim_pending_rejection(
        self,
        run_id: str,
        pending_approval: dict[str, Any],
        *,
        expected_approval_id: str,
    ) -> bool:
        return self._claim_pending_decision(
            run_id,
            pending_approval,
            expected_approval_id=expected_approval_id,
            claimed_status="rejected",
        )

    def claim_pending_timeout(
        self,
        run_id: str,
        pending_approval: dict[str, Any],
        *,
        expected_approval_id: str,
    ) -> bool:
        return self._claim_pending_decision(
            run_id,
            pending_approval,
            expected_approval_id=expected_approval_id,
            claimed_status="cancelled",
        )

    def assert_approval_resume_active(
        self,
        run_id: str,
        expected_approval_id: str,
    ) -> None:
        expected_id = str(expected_approval_id or "").strip()
        if not expected_id:
            raise self._error_type("approval_expected_id_required")
        with self._db_lock:
            row = self._conn.execute(
                """
                SELECT 1
                  FROM runs
                  JOIN run_approvals
                    ON run_approvals.run_id=runs.run_id
                   AND run_approvals.approval_id=?
                   AND run_approvals.status='approved'
                 WHERE runs.run_id=?
                   AND runs.status='running'
                 LIMIT 1
                """,
                (expected_id, run_id),
            ).fetchone()
        if row is None:
            raise self._error_type("approval_resume_inactive")

    def _claim_pending_decision(
        self,
        run_id: str,
        pending_approval: dict[str, Any],
        *,
        expected_approval_id: str,
        claimed_status: str,
    ) -> bool:
        expected_id = str(expected_approval_id or "").strip()
        if not expected_id:
            raise self._error_type("approval_expected_id_required")
        pending_id = str(pending_approval.get("approval_id") or "").strip()
        if pending_id and pending_id != expected_id:
            raise self._error_type("approval_generation_mismatch")
        now = self._now()
        with self._db_lock:
            with repository_transaction(self._conn):
                run_row = self._conn.execute(
                    "SELECT status, pending_approval_json FROM runs WHERE run_id=?",
                    (run_id,),
                ).fetchone()
                if run_row is None or str(run_row["status"] or "") != "approval_required":
                    return False
                current_pending = self._json_load(
                    str(run_row["pending_approval_json"] or "{}"),
                    {},
                )
                current_id = str(
                    current_pending.get("approval_id")
                    if isinstance(current_pending, dict)
                    else ""
                ).strip()
                if current_id != expected_id:
                    raise self._error_type("approval_generation_mismatch")
                row = self._conn.execute(
                    """
                    SELECT status
                      FROM run_approvals
                     WHERE run_id=? AND approval_id=?
                    """,
                    (run_id, expected_id),
                ).fetchone()
                if row is None:
                    raise self._error_type("approval_generation_projection_missing")
                if str(row["status"] or "") != "pending":
                    return False
                cursor = self._conn.execute(
                    """
                    UPDATE run_approvals
                       SET status=?,
                           resolved_at=CASE WHEN resolved_at='' THEN ? ELSE resolved_at END,
                           updated_at=?
                     WHERE approval_id=? AND run_id=? AND status='pending'
                    """,
                    (claimed_status, now, now, expected_id, run_id),
                )
                claimed = int(cursor.rowcount or 0) == 1
                if claimed and claimed_status == "approved":
                    # Exactly one approved generation may authorize a running
                    # continuation. Consume both older approvals and orphaned
                    # pending projections only after the current generation's
                    # CAS wins. The enclosing claim + Run projection UoW rolls
                    # this back atomically if the Run cannot become running.
                    self._conn.execute(
                        """
                        UPDATE run_approvals
                           SET status='consumed',
                               resolved_at=CASE
                                   WHEN resolved_at='' THEN ?
                                   ELSE resolved_at
                               END,
                               updated_at=?
                         WHERE run_id=?
                           AND approval_id<>?
                           AND status IN ('pending', 'approved')
                        """,
                        (now, now, run_id, expected_id),
                    )
                return claimed

    def resolve_pending(self, run_id: str, *, status: str) -> None:
        resolved_status = (
            "approved"
            if status in {"running", "completed"}
            else "cancelled"
            if status == "cancelled"
            else "resolved"
        )
        now = self._now()
        self._conn.execute(
            """
            UPDATE run_approvals
               SET status=?, resolved_at=CASE WHEN resolved_at='' THEN ? ELSE resolved_at END,
                   updated_at=?
             WHERE run_id=? AND status='pending'
            """,
            (resolved_status, now, now, run_id),
        )
