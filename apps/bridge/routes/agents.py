"""Agent Studio, Skill Library, Workflow Studio, and run routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.shell.agent.runtime.memory_services import issue_user_memory_consent_capability
from apps.shell.agent_runtime import AgentRuntimeError, get_agent_runtime_service
from packages.security import redact_api_error_detail

router = APIRouter(prefix="/ui", tags=["Agent Studio"])


class AgentRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    agent_id: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=160)
    nickname: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    avatar_url: str | None = Field(default=None, max_length=2_000_000)
    category: str | None = Field(default=None, max_length=80)
    instructions: str | None = Field(default=None, max_length=60000)
    persona_prompt: str | None = Field(default=None, max_length=60000)
    model_mode: str | None = Field(default=None, max_length=40)
    execution_backend: str | None = Field(default=None, max_length=40)
    model_profile_id: str | None = Field(default=None, max_length=160)
    vision_model_profile_id: str | None = Field(default=None, max_length=160)
    model_config_data: dict[str, Any] | None = Field(default=None, alias="model_config")
    tool_policy: dict[str, Any] | None = None
    workspace_policy: dict[str, Any] | None = None
    skill_ids: list[str] | None = None
    output_contract: str | None = Field(default=None, max_length=80)
    enabled: bool | None = None


class SkillImportRequest(BaseModel):
    source_path: str = Field(..., min_length=1, max_length=4000)
    folder_id: str | None = Field(default=None, max_length=160)


class SkillInstallRequest(BaseModel):
    command: str = Field(..., min_length=1, max_length=4000)
    folder_id: str | None = Field(default=None, max_length=160)


class SkillUpdateRequest(BaseModel):
    enabled: bool | None = None
    folder_id: str | None = Field(default=None, max_length=160)


class SkillFolderRequest(BaseModel):
    folder_id: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=1000)
    source_scope: str | None = Field(default=None, max_length=40)
    sort_order: int | None = None


class AgentSkillRequest(BaseModel):
    skill_id: str = Field(..., min_length=1, max_length=160)


class WorkflowRequest(BaseModel):
    workflow_id: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=160)
    description: str | None = Field(default=None, max_length=2000)
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None
    default_input_schema: dict[str, Any] | None = None
    enabled: bool | None = None


class AgentRunRequest(BaseModel):
    agent_id: str | None = Field(default=None, max_length=160)
    runnable_id: str | None = Field(default=None, max_length=160)
    run_group_id: str | None = Field(default=None, max_length=160)
    client_run_id: str | None = Field(default=None, max_length=160)
    source: str | None = Field(default=None, max_length=80)
    user_goal: str | None = Field(default=None, max_length=60000)
    goal: str | None = Field(default=None, max_length=60000)


class WorkflowRunRequest(BaseModel):
    workflow_id: str | None = Field(default=None, max_length=160)
    runnable_id: str | None = Field(default=None, max_length=160)
    run_group_id: str | None = Field(default=None, max_length=160)
    client_run_id: str | None = Field(default=None, max_length=160)
    source: str | None = Field(default=None, max_length=80)
    user_goal: str | None = Field(default=None, max_length=60000)
    goal: str | None = Field(default=None, max_length=60000)


class ApprovalRejectRequest(BaseModel):
    approval_id: str | None = Field(default=None, max_length=160)
    reason: str | None = Field(default=None, max_length=2000)


class MemoryRequest(BaseModel):
    content: str | None = Field(default=None, max_length=60000)
    old_content: str | None = Field(default=None, max_length=60000)
    kind: str | None = Field(default=None, max_length=40)
    scope: str | None = Field(default=None, max_length=40)
    reason: str | None = Field(default=None, max_length=2000)
    project_id: str | None = Field(default=None, max_length=160)
    source_session_id: str | None = Field(default=None, max_length=160)
    source_message_id: str | None = Field(default=None, max_length=160)
    source_task_id: str | None = Field(default=None, max_length=160)
    enabled: bool | None = None
    user_confirmed: bool | None = None
    consent_receipt: dict[str, str] | None = None


class FutureTaskRequest(BaseModel):
    title: str | None = Field(default=None, max_length=1000)
    prompt: str | None = Field(default=None, max_length=60000)
    runnable_id: str | None = Field(default=None, max_length=160)
    runnable_name: str | None = Field(default=None, max_length=160)
    delay_seconds: float | None = None
    scheduled_at_epoch: float | None = None
    cron: str | None = Field(default=None, max_length=80)


class FutureTaskCancelRequest(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class FutureTaskTriggerRequest(BaseModel):
    now_epoch: float | None = None
    limit: int | None = Field(default=20, ge=1, le=100)


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True, exclude_none=True, by_alias=True)


def _payload_with_idempotency(model: BaseModel, request: Request | None) -> dict[str, Any]:
    payload = _payload(model)
    headers = getattr(request, "headers", None)
    if not payload.get("client_run_id") and headers is not None:
        key = str(headers.get("idempotency-key", "") or "").strip()
        if key:
            payload["client_run_id"] = key
    return payload


def _bad_request(exc: Exception) -> HTTPException:
    detail = redact_api_error_detail(exc)
    status_code = 409 if _approval_generation_conflict(detail) else 400
    return HTTPException(status_code=status_code, detail=detail)


def _approval_generation_conflict(detail: Any) -> bool:
    text = str(detail or "")
    return any(
        marker in text
        for marker in (
            "approval_generation_mismatch",
            "approval_generation_projection_missing",
            "approval_generation_conflict",
        )
    )


def _agent_runtime_service(request: Request | None = None) -> Any:
    state = getattr(getattr(request, "app", None), "state", None)
    runtime = getattr(state, "runtime", None)
    if runtime is not None:
        service = getattr(runtime, "agent_runtime_service", None)
        if service is not None:
            return service
        getter = getattr(runtime, "get_agent_runtime_service", None)
        if callable(getter):
            service = getter()
            if service is not None:
                return service
    return get_agent_runtime_service()


@router.get("/agents")
async def list_agents(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_agents)


@router.post("/agents")
async def create_agent(
    request: AgentRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).create_agent, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).get_agent, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@router.patch("/agents/{agent_id}")
async def update_agent(
    agent_id: str,
    request: AgentRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).update_agent,
            agent_id,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).delete_agent, agent_id)


@router.post("/agents/{agent_id}/test-model")
async def test_agent_model(agent_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).test_agent_model, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/agents/{agent_id}/skills")
async def attach_agent_skill(
    agent_id: str,
    request: AgentSkillRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).attach_skill,
            agent_id,
            request.skill_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 或 Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/agents/{agent_id}/skills/{skill_id}")
async def detach_agent_skill(
    agent_id: str,
    skill_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).detach_skill,
            agent_id,
            skill_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@router.get("/skills")
async def list_skills(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_skills)


@router.post("/skills")
async def import_skill_from_post(
    request: SkillImportRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    return await import_skill(request, http_request)


@router.post("/skills/import")
async def import_skill(
    request: SkillImportRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).import_skill,
            request.source_path,
            request.folder_id,
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/skills/sources")
async def list_skill_sources(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_native_skill_sources)


@router.get("/skill-folders")
async def list_skill_folders(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_skill_folders)


@router.post("/skill-folders")
async def create_skill_folder(
    request: SkillFolderRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).create_skill_folder, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.patch("/skill-folders/{folder_id}")
async def update_skill_folder(
    folder_id: str,
    request: SkillFolderRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).update_skill_folder,
            folder_id,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/skill-folders/{folder_id}")
async def delete_skill_folder(
    folder_id: str,
    delete_skills: bool = False,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).delete_skill_folder,
            folder_id,
            delete_skills=delete_skills,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc


@router.post("/skills/sync")
async def sync_native_skills(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).sync_native_skills)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/skills/install")
async def install_skill(
    request: SkillInstallRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).install_skill_command,
            request.command,
            request.folder_id,
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).get_skill, skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


@router.patch("/skills/{skill_id}")
async def update_skill(
    skill_id: str,
    request: SkillUpdateRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).update_skill,
            skill_id,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).delete_skill, skill_id)


@router.get("/workflows")
async def list_workflows(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_workflows)


@router.post("/workflows")
async def create_workflow(
    request: WorkflowRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).create_workflow, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).get_workflow, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc


@router.patch("/workflows/{workflow_id}")
async def update_workflow(
    workflow_id: str,
    request: WorkflowRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).update_workflow,
            workflow_id,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(
    workflow_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    return await asyncio.to_thread(_agent_runtime_service(http_request).delete_workflow, workflow_id)


@router.get("/runnables")
async def list_runnables(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_runnables)


@router.get("/memories")
async def list_memories(
    include_deleted: bool = False,
    limit: int = 100,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _agent_runtime_service(http_request).list_memory_items,
        include_deleted=include_deleted,
        limit=limit,
    )


@router.post("/memories")
async def create_memory(
    request: MemoryRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).create_memory_item, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.patch("/memories/{memory_id}")
async def update_memory(
    memory_id: str,
    request: MemoryRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).update_memory_item,
            memory_id,
            _payload(request),
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/memories/{memory_id}/consent-capability")
async def issue_memory_consent_capability(
    memory_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        service = _agent_runtime_service(http_request)
        return await asyncio.to_thread(
            issue_user_memory_consent_capability,
            service.memory_services,
            memory_id,
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/memories/{memory_id}")
async def delete_memory(
    memory_id: str,
    reason: str = "",
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).delete_memory_item,
            memory_id,
            reason=reason,
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/future-tasks")
async def list_future_tasks(
    include_finished: bool = True,
    limit: int = 100,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    return await asyncio.to_thread(
        _agent_runtime_service(http_request).list_future_tasks,
        include_finished=include_finished,
        limit=limit,
    )


@router.post("/future-tasks")
async def schedule_future_task(
    request: FutureTaskRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).schedule_future_task, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/future-tasks/trigger-due")
async def trigger_due_future_tasks(
    request: FutureTaskTriggerRequest | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    payload = _payload(request) if request is not None else {}
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).trigger_due_future_tasks,
            now_epoch=payload.get("now_epoch"),
            limit=payload.get("limit") or 20,
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/future-tasks/{future_task_id}/cancel")
async def cancel_future_task(
    future_task_id: str,
    request: FutureTaskCancelRequest | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).cancel_future_task,
            future_task_id,
            reason=(request.reason if request is not None else "") or "",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="FutureTask 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/runs")
async def list_runs(limit: int = 50, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_runs, limit)


@router.get("/run-groups")
async def list_run_groups(limit: int = 50, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await asyncio.to_thread(_agent_runtime_service(http_request).list_run_groups, limit)


@router.get("/run-groups/{run_group_id}")
async def get_run_group(
    run_group_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).get_run_group, run_group_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="RunGroup 不存在") from exc


@router.get("/runs/{run_id}")
async def get_any_run(run_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await get_run(run_id, http_request)


@router.delete("/runs/{run_id}")
async def delete_run(run_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).delete_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/runs/{run_id}/artifacts/{artifact_path:path}")
async def get_run_artifact(
    run_id: str,
    artifact_path: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).read_run_artifact,
            run_id,
            artifact_path,
        )
    except (AgentRuntimeError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Artifact 不存在") from exc


@router.post("/agent-runs")
async def create_agent_run(
    request: AgentRunRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    if str(request.run_group_id or "").strip():
        raise HTTPException(status_code=400, detail="public_run_group_attachment_forbidden")
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).create_agent_run,
            _payload_with_idempotency(request, http_request),
        )
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.get("/agent-runs/{run_id}")
async def get_agent_run(run_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await get_run(run_id, http_request)


@router.post("/workflow-runs")
async def create_workflow_run(
    request: WorkflowRunRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    if str(request.run_group_id or "").strip():
        raise HTTPException(status_code=400, detail="public_run_group_attachment_forbidden")
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).create_workflow_run,
            _payload_with_idempotency(request, http_request),
        )
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.get("/workflow-runs/{run_id}")
async def get_workflow_run(run_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return await get_run(run_id, http_request)


async def get_run(run_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).get_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


@router.post("/runs/{run_id}/rerun")
async def rerun_run(run_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).rerun_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/runs/{run_id}/cancel")
async def cancel_run(run_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).cancel_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


@router.post("/runs/{run_id}/approval/approve")
async def approve_run_approval(
    run_id: str,
    request: ApprovalRejectRequest | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    approval_id = str(
        (request.approval_id if request is not None else "") or ""
    ).strip()
    if not approval_id:
        raise HTTPException(status_code=400, detail="approval_expected_id_required")
    try:
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).approve_run_approval,
            run_id,
            approval_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/runs/{run_id}/approval/reject")
async def reject_run_approval(
    run_id: str,
    request: ApprovalRejectRequest | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    approval_id = str(
        (request.approval_id if request is not None else "") or ""
    ).strip()
    if not approval_id:
        raise HTTPException(status_code=400, detail="approval_expected_id_required")
    try:
        reason = request.reason if request is not None else ""
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).reject_run_approval,
            run_id,
            reason or "",
            approval_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc
