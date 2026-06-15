"""Run row persistence for the Agent runtime."""

from __future__ import annotations

from typing import Any, Callable
from uuid import uuid4

_DEFAULT_UNSET = object()


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

    def insert(
        self,
        *,
        kind: str,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        client_request_id: str = "",
    ) -> dict[str, Any]:
        if not self._accepting_runs():
            raise self._error_type("Native Runtime 正在关闭，暂不接受新的 Run")
        run_id = f"{kind}_{uuid4().hex[:12]}"
        now = self._now()
        clean_client_request_id = str(client_request_id or "").strip()[:128]
        if self._contains_sensitive_text(clean_client_request_id):
            raise self._error_type("client_request_id 不能包含 API key、token 或其他敏感值")
        self._conn.execute(
            """
            INSERT INTO runs (
                run_id, run_group_id, client_request_id, kind, runnable_id,
                status, user_goal, result,
                timeline_json, artifacts_json, pending_approval_json, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                run_id,
                run_group_id,
                clean_client_request_id,
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
        self._conn.commit()
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
    ) -> dict[str, Any]:
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
        self._conn.execute(
            """
            UPDATE runs
               SET status=?, result=?, timeline_json=?, artifacts_json=?,
                   pending_approval_json=?, updated_at=?
             WHERE run_id=?
            """,
            (
                next_status,
                safe_result,
                self._json_dump(safe_timeline),
                self._json_dump(safe_artifacts),
                pending_approval_json,
                self._now(),
                run_id,
            ),
        )
        self._sync_projections(
            run_id,
            status=next_status,
            artifacts=safe_artifacts,
            pending_approval=(
                next_pending_approval if isinstance(next_pending_approval, dict) else {}
            ),
        )
        self._conn.commit()
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
