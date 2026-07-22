"""Runnable and delegation compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any, Callable

from apps.shell.agent.runtime.delegation import ChatRunnableMentionParser
from apps.shell.agent.runtime.run_group_attachments import RunGroupChildAttachment


class RuntimeRunnableFacadeMixin:
    """Keeps legacy runnable helper methods while delegating to split services."""

    def list_runnables(self) -> dict[str, Any]:
        return self.runnable_catalog.list_runnables(
            self.list_agents()["agents"],
            self.list_workflows()["workflows"],
        )

    def _agent_runnable_summary(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self.runnable_catalog.agent_summary(agent)

    def _workflow_participants(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        return self.runnable_catalog.workflow_participants(workflow)

    def _workflow_runnable_summary(self, workflow: dict[str, Any]) -> dict[str, Any]:
        return self.runnable_catalog.workflow_summary(workflow)

    def list_delegation_targets(self) -> dict[str, Any]:
        return self.runnable_catalog.list_delegation_targets(
            self.list_agents()["agents"],
            self.list_workflows()["workflows"],
        )

    def resolve_runnable(self, *, runnable_id: str = "", name: str = "") -> dict[str, Any] | None:
        return self.runnable_resolver.resolve(runnable_id=runnable_id, name=name)

    def create_run_for_runnable(
        self,
        *,
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
        run_group_id: str = "",
        upstream: str = "",
        client_run_id: str = "",
        client_request_id: str = "",
        agent_override: dict[str, Any] | None = None,
        daily_desktop_policy_overlay: bool = False,
        runtime_planner_entrypoint: bool = False,
        runtime_execution_envelope: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        daily_desktop_planning_context: str | None = None,
        project_root_group: bool | None = None,
        run_group_attachment: RunGroupChildAttachment | None = None,
    ) -> dict[str, Any]:
        return self.runnable_run_coordinator.create_run(
            runnable_id=runnable_id,
            name=name,
            user_goal=user_goal,
            run_group_id=run_group_id,
            upstream=upstream,
            client_run_id=client_run_id,
            client_request_id=client_request_id,
            agent_override=agent_override,
            daily_desktop_policy_overlay=daily_desktop_policy_overlay,
            runtime_planner_entrypoint=runtime_planner_entrypoint,
            runtime_execution_envelope=runtime_execution_envelope,
            metadata=metadata,
            direct_tool_requests=direct_tool_requests,
            daily_desktop_planning_context=daily_desktop_planning_context,
            project_root_group=project_root_group,
            run_group_attachment=run_group_attachment,
        )

    def create_run_for_runnable_async(
        self,
        *,
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
        run_group_id: str = "",
        upstream: str = "",
        client_run_id: str = "",
        client_request_id: str = "",
        agent_override: dict[str, Any] | None = None,
        daily_desktop_policy_overlay: bool = False,
        runtime_planner_entrypoint: bool = False,
        runtime_execution_envelope: dict[str, Any] | None = None,
        metadata: dict[str, Any] | None = None,
        direct_tool_requests: list[dict[str, Any]] | None = None,
        daily_desktop_planning_context: str | None = None,
        project_root_group: bool | None = None,
        run_group_attachment: RunGroupChildAttachment | None = None,
        deferred_execution_start_sink: Callable[[Callable[[], None]], None]
        | None = None,
        on_complete: Callable[[dict[str, Any]], None] | None = None,
    ) -> dict[str, Any]:
        """创建 Run 并立即返回，异步执行实际任务。"""
        return self.runnable_run_coordinator.create_run_async(
            runnable_id=runnable_id,
            name=name,
            user_goal=user_goal,
            run_group_id=run_group_id,
            upstream=upstream,
            client_run_id=client_run_id,
            client_request_id=client_request_id,
            agent_override=agent_override,
            daily_desktop_policy_overlay=daily_desktop_policy_overlay,
            runtime_planner_entrypoint=runtime_planner_entrypoint,
            runtime_execution_envelope=runtime_execution_envelope,
            metadata=metadata,
            direct_tool_requests=direct_tool_requests,
            daily_desktop_planning_context=daily_desktop_planning_context,
            project_root_group=project_root_group,
            run_group_attachment=run_group_attachment,
            deferred_execution_start_sink=deferred_execution_start_sink,
            on_complete=on_complete,
        )

    def rerun_run(
        self,
        run_id: str,
        request: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return self.run_rerun.rerun(run_id, request)

    def delegate_runnable(
        self,
        *,
        kind: str = "",
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
    ) -> dict[str, Any]:
        return self.runnable_run_coordinator.delegate(
            kind=kind,
            runnable_id=runnable_id,
            name=name,
            user_goal=user_goal,
        )

    def parse_known_chat_runnable(self, text: str) -> tuple[str, str] | None:
        return self.chat_runnable_parser.parse_known(text)

    @staticmethod
    def parse_chat_runnable(text: str) -> tuple[str, str] | None:
        return ChatRunnableMentionParser.parse(text)

    @staticmethod
    def _chat_mention_parts(text: str) -> tuple[str, str, list[str]] | None:
        return ChatRunnableMentionParser.mention_parts(text)

    @staticmethod
    def _chat_mention_goal(prefix: str, remainder: str, remaining_lines: list[str]) -> str:
        return ChatRunnableMentionParser.mention_goal(prefix, remainder, remaining_lines)
