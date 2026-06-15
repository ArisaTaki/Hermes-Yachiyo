"""Agent Studio, Skill Library, and Workflow runtime services."""

from __future__ import annotations

import inspect
import json
import logging
import os
import sqlite3
import subprocess
import threading
import time
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from urllib import error as urlerror
from urllib import request as urlrequest
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
    row_to_agent as _project_agent_row,
    row_to_agent_private as _project_agent_private_row,
    row_to_run as _project_run_row,
    row_to_run_group as _project_run_group_row,
    row_to_skill as _project_skill_row,
    row_to_skill_folder as _project_skill_folder_row,
    row_to_workflow as _project_workflow_row,
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
    check_context_budget as _runtime_check_context_budget,
    json_chars as _json_chars,
    limit_json_strings as _limit_json_strings,
    limit_model_output as _runtime_limit_model_output,
    limit_tool_result as _runtime_limit_tool_result,
    run_budget_from_timeline as _runtime_run_budget_from_timeline,
    truncate_text as _truncate_text,
)
from apps.shell.agent.runtime.approval_lifecycle import (
    ApprovalCoordinator,
    ApprovalPauseProjectionCoordinator,
)
from apps.shell.agent.runtime.approval_resume import ApprovalResumeCoordinator
from apps.shell.agent.runtime.approval_execution import RuntimeApprovalExecutionService
from apps.shell.agent.runtime.approval_services import (
    RuntimeApprovalServiceBundle,
    build_runtime_approval_services as _build_runtime_approval_services,
)
from apps.shell.agent.runtime.approval_snapshots import (
    ApprovalSnapshotBuilder,
    public_pending_approval as _runtime_public_pending_approval,
)
from apps.shell.agent.runtime.approval_transitions import RuntimeApprovalTransitionService
from apps.shell.agent.runtime.agent_context import (
    AgentContextBuilder,
    agent_goal_disallows_tool as _runtime_agent_goal_disallows_tool,
    agent_output_contract_rules as _runtime_agent_output_contract_rules,
    user_goal_from_agent_messages as _runtime_user_goal_from_agent_messages,
)
from apps.shell.agent.runtime.agent_outcomes import RuntimeAgentRunOutcomeProjector
from apps.shell.agent.runtime.agent_preparation import RuntimeAgentRunPreparer
from apps.shell.agent.runtime.agent_runs import RuntimeAgentRunStarter
from apps.shell.agent.runtime.agent_services import (
    RuntimeAgentServiceBundle,
    build_runtime_agent_services as _build_runtime_agent_services,
)
from apps.shell.agent.runtime.agent_skills import RuntimeAgentSkillLoader
from apps.shell.agent.runtime.cancellation import (
    RunCancellationProjection,
    WorkflowCancellationProjectionCoordinator,
    WorkflowCancellationTarget,
)
from apps.shell.agent.runtime.core_services import (
    RuntimeCoreServiceBundle,
    build_runtime_core_services as _build_runtime_core_services,
)
from apps.shell.agent.runtime.credentials import RuntimeCredentialService
from apps.shell.agent.runtime.custom_api_agent import RuntimeCustomApiAgentLoop
from apps.shell.agent.runtime.delegation import ChatRunnableMentionParser
from apps.shell.agent.runtime.definition_services import (
    RuntimeDefinitionServiceBundle,
    build_runtime_definition_services as _build_runtime_definition_services,
)
from apps.shell.agent.runtime.engine_state import (
    RuntimeEngineStateBundle,
    build_runtime_engine_state as _build_runtime_engine_state,
)
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
    runtime_trace_input_preview as _runtime_trace_input_preview,
    skill_trace_result as _skill_trace_result,
    task_run_event_payload as _task_run_event_payload,
    tool_input_preview as _tool_input_preview,
    tool_trace_status as _tool_trace_status,
)
from apps.shell.agent.runtime.future_task_service import RuntimeFutureTaskService
from apps.shell.agent.runtime.future_task_scheduler import FutureTaskTriggerScheduler
from apps.shell.agent.runtime.main_chat_config import MainChatRuntimeConfigBuilder
from apps.shell.agent.runtime.main_chat_model import MainChatModelCaller
from apps.shell.agent.runtime.main_chat_model_loop import MainChatModelLoopRunner
from apps.shell.agent.runtime.main_chat_runs import MainChatRunLifecycle
from apps.shell.agent.runtime.memory_services import RuntimeMemoryService
from apps.shell.agent.runtime.model_profiles import RuntimeAgentModelTester, RuntimeModelProfileResolver
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
from apps.shell.agent.runtime.run_readiness import RuntimeRunReadinessValidator
from apps.shell.agent.runtime.run_cancellation import RuntimeRunCancellationService
from apps.shell.agent.runtime.run_deletion import RuntimeRunDeletionService
from apps.shell.agent.runtime.run_rerun import RuntimeRunRerunService
from apps.shell.agent.runtime.run_services import (
    RuntimeRunServiceBundle,
    build_runtime_run_services as _build_runtime_run_services,
)
from apps.shell.agent.runtime.run_timeline import RuntimeRunTimelineService
from apps.shell.agent.runtime.runnable_services import (
    RuntimeRunnableServiceBundle,
    build_runtime_runnable_services as _build_runtime_runnable_services,
)
from apps.shell.agent.runtime.runnables import (
    RuntimeRunnableCatalog,
    RuntimeRunnableResolver,
    RuntimeRunnableRunCoordinator,
)
from apps.shell.agent.runtime.schema import (
    RuntimeSchemaMigrator,
    agent_model_credential_ref as _agent_model_credential_ref,
    initialize_runtime_schema as _initialize_runtime_schema,
)
from apps.shell.agent.runtime.seed_templates import RuntimeSeedTemplateService
from apps.shell.agent.runtime.paths import (
    RuntimeDirectoryLayout,
    agent_workspace_dir as _runtime_agent_workspace_dir,
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
from apps.shell.agent.runtime.skill_content import SkillContentInspector
from apps.shell.agent.runtime.skill_import import SkillImportPreparer, SkillImportSourceResolver
from apps.shell.agent.runtime.skill_import_service import RuntimeSkillImportService
from apps.shell.agent.runtime.skill_install import SkillInstallCommandValidator
from apps.shell.agent.runtime.skill_install_service import RuntimeSkillInstallService
from apps.shell.agent.runtime.skill_sources import SkillSourceDiscovery
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
from apps.shell.agent.runtime.tool_loop import (
    RuntimeToolLoopProjectionBuilder,
    append_tool_result_message as _runtime_append_tool_result_message,
    assistant_message_for_history as _runtime_assistant_message_for_history,
    fatal_tool_failure_detail as _runtime_fatal_tool_failure_detail,
    tool_loop_limit_artifact_completion as _runtime_tool_loop_limit_artifact_completion,
    tool_loop_limit_detail as _runtime_tool_loop_limit_detail,
)
from apps.shell.agent.runtime.timeline import RuntimeAgentTimelineBuilder

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
from apps.shell.agent.runtime.workflow_path import WorkflowDefinitionValidator, WorkflowPathPlanner
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
from apps.shell.agent.runtime.workflow_runs import RuntimeWorkflowRunStarter
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
    redact_sensitive_text,
)

logger = logging.getLogger(__name__)


_EXECUTION_BACKENDS = {"native_profile", "yachiyo_profile", "external_cli"}
_MEMORY_CONTEXT_LIMIT = 12
_MEMORY_CONTENT_MAX_CHARS = 4000
_FINAL_RUN_STATUSES = {"completed", "failed", "cancelled"}
_WORKFLOW_NODE_TYPES = {"start", "agent", "approval", "artifact", "condition", "parallel", "workflow", "loop"}
_NATIVE_LIBRARY_SOURCE_TYPES = {"native_global", "native_project"}
_SKILL_SOURCE_TYPES = {*_NATIVE_LIBRARY_SOURCE_TYPES, "npx_skills", "local_zip", "local_dir"}
_UNSET = object()
_MAIN_CHAT_AGENT_ID = "builtin:yachiyo-main"
_SYSTEM_AGENT_IDS = {_MAIN_CHAT_AGENT_ID}
_DEFAULT_AGENT_IDS = {
    _MAIN_CHAT_AGENT_ID,
    "agent_yachiyo_orchestrator",
    "agent_coding",
    "agent_design",
    "agent_review",
    "agent_research",
    "agent_office",
    "agent_custom",
}
_MARKET_AGENT_OPERATING_DOCTRINE = (
    "Market-grade Agent operating doctrine:\n"
    "- Act as a persistent personal agent, not a one-shot chatbot: preserve user intent, "
    "handoff context, and reusable outputs when the task has follow-up value.\n"
    "- Prefer the smallest reliable action loop: reason from available context, inspect before "
    "acting, use tools only when they materially improve the answer, and do not fabricate tool results.\n"
    "- Treat Skills as task manuals and tools as external actions; use mounted Skills when relevant, "
    "but keep direct answers lightweight when no Skill is needed.\n"
    "- For multi-step work, expose progress through concise summaries, artifacts, or workflow handoffs "
    "instead of hiding important intermediate decisions.\n"
    "- Respect safety boundaries: approval gates, workspace scopes, credential redaction, and user "
    "instructions outrank autonomy."
)


def _is_active_run_status(status: str) -> bool:
    return (status.strip() or "running") not in _FINAL_RUN_STATUSES


def _agent_output_contract_rules(contract: Any) -> str:
    return _runtime_agent_output_contract_rules(contract)


def _user_goal_from_agent_messages(messages: list[dict[str, Any]]) -> str:
    return _runtime_user_goal_from_agent_messages(messages)


def _agent_goal_disallows_tool(user_goal: str, tool_name: str) -> str:
    return _runtime_agent_goal_disallows_tool(user_goal, tool_name)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_execution_backend(value: Any, *, model_mode: str = "") -> str:
    """Normalize all Studio execution backends to the native runtime."""
    backend = str(value or "").strip()
    if backend and backend not in _EXECUTION_BACKENDS:
        raise AgentRuntimeError("execution_backend 不再支持 legacy 或未知执行后端；请使用 native_profile")
    return "native_profile"


def _normalize_skill_source_type(value: Any) -> str:
    source_type = str(value or "").strip()
    return source_type


def _is_native_library_source_type(value: Any) -> bool:
    return _normalize_skill_source_type(value) in _NATIVE_LIBRARY_SOURCE_TYPES


def redact_secrets(value: Any) -> str:
    return redact_sensitive_text(
        value,
        limit=0,
        collapse_whitespace=False,
        trim=False,
    )


def _iso_epoch(value: Any) -> float:
    text = str(value or "").strip()
    if not text:
        return time.time()
    try:
        return datetime.fromisoformat(text).timestamp()
    except ValueError:
        return time.time()


def _skill_content_hash(root: Path) -> str:
    return SkillContentInspector.content_hash(root)


def _parse_skill_frontmatter(markdown: str) -> dict[str, Any]:
    return SkillContentInspector.parse_frontmatter(markdown)


def _call_model_profile_chat_message(
    base_url: str,
    model: str,
    api_key: str,
    messages: list[dict[str, Any]],
    *,
    tools: list[dict[str, Any]] | None = None,
    stream: bool = False,
) -> Any:
    kwargs: dict[str, Any] = {}
    if tools is not None:
        kwargs["tools"] = tools
    if stream and _callable_accepts_keyword(openai_compatible_chat_message, "stream"):
        kwargs["stream"] = True
    return openai_compatible_chat_message(base_url, model, api_key, messages, **kwargs)


def _callable_accepts_keyword(func: Any, name: str) -> bool:
    try:
        parameters = inspect.signature(func).parameters
    except (TypeError, ValueError):
        return False
    return name in parameters or any(parameter.kind == inspect.Parameter.VAR_KEYWORD for parameter in parameters.values())


def _public_pending_approval(value: Any) -> dict[str, Any]:
    return _runtime_public_pending_approval(value)


class NativeRunEngine:
    """Persistent native agent execution engine shared by product entry points.

    AgentRuntimeService is kept as a compatibility name below because mature
    routes, tests, and UI-facing APIs still use the service label.
    """

    def __init__(
        self,
        db_path: Path | str | None = None,
        workspace_dir: Path | str | None = None,
        *,
        credential_store: CredentialStore | None = None,
        seed_templates: bool = True,
    ) -> None:
        engine_state = _build_runtime_engine_state(
            db_path=db_path,
            workspace_dir=workspace_dir,
            credential_store=credential_store,
        )
        self._install_runtime_engine_state(engine_state)
        recorders = _build_runtime_recorders(
            append_run_event=self.append_run_event,
            now=_now,
        )
        self._install_runtime_recorders(recorders)
        definition_services = _build_runtime_definition_services(
            conn=self._conn,
            ensure_row_factory=self._ensure_row_factory,
            get_run=lambda run_id: self.get_run(run_id),
            now=_now,
            error_type=AgentRuntimeError,
            row_to_skill_folder=self._row_to_skill_folder,
            slug=_slug,
            skill_folder_id_suffix_factory=lambda: uuid4().hex[:6],
            delete_skill=lambda skill_id: self.delete_skill(skill_id),
            row_to_skill=self._row_to_skill,
            json_dump=_json_dump,
            json_load=_json_load,
            normalize_skill_folder_id=self._normalize_skill_folder_id,
            installed_skill_source_map=self._installed_skill_source_map,
            record_studio_deletion=self._record_studio_deletion,
            skill_deletion_key=self._skill_deletion_key,
            is_native_library_source_type=_is_native_library_source_type,
            skills_dir=self.skills_dir,
            skill_installs_dir=self.skill_installs_dir,
            skill_id_factory=lambda name: f"skill_{_slug(name, 'skill')}_{uuid4().hex[:8]}",
            row_to_agent=self._row_to_agent,
            row_to_agent_private=self._row_to_agent_private,
            coerce_named_row=self._coerce_named_row,
            main_chat_virtual_agent=self._main_chat_virtual_agent,
            agent_id_factory=lambda name: f"agent_{_slug(name, 'agent')}_{uuid4().hex[:8]}",
            normalize_execution_backend=_normalize_execution_backend,
            ensure_global_name_available=self._ensure_global_name_available,
            validate_agent_profile_refs=self._validate_agent_profile_refs,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            assign_default_agent_workdir=self._assign_default_agent_workdir,
            trust_workspace_from_policy=self._trust_workspace_from_policy,
            agent_model_credential_ref=self._agent_model_credential_ref,
            store_credential=self._store_credential,
            delete_credential=self._delete_credential,
            clear_studio_deletion=self._clear_studio_deletion,
            system_agent_ids=_SYSTEM_AGENT_IDS,
            main_chat_agent_id=_MAIN_CHAT_AGENT_ID,
            native_skill_home=_native_skill_home,
            skill_installs_native_home=self.skill_installs_native_home,
            normalize_skill_source_type=_normalize_skill_source_type,
            native_library_source_types=_NATIVE_LIBRARY_SOURCE_TYPES,
            workspace_dir=self.workspace_dir,
            skill_import_id_factory=lambda: uuid4().hex,
            skill_source_types=_SKILL_SOURCE_TYPES,
            row_to_workflow=self._row_to_workflow,
            workflow_id_factory=lambda name: f"workflow_{_slug(name, 'workflow')}_{uuid4().hex[:8]}",
            validate_workflow=self.validate_workflow,
            validate_workflow_agent_nodes=self._validate_workflow_agent_nodes,
            validate_workflow_subworkflow_nodes=self._validate_workflow_subworkflow_nodes,
        )
        self._install_runtime_definition_services(definition_services)
        run_services = _build_runtime_run_services(
            conn=self._conn,
            db_lock=self._db_lock,
            ensure_row_factory=self._ensure_row_factory,
            row_to_run_group=self._row_to_run_group,
            row_to_run=self._row_to_run,
            now=_now,
            json_dump=_json_dump,
            json_load=_json_load,
            redact_secrets=redact_secrets,
            redact_json_value=_redact_json_value,
            contains_sensitive_text=contains_sensitive_text,
            error_type=AgentRuntimeError,
            unset_sentinel=_UNSET,
            agent_artifacts_dir=self.agent_artifacts_dir,
            workflow_artifacts_dir=self.workflow_artifacts_dir,
            get_run=self.get_run,
            safe_rel_path=_safe_rel_path,
            is_within=_is_within,
            read_text=_read_text,
            task_run_links=self.task_run_links,
            accepting_runs=lambda: self._accepting_runs,
            append_run_to_group=self._append_run_to_group,
            get_run_group=self.get_run_group,
            insert_run_group=self._insert_run_group,
            insert_run=self._insert_run,
            run_by_client_request_id=self._run_by_client_request_id,
            client_request_id_from_payload=self._client_request_id_from_payload,
            agent_workspace_dir=self._agent_workspace_dir,
        )
        self._install_runtime_run_services(run_services)
        self._install_runtime_memory_services(
            RuntimeMemoryService(
                self._conn,
                self._db_lock,
                now=_now,
                json_dump=_json_dump,
                redact_json_value=_redact_json_value,
                redact_secrets=redact_secrets,
                memory_scopes=_MEMORY_SCOPES,
                memory_kinds=_MEMORY_KINDS,
                context_limit=_MEMORY_CONTEXT_LIMIT,
                content_max_chars=_MEMORY_CONTENT_MAX_CHARS,
                error_type=AgentRuntimeError,
            )
        )
        core_services = _build_runtime_core_services(
            run_events=self.run_events,
            timeline_factory=self._timeline,
            profile_service_factory=lambda: get_model_profile_service(),
            supports_openai_compatible_api=supports_openai_compatible_api,
            default_agent_ids=_DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        )
        self._install_runtime_core_services(core_services)
        self.agent_model_tester = RuntimeAgentModelTester(
            profile_service_factory=lambda: get_model_profile_service(),
            default_agent_ids=_DEFAULT_AGENT_IDS,
            call_custom_api=self._openai_compatible_chat,
            now_seconds=time.time,
            redact_error=redact_api_error_text,
            error_type=AgentRuntimeError,
        )
        self._install_runtime_run_timeline(
            RuntimeRunTimelineService(
                runs=self.runs,
                run_groups=self.run_groups,
                runtime_events=self.runtime_events,
                run_artifacts=self.run_artifacts,
            )
        )
        self._install_runtime_main_chat_config(
            MainChatRuntimeConfigBuilder(
                main_chat_agent_id=_MAIN_CHAT_AGENT_ID,
                agent_workspaces_dir=self.agent_workspaces_dir,
                workspace_status=lambda: get_workspace_status(),
                compile_tool_policy=self._compile_tool_policy,
                compile_workspace_policy=self._compile_workspace_policy,
                trust_workspace_from_policy=self._trust_workspace_from_policy,
                memory_tool_names=list(_MEMORY_TOOL_NAMES),
                future_task_tool_names=list(_FUTURE_TASK_TOOL_NAMES),
            )
        )
        self._install_runtime_tool_brokers(
            RuntimeToolBrokerFactory(
                agent_artifacts_dir=self.agent_artifacts_dir,
                tool_broker_factory=ToolBroker,
                memory_store=self._memory_store,
                future_task_store=self._future_task_store,
                main_chat_agent_id=_MAIN_CHAT_AGENT_ID,
            )
        )
        self._install_runtime_main_chat_runs(
            MainChatRunLifecycle(
                main_chat_agent_id=_MAIN_CHAT_AGENT_ID,
                insert_run=self._insert_run,
                link_task_run=self.link_task_run,
                get_run=self.get_run,
                update_run=self._update_run,
                task_run_links=self.task_run_links,
                task_events=self.runtime_task_events,
                timeline_factory=self._timeline,
                redact_secrets=redact_secrets,
                final_statuses=_FINAL_RUN_STATUSES,
            )
        )
        self._install_runtime_main_chat_model(
            MainChatModelCaller(
                get_run=self.get_run,
                default_profile_id=lambda capability: str(
                    get_model_profile_service().get_defaults().get(capability) or ""
                ).strip(),
                model_profile_config_private=lambda profile_id, capability="chat": self._model_profile_config_private(
                    profile_id,
                    capability=capability,
                ),
                run_budget=self._run_budget,
                check_context_budget=self._check_context_budget,
                limit_model_output=self._limit_model_output,
                timeline_factory=self._timeline,
                update_run=self._update_run,
                append_run_event=self.append_run_event,
                task_model_events=self.runtime_task_model_events,
                call_model=lambda base_url, model, api_key, messages, **kwargs: _call_model_profile_chat_message(
                    base_url,
                    model,
                    api_key,
                    messages,
                    **kwargs,
                ),
                coalesce_model_message=_coalesce_model_message,
                message_visible_content_text=_message_visible_content_text,
                model_message_metadata=_model_message_metadata,
                terminal_run_or_none=self._terminal_run_or_none,
                redact_secrets=redact_secrets,
                error_type=AgentRuntimeError,
            )
        )
        tooling = _build_runtime_tooling(
            normalize_tool_name=_normalize_tool_name,
            input_preview=_tool_input_preview,
            run_budget=self._run_budget,
            validate_tool_payload=RuntimeToolOperations.validate_tool_payload,
            limit_tool_result=self._limit_tool_result,
            timeline_factory=self._timeline,
            tool_call_events=self.runtime_tool_call_events,
            trace_events=self.runtime_trace_events,
            append_run_event=self.append_run_event,
            allows_tool=PolicyGate.allows_tool,
            user_goal_from_messages=_user_goal_from_agent_messages,
            goal_disallows_tool=_agent_goal_disallows_tool,
            pending_approval_builder=self.tool_pending_approvals,
            call_agent_tool=self._call_agent_tool,
        )
        self._install_runtime_tooling(tooling)
        self.tool_operations = RuntimeToolOperations(
            tool_request_runner=self.tool_request_runner,
            tool_call_executor=self.tool_call_executor,
        )
        self._install_runtime_custom_api_agent_loop(
            RuntimeCustomApiAgentLoop(
                agent_model_config_private=self._agent_model_config_private,
                compile_agent_runtime=self._compile_agent_runtime,
                run_budget=self._run_budget,
                check_context_budget=self._check_context_budget,
                tool_schemas=RuntimeToolOperations.model_tool_schemas,
                normalize_tool_iteration=_normalize_tool_iteration,
                max_tool_iterations=_MAX_AGENT_TOOL_ITERATIONS,
                operating_doctrine=_MARKET_AGENT_OPERATING_DOCTRINE,
                memory_tool_names=_MEMORY_TOOL_NAMES,
                future_task_tool_names=_FUTURE_TASK_TOOL_NAMES,
                call_model=lambda base_url, model, api_key, messages, **kwargs: _call_model_profile_chat_message(
                    base_url,
                    model,
                    api_key,
                    messages,
                    **kwargs,
                ),
                coalesce_model_message=_coalesce_model_message,
                message_visible_content_text=_message_visible_content_text,
                model_message_metadata=_model_message_metadata,
                tool_requests_from_message=self._tool_requests_from_message,
                timeline_factory=self._timeline,
                limit_model_output=self._limit_model_output,
                model_output_text_factory=_ModelOutputText,
                tool_loop_projection=self.tool_loop_projection,
                run_tool_requests=self._run_tool_requests,
                error_type=AgentRuntimeError,
            )
        )
        agent_services = _build_runtime_agent_services(
            get_skill=self.get_skill,
            error_type=AgentRuntimeError,
            compile_agent_runtime=self._compile_agent_runtime,
            load_agent_skills=self._load_agent_skills,
            long_term_memory_context=self._long_term_memory_context,
            operating_doctrine=_MARKET_AGENT_OPERATING_DOCTRINE,
            agent_artifacts_dir=self.agent_artifacts_dir,
            normalize_execution_backend=_normalize_execution_backend,
            agent_context=self._agent_context,
            memory_store=self._memory_store,
            future_task_store=self._future_task_store,
            runtime_agent_timeline=self.runtime_agent_timeline,
            runtime_agent_run_events=self.runtime_agent_run_events,
            runtime_trace_events=self.runtime_trace_events,
            append_run_event=self.append_run_event,
            timeline_factory=self._timeline,
            memory_context_limit=_MEMORY_CONTEXT_LIMIT,
            runtime_task_model_events=self.runtime_task_model_events,
            update_run=self._update_run,
            model_output_metadata=_model_output_metadata,
            redact_secrets=redact_secrets,
            tool_brokers=self.tool_brokers,
        )
        self._install_runtime_agent_services(agent_services)
        approval_services = _build_runtime_approval_services(
            timeline_factory=self._timeline,
            append_run_event=self.append_run_event,
            update_run=self._update_run,
            snapshots=self.approval_snapshots,
            call_agent_tool=self._call_agent_tool,
            fatal_tool_failure_detail=self._fatal_tool_failure_detail,
            append_tool_result_message=self._append_tool_result_message,
            run_tool_requests=self._run_tool_requests,
            claim_pending_approval=self.run_approvals.claim_pending_approval,
            continue_custom_api_agent=self._run_custom_api_agent,
        )
        self._install_runtime_approval_services(approval_services)
        self._install_runtime_approval_transitions(
            RuntimeApprovalTransitionService(
                get_run=lambda run_id: self.get_run(run_id),
                pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
                approvals=self.approvals,
                project_child_run_transition=lambda result: self._project_child_run_transition(result),
                project_cancelled_workflow_group_if_root=lambda run, result: self._project_cancelled_workflow_group_if_root(
                    run,
                    result,
                ),
                cancel_run=lambda run_id: self.cancel_run(run_id),
            )
        )
        self._install_runtime_tool_approval_resume(
            RuntimeToolApprovalResumeService(
                pending_approval_private=lambda run_id: self.runs.pending_approval_private(run_id),
                get_agent_private=lambda agent_id: self._get_agent_private(agent_id),
                compile_agent_runtime=lambda agent: self._compile_agent_runtime(agent),
                load_agent_skills=lambda skill_ids: self._load_agent_skills(skill_ids),
                tool_brokers=self.tool_brokers,
                run_budget=lambda run_id, timeline: self._run_budget(run_id, timeline),
                resume_approved_tool_run=lambda **kwargs: self._resume_approved_tool_run(**kwargs),
                main_chat_agent_config=lambda **kwargs: self._main_chat_agent_config(**kwargs),
                main_chat_pending_approval=lambda pending_approval, **kwargs: self._main_chat_pending_approval(
                    pending_approval,
                    **kwargs,
                ),
                default_chat_profile_id=lambda: str(
                    get_model_profile_service().get_defaults().get("chat") or ""
                ).strip(),
                project_agent_running=lambda running: self._project_agent_approval_resume_running(running),
                project_agent_completed=lambda context, result_text: self._project_agent_approval_resume_completed(
                    context,
                    result_text,
                ),
                project_main_chat_completed=lambda context, result_text: self._project_main_chat_approval_resume_completed(
                    context,
                    result_text,
                ),
                project_child_run_transition=lambda result: self._project_child_run_transition(result),
                redact_agent_error=redact_secrets,
                main_chat_agent_id=_MAIN_CHAT_AGENT_ID,
                error_type=AgentRuntimeError,
            )
        )
        self.approval_execution = RuntimeApprovalExecutionService(
            execution_lock=self._approval_execution_lock,
            execution_in_progress=self._approval_execution_in_progress,
            get_run=lambda run_id: self.get_run(run_id),
            approve_once=lambda run: self._approve_run_approval_once(run),
        )
        self._install_runtime_main_chat_model_loop(
            MainChatModelLoopRunner(
                get_run=self.get_run,
                default_profile_id=lambda: str(
                    get_model_profile_service().get_defaults().get("chat") or ""
                ).strip(),
                model_profile_config_private=lambda profile_id: self._model_profile_config_private(
                    profile_id,
                    capability="chat",
                ),
                main_chat_agent_config=self._main_chat_agent_config,
                compile_agent_runtime=self._compile_agent_runtime,
                run_budget=self._run_budget,
                check_context_budget=self._check_context_budget,
                runtime_agent_timeline=self.runtime_agent_timeline,
                timeline_factory=self._timeline,
                update_run=self._update_run,
                append_run_event=self.append_run_event,
                task_model_events=self.runtime_task_model_events,
                tool_brokers=self.tool_brokers,
                continue_custom_api_agent=self._run_custom_api_agent,
                main_chat_pending_approval=self._main_chat_pending_approval,
                approval_pause=self.approval_pause,
                terminal_run_or_none=self._terminal_run_or_none,
                redact_secrets=redact_secrets,
                model_output_metadata=_model_output_metadata,
                error_type=AgentRuntimeError,
            )
        )
        workflow_planning_services = _build_runtime_workflow_planning_services(
            get_run_group=self.get_run_group,
            get_run=self.get_run,
            node_kind=self._node_kind,
            node_types=_WORKFLOW_NODE_TYPES,
            get_agent_private=self._get_agent_private,
            get_workflow=self.get_workflow,
            load_agent_skills=self._load_agent_skills,
            agent_model_config_private=self._agent_model_config_private,
            default_agent_ids=_DEFAULT_AGENT_IDS,
            timeline_factory=self._timeline,
            workflow_path_snapshot=self._workflow_path_snapshot,
            workflow_runtime_snapshot=self._workflow_runtime_snapshot,
            insert_run_group=self._insert_run_group,
            insert_run=self._insert_run,
            run_by_client_request_id=self._run_by_client_request_id,
            client_request_id_from_payload=self._client_request_id_from_payload,
            workflow_path=self._workflow_path,
        )
        self._install_runtime_workflow_planning_services(workflow_planning_services)
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
            timeline_factory=lambda event, detail="", **extra: self._timeline(event, detail, **extra),
            append_run_event=lambda run_id, event_type, payload: self.append_run_event(run_id, event_type, payload),
            update_run=lambda run_id, **kwargs: self._update_run(run_id, **kwargs),
            update_run_group=lambda run_group_id, **kwargs: self._update_run_group(run_group_id, **kwargs),
            approve_workflow_node=lambda run_id, **kwargs: self.approvals.approve_workflow_node(run_id, **kwargs),
        )
        self._install_runtime_workflow_execution_services(workflow_execution_services)
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
            timeline_factory=lambda event, detail="", **extra: self._timeline(event, detail, **extra),
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
                timeline_factory=lambda event, detail="", **extra: self._timeline(
                    event,
                    detail,
                    **extra,
                ),
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
                timeline_factory=lambda event, detail="", **extra: self._timeline(
                    event,
                    detail,
                    **extra,
                ),
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

    def _install_runtime_engine_state(self, state: RuntimeEngineStateBundle) -> None:
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

    def _install_runtime_recorders(self, recorders: RuntimeRecorderBundle) -> None:
        self.tool_request_parser = recorders.tool_request_parser
        self.runtime_agent_run_events = recorders.runtime_agent_run_events
        self.tool_event_payloads = recorders.tool_event_payloads
        self.runtime_tool_call_events = recorders.runtime_tool_call_events
        self.runtime_task_model_events = recorders.runtime_task_model_events
        self.runtime_task_events = recorders.runtime_task_events
        self.runtime_trace_events = recorders.runtime_trace_events
        self.tool_pending_approvals = recorders.tool_pending_approvals

    def _install_runtime_definition_services(self, services: RuntimeDefinitionServiceBundle) -> None:
        self.task_run_links = services.task_run_links
        self.trusted_workspaces = services.trusted_workspaces
        self.studio_deletions = services.studio_deletions
        self.skill_folders = services.skill_folders
        self.skill_records = services.skill_records
        self.agent_definitions = services.agent_definitions
        self.skill_install_validator = services.skill_install_validator
        self.skill_sources = services.skill_sources
        self.skill_content = services.skill_content
        self.skill_import_sources = services.skill_import_sources
        self.skill_import_preparer = services.skill_import_preparer
        self.skill_sync = services.skill_sync
        self.workflows = services.workflows

    def _install_runtime_run_services(self, services: RuntimeRunServiceBundle) -> None:
        self.approval_snapshots = services.approval_snapshots
        self.run_groups = services.run_groups
        self.run_approvals = services.run_approvals
        self.run_artifacts = services.run_artifacts
        self.run_projections = services.run_projections
        self.runs = services.runs
        self.run_events = services.run_events
        self.agent_run_starter = services.agent_run_starter

    def _install_runtime_memory_services(self, memory_services: RuntimeMemoryService) -> None:
        self.memory_services = memory_services

    def _install_runtime_core_services(self, core_services: RuntimeCoreServiceBundle) -> None:
        self.runtime_events = core_services.runtime_events
        self.runtime_agent_timeline = core_services.runtime_agent_timeline
        self.runtime_policy = core_services.runtime_policy
        self.model_profile_resolver = core_services.model_profile_resolver

    def _install_runtime_run_timeline(
        self,
        run_timeline: RuntimeRunTimelineService,
    ) -> None:
        self.run_timeline = run_timeline

    def _install_runtime_main_chat_config(self, main_chat_config: MainChatRuntimeConfigBuilder) -> None:
        self.main_chat_config = main_chat_config

    def _install_runtime_tool_brokers(self, tool_brokers: RuntimeToolBrokerFactory) -> None:
        self.tool_brokers = tool_brokers

    def _install_runtime_main_chat_runs(self, main_chat_runs: MainChatRunLifecycle) -> None:
        self.main_chat_runs = main_chat_runs

    def _install_runtime_main_chat_model(self, main_chat_model: MainChatModelCaller) -> None:
        self.main_chat_model = main_chat_model

    def _install_runtime_main_chat_model_loop(self, main_chat_model_loop: MainChatModelLoopRunner) -> None:
        self.main_chat_model_loop = main_chat_model_loop

    def _install_runtime_tooling(self, tooling: RuntimeToolingBundle) -> None:
        self.tool_loop_projection = tooling.tool_loop_projection
        self.tool_call_executor = tooling.tool_call_executor
        self.tool_request_runner = tooling.tool_request_runner

    def _install_runtime_custom_api_agent_loop(self, custom_api_agent_loop: RuntimeCustomApiAgentLoop) -> None:
        self.custom_api_agent_loop = custom_api_agent_loop

    def _install_runtime_agent_services(self, agent_services: RuntimeAgentServiceBundle) -> None:
        self.agent_skill_loader = agent_services.agent_skill_loader
        self.agent_context_builder = agent_services.agent_context_builder
        self.agent_run_preparer = agent_services.agent_run_preparer
        self.agent_run_outcomes = agent_services.agent_run_outcomes

    def _install_runtime_approval_services(self, approval_services: RuntimeApprovalServiceBundle) -> None:
        self.approval_pause = approval_services.approval_pause
        self.approvals = approval_services.approvals
        self.approval_resume = approval_services.approval_resume

    def _install_runtime_approval_transitions(self, approval_transitions: RuntimeApprovalTransitionService) -> None:
        self.approval_transitions = approval_transitions

    def _install_runtime_tool_approval_resume(self, tool_approval_resume: RuntimeToolApprovalResumeService) -> None:
        self.tool_approval_resume = tool_approval_resume

    def _install_runtime_workflow_execution_services(
        self,
        workflow_services: RuntimeWorkflowExecutionServiceBundle,
    ) -> None:
        self.workflow_continuation = workflow_services.workflow_continuation
        self.workflow_approval_resume = workflow_services.workflow_approval_resume
        self.workflow_cancellation = workflow_services.workflow_cancellation
        self.workflow_child_outcomes = workflow_services.workflow_child_outcomes

    def _install_runtime_workflow_planning_services(
        self,
        workflow_services: RuntimeWorkflowPlanningServiceBundle,
    ) -> None:
        self.workflow_parent_locator = workflow_services.workflow_parent_locator
        self.workflow_path_planner = workflow_services.workflow_path_planner
        self.workflow_definition_validator = workflow_services.workflow_definition_validator
        self.run_readiness_validator = workflow_services.run_readiness_validator
        self.workflow_run_start_projector = workflow_services.workflow_run_start_projector
        self.workflow_run_starter = workflow_services.workflow_run_starter
        self.workflow_resume_planner = workflow_services.workflow_resume_planner

    def _install_runtime_runnable_services(self, runnable_services: RuntimeRunnableServiceBundle) -> None:
        self.future_task_scheduler = runnable_services.future_task_scheduler
        self.chat_runnable_parser = runnable_services.chat_runnable_parser
        self.runnable_catalog = runnable_services.runnable_catalog
        self.runnable_run_coordinator = runnable_services.runnable_run_coordinator

    def _install_runtime_workflow_transition_services(
        self,
        workflow_services: RuntimeWorkflowTransitionServiceBundle,
    ) -> None:
        self.workflow_parent_resume = workflow_services.workflow_parent_resume
        self.approval_resume_projection = workflow_services.approval_resume_projection
        self.run_transition_projection = workflow_services.run_transition_projection

    def _install_runtime_run_cancellation(
        self,
        run_cancellation: RuntimeRunCancellationService,
    ) -> None:
        self.run_cancellation = run_cancellation

    def _install_runtime_run_rerun(
        self,
        run_rerun: RuntimeRunRerunService,
    ) -> None:
        self.run_rerun = run_rerun

    def _install_runtime_run_deletion(
        self,
        run_deletion: RuntimeRunDeletionService,
    ) -> None:
        self.run_deletion = run_deletion

    def _install_runtime_shutdown(
        self,
        shutdown: RuntimeShutdownService,
    ) -> None:
        self.runtime_shutdown = shutdown

    def close(self) -> None:
        self.shutdown()

    def shutdown(self, *, close_db: bool = True) -> None:
        self.runtime_shutdown.shutdown(close_db=close_db)

    def _ensure_row_factory(self) -> None:
        if self._conn.row_factory is not _named_row_factory:
            self._conn.row_factory = _named_row_factory

    def _coerce_named_row(self, row: Any, description: Any = None) -> Any:
        return _coerce_named_row_value(row, description)

    def _init_db(self) -> None:
        _initialize_runtime_schema(
            self._conn,
            now=_now,
            ensure_runtime_columns=self._ensure_runtime_columns,
            vacuum_after_secret_scrub=self._vacuum_after_secret_scrub,
        )

    def _schema_migrator(self) -> RuntimeSchemaMigrator:
        return RuntimeSchemaMigrator(
            self._conn,
            now=_now,
            redact_secrets=redact_secrets,
            credential_store=self._credential_store,
        )

    def _ensure_runtime_columns(self) -> bool:
        return self._schema_migrator().ensure_runtime_columns()

    def _vacuum_after_secret_scrub(self) -> None:
        try:
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            self._conn.execute("VACUUM")
            self._conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
        except sqlite3.Error:
            logger.debug("NativeRunEngine secret scrub vacuum failed", exc_info=True)

    def _migrate_native_execution_and_skill_sources(self) -> None:
        self._schema_migrator().migrate_native_execution_and_skill_sources()

    def _migrate_run_group_secret_projections(self) -> bool:
        return self._schema_migrator().migrate_run_group_secret_projections()

    def _agent_model_credential_ref(self, agent_id: str) -> str:
        return _agent_model_credential_ref(agent_id)

    def _store_credential(self, ref: str, secret: str) -> None:
        self.runtime_credentials.store(ref, secret)

    def _read_credential(self, ref: str) -> str:
        return self.runtime_credentials.read(ref)

    def _delete_credential(self, ref: str) -> None:
        self.runtime_credentials.delete(ref)

    def _migrate_agent_model_credentials(self) -> bool:
        return self._schema_migrator().migrate_agent_model_credentials()

    def _record_studio_deletion(self, item_type: str, item_key: str) -> None:
        self.studio_deletions.record(item_type, item_key)

    def _clear_studio_deletion(self, item_type: str, item_key: str) -> None:
        self.studio_deletions.clear(item_type, item_key)

    def _has_studio_deletion(self, item_type: str, item_key: str) -> bool:
        return self.studio_deletions.has(item_type, item_key)

    @staticmethod
    def _skill_deletion_key(source_type: str, origin_path: str) -> str:
        clean_origin = str(origin_path or "").strip()
        if not clean_origin:
            return ""
        library = "native" if _is_native_library_source_type(source_type) else "installed"
        try:
            clean_origin = str(Path(clean_origin).expanduser().resolve())
        except OSError:
            pass
        return f"{library}:{clean_origin}"

    def _seed_templates(self) -> None:
        self.seed_template_service.seed()

    def _seed_workflow_templates(self) -> None:
        self.seed_template_service.seed_workflows()

    @staticmethod
    def _default_tool_policy(category: str = "custom") -> dict[str, Any]:
        return RuntimePolicyCompiler.default_tool_policy(category)

    @staticmethod
    def _default_workspace_policy() -> dict[str, Any]:
        return RuntimePolicyCompiler.default_workspace_policy()

    def _default_agent_workdir(self, agent_id: str) -> Path:
        return self.workspace_policy_service.default_agent_workdir(agent_id)

    def _assign_default_agent_workdir(
        self,
        agent_id: str,
        workspace_policy: dict[str, Any],
        tool_policy: dict[str, Any],
    ) -> dict[str, Any]:
        return self.workspace_policy_service.assign_default_agent_workdir(agent_id, workspace_policy, tool_policy)

    def trust_workspace(self, path: str | Path, *, source: str = "runtime", commit: bool = True) -> dict[str, Any]:
        return self.workspace_policy_service.trust_workspace(path, source=source, commit=commit)

    def _trust_workspace_from_policy(
        self,
        workspace_policy: dict[str, Any],
        *,
        source: str,
        commit: bool = True,
    ) -> None:
        self.workspace_policy_service.trust_workspace_from_policy(
            workspace_policy,
            source=source,
            commit=commit,
        )

    def list_trusted_workspaces(self) -> dict[str, Any]:
        return self.workspace_policy_service.list_trusted_workspaces()

    def _migrate_agent_workspace_policies(self) -> None:
        self.workspace_policy_service.migrate_agent_workspace_policies()

    @staticmethod
    def _tool_schemas(allowed_tools: list[str]) -> list[dict[str, Any]]:
        return RuntimeToolOperations.model_tool_schemas(allowed_tools)

    def _compile_tool_policy(self, category: str, policy: Any = None) -> dict[str, Any]:
        return self.runtime_policy.compile_tool_policy(category, policy)

    def _compile_workspace_policy(self, policy: Any = None) -> dict[str, Any]:
        return self.runtime_policy.compile_workspace_policy(policy)

    def _memory_store(self, *, source_run_id: str = "") -> AgentMemoryStore:
        return self.memory_services.memory_store(source_run_id=source_run_id)

    def _future_task_store(
        self,
        *,
        source_run_id: str = "",
        default_runnable_id: str = "",
    ) -> AgentFutureTaskStore:
        return self.memory_services.future_task_store(
            source_run_id=source_run_id,
            default_runnable_id=default_runnable_id,
        )

    def list_memory_items(self, *, include_deleted: bool = False, limit: int = 100) -> dict[str, Any]:
        return self.memory_services.list_items(include_deleted=include_deleted, limit=limit)

    def create_memory_item(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.memory_services.create_item(payload)

    def update_memory_item(self, memory_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.memory_services.update_item(memory_id, payload)

    def delete_memory_item(self, memory_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.memory_services.delete_item(memory_id, reason=reason)

    def _long_term_memory_context(self) -> str:
        return self.memory_services.long_term_memory_context()

    def schedule_future_task(self, payload: dict[str, Any], *, source_run_id: str = "") -> dict[str, Any]:
        return self.future_task_service.schedule(payload, source_run_id=source_run_id)

    def list_future_tasks(self, *, include_finished: bool = True, limit: int = 100) -> dict[str, Any]:
        return self.future_task_service.list(include_finished=include_finished, limit=limit)

    def cancel_future_task(self, future_task_id: str, *, reason: str = "") -> dict[str, Any]:
        return self.future_task_service.cancel(future_task_id, reason=reason)

    def trigger_due_future_tasks(self, *, now_epoch: float | None = None, limit: int = 20) -> dict[str, Any]:
        return self.future_task_service.trigger_due(now_epoch=now_epoch, limit=limit)

    def _row_to_agent(self, row: Any) -> dict[str, Any]:
        return _project_agent_row(
            row,
            json_load=_json_load,
            default_tool_policy=self._default_tool_policy,
            default_workspace_policy=self._default_workspace_policy,
            compile_tool_policy=self._compile_tool_policy,
            compile_workspace_policy=self._compile_workspace_policy,
            normalize_execution_backend=_normalize_execution_backend,
        )

    def _row_to_agent_private(self, row: Any) -> dict[str, Any]:
        return _project_agent_private_row(
            row,
            row_to_agent=self._row_to_agent,
            read_credential=self._read_credential,
        )

    def _main_chat_virtual_agent(self) -> dict[str, Any]:
        try:
            default_profile_id = str(get_model_profile_service().get_defaults().get("chat") or "").strip()
        except Exception:
            default_profile_id = ""
        return self.main_chat_config.virtual_agent(default_profile_id=default_profile_id)

    def _row_to_skill(self, row: sqlite3.Row) -> dict[str, Any]:
        return _project_skill_row(row, skills_dir=self.skills_dir, json_load=_json_load)

    def _row_to_skill_folder(self, row: sqlite3.Row) -> dict[str, Any]:
        return _project_skill_folder_row(row)

    def _row_to_workflow(self, row: sqlite3.Row) -> dict[str, Any]:
        return _project_workflow_row(row, json_load=_json_load)

    def _row_to_run(self, row: sqlite3.Row) -> dict[str, Any]:
        return _project_run_row(
            row,
            json_load=_json_load,
            public_pending_approval=_public_pending_approval,
            task_run_link_for_run=self.task_run_links.for_run,
            run_group_source=self._run_group_source,
            runnable_name=self._runnable_name,
        )

    def _row_to_run_group(self, row: sqlite3.Row) -> dict[str, Any]:
        return _project_run_group_row(row, json_load=_json_load)

    def _runnable_name(self, kind: str, runnable_id: str) -> str:
        self._ensure_row_factory()
        if kind == "main_chat_run" and runnable_id == _MAIN_CHAT_AGENT_ID:
            return "Yachiyo"
        if kind == "agent_run":
            row = self._conn.execute("SELECT name FROM agents WHERE agent_id=?", (runnable_id,)).fetchone()
            return str(row["name"]) if row is not None else ""
        if kind == "workflow_run":
            row = self._conn.execute("SELECT name FROM workflows WHERE workflow_id=?", (runnable_id,)).fetchone()
            return str(row["name"]) if row is not None else ""
        return ""

    def _ensure_global_name_available(self, name: str, *, ignore_agent_id: str = "", ignore_workflow_id: str = "") -> None:
        self._ensure_row_factory()
        clean = (name or "").strip()
        if not clean:
            raise AgentRuntimeError("名称不能为空")
        if clean.lower() == "yachiyo":
            raise AgentRuntimeError("Yachiyo 是系统 Agent 名称，不能作为普通 Agent/Workflow 名称")
        agent = self._conn.execute(
            "SELECT agent_id FROM agents WHERE LOWER(name)=LOWER(?)",
            (clean,),
        ).fetchone()
        if agent and agent["agent_id"] != ignore_agent_id:
            raise AgentRuntimeError("Agent/Workflow 名称必须全局唯一")
        workflow = self._conn.execute(
            "SELECT workflow_id FROM workflows WHERE LOWER(name)=LOWER(?)",
            (clean,),
        ).fetchone()
        if workflow and workflow["workflow_id"] != ignore_workflow_id:
            raise AgentRuntimeError("Agent/Workflow 名称必须全局唯一")

    @staticmethod
    def _validate_available_profile(profile_id: str, capability: str) -> dict[str, Any]:
        return RuntimeModelProfileResolver(
            profile_service_factory=lambda: get_model_profile_service(),
            supports_openai_compatible_api=supports_openai_compatible_api,
            default_agent_ids=_DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        ).validate_available_profile(profile_id, capability)

    def _validate_agent_profile_refs(self, payload: dict[str, Any]) -> None:
        self.model_profile_resolver.validate_agent_profile_refs(payload)

    def list_agents(self) -> dict[str, Any]:
        return self.agent_definitions.list()

    def get_agent(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.get(agent_id)

    def _get_agent_private(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.get_private(agent_id)

    def create_agent(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        return self.agent_definitions.create(payload, seed=seed)

    def update_agent(self, agent_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.agent_definitions.update(agent_id, payload)

    def delete_agent(self, agent_id: str) -> dict[str, Any]:
        return self.agent_definitions.delete(agent_id)

    def attach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        skill = self.get_skill(skill_id)
        if not skill.get("enabled", True):
            raise AgentRuntimeError("Skill 已停用，不能挂载")
        skill_ids = list(dict.fromkeys([*agent.get("skill_ids", []), skill_id]))
        return self.update_agent(agent_id, {"skill_ids": skill_ids})

    def detach_skill(self, agent_id: str, skill_id: str) -> dict[str, Any]:
        agent = self.get_agent(agent_id)
        skill_ids = [item for item in agent.get("skill_ids", []) if item != skill_id]
        return self.update_agent(agent_id, {"skill_ids": skill_ids})

    def list_skill_folders(self) -> dict[str, Any]:
        return self.skill_folders.list()

    def create_skill_folder(self, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_folders.create(payload)

    def get_skill_folder(self, folder_id: str) -> dict[str, Any]:
        return self.skill_folders.get(folder_id)

    def update_skill_folder(self, folder_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_folders.update(folder_id, payload)

    def delete_skill_folder(self, folder_id: str, *, delete_skills: bool = False) -> dict[str, Any]:
        return self.skill_folders.delete(folder_id, delete_skills=delete_skills)

    def list_skills(self) -> dict[str, Any]:
        return self.skill_records.list()

    def list_native_skill_sources(self) -> dict[str, Any]:
        roots = self._native_skill_root_specs()
        return {
            "ok": True,
            "roots": [
                {
                    "path": str(root["path"]),
                    "source_type": root["source_type"],
                    "library": "native",
                    "exists": root["path"].exists(),
                    "skill_count": self._count_skill_files(root["path"]),
                }
                for root in roots
            ],
        }

    def get_skill(self, skill_id: str) -> dict[str, Any]:
        return self.skill_records.get(skill_id)

    def import_skill(self, source_path: str, folder_id: str | None = None) -> dict[str, Any]:
        return self.skill_import_service.import_skill(source_path, folder_id)

    def sync_native_skills(self, roots: list[Any] | None = None) -> dict[str, Any]:
        return self._sync_skill_roots(self._native_skill_root_specs(roots), library="native")

    def sync_installed_skills(
        self,
        *,
        record_source_type: str = "npx_skills",
        folder_id: str | None = None,
        source_ref_override: str = "",
        restore_deleted: bool = False,
    ) -> dict[str, Any]:
        source_type = record_source_type if record_source_type == "npx_skills" else "npx_skills"
        roots = self._installed_skill_root_specs(source_type=source_type, source_ref_override=source_ref_override)
        return self._sync_skill_roots(
            roots,
            library="installed",
            folder_id=folder_id,
            restore_deleted=restore_deleted,
        )

    def _sync_skill_roots(
        self,
        root_specs: list[dict[str, Any]],
        *,
        library: str,
        folder_id: str | None = None,
        restore_deleted: bool = False,
    ) -> dict[str, Any]:
        return self.skill_sync_service.sync_roots(
            root_specs,
            library=library,
            folder_id=folder_id,
            restore_deleted=restore_deleted,
        )

    def install_skill_command(self, command: str, folder_id: str | None = None) -> dict[str, Any]:
        return self.skill_install_service.install(command, folder_id)

    def _import_skill_root(
        self,
        source_root: Path,
        *,
        source_path: str,
        source_type: str,
        origin_path: str,
        source_ref: str,
        sync_status: str,
        synced_at: str = "",
        copy_to_managed: bool = True,
        folder_id: str | None = None,
    ) -> dict[str, Any]:
        return self.skill_import_service.import_root(
            source_root=source_root,
            source_path=source_path,
            source_type=source_type,
            origin_path=origin_path,
            source_ref=source_ref,
            sync_status=sync_status,
            copy_to_managed=copy_to_managed,
            synced_at=synced_at,
            folder_id=folder_id,
        )

    def _find_existing_skill(self, origin_path: str, content_hash: str, source_type: str) -> sqlite3.Row | None:
        return self.skill_import_service.find_existing(origin_path, content_hash, source_type)

    def _repair_native_skill_references(self) -> None:
        self.skill_records.repair_native_references()

    def _repair_installed_skill_provenance(self) -> None:
        self.skill_records.repair_installed_provenance()

    def _native_skill_root_specs(self, roots: list[Any] | None = None) -> list[dict[str, Any]]:
        return self.skill_sources.native_root_specs(roots)

    def _installed_skill_root_specs(self, *, source_type: str, source_ref_override: str = "") -> list[dict[str, Any]]:
        return self.skill_sources.installed_root_specs(
            source_type=source_type,
            source_ref_override=source_ref_override,
        )

    def _installed_skill_source_map(self) -> dict[str, str]:
        return self.skill_sources.installed_source_map()

    @staticmethod
    def _skill_lock_source_ref(entry: dict[str, Any]) -> str:
        return SkillSourceDiscovery.skill_lock_source_ref(entry)

    @staticmethod
    def _infer_native_source_type(path: Path) -> str:
        return SkillSourceDiscovery.infer_native_source_type(path)

    @staticmethod
    def _count_skill_files(root: Path) -> int:
        return SkillSourceDiscovery.count_skill_files(root)

    def _validated_skill_install_argv(self, command: str) -> tuple[list[str], str]:
        return self.skill_install_validator.validate(command)

    def _skill_install_source_ref(self, argv: list[str], installer: str) -> str:
        return self.skill_install_validator.source_ref(argv, installer)

    @staticmethod
    def _metadata_skill_source_ref(metadata: dict[str, Any], fallback: str) -> str:
        return SkillContentInspector.metadata_source_ref(metadata, fallback)

    def _validated_npx_skills_argv(self, argv: list[str]) -> list[str]:
        return self.skill_install_validator.validate_npx_skills_argv(argv)

    @staticmethod
    def _has_agent_target(args: list[str]) -> bool:
        return SkillInstallCommandValidator.has_agent_target(args)

    def _validate_skill_install_agent_target(self, args: list[str]) -> None:
        self.skill_install_validator.validate_agent_target(args)

    def _normalize_skill_folder_id(self, folder_id: str | None) -> str:
        return self.skill_folders.normalize_id(folder_id)

    def _validate_skill_folder_name(self, name: str, *, current_folder_id: str = "") -> None:
        self.skill_folders.validate_name(name, current_folder_id=current_folder_id)

    def update_skill(self, skill_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.skill_records.update(skill_id, payload)

    @staticmethod
    def _skill_name(markdown: str, fallback: str) -> str:
        return SkillContentInspector.name(markdown, fallback)

    @staticmethod
    def _skill_description(markdown: str) -> str:
        return SkillContentInspector.description(markdown)

    @staticmethod
    def _skill_summary(markdown: str) -> str:
        return SkillContentInspector.summary(markdown)

    @staticmethod
    def _skill_asset_paths(root: Path) -> list[str]:
        return SkillContentInspector.asset_paths(root)

    def delete_skill(self, skill_id: str) -> dict[str, Any]:
        return self.skill_records.delete(skill_id)

    def list_workflows(self) -> dict[str, Any]:
        return self.workflows.list()

    def get_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.workflows.get(workflow_id)

    def create_workflow(self, payload: dict[str, Any], *, seed: bool = False) -> dict[str, Any]:
        return self.workflows.create(payload, seed=seed)

    def update_workflow(self, workflow_id: str, payload: dict[str, Any]) -> dict[str, Any]:
        return self.workflows.update(workflow_id, payload)

    def delete_workflow(self, workflow_id: str) -> dict[str, Any]:
        return self.workflows.delete(workflow_id)

    @staticmethod
    def _node_kind(node: dict[str, Any]) -> str:
        data = node.get("data") or {}
        data_kind = str(data.get("kind") or data.get("node_type") or "").strip()
        node_type = str(node.get("type") or "").strip()
        if data_kind and node_type in {"", "input", "default", "output"}:
            return data_kind
        return node_type or data_kind

    def validate_workflow(self, nodes: list[dict[str, Any]], edges: list[dict[str, Any]]) -> dict[str, Any]:
        return self.workflow_definition_validator.validate(nodes, edges)

    def _workflow_agent_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        return self.run_readiness_validator.workflow_agent_for_node(node)

    @staticmethod
    def _workflow_id_for_node(node: dict[str, Any]) -> str:
        return RuntimeRunReadinessValidator.workflow_id_for_node(node)

    def _workflow_for_node(self, node: dict[str, Any]) -> dict[str, Any]:
        return self.run_readiness_validator.workflow_for_node(node)

    def _validate_workflow_agent_nodes(self, nodes: list[dict[str, Any]]) -> None:
        self.run_readiness_validator.validate_workflow_agent_nodes(nodes)

    def _validate_workflow_subworkflow_nodes(
        self,
        nodes: list[dict[str, Any]],
        *,
        parent_workflow_id: str = "",
    ) -> None:
        self.run_readiness_validator.validate_workflow_subworkflow_nodes(
            nodes,
            parent_workflow_id=parent_workflow_id,
        )

    def _validate_agent_run_readiness(
        self,
        agent: dict[str, Any],
        *,
        label: str = "Agent",
        require_model_config: bool = False,
    ) -> None:
        self.run_readiness_validator.validate_agent_run_readiness(
            agent,
            label=label,
            require_model_config=require_model_config,
        )

    def _validate_workflow_agent_run_readiness(self, nodes: list[dict[str, Any]]) -> None:
        self.run_readiness_validator.validate_workflow_agent_run_readiness(nodes)

    def _validate_workflow_runnable_steps(self, nodes: list[dict[str, Any]]) -> None:
        self.run_readiness_validator.validate_workflow_runnable_steps(nodes)

    def list_runs(self, limit: int = 50) -> dict[str, Any]:
        return self.run_timeline.list_runs(limit)

    def list_run_groups(self, limit: int = 50) -> dict[str, Any]:
        return self.run_timeline.list_run_groups(limit)

    def get_run_group(self, run_group_id: str) -> dict[str, Any]:
        return self.run_timeline.get_run_group(run_group_id)

    def _run_group_source(self, run_group_id: str) -> str:
        return self.run_timeline.run_group_source(run_group_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        return self.run_timeline.get_run(run_id)

    def link_task_run(self, *, task_id: str, run_id: str, session_id: str = "") -> dict[str, Any]:
        return self.task_run_links.link(task_id=task_id, run_id=run_id, session_id=session_id)

    def get_task_run_link(self, task_id: str) -> dict[str, Any]:
        return self.task_run_links.get(task_id)

    def append_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        actor: str = "native_runtime",
        visibility: str = "user",
        sensitivity: str = "public",
    ) -> dict[str, Any]:
        return self.run_timeline.append_event(
            run_id,
            event_type,
            payload,
            actor=actor,
            visibility=visibility,
            sensitivity=sensitivity,
        )

    def list_run_events(
        self,
        run_id: str,
        *,
        after_sequence: int = 0,
        limit: int = 200,
        include_internal: bool = False,
    ) -> dict[str, Any]:
        return self.run_timeline.list_events(
            run_id,
            after_sequence=after_sequence,
            limit=limit,
            include_internal=include_internal,
        )

    def delete_run(self, run_id: str) -> dict[str, Any]:
        return self.run_deletion.delete(run_id)

    def read_run_artifact(self, run_id: str, artifact_path: str) -> dict[str, Any]:
        return self.run_timeline.read_artifact(run_id, artifact_path)

    def _insert_run_group(
        self,
        *,
        title: str,
        source: str,
        workspace_dir: str = "",
    ) -> dict[str, Any]:
        return self.run_groups.insert(title=title, source=source, workspace_dir=workspace_dir)

    def _append_run_to_group(self, run_group_id: str, run_id: str) -> None:
        self.run_groups.append_run(run_group_id, run_id)

    @staticmethod
    def _client_request_id_from_payload(payload: dict[str, Any]) -> str:
        client_request_id = str(
            payload.get("client_run_id")
            or payload.get("client_request_id")
            or payload.get("idempotency_key")
            or ""
        ).strip()[:128]
        if contains_sensitive_text(client_request_id):
            raise AgentRuntimeError("client_run_id/idempotency_key 不能包含 API key、token 或其他敏感值")
        return client_request_id

    def _run_by_client_request_id(self, client_request_id: str) -> dict[str, Any] | None:
        return self.runs.by_client_request_id(client_request_id)

    def _update_run_group(
        self,
        run_group_id: str,
        *,
        status: str | None = None,
        summary: str | None = None,
    ) -> None:
        self.run_groups.update(run_group_id, status=status, summary=summary)

    def _insert_run(
        self,
        *,
        kind: str,
        runnable_id: str,
        user_goal: str,
        run_group_id: str = "",
        client_request_id: str = "",
    ) -> dict[str, Any]:
        return self.runs.insert(
            kind=kind,
            runnable_id=runnable_id,
            user_goal=user_goal,
            run_group_id=run_group_id,
            client_request_id=client_request_id,
        )

    def _update_run(
        self,
        run_id: str,
        *,
        status: str | None = None,
        result: str | None = None,
        timeline: list[dict[str, Any]] | None = None,
        artifacts: list[dict[str, Any]] | None = None,
        pending_approval: dict[str, Any] | None | object = _UNSET,
    ) -> dict[str, Any]:
        run = self.runs.update(
            run_id,
            status=status,
            result=result,
            timeline=timeline,
            artifacts=artifacts,
            pending_approval=pending_approval,
        )
        return run

    def _terminal_run_or_none(self, run_id: str) -> dict[str, Any] | None:
        try:
            run = self.get_run(run_id)
        except KeyError:
            return None
        status = str(run.get("status") or "").strip()
        return run if status in _FINAL_RUN_STATUSES else None

    @staticmethod
    def _timeline(event: str, detail: str = "", **extra: Any) -> dict[str, Any]:
        return {
            "time": _now(),
            "event": event,
            "detail": redact_secrets(detail),
            **_redact_json_value(extra),
        }

    def _run_budget(self, run_id: str, timeline: list[dict[str, Any]]) -> _RunBudget:
        try:
            run = self.get_run(run_id) if run_id else {}
        except KeyError:
            run = {}
        return _runtime_run_budget_from_timeline(
            self.runtime_limits,
            started_at_epoch=_iso_epoch(run.get("created_at")),
            timeline=timeline,
        )

    def _check_context_budget(self, budget: _RunBudget, messages: list[dict[str, Any]]) -> None:
        _runtime_check_context_budget(budget, messages, redact_json_value=_redact_json_value)

    def _limit_model_output(self, value: Any) -> tuple[str, bool]:
        return _runtime_limit_model_output(value, limits=self.runtime_limits, redact_text=redact_secrets)

    def _limit_tool_result(self, result: dict[str, Any]) -> dict[str, Any]:
        return _runtime_limit_tool_result(result, limits=self.runtime_limits, redact_json_value=_redact_json_value)

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
        agent_id = str(payload.get("agent_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not agent_id:
            raise AgentRuntimeError("缺少 agent_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        agent = self._get_agent_private(agent_id)
        self._validate_agent_run_readiness(agent)
        start = self.agent_run_starter.start_sync(payload, agent=agent, lock=self._db_lock)
        if start.existing:
            return start.run
        run = start.run
        result = self._execute_agent_run(
            run["run_id"],
            agent,
            user_goal,
            upstream=str(payload.get("upstream") or ""),
        )
        if start.root_group:
            result = self._project_agent_run_group_if_root(result)
        return result

    def create_agent_run_async(
        self,
        payload: dict[str, Any],
        on_complete: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> dict[str, Any]:
        """创建 Agent Run 并立即返回，异步执行实际任务。

        Args:
            payload: Agent Run 配置
            on_complete: 执行完成后的回调函数（在后台线程中调用）

        Returns:
            包含 run_id 和 status="processing" 的 run 信息
        """
        agent_id = str(payload.get("agent_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not agent_id:
            raise AgentRuntimeError("缺少 agent_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        agent = self._get_agent_private(agent_id)
        self._validate_agent_run_readiness(agent)

        start = self.agent_run_starter.start_async(payload, agent=agent)
        run = start.run

        # 立即返回 processing 状态
        result = {
            **run,
            "status": "processing",
            "runnable": self.resolve_runnable(runnable_id=agent_id),
            "agent_run_id": run["run_id"],
        }

        # 启动后台线程执行
        def _execute_in_background() -> None:
            try:
                exec_result = self._execute_agent_run(
                    run["run_id"],
                    agent,
                    user_goal,
                    upstream=str(payload.get("upstream") or ""),
                )
                if start.root_group:
                    exec_result = self._project_agent_run_group_if_root(exec_result)
                if on_complete:
                    on_complete(exec_result)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "异步 Agent Run 执行失败: %s", exc, exc_info=True
                )
                safe_error = redact_secrets(exc)
                # 更新 run 状态为 failed
                self.runtime_agent_run_events.failed(run["run_id"], safe_error)
                self._update_run(
                    run["run_id"],
                    status="failed",
                    result=safe_error,
                    timeline=[self.runtime_agent_timeline.failed(safe_error)],
                    artifacts=[],
                    pending_approval=None,
                )
                if on_complete:
                    on_complete({
                        **run,
                        "status": "failed",
                        "result": safe_error,
                    })

        thread = threading.Thread(
            target=_execute_in_background,
            name=f"agent-run-{run['run_id'][:8]}",
            daemon=True,
        )
        thread.start()

        return result

    def _execute_agent_run(self, run_id: str, agent: dict[str, Any], user_goal: str, upstream: str = "") -> dict[str, Any]:
        preparation = self.agent_run_preparer.prepare(
            run_id,
            agent,
            user_goal,
            upstream,
        )
        timeline = preparation.timeline
        artifacts = preparation.artifacts
        try:
            self.agent_run_preparer.write_context_artifact(run_id, preparation)
            result = self._run_custom_api_agent(
                agent,
                preparation.context,
                preparation.broker,
                timeline,
                artifacts,
                run_id=run_id,
            )
            return self.agent_run_outcomes.completed(
                run_id,
                result,
                timeline=timeline,
                artifacts=artifacts,
            )
        except AgentApprovalRequired as exc:
            return self.approval_pause.project_tool_required(
                run_id,
                pending_approval=exc.pending_approval,
                timeline=timeline,
                artifacts=artifacts,
            )
        except Exception as exc:
            return self.agent_run_outcomes.failed(
                run_id,
                exc,
                timeline=timeline,
                artifacts=artifacts,
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
        start_iteration: int = 0,
        run_id: str = "",
        budget: _RunBudget | None = None,
    ) -> str:
        return self.custom_api_agent_loop.run(
            agent,
            context,
            broker,
            timeline,
            artifacts,
            messages=messages,
            start_iteration=start_iteration,
            run_id=run_id,
            budget=budget,
        )

    @staticmethod
    def _tool_loop_limit_detail(timeline: list[dict[str, Any]]) -> str:
        return _runtime_tool_loop_limit_detail(timeline)

    @staticmethod
    def _tool_loop_limit_artifact_completion(timeline: list[dict[str, Any]], artifacts: list[dict[str, Any]]) -> str | None:
        return _runtime_tool_loop_limit_artifact_completion(timeline, artifacts)

    @staticmethod
    def _fatal_tool_failure_detail(tool_name: str, tool_request: dict[str, Any], tool_result: dict[str, Any]) -> str:
        return _runtime_fatal_tool_failure_detail(tool_name, tool_request, tool_result)

    @staticmethod
    def _assistant_message_for_history(message: dict[str, Any]) -> dict[str, Any]:
        return _runtime_assistant_message_for_history(message)

    @staticmethod
    def _append_tool_result_message(messages: list[dict[str, Any]], tool_request: dict[str, Any], tool_result: dict[str, Any]) -> None:
        _runtime_append_tool_result_message(messages, tool_request, tool_result)

    def _run_tool_requests(
        self,
        tool_requests: list[dict[str, Any]],
        allowed_tools: list[str],
        broker: Any,
        messages: list[dict[str, Any]],
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        *,
        next_iteration: int,
        run_id: str = "",
        budget: _RunBudget | None = None,
    ) -> None:
        self.tool_operations.run_tool_requests(
            tool_requests,
            allowed_tools,
            broker,
            messages,
            timeline,
            artifacts,
            next_iteration=next_iteration,
            run_id=run_id,
            budget=budget,
        )

    def _call_agent_tool(
        self,
        tool_request: dict[str, Any],
        allowed_tools: list[str],
        broker: Any,
        timeline: list[dict[str, Any]],
        *,
        artifacts: list[dict[str, Any]] | None = None,
        approved: bool = False,
        run_id: str = "",
        budget: _RunBudget | None = None,
    ) -> dict[str, Any]:
        return self.tool_operations.call_agent_tool(
            tool_request,
            allowed_tools,
            broker,
            timeline,
            artifacts=artifacts,
            approved=approved,
            run_id=run_id,
            budget=budget,
        )

    @staticmethod
    def _validate_tool_payload(tool_name: str, payload: dict[str, Any]) -> None:
        RuntimeToolOperations.validate_tool_payload(tool_name, payload)

    @staticmethod
    def _make_pending_approval(
        tool_request: dict[str, Any],
        *,
        messages: list[dict[str, Any]],
        next_iteration: int,
        remaining_tool_requests: list[dict[str, Any]],
    ) -> dict[str, Any]:
        return RuntimeToolOperations.build_pending_approval(
            tool_request,
            messages=messages,
            next_iteration=next_iteration,
            remaining_tool_requests=remaining_tool_requests,
            now=_now,
        )

    def _tool_requests_from_message(self, message: dict[str, Any], content: str) -> list[dict[str, Any]]:
        return self.tool_operations.tool_requests_from_message(message, content)

    @staticmethod
    def _parse_tool_calls(tool_calls: Any) -> list[dict[str, Any]]:
        return RuntimeToolOperations.parse_tool_calls(tool_calls)

    @staticmethod
    def _model_profile_config_private(profile_id: str, *, capability: str) -> dict[str, Any]:
        return RuntimeModelProfileResolver(
            profile_service_factory=lambda: get_model_profile_service(),
            supports_openai_compatible_api=supports_openai_compatible_api,
            default_agent_ids=_DEFAULT_AGENT_IDS,
            error_type=AgentRuntimeError,
        ).model_profile_config_private(profile_id, capability=capability)

    @staticmethod
    def _chat_profile_model_config_private(profile_id: str) -> dict[str, Any]:
        return NativeRunEngine._model_profile_config_private(profile_id, capability="chat")

    def _agent_model_config_private(self, agent: dict[str, Any]) -> dict[str, Any]:
        return self.model_profile_resolver.agent_model_config_private(agent)

    @staticmethod
    def _parse_tool_request(content: str) -> dict[str, Any] | None:
        return RuntimeToolOperations.parse_tool_request(content)

    @staticmethod
    def _openai_compatible_chat(base_url: str, model: str, api_key: str, messages: list[dict[str, str]]) -> str:
        url = f"{base_url.rstrip('/')}/chat/completions"
        timeout = read_openai_compatible_chat_timeout()
        body = json.dumps({"model": model, "messages": messages, "temperature": 0.2}).encode("utf-8")
        request = urlrequest.Request(
            url,
            data=body,
            method="POST",
            headers={
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}",
            },
        )
        try:
            with urlopen_with_bundled_ca(request, timeout=timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except TimeoutError as exc:
            raise AgentRuntimeError(f"custom_api 调用超时：等待响应超过 {timeout:g} 秒") from exc
        except (urlerror.URLError, json.JSONDecodeError) as exc:
            raise AgentRuntimeError(f"custom_api 调用失败：{redact_secrets(exc)}") from exc
        return str(payload.get("choices", [{}])[0].get("message", {}).get("content") or "")

    def test_agent_model(self, agent_id: str) -> dict[str, Any]:
        agent = self._get_agent_private(agent_id)
        return self.agent_model_tester.test_agent_model(agent)

    def create_workflow_run(self, payload: dict[str, Any]) -> dict[str, Any]:
        workflow_id = str(payload.get("workflow_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not workflow_id:
            raise AgentRuntimeError("缺少 workflow_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        workflow = self.get_workflow(workflow_id)
        if not workflow.get("enabled", True):
            raise AgentRuntimeError("Workflow 已停用")
        self.validate_workflow(workflow["nodes"], workflow["edges"])
        self._validate_workflow_agent_nodes(workflow["nodes"])
        self._validate_workflow_subworkflow_nodes(workflow["nodes"], parent_workflow_id=workflow_id)
        self._validate_workflow_runnable_steps(workflow["nodes"])
        self._validate_workflow_agent_run_readiness(workflow["nodes"])
        start = self.workflow_run_starter.start_sync(
            payload,
            workflow=workflow,
            workflow_id=workflow_id,
            lock=self._db_lock,
        )
        if start.existing:
            return start.run
        run = start.run
        timeline, started_payload = self.workflow_run_start_projector.started_projection(workflow_id, workflow)
        self.append_run_event(
            run["run_id"],
            "workflow.run.started",
            started_payload,
        )
        artifacts: list[dict[str, Any]] = []
        context = user_goal
        return self._continue_workflow_run(
            run,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=0,
            root_group=start.root_group,
        )

    def create_workflow_run_async(
        self,
        payload: dict[str, Any],
        on_complete: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> dict[str, Any]:
        workflow_id = str(payload.get("workflow_id") or payload.get("runnable_id") or "")
        user_goal = str(payload.get("user_goal") or payload.get("goal") or "").strip()
        if not workflow_id:
            raise AgentRuntimeError("缺少 workflow_id")
        if not user_goal:
            raise AgentRuntimeError("运行目标不能为空")
        workflow = self.get_workflow(workflow_id)
        if not workflow.get("enabled", True):
            raise AgentRuntimeError("Workflow 已停用")
        self.validate_workflow(workflow["nodes"], workflow["edges"])
        self._validate_workflow_agent_nodes(workflow["nodes"])
        self._validate_workflow_subworkflow_nodes(workflow["nodes"], parent_workflow_id=workflow_id)
        self._validate_workflow_runnable_steps(workflow["nodes"])
        self._validate_workflow_agent_run_readiness(workflow["nodes"])

        start = self.workflow_run_starter.start_async(
            payload,
            workflow=workflow,
            workflow_id=workflow_id,
        )
        run = start.run
        timeline, started_payload = self.workflow_run_start_projector.started_projection(workflow_id, workflow)
        self.append_run_event(
            run["run_id"],
            "workflow.run.started",
            started_payload,
        )
        run = self._update_run(
            run["run_id"],
            status="running",
            timeline=timeline,
            artifacts=[],
            pending_approval=None,
        )
        result = {
            **run,
            "status": "processing",
            "workflow_run_id": run["run_id"],
            "runnable": self.resolve_runnable(runnable_id=workflow_id),
        }

        def _execute_in_background() -> None:
            try:
                exec_result = self._continue_workflow_run(
                    run,
                    workflow,
                    context=user_goal,
                    timeline=list(timeline),
                    artifacts=[],
                    start_index=0,
                    root_group=start.root_group,
                )
                if on_complete:
                    on_complete(exec_result)
            except Exception as exc:
                import logging
                logging.getLogger(__name__).error(
                    "异步 Workflow Run 执行失败: %s", exc, exc_info=True
                )
                failed = self.workflow_continuation.project_background_failure(
                    run,
                    timeline=timeline,
                    error=exc,
                    root_group=start.root_group,
                )
                if on_complete:
                    on_complete(failed)

        thread = threading.Thread(
            target=_execute_in_background,
            name=f"workflow-run-{run['run_id'][:8]}",
            daemon=True,
        )
        thread.start()

        return result

    def _workflow_parent_runs_waiting_for_child(
        self,
        child_run: dict[str, Any],
    ) -> list[dict[str, Any]]:
        return self.workflow_parent_locator.parent_runs_waiting_for_child(child_run)

    def _workflow_resume_start_index(
        self,
        workflow: dict[str, Any],
        workflow_run: dict[str, Any],
        child_run_id: str,
    ) -> int | None:
        return self.workflow_resume_planner.resume_start_index(
            workflow,
            workflow_run,
            child_run_id,
        )

    def _workflow_run_is_group_root(self, workflow_run: dict[str, Any]) -> bool:
        return self.workflow_parent_locator.workflow_run_is_group_root(workflow_run)

    @staticmethod
    def _workflow_child_artifact_refs(child_run: dict[str, Any], label: str) -> list[dict[str, Any]]:
        return WorkflowChildOutcomeCoordinator.child_artifact_refs(child_run, label)

    @staticmethod
    def _workflow_child_node_context(
        timeline: list[dict[str, Any]],
        child_run: dict[str, Any],
    ) -> tuple[str, dict[str, str]]:
        return WorkflowChildOutcomeCoordinator.child_node_context(timeline, child_run)

    def _merge_workflow_child_run_outcome(
        self,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        child_run: dict[str, Any],
        label: str,
    ) -> None:
        self.workflow_child_outcomes.merge_child_run_outcome(
            timeline,
            artifacts,
            child_run,
            label,
        )

    @staticmethod
    def _workflow_artifact_path(label: str, artifacts: list[dict[str, Any]], configured_path: str = "") -> str:
        return WorkflowPathPlanner.artifact_path(label, artifacts, configured_path)

    def _resume_parent_workflows_after_child_update(self, child_run: dict[str, Any]) -> None:
        self.workflow_parent_resume.resume_after_child_update(child_run)

    def _mark_parent_workflows_child_running(self, child_run: dict[str, Any]) -> None:
        self.workflow_parent_resume.mark_child_running(child_run)

    def _resume_parent_workflow_after_child_update(
        self,
        workflow_run: dict[str, Any],
        child_run: dict[str, Any],
    ) -> dict[str, Any]:
        return self.workflow_parent_resume.resume_parent_after_child_update(workflow_run, child_run)

    def _continue_workflow_run(
        self,
        run: dict[str, Any],
        workflow: dict[str, Any],
        *,
        context: str,
        timeline: list[dict[str, Any]],
        artifacts: list[dict[str, Any]],
        start_index: int,
        root_group: bool,
        start_node_id: str = "",
    ) -> dict[str, Any]:
        return self.workflow_continuation.continue_run(
            run,
            workflow,
            context=context,
            timeline=timeline,
            artifacts=artifacts,
            start_index=start_index,
            root_group=root_group,
            start_node_id=start_node_id,
        )

    def _workflow_path(self, workflow: dict[str, Any]) -> list[dict[str, Any]]:
        return self.workflow_path_planner.workflow_path(workflow)

    def _workflow_nodes_by_id(self, workflow: dict[str, Any]) -> dict[str, dict[str, Any]]:
        return self.workflow_path_planner.nodes_by_id(workflow)

    def _workflow_next_node_id(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any] | str,
        context: str,
    ) -> str:
        return self.workflow_resume_planner.next_node_id(workflow, node, context)

    def _workflow_condition_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
    ) -> dict[str, Any]:
        return self.workflow_path_planner.condition_selection(workflow, node, context)

    def _workflow_parallel_plan(self, workflow: dict[str, Any], node: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_path_planner.parallel_plan(workflow, node)

    def _workflow_loop_selection(
        self,
        workflow: dict[str, Any],
        node: dict[str, Any],
        context: str,
        *,
        previous_iterations: int = 0,
    ) -> dict[str, Any]:
        return self.workflow_path_planner.loop_selection(
            workflow,
            node,
            context,
            previous_iterations=previous_iterations,
        )

    def _workflow_loop_step_limit(self, workflow: dict[str, Any]) -> int:
        return self.workflow_path_planner.loop_step_limit(workflow)

    def _workflow_loop_iterations_from_timeline(self, timeline: list[dict[str, Any]]) -> dict[str, int]:
        return self.workflow_path_planner.loop_iterations_from_timeline(timeline)

    @staticmethod
    def _workflow_node_task(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.node_task(node)

    @staticmethod
    def _workflow_approval_criteria(node: dict[str, Any]) -> str:
        return WorkflowPathPlanner.approval_criteria(node)

    @staticmethod
    def _workflow_child_goal(workflow_goal: str, step_task: str) -> str:
        return WorkflowPathPlanner.child_goal(workflow_goal, step_task)

    def _workflow_path_snapshot(self, workflow: dict[str, Any]) -> list[dict[str, str]]:
        return self.workflow_path_planner.path_snapshot(workflow)

    @staticmethod
    def _workflow_runtime_snapshot(workflow: dict[str, Any]) -> dict[str, Any]:
        return WorkflowPathPlanner.runtime_snapshot(workflow)

    def _workflow_for_run_resume(self, workflow_run: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_resume_planner.workflow_for_run_resume(workflow_run)

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        clean_run_id = str(run_id or "").strip()
        with self._run_cancel_locks_guard:
            lock = self._run_cancel_locks.setdefault(clean_run_id, threading.RLock())
        try:
            with lock:
                return self._cancel_run_once(clean_run_id)
        finally:
            with self._run_cancel_locks_guard:
                if self._run_cancel_locks.get(clean_run_id) is lock:
                    self._run_cancel_locks.pop(clean_run_id, None)

    def _cancel_workflow_run_projection(
        self,
        run_id: str,
        run: dict[str, Any],
        timeline: list[dict[str, Any]],
    ) -> tuple[list[dict[str, Any]], list[dict[str, Any]], str]:
        return self.workflow_cancellation.project_cancelled_workflow_run(run_id, run, timeline)

    def _cancel_run_once(self, run_id: str) -> dict[str, Any]:
        return self.run_cancellation.cancel_once(run_id)

    def _tool_approval_resume_context(
        self,
        run: dict[str, Any],
        pending: dict[str, Any],
        *,
        runtime: dict[str, Any],
        skills: list[dict[str, Any]] | None = None,
    ) -> ToolApprovalResumeContext:
        return self.tool_approval_resume.context(
            run,
            pending,
            runtime=runtime,
            skills=skills,
        )

    def approve_run_approval(self, run_id: str) -> dict[str, Any]:
        return self.approval_execution.approve_run_approval(run_id)

    def _approve_run_approval_once(self, run: dict[str, Any]) -> dict[str, Any]:
        if run["status"] != "approval_required":
            return run
        if run["kind"] == "workflow_run":
            return self._approve_workflow_run_approval(run)
        if run["kind"] == "main_chat_run":
            return self._approve_main_chat_run_approval(run)
        if run["kind"] != "agent_run":
            raise AgentRuntimeError("当前只支持恢复 Agent Run 的工具审批")
        return self.tool_approval_resume.approve_agent_run(run)

    def _resume_approved_tool_run(
        self,
        *,
        run_id: str,
        pending: dict[str, Any],
        resume_context: ToolApprovalResumeContext,
        agent: dict[str, Any],
        resumed_detail: str,
        running_result: str,
        project_completed: Any,
        project_running: Any | None = None,
        project_required: Any | None = None,
        project_result: Any | None = None,
        redact_error: Any = redact_api_error_text,
    ) -> dict[str, Any]:
        return self.approval_resume.resume_approved_tool_run(
            run_id=run_id,
            pending=pending,
            context=resume_context,
            agent=agent,
            resumed_detail=resumed_detail,
            running_result=running_result,
            project_completed=project_completed,
            project_required=self._project_approval_resume_required,
            project_failed=self._project_approval_resume_failed,
            get_current_run=self.get_run,
            project_running=project_running,
            prepare_required=project_required,
            project_result=project_result,
            redact_error=redact_error,
        )

    def _project_agent_approval_resume_running(self, running: dict[str, Any]) -> dict[str, Any]:
        return self.approval_resume_projection.project_agent_running(running)

    def _project_agent_approval_resume_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_agent_completed(context, result_text)

    def _project_main_chat_approval_resume_completed(
        self,
        context: ToolApprovalResumeContext,
        result_text: str,
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_main_chat_completed(context, result_text)

    def _project_approval_resume_required(
        self,
        context: ToolApprovalResumeContext,
        pending_approval: dict[str, Any],
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_required(context, pending_approval)

    def _project_approval_resume_failed(
        self,
        context: ToolApprovalResumeContext,
        safe_error: str,
    ) -> dict[str, Any]:
        return self.approval_resume_projection.project_failed(context, safe_error)

    def _approve_main_chat_run_approval(self, run: dict[str, Any]) -> dict[str, Any]:
        return self.tool_approval_resume.approve_main_chat_run(run)

    def _approve_workflow_run_approval(self, run: dict[str, Any]) -> dict[str, Any]:
        return self.workflow_approval_execution.approve_workflow_run(run)

    def _project_cancelled_workflow_group_if_root(
        self,
        run: dict[str, Any],
        result: dict[str, Any],
    ) -> dict[str, Any]:
        return self.run_transition_projection.project_cancelled_workflow_group_if_root(run, result)

    def _project_child_run_transition(self, result: dict[str, Any]) -> dict[str, Any]:
        return self.run_transition_projection.project_child_run_transition(result)

    def _project_agent_run_group_if_root(self, result: dict[str, Any]) -> dict[str, Any]:
        return self.run_transition_projection.project_agent_run_group_if_root(result)

    def reject_run_approval(self, run_id: str, reason: str = "") -> dict[str, Any]:
        return self.approval_transitions.reject(run_id, reason)

    def timeout_run_approval(self, run_id: str, reason: str = "approval_wait_timeout") -> dict[str, Any]:
        return self.approval_transitions.timeout(run_id, reason)

    def _update_agent_run_group_if_root(self, run: dict[str, Any]) -> None:
        self.agent_run_group_projection.update_if_root(run)

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
    ) -> dict[str, Any]:
        return self.runnable_run_coordinator.create_run(
            runnable_id=runnable_id,
            name=name,
            user_goal=user_goal,
            run_group_id=run_group_id,
            upstream=upstream,
            client_run_id=client_run_id,
            client_request_id=client_request_id,
        )

    def create_run_for_runnable_async(
        self,
        *,
        runnable_id: str = "",
        name: str = "",
        user_goal: str = "",
        run_group_id: str = "",
        upstream: str = "",
        on_complete: "Callable[[dict[str, Any]], None] | None" = None,
    ) -> dict[str, Any]:
        """创建 Run 并立即返回，异步执行实际任务。"""
        return self.runnable_run_coordinator.create_run_async(
            runnable_id=runnable_id,
            name=name,
            user_goal=user_goal,
            run_group_id=run_group_id,
            upstream=upstream,
            on_complete=on_complete,
        )

    def rerun_run(self, run_id: str) -> dict[str, Any]:
        return self.run_rerun.rerun(run_id)

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


AgentRuntimeService = NativeRunEngine

_global_agent_runtime_service: NativeRunEngine | None = None


def get_native_agent_readiness() -> dict[str, Any]:
    """Return native main-agent readiness."""
    try:
        profile_service = get_model_profile_service()
        profile_id = str(profile_service.get_defaults().get("chat") or "").strip()
        if not profile_id:
            return {
                "ready": False,
                "code": "native_agent_not_ready",
                "reason": "model_profile_required",
                "message": "请先配置并选择默认对话模型。",
                "capabilities": {
                    "model": False,
                    "image_input": False,
                    "tools": False,
                    "approval": False,
                },
            }
        profile = profile_service.get_profile_private(profile_id)
    except KeyError:
        return {
            "ready": False,
            "code": "native_agent_not_ready",
            "reason": "model_profile_required",
            "message": "默认对话模型不存在，请重新选择。",
            "capabilities": {
                "model": False,
                "image_input": False,
                "tools": False,
                "approval": False,
            },
        }
    except Exception as exc:
        return {
            "ready": False,
            "code": "native_agent_not_ready",
            "reason": "model_profile_unavailable",
            "message": redact_secrets(exc),
            "capabilities": {
                "model": False,
                "image_input": False,
                "tools": False,
                "approval": False,
            },
        }

    reason = ""
    if not profile.get("enabled", True):
        reason = "默认对话模型已停用。"
    elif str(profile.get("status") or "") != "available":
        reason = "默认对话模型尚未通过连接测试。"
    elif str(profile.get("capability") or "") != "chat":
        reason = "默认模型不是对话模型。"
    elif not supports_openai_compatible_api(str(profile.get("provider") or "openai_compatible")):
        reason = "Native Agent 当前仅支持 OpenAI-compatible 对话模型。"
    elif not all(str(profile.get(key) or "").strip() for key in ("base_url", "model", "api_key")):
        reason = "默认对话模型配置不完整。"

    ready = not reason
    return {
        "ready": ready,
        "code": "" if ready else "native_agent_not_ready",
        "reason": "" if ready else "model_profile_unavailable",
        "message": reason,
        "profile_id": profile_id,
        "model": str(profile.get("model") or ""),
        "provider": str(profile.get("provider") or ""),
        "capabilities": {
            "model": ready,
            "image_input": ready,
            "tools": False,
            "approval": False,
        },
    }


def get_native_run_engine() -> NativeRunEngine:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is None:
        _global_agent_runtime_service = NativeRunEngine()
    return _global_agent_runtime_service


def get_agent_runtime_service() -> NativeRunEngine:
    """Compatibility accessor for existing AppState, TaskRunner, and routes."""
    return get_native_run_engine()


def close_agent_runtime_service() -> None:
    global _global_agent_runtime_service
    if _global_agent_runtime_service is not None:
        _global_agent_runtime_service.close()
        _global_agent_runtime_service = None
