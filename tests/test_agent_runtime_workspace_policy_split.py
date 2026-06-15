"""Tests for workspace policy helpers split out of the legacy runtime."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.serialization import json_dump_sorted, json_load
from apps.shell.agent.runtime.workspace_policy import RuntimeWorkspacePolicyService
from apps.shell.agent.tools.policy import RuntimePolicyCompiler


def test_workspace_policy_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeWorkspacePolicyService is RuntimeWorkspacePolicyService


def test_workspace_policy_service_assigns_stable_default_workdir(tmp_path) -> None:
    service = _workspace_policy_service(tmp_path)

    assigned = service.assign_default_agent_workdir(
        "agent/weird id",
        {"default_workdir": "", "readable_scopes": ["."], "writable_scopes": []},
        {"allowed_tools": ["workspace.write_patch"]},
    )

    assert assigned["default_workdir"].startswith(str(tmp_path / "agent-workspaces" / "agent-weird-id-"))
    assert Path(assigned["default_workdir"]).exists()
    assert assigned["writable_scopes"] == ["."]


def test_workspace_policy_service_migrates_agents_without_default_workdir(tmp_path) -> None:
    conn = _connect_workspace_policy_db()
    compiler = RuntimePolicyCompiler()
    conn.execute(
        """
        INSERT INTO agents (
            agent_id, category, tool_policy_json, workspace_policy_json, updated_at
        ) VALUES (?, ?, ?, ?, ?)
        """,
        (
            "agent-1",
            "coding",
            json_dump_sorted({"allowed_tools": ["workspace.write_patch"]}),
            json_dump_sorted({"default_workdir": "", "readable_scopes": ["."], "writable_scopes": []}),
            "old",
        ),
    )
    service = RuntimeWorkspacePolicyService(
        conn=conn,
        agent_workspaces_dir=tmp_path / "agent-workspaces",
        trusted_workspaces=_FakeTrustedWorkspaces(),
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        default_workspace_policy=compiler.default_workspace_policy,
        json_load=json_load,
        json_dump=json_dump_sorted,
        now=lambda: "now",
    )

    service.migrate_agent_workspace_policies()

    row = conn.execute("SELECT workspace_policy_json, updated_at FROM agents WHERE agent_id='agent-1'").fetchone()
    workspace_policy = json_load(row["workspace_policy_json"], {})
    assert workspace_policy["default_workdir"] == str(tmp_path / "agent-workspaces" / "agent-1")
    assert workspace_policy["writable_scopes"] == ["."]
    assert row["updated_at"] == "now"


def _connect_workspace_policy_db() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute(
        """
        CREATE TABLE agents (
            agent_id TEXT PRIMARY KEY,
            category TEXT NOT NULL,
            tool_policy_json TEXT NOT NULL,
            workspace_policy_json TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    return conn


def _workspace_policy_service(tmp_path) -> RuntimeWorkspacePolicyService:
    compiler = RuntimePolicyCompiler()
    return RuntimeWorkspacePolicyService(
        conn=_connect_workspace_policy_db(),
        agent_workspaces_dir=tmp_path / "agent-workspaces",
        trusted_workspaces=_FakeTrustedWorkspaces(),
        compile_tool_policy=compiler.compile_tool_policy,
        compile_workspace_policy=compiler.compile_workspace_policy,
        default_workspace_policy=compiler.default_workspace_policy,
        json_load=json_load,
        json_dump=json_dump_sorted,
        now=lambda: "now",
    )


class _FakeTrustedWorkspaces:
    def trust(self, path: str | Path, *, source: str = "runtime", commit: bool = True) -> dict[str, Any]:
        return {"path": str(path), "source": source, "commit": commit}

    def trust_from_policy(
        self,
        workspace_policy: dict[str, Any],
        *,
        source: str,
        commit: bool = True,
    ) -> None:
        return None

    def list(self) -> dict[str, Any]:
        return {"ok": True, "workspaces": []}
