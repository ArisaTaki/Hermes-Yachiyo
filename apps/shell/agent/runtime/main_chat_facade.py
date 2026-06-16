"""Main Chat compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any


class RuntimeMainChatFacadeMixin:
    """Keeps daily Chat runtime methods while delegating to split services."""

    def start_main_chat_run(
        self,
        *,
        task_id: str,
        session_id: str,
        user_goal: str,
    ) -> dict[str, Any]:
        return self.main_chat_runs.start(task_id=task_id, session_id=session_id, user_goal=user_goal)

    def call_main_chat_model(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        profile_id: str = "",
        capability: str = "chat",
    ) -> str:
        return self.main_chat_model.call(
            run_id,
            messages,
            profile_id=profile_id,
            capability=capability,
        )

    def _main_chat_workspace_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.main_chat_config.workspace_policy(policy)

    def _main_chat_tool_policy(self, policy: dict[str, Any] | None = None) -> dict[str, Any]:
        return self.main_chat_config.tool_policy(policy)

    def _main_chat_agent_config(
        self,
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.main_chat_config.agent_config(
            model_profile_id=model_profile_id,
            tool_policy=tool_policy,
            workspace_policy=workspace_policy,
        )

    @staticmethod
    def _main_chat_pending_approval(
        pending_approval: dict[str, Any],
        *,
        model_profile_id: str,
        tool_policy: dict[str, Any],
        workspace_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            **pending_approval,
            "resume_kind": "main_chat",
            "model_profile_id": str(model_profile_id or "").strip(),
            "tool_policy": tool_policy,
            "workspace_policy": workspace_policy,
        }

    def execute_main_chat_model_loop(
        self,
        run_id: str,
        messages: list[dict[str, Any]],
        *,
        profile_id: str = "",
        tool_policy: dict[str, Any] | None = None,
        workspace_policy: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.main_chat_model_loop.execute(
            run_id,
            messages,
            profile_id=profile_id,
            tool_policy=tool_policy,
            workspace_policy=workspace_policy,
        )

    def complete_main_chat_run(self, run_id: str, result: str) -> dict[str, Any]:
        return self.main_chat_runs.complete(run_id, result)

    def fail_main_chat_run(self, run_id: str, error: Any) -> dict[str, Any]:
        return self.main_chat_runs.fail(run_id, error)
