"""Tests for tool approval resume service split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

import pytest

from apps.shell import agent_runtime
from apps.shell.agent.runtime.tool_approval_resume import RuntimeToolApprovalResumeService
from apps.shell.agent.runtime.tool_approvals import ToolApprovalResumeContext
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


class FakeToolBrokers:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def for_run(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"broker": kwargs}


class RestorableFakeBroker:
    def __init__(self) -> None:
        self.restored_target_ids: list[str] = []

    def restore_owned_browser_target(self, target_id: str) -> None:
        self.restored_target_ids.append(target_id)


class RestoringFakeToolBrokers(FakeToolBrokers):
    def __init__(self) -> None:
        super().__init__()
        self.broker = RestorableFakeBroker()

    def for_run(self, **kwargs: Any) -> RestorableFakeBroker:
        self.calls.append(kwargs)
        return self.broker


def _pending(tool: str = "terminal.run") -> dict[str, Any]:
    return {
        "tool": tool,
        "messages": [{"role": "assistant", "content": "Need approval"}],
        "tool_request": {"tool": tool, "input": {"command": "printf ok"}},
        "remaining_tool_requests": [{"tool": "artifact.write", "input": {"path": "ok.md"}}],
        "next_iteration": 4,
    }


def _run(run_id: str, **payload: Any) -> dict[str, Any]:
    original_goal = f"Resume the approved action for {run_id}"
    return {
        "run_id": run_id,
        "user_goal": original_goal,
        "goal_contract": {
            "contract_id": f"contract-{run_id}",
            "run_id": run_id,
            "original_goal": original_goal,
            "criteria": [
                {
                    "criterion_id": f"criterion-{run_id}",
                    "description": "Complete the approved action",
                    "effectful": True,
                    "response_satisfiable": False,
                }
            ],
        },
        **payload,
    }


def _service(**overrides: Any) -> tuple[RuntimeToolApprovalResumeService, dict[str, Any]]:
    state: dict[str, Any] = {
        "pending": _pending(),
        "resume_calls": [],
        "tool_brokers": FakeToolBrokers(),
    }
    service = RuntimeToolApprovalResumeService(
        pending_approval_private=lambda _run_id: state["pending"],
        get_agent_private=lambda agent_id: {
            "agent_id": agent_id,
            "skill_ids": ["skill-1"],
            "category": "coding",
        },
        compile_agent_runtime=lambda _agent: {
            "tool_policy": {"allowed_tools": ["terminal.run", "artifact.write"]},
            "workspace_policy": {"default_workdir": "/tmp/project"},
        },
        load_agent_skills=lambda skill_ids: [{"skill_id": skill_id} for skill_id in skill_ids],
        tool_brokers=state["tool_brokers"],
        run_budget=lambda run_id, timeline: {"run_id": run_id, "events": len(timeline)},
        resume_approved_tool_run=lambda **kwargs: state["resume_calls"].append(kwargs)
        or {"status": "resumed", "kwargs": kwargs},
        main_chat_agent_config=lambda **kwargs: {
            "agent_id": "builtin:yachiyo-main",
            "category": "orchestrator",
            **kwargs,
        },
        main_chat_pending_approval=lambda pending_approval, **kwargs: {
            **pending_approval,
            **kwargs,
            "resume_kind": "main_chat",
        },
        default_chat_profile_id=lambda: "profile-chat",
        project_agent_running=lambda running: {"agent_running": running},
        project_agent_completed=lambda context, result_text: {
            "agent_completed": context.run_id,
            "result": result_text,
        },
        project_main_chat_completed=lambda context, result_text: {
            "main_completed": context.run_id,
            "result": result_text,
        },
        project_child_run_transition=lambda result: {"child_projected": result},
        redact_agent_error=lambda value: str(value).replace("secret", "[redacted]"),
        main_chat_agent_id="builtin:yachiyo-main",
        error_type=agent_runtime.AgentRuntimeError,
    )
    for key, value in overrides.items():
        setattr(service, key, value)
    return service, state


def test_tool_approval_resume_service_builds_resume_context() -> None:
    service, state = _service()
    run = _run(
        "run-1",
        runnable_id="agent-1",
        timeline=[{"event": "agent.tool.approval_required"}],
        artifacts=[{"path": "context.md"}],
    )

    context = service.context(
        run,
        state["pending"],
        runtime={
            "tool_policy": {"allowed_tools": ["terminal.run"]},
            "workspace_policy": {"default_workdir": "/tmp/project"},
        },
        skills=[{"skill_id": "skill-1"}],
    )

    assert isinstance(context, ToolApprovalResumeContext)
    assert context.run_id == "run-1"
    assert context.tool_name == "terminal.run"
    assert context.allowed_tools == ["terminal.run"]
    assert context.budget == {"run_id": "run-1", "events": 1}
    assert state["tool_brokers"].calls == [
        {
            "run_id": "run-1",
            "workspace_policy": {"default_workdir": "/tmp/project"},
            "skills": [{"skill_id": "skill-1"}],
            "default_runnable_id": "agent-1",
        }
    ]


def test_tool_approval_resume_restores_only_trusted_run_owned_browser_target() -> None:
    service, state = _service()
    tool_brokers = RestoringFakeToolBrokers()
    service._tool_brokers = tool_brokers
    state["pending"] = {
        "tool": "browser.click",
        "messages": [{"role": "assistant", "content": "Need approval"}],
        "tool_request": {"tool": "browser.click", "input": {"selector": "#go"}},
        "remaining_tool_requests": [],
        "next_iteration": 2,
    }
    run = _run(
        "run-browser",
        runnable_id="agent-1",
        timeline=[
            {
                "event": "agent.tool.call",
                "tool": "browser.open_url",
                "result": {
                    "ok": True,
                    "action": "browser.open_url",
                    "data": {
                        "target_id": "target-owned-by-run",
                        "target_owned_by_run": True,
                    },
                },
            },
            {
                "event": "model.output.completed",
                "result": {
                    "ok": True,
                    "action": "browser.open_url",
                    "data": {
                        "target_id": "forged-non-tool-target",
                        "target_owned_by_run": True,
                    },
                },
            },
            {
                "event": "agent.tool.approval_required",
                "tool": "browser.click",
                "input": {"target_id": "model-forged-target"},
            },
        ],
        artifacts=[],
    )

    context = service.context(
        run,
        state["pending"],
        runtime={
            "tool_policy": {"allowed_tools": ["browser.click"]},
            "workspace_policy": {"default_workdir": "/tmp/project"},
        },
    )

    assert context.broker is tool_brokers.broker
    assert tool_brokers.broker.restored_target_ids == ["target-owned-by-run"]


def test_tool_approval_resume_does_not_resurrect_target_after_ownership_clear() -> None:
    service, state = _service()
    tool_brokers = RestoringFakeToolBrokers()
    service._tool_brokers = tool_brokers
    run = _run(
        "run-browser-cleared",
        runnable_id="agent-1",
        timeline=[
            {
                "event": "agent.tool.call",
                "tool": "browser.open_url",
                "result": {
                    "ok": True,
                    "action": "browser.open_url",
                    "data": {
                        "target_id": "stale-target",
                        "target_owned_by_run": True,
                    },
                },
            },
            {
                "event": "agent.tool.call",
                "tool": "browser.open_url",
                "result": {
                    "ok": False,
                    "action": "browser.open_url",
                    "error": "chrome_cdp_unavailable",
                    "browser_target_ownership_cleared": True,
                },
            },
            {"event": "agent.tool.approval_required", "tool": "browser.click"},
        ],
        artifacts=[],
    )

    service.context(
        run,
        state["pending"],
        runtime={
            "tool_policy": {"allowed_tools": ["browser.click"]},
            "workspace_policy": {"default_workdir": "/tmp/project"},
        },
    )

    assert tool_brokers.broker.restored_target_ids == []


def test_tool_approval_resume_service_scopes_group_resume_to_foreground_lock() -> None:
    service, state = _service()
    run = _run(
        "run-1",
        run_group_id="group-run-1",
        runnable_id="agent-1",
        timeline=[{"event": "agent.tool.approval_required"}],
        artifacts=[],
    )

    context = service.context(
        run,
        state["pending"],
        runtime={
            "tool_policy": {"allowed_tools": ["terminal.run"]},
            "workspace_policy": {"default_workdir": "/tmp/project"},
        },
        skills=[{"skill_id": "skill-1"}],
    )

    assert context.broker == {
        "broker": {
            "run_id": "run-1",
            "workspace_policy": {"default_workdir": "/tmp/project"},
            "skills": [{"skill_id": "skill-1"}],
            "default_runnable_id": "agent-1",
            "foreground_lock_key": "group-run-1",
            "foreground_lock_owner": "group-run-1:run-1",
        }
    }


def test_tool_approval_resume_service_scopes_workflow_child_resume_to_foreground_lock() -> None:
    service, state = _service()
    state["pending"] = {
        **state["pending"],
        "workflow_run_id": "workflow-run-1",
        "workflow_node_id": "desktop-node",
        "workflow_node_label": "Type in app",
    }
    run = _run(
        "child-run-1",
        runnable_id="agent-1",
        timeline=[{"event": "agent.tool.approval_required"}],
        artifacts=[],
    )

    context = service.context(
        run,
        state["pending"],
        runtime={
            "tool_policy": {"allowed_tools": ["terminal.run"]},
            "workspace_policy": {"default_workdir": "/tmp/project"},
        },
        skills=[{"skill_id": "skill-1"}],
    )

    assert context.broker == {
        "broker": {
            "run_id": "child-run-1",
            "workspace_policy": {"default_workdir": "/tmp/project"},
            "skills": [{"skill_id": "skill-1"}],
            "default_runnable_id": "agent-1",
            "foreground_lock_key": "workflow:workflow-run-1",
            "foreground_lock_owner": "workflow:workflow-run-1:child-run-1",
        }
    }


def test_tool_approval_resume_service_dispatches_agent_resume() -> None:
    service, state = _service()
    run = _run(
        "run-agent",
        kind="agent_run",
        runnable_id="agent-1",
        timeline=[{"event": "agent.tool.approval_required"}],
        artifacts=[],
    )

    result = service.approve_agent_run(run)

    call = state["resume_calls"][0]
    assert result["status"] == "resumed"
    assert call["run_id"] == "run-agent"
    assert call["pending"] is state["pending"]
    assert call["agent"]["agent_id"] == "agent-1"
    assert call["resume_context"].tool_name == "terminal.run"
    assert call["resumed_detail"] == "Agent resumed after approval"
    assert call["running_result"] == "已批准，Agent 正在继续执行"
    assert call["project_running"]({"status": "running"}) == {
        "agent_running": {"status": "running"}
    }
    assert call["project_result"]({"status": "completed"}) == {
        "child_projected": {"status": "completed"}
    }
    assert call["redact_error"]("secret") == "[redacted]"


def test_tool_approval_resume_service_supports_legacy_exact_resume_signature() -> None:
    service, state = _service()
    state["pending"]["approval_id"] = "approval-legacy-resume"
    calls: list[dict[str, Any]] = []

    def legacy_resume(
        *,
        run_id: str,
        pending: dict[str, Any],
        resume_context: ToolApprovalResumeContext,
        agent: dict[str, Any],
        resumed_detail: str,
        running_result: str,
        project_running: Any,
        project_completed: Any,
        project_result: Any,
        redact_error: Any,
    ) -> dict[str, Any]:
        calls.append(
            {
                "run_id": run_id,
                "pending": pending,
                "resume_context": resume_context,
                "agent": agent,
                "resumed_detail": resumed_detail,
                "running_result": running_result,
                "project_running": project_running,
                "project_completed": project_completed,
                "project_result": project_result,
                "redact_error": redact_error,
            }
        )
        return {"status": "resumed"}

    service._resume_approved_tool_run = legacy_resume
    result = service.approve_agent_run(
        _run(
            "run-agent-legacy-resume",
            kind="agent_run",
            runnable_id="agent-1",
            timeline=[{"event": "agent.tool.approval_required"}],
            artifacts=[],
        ),
        expected_approval_id="approval-legacy-resume",
    )

    assert result == {"status": "resumed"}
    assert calls[0]["run_id"] == "run-agent-legacy-resume"
    assert calls[0]["resume_context"].approval_id == "approval-legacy-resume"


def test_tool_approval_resume_service_dispatches_main_chat_resume() -> None:
    service, state = _service()
    run = _run(
        "run-main",
        kind="main_chat_run",
        runnable_id="builtin:yachiyo-main",
        timeline=[{"event": "agent.tool.approval_required"}],
        artifacts=[],
    )

    result = service.approve_main_chat_run(run)

    call = state["resume_calls"][0]
    prepared = call["project_required"]({"tool": "terminal.run"})
    assert result["status"] == "resumed"
    assert call["agent"]["model_profile_id"] == "profile-chat"
    assert call["resumed_detail"] == "Main chat resumed after approval"
    assert call["running_result"] == "已批准，Yachiyo 正在继续执行"
    assert prepared["resume_kind"] == "main_chat"
    assert prepared["model_profile_id"] == "profile-chat"
    assert prepared["tool_policy"] == {"allowed_tools": ["terminal.run", "artifact.write"]}
    assert prepared["workspace_policy"] == {"default_workdir": "/tmp/project"}


def test_main_chat_approval_resume_preserves_runtime_authority_for_next_pause() -> None:
    service, state = _service()
    envelope = {
        "envelope_id": "approval-envelope-notes",
        "requests": [
            {
                "request_id": "open-notes",
                "tool_name": "app.open",
                "input": {"app_name": "Notes"},
                "status": "blocked",
            }
        ],
    }
    metadata = {
        "yachiyo_runtime_planner": True,
        "desktop_execution_policy": {"mode": "background"},
    }
    state["pending"] = {
        **_pending(),
        "model_profile_id": "profile-chat",
        "tool_policy": {"allowed_tools": ["terminal.run", "artifact.write"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
        "runtime_execution_envelope": envelope,
        "runtime_execution_metadata": metadata,
    }
    run = _run(
        "run-main-authority",
        kind="main_chat_run",
        runnable_id="builtin:yachiyo-main",
        timeline=[{"event": "agent.tool.approval_required"}],
        artifacts=[],
    )

    service.approve_main_chat_run(run)

    call = state["resume_calls"][0]
    assert call["resume_context"].runtime_execution_envelope == envelope
    assert call["resume_context"].runtime_execution_metadata == metadata
    next_pending = call["project_required"](
        {
            "approval_id": "approval-next",
            "tool": "artifact.write",
        }
    )
    assert next_pending["runtime_execution_envelope"] == envelope
    assert next_pending["runtime_execution_metadata"] == metadata


def test_main_chat_approval_resume_fails_closed_for_legacy_repause_builder() -> None:
    service, state = _service()
    state["pending"] = {
        **_pending(),
        "model_profile_id": "profile-chat",
        "tool_policy": {"allowed_tools": ["terminal.run", "app.open"]},
        "workspace_policy": {"default_workdir": "/tmp/project"},
        "runtime_execution_envelope": {
            "requests": [
                {
                    "request_id": "open-notes",
                    "tool_name": "app.open",
                    "input": {"app_name": "Notes"},
                    "status": "blocked",
                }
            ]
        },
    }

    def legacy_pending_builder(
        pending_approval: dict[str, Any],
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any],
        workspace_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **pending_approval,
            "model_profile_id": model_profile_id,
            "tool_policy": tool_policy,
            "workspace_policy": workspace_policy,
        }

    service._main_chat_pending_approval = legacy_pending_builder
    service.approve_main_chat_run(
        _run(
            "run-main-legacy-repause",
            kind="main_chat_run",
            runnable_id="builtin:yachiyo-main",
            timeline=[{"event": "agent.tool.approval_required"}],
            artifacts=[],
        )
    )

    with pytest.raises(
        agent_runtime.AgentRuntimeError,
        match="approval_resume_runtime_authority_unsupported",
    ):
        state["resume_calls"][0]["project_required"](
            {"approval_id": "approval-next", "tool": "artifact.write"}
        )


def test_main_chat_approval_resume_keeps_legacy_repause_builder_without_authority() -> None:
    service, state = _service()

    def legacy_pending_builder(
        pending_approval: dict[str, Any],
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any],
        workspace_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **pending_approval,
            "model_profile_id": model_profile_id,
            "tool_policy": tool_policy,
            "workspace_policy": workspace_policy,
        }

    service._main_chat_pending_approval = legacy_pending_builder
    service.approve_main_chat_run(
        _run(
            "run-main-legacy-repause-no-authority",
            kind="main_chat_run",
            runnable_id="builtin:yachiyo-main",
            timeline=[{"event": "agent.tool.approval_required"}],
            artifacts=[],
        )
    )

    pending = state["resume_calls"][0]["project_required"](
        {"approval_id": "approval-next", "tool": "artifact.write"}
    )
    assert pending["model_profile_id"] == "profile-chat"
    assert "runtime_execution_envelope" not in pending
    assert "runtime_execution_metadata" not in pending


def test_tool_approval_resume_service_accepts_runtime_planner_profileless_desktop_resume() -> None:
    service, state = _service()
    state["pending"] = {
        "tool": "desktop.quit_app",
        "tool_request": {"tool": "desktop.quit_app", "input": {}},
        "messages": [{"role": "user", "content": "退出当前应用"}],
        "remaining_tool_requests": [],
        "next_iteration": 1,
        "model_profile_id": "",
        "tool_policy": {
            "allowed_tools": ["desktop.quit_app"],
            "approval_required": {"desktop.quit_app": True},
        },
        "workspace_policy": {"default_workdir": "/tmp/project"},
    }
    service._default_chat_profile_id = lambda: ""
    run = _run(
        "run-main",
        kind="main_chat_run",
        runnable_id="builtin:yachiyo-main",
        timeline=[
            {
                "event": "agent.desktop.intent_planned",
                "tool": "desktop.quit_app",
                "source": "runtime_planner",
            }
        ],
        artifacts=[],
    )

    result = service.approve_main_chat_run(run)

    call = state["resume_calls"][0]
    assert result["status"] == "resumed"
    assert call["agent"]["model_profile_id"] == ""
    assert call["pending"] is state["pending"]


def test_native_runtime_installs_tool_approval_resume_service(tmp_path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        assert agent_runtime.RuntimeToolApprovalResumeService is RuntimeToolApprovalResumeService
        assert isinstance(service.tool_approval_resume, RuntimeToolApprovalResumeService)
        assert getattr(service.tool_approval_resume._run_budget, "__self__", None) is not service
    finally:
        service.close()
