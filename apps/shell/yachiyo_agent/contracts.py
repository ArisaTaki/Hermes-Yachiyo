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
    title: str
    kind: str
    path: str | None = None
    mime_type: str | None = None
    size_bytes: int | None = None
    preview_text: str | None = None
    url: str | None = None
    created_at: str = ""


class ToolCallSnapshot(_PublicSnapshot):
    tool_call_id: str
    run_id: str | None = None
    tool_name: str
    status: str
    risk_level: str | None = None
    input_preview: dict[str, Any] = Field(default_factory=dict)
    output_preview: dict[str, Any] = Field(default_factory=dict)
    approval_id: str | None = None
    started_at: str = ""
    completed_at: str | None = None


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
    artifacts: list[ArtifactSnapshot] = Field(default_factory=list)
    open_in_studio_url: str | None = None
    created_at: str = ""
    updated_at: str = ""


class RunTimelineChildSnapshot(_PublicSnapshot):
    run_id: str
    title: str | None = None
    status: str = ""
    kind: str | None = None
    agent_id: str | None = None
    workflow_id: str | None = None


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
    events: list[PublicRunEvent] = Field(default_factory=list)
    tool_calls: list[ToolCallSnapshot] = Field(default_factory=list)
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


class StartChatTaskRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str
    conversation_id: str | None = None
    title: str | None = None
    agent_id: str | None = None
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
