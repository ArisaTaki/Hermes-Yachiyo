"""Public Yachiyo Agent contracts shared by Chat and Agent Studio."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

TaskStatus = Literal[
    "queued",
    "running",
    "waiting_approval",
    "completed",
    "failed",
    "cancelled",
]
GroupMode = Literal["moderated", "round_robin", "debate", "pipeline", "parallel", "custom"]
MemoryScope = Literal["shared", "per_agent", "hybrid"]
ApprovalStatus = Literal["pending", "approved", "rejected", "cancelled", "expired"]
DesktopExecutionRisk = Literal["low", "medium", "high"]
RecoveryActionKind = Literal["permission_recovery", "retry_original"]
TaskWorkspaceItemKind = Literal[
    "input",
    "scratch",
    "artifact",
    "checkpoint",
    "todo",
    "memory",
    "other",
]
TaskTodoStatus = Literal["pending", "in_progress", "blocked", "completed", "skipped"]
TaskCheckpointStatus = Literal[
    "planned",
    "ready",
    "waiting_approval",
    "blocked",
    "completed",
]
TaskReplanStatus = Literal["requested", "planned", "running", "completed", "blocked"]
TaskIntentKind = Literal[
    "desktop_operation",
    "data_analysis",
    "report_generation",
    "web_research",
    "file_operation",
    "file_access",
    "file_organization",
    "communication",
    "schedule",
    "media_playback",
    "system_control",
    "clipboard_operation",
    "information_capture",
    "code_task",
    "workflow_orchestration",
    "multi_agent",
    "general",
]
CapabilityCategory = Literal[
    "desktop",
    "data",
    "file",
    "terminal",
    "browser",
    "artifact",
    "capture",
    "clipboard",
    "communication",
    "schedule",
    "media",
    "system",
    "workflow",
    "group",
    "memory",
    "skill",
    "general",
]


class _PublicSnapshot(BaseModel):
    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        serialize_by_alias=True,
    )


class ReadinessSnapshot(_PublicSnapshot):
    ready: bool
    status: str = ""
    message: str | None = None
    capabilities: dict[str, Any] = Field(default_factory=dict)


class DesktopExecutionCapabilitySnapshot(_PublicSnapshot):
    available: bool = False
    platform: str = ""
    missing_permissions: list[str] = Field(default_factory=list)
    blocking_conditions: list[str] = Field(default_factory=list)
    tools: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    degraded_tools: list[str] = Field(default_factory=list)
    unavailable_tools: list[str] = Field(default_factory=list)
    risk_default: DesktopExecutionRisk = "low"
    diagnostic_route: str | None = None


class DesktopActionRiskSnapshot(_PublicSnapshot):
    action_id: str
    risk_level: DesktopExecutionRisk
    title: str
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    requires_approval: bool = False


class DesktopRecoveryActionMetadataSnapshot(_PublicSnapshot):
    daily_desktop_intent: bool = True
    desktop_permission_recovery: bool = True
    desktop_permission_retry: bool | None = None
    recovery_action_kind: RecoveryActionKind | None = None
    recovery_tool: str
    recovery_input: dict[str, Any] = Field(default_factory=dict)
    recovery_permission_target: str = ""
    recovery_risk_level: DesktopExecutionRisk | str | None = None
    recovery_retry_tool: str | None = None
    recovery_retry_input: dict[str, Any] = Field(default_factory=dict)
    recovery_retry_input_schema: dict[str, Any] = Field(default_factory=dict)
    recovery_retry_input_source: str | None = None
    recovery_retry_artifact_tool: str | None = None
    recovery_retry_artifact_kind: str | None = None
    required_retry_fields: list[str] = Field(default_factory=list)
    recommended_tools: list[str] = Field(default_factory=list)
    recovery_retry_prompt: str | None = None
    recovery_followup_tool: str | None = None
    recovery_followup_input: dict[str, Any] = Field(default_factory=dict)
    recovery_retry_source_event_type: str | None = None
    recovery_retry_source_tool_call_id: str | None = None
    source_task_id: str | None = None
    source_task_title: str | None = None


class ToolCatalogItemSnapshot(_PublicSnapshot):
    tool_name: str
    function_name: str
    description: str = ""
    capability_id: str | None = None
    risk_level: DesktopExecutionRisk | str | None = None
    approval_required: bool = False
    input_schema: dict[str, Any] = Field(default_factory=dict)
    model_tool_schema: dict[str, Any] = Field(default_factory=dict)
    missing_permissions: list[str] = Field(default_factory=list)
    blocking_conditions: list[str] = Field(default_factory=list)
    fallback_notes: list[str] = Field(default_factory=list)
    diagnostic_route: str | None = None
    source: str = "runtime"


class RestrictedPluginToolSnapshot(_PublicSnapshot):
    tool_name: str
    tool_id: str = ""
    function_name: str = ""
    risk_level: DesktopExecutionRisk | str | None = None
    enabled: bool = False


class RestrictedToolPluginSnapshot(_PublicSnapshot):
    plugin_id: str
    enabled: bool = False
    tool_names: list[str] = Field(default_factory=list)
    tools: list[RestrictedPluginToolSnapshot] = Field(default_factory=list)
    skill_docs: str = ""
    source: str = "restricted_tool_plugin"


class InstallRestrictedToolPluginRequest(_PublicSnapshot):
    plugin_id: str
    enabled: bool = True


class UpdateRestrictedToolPluginRequest(_PublicSnapshot):
    enabled: bool | None = None


class ToolCatalogSnapshot(_PublicSnapshot):
    tools: list[ToolCatalogItemSnapshot] = Field(default_factory=list)
    capabilities: dict[str, DesktopExecutionCapabilitySnapshot] = Field(default_factory=dict)
    plugins: list[RestrictedToolPluginSnapshot] = Field(default_factory=list)
    source: str = "runtime"


class CapabilitySnapshot(_PublicSnapshot):
    capability_id: str
    title: str
    category: CapabilityCategory | str = "general"
    description: str = ""
    tools: list[str] = Field(default_factory=list)
    available_tools: list[str] = Field(default_factory=list)
    missing_tools: list[str] = Field(default_factory=list)
    risk_level: DesktopExecutionRisk | str = "low"
    approval_required: bool = False
    discovery_actions: list[str] = Field(default_factory=list)
    execution_actions: list[str] = Field(default_factory=list)
    output_kinds: list[str] = Field(default_factory=list)
    source: str = "capability_registry"


class TaskIntentSnapshot(_PublicSnapshot):
    intent_id: str
    kind: TaskIntentKind | str
    title: str
    user_goal: str = ""
    confidence: float = 0.0
    description: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    expected_outputs: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    preferred_capabilities: list[str] = Field(default_factory=list)
    missing_inputs: list[str] = Field(default_factory=list)
    risk_level: DesktopExecutionRisk | str = "low"
    source: str = "task_intent_router"


class ToolPlanStepSnapshot(_PublicSnapshot):
    step_id: str
    title: str
    capability_id: str
    action: str = ""
    tool_name: str | None = None
    input_preview: dict[str, Any] = Field(default_factory=dict)
    risk_level: DesktopExecutionRisk | str = "low"
    approval_required: bool = False
    depends_on: list[str] = Field(default_factory=list)
    reason: str = ""
    fallback_tools: list[str] = Field(default_factory=list)
    status: Literal["planned", "unavailable", "skipped"] | str = "planned"


class ToolPlanSnapshot(_PublicSnapshot):
    plan_id: str
    title: str
    steps: list[ToolPlanStepSnapshot] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    approvals_required: list[str] = Field(default_factory=list)
    artifacts_expected: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    source: str = "runtime_planner"


class TaskWorkspaceItemSnapshot(_PublicSnapshot):
    item_id: str
    title: str
    kind: TaskWorkspaceItemKind | str = "other"
    path: str | None = None
    description: str = ""
    source_step_id: str | None = None
    status: str = "planned"
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskWorkspaceSnapshot(_PublicSnapshot):
    workspace_id: str
    title: str
    root_label: str = "runtime://task-workspace"
    summary: str = ""
    items: list[TaskWorkspaceItemSnapshot] = Field(default_factory=list)
    context: dict[str, Any] = Field(default_factory=dict)
    source: str = "runtime_planner"


class TaskTodoItemSnapshot(_PublicSnapshot):
    todo_id: str
    title: str
    status: TaskTodoStatus | str = "pending"
    capability_id: str = ""
    step_id: str | None = None
    tool_name: str | None = None
    approval_required: bool = False
    depends_on: list[str] = Field(default_factory=list)
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class TaskCheckpointSnapshot(_PublicSnapshot):
    checkpoint_id: str
    title: str
    status: TaskCheckpointStatus | str = "planned"
    after_step_id: str | None = None
    depends_on: list[str] = Field(default_factory=list)
    verifies: list[str] = Field(default_factory=list)
    replan_on_failure: bool = True
    payload: dict[str, Any] = Field(default_factory=dict)


class ReplanSignalSnapshot(_PublicSnapshot):
    signal_id: str
    trigger: str
    source_step_id: str | None = None
    condition: str = ""
    target: str = ""
    fallback_tools: list[str] = Field(default_factory=list)
    reason: str = ""


class TaskCoreSnapshot(_PublicSnapshot):
    core_id: str
    workspace: TaskWorkspaceSnapshot
    todos: list[TaskTodoItemSnapshot] = Field(default_factory=list)
    checkpoints: list[TaskCheckpointSnapshot] = Field(default_factory=list)
    replan_signals: list[ReplanSignalSnapshot] = Field(default_factory=list)
    source: str = "runtime_planner"


class TaskReplanRequestSnapshot(_PublicSnapshot):
    request_id: str
    trigger: str
    status: TaskReplanStatus | str = "requested"
    run_id: str | None = None
    task_id: str | None = None
    decision_id: str | None = None
    plan_id: str | None = None
    core_id: str | None = None
    source_step_id: str | None = None
    source_tool_name: str | None = None
    target_capability_id: str = ""
    condition: str = ""
    reason: str = ""
    failure_event_type: str = ""
    failure_detail: str = ""
    fallback_tools: list[str] = Field(default_factory=list)
    replan_prompt: str = ""
    route_to_studio: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""
    source: str = "runtime_planner"


class RuntimePlanSnapshot(_PublicSnapshot):
    plan_id: str
    intent: TaskIntentSnapshot
    capabilities: list[CapabilitySnapshot] = Field(default_factory=list)
    tool_plan: ToolPlanSnapshot
    task_core: TaskCoreSnapshot | None = None
    route_to_studio: bool = False
    timeline_preview: list[dict[str, Any]] = Field(default_factory=list)
    source: str = "runtime_planner"


class PlannerDecisionSnapshot(_PublicSnapshot):
    decision_id: str
    prompt: str
    selected_intent: TaskIntentSnapshot
    candidate_intents: list[TaskIntentSnapshot] = Field(default_factory=list)
    plan: RuntimePlanSnapshot
    created_at: str = ""
    source: str = "runtime_planner"


class PlannerTraceSummarySnapshot(_PublicSnapshot):
    source: str = ""
    decision_id: str | None = None
    plan_id: str | None = None
    intent_kind: str | None = None
    intent_title: str | None = None
    route_to_studio: bool | None = None
    selection_source: str | None = None
    selection_role: str | None = None
    selection_reason: str | None = None
    planner_entrypoint: str | None = None
    entrypoint_source: str | None = None
    launcher_mode: str | None = None
    launcher_surface: str | None = None
    runnable_kind: str | None = None
    followup_target: dict[str, Any] = Field(default_factory=dict)
    plan_tools: list[str] = Field(default_factory=list)
    selected_tools: list[str] = Field(default_factory=list)
    plan_capabilities: list[str] = Field(default_factory=list)
    required_capabilities: list[str] = Field(default_factory=list)
    missing_capabilities: list[str] = Field(default_factory=list)
    approvals_required: list[str] = Field(default_factory=list)
    artifacts_expected: list[str] = Field(default_factory=list)
    open_questions: list[str] = Field(default_factory=list)
    step_count: int = 0
    event_count: int = 0


class PublicRunEvent(_PublicSnapshot):
    event_id: str | None = None
    run_id: str
    sequence: int = 0
    schema_version: int = 1
    event_type: str
    title: str | None = None
    detail: str | None = None
    actor: str | None = None
    visibility: Literal["user", "internal"] = "user"
    sensitivity: Literal["public", "secret"] = "public"
    payload: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class RunEventPageSnapshot(_PublicSnapshot):
    run_id: str
    after_sequence: int = 0
    limit: int = 200
    next_after_sequence: int = 0
    has_more: bool = False
    events: list[PublicRunEvent] = Field(default_factory=list)


class ApprovalCardSnapshot(_PublicSnapshot):
    approval_id: str
    run_id: str | None = None
    source_run_id: str | None = None
    source_runnable_id: str | None = None
    source_runnable_name: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    workflow_node_id: str | None = None
    workflow_node_label: str | None = None
    group_id: str | None = None
    group_run_id: str | None = None
    title: str
    description: str | None = None
    status: ApprovalStatus = "pending"
    tool_name: str | None = None
    risk_level: str | None = None
    input_preview: dict[str, Any] = Field(default_factory=dict)
    policy_reason: str | None = None
    requested_at: str = ""
    resolved_at: str | None = None
    open_in_studio_url: str | None = None


class ArtifactSnapshot(_PublicSnapshot):
    artifact_id: str
    run_id: str | None = None
    source_run_id: str | None = None
    source_tool: str | None = None
    source_runnable_id: str | None = None
    source_runnable_name: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    workflow_node_id: str | None = None
    workflow_node_label: str | None = None
    group_id: str | None = None
    group_run_id: str | None = None
    title: str
    kind: str
    planned_kind: str | None = None
    source_kind: str | None = None
    requested_outputs: list[str] | None = None
    manifest_index: int | None = None
    path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    preview_text: str | None = None
    url: str | None = None
    created_at: str = ""


class ArtifactContentSnapshot(_PublicSnapshot):
    ok: bool = True
    run_id: str | None = None
    task_id: str | None = None
    path: str
    content: str = ""
    mime_type: str | None = None
    truncated: bool = False


class ToolCallSnapshot(_PublicSnapshot):
    tool_call_id: str
    run_id: str | None = None
    source_run_id: str | None = None
    source_runnable_id: str | None = None
    source_runnable_name: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    workflow_node_id: str | None = None
    workflow_node_label: str | None = None
    group_id: str | None = None
    group_run_id: str | None = None
    tool_name: str
    status: str
    risk_level: str | None = None
    input_preview: dict[str, Any] = Field(default_factory=dict)
    output_preview: dict[str, Any] = Field(default_factory=dict)
    foreground_lock_busy: bool = False
    foreground_lock_holder: str | None = None
    approval_id: str | None = None
    started_at: str = ""
    completed_at: str | None = None


class MemoryTraceSnapshot(_PublicSnapshot):
    trace_id: str
    run_id: str
    event_id: str | None = None
    sequence: int = 0
    event_type: str
    status: str = "completed"
    action: str | None = None
    memory_id: str | None = None
    memory_kind: str | None = None
    memory_scope: str | None = None
    count: int = 0
    source_run_id: str | None = None
    source_runnable_id: str | None = None
    source_runnable_name: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    workflow_node_id: str | None = None
    workflow_node_label: str | None = None
    group_id: str | None = None
    group_run_id: str | None = None
    title: str
    detail: str | None = None
    payload_preview: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class SkillTraceSnapshot(_PublicSnapshot):
    trace_id: str
    run_id: str
    event_id: str | None = None
    sequence: int = 0
    event_type: str
    status: str = "completed"
    skill_id: str | None = None
    skill_name: str | None = None
    source_ref: str | None = None
    source_type: str | None = None
    tool_name: str | None = None
    source_run_id: str | None = None
    source_runnable_id: str | None = None
    source_runnable_name: str | None = None
    workflow_id: str | None = None
    workflow_run_id: str | None = None
    workflow_node_id: str | None = None
    workflow_node_label: str | None = None
    group_id: str | None = None
    group_run_id: str | None = None
    title: str
    detail: str | None = None
    payload_preview: dict[str, Any] = Field(default_factory=dict)
    created_at: str = ""


class AgentTaskSnapshot(_PublicSnapshot):
    task_id: str
    conversation_id: str | None = None
    title: str
    status: TaskStatus
    summary: str | None = None
    current_step: str | None = None
    progress_text: str | None = None
    needs_user_action: bool = False
    pending_approvals: list[ApprovalCardSnapshot] = Field(default_factory=list)
    recent_events: list[PublicRunEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallSnapshot] = Field(default_factory=list)
    artifacts: list[ArtifactSnapshot] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
    planner_summary: PlannerTraceSummarySnapshot | None = None
    task_core: TaskCoreSnapshot | None = None
    open_in_studio_url: str | None = None
    created_at: str = ""
    updated_at: str = ""


class AgentTaskLightSnapshot(_PublicSnapshot):
    task_id: str
    conversation_id: str | None = None
    title: str
    status: TaskStatus
    detail: str | None = None
    needs_user_action: bool = False
    pending_approval: ApprovalCardSnapshot | None = None
    open_in_studio_url: str | None = None
    created_at: str = ""
    updated_at: str = ""


class RunTimelineChildSnapshot(_PublicSnapshot):
    run_id: str
    title: str | None = None
    status: str = ""
    kind: str | None = None
    parent_run_id: str | None = None
    group_run_id: str | None = None
    run_group_id: str | None = None
    workflow_run_id: str | None = None
    workflow_node_id: str | None = None
    workflow_node_label: str | None = None
    agent_id: str | None = None
    workflow_id: str | None = None
    planner_summary: PlannerTraceSummarySnapshot | None = None


class RunTimelineSnapshot(_PublicSnapshot):
    run_id: str
    parent_run_id: str | None = None
    group_run_id: str | None = None
    run_group_id: str | None = None
    workflow_run_id: str | None = None
    agent_id: str | None = None
    status: str
    title: str | None = None
    task_id: str | None = None
    session_id: str | None = None
    task_run_link_created_at: str | None = None
    task_run_link_updated_at: str | None = None
    task_run_link_run_status: str | None = None
    task_run_link_last_event_sequence: int | None = None
    rerun_of_run_id: str | None = None
    rerun_of_kind: str | None = None
    rerun_of_status: str | None = None
    rerun_of_runnable_id: str | None = None
    rerun_of_runnable_name: str | None = None
    rerun_original_created_at: str | None = None
    rerun_original_updated_at: str | None = None
    planner_summary: PlannerTraceSummarySnapshot | None = None
    task_core: TaskCoreSnapshot | None = None
    events: list[PublicRunEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallSnapshot] = Field(default_factory=list)
    memory_traces: list[MemoryTraceSnapshot] = Field(default_factory=list)
    skill_traces: list[SkillTraceSnapshot] = Field(default_factory=list)
    approvals: list[ApprovalCardSnapshot] = Field(default_factory=list)
    pending_approval: ApprovalCardSnapshot | None = None
    artifacts: list[ArtifactSnapshot] = Field(default_factory=list)
    children: list[RunTimelineChildSnapshot] = Field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""


class AgentDefinitionSnapshot(_PublicSnapshot):
    agent_id: str
    name: str
    nickname: str | None = None
    description: str | None = None
    instructions: str | None = None
    persona_prompt: str | None = None
    avatar_url: str | None = None
    category: str | None = None
    model_mode: str | None = None
    execution_backend: str | None = None
    model_profile_id: str | None = None
    vision_model_profile_id: str | None = None
    model_settings: dict[str, Any] = Field(
        default_factory=dict,
        alias="model_config",
        serialization_alias="model_config",
    )
    tool_policy: dict[str, Any] = Field(default_factory=dict)
    workspace_policy: dict[str, Any] = Field(default_factory=dict)
    skill_ids: list[str] = Field(default_factory=list)
    output_contract: str | None = None
    enabled: bool = True
    virtual: bool = False
    system: bool = False
    builtin: bool = False
    editable: bool = True
    deletable: bool = True
    created_at: str = ""
    updated_at: str = ""


class AgentDeskItemSnapshot(_PublicSnapshot):
    path: str
    name: str
    kind: Literal["file", "directory", "note"] = "file"
    size_bytes: int | None = None
    mime_type: str | None = None
    preview_text: str | None = None
    updated_at: str = ""


class AgentDeskSnapshot(_PublicSnapshot):
    agent_id: str
    root_path: str
    notes_path: str = "desk-notes.md"
    metadata_path: str = ".yachiyo-desk.json"
    items: list[AgentDeskItemSnapshot] = Field(default_factory=list)
    updated_at: str = ""


class SkillSnapshot(_PublicSnapshot):
    skill_id: str
    name: str
    description: str | None = None
    source_path: str | None = None
    local_path: str | None = None
    folder_id: str | None = None
    folder_name: str | None = None
    source_type: str | None = None
    origin_path: str | None = None
    source_ref: str | None = None
    content_hash: str | None = None
    last_synced_at: str | None = None
    sync_status: str | None = None
    content_summary: str | None = None
    skill_markdown: str | None = None
    asset_paths: list[str] = Field(default_factory=list)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


class SkillFolderSnapshot(_PublicSnapshot):
    folder_id: str
    name: str
    description: str | None = None
    source_scope: Literal["all", "installed", "native"] | str = "all"
    sort_order: int = 0
    skill_count: int = 0
    installed_count: int = 0
    native_count: int = 0
    created_at: str = ""
    updated_at: str = ""


class SkillSourceRootSnapshot(_PublicSnapshot):
    path: str
    source_type: str
    library: str | None = None
    exists: bool = False
    skill_count: int = 0


class MemorySnapshot(_PublicSnapshot):
    memory_id: str
    scope: str
    kind: str
    content: str
    source_session_id: str | None = None
    source_message_id: str | None = None
    source_task_id: str | None = None
    source_run_id: str | None = None
    confidence: float = 0.0
    pinned: bool = False
    user_confirmed: bool = False
    created_at: str = ""
    updated_at: str = ""
    deleted_at: str | None = None


class FutureTaskSnapshot(_PublicSnapshot):
    future_task_id: str
    title: str
    prompt: str
    runnable_id: str | None = None
    runnable_name: str | None = None
    status: str = "scheduled"
    scheduled_at_epoch: float = 0.0
    cron: str | None = None
    source_run_id: str | None = None
    last_run_id: str | None = None
    run_count: int = 0
    error: str | None = None
    created_at: str = ""
    updated_at: str = ""
    cancelled_at: str | None = None


class AgentGroupMemberSnapshot(_PublicSnapshot):
    agent_id: str
    name: str
    role: str | None = None
    sort_order: int = 0
    enabled: bool = True
    run_id: str | None = None
    run_status: str | None = None
    tool_calls: list[ToolCallSnapshot] = Field(default_factory=list)
    pending_approvals: list[ApprovalCardSnapshot] = Field(default_factory=list)
    artifacts: list[ArtifactSnapshot] = Field(default_factory=list)


class AgentGroupSnapshot(_PublicSnapshot):
    group_id: str
    name: str
    description: str | None = None
    members: list[AgentGroupMemberSnapshot] = Field(default_factory=list)
    mode: GroupMode = "moderated"
    moderator_agent_id: str | None = None
    default_model: str | None = None
    memory_scope: MemoryScope = "shared"
    tool_policy_id: str | None = None
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


class GroupRunSnapshot(_PublicSnapshot):
    group_run_id: str
    run_group_id: str | None = None
    group_id: str
    title: str
    status: str
    objective: str
    participants: list[AgentGroupMemberSnapshot] = Field(default_factory=list)
    active_speaker_agent_id: str | None = None
    events: list[PublicRunEvent] = Field(default_factory=list)
    runs: list[RunTimelineSnapshot] = Field(default_factory=list)
    child_run_ids: list[str] = Field(default_factory=list)
    tool_calls: list[ToolCallSnapshot] = Field(default_factory=list)
    memory_traces: list[MemoryTraceSnapshot] = Field(default_factory=list)
    skill_traces: list[SkillTraceSnapshot] = Field(default_factory=list)
    shared_artifacts: list[ArtifactSnapshot] = Field(default_factory=list)
    pending_approvals: list[ApprovalCardSnapshot] = Field(default_factory=list)
    final_answer: str | None = None
    created_at: str = ""
    updated_at: str = ""


class FutureTaskTriggerResultSnapshot(_PublicSnapshot):
    ok: bool = True
    future_task: FutureTaskSnapshot | None = None
    run: RunTimelineSnapshot | None = None
    error: str | None = None


class WorkflowSnapshot(_PublicSnapshot):
    workflow_id: str
    name: str
    description: str | None = None
    nodes: list[dict[str, Any]] = Field(default_factory=list)
    edges: list[dict[str, Any]] = Field(default_factory=list)
    default_input_schema: dict[str, Any] = Field(default_factory=dict)
    enabled: bool = True
    created_at: str = ""
    updated_at: str = ""


class ChatRunnableParticipantSnapshot(_PublicSnapshot):
    runnable_id: str
    agent_id: str | None = None
    workflow_id: str | None = None
    kind: Literal["agent", "workflow"]
    name: str
    nickname: str | None = None
    avatar_url: str | None = None
    category: str | None = None
    enabled: bool = True


class ChatRunnableSnapshot(_PublicSnapshot):
    runnable_id: str
    agent_id: str | None = None
    workflow_id: str | None = None
    kind: Literal["agent", "workflow"]
    name: str
    nickname: str | None = None
    description: str | None = None
    avatar_url: str | None = None
    category: str | None = None
    output_contract: str | None = None
    enabled: bool = True
    tool_capabilities: list[str] = Field(default_factory=list)
    approval_required_tools: list[str] = Field(default_factory=list)
    participants: list[ChatRunnableParticipantSnapshot] = Field(default_factory=list)


class ChatRunnableCatalogSnapshot(_PublicSnapshot):
    agents: list[ChatRunnableSnapshot] = Field(default_factory=list)
    workflows: list[ChatRunnableSnapshot] = Field(default_factory=list)


class WorkflowRunSnapshot(RunTimelineSnapshot):
    workflow_id: str | None = None
    objective: str = ""
    current_node_id: str | None = None
    current_node_label: str | None = None
    final_answer: str | None = None


class PlannerOrchestrationStartSnapshot(_PublicSnapshot):
    kind: Literal["workflow", "group_run"] | str
    status: Literal["started", "handoff", "unsupported", "target_not_found"] | str
    decision: PlannerDecisionSnapshot
    target_id: str | None = None
    target_name: str | None = None
    objective: str = ""
    title: str = ""
    route_to_studio: bool = True
    message: str = ""
    workflow_run: WorkflowRunSnapshot | None = None
    group_run: GroupRunSnapshot | None = None


class StartChatTaskRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str
    conversation_id: str | None = None
    title: str | None = None
    agent_id: str | None = None
    workflow_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ApprovalDecision(BaseModel):
    model_config = ConfigDict(extra="allow")

    approved: bool = True
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class SaveAgentGroupMemberRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_id: str
    role: str | None = None
    sort_order: int = 0
    enabled: bool = True


class SaveAgentRequest(BaseModel):
    model_config = ConfigDict(extra="allow", populate_by_name=True)

    agent_id: str | None = None
    name: str | None = None
    nickname: str | None = None
    description: str | None = None
    instructions: str | None = None
    persona_prompt: str | None = None
    avatar_url: str | None = None
    category: str | None = None
    model_mode: str | None = None
    execution_backend: str | None = None
    model_profile_id: str | None = None
    vision_model_profile_id: str | None = None
    model_settings: dict[str, Any] | None = Field(
        default=None,
        alias="model_config",
        serialization_alias="model_config",
    )
    tool_policy: dict[str, Any] | None = None
    workspace_policy: dict[str, Any] | None = None
    skill_ids: list[str] | None = None
    output_contract: str | None = None
    enabled: bool | None = None


class SaveAgentDeskNoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = ""


class SaveAgentDeskFileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    content: str = ""


class AgentDeskFileEventRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str
    event_type: Literal["created", "modified", "deleted", "changed"] = "changed"
    delay_seconds: int | float | None = 0


class SaveAgentGroupRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    group_id: str | None = None
    name: str | None = None
    description: str | None = None
    members: list[SaveAgentGroupMemberRequest] | None = None
    participant_ids: list[str] | None = None
    agent_ids: list[str] | None = None
    mode: GroupMode | None = None
    moderator_agent_id: str | None = None
    default_model: str | None = None
    memory_scope: MemoryScope | None = None
    tool_policy_id: str | None = None
    enabled: bool | None = None


class StartGroupRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    group_id: str
    objective: str
    title: str | None = None
    client_run_id: str | None = None


class StartAgentRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    agent_id: str
    objective: str
    title: str | None = None
    client_run_id: str | None = None


class SaveWorkflowRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    workflow_id: str | None = None
    name: str | None = None
    description: str | None = None
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    default_input_schema: dict[str, Any] | None = None
    enabled: bool | None = None


class StartWorkflowRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    workflow_id: str
    objective: str
    title: str | None = None
    client_run_id: str | None = None


class StartPlannerOrchestrationRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str
    objective: str | None = None
    title: str | None = None
    target_id: str | None = None
    target_name: str | None = None
    allowed_tools: list[str] | None = None
    client_run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RerunRunRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    scope: Literal["run", "workflow_node", "workflow_branch"] | str = "run"
    workflow_node_id: str | None = None
    workflow_node_label: str | None = None
    workflow_edge_branch: str | None = None
    workflow_node_selected_target: str | None = None
    reason: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
