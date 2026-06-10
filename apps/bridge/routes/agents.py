"""Agent Studio, Skill Library, Workflow Studio, and run routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

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
    reason: str | None = Field(default=None, max_length=2000)


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
    return HTTPException(status_code=400, detail=redact_api_error_detail(exc))


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
async def list_agents() -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().list_agents)


@router.post("/agents")
async def create_agent(request: AgentRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().create_agent, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/agents/{agent_id}")
async def get_agent(agent_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().get_agent, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@router.patch("/agents/{agent_id}")
async def update_agent(agent_id: str, request: AgentRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().update_agent, agent_id, _payload(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/agents/{agent_id}")
async def delete_agent(agent_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().delete_agent, agent_id)


@router.post("/agents/{agent_id}/test-model")
async def test_agent_model(agent_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().test_agent_model, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/agents/{agent_id}/skills")
async def attach_agent_skill(agent_id: str, request: AgentSkillRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().attach_skill, agent_id, request.skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 或 Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/agents/{agent_id}/skills/{skill_id}")
async def detach_agent_skill(agent_id: str, skill_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().detach_skill, agent_id, skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@router.get("/skills")
async def list_skills() -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().list_skills)


@router.post("/skills")
async def import_skill_from_post(request: SkillImportRequest) -> dict[str, Any]:
    return await import_skill(request)


@router.post("/skills/import")
async def import_skill(request: SkillImportRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().import_skill, request.source_path, request.folder_id)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/skills/sources")
async def list_skill_sources() -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().list_native_skill_sources)


@router.get("/skill-folders")
async def list_skill_folders() -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().list_skill_folders)


@router.post("/skill-folders")
async def create_skill_folder(request: SkillFolderRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().create_skill_folder, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.patch("/skill-folders/{folder_id}")
async def update_skill_folder(folder_id: str, request: SkillFolderRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().update_skill_folder, folder_id, _payload(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/skill-folders/{folder_id}")
async def delete_skill_folder(folder_id: str, delete_skills: bool = False) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            get_agent_runtime_service().delete_skill_folder,
            folder_id,
            delete_skills=delete_skills,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc


@router.post("/skills/sync")
async def sync_native_skills() -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().sync_native_skills)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/skills/install")
async def install_skill(request: SkillInstallRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().install_skill_command, request.command, request.folder_id)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/skills/{skill_id}")
async def get_skill(skill_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().get_skill, skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


@router.patch("/skills/{skill_id}")
async def update_skill(skill_id: str, request: SkillUpdateRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().update_skill, skill_id, _payload(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/skills/{skill_id}")
async def delete_skill(skill_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().delete_skill, skill_id)


@router.get("/workflows")
async def list_workflows() -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().list_workflows)


@router.post("/workflows")
async def create_workflow(request: WorkflowRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().create_workflow, _payload(request))
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/workflows/{workflow_id}")
async def get_workflow(workflow_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().get_workflow, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc


@router.patch("/workflows/{workflow_id}")
async def update_workflow(workflow_id: str, request: WorkflowRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_agent_runtime_service().update_workflow, workflow_id, _payload(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/workflows/{workflow_id}")
async def delete_workflow(workflow_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().delete_workflow, workflow_id)


@router.get("/runnables")
async def list_runnables() -> dict[str, Any]:
    return await asyncio.to_thread(get_agent_runtime_service().list_runnables)


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
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_agent_runtime_service(http_request).approve_run_approval, run_id)
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
    try:
        reason = request.reason if request is not None else ""
        return await asyncio.to_thread(
            _agent_runtime_service(http_request).reject_run_approval,
            run_id,
            reason or "",
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc
