"""Runtime installation compatibility facade methods for NativeRunEngine."""

from __future__ import annotations

from typing import Any

from apps.shell.agent.runtime.credentials import RuntimeCredentialService
from apps.shell.agent.runtime.model_calling import (
    RuntimeModelProfileChatAdapter,
    RuntimeOpenAICompatibleChatAdapter,
)
from apps.shell.agent.runtime.run_cancellation import RuntimeRunCancellationCoordinator


def _legacy_agent_runtime_module() -> Any:
    from apps.shell import agent_runtime

    return agent_runtime


class RuntimeInstallationFacadeMixin:
    """Keeps legacy runtime collaborator installation methods."""

    def _install_runtime_model_adapters(self) -> None:
        self.model_profile_chat_adapter = RuntimeModelProfileChatAdapter(
            chat_message_provider=lambda: _legacy_agent_runtime_module().openai_compatible_chat_message,
        )
        self.openai_compatible_chat_adapter = RuntimeOpenAICompatibleChatAdapter(
            timeout_provider=lambda: _legacy_agent_runtime_module().read_openai_compatible_chat_timeout(),
            urlopen=lambda *args, **kwargs: _legacy_agent_runtime_module().urlopen_with_bundled_ca(*args, **kwargs),
            redact_error=lambda value: _legacy_agent_runtime_module().redact_secrets(value),
        )

    def _install_runtime_engine_state(self, state: Any) -> None:
        self.workspace_dir = state.workspace_dir
        self.db_path = state.db_path
        self._credential_store = state.credential_store
        self.skills_dir = state.skills_dir
        self.skill_installs_dir = state.skill_installs_dir
        self.skill_installs_native_home = state.skill_installs_native_home
        self.agent_artifacts_dir = state.agent_artifacts_dir
        self.workflow_artifacts_dir = state.workflow_artifacts_dir
        self.agent_workspaces_dir = state.agent_workspaces_dir
        self._accepting_runs = state.accepting_runs
        self._closed = state.closed
        self.runtime_limits = state.runtime_limits
        self._db_lock = state.db_lock
        self._approval_execution_lock = state.approval_execution_lock
        self._approval_execution_in_progress = state.approval_execution_in_progress
        self._run_cancel_locks = state.run_cancel_locks
        self._run_cancel_locks_guard = state.run_cancel_locks_guard
        self._conn = state.conn
        self.runtime_credentials = RuntimeCredentialService(state.credential_store)

    def _install_runtime_recorders(self, recorders: Any) -> None:
        self.tool_request_parser = recorders.tool_request_parser
        self.runtime_agent_run_events = recorders.runtime_agent_run_events
        self.tool_event_payloads = recorders.tool_event_payloads
        self.runtime_tool_call_events = recorders.runtime_tool_call_events
        self.runtime_task_model_events = recorders.runtime_task_model_events
        self.runtime_task_events = recorders.runtime_task_events
        self.runtime_trace_events = recorders.runtime_trace_events
        self.tool_pending_approvals = recorders.tool_pending_approvals

    def _install_runtime_definition_services(self, services: Any) -> None:
        self.task_run_links = services.task_run_links
        self.trusted_workspaces = services.trusted_workspaces
        self.studio_deletions = services.studio_deletions
        self.skill_folders = services.skill_folders
        self.skill_records = services.skill_records
        self.agent_definitions = services.agent_definitions
        self.agent_skill_attachments = services.agent_skill_attachments
        self.skill_install_validator = services.skill_install_validator
        self.skill_sources = services.skill_sources
        self.skill_content = services.skill_content
        self.skill_import_sources = services.skill_import_sources
        self.skill_import_preparer = services.skill_import_preparer
        self.skill_sync = services.skill_sync
        self.workflows = services.workflows

    def _install_runtime_run_services(self, services: Any) -> None:
        self.approval_snapshots = services.approval_snapshots
        self.run_groups = services.run_groups
        self.run_approvals = services.run_approvals
        self.run_artifacts = services.run_artifacts
        self.run_projections = services.run_projections
        self.runs = services.runs
        self.run_events = services.run_events
        self.agent_run_starter = services.agent_run_starter

    def _install_runtime_memory_services(self, memory_services: Any) -> None:
        self.memory_services = memory_services

    def _install_runtime_core_services(self, core_services: Any) -> None:
        self.runtime_events = core_services.runtime_events
        self.runtime_agent_timeline = core_services.runtime_agent_timeline
        self.runtime_policy = core_services.runtime_policy
        self.model_profile_resolver = core_services.model_profile_resolver

    def _install_runtime_run_timeline(self, run_timeline: Any) -> None:
        self.run_timeline = run_timeline

    def _install_runtime_main_chat_config(self, main_chat_config: Any) -> None:
        self.main_chat_config = main_chat_config

    def _install_runtime_tool_brokers(self, tool_brokers: Any) -> None:
        self.tool_brokers = tool_brokers

    def _install_runtime_main_chat_runs(self, main_chat_runs: Any) -> None:
        self.main_chat_runs = main_chat_runs

    def _install_runtime_main_chat_model(self, main_chat_model: Any) -> None:
        self.main_chat_model = main_chat_model

    def _install_runtime_main_chat_model_loop(self, main_chat_model_loop: Any) -> None:
        self.main_chat_model_loop = main_chat_model_loop

    def _install_runtime_tooling(self, tooling: Any) -> None:
        self.tool_loop_projection = tooling.tool_loop_projection
        self.tool_call_executor = tooling.tool_call_executor
        self.tool_request_runner = tooling.tool_request_runner

    def _install_runtime_custom_api_agent_loop(self, custom_api_agent_loop: Any) -> None:
        self.custom_api_agent_loop = custom_api_agent_loop

    def _install_runtime_agent_services(self, agent_services: Any) -> None:
        self.agent_skill_loader = agent_services.agent_skill_loader
        self.agent_context_builder = agent_services.agent_context_builder
        self.agent_run_preparer = agent_services.agent_run_preparer
        self.agent_run_outcomes = agent_services.agent_run_outcomes

    def _install_runtime_approval_services(self, approval_services: Any) -> None:
        self.approval_pause = approval_services.approval_pause
        self.approvals = approval_services.approvals
        self.approval_resume = approval_services.approval_resume

    def _install_runtime_approval_transitions(self, approval_transitions: Any) -> None:
        self.approval_transitions = approval_transitions

    def _install_runtime_tool_approval_resume(self, tool_approval_resume: Any) -> None:
        self.tool_approval_resume = tool_approval_resume

    def _install_runtime_workflow_execution_services(self, workflow_services: Any) -> None:
        self.workflow_continuation = workflow_services.workflow_continuation
        self.workflow_approval_resume = workflow_services.workflow_approval_resume
        self.workflow_cancellation = workflow_services.workflow_cancellation
        self.workflow_child_outcomes = workflow_services.workflow_child_outcomes

    def _install_runtime_workflow_planning_services(self, workflow_services: Any) -> None:
        self.workflow_parent_locator = workflow_services.workflow_parent_locator
        self.workflow_path_planner = workflow_services.workflow_path_planner
        self.workflow_definition_validator = workflow_services.workflow_definition_validator
        self.run_readiness_validator = workflow_services.run_readiness_validator
        self.workflow_run_start_projector = workflow_services.workflow_run_start_projector
        self.workflow_run_starter = workflow_services.workflow_run_starter
        self.workflow_resume_planner = workflow_services.workflow_resume_planner

    def _install_runtime_runnable_services(self, runnable_services: Any) -> None:
        self.future_task_scheduler = runnable_services.future_task_scheduler
        self.chat_runnable_parser = runnable_services.chat_runnable_parser
        self.runnable_catalog = runnable_services.runnable_catalog
        self.runnable_run_coordinator = runnable_services.runnable_run_coordinator

    def _install_runtime_workflow_transition_services(self, workflow_services: Any) -> None:
        self.workflow_parent_resume = workflow_services.workflow_parent_resume
        self.approval_resume_projection = workflow_services.approval_resume_projection
        self.run_transition_projection = workflow_services.run_transition_projection

    def _install_runtime_run_cancellation(self, run_cancellation: Any) -> None:
        self.run_cancellation = run_cancellation
        self.run_cancellation_coordinator = RuntimeRunCancellationCoordinator(
            cancel_once=self.run_cancellation.cancel_once,
            run_cancel_locks=self._run_cancel_locks,
            run_cancel_locks_guard=self._run_cancel_locks_guard,
        )

    def _install_runtime_run_rerun(self, run_rerun: Any) -> None:
        self.run_rerun = run_rerun

    def _install_runtime_run_deletion(self, run_deletion: Any) -> None:
        self.run_deletion = run_deletion

    def _install_runtime_shutdown(self, shutdown: Any) -> None:
        self.runtime_shutdown = shutdown
