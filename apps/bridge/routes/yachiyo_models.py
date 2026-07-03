"""Yachiyo route request models."""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class TaskApprovalRequest(BaseModel):
    model_config = ConfigDict(extra="allow")

    approval_id: str | None = Field(default=None, max_length=160)
    reason: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class StartGroupRunBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    objective: str = Field(..., min_length=1, max_length=60000)
    title: str | None = Field(default=None, max_length=1000)
    client_run_id: str | None = Field(default=None, max_length=160)


class StartAgentRunBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    objective: str = Field(..., min_length=1, max_length=60000)
    title: str | None = Field(default=None, max_length=1000)
    client_run_id: str | None = Field(default=None, max_length=160)


class AgentSkillBody(BaseModel):
    skill_id: str = Field(..., min_length=1, max_length=160)


class SkillUpdateBody(BaseModel):
    enabled: bool | None = None
    folder_id: str | None = Field(default=None, max_length=160)


class SkillFolderBody(BaseModel):
    folder_id: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    source_scope: str | None = Field(default=None, max_length=40)
    sort_order: int | None = None


class SkillImportBody(BaseModel):
    source_path: str = Field(..., min_length=1, max_length=4000)
    folder_id: str | None = Field(default=None, max_length=160)


class SkillInstallBody(BaseModel):
    command: str = Field(..., min_length=1, max_length=4000)
    folder_id: str | None = Field(default=None, max_length=160)


class RestrictedToolPluginInstallBody(BaseModel):
    plugin_id: str = Field(..., min_length=1, max_length=160)
    enabled: bool = True


class RestrictedToolPluginUpdateBody(BaseModel):
    enabled: bool | None = None


class PlanTaskBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    prompt: str = Field(..., min_length=1, max_length=60000)
    allowed_tools: list[str] | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PlanExecutionBody(PlanTaskBody):
    direct: bool = False


class StartPlannerOrchestrationBody(PlanTaskBody):
    objective: str | None = Field(default=None, max_length=60000)
    title: str | None = Field(default=None, max_length=1000)
    target_id: str | None = Field(default=None, max_length=160)
    target_name: str | None = Field(default=None, max_length=1000)
    client_run_id: str | None = Field(default=None, max_length=160)


class MemoryBody(BaseModel):
    content: str | None = Field(default=None, max_length=60000)
    old_content: str | None = Field(default=None, max_length=60000)
    kind: str | None = Field(default=None, max_length=40)
    scope: str | None = Field(default=None, max_length=40)
    reason: str | None = Field(default=None, max_length=2000)


class FutureTaskCancelBody(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class FutureTaskTriggerBody(BaseModel):
    now_epoch: float | None = None
    limit: int | None = Field(default=None, ge=1, le=200)


class StartWorkflowRunBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    objective: str = Field(..., min_length=1, max_length=60000)
    title: str | None = Field(default=None, max_length=1000)
    client_run_id: str | None = Field(default=None, max_length=160)


class RerunRunBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    scope: str | None = Field(default=None, max_length=40)
    workflow_node_id: str | None = Field(default=None, max_length=240)
    workflow_node_label: str | None = Field(default=None, max_length=1000)
    workflow_edge_branch: str | None = Field(default=None, max_length=160)
    workflow_node_selected_target: str | None = Field(default=None, max_length=240)
    reason: str | None = Field(default=None, max_length=2000)
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunReplanRecoveryActionBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    request_id: str = Field(..., min_length=1, max_length=240)
    action_id: str | None = Field(default=None, max_length=240)
    agent_id: str | None = Field(default=None, max_length=160)
    title: str | None = Field(default=None, max_length=1000)
    client_run_id: str | None = Field(default=None, max_length=160)
    continue_to_model: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)
