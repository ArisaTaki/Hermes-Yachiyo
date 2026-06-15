"""Approval projection persistence for Agent runtime runs."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class ApprovalRepository:
    """Projection store for user-visible and idempotent run approvals."""

    def __init__(
        self,
        conn: Any,
        db_lock: Any,
        *,
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        public_pending_approval: Callable[[Any], dict[str, Any]],
    ) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._now = now
        self._json_dump = json_dump
        self._public_pending_approval = public_pending_approval

    def sync(self, run_id: str, *, status: str, pending_approval: dict[str, Any]) -> None:
        if pending_approval:
            self.upsert_pending(run_id, pending_approval)
            return
        self.resolve_pending(run_id, status=status)

    def upsert_pending(self, run_id: str, pending_approval: dict[str, Any]) -> None:
        public = self._public_pending_approval(pending_approval)
        approval_id = str(pending_approval.get("approval_id") or f"approval_{run_id}").strip()
        requested_at = str(pending_approval.get("requested_at") or self._now())
        self._conn.execute(
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

    def claim_pending_approval(self, run_id: str, pending_approval: dict[str, Any]) -> bool:
        approval_id = str(pending_approval.get("approval_id") or f"approval_{run_id}").strip()
        if not approval_id:
            return False
        public = self._public_pending_approval(pending_approval)
        now = self._now()
        requested_at = str(pending_approval.get("requested_at") or now)
        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT status FROM run_approvals WHERE approval_id=? AND run_id=?",
                    (approval_id, run_id),
                ).fetchone()
                if row is None:
                    self._conn.execute(
                        """
                        INSERT INTO run_approvals (
                            approval_id, run_id, status, tool, input_preview_json, payload_json,
                            requested_at, resolved_at, updated_at
                        ) VALUES (?, ?, 'pending', ?, ?, ?, ?, '', ?)
                        """,
                        (
                            approval_id,
                            run_id,
                            str(public.get("tool") or "")[:120],
                            self._json_dump(public.get("input_preview") or {}),
                            self._json_dump(public),
                            requested_at,
                            now,
                        ),
                    )
                    current_status = "pending"
                else:
                    current_status = str(row["status"] or "")
                if current_status != "pending":
                    self._conn.commit()
                    return False
                cursor = self._conn.execute(
                    """
                    UPDATE run_approvals
                       SET status='approved',
                           resolved_at=CASE WHEN resolved_at='' THEN ? ELSE resolved_at END,
                           updated_at=?
                     WHERE approval_id=? AND run_id=? AND status='pending'
                    """,
                    (now, now, approval_id, run_id),
                )
                claimed = int(cursor.rowcount or 0) == 1
                self._conn.commit()
                return claimed
            except Exception:
                self._conn.rollback()
                raise

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
