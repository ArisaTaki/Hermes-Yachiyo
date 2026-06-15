"""Tests for approval execution guard split out of the legacy runtime."""

from __future__ import annotations

import threading
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_execution import RuntimeApprovalExecutionService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_approval_execution_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeApprovalExecutionService is RuntimeApprovalExecutionService


def test_native_runtime_installs_split_approval_execution_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.approval_execution, RuntimeApprovalExecutionService)
        assert service.approval_execution._execution_lock is service._approval_execution_lock
        assert service.approval_execution._execution_in_progress is service._approval_execution_in_progress
    finally:
        service.close()


def test_runtime_approval_execution_service_serializes_approval_resume() -> None:
    runs = {"run-1": {"run_id": "run-1", "status": "approval_required"}}
    in_progress: set[str] = set()
    calls: list[dict[str, Any]] = []

    def approve_once(run: dict[str, Any]) -> dict[str, Any]:
        calls.append(dict(run))
        runs["run-1"] = {"run_id": "run-1", "status": "completed"}
        return runs["run-1"]

    service = RuntimeApprovalExecutionService(
        execution_lock=threading.RLock(),
        execution_in_progress=in_progress,
        get_run=lambda run_id: runs[run_id],
        approve_once=approve_once,
    )

    first = service.approve_run_approval("run-1")
    second = service.approve_run_approval("run-1")

    assert first["status"] == "completed"
    assert second["status"] == "completed"
    assert calls == [{"run_id": "run-1", "status": "approval_required"}]
    assert in_progress == set()


def test_runtime_approval_execution_service_returns_current_run_when_already_in_progress() -> None:
    run = {"run_id": "run-1", "status": "approval_required"}
    in_progress = {"run-1"}
    service = RuntimeApprovalExecutionService(
        execution_lock=threading.RLock(),
        execution_in_progress=in_progress,
        get_run=lambda _run_id: run,
        approve_once=lambda _run: {"run_id": "run-1", "status": "completed"},
    )

    assert service.approve_run_approval("run-1") is run
    assert in_progress == {"run-1"}
