"""Yachiyo public Agent facade routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field

from apps.bridge.deps import get_runtime
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.chat_api import ChatAPI
from apps.shell.yachiyo_agent import (
    AgentStudioService,
    ApprovalDecision,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    StartAgentRunRequest,
    StartChatTaskRequest,
    StartGroupRunRequest,
    StartWorkflowRunRequest,
    YachiyoAgentService,
)
from apps.shell.yachiyo_agent.legacy_ports import LegacyRuntimePort, LegacyStudioPort
from packages.security import redact_api_error_detail

router = APIRouter(prefix="/yachiyo", tags=["Yachiyo Agent"])


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


class StartWorkflowRunBody(BaseModel):
    model_config = ConfigDict(extra="allow")

    objective: str = Field(..., min_length=1, max_length=60000)
    title: str | None = Field(default=None, max_length=1000)
    client_run_id: str | None = Field(default=None, max_length=160)


def _app_runtime_from_request(request: Request | None = None) -> Any:
    state = getattr(getattr(request, "app", None), "state", None)
    app_runtime = getattr(state, "runtime", None)
    if app_runtime is None:
        try:
            app_runtime = get_runtime()
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail="Yachiyo runtime unavailable") from exc
    return app_runtime


def _runtime_from_request(request: Request | None = None) -> Any:
    app_runtime = _app_runtime_from_request(request)
    service = getattr(app_runtime, "agent_runtime_service", None)
    if service is not None:
        return service
    getter = getattr(app_runtime, "get_agent_runtime_service", None)
    if callable(getter):
        service = getter()
        if service is not None:
            return service
    raise HTTPException(status_code=503, detail="Yachiyo agent runtime unavailable")


def _agent_service(request: Request | None = None) -> YachiyoAgentService:
    return YachiyoAgentService(LegacyRuntimePort(_runtime_from_request(request)))


def _studio_service(request: Request | None = None) -> AgentStudioService:
    return AgentStudioService(LegacyStudioPort(_runtime_from_request(request)))


def _snapshot(model: Any) -> dict[str, Any]:
    return model.model_dump(mode="json")


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=redact_api_error_detail(exc))


def _start_chat_backed_task(
    request: StartChatTaskRequest,
    http_request: Request | None = None,
) -> dict[str, Any] | None:
    agent_id = str(request.agent_id or "").strip()
    if not agent_id:
        return None
    app_runtime = _app_runtime_from_request(http_request)
    if getattr(app_runtime, "chat_session", None) is None:
        return None

    metadata = request.metadata if isinstance(request.metadata, dict) else {}
    client_message_id = str(
        metadata.get("client_message_id")
        or metadata.get("idempotency_key")
        or metadata.get("client_task_id")
        or ""
    ).strip()
    chat_api = ChatAPI(app_runtime)
    result = chat_api.send_runnable_message_in_session(
        request.conversation_id or "",
        request.prompt,
        runnable_id=agent_id,
        client_message_id=client_message_id,
    )
    if result.get("ok") is False:
        raise AgentRuntimeError(str(result.get("error") or "发送 Agent 任务失败"))

    run_id = str(
        result.get("run_id")
        or result.get("agent_run_id")
        or result.get("workflow_run_id")
        or ""
    ).strip()
    if not run_id:
        return None

    conversation_id = str(
        result.get("session_id")
        or request.conversation_id
        or getattr(getattr(app_runtime, "chat_session", None), "session_id", "")
        or ""
    ).strip()
    task_id = str(
        metadata.get("task_id")
        or metadata.get("client_task_id")
        or run_id
    ).strip()
    link_task_run = getattr(_runtime_from_request(http_request), "link_task_run", None)
    if callable(link_task_run):
        link_task_run(task_id=task_id, run_id=run_id, session_id=conversation_id)
    return _snapshot(_agent_service(http_request).get_task_snapshot(task_id or run_id))


@router.get("/readiness")
@router.get("/chat/readiness")
async def readiness(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    return _snapshot(await asyncio.to_thread(_agent_service(http_request).readiness))


@router.get("/tasks")
@router.get("/chat/tasks")
async def list_tasks(
    conversation_id: str | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    tasks = await asyncio.to_thread(
        _agent_service(http_request).list_recent_tasks,
        conversation_id,
    )
    return {"tasks": [_snapshot(task) for task in tasks]}


@router.post("/tasks")
@router.post("/chat/tasks")
async def start_task(
    request: StartChatTaskRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        chat_snapshot = await asyncio.to_thread(_start_chat_backed_task, request, http_request)
        if chat_snapshot is not None:
            return chat_snapshot
        snapshot = await asyncio.to_thread(_agent_service(http_request).start_chat_task, request)
        return _snapshot(snapshot)
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise _bad_request(exc) from exc


@router.get("/tasks/{task_id}")
@router.get("/chat/tasks/{task_id}")
async def get_task(task_id: str, http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        snapshot = await asyncio.to_thread(_agent_service(http_request).get_task_snapshot, task_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


@router.post("/tasks/{task_id}/approve")
@router.post("/chat/tasks/{task_id}/approve")
async def approve_task(
    task_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    approval_id = (request.approval_id if request is not None else None) or task_id
    decision = ApprovalDecision(
        approved=True,
        reason=request.reason if request is not None else None,
        metadata=request.metadata if request is not None else {},
    )
    try:
        snapshot = await asyncio.to_thread(
            _agent_service(http_request).approve,
            approval_id,
            decision,
        )
        return _snapshot(snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.post("/tasks/{task_id}/reject")
@router.post("/chat/tasks/{task_id}/reject")
async def reject_task(
    task_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    approval_id = (request.approval_id if request is not None else None) or task_id
    try:
        snapshot = await asyncio.to_thread(
            _agent_service(http_request).reject,
            approval_id,
            request.reason if request is not None else "",
        )
        return _snapshot(snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.post("/tasks/{task_id}/cancel")
@router.post("/chat/tasks/{task_id}/cancel")
async def cancel_task(
    task_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_agent_service(http_request).cancel, task_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


@router.get("/studio/agents")
async def list_studio_agents(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    agents = await asyncio.to_thread(_studio_service(http_request).list_agents)
    return {"agents": [_snapshot(agent) for agent in agents]}


@router.post("/studio/agents")
async def save_studio_agent(
    request: SaveAgentRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).save_agent, request)
        return _snapshot(snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/agents/{agent_id}")
async def get_studio_agent(
    agent_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).get_agent, agent_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@router.delete("/studio/agents/{agent_id}")
async def delete_studio_agent(
    agent_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_studio_service(http_request).delete_agent, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/agents/{agent_id}/test-model")
async def test_studio_agent_model(
    agent_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_studio_service(http_request).test_agent_model, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/agents/{agent_id}/skills")
async def attach_studio_agent_skill(
    agent_id: str,
    request: AgentSkillBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).attach_skill,
            agent_id,
            request.skill_id,
        )
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 或 Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/studio/agents/{agent_id}/skills/{skill_id}")
async def detach_studio_agent_skill(
    agent_id: str,
    skill_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).detach_skill,
            agent_id,
            skill_id,
        )
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


@router.get("/studio/skills")
async def list_studio_skills(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    skills = await asyncio.to_thread(_studio_service(http_request).list_skills)
    return {"skills": [_snapshot(skill) for skill in skills]}


@router.patch("/studio/skills/{skill_id}")
async def update_studio_skill(
    skill_id: str,
    request: SkillUpdateBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).update_skill,
            skill_id,
            payload,
        )
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/studio/skills/{skill_id}")
async def delete_studio_skill(
    skill_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_studio_service(http_request).delete_skill, skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


@router.post("/studio/agents/{agent_id}/runs")
async def start_studio_agent_run(
    agent_id: str,
    request: StartAgentRunBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        run_request = StartAgentRunRequest(
            agent_id=agent_id,
            objective=request.objective,
            title=request.title,
            client_run_id=request.client_run_id,
        )
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).start_agent_run,
            run_request,
        )
        return _snapshot(snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/groups")
async def list_studio_groups(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    groups = await asyncio.to_thread(_studio_service(http_request).list_groups)
    return {"groups": [_snapshot(group) for group in groups]}


@router.post("/studio/groups")
async def save_studio_group(
    request: SaveAgentGroupRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).save_group, request)
        return _snapshot(snapshot)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/groups/{group_id}")
async def get_studio_group(
    group_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).get_group, group_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AgentGroup 不存在") from exc


@router.post("/studio/groups/{group_id}/runs")
async def start_studio_group_run(
    group_id: str,
    request: StartGroupRunBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        run_request = StartGroupRunRequest(
            group_id=group_id,
            objective=request.objective,
            title=request.title,
            client_run_id=request.client_run_id,
        )
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).start_group_run,
            run_request,
        )
        return _snapshot(snapshot)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/group-runs")
async def list_studio_group_runs(
    http_request: Request = None,  # type: ignore[assignment]
    limit: int = 50,
) -> dict[str, Any]:
    group_runs = await asyncio.to_thread(
        _studio_service(http_request).list_group_runs,
        max(1, min(200, int(limit or 50))),
    )
    return {"group_runs": [_snapshot(group_run) for group_run in group_runs]}


@router.get("/studio/group-runs/{group_run_id}")
async def get_studio_group_run(
    group_run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).get_group_run,
            group_run_id,
        )
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="GroupRun 不存在") from exc


@router.get("/studio/workflows")
async def list_studio_workflows(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    workflows = await asyncio.to_thread(_studio_service(http_request).list_workflows)
    return {"workflows": [_snapshot(workflow) for workflow in workflows]}


@router.post("/studio/workflows")
async def save_studio_workflow(
    request: SaveWorkflowRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).save_workflow, request)
        return _snapshot(snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/workflows/{workflow_id}")
async def get_studio_workflow(
    workflow_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).get_workflow, workflow_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc


@router.delete("/studio/workflows/{workflow_id}")
async def delete_studio_workflow(
    workflow_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_studio_service(http_request).delete_workflow, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/workflows/{workflow_id}/runs")
async def start_studio_workflow_run(
    workflow_id: str,
    request: StartWorkflowRunBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        run_request = StartWorkflowRunRequest(
            workflow_id=workflow_id,
            objective=request.objective,
            title=request.title,
            client_run_id=request.client_run_id,
        )
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).start_workflow_run,
            run_request,
        )
        return _snapshot(snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/runs/{run_id}/timeline")
async def get_studio_run_timeline(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).get_run_timeline, run_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


@router.get("/studio/runs")
async def list_studio_runs(
    http_request: Request = None,  # type: ignore[assignment]
    limit: int = 50,
) -> dict[str, Any]:
    runs = await asyncio.to_thread(
        _studio_service(http_request).list_run_timelines,
        max(1, min(200, int(limit or 50))),
    )
    return {"runs": [_snapshot(run) for run in runs]}


@router.get("/studio/runs/{run_id}")
async def get_studio_run(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).get_run_timeline, run_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


@router.post("/studio/runs/{run_id}/rerun")
async def rerun_studio_run(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).rerun_run, run_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/runs/{run_id}/cancel")
async def cancel_studio_run(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).cancel_run, run_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


@router.delete("/studio/runs/{run_id}")
async def delete_studio_run(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(_studio_service(http_request).delete_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/runs/{run_id}/approval/approve")
async def approve_studio_run_approval(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(_studio_service(http_request).approve_run_approval, run_id)
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/runs/{run_id}/approval/reject")
async def reject_studio_run_approval(
    run_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).reject_run_approval,
            run_id,
            request.reason if request is not None else "",
        )
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/runs/{run_id}/artifacts/{artifact_path:path}")
async def get_studio_run_artifact(
    run_id: str,
    artifact_path: str,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _studio_service(http_request).read_run_artifact,
            run_id,
            artifact_path,
        )
    except (AgentRuntimeError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Artifact 不存在") from exc


@router.get("/studio/runs/{run_id}/events")
async def get_studio_run_events(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
    after_sequence: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    try:
        events = await asyncio.to_thread(
            lambda: list(_studio_service(http_request).get_run_event_stream(run_id))
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    clean_after_sequence = max(0, int(after_sequence or 0))
    clean_limit = max(1, min(500, int(limit or 200)))
    page = [
        event
        for event in events
        if int(getattr(event, "sequence", 0) or 0) > clean_after_sequence
    ][:clean_limit]
    return {
        "run_id": run_id,
        "after_sequence": clean_after_sequence,
        "limit": clean_limit,
        "events": [_snapshot(event) for event in page],
    }
