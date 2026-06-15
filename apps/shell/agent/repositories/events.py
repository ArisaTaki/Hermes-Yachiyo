"""Run event persistence for the Agent runtime."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Callable
from uuid import uuid4

from apps.shell.agent.runtime.events import redact_run_event_payload


class RunEventRepository:
    """Durable, replayable execution fact log for native runs."""

    def __init__(
        self,
        conn: Any,
        db_lock: Any,
        *,
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        json_load: Callable[[str, Any], Any],
        error_type: type[Exception] = RuntimeError,
        ensure_run_exists: Callable[[str], Any] | None = None,
        sync_event_cursor: Callable[..., Any] | None = None,
    ) -> None:
        self._conn = conn
        self._db_lock = db_lock
        self._now = now
        self._json_dump = json_dump
        self._json_load = json_load
        self._error_type = error_type
        self._ensure_run_exists = ensure_run_exists
        self._sync_event_cursor = sync_event_cursor

    def append(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        clean_event_type = str(event_type or "").strip()
        if not clean_run_id or not clean_event_type:
            raise self._error_type("RunEvent 缺少 run_id 或 event_type")

        event_id = f"event_{uuid4().hex[:16]}"
        created_at = self._now()
        safe_payload = redact_run_event_payload(deepcopy(payload or {}))
        visibility_text = str(visibility or "").strip()
        sensitivity_text = str(sensitivity or "").strip()
        normalized_visibility = "internal" if visibility_text == "internal" else "user"
        normalized_sensitivity = "secret" if sensitivity_text == "secret" else "public"

        with self._db_lock:
            try:
                self._conn.execute("BEGIN IMMEDIATE")
                row = self._conn.execute(
                    "SELECT COALESCE(MAX(sequence), 0) + 1 AS next_sequence "
                    "FROM run_events WHERE run_id=?",
                    (clean_run_id,),
                ).fetchone()
                sequence = int(row["next_sequence"] if row is not None else 1)
                self._conn.execute(
                    """
                    INSERT INTO run_events (
                        event_id, run_id, sequence, schema_version, event_type,
                        actor, visibility, sensitivity, payload_json, created_at
                    ) VALUES (?, ?, ?, 1, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        event_id,
                        clean_run_id,
                        sequence,
                        clean_event_type,
                        str(actor or "native_runtime"),
                        normalized_visibility,
                        normalized_sensitivity,
                        self._json_dump(safe_payload),
                        created_at,
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise
            if callable(self._sync_event_cursor):
                self._sync_event_cursor(clean_run_id, sequence=sequence)

        event = {
            "event_id": event_id,
            "run_id": clean_run_id,
            "sequence": sequence,
            "schema_version": 1,
            "event_type": clean_event_type,
            "actor": str(actor or "native_runtime"),
            "visibility": normalized_visibility,
            "sensitivity": normalized_sensitivity,
            "payload": safe_payload,
            "created_at": created_at,
        }
        return event

    def list(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        if callable(self._ensure_run_exists):
            self._ensure_run_exists(clean_run_id)
        safe_after_sequence = max(0, int(after_sequence or 0))
        safe_limit = max(1, min(int(limit or 200), 1000))
        params: list[Any] = [clean_run_id, safe_after_sequence]
        visibility_clause = ""
        if not include_internal:
            visibility_clause = " AND visibility='user' AND sensitivity!='secret'"
        params.append(safe_limit)
        rows = self._conn.execute(
            f"""
            SELECT * FROM run_events
             WHERE run_id=? AND sequence>?{visibility_clause}
             ORDER BY sequence ASC
             LIMIT ?
            """,
            tuple(params),
        ).fetchall()
        return {
            "ok": True,
            "run_id": clean_run_id,
            "after_sequence": safe_after_sequence,
            "limit": safe_limit,
            "events": [
                {
                    "event_id": str(row["event_id"]),
                    "run_id": str(row["run_id"]),
                    "sequence": int(row["sequence"]),
                    "schema_version": int(row["schema_version"]),
                    "event_type": str(row["event_type"]),
                    "actor": str(row["actor"]),
                    "visibility": str(row["visibility"]),
                    "sensitivity": str(row["sensitivity"]),
                    "payload": self._json_load(row["payload_json"], {}),
                    "created_at": str(row["created_at"]),
                }
                for row in rows
            ],
        }
