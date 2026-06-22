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
    RuntimeApprovalRuntimeServiceBundle,
    RuntimeApprovalServiceBundle,
    build_runtime_approval_runtime_services as _build_runtime_approval_runtime_services,
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
from apps.shell.agent.runtime.agent_chat_entrypoints import (
    RuntimeAgentChatEntrypointSetup,
    build_runtime_agent_chat_entrypoint_setup as _build_runtime_agent_chat_entrypoint_setup,
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
from apps.shell.agent.runtime.callbacks import supports_keyword
from apps.shell.agent.runtime.core_services import (
    RuntimeCoreServiceBundle,
    build_runtime_core_services as _build_runtime_core_services,
    RuntimeMemoryCoreSetup,
    build_runtime_memory_core_setup as _build_runtime_memory_core_setup,
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
from apps.shell.agent.runtime.foundation import (
    RuntimeFoundationSetup,
    build_runtime_foundation_setup as _build_runtime_foundation_setup,
)
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
from apps.shell.agent.runtime.main_chat_model import (
    MainChatModelCaller,
    RuntimeMainChatModelSetup,
    build_runtime_main_chat_model_setup as _build_runtime_main_chat_model_setup,
)
from apps.shell.agent.runtime.main_chat_model_loop import (
    MainChatModelLoopRunner,
    build_runtime_main_chat_model_loop_runner as _build_runtime_main_chat_model_loop_runner,
)
from apps.shell.agent.runtime.main_chat_runs import MainChatRunLifecycle
from apps.shell.agent.runtime.memory_services import RuntimeMemoryService
from apps.shell.agent.runtime.model_calling import (
    RuntimeModelCallAdapterBundle,
    RuntimeModelProfileChatAdapter,
    RuntimeOpenAICompatibleChatAdapter,
    build_runtime_model_call_adapters as _build_runtime_model_call_adapters,
    call_model_profile_chat_message as _runtime_call_model_profile_chat_message,
    callable_accepts_keyword as _callable_accepts_keyword,
    openai_compatible_chat as _runtime_openai_compatible_chat,
)
from apps.shell.agent.runtime.model_profiles import RuntimeAgentModelTester, RuntimeModelProfileResolver
from apps.shell.agent.runtime.model_compat import (
    build_legacy_model_call_adapters as _build_legacy_model_call_adapters,
    runtime_model_compat_provider as _runtime_model_compat_provider,
)
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
from apps.shell.agent.runtime.native_engine import NativeRunEngine
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
    RuntimeRunLayerSetup,
    RuntimeRunServiceBundle,
    build_runtime_run_layer_setup as _build_runtime_run_layer_setup,
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
from apps.shell.agent.runtime.service_access import (
    close_runtime_service as _close_runtime_service,
    resolve_runtime_service as _resolve_runtime_service,
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
    RuntimeToolingStack,
    build_runtime_tooling as _build_runtime_tooling,
    build_runtime_tooling_stack as _build_runtime_tooling_stack,
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
    WorkflowApprovalPauseCoordinator,
    WorkflowApprovalPauseProjection,
    WorkflowApprovalResumeContext,
    WorkflowApprovalResumeCoordinator,
    WorkflowApprovalTransitionContext,
)
from apps.shell.agent.runtime.workflow_child_approvals import (
    WorkflowChildPendingApprovalProjection,
)
from apps.shell.agent.runtime.workflow_outcomes import (
    WorkflowChildExecutionStatusProjection,
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
from apps.shell.agent.runtime.workflow_parallel import (
    WorkflowParallelExecutionPortBundle,
    WorkflowParallelNodeExecution,
)
from apps.shell.agent.runtime.workflow_projections import (
    WorkflowConditionNodeProjection,
    WorkflowContinuationFailureProjection,
    WorkflowEdgeFollowedCoordinator,
    WorkflowEdgeFollowedProjection,
    WorkflowLoopNodeProjection,
    WorkflowParallelBranchProjection,
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

_legacy_model_call_adapters = _build_legacy_model_call_adapters()
_legacy_model_profile_chat_adapter = _legacy_model_call_adapters.model_profile_chat_adapter
_legacy_openai_compatible_chat_adapter = _legacy_model_call_adapters.openai_compatible_chat_adapter


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


AgentRuntimeService = NativeRunEngine

_global_agent_runtime_service: NativeRunEngine | None = None
_runtime_service_lifecycle = RuntimeServiceLifecycle(factory=NativeRunEngine)


def get_native_agent_readiness() -> dict[str, Any]:
    """Return native main-agent readiness."""
    return _runtime_model_compat_provider().native_agent_readiness()


def get_native_run_engine() -> NativeRunEngine:
    global _global_agent_runtime_service
    _global_agent_runtime_service = _resolve_runtime_service(
        lifecycle=_runtime_service_lifecycle,
        current=_global_agent_runtime_service,
    )
    return _global_agent_runtime_service


def get_agent_runtime_service() -> NativeRunEngine:
    """Compatibility accessor for existing AppState, TaskRunner, and routes."""
    return get_native_run_engine()


def close_agent_runtime_service() -> None:
    global _global_agent_runtime_service
    _close_runtime_service(
        lifecycle=_runtime_service_lifecycle,
        current=_global_agent_runtime_service,
    )
    _global_agent_runtime_service = None
