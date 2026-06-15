"""Tests for tool approval resume service split out of the legacy runtime."""

from __future__ import annotations

from typing import Any

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


def _pending(tool: str = "terminal.run") -> dict[str, Any]:
    return {
        "tool": tool,
        "messages": [{"role": "assistant", "content": "Need approval"}],
        "tool_request": {"tool": tool, "input": {"command": "printf ok"}},
        "remaining_tool_requests": [{"tool": "artifact.write", "input": {"path": "ok.md"}}],
        "next_iteration": 4,
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
    run = {
        "run_id": "run-1",
        "runnable_id": "agent-1",
        "timeline": [{"event": "agent.tool.approval_required"}],
        "artifacts": [{"path": "context.md"}],
    }

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


def test_tool_approval_resume_service_dispatches_agent_resume() -> None:
    service, state = _service()
    run = {
        "run_id": "run-agent",
        "kind": "agent_run",
        "runnable_id": "agent-1",
        "timeline": [{"event": "agent.tool.approval_required"}],
        "artifacts": [],
    }

    result = service.approve_agent_run(run)

    call = state["resume_calls"][0]
    assert result["status"] == "resumed"
    assert call["run_id"] == "run-agent"
    assert call["pending"] is state["pending"]
    assert call["agent"]["agent_id"] == "agent-1"
    assert call["resume_context"].tool_name == "terminal.run"
    assert call["resumed_detail"] == "Agent resumed after approval"
    assert call["running_result"] == "已批准，Agent 正在继续执行"
    assert call["project_running"]({"status": "running"}) == {"agent_running": {"status": "running"}}
    assert call["project_result"]({"status": "completed"}) == {
        "child_projected": {"status": "completed"}
    }
    assert call["redact_error"]("secret") == "[redacted]"


def test_tool_approval_resume_service_dispatches_main_chat_resume() -> None:
    service, state = _service()
    run = {
        "run_id": "run-main",
        "kind": "main_chat_run",
        "runnable_id": "builtin:yachiyo-main",
        "timeline": [{"event": "agent.tool.approval_required"}],
        "artifacts": [],
    }

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
    finally:
        service.close()
