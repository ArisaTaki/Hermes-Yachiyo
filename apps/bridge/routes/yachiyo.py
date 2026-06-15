"""Yachiyo public Agent facade routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from apps.bridge.routes.yachiyo_models import (
    AgentSkillBody,
    FutureTaskCancelBody,
    FutureTaskTriggerBody,
    MemoryBody,
    SkillFolderBody,
    SkillImportBody,
    SkillInstallBody,
    SkillUpdateBody,
    StartAgentRunBody,
    StartGroupRunBody,
    StartWorkflowRunBody,
    TaskApprovalRequest,
)
from apps.bridge.routes.yachiyo_services import (
    agent_service as _agent_service,
    bad_request as _bad_request,
    snapshot as _snapshot,
    studio_service as _studio_service,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import (
    ApprovalDecision,
    SaveAgentGroupRequest,
    SaveAgentRequest,
    SaveWorkflowRequest,
    StartAgentRunRequest,
    StartChatTaskRequest,
    StartGroupRunRequest,
    StartWorkflowRunRequest,
)

router = APIRouter(prefix="/yachiyo", tags=["Yachiyo Agent"])


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
    metadata = dict(request.metadata) if request is not None else {}
    if request is not None and request.approval_id:
        metadata.setdefault("approval_id", request.approval_id)
    decision = ApprovalDecision(
        approved=True,
        reason=request.reason if request is not None else None,
        metadata=metadata,
    )
    try:
        snapshot = await asyncio.to_thread(
            _agent_service(http_request).approve,
            task_id,
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
    try:
        snapshot = await asyncio.to_thread(
            _agent_service(http_request).reject,
            task_id,
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


@router.get("/studio/skills/sources")
async def list_studio_skill_sources(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    roots = await asyncio.to_thread(_studio_service(http_request).list_skill_sources)
    return {"roots": [_snapshot(root) for root in roots]}


@router.post("/studio/skills/import")
async def import_studio_skill(
    request: SkillImportBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).import_skill,
            request.source_path,
            request.folder_id,
        )
        return _snapshot(snapshot)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/skills/sync")
async def sync_studio_native_skills(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    try:
        return await asyncio.to_thread(_studio_service(http_request).sync_native_skills)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/skills/install")
async def install_studio_skill(
    request: SkillInstallBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _studio_service(http_request).install_skill_command,
            request.command,
            request.folder_id,
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


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


@router.get("/studio/skill-folders")
async def list_studio_skill_folders(http_request: Request = None) -> dict[str, Any]:  # type: ignore[assignment]
    payload = await asyncio.to_thread(_studio_service(http_request).list_skill_folders)
    uncategorized = payload.get("uncategorized")
    return {
        "folders": [_snapshot(folder) for folder in payload.get("folders") or []],
        "uncategorized": _snapshot(uncategorized) if uncategorized is not None else None,
    }


@router.post("/studio/skill-folders")
async def create_studio_skill_folder(
    request: SkillFolderBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).create_skill_folder,
            payload,
        )
        return _snapshot(snapshot)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.patch("/studio/skill-folders/{folder_id}")
async def update_studio_skill_folder(
    folder_id: str,
    request: SkillFolderBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).update_skill_folder,
            folder_id,
            payload,
        )
        return _snapshot(snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/studio/skill-folders/{folder_id}")
async def delete_studio_skill_folder(
    folder_id: str,
    delete_skills: bool = False,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _studio_service(http_request).delete_skill_folder,
            folder_id,
            delete_skills,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc


@router.get("/studio/memories")
async def list_studio_memories(
    include_deleted: bool = False,
    limit: int = 100,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    memories = await asyncio.to_thread(
        _studio_service(http_request).list_memories,
        include_deleted,
        max(1, min(500, int(limit or 100))),
    )
    return {"memories": [_snapshot(memory) for memory in memories]}


@router.post("/studio/memories")
async def create_studio_memory(
    request: MemoryBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).create_memory,
            payload,
        )
        return _snapshot(snapshot)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.patch("/studio/memories/{memory_id}")
async def update_studio_memory(
    memory_id: str,
    request: MemoryBody,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).update_memory,
            memory_id,
            payload,
        )
        return _snapshot(snapshot)
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.delete("/studio/memories/{memory_id}")
async def delete_studio_memory(
    memory_id: str,
    reason: str = "",
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            _studio_service(http_request).delete_memory,
            memory_id,
            reason,
        )
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.get("/studio/future-tasks")
async def list_studio_future_tasks(
    include_finished: bool = True,
    limit: int = 100,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    future_tasks = await asyncio.to_thread(
        _studio_service(http_request).list_future_tasks,
        include_finished,
        max(1, min(500, int(limit or 100))),
    )
    return {"future_tasks": [_snapshot(future_task) for future_task in future_tasks]}


@router.post("/studio/future-tasks/trigger-due")
async def trigger_due_studio_future_tasks(
    request: FutureTaskTriggerBody | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    body = request or FutureTaskTriggerBody()
    try:
        triggered = await asyncio.to_thread(
            _studio_service(http_request).trigger_due_future_tasks,
            body.now_epoch,
            max(1, min(200, int(body.limit or 20))),
        )
        return {"ok": True, "triggered": [_snapshot(item) for item in triggered]}
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


@router.post("/studio/future-tasks/{future_task_id}/cancel")
async def cancel_studio_future_task(
    future_task_id: str,
    request: FutureTaskCancelBody | None = None,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    try:
        snapshot = await asyncio.to_thread(
            _studio_service(http_request).cancel_future_task,
            future_task_id,
            request.reason if request is not None else "",
        )
        return {"ok": True, "future_task": _snapshot(snapshot)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="FutureTask 不存在") from exc
    except AgentRuntimeError as exc:
        raise _bad_request(exc) from exc


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
    filtered_events = [
        event
        for event in events
        if int(getattr(event, "sequence", 0) or 0) > clean_after_sequence
    ]
    page = filtered_events[:clean_limit]
    next_after_sequence = max(
        [int(getattr(event, "sequence", 0) or 0) for event in page] or [clean_after_sequence]
    )
    return {
        "run_id": run_id,
        "after_sequence": clean_after_sequence,
        "limit": clean_limit,
        "next_after_sequence": next_after_sequence,
        "has_more": len(filtered_events) > clean_limit,
        "events": [_snapshot(event) for event in page],
    }
