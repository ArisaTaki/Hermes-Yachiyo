"""Tests for default seed templates split out of the legacy runtime."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.seed_templates import RuntimeSeedTemplateService
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES,
    LOW_RISK_BROWSER_TOOL_NAMES,
    LOW_RISK_DESKTOP_TOOL_NAMES,
    MEMORY_TOOL_NAMES,
    RuntimePolicyCompiler,
)


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


def test_seed_template_service_backfills_legacy_default_agent_desktop_tools() -> None:
    conn = _connect_seed_db()
    legacy_policy = {
        "allowed_tools": [
            "workspace.list",
            "workspace.read",
            *MEMORY_TOOL_NAMES,
            *FUTURE_TASK_TOOL_NAMES,
            "artifact.write",
        ],
        "approval_required": {},
    }
    conn.execute(
        """
        INSERT INTO agents (agent_id, name, category, tool_policy_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            "agent_yachiyo_orchestrator",
            "Yachiyo Orchestrator",
            "orchestrator",
            json.dumps(legacy_policy),
        ),
    )
    service = _seed_service(conn)

    service.seed_agents()

    row = conn.execute(
        "SELECT tool_policy_json FROM agents WHERE agent_id=?",
        ("agent_yachiyo_orchestrator",),
    ).fetchone()
    tool_policy = json.loads(row["tool_policy_json"])
    allowed_tools = set(tool_policy["allowed_tools"])
    assert set(LOW_RISK_DESKTOP_TOOL_NAMES).issubset(allowed_tools)
    assert set(LOW_RISK_BROWSER_TOOL_NAMES).issubset(allowed_tools)
    assert tool_policy["approval_required"] == {}


def test_seed_template_service_does_not_backfill_customized_agent_policy() -> None:
    conn = _connect_seed_db()
    custom_policy = {
        "allowed_tools": ["workspace.read", "artifact.write"],
        "approval_required": {},
    }
    conn.execute(
        """
        INSERT INTO agents (agent_id, name, category, tool_policy_json)
        VALUES (?, ?, ?, ?)
        """,
        (
            "agent_yachiyo_orchestrator",
            "Yachiyo Orchestrator",
            "orchestrator",
            json.dumps(custom_policy),
        ),
    )
    service = _seed_service(conn)

    service.seed_agents()

    row = conn.execute(
        "SELECT tool_policy_json FROM agents WHERE agent_id=?",
        ("agent_yachiyo_orchestrator",),
    ).fetchone()
    assert json.loads(row["tool_policy_json"]) == custom_policy


def _connect_seed_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.executescript(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            category TEXT,
            tool_policy_json TEXT
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
            "INSERT INTO agents (agent_id, name, category, tool_policy_json) VALUES (?, ?, ?, ?)",
            (
                payload["agent_id"],
                payload["name"],
                payload["category"],
                json.dumps(payload["tool_policy"], ensure_ascii=False, sort_keys=True),
            ),
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
