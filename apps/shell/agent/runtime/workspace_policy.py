"""Workspace policy helpers for Agent runtime definitions."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, Callable


class RuntimeWorkspacePolicyService:
    """Projects default Agent workdirs and trusted workspace policy updates."""

    def __init__(
        self,
        *,
        conn: Any,
        agent_workspaces_dir: Path,
        trusted_workspaces: Any,
        compile_tool_policy: Callable[[str, Any], dict[str, Any]],
        compile_workspace_policy: Callable[[Any], dict[str, Any]],
        default_workspace_policy: Callable[[], dict[str, Any]],
        json_load: Callable[[Any, Any], Any],
        json_dump: Callable[[Any], str],
        now: Callable[[], str],
    ) -> None:
        self._conn = conn
        self._agent_workspaces_dir = agent_workspaces_dir
        self._trusted_workspaces = trusted_workspaces
        self._compile_tool_policy = compile_tool_policy
        self._compile_workspace_policy = compile_workspace_policy
        self._default_workspace_policy = default_workspace_policy
        self._json_load = json_load
        self._json_dump = json_dump
        self._now = now

    def default_agent_workdir(self, agent_id: str) -> Path:
        raw_id = str(agent_id or "")
        clean_id = re.sub(r"[^A-Za-z0-9._-]+", "-", raw_id).strip(".-")[:80]
        if not clean_id:
            clean_id = "agent"
        if clean_id != raw_id:
            clean_id = f"{clean_id}-{hashlib.sha256(raw_id.encode('utf-8')).hexdigest()[:8]}"
        workdir = self._agent_workspaces_dir / clean_id
        workdir.mkdir(parents=True, exist_ok=True)
        return workdir

    def assign_default_agent_workdir(
        self,
        agent_id: str,
        workspace_policy: dict[str, Any],
        tool_policy: dict[str, Any],
    ) -> dict[str, Any]:
        if str(workspace_policy.get("default_workdir") or "").strip():
            return workspace_policy
        assigned = {**workspace_policy, "default_workdir": str(self.default_agent_workdir(agent_id))}
        if "workspace.write_patch" in (tool_policy.get("allowed_tools") or []) and not assigned.get("writable_scopes"):
            assigned["writable_scopes"] = ["."]
        return assigned

    def trust_workspace(self, path: str | Path, *, source: str = "runtime", commit: bool = True) -> dict[str, Any]:
        return self._trusted_workspaces.trust(path, source=source, commit=commit)

    def trust_workspace_from_policy(
        self,
        workspace_policy: dict[str, Any],
        *,
        source: str,
        commit: bool = True,
    ) -> None:
        workdir = str(workspace_policy.get("default_workdir") or "").strip()
        if not workdir:
            return
        self._trusted_workspaces.trust_from_policy(
            workspace_policy,
            source=source,
            commit=commit,
        )

    def list_trusted_workspaces(self) -> dict[str, Any]:
        return self._trusted_workspaces.list()

    def migrate_agent_workspace_policies(self) -> None:
        rows = self._conn.execute(
            "SELECT agent_id, category, tool_policy_json, workspace_policy_json FROM agents"
        ).fetchall()
        changed = False
        for row in rows:
            tool_policy = self._compile_tool_policy(
                str(row["category"] or "custom"),
                self._json_load(row["tool_policy_json"], {}),
            )
            workspace_policy = self._compile_workspace_policy(
                self._json_load(row["workspace_policy_json"], self._default_workspace_policy())
            )
            if str(workspace_policy.get("default_workdir") or "").strip():
                continue
            workspace_policy = self.assign_default_agent_workdir(str(row["agent_id"]), workspace_policy, tool_policy)
            self._conn.execute(
                "UPDATE agents SET workspace_policy_json=?, updated_at=? WHERE agent_id=?",
                (self._json_dump(workspace_policy), self._now(), row["agent_id"]),
            )
            changed = True
        if changed:
            self._conn.commit()
