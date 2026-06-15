"""Name validation for Agent and Workflow definitions."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from apps.shell.agent.runtime.errors import AgentRuntimeError


class RuntimeDefinitionNameGuard:
    """Keeps Agent and Workflow display names globally unique."""

    def __init__(
        self,
        conn: Any,
        *,
        ensure_row_factory: Callable[[], Any],
        error_type: type[Exception] = AgentRuntimeError,
    ) -> None:
        self._conn = conn
        self._ensure_row_factory = ensure_row_factory
        self._error_type = error_type

    def ensure_available(
        self,
        name: str,
        *,
        ignore_agent_id: str = "",
        ignore_workflow_id: str = "",
    ) -> None:
        self._ensure_row_factory()
        clean = (name or "").strip()
        if not clean:
            raise self._error_type("名称不能为空")
        if clean.lower() == "yachiyo":
            raise self._error_type("Yachiyo 是系统 Agent 名称，不能作为普通 Agent/Workflow 名称")
        agent = self._conn.execute(
            "SELECT agent_id FROM agents WHERE LOWER(name)=LOWER(?)",
            (clean,),
        ).fetchone()
        if agent and agent["agent_id"] != ignore_agent_id:
            raise self._error_type("Agent/Workflow 名称必须全局唯一")
        workflow = self._conn.execute(
            "SELECT workflow_id FROM workflows WHERE LOWER(name)=LOWER(?)",
            (clean,),
        ).fetchone()
        if workflow and workflow["workflow_id"] != ignore_workflow_id:
            raise self._error_type("Agent/Workflow 名称必须全局唯一")
