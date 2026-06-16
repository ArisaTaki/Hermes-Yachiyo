"""Agent Studio, Skill Library, and Workflow runtime services."""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import time
from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from apps.core.tls import urlopen_with_bundled_ca
from apps.installer.workspace_init import get_workspace_status
from apps.shell.agent.repositories.agents import AgentDefinitionRepository
from apps.shell.agent.repositories.approvals import ApprovalRepository
from apps.shell.agent.repositories.artifacts import RunArtifactRepository
from apps.shell.agent.repositories.events import RunEventRepository
from apps.shell.agent.repositories.future_tasks import AgentFutureTaskStore
from apps.shell.agent.repositories.groups import RunGroupRepository
from apps.shell.agent.repositories.memories import AgentMemoryStore
from apps.shell.agent.repositories.runs import RunRepository
from apps.shell.agent.repositories.row_projections import (
    RuntimeRowProjector,
)
from apps.shell.agent.repositories.skill_folders import SkillFolderRepository
from apps.shell.agent.repositories.skills import SkillRepository
from apps.shell.agent.repositories.sqlite import (
    LockedConnection as _LockedConnection,
    LockedCursor as _LockedCursor,
    coerce_named_row as _coerce_named_row_value,
    named_row_factory as _named_row_factory,
    open_locked_runtime_connection as _open_runtime_sqlite_connection,
)
from apps.shell.agent.repositories.studio_deletions import StudioDeletionRepository
from apps.shell.agent.repositories.task_run_links import TaskRunLinkRepository
from apps.shell.agent.repositories.workspaces import TrustedWorkspaceRepository
from apps.shell.agent.repositories.workflows import WorkflowRepository
from apps.shell.agent.runtime.budget import (
    RunBudget as _RunBudget,
)
from apps.shell.agent.runtime.budget import (
    RunBudgetLimits as _RunBudgetLimits,
)
from apps.shell.agent.runtime.budget import (
    WorkflowRunBudget as _WorkflowRunBudget,
    context_budget_checker as _runtime_context_budget_checker,
    json_chars as _json_chars,
    limit_json_strings as _limit_json_strings,
    model_output_limiter as _runtime_model_output_limiter,
    run_budget_factory as _runtime_run_budget_factory,
    run_budget_from_timeline as _runtime_run_budget_from_timeline,
    tool_result_limiter as _runtime_tool_result_limiter,
    truncate_text as _truncate_text,
)
from apps.shell.agent.runtime.approval_lifecycle import (
    ApprovalCoordinator,
    ApprovalPauseProjectionCoordinator,
)
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.approval_execution import (
    RuntimeApprovalExecutionService,
    RuntimeApprovalRunDispatcher,
)
from apps.shell.agent.runtime.approval_services import (
    RuntimeApprovalServiceBundle,
    build_runtime_approval_services as _build_runtime_approval_services,
)
from apps.shell.agent.runtime.approval_snapshots import (
    ApprovalSnapshotBuilder,
    public_pending_approval as _public_pending_approval,
)
from apps.shell.agent.runtime.approval_transitions import RuntimeApprovalTransitionService
from apps.shell.agent.runtime.agent_context import (
    AgentContextBuilder,
    agent_goal_disallows_tool as _agent_goal_disallows_tool,
    agent_output_contract_rules as _agent_output_contract_rules,
    user_goal_from_agent_messages as _user_goal_from_agent_messages,
)
from apps.shell.agent.runtime.agent_facade import RuntimeAgentFacadeMixin
from apps.shell.agent.runtime.agent_outcomes import RuntimeAgentRunOutcomeProjector
from apps.shell.agent.runtime.agent_preparation import RuntimeAgentRunPreparer
from apps.shell.agent.runtime.agent_runs import (
    RuntimeAgentRunAsyncCoordinator,
    RuntimeAgentRunCoordinator,
    RuntimeAgentRunExecutor,
    RuntimeAgentRunStarter,
)
from apps.shell.agent.runtime.agent_services import (
    RuntimeAgentServiceBundle,
    build_runtime_agent_services as _build_runtime_agent_services,
)
from apps.shell.agent.runtime.agent_skills import RuntimeAgentSkillLoader
from apps.shell.agent.runtime.skill_attachments import RuntimeAgentSkillAttachmentService
from apps.shell.agent.runtime.cancellation import (
    RunCancellationProjection,
    WorkflowCancellationProjectionCoordinator,
    WorkflowCancellationTarget,
)
from apps.shell.agent.runtime.core_services import (
    RuntimeCoreServiceBundle,
    build_runtime_core_services as _build_runtime_core_services,
)
from apps.shell.agent.runtime.clock import iso_epoch as _iso_epoch, utc_now_iso as _now
from apps.shell.agent.runtime.config import (
    DEFAULT_AGENT_IDS as _DEFAULT_AGENT_IDS,
    EXECUTION_BACKENDS as _EXECUTION_BACKENDS,
    FINAL_RUN_STATUSES as _FINAL_RUN_STATUSES,
    MAIN_CHAT_AGENT_ID as _MAIN_CHAT_AGENT_ID,
    MARKET_AGENT_OPERATING_DOCTRINE as _MARKET_AGENT_OPERATING_DOCTRINE,
    MEMORY_CONTENT_MAX_CHARS as _MEMORY_CONTENT_MAX_CHARS,
    MEMORY_CONTEXT_LIMIT as _MEMORY_CONTEXT_LIMIT,
    NATIVE_LIBRARY_SOURCE_TYPES as _NATIVE_LIBRARY_SOURCE_TYPES,
    SKILL_SOURCE_TYPES as _SKILL_SOURCE_TYPES,
    SYSTEM_AGENT_IDS as _SYSTEM_AGENT_IDS,
    WORKFLOW_NODE_TYPES as _WORKFLOW_NODE_TYPES,
    is_active_run_status as _is_active_run_status,
    is_native_library_source_type as _is_native_library_source_type,
    normalize_execution_backend as _normalize_execution_backend,
    normalize_skill_source_type as _normalize_skill_source_type,
)
from apps.shell.agent.runtime.credentials import RuntimeCredentialService
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.delegation import ChatRunnableMentionParser
from apps.shell.agent.runtime.definition_services import (
    RuntimeDefinitionServiceBundle,
    build_runtime_definition_services as _build_runtime_definition_services,
)
from apps.shell.agent.runtime.definition_names import RuntimeDefinitionNameGuard
from apps.shell.agent.runtime.engine_state import (
    RuntimeEngineStateBundle,
    build_runtime_engine_state as _build_runtime_engine_state,
)
from apps.shell.agent.runtime.engine_facade import RuntimeEngineFacadeMixin
from apps.shell.agent.runtime.errors import AgentApprovalRequired, AgentRuntimeError
from apps.shell.agent.runtime.events import (
    RuntimeAgentRunEventRecorder,
    RuntimeRunEventRecorder,
    RuntimeTaskEventRecorder,
    RuntimeTaskModelEventBuilder,
    RuntimeToolCallEventRecorder,
    RuntimeTraceEventBuilder,
    ToolEventPayloadBuilder,
    artifact_created_payload as _artifact_created_payload,
    canonical_run_event_aliases as _canonical_run_event_aliases,
    canonical_tool_event_payload as _canonical_tool_event_payload,
    canonical_tool_input_preview as _canonical_tool_input_preview,
    memory_retrieved_payload as _memory_retrieved_payload,
    memory_skill_trace_event as _memory_skill_trace_event,
    memory_trace_result as _memory_trace_result,
    redact_json_value as _redact_json_value,
    redact_secrets,
    runtime_trace_input_preview as _runtime_trace_input_preview,
    skill_trace_result as _skill_trace_result,
    task_run_event_payload as _task_run_event_payload,
    tool_input_preview as _tool_input_preview,
    tool_trace_status as _tool_trace_status,
)
from apps.shell.agent.runtime.future_task_service import RuntimeFutureTaskService
from apps.shell.agent.runtime.future_task_scheduler import FutureTaskTriggerScheduler
from apps.shell.agent.runtime.installation_facade import RuntimeInstallationFacadeMixin
from apps.shell.agent.runtime.main_chat_config import (
    MainChatRuntimeConfigBuilder,
    MainChatVirtualAgentProjector,
)
from apps.shell.agent.runtime.main_chat_facade import RuntimeMainChatFacadeMixin
from apps.shell.agent.runtime.main_chat_model import MainChatModelCaller
from apps.shell.agent.runtime.main_chat_model_loop import MainChatModelLoopRunner
from apps.shell.agent.runtime.main_chat_runs import MainChatRunLifecycle
from apps.shell.agent.runtime.memory_services import RuntimeMemoryService
from apps.shell.agent.runtime.model_calling import (
    RuntimeModelProfileChatAdapter,
    RuntimeOpenAICompatibleChatAdapter,
    call_model_profile_chat_message as _runtime_call_model_profile_chat_message,
    callable_accepts_keyword as _callable_accepts_keyword,
    openai_compatible_chat as _runtime_openai_compatible_chat,
)
from apps.shell.agent.runtime.model_profiles import RuntimeAgentModelTester, RuntimeModelProfileResolver
from apps.shell.agent.runtime.model_facade import RuntimeModelFacadeMixin
from apps.shell.agent.runtime.model_messages import (
    RESPONSES_STREAM_REASONING_EVENTS as _RESPONSES_STREAM_REASONING_EVENTS,
    ModelOutputText as _ModelOutputText,
    coalesce_model_message as _coalesce_model_message,
    coalesced_stream_tool_calls as _coalesced_stream_tool_calls,
    coerce_function_call as _coerce_function_call,
    coerce_model_usage as _coerce_model_usage,
    coerce_tool_call as _coerce_tool_call,
    coerce_tool_calls as _coerce_tool_calls,
    first_present as _first_present,
    is_reasoning_content_part as _is_reasoning_content_part,
    message_content_part_type as _message_content_part_type,
    message_content_text as _message_content_text,
    message_field as _message_field,
    message_text_value as _message_text_value,
    message_visible_content_text as _message_visible_content_text,
    model_message_metadata as _model_message_metadata,
    model_output_completed_payload as _model_output_completed_payload,
    model_output_metadata as _model_output_metadata,
    responses_stream_event_type as _responses_stream_event_type,
    responses_stream_is_reasoning_event as _responses_stream_is_reasoning_event,
    responses_stream_text_delta as _responses_stream_text_delta,
    responses_stream_text_done as _responses_stream_text_done,
    responses_stream_text_key as _responses_stream_text_key,
    responses_stream_tool_call as _responses_stream_tool_call,
    merge_stream_tool_call_delta as _merge_stream_tool_call_delta,
    stream_choice_index as _stream_choice_index,
    stream_chunk_finish_reason as _stream_chunk_finish_reason,
    stream_chunk_text as _stream_chunk_text,
    stream_chunk_tool_calls as _stream_chunk_tool_calls,
    stream_chunk_usage as _stream_chunk_usage,
    stream_index_value as _stream_index_value,
    tool_arguments_text as _tool_arguments_text,
)
from apps.shell.agent.runtime.recorders import (
    RuntimeRecorderBundle,
    build_runtime_recorders as _build_runtime_recorders,
    build_tool_pending_approval as _build_tool_pending_approval,
)
from apps.shell.agent.runtime.run_projections import (
    AgentRunGroupProjectionCoordinator,
    ApprovalResumeProjectionCoordinator,
    RunProjectionCoordinator,
)
from apps.shell.agent.runtime.run_readiness import (
    RuntimeRunReadinessValidator,
    native_agent_readiness as _runtime_native_agent_readiness,
)
from apps.shell.agent.runtime.run_cancellation import (
    RuntimeRunCancellationCoordinator,
    RuntimeRunCancellationService,
)
from apps.shell.agent.runtime.run_deletion import RuntimeRunDeletionService
from apps.shell.agent.runtime.run_rerun import RuntimeRunRerunService
from apps.shell.agent.runtime.run_requests import RuntimeRunRequestParser
from apps.shell.agent.runtime.run_services import (
    RuntimeRunServiceBundle,
    build_runtime_run_services as _build_runtime_run_services,
)
from apps.shell.agent.runtime.run_facade import RUNTIME_UNSET as _UNSET, RuntimeRunFacadeMixin
from apps.shell.agent.runtime.run_control_facade import RuntimeRunControlFacadeMixin
from apps.shell.agent.runtime.run_status import RuntimeTerminalRunResolver
from apps.shell.agent.runtime.run_timeline import RuntimeRunTimelineService
from apps.shell.agent.runtime.runnable_names import RuntimeRunnableNameResolver
from apps.shell.agent.runtime.runnable_services import (
    RuntimeRunnableServiceBundle,
    build_runtime_runnable_services as _build_runtime_runnable_services,
)
from apps.shell.agent.runtime.runnable_facade import RuntimeRunnableFacadeMixin
from apps.shell.agent.runtime.runnables import (
    RuntimeRunnableCatalog,
    RuntimeRunnableResolver,
    RuntimeRunnableRunCoordinator,
)
from apps.shell.agent.runtime.schema import (
    RuntimeSchemaService,
    RuntimeSchemaMigrator,
    agent_model_credential_ref as _agent_model_credential_ref,
    initialize_runtime_schema as _initialize_runtime_schema,
)
from apps.shell.agent.runtime.service_lifecycle import RuntimeServiceLifecycle
from apps.shell.agent.runtime.seed_templates import RuntimeSeedTemplateService
from apps.shell.agent.runtime.studio_facade import RuntimeStudioFacadeMixin
from apps.shell.agent.runtime.paths import (
    RuntimeDirectoryLayout,
    native_skill_home as _native_skill_home,
    oha_yachiyo_home as _oha_yachiyo_home,
    runtime_directory_layout as _runtime_directory_layout,
)
from apps.shell.agent.runtime.serialization import (
    json_dump_sorted as _json_dump,
    json_load as _json_load,
    slug as _slug,
)
from apps.shell.agent.runtime.shutdown import RuntimeShutdownService
from apps.shell.agent.runtime.support_facade import RuntimeSupportFacadeMixin
from apps.shell.agent.runtime.skill_content import (
    SkillContentInspector,
    content_hash as _skill_content_hash,
    parse_frontmatter as _parse_skill_frontmatter,
)
from apps.shell.agent.runtime.skill_import import SkillImportPreparer, SkillImportSourceResolver
from apps.shell.agent.runtime.skill_import_service import RuntimeSkillImportService
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from apps.shell.agent.runtime.skill_install_service import RuntimeSkillInstallService
from apps.shell.agent.runtime.skill_sources import (
    SkillSourceDiscovery,
    skill_deletion_key as _runtime_skill_deletion_key,
)
from apps.shell.agent.runtime.skill_sync import SkillSyncPlanner
from apps.shell.agent.runtime.skill_sync_service import RuntimeSkillSyncService
from apps.shell.agent.runtime.tool_brokers import RuntimeToolBrokerFactory
from apps.shell.agent.runtime.tool_requests import (
    MAX_AGENT_TOOL_ITERATIONS as _MAX_AGENT_TOOL_ITERATIONS,
    ToolRequestParser,
    normalize_tool_iteration as _normalize_tool_iteration,
    normalize_tool_name as _normalize_tool_name,
)
from apps.shell.agent.runtime.tool_approvals import (
    ToolApprovalClaimProjection,
    ToolApprovalContinuationHandoff,
    ToolApprovalContinuationOutcome,
    ToolApprovalCustomApiContinuationRequest,
    ToolApprovalExecutionFailureProjection,
    ToolApprovalExecutionFollowup,
    ToolApprovalExecutionRequest,
    ToolPendingApprovalBuilder,
    ToolApprovalResumeContext,
    ToolApprovalTransitionContext,
)
from apps.shell.agent.runtime.tool_approval_resume import RuntimeToolApprovalResumeService
from apps.shell.agent.runtime.tool_execution import RuntimeToolCallExecutor, RuntimeToolRequestRunner
from apps.shell.agent.runtime.tooling import (
    RuntimeToolingBundle,
    build_runtime_tooling as _build_runtime_tooling,
)
from apps.shell.agent.runtime.tool_operations import RuntimeToolOperations
from apps.shell.agent.runtime.tool_facade import RuntimeToolFacadeMixin
from apps.shell.agent.runtime.tool_loop import (
    RuntimeToolLoopProjectionBuilder,
)
from apps.shell.agent.runtime.timeline import (
    RuntimeAgentTimelineBuilder,
    runtime_timeline_factory as _runtime_timeline_factory,
)

from apps.shell.agent.runtime.workflow_continuation import (
    WorkflowContinuationCoordinator,
    WorkflowContinuationPortBundle,
)
from apps.shell.agent.runtime.workflow_approval_execution import (
    RuntimeWorkflowApprovalExecutionService,
)
from apps.shell.agent.runtime.workflow_approvals import (
    WorkflowApprovalPauseProjection,
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
    WorkflowApprovalTransitionContext,
)
from apps.shell.agent.runtime.workflow_outcomes import (
    WorkflowChildOutcomeCoordinator,
    WorkflowChildRunProjection,
    WorkflowChildStatusProjection,
    WorkflowParentResumeFailureProjection,
)
from apps.shell.agent.runtime.workflow_path import (
    WorkflowDefinitionValidator,
    WorkflowPathPlanner,
    workflow_node_kind as _workflow_node_kind,
)
from apps.shell.agent.runtime.workflow_facade import RuntimeWorkflowFacadeMixin
from apps.shell.agent.runtime.workflow_nodes import (
    WorkflowAgentNodeExecution,
    WorkflowAgentNodeHandoff,
    WorkflowArtifactNodeWrite,
    WorkflowNodePortBundle,
    WorkflowSubworkflowNodeExecution,
)
from apps.shell.agent.runtime.workflow_parent_resume import WorkflowParentResumeCoordinator
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowEdgeFollowedProjection,
    WorkflowLoopNodeProjection,
    WorkflowParallelNodeProjection,
    WorkflowProjectionPortBundle,
    WorkflowRunCompletionProjection,
    WorkflowStartNodeProjection,
)
from apps.shell.agent.runtime.workflow_resume import (
    RunTransitionProjectionCoordinator,
    WorkflowParentRunLocator,
    WorkflowResumePlanner,
)
from apps.shell.agent.runtime.workflow_runs import (
    RuntimeWorkflowRunAsyncCoordinator,
    RuntimeWorkflowRunCoordinator,
    RuntimeWorkflowRunStarter,
)
from apps.shell.agent.runtime.workflow_run_outcomes import WorkflowRunOutcomeProjector
from apps.shell.agent.runtime.workflow_services import (
    RuntimeWorkflowExecutionServiceBundle,
    RuntimeWorkflowPlanningServiceBundle,
    RuntimeWorkflowTransitionServiceBundle,
    build_runtime_workflow_execution_services as _build_runtime_workflow_execution_services,
    build_runtime_workflow_planning_services as _build_runtime_workflow_planning_services,
    build_runtime_workflow_transition_services as _build_runtime_workflow_transition_services,
)
from apps.shell.agent.runtime.workflow_start import WorkflowRunStartProjector
from apps.shell.agent.runtime.workspace_policy import RuntimeWorkspacePolicyService
from apps.shell.agent.tools.broker import (
    _TERMINAL_PROCESS_LOCK,
    _TERMINAL_PROCESSES,
    ToolBroker,
    cancel_terminal_process_groups,
)
from apps.shell.agent.tools.workspace import (
    _apply_single_file_unified_diff,
    _atomic_write_text,
    _is_within,
    _read_text,
    _safe_rel_path,
    _sha256_bytes,
    _sha256_file,
)
from apps.shell.agent.tools.policy import (
    FUTURE_TASK_TOOL_NAMES as _FUTURE_TASK_TOOL_NAMES,
    HIGH_RISK_AGENT_TOOLS as _HIGH_RISK_AGENT_TOOLS,
    KNOWN_AGENT_TOOLS as _KNOWN_AGENT_TOOLS,
    MEMORY_KINDS as _MEMORY_KINDS,
    MEMORY_TOOL_NAMES as _MEMORY_TOOL_NAMES,
    MEMORY_SCOPES as _MEMORY_SCOPES,
    RuntimePolicyCompiler,
    TOOL_DESCRIPTORS,
    PolicyGate,
    ToolDescriptor,
    ToolDescriptorRegistry,
    TOOL_FUNCTION_NAMES as _TOOL_FUNCTION_NAMES,
    TOOL_NAME_ALIASES as _TOOL_NAME_ALIASES,
)
from apps.shell.credential_store import (
    CredentialStore,
    create_credential_store,
)
from apps.shell.model_profiles import (
    get_model_profile_service,
    openai_compatible_chat_message,
    read_openai_compatible_chat_timeout,
    supports_openai_compatible_api,
)
from packages.security import (
    contains_sensitive_text,
    redact_api_error_text,
)

_legacy_model_profile_chat_adapter = RuntimeModelProfileChatAdapter(
    chat_message_provider=lambda: openai_compatible_chat_message,
)
_legacy_openai_compatible_chat_adapter = RuntimeOpenAICompatibleChatAdapter(
    timeout_provider=lambda: read_openai_compatible_chat_timeout(),
    urlopen=lambda *args, **kwargs: urlopen_with_bundled_ca(*args, **kwargs),
    redact_error=lambda value: redact_secrets(value),
)


def _call_model_profile_chat_message(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
) -> Any:
    return _legacy_model_profile_chat_adapter.call(
        base_url,
        model,
        api_key,
        messages,
        tools=tools,
        stream=stream,
    )


class NativeRunEngine(
    RuntimeEngineFacadeMixin,
    RuntimeStudioFacadeMixin,
    RuntimeMainChatFacadeMixin,
    RuntimeRunFacadeMixin,
    RuntimeAgentFacadeMixin,
    RuntimeToolFacadeMixin,
    RuntimeModelFacadeMixin,
    RuntimeWorkflowFacadeMixin,
    RuntimeRunControlFacadeMixin,
    RuntimeRunnableFacadeMixin,
    RuntimeSupportFacadeMixin,
    RuntimeInstallationFacadeMixin,
):
    """Persistent native agent execution engine shared by product entry points.

    AgentRuntimeService is kept as a compatibility name below because mature
    routes, tests, and UI-facing APIs still use the service label.
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
        workflow_execution_services = _build_runtime_workflow_execution_services(
            engine=self,
            iso_epoch=lambda value: _iso_epoch(value),
            workflow_path=self.workflow_path_planner.workflow_path,
            workflow_nodes_by_id=self.workflow_path_planner.nodes_by_id,
            workflow_next_node_id=self.workflow_path_planner.next_node_id,
            workflow_parallel_plan=self.workflow_path_planner.parallel_plan,
            workflow_condition_selection=self.workflow_path_planner.condition_selection,
            workflow_loop_selection=self.workflow_path_planner.loop_selection,
            workflow_loop_iterations_from_timeline=(
                self.workflow_path_planner.loop_iterations_from_timeline
            ),
            workflow_loop_step_limit=self.workflow_path_planner.loop_step_limit,
            workflow_run_started_projection=self.workflow_run_start_projector.started_projection,
            workflow_artifact_write=lambda run, artifact_path, context: (
                self.tool_brokers.for_run(
                    run_id=str(run.get("run_id") or ""),
                    workspace_policy=self._default_workspace_policy(),
                    artifacts_dir=self.workflow_artifacts_dir,
                ).artifact_write(artifact_path, context)
            ),
            claim_pending_approval=self.run_approvals.claim_pending_approval,
            get_current_run=lambda run_id: self.get_run(run_id),
            pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
            get_run=lambda run_id: self.get_run(run_id),
            merge_workflow_child_run_outcome=lambda timeline, artifacts, child_run, label: (
                self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
            ),
            timeline_factory=runtime_timeline_factory,
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
            approve_workflow_node=lambda run_id, **kwargs: self.approvals.approve_workflow_node(run_id, **kwargs),
        )
        self._install_runtime_workflow_execution_services(workflow_execution_services)
        self.workflow_run_async_coordinator = RuntimeWorkflowRunAsyncCoordinator(
            get_workflow=lambda workflow_id: self.get_workflow(workflow_id),
            validate_workflow=lambda nodes, edges: self.validate_workflow(nodes, edges),
            validate_workflow_agent_nodes=lambda nodes: self._validate_workflow_agent_nodes(nodes),
            validate_workflow_subworkflow_nodes=lambda nodes, **kwargs: (
                self._validate_workflow_subworkflow_nodes(nodes, **kwargs)
            ),
            validate_workflow_runnable_steps=lambda nodes: self._validate_workflow_runnable_steps(nodes),
            validate_workflow_agent_run_readiness=lambda nodes: self._validate_workflow_agent_run_readiness(nodes),
            starter=self.workflow_run_starter,
            start_projector=self.workflow_run_start_projector,
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            continue_workflow_run=lambda run, workflow, **kwargs: self._continue_workflow_run(
                run,
                workflow,
                **kwargs,
            ),
            project_background_failure=lambda run, **kwargs: self.workflow_continuation.project_background_failure(
                run,
                **kwargs,
            ),
            resolve_runnable=lambda **kwargs: self.resolve_runnable(**kwargs),
            error_type=AgentRuntimeError,
        )
        self.workflow_approval_execution = RuntimeWorkflowApprovalExecutionService(
            pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
            workflow_for_run_resume=lambda run: self._workflow_for_run_resume(run),
            workflow_run_is_group_root=lambda run: self._workflow_run_is_group_root(run),
            workflow_approval_resume=self.workflow_approval_resume,
        )
        self.runnable_resolver = RuntimeRunnableResolver(
            main_chat_agent_id=_MAIN_CHAT_AGENT_ID,
            main_chat_virtual_agent=self._main_chat_virtual_agent,
            ensure_row_factory=self._ensure_row_factory,
            fetch_agent_by_id=lambda agent_id: self._conn.execute(
                "SELECT * FROM agents WHERE agent_id=?",
                (agent_id,),
            ).fetchone(),
            fetch_workflow_by_id=lambda workflow_id: self._conn.execute(
                "SELECT * FROM workflows WHERE workflow_id=?",
                (workflow_id,),
            ).fetchone(),
            fetch_agents_by_name=lambda name: self._conn.execute(
                "SELECT * FROM agents WHERE LOWER(name)=LOWER(?) OR LOWER(nickname)=LOWER(?)",
                (name, name),
            ).fetchall(),
            fetch_workflow_by_name=lambda name: self._conn.execute(
                "SELECT * FROM workflows WHERE LOWER(name)=LOWER(?)",
                (name,),
            ).fetchone(),
            row_to_agent=self._row_to_agent,
            row_to_workflow=self._row_to_workflow,
            agent_summary=self._agent_runnable_summary,
            workflow_summary=self._workflow_runnable_summary,
            error_type=AgentRuntimeError,
        )
        runnable_services = _build_runtime_runnable_services(
            conn=self._conn,
            db_lock=self._db_lock,
            create_run_for_runnable=lambda **kwargs: self.create_run_for_runnable(**kwargs),
            future_task_store=lambda **kwargs: self._future_task_store(**kwargs),
            now=_now,
            redact_secrets=redact_secrets,
            error_type=AgentRuntimeError,
            list_runnables=lambda: list(self.list_runnables().get("runnables") or []),
            node_kind=self._node_kind,
            get_agent=self.get_agent,
            resolve_runnable=self.runnable_resolver.resolve,
            create_agent_run=self.create_agent_run,
            create_workflow_run=self.create_workflow_run,
            create_agent_run_async=self.create_agent_run_async,
            create_workflow_run_async=self.create_workflow_run_async,
        )
        self._install_runtime_runnable_services(runnable_services)
        self.future_task_service = RuntimeFutureTaskService(
            future_task_store=lambda **kwargs: self._future_task_store(**kwargs),
            resolve_runnable=self.runnable_resolver.resolve,
            trigger_scheduler=self.future_task_scheduler,
            default_runnable_id=_MAIN_CHAT_AGENT_ID,
            error_type=AgentRuntimeError,
        )
        self.agent_run_group_projection = AgentRunGroupProjectionCoordinator(
            get_run_group=lambda run_group_id: self.get_run_group(run_group_id),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(
                run_group_id,
                **kwargs,
            ),
        )
        workflow_transition_services = _build_runtime_workflow_transition_services(
            parent_runs_waiting_for_child=lambda child_run: self._workflow_parent_runs_waiting_for_child(child_run),
            workflow_run_is_group_root=lambda workflow_run: self._workflow_run_is_group_root(workflow_run),
            workflow_child_node_context=lambda timeline, child_run: self._workflow_child_node_context(timeline, child_run),
            merge_workflow_child_run_outcome=lambda timeline, artifacts, child_run, label: (
                self._merge_workflow_child_run_outcome(timeline, artifacts, child_run, label)
            ),
            workflow_for_run_resume=lambda workflow_run: self._workflow_for_run_resume(workflow_run),
            workflow_resume_start_index=lambda workflow, workflow_run, child_run_id: (
                self._workflow_resume_start_index(workflow, workflow_run, child_run_id)
            ),
            workflow_next_node_id=lambda workflow, node_id, context: (
                self._workflow_next_node_id(workflow, node_id, context)
            ),
            continue_workflow_run=lambda run, workflow, **kwargs: self.workflow_continuation.continue_run(run, workflow, **kwargs),
            timeline_factory=runtime_timeline_factory,
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
            update_agent_run_group_if_root=lambda run: self._update_agent_run_group_if_root(run),
            mark_parent_workflows_child_running=lambda run: self._mark_parent_workflows_child_running(run),
            resume_parent_workflows_after_child_update=lambda run: self._resume_parent_workflows_after_child_update(run),
            get_run=lambda run_id: self.get_run(run_id),
        )
        self._install_runtime_workflow_transition_services(workflow_transition_services)
        self._install_runtime_run_cancellation(
            RuntimeRunCancellationService(
                get_run=lambda run_id: self.get_run(run_id),
                update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
                append_run_event=lambda run_id, event_type, payload: self.append_run_event(
                    run_id,
                    event_type,
                    payload,
                ),
                timeline_factory=runtime_timeline_factory,
                workflow_cancellation=self.workflow_cancellation,
                workflow_run_is_group_root=lambda result: self._workflow_run_is_group_root(result),
                project_cancelled_workflow_group_if_root=lambda run, result: (
                    self._project_cancelled_workflow_group_if_root(run, result)
                ),
                resume_parent_workflows_after_child_update=lambda projected: (
                    self._resume_parent_workflows_after_child_update(projected)
                ),
                project_child_run_transition=lambda result: self._project_child_run_transition(result),
                final_statuses=_FINAL_RUN_STATUSES,
            )
        )
        self._install_runtime_run_rerun(
            RuntimeRunRerunService(
                get_run=lambda run_id: self.get_run(run_id),
                create_agent_run=lambda payload: self.create_agent_run(payload),
                create_workflow_run=lambda payload: self.create_workflow_run(payload),
                timeline_factory=runtime_timeline_factory,
                append_run_event=lambda run_id, event_type, payload: self.append_run_event(
                    run_id,
                    event_type,
                    payload,
                ),
                update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
                resolve_runnable=lambda **kwargs: self.resolve_runnable(**kwargs),
                final_statuses=_FINAL_RUN_STATUSES,
                error_type=AgentRuntimeError,
            )
        )
        self._install_runtime_run_deletion(
            RuntimeRunDeletionService(
                get_run=lambda run_id: self.get_run(run_id),
                group_runs=lambda run_group_id: self.run_groups.runs(run_group_id),
                delete_run_rows=lambda targets, **kwargs: self.runs.delete_rows(
                    targets,
                    **kwargs,
                ),
                delete_artifacts=lambda *args, **kwargs: self.run_artifacts.delete_files(
                    *args,
                    **kwargs,
                ),
                delete_group=lambda run_group_id: self.run_groups.delete(run_group_id),
                remove_group_run_ids=lambda run_group_id, deleted_ids: (
                    self.run_groups.remove_run_ids(run_group_id, deleted_ids)
                ),
                commit=lambda: self._conn.commit(),
                is_active_run_status=_is_active_run_status,
                error_type=AgentRuntimeError,
            )
        )
        self._install_runtime_shutdown(
            RuntimeShutdownService(
                conn=self._conn,
                credential_store=self._credential_store,
                is_closed=lambda: self._closed,
                mark_not_accepting=lambda: setattr(self, "_accepting_runs", False),
                mark_closed=lambda: setattr(self, "_closed", True),
                cancel_terminal_process_groups=lambda: cancel_terminal_process_groups(),
                ensure_row_factory=lambda: self._ensure_row_factory(),
                cancel_run=lambda run_id: self.cancel_run(run_id),
            )
        )
        self._init_db()
        self.workspace_policy_service = RuntimeWorkspacePolicyService(
            conn=self._conn,
            agent_workspaces_dir=self.agent_workspaces_dir,
            trusted_workspaces=self.trusted_workspaces,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            default_workspace_policy=self._default_workspace_policy,
            json_load=_json_load,
            json_dump=_json_dump,
            now=_now,
        )
        self._migrate_agent_workspace_policies()
        self.seed_template_service = RuntimeSeedTemplateService(
            conn=self._conn,
            create_agent=self.create_agent,
            create_workflow=self.create_workflow,
            default_tool_policy=self._default_tool_policy,
            default_workspace_policy=self._default_workspace_policy,
            has_studio_deletion=self._has_studio_deletion,
        )
        self.skill_import_service = RuntimeSkillImportService(
            conn=self._conn,
            source_resolver=self.skill_import_sources,
            preparer=self.skill_import_preparer,
            skill_records=self.skill_records,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            skill_deletion_key=self._skill_deletion_key,
            clear_studio_deletion=self._clear_studio_deletion,
            get_skill=self.get_skill,
            error_type=AgentRuntimeError,
        )
        self.skill_sync_service = RuntimeSkillSyncService(
            conn=self._conn,
            skill_sync=self.skill_sync,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            skill_deletion_key=self._skill_deletion_key,
            has_studio_deletion=self._has_studio_deletion,
            clear_studio_deletion=self._clear_studio_deletion,
            import_skill_root=self._import_skill_root,
            now=_now,
            redact_error=redact_api_error_text,
            error_type=AgentRuntimeError,
        )
        self.skill_install_service = RuntimeSkillInstallService(
            validator=self.skill_install_validator,
            skill_installs_dir=self.skill_installs_dir,
            skill_installs_native_home=self.skill_installs_native_home,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            sync_installed_skills=self.sync_installed_skills,
            run_command=lambda *args, **kwargs: subprocess.run(*args, **kwargs),
            now=_now,
            redact_secrets=redact_secrets,
            error_type=AgentRuntimeError,
        )
        if seed_templates:
            self._seed_templates()

AgentRuntimeService = NativeRunEngine

_global_agent_runtime_service: NativeRunEngine | None = None
_runtime_service_lifecycle = RuntimeServiceLifecycle(factory=NativeRunEngine)


def get_native_agent_readiness() -> dict[str, Any]:
    """Return native main-agent readiness."""
    return _runtime_native_agent_readiness(
        profile_service_factory=lambda: get_model_profile_service(),
        supports_openai_compatible_api=supports_openai_compatible_api,
        redact_error=redact_secrets,
    )


def get_native_run_engine() -> NativeRunEngine:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is not None:
        _runtime_service_lifecycle.set_current(_global_agent_runtime_service)
        return _global_agent_runtime_service
    _global_agent_runtime_service = _runtime_service_lifecycle.get()
    return _global_agent_runtime_service


def get_agent_runtime_service() -> NativeRunEngine:
    """Compatibility accessor for existing AppState, TaskRunner, and routes."""
    return get_native_run_engine()


def close_agent_runtime_service() -> None:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is not None:
        _runtime_service_lifecycle.set_current(_global_agent_runtime_service)
    _runtime_service_lifecycle.close()
    _global_agent_runtime_service = None
