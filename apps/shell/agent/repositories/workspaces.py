"""Trusted workspace persistence for Agent runtime workspace policy."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Callable

from apps.shell.agent.runtime.errors import AgentRuntimeError


class TrustedWorkspaceRepository:
    """Projection store for workspace directories trusted by runtime policy."""

    def __init__(
        self,
        conn: Any,
        *,
        now: Callable[[], str],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._conn = conn
        self._now = now
        self._error_type = error_type

    def trust(self, path: str | Path, *, source: str = "runtime", commit: bool = True) -> dict[str, Any]:
        raw_path = str(path or "").strip()
        if not raw_path:
            raise self._error_type("trusted workspace 路径不能为空")
        try:
            resolved = Path(raw_path).expanduser().resolve()
        except OSError as exc:
            raise self._error_type(f"trusted workspace 路径无效：{exc}") from exc
        if not resolved.exists() or not resolved.is_dir():
            raise self._error_type("trusted workspace 必须是已存在目录")
        now = self._now()
        safe_source = str(source or "runtime")[:120]
        self._conn.execute(
            """
            INSERT INTO trusted_workspaces (path, source, trusted_at, updated_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(path) DO UPDATE SET
                source=excluded.source,
                updated_at=excluded.updated_at
            """,
            (str(resolved), safe_source, now, now),
        )
        if commit:
            self._conn.commit()
        return {"path": str(resolved), "source": safe_source, "trusted_at": now}

    def trust_from_policy(
        self,
        workspace_policy: dict[str, Any],
        *,
        source: str,
        commit: bool = True,
    ) -> None:
        workdir = str(workspace_policy.get("default_workdir") or "").strip()
        if not workdir:
            return
        try:
            self.trust(workdir, source=source, commit=commit)
        except self._error_type:
            return

    def list(self) -> dict[str, Any]:
        rows = self._conn.execute(
            "SELECT path, source, trusted_at, updated_at FROM trusted_workspaces ORDER BY updated_at DESC"
        ).fetchall()
        return {
            "ok": True,
            "workspaces": [
                {
                    "path": str(row["path"]),
                    "source": str(row["source"] or ""),
                    "trusted_at": str(row["trusted_at"] or ""),
                    "updated_at": str(row["updated_at"] or ""),
                }
                for row in rows
            ],
        }
