"""Tests for approval execution guard split out of the legacy runtime."""

from __future__ import annotations

import threading
from typing import Any

from apps.shell import agent_runtime
from apps.shell.agent.runtime.approval_execution import (
    RuntimeApprovalExecutionService,
    RuntimeApprovalRunDispatcher,
)
from apps.shell.agent.runtime.approval_services import (
    RuntimeApprovalRuntimeServiceBundle,
    build_runtime_approval_runtime_services,
)
from apps.shell.agent.runtime.approval_transitions import RuntimeApprovalTransitionService
from apps.shell.agent.runtime.tool_approval_resume import RuntimeToolApprovalResumeService
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_approval_execution_service_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeApprovalExecutionService is RuntimeApprovalExecutionService
    assert agent_runtime.RuntimeApprovalRunDispatcher is RuntimeApprovalRunDispatcher
    assert agent_runtime.RuntimeApprovalRuntimeServiceBundle is RuntimeApprovalRuntimeServiceBundle
    assert agent_runtime._build_runtime_approval_runtime_services is build_runtime_approval_runtime_services


def test_build_runtime_approval_runtime_services_wires_gate_preserving_services() -> None:
    execution_lock = threading.RLock()
    in_progress: set[str] = set()
    setup = build_runtime_approval_runtime_services(
        get_run=lambda run_id: {"run_id": run_id, "status": "approval_required", "kind": "agent_run"},
        pending_approval_private=lambda _run_id: {"tool": "workspace.read"},
        approvals=object(),
        project_child_run_transition=lambda result: result,
        project_cancelled_workflow_group_if_root=lambda _run, result: result,
        cancel_run=lambda run_id: {"run_id": run_id, "status": "cancelled"},
        get_agent_private=lambda agent_id: {"agent_id": agent_id},
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": []},
            "workspace_policy": {},
        },
        load_agent_skills=lambda _skill_ids: [],
        tool_brokers=object(),
        run_budget=lambda _run_id, _timeline: object(),
        resume_approved_tool_run=lambda **kwargs: {"status": "resumed", **kwargs},
        main_chat_agent_config=lambda **kwargs: {"agent_id": "builtin:yachiyo-main", **kwargs},
        main_chat_pending_approval=lambda pending, **kwargs: {"pending": pending, **kwargs},
        default_chat_profile_id=lambda: "profile-chat",
        project_agent_running=lambda running: running,
        project_agent_completed=lambda _context, result_text: {"result": result_text},
        project_main_chat_completed=lambda _context, result_text: {"result": result_text},
        approve_workflow_run=lambda run: {**run, "route": "workflow"},
        approve_main_chat_run=lambda run: {**run, "route": "main_chat"},
        execution_lock=execution_lock,
        execution_in_progress=in_progress,
    )

    assert isinstance(setup, RuntimeApprovalRuntimeServiceBundle)
    assert isinstance(setup.approval_transitions, RuntimeApprovalTransitionService)
    assert isinstance(setup.tool_approval_resume, RuntimeToolApprovalResumeService)
    assert isinstance(setup.approval_resume_dispatcher, RuntimeApprovalRunDispatcher)
    assert isinstance(setup.approval_execution, RuntimeApprovalExecutionService)
    assert setup.approval_resume_dispatcher._approve_agent_run.__self__ is setup.tool_approval_resume
    assert (
        setup.approval_resume_dispatcher._approve_agent_run.__func__
        is RuntimeToolApprovalResumeService.approve_agent_run
    )
    assert setup.approval_execution._execution_lock is execution_lock
    assert setup.approval_execution._execution_in_progress is in_progress
    assert setup.approval_execution._approve_once.__self__ is setup.approval_resume_dispatcher
    assert setup.approval_execution._approve_once.__func__ is RuntimeApprovalRunDispatcher.approve_once


def test_native_runtime_installs_split_approval_execution_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert isinstance(service.approval_execution, RuntimeApprovalExecutionService)
        assert isinstance(service.approval_resume_dispatcher, RuntimeApprovalRunDispatcher)
        assert service.approval_execution._execution_lock is service._approval_execution_lock
        assert service.approval_execution._execution_in_progress is service._approval_execution_in_progress
        assert service.approval_execution._approve_once.__self__ is service.approval_resume_dispatcher
    finally:
        service.close()


def test_runtime_approval_run_dispatcher_routes_by_run_kind() -> None:
    calls: list[tuple[str, str]] = []
    dispatcher = RuntimeApprovalRunDispatcher(
        approve_workflow_run=lambda run: calls.append(("workflow", run["run_id"])) or {"status": "workflow"},
        approve_main_chat_run=lambda run: calls.append(("main_chat", run["run_id"])) or {"status": "main_chat"},
        approve_agent_run=lambda run: calls.append(("agent", run["run_id"])) or {"status": "agent"},
        error_type=agent_runtime.AgentRuntimeError,
    )

    assert dispatcher.approve_once({"run_id": "wf", "status": "approval_required", "kind": "workflow_run"}) == {
        "status": "workflow"
    }
    assert dispatcher.approve_once({"run_id": "chat", "status": "approval_required", "kind": "main_chat_run"}) == {
        "status": "main_chat"
    }
    assert dispatcher.approve_once({"run_id": "agent", "status": "approval_required", "kind": "agent_run"}) == {
        "status": "agent"
    }
    current = {"run_id": "done", "status": "completed", "kind": "agent_run"}
    assert dispatcher.approve_once(current) is current
    assert calls == [("workflow", "wf"), ("main_chat", "chat"), ("agent", "agent")]


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
