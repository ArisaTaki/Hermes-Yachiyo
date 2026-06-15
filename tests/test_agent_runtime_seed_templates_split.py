"""Tests for default seed templates split out of the legacy runtime."""

from __future__ import annotations

import sqlite3
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.seed_templates import RuntimeSeedTemplateService
from apps.shell.agent.tools.policy import RuntimePolicyCompiler


def test_seed_template_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeSeedTemplateService is RuntimeSeedTemplateService


def test_seed_template_service_seeds_default_agents_and_workflows() -> None:
    conn = _connect_seed_db()
    service = _seed_service(conn)

    service.seed()

    agent_ids = {
        row["agent_id"]
        for row in conn.execute("SELECT agent_id FROM agents").fetchall()
    }
    workflow_ids = {
        row["workflow_id"]
        for row in conn.execute("SELECT workflow_id FROM workflows").fetchall()
    }

    assert "agent_coding" in agent_ids
    assert "agent_yachiyo_orchestrator" in agent_ids
    assert workflow_ids == {
        "workflow_web_idea_full",
        "workflow_phase4_agent_line_smoke",
    }


def test_seed_template_service_keeps_deleted_workflows_deleted() -> None:
    conn = _connect_seed_db()
    service = _seed_service(
        conn,
        deleted={("workflow", "workflow_web_idea_full")},
    )

    service.seed()

    workflow_ids = {
        row["workflow_id"]
        for row in conn.execute("SELECT workflow_id FROM workflows").fetchall()
    }

    assert "workflow_web_idea_full" not in workflow_ids
    assert workflow_ids == {"workflow_phase4_agent_line_smoke"}


def test_seed_template_service_skips_workflows_with_missing_agents() -> None:
    conn = _connect_seed_db()
    service = _seed_service(conn)

    service.seed_workflows()

    assert conn.execute("SELECT COUNT(*) AS count FROM workflows").fetchone()["count"] == 0


def _connect_seed_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        CREATE TABLE workflows (
            workflow_id TEXT PRIMARY KEY,
            name TEXT NOT NULL
        );
        """
    )
    return conn


def _seed_service(
    conn: sqlite3.Connection,
    *,
    deleted: set[tuple[str, str]] | None = None,
) -> RuntimeSeedTemplateService:
    compiler = RuntimePolicyCompiler()

    def create_agent(payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        assert seed is True
        conn.execute(
            "INSERT INTO agents (agent_id, name) VALUES (?, ?)",
            (payload["agent_id"], payload["name"]),
        )
        return payload

    def create_workflow(payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        assert seed is True
        conn.execute(
            "INSERT INTO workflows (workflow_id, name) VALUES (?, ?)",
            (payload["workflow_id"], payload["name"]),
        )
        return payload

    return RuntimeSeedTemplateService(
        conn=conn,
        create_agent=create_agent,
        create_workflow=create_workflow,
        default_tool_policy=compiler.default_tool_policy,
        default_workspace_policy=compiler.default_workspace_policy,
        has_studio_deletion=lambda item_type, item_key: (item_type, item_key) in (deleted or set()),
    )
