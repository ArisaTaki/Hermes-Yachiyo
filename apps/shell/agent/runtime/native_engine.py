"""Native runtime engine composition."""

from __future__ import annotations

from pathlib import Path

from apps.shell.agent.runtime.agent_facade import RuntimeAgentFacadeMixin
from apps.shell.agent.runtime.engine_facade import RuntimeEngineFacadeMixin
from apps.shell.agent.runtime.group_facade import RuntimeGroupFacadeMixin
from apps.shell.agent.runtime.installation_facade import RuntimeInstallationFacadeMixin
from apps.shell.agent.runtime.main_chat_facade import RuntimeMainChatFacadeMixin
from apps.shell.agent.runtime.model_facade import RuntimeModelFacadeMixin
from apps.shell.agent.runtime.run_control_facade import RuntimeRunControlFacadeMixin
from apps.shell.agent.runtime.run_facade import RuntimeRunFacadeMixin
from apps.shell.agent.runtime.runnable_facade import RuntimeRunnableFacadeMixin
from apps.shell.agent.runtime.restricted_plugins import RuntimeRestrictedPluginFacadeMixin
from apps.shell.agent.runtime.studio_facade import RuntimeStudioFacadeMixin
from apps.shell.agent.runtime.support_facade import RuntimeSupportFacadeMixin
from apps.shell.agent.runtime.tool_facade import RuntimeToolFacadeMixin
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.workflow_facade import RuntimeWorkflowFacadeMixin
from apps.shell.agent.runtime.workflow_path import workflow_node_kind as _workflow_node_kind
from apps.shell.agent.tools.policy import RuntimePolicyCompiler
from apps.shell.credential_store import CredentialStore


class NativeRunEngine(
    RuntimeEngineFacadeMixin,
    RuntimeStudioFacadeMixin,
    RuntimeMainChatFacadeMixin,
    RuntimeRunFacadeMixin,
    RuntimeGroupFacadeMixin,
    RuntimeAgentFacadeMixin,
    RuntimeToolFacadeMixin,
    RuntimeRestrictedPluginFacadeMixin,
    RuntimeModelFacadeMixin,
    RuntimeWorkflowFacadeMixin,
    RuntimeRunControlFacadeMixin,
    RuntimeRunnableFacadeMixin,
    RuntimeSupportFacadeMixin,
    RuntimeInstallationFacadeMixin,
):
    """Persistent native agent execution engine shared by product entry points.

    AgentRuntimeService remains a compatibility name in apps.shell.agent_runtime
    because mature routes, tests, and UI-facing APIs still use the service label.
    """

    _tool_schemas = staticmethod(RuntimeToolOperations.model_tool_schemas)
    _validate_tool_payload = staticmethod(RuntimeToolOperations.validate_tool_payload)
    _parse_tool_calls = staticmethod(RuntimeToolOperations.parse_tool_calls)
    _parse_tool_request = staticmethod(RuntimeToolOperations.parse_tool_request)
    _default_tool_policy = staticmethod(RuntimePolicyCompiler.default_tool_policy)
    _default_workspace_policy = staticmethod(RuntimePolicyCompiler.default_workspace_policy)
    _node_kind = staticmethod(_workflow_node_kind)

    def __init__(
        self,
        db_path: Path | str | None = None,
        workspace_dir: Path | str | None = None,
        *,
        credential_store: CredentialStore | None = None,
        seed_templates: bool = True,
    ) -> None:
        self._install_runtime_model_adapters()
        self._install_runtime_foundation(
            db_path=db_path,
            workspace_dir=workspace_dir,
            credential_store=credential_store,
        )
        self._install_runtime_restricted_plugins()
        self._install_runtime_definition_layer()
        self._install_runtime_run_layer()
        runtime_timeline_factory = self._install_runtime_memory_and_core()
        self._install_runtime_agent_chat_entrypoints(
            runtime_timeline_factory=runtime_timeline_factory,
        )
        runtime_context_budget_checker, runtime_model_output_limiter = (
            self._install_runtime_run_budget_and_main_chat_model(
                runtime_timeline_factory=runtime_timeline_factory,
            )
        )
        self._install_runtime_tooling_and_custom_agent_loop(
            runtime_timeline_factory=runtime_timeline_factory,
            runtime_context_budget_checker=runtime_context_budget_checker,
            runtime_model_output_limiter=runtime_model_output_limiter,
        )
        self._install_runtime_agent_and_approval_services(
            runtime_timeline_factory=runtime_timeline_factory,
        )
        self._install_runtime_approval_runtime_services()
        self._install_runtime_main_chat_model_loop_runner(
            runtime_timeline_factory=runtime_timeline_factory,
            runtime_context_budget_checker=runtime_context_budget_checker,
        )
        self._install_runtime_workflow_planning_and_coordinator(
            runtime_timeline_factory=runtime_timeline_factory,
        )
        self._install_runtime_workflow_execution_and_async(
            runtime_timeline_factory=runtime_timeline_factory,
        )
        self._install_runtime_runnable_entrypoints()
        self._install_runtime_workflow_transitions(
            runtime_timeline_factory=runtime_timeline_factory,
        )
        self._install_runtime_run_control_and_shutdown(
            runtime_timeline_factory=runtime_timeline_factory,
        )
        self._init_db()
        self._install_runtime_post_db_support_services(
            seed_templates=seed_templates,
        )
