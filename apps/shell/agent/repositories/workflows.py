"""Workflow definition persistence for the Agent runtime."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class WorkflowRepository:
    """Stores Workflow definitions while engine callbacks keep validation policy."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        row_to_workflow: Callable[[Any], dict[str, Any]],
        now: Callable[[], str],
        json_dump: Callable[[Any], str],
        workflow_id_factory: Callable[[str], str],
        ensure_global_name_available: Callable[..., Any],
        validate_workflow: Callable[[list[dict[str, Any]], list[dict[str, Any]]], Any],
        validate_workflow_agent_nodes: Callable[[list[dict[str, Any]]], Any],
        validate_workflow_subworkflow_nodes: Callable[..., Any],
        record_studio_deletion: Callable[[str, str], Any],
        clear_studio_deletion: Callable[[str, str], Any],
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._row_to_workflow = row_to_workflow
        self._now = now
        self._json_dump = json_dump
        self._workflow_id_factory = workflow_id_factory
        self._ensure_global_name_available = ensure_global_name_available
        self._validate_workflow = validate_workflow
        self._validate_workflow_agent_nodes = validate_workflow_agent_nodes
        self._validate_workflow_subworkflow_nodes = validate_workflow_subworkflow_nodes
        self._record_studio_deletion = record_studio_deletion
        self._clear_studio_deletion = clear_studio_deletion

    def list(self) -> dict[str, Any]:
        self._ensure_row_factory()
        rows = self._conn.execute("SELECT * FROM workflows ORDER BY updated_at DESC").fetchall()
        return {"ok": True, "workflows": [self._row_to_workflow(row) for row in rows]}

    def get(self, workflow_id: str) -> dict[str, Any]:
        self._ensure_row_factory()
        row = self._conn.execute(
            "SELECT * FROM workflows WHERE workflow_id=?",
            (workflow_id,),
        ).fetchone()
        if row is None:
            raise KeyError(workflow_id)
        return self._row_to_workflow(row)

    def create(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        name = str(payload.get("name") or "").strip()
        self._ensure_global_name_available(name)
        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        workflow_id = str(payload.get("workflow_id") or self._workflow_id_factory(name))
        self._validate_workflow(nodes, edges)
        self._validate_workflow_agent_nodes(nodes)
        self._validate_workflow_subworkflow_nodes(nodes, parent_workflow_id=workflow_id)
        now = self._now()
        self._conn.execute(
            """
            INSERT INTO workflows (
                workflow_id, name, description, nodes_json, edges_json,
                default_input_schema_json, enabled, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workflow_id,
                name,
                str(payload.get("description") or ""),
                self._json_dump(nodes),
                self._json_dump(edges),
                self._json_dump(payload.get("default_input_schema") or {}),
                1 if payload.get("enabled", True) else 0,
                now,
                now,
            ),
        )
        if not seed:
            self._clear_studio_deletion("workflow", workflow_id)
        self._conn.commit()
        return self.get(workflow_id)

    def update(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        current = self.get(workflow_id)
        next_payload = dict(payload)
        if "name" in payload:
            name = str(payload.get("name") or "").strip()
            self._ensure_global_name_available(name, ignore_workflow_id=workflow_id)
            next_payload["name"] = name
        next_workflow = {**current, **next_payload}
        nodes = next_workflow.get("nodes") or []
        edges = next_workflow.get("edges") or []
        self._validate_workflow(nodes, edges)
        self._validate_workflow_agent_nodes(nodes)
        self._validate_workflow_subworkflow_nodes(nodes, parent_workflow_id=workflow_id)
        self._conn.execute(
            """
            UPDATE workflows
               SET name=?, description=?, nodes_json=?, edges_json=?,
                   default_input_schema_json=?, enabled=?, updated_at=?
             WHERE workflow_id=?
            """,
            (
                str(next_workflow.get("name") or ""),
                str(next_workflow.get("description") or ""),
                self._json_dump(nodes),
                self._json_dump(edges),
                self._json_dump(next_workflow.get("default_input_schema") or {}),
                1 if next_workflow.get("enabled", True) else 0,
                self._now(),
                workflow_id,
            ),
        )
        self._conn.commit()
        return self.get(workflow_id)

    def delete(self, workflow_id: str) -> dict[str, Any]:
        if self._conn.execute("SELECT 1 FROM workflows WHERE workflow_id=?", (workflow_id,)).fetchone() is not None:
            self._record_studio_deletion("workflow", workflow_id)
        self._conn.execute("DELETE FROM workflows WHERE workflow_id=?", (workflow_id,))
        self._conn.commit()
        return {"ok": True}
