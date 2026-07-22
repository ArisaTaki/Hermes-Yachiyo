"""Agent run compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.paths import agent_workspace_dir as _runtime_agent_workspace_dir


class RuntimeAgentFacadeMixin:
    """Keeps legacy Agent helper methods while delegating to split services."""

    def _load_agent_skills(self, skill_ids: list[str]) -> list[dict[str, Any]]:
        return self.agent_skill_loader.load(skill_ids)

    def _compile_agent_runtime(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self.runtime_policy.compile_agent_runtime(agent)

    def _agent_context(
        self,
        agent: dict[str, Any],
        user_goal: str,
        upstream: str = "",
        *,
        skills: list[dict[str, Any]] | None = None,
    ) -> str:
        return self.agent_context_builder.build(
            agent,
            user_goal,
            upstream,
            skills=skills,
        )

    @staticmethod
    def _agent_workspace_dir(agent: dict[str, Any]) -> str:
        return _runtime_agent_workspace_dir(agent)

    def create_agent_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.agent_run_coordinator.create_sync(payload)

    def create_agent_run_async(
        self,
        payload: dict[str, Any],
        on_complete: Callable[[dict[str, Any]], None] | None = None,
        deferred_execution_start_sink: Callable[[Callable[[], None]], None]
        | None = None,
    ) -> dict[str, Any]:
        return self.agent_run_async_coordinator.create_async(
            payload,
            on_complete=on_complete,
            deferred_execution_start_sink=deferred_execution_start_sink,
        )

    def _execute_agent_run(
        self,
        run_id: str,
        agent: dict[str, Any],
        user_goal: str,
        upstream: str = "",
        run_group_id: str = "",
        workflow_run_id: str = "",
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        runtime_execution_envelope: dict[str, Any] | None = None,
        runtime_execution_metadata: dict[str, Any] | None = None,
        daily_desktop_planning_context: str | None = None,
    ) -> dict[str, Any]:
        kwargs: dict[str, Any] = {}
        if run_group_id and supports_keyword(self.agent_run_executor.execute, "run_group_id"):
            kwargs["run_group_id"] = run_group_id
        if workflow_run_id and supports_keyword(self.agent_run_executor.execute, "workflow_run_id"):
            kwargs["workflow_run_id"] = workflow_run_id
        if (
            direct_tool_request is not None
            and supports_keyword(self.agent_run_executor.execute, "direct_tool_request")
        ):
            kwargs["direct_tool_request"] = direct_tool_request
        if (
            direct_tool_requests is not None
            and supports_keyword(self.agent_run_executor.execute, "direct_tool_requests")
        ):
            kwargs["direct_tool_requests"] = direct_tool_requests
        if (
            runtime_execution_envelope is not None
            and supports_keyword(self.agent_run_executor.execute, "runtime_execution_envelope")
        ):
            kwargs["runtime_execution_envelope"] = runtime_execution_envelope
        if (
            runtime_execution_metadata is not None
            and supports_keyword(self.agent_run_executor.execute, "runtime_execution_metadata")
        ):
            kwargs["runtime_execution_metadata"] = runtime_execution_metadata
        if (
            daily_desktop_planning_context is not None
            and supports_keyword(
                self.agent_run_executor.execute,
                "daily_desktop_planning_context",
            )
        ):
            kwargs["daily_desktop_planning_context"] = daily_desktop_planning_context
        return self.agent_run_executor.execute(
            run_id,
            agent,
            user_goal,
            upstream,
            **kwargs,
        )

    def _run_custom_api_agent(
        self,
        agent: dict[str, Any],
        context: str,
        broker: Any,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        messages: list[dict[str, Any]] | None = None,
        direct_tool_request: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        runtime_execution_envelope: dict[str, Any] | None = None,
        runtime_execution_metadata: dict[str, Any] | None = None,
        daily_desktop_planning_context: str | None = None,
        original_goal: str | None = None,
        start_iteration: int = 0,
        run_id: str = "",
        budget: Any | None = None,
        resume_after_approved_tool: bool = False,
    ) -> str:
        return self.custom_api_agent_loop.run(
            agent,
            context,
            broker,
            timeline,
            artifacts,
            messages=messages,
            direct_tool_request=direct_tool_request,
            direct_tool_requests=direct_tool_requests,
            runtime_execution_envelope=runtime_execution_envelope,
            runtime_execution_metadata=runtime_execution_metadata,
            daily_desktop_planning_context=daily_desktop_planning_context,
            original_goal=original_goal,
            start_iteration=start_iteration,
            run_id=run_id,
            budget=budget,
            resume_after_approved_tool=resume_after_approved_tool,
        )

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        agent = self._get_agent_private(agent_id)
        return self.agent_model_tester.test_agent_model(agent)
