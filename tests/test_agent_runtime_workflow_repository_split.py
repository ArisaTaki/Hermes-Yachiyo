"""Tests for the WorkflowRepository split out of agent_runtime."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.repositories.workflows import WorkflowRepository


def _json_dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _json_load(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return fallback


def _row_to_workflow(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "workflow_id": str(row["workflow_id"]),
        "name": str(row["name"]),
        "description": str(row["description"] or ""),
        "nodes": _json_load(row["nodes_json"], []),
        "edges": _json_load(row["edges_json"], []),
        "default_input_schema": _json_load(row["default_input_schema_json"], {}),
        "enabled": bool(row["enabled"]),
        "created_at": str(row["created_at"]),
        "updated_at": str(row["updated_at"]),
    }


def _connect_workflows_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE workflows (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT NOT NULL DEFAULT '',
            nodes_json TEXT NOT NULL DEFAULT '[]',
            edges_json TEXT NOT NULL DEFAULT '[]',
            default_input_schema_json TEXT NOT NULL DEFAULT '{}',
            enabled INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        );
        """
    )
    return conn


def test_workflow_repository_remains_exported_from_legacy_runtime_module() -> None:
    assert agent_runtime.WorkflowRepository is WorkflowRepository


def test_workflow_repository_lifecycle_and_validation_callbacks() -> None:
    conn = _connect_workflows_db()
    ensure_calls: list[tuple[str, str]] = []
    workflow_validation_calls: list[tuple[list[dict[str, Any]], list[dict[str, Any]]]] = []
    agent_validation_calls: list[list[dict[str, Any]]] = []
    subworkflow_validation_calls: list[tuple[list[dict[str, Any]], str]] = []
    deletion_events: list[tuple[str, str, str]] = []
    now_values = iter(
        [
            "2026-06-14T10:00:00Z",
            "2026-06-14T10:01:00Z",
        ],
    )

    def ensure_name(name: str, *, ignore_workflow_id: str = "", **_: Any) -> None:
        ensure_calls.append((name, ignore_workflow_id))

    def validate_workflow(nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> None:
        workflow_validation_calls.append((nodes, edges))

    def validate_agent_nodes(nodes: list[dict[str, Any]]) -> None:
        agent_validation_calls.append(nodes)

    def validate_subworkflows(nodes: list[dict[str, Any]], *, parent_workflow_id: str) -> None:
        subworkflow_validation_calls.append((nodes, parent_workflow_id))

    repo = WorkflowRepository(
        conn,
        ensure_row_factory=lambda: None,
        row_to_workflow=_row_to_workflow,
        now=lambda: next(now_values),
        json_dump=_json_dump,
        workflow_id_factory=lambda name: f"workflow_{name.lower().replace(' ', '_')}",
        ensure_global_name_available=ensure_name,
        validate_workflow=validate_workflow,
        validate_workflow_agent_nodes=validate_agent_nodes,
        validate_workflow_subworkflow_nodes=validate_subworkflows,
        record_studio_deletion=lambda kind, key: deletion_events.append(("record", kind, key)),
        clear_studio_deletion=lambda kind, key: deletion_events.append(("clear", kind, key)),
    )

    nodes = [{"id": "start", "data": {"kind": "start"}}]
    created = repo.create(
        {
            "name": "Daily Flow",
            "description": "first",
            "nodes": nodes,
            "edges": [],
            "default_input_schema": {"goal": "string"},
        },
    )
    assert created["workflow_id"] == "workflow_daily_flow"
    assert created["name"] == "Daily Flow"
    assert created["default_input_schema"] == {"goal": "string"}
    assert ensure_calls == [("Daily Flow", "")]
    assert workflow_validation_calls == [(nodes, [])]
    assert agent_validation_calls == [nodes]
    assert subworkflow_validation_calls == [(nodes, "workflow_daily_flow")]
    assert deletion_events == [("clear", "workflow", "workflow_daily_flow")]

    updated_nodes = [*nodes, {"id": "agent", "data": {"kind": "agent"}}]
    updated = repo.update(
        created["workflow_id"],
        {
            "name": "Daily Flow v2",
            "nodes": updated_nodes,
            "enabled": False,
        },
    )
    assert updated["name"] == "Daily Flow v2"
    assert updated["enabled"] is False
    assert ensure_calls[-1] == ("Daily Flow v2", "workflow_daily_flow")
    assert workflow_validation_calls[-1] == (updated_nodes, [])
    assert subworkflow_validation_calls[-1] == (updated_nodes, "workflow_daily_flow")

    assert repo.list()["workflows"][0]["workflow_id"] == "workflow_daily_flow"
    assert repo.delete("workflow_daily_flow") == {"ok": True}
    assert deletion_events[-1] == ("record", "workflow", "workflow_daily_flow")
    assert conn.execute("SELECT COUNT(*) AS count FROM workflows").fetchone()["count"] == 0
