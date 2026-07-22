"""Tests for main Chat facade methods split out of the legacy runtime."""

from __future__ import annotations

from pathlib import Path

from apps.shell import agent_runtime
from apps.shell.agent.runtime.main_chat_facade import RuntimeMainChatFacadeMixin
from apps.shell.agent_runtime import AgentRuntimeService
from apps.shell.credential_store import MemoryCredentialStore


def test_runtime_main_chat_facade_mixin_remains_exported_from_legacy_module() -> None:
    assert agent_runtime.RuntimeMainChatFacadeMixin is RuntimeMainChatFacadeMixin
    assert issubclass(agent_runtime.NativeRunEngine, RuntimeMainChatFacadeMixin)
    assert "start_main_chat_run" not in agent_runtime.NativeRunEngine.__dict__
    assert "latest_awaiting_user_main_chat_run" not in agent_runtime.NativeRunEngine.__dict__
    assert "execute_main_chat_model_loop" not in agent_runtime.NativeRunEngine.__dict__
    assert "complete_main_chat_run" not in agent_runtime.NativeRunEngine.__dict__


def test_native_runtime_keeps_main_chat_facade_methods_available_after_split(tmp_path: Path) -> None:
    service = AgentRuntimeService(
        db_path=tmp_path / "agent-runtime.db",
        workspace_dir=tmp_path / "runtime",
        credential_store=MemoryCredentialStore(),
        seed_templates=False,
    )
    try:
        config = service._main_chat_agent_config(model_profile_id="profile-chat")
        pending = service._main_chat_pending_approval(
            {"approval_id": "approval-1", "tool": "terminal.run"},
            model_profile_id=" profile-chat ",
            tool_policy={"allowed_tools": ["terminal.run"]},
            workspace_policy={"default_workdir": str(tmp_path)},
        )
        run = service.start_main_chat_run(
            task_id="task-main-facade",
            session_id="session-main-facade",
            user_goal="hello",
        )
        completed = service.complete_main_chat_run(run["run_id"], "done")

        assert config["agent_id"] == "builtin:yachiyo-main"
        assert pending["resume_kind"] == "main_chat"
        assert pending["model_profile_id"] == "profile-chat"
        assert run["kind"] == "main_chat_run"
        assert completed["status"] == "completed"
    finally:
        service.close()


def test_main_chat_pending_approval_keeps_existing_runtime_authority_on_repause() -> None:
    envelope = {
        "envelope_id": "repause-authority",
        "requests": [
            {
                "request_id": "open-notes",
                "tool_name": "app.open",
                "input": {"app_name": "Notes"},
                "status": "blocked",
            }
        ],
    }
    metadata = {"yachiyo_runtime_planner": True}

    pending = RuntimeMainChatFacadeMixin._main_chat_pending_approval(
        {
            "approval_id": "approval-next",
            "tool": "artifact.write",
            "runtime_execution_envelope": envelope,
            "runtime_execution_metadata": metadata,
        },
        model_profile_id="profile-chat",
        tool_policy={"allowed_tools": ["artifact.write", "app.open"]},
        workspace_policy={"default_workdir": "/tmp/project"},
        runtime_execution_envelope={},
        runtime_execution_metadata={},
    )

    assert pending["runtime_execution_envelope"] == envelope
    assert pending["runtime_execution_metadata"] == metadata
    envelope["requests"][0]["input"]["app_name"] = "Slack"
    metadata["yachiyo_runtime_planner"] = False
    assert pending["runtime_execution_envelope"]["requests"][0]["input"] == {
        "app_name": "Notes"
    }
    assert pending["runtime_execution_metadata"]["yachiyo_runtime_planner"] is True


def test_main_chat_facade_delegates_pending_clarification_lookup() -> None:
    calls: list[str] = []

    class TaskRunLinks:
        def latest_awaiting_user_main_chat_for_session(
            self,
            session_id: str,
        ) -> dict[str, str]:
            calls.append(session_id)
            return {"run_id": "run-pending", "session_id": session_id}

    runtime = RuntimeMainChatFacadeMixin()
    runtime.task_run_links = TaskRunLinks()

    assert runtime.latest_awaiting_user_main_chat_run("session-a") == {
        "run_id": "run-pending",
        "session_id": "session-a",
    }
    assert calls == ["session-a"]
