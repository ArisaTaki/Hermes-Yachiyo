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
