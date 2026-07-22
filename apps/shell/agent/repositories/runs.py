"""Run row persistence for the Agent runtime."""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable
from uuid import uuid4

from apps.shell.agent.repositories.sqlite import repository_transaction

_DEFAULT_UNSET = object()
_ASYNC_EXECUTION_LEASE_LOST = (
    "async execution lease lost or Run is no longer running"
)


class RunRepository:
    """Source of truth for native run lifecycle rows."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        row_to_run: Callable[[Any], dict[str, Any]],
        accepting_runs: Callable[[], bool],
        sync_projections: Callable[..., Any],
        append_run_to_group: Callable[[str, str], Any],
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        json_load: Callable[[str, Any], Any],
        redact_secrets: Callable[[Any], str],
        redact_json_value: Callable[[Any], Any],
        contains_sensitive_text: Callable[[str], bool],
        error_type: type[Exception] = RuntimeError,
        unset_sentinel: object = _DEFAULT_UNSET,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_run = row_to_run
        self._accepting_runs = accepting_runs
        self._sync_projections = sync_projections
        self._append_run_to_group = append_run_to_group
        self._now = now
        self._json_dump = json_dump
        self._json_load = json_load
        self._redact_secrets = redact_secrets
        self._redact_json_value = redact_json_value
        self._contains_sensitive_text = contains_sensitive_text
        self._error_type = error_type
        self._unset_sentinel = unset_sentinel
        self._execution_lease_local = threading.local()
        self._async_lease_schema_available: bool | None = None
        self._project_root_group_schema_available: bool | None = None

    def _has_async_execution_lease_schema(self) -> bool:
        cached = self._async_lease_schema_available
        if cached is not None:
            return cached
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        available = {
            "async_lease_generation",
            "async_lease_owner_token",
            "async_lease_expires_at",
            "async_lease_heartbeat_at",
        } <= columns
        self._async_lease_schema_available = available
        return available

    def _has_project_root_group_schema(self) -> bool:
        cached = self._project_root_group_schema_available
        if cached is not None:
            return cached
        columns = {
            str(row["name"])
            for row in self._conn.execute("PRAGMA table_info(runs)").fetchall()
        }
        available = "project_root_group" in columns
        self._project_root_group_schema_available = available
        return available

    def list(self, limit: int = 50) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute(
            """
            SELECT runs.*, run_groups.source AS run_group_source
             FROM runs
              LEFT JOIN run_groups ON run_groups.run_group_id = runs.run_group_id
             WHERE NOT (
                runs.kind = 'agent_run'
                AND runs.run_group_id != ''
                AND EXISTS (
                    SELECT 1
                      FROM runs workflow_parent
                     WHERE workflow_parent.run_group_id = runs.run_group_id
                       AND workflow_parent.kind = 'workflow_run'
                )
             )
             ORDER BY runs.updated_at DESC
             LIMIT ?
            """,
            (max(1, min(int(limit or 50), 200)),),
        ).fetchall()
        return {"ok": True, "runs": [self._row_to_run(row) for row in rows]}

    def get(self, run_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute("SELECT * FROM runs WHERE run_id=?", (run_id,)).fetchone()
        if row is None:
            raise KeyError(run_id)
        return self._row_to_run(row)

    def pending_approval_json(self, run_id: str) -> str:
        self._ensure_row_factory()
        row = self._conn.execute(
            "SELECT pending_approval_json FROM runs WHERE run_id=?",
            (run_id,),
        ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return str(row["pending_approval_json"] or "{}")

    def pending_approval_private(self, run_id: str) -> dict[str, Any]:
        pending = self._json_load(self.pending_approval_json(run_id), {})
        return pending if isinstance(pending, dict) else {}

    def by_client_request_id(self, client_request_id: str) -> dict[str, Any] | None:
        clean_id = str(client_request_id or "").strip()
        if not clean_id:
            return None
        self._ensure_row_factory()
        row = self._conn.execute(
            "SELECT * FROM runs WHERE client_request_id=? LIMIT 1",
            (clean_id,),
        ).fetchone()
        if row is None:
            return None
        run = self._row_to_run(row)
        run["idempotent"] = True
        return run

    def async_execution_lease_by_client_request_id(
        self,
        client_request_id: str,
    ) -> tuple[dict[str, Any], int, str, str] | None:
        """Returns public Run data plus private lease identity for async claiming."""

        clean_id = str(client_request_id or "").strip()
        if not clean_id:
            return None
        self._ensure_row_factory()
        row = self._conn.execute(
            "SELECT * FROM runs WHERE client_request_id=? LIMIT 1",
            (clean_id,),
        ).fetchone()
        if row is None:
            return None
        run = self._row_to_run(row)
        run["idempotent"] = True
        return (
            run,
            int(row["async_lease_generation"] or 0),
            str(row["async_lease_owner_token"] or ""),
            str(row["async_lease_expires_at"] or ""),
        )

    def try_take_over_async_execution_lease(
        self,
        run_id: str,
        *,
        expected_generation: int,
        expected_owner_token: str,
        expected_expires_at: str,
        owner_token: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> dict[str, Any] | None:
        """Atomically takes an expired running lease using generation/token CAS."""

        clean_run_id = str(run_id or "").strip()
        clean_owner_token = str(owner_token or "").strip()[:128]
        if not clean_run_id or not clean_owner_token:
            return None
        cursor = self._conn.execute(
            """
            UPDATE runs
               SET async_lease_generation=?, async_lease_owner_token=?,
                   async_lease_expires_at=?, async_lease_heartbeat_at=?, updated_at=?
             WHERE run_id=?
               AND status='running'
               AND async_lease_generation=?
               AND async_lease_owner_token=?
               AND async_lease_expires_at=?
               AND (async_lease_expires_at='' OR async_lease_expires_at<=?)
            """,
            (
                max(0, int(expected_generation)) + 1,
                clean_owner_token,
                str(lease_expires_at or ""),
                str(heartbeat_at or ""),
                self._now(),
                clean_run_id,
                max(0, int(expected_generation)),
                str(expected_owner_token or ""),
                str(expected_expires_at or ""),
                str(heartbeat_at or ""),
            ),
        )
        self._conn.commit()
        if cursor.rowcount != 1:
            return None
        return self.get(clean_run_id)

    def renew_async_execution_lease(
        self,
        run_id: str,
        *,
        generation: int,
        owner_token: str,
        heartbeat_at: str,
        lease_expires_at: str,
    ) -> bool:
        cursor = self._conn.execute(
            """
            UPDATE runs
               SET async_lease_expires_at=?, async_lease_heartbeat_at=?
             WHERE run_id=?
               AND status='running'
               AND async_lease_generation=?
               AND async_lease_owner_token=?
            """,
            (
                str(lease_expires_at or ""),
                str(heartbeat_at or ""),
                str(run_id or "").strip(),
                max(0, int(generation)),
                str(owner_token or ""),
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def owns_async_execution_lease(
        self,
        run_id: str,
        *,
        generation: int,
        owner_token: str,
    ) -> bool:
        row = self._conn.execute(
            """
            SELECT 1
             FROM runs
             WHERE run_id=?
               AND async_lease_generation=?
               AND async_lease_owner_token=?
             LIMIT 1
            """,
            (
                str(run_id or "").strip(),
                max(0, int(generation)),
                str(owner_token or ""),
            ),
        ).fetchone()
        return row is not None

    def release_async_execution_lease(
        self,
        run_id: str,
        *,
        generation: int,
        owner_token: str,
    ) -> bool:
        cursor = self._conn.execute(
            """
            UPDATE runs
               SET async_lease_owner_token='', async_lease_expires_at='',
                   async_lease_heartbeat_at=''
             WHERE run_id=?
               AND status!='running'
               AND async_lease_generation=?
               AND async_lease_owner_token=?
            """,
            (
                str(run_id or "").strip(),
                max(0, int(generation)),
                str(owner_token or ""),
            ),
        )
        self._conn.commit()
        return cursor.rowcount == 1

    def assert_bound_async_execution_active(
        self,
        run_id: str = "",
        *,
        require_running: bool = True,
    ) -> None:
        """Fail closed when the current executor thread no longer owns its Run."""

        bound_lease = getattr(self._execution_lease_local, "value", None)
        if not isinstance(bound_lease, tuple) or len(bound_lease) < 3:
            return
        bound_run_id = str(bound_lease[0] or "").strip()
        clean_run_id = str(run_id or "").strip()
        if clean_run_id and clean_run_id != bound_run_id:
            raise self._error_type(_ASYNC_EXECUTION_LEASE_LOST)
        cancellation_event = bound_lease[3] if len(bound_lease) >= 4 else None
        if (
            cancellation_event is not None
            and callable(getattr(cancellation_event, "is_set", None))
            and cancellation_event.is_set()
        ):
            raise self._error_type(_ASYNC_EXECUTION_LEASE_LOST)
        row = self._conn.execute(
            f"""
            SELECT 1
              FROM runs
             WHERE run_id=?
               {"AND status='running'" if require_running else ""}
               AND async_lease_generation=?
               AND async_lease_owner_token=?
             LIMIT 1
            """,
            (
                bound_run_id,
                max(0, int(bound_lease[1])),
                str(bound_lease[2] or ""),
            ),
        ).fetchone()
        if row is None:
            raise self._error_type(_ASYNC_EXECUTION_LEASE_LOST)

    @contextmanager
    def bind_async_execution_lease(
        self,
        run_id: str,
        *,
        generation: int,
        owner_token: str,
        cancellation_event: Any | None = None,
    ) -> Any:
        """Fences RunRepository writes made by the current executor thread."""

        previous = getattr(self._execution_lease_local, "value", None)
        self._execution_lease_local.value = (
            str(run_id or "").strip(),
            max(0, int(generation)),
            str(owner_token or ""),
            cancellation_event,
        )
        try:
            yield
        finally:
            if previous is None:
                try:
                    del self._execution_lease_local.value
                except AttributeError:
                    pass
            else:
                self._execution_lease_local.value = previous

    def insert(
        self,
        *,
        kind: str,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        client_request_id: str = "",
        project_root_group: bool = False,
        async_lease_generation: int = 0,
        async_lease_owner_token: str = "",
        async_lease_expires_at: str = "",
        async_lease_heartbeat_at: str = "",
    ) -> dict[str, Any]:
        with repository_transaction(self._conn):
            return self._insert_in_transaction(
                kind=kind,
                runnable_id=runnable_id,
                user_goal=user_goal,
                run_group_id=run_group_id,
                client_request_id=client_request_id,
                project_root_group=project_root_group,
                async_lease_generation=async_lease_generation,
                async_lease_owner_token=async_lease_owner_token,
                async_lease_expires_at=async_lease_expires_at,
                async_lease_heartbeat_at=async_lease_heartbeat_at,
            )

    def _insert_in_transaction(
        self,
        *,
        kind: str,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        client_request_id: str = "",
        project_root_group: bool = False,
        async_lease_generation: int = 0,
        async_lease_owner_token: str = "",
        async_lease_expires_at: str = "",
        async_lease_heartbeat_at: str = "",
    ) -> dict[str, Any]:
        if not self._accepting_runs():
            raise self._error_type("Native Runtime 正在关闭，暂不接受新的 Run")
        run_id = f"{kind}_{uuid4().hex[:12]}"
        now = self._now()
        clean_client_request_id = str(client_request_id or "").strip()[:128]
        if self._contains_sensitive_text(clean_client_request_id):
            raise self._error_type("client_request_id 不能包含 API key、token 或其他敏感值")
        has_project_root_group = self._has_project_root_group_schema()
        if self._has_async_execution_lease_schema() and has_project_root_group:
            self._conn.execute(
                """
            INSERT INTO runs (
                run_id, run_group_id, client_request_id,
                project_root_group,
                async_lease_generation, async_lease_owner_token,
                async_lease_expires_at, async_lease_heartbeat_at,
                kind, runnable_id,
                status, user_goal, result,
                timeline_json, artifacts_json, pending_approval_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    run_group_id,
                    clean_client_request_id,
                    1 if project_root_group else 0,
                    max(0, int(async_lease_generation or 0)),
                    str(async_lease_owner_token or "").strip()[:128],
                    str(async_lease_expires_at or ""),
                    str(async_lease_heartbeat_at or ""),
                    kind,
                    runnable_id,
                    "running",
                    self._redact_secrets(user_goal),
                    "",
                    "[]",
                    "[]",
                    "{}",
                    now,
                    now,
                ),
            )
        elif self._has_async_execution_lease_schema():
            self._conn.execute(
                """
            INSERT INTO runs (
                run_id, run_group_id, client_request_id,
                async_lease_generation, async_lease_owner_token,
                async_lease_expires_at, async_lease_heartbeat_at,
                kind, runnable_id,
                status, user_goal, result,
                timeline_json, artifacts_json, pending_approval_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    run_group_id,
                    clean_client_request_id,
                    max(0, int(async_lease_generation or 0)),
                    str(async_lease_owner_token or "").strip()[:128],
                    str(async_lease_expires_at or ""),
                    str(async_lease_heartbeat_at or ""),
                    kind,
                    runnable_id,
                    "running",
                    self._redact_secrets(user_goal),
                    "",
                    "[]",
                    "[]",
                    "{}",
                    now,
                    now,
                ),
            )
        else:
            if async_lease_owner_token:
                raise self._error_type("async execution lease schema is unavailable")
            columns = ["run_id", "run_group_id", "client_request_id"]
            params: list[Any] = [
                run_id,
                run_group_id,
                clean_client_request_id,
            ]
            if has_project_root_group:
                columns.append("project_root_group")
                params.append(1 if project_root_group else 0)
            columns.extend(
                [
                    "kind",
                    "runnable_id",
                    "status",
                    "user_goal",
                    "result",
                    "timeline_json",
                    "artifacts_json",
                    "pending_approval_json",
                    "created_at",
                    "updated_at",
                ]
            )
            params.extend(
                [
                    kind,
                    runnable_id,
                    "running",
                    self._redact_secrets(user_goal),
                    "",
                    "[]",
                    "[]",
                    "{}",
                    now,
                    now,
                ]
            )
            self._conn.execute(
                f"INSERT INTO runs ({', '.join(columns)}) "
                f"VALUES ({', '.join('?' for _column in columns)})",
                tuple(params),
            )
        self._append_run_to_group(run_group_id, run_id)
        return self.get(run_id)

    def update(
        self,
        run_id: str,
        *,
        status: str | None = None,
        result: str | None = None,
        timeline: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        pending_approval: dict[str, Any] | None | object = _DEFAULT_UNSET,
        expected_status: str | None = None,
        expected_approval_id: str = "",
        expected_updated_at: str | None = None,
        expected_pending_approval_absent: bool = False,
    ) -> dict[str, Any] | None:
        with repository_transaction(self._conn):
            return self._update_in_transaction(
                run_id,
                status=status,
                result=result,
                timeline=timeline,
                artifacts=artifacts,
                pending_approval=pending_approval,
                expected_status=expected_status,
                expected_approval_id=expected_approval_id,
                expected_updated_at=expected_updated_at,
                expected_pending_approval_absent=expected_pending_approval_absent,
            )

    def _update_in_transaction(
        self,
        run_id: str,
        *,
        status: str | None = None,
        result: str | None = None,
        timeline: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        pending_approval: dict[str, Any] | None | object = _DEFAULT_UNSET,
        expected_status: str | None = None,
        expected_approval_id: str = "",
        expected_updated_at: str | None = None,
        expected_pending_approval_absent: bool = False,
    ) -> dict[str, Any] | None:
        current = self.get(run_id)
        if pending_approval is self._unset_sentinel or pending_approval is _DEFAULT_UNSET:
            pending_approval_json = self.pending_approval_json(run_id)
            next_pending_approval = self._json_load(pending_approval_json, {})
        else:
            next_pending_approval = self._redact_json_value(pending_approval or {})
            pending_approval_json = self._json_dump(next_pending_approval)
        safe_result = self._redact_secrets(result) if result is not None else current["result"]
        safe_timeline = self._redact_json_value(
            timeline if timeline is not None else current["timeline"],
        )
        safe_artifacts = self._redact_json_value(
            artifacts if artifacts is not None else current["artifacts"],
        )
        next_status = status or current["status"]
        bound_lease = getattr(self._execution_lease_local, "value", None)
        fenced_lease = (
            bound_lease
            if isinstance(bound_lease, tuple)
            and len(bound_lease) >= 3
            and str(bound_lease[0] or "") == str(run_id or "")
            else None
        )
        if fenced_lease is not None:
            self.assert_bound_async_execution_active(run_id)
        where_clause = "run_id=?"
        reset_unbound_terminal_lease = (
            fenced_lease is None
            and next_status in {"cancelled", "canceled", "completed", "failed"}
            and self._has_async_execution_lease_schema()
        )
        lease_reset_clause = (
            ", async_lease_owner_token='', async_lease_expires_at='',"
            " async_lease_heartbeat_at=''"
            if reset_unbound_terminal_lease
            else ""
        )
        params: list[Any] = [
            next_status,
            safe_result,
            self._json_dump(safe_timeline),
            self._json_dump(safe_artifacts),
            pending_approval_json,
            self._now(),
            run_id,
        ]
        clean_expected_status = str(expected_status or "").strip()
        clean_expected_approval_id = str(expected_approval_id or "").strip()
        clean_expected_updated_at = (
            None if expected_updated_at is None else str(expected_updated_at)
        )
        if clean_expected_approval_id and not clean_expected_status:
            raise self._error_type(
                "approval resume CAS requires expected Run status"
            )
        if clean_expected_status:
            where_clause += " AND status=?"
            params.append(clean_expected_status)
        if clean_expected_approval_id:
            if clean_expected_status == "approval_required":
                where_clause += (
                    " AND COALESCE("
                    "json_extract(pending_approval_json, '$.approval_id'), ''"
                    ")=?"
                )
            else:
                where_clause += (
                    " AND EXISTS ("
                    "SELECT 1 FROM run_approvals"
                    " WHERE run_approvals.run_id=runs.run_id"
                    " AND run_approvals.approval_id=?"
                    " AND run_approvals.status='approved'"
                    ")"
                )
            params.append(clean_expected_approval_id)
        if clean_expected_updated_at is not None:
            where_clause += " AND updated_at=?"
            params.append(clean_expected_updated_at)
        if expected_pending_approval_absent:
            where_clause += " AND TRIM(pending_approval_json)='{}'"
        if fenced_lease is not None:
            where_clause += (
                " AND status='running'"
                " AND async_lease_generation=? AND async_lease_owner_token=?"
            )
            params.extend([int(fenced_lease[1]), str(fenced_lease[2])])
        cursor = self._conn.execute(
            f"""
            UPDATE runs
               SET status=?, result=?, timeline_json=?, artifacts_json=?,
                   pending_approval_json=?, updated_at=?{lease_reset_clause}
             WHERE {where_clause}
            """,
            tuple(params),
        )
        if fenced_lease is not None and cursor.rowcount != 1:
            self._conn.rollback()
            raise self._error_type(_ASYNC_EXECUTION_LEASE_LOST)
        has_cas_predicate = bool(
            clean_expected_status
            or clean_expected_approval_id
            or clean_expected_updated_at is not None
            or expected_pending_approval_absent
        )
        if has_cas_predicate and cursor.rowcount != 1:
            approval_resume_lost_to_terminal_transition = bool(
                clean_expected_status == "approval_required"
                and clean_expected_approval_id
                and str(current.get("status") or "")
                in {"cancelled", "canceled", "completed", "failed"}
            )
            if not approval_resume_lost_to_terminal_transition:
                self._conn.rollback()
            return None
        self._sync_projections(
            run_id,
            status=next_status,
            artifacts=safe_artifacts,
            pending_approval=(
                next_pending_approval if isinstance(next_pending_approval, dict) else {}
            ),
        )
        return self.get(run_id)

    def delete_rows(self, runs: list[dict[str, Any]], *, delete_artifacts: Any) -> list[str]:
        deleted_run_ids: list[str] = []
        for run in runs:
            run_id = str(run.get("run_id") or "")
            if not run_id:
                continue
            if callable(delete_artifacts):
                delete_artifacts(run)
            self._conn.execute("DELETE FROM runs WHERE run_id=?", (run_id,))
            deleted_run_ids.append(run_id)
        return deleted_run_ids
