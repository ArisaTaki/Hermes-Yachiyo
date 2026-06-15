"""Approval execution guard for Runtime approval resume entrypoints."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


class RuntimeApprovalRunDispatcher:
    """Dispatches approved Run resumes by runtime kind without bypassing gates."""

    def __init__(
        self,
        *,
        approve_workflow_run: Callable[[dict[str, Any]], dict[str, Any]],
        approve_main_chat_run: Callable[[dict[str, Any]], dict[str, Any]],
        approve_agent_run: Callable[[dict[str, Any]], dict[str, Any]],
        error_type: type[Exception],
    ) -> None:
        self._approve_workflow_run = approve_workflow_run
        self._approve_main_chat_run = approve_main_chat_run
        self._approve_agent_run = approve_agent_run
        self._error_type = error_type

    def approve_once(self, run: dict[str, Any]) -> dict[str, Any]:
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            return self._approve_workflow_run(run)
        if run["kind"] == "main_chat_run":
            return self._approve_main_chat_run(run)
        if run["kind"] != "agent_run":
            raise self._error_type("当前只支持恢复 Agent Run 的工具审批")
        return self._approve_agent_run(run)


class RuntimeApprovalExecutionService:
    """Serializes approval execution for a run while preserving legacy callbacks."""

    def __init__(
        self,
        *,
        execution_lock: Any,
        execution_in_progress: set[str],
        get_run: Callable[[str], dict[str, Any]],
        approve_once: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> None:
        self._execution_lock = execution_lock
        self._execution_in_progress = execution_in_progress
        self._get_run = get_run
        self._approve_once = approve_once

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        with self._execution_lock:
            run = self._get_run(clean_run_id)
            if run["status"] != "approval_required":
                return run
            if clean_run_id in self._execution_in_progress:
                return run
            self._execution_in_progress.add(clean_run_id)
        try:
            return self._approve_once(run)
        finally:
            with self._execution_lock:
                self._execution_in_progress.discard(clean_run_id)
