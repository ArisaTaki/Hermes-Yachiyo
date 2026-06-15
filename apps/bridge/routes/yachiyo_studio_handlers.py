"""Agent Studio-facing Yachiyo route handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import (
    AgentSkillBody,
    FutureTaskCancelBody,
    FutureTaskTriggerBody,
    MemoryBody,
    SkillFolderBody,
    SkillImportBody,
    SkillInstallBody,
    SkillUpdateBody,
    StartGroupRunBody,
)
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    snapshot,
    studio_service,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import SaveAgentGroupRequest, SaveAgentRequest, StartGroupRunRequest


async def list_agents(http_request: Request | None = None) -> dict[str, Any]:
    agents = await asyncio.to_thread(studio_service(http_request).list_agents)
    return {"agents": [snapshot(agent) for agent in agents]}


async def save_agent(
    request: SaveAgentRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        agent_snapshot = await asyncio.to_thread(studio_service(http_request).save_agent, request)
        return snapshot(agent_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def get_agent(
    agent_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        agent_snapshot = await asyncio.to_thread(studio_service(http_request).get_agent, agent_id)
        return snapshot(agent_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


async def delete_agent(
    agent_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).delete_agent, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def test_agent_model(
    agent_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).test_agent_model, agent_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def attach_agent_skill(
    agent_id: str,
    request: AgentSkillBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        agent_snapshot = await asyncio.to_thread(
            studio_service(http_request).attach_skill,
            agent_id,
            request.skill_id,
        )
        return snapshot(agent_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 或 Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def detach_agent_skill(
    agent_id: str,
    skill_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        agent_snapshot = await asyncio.to_thread(
            studio_service(http_request).detach_skill,
            agent_id,
            skill_id,
        )
        return snapshot(agent_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc


async def list_skills(http_request: Request | None = None) -> dict[str, Any]:
    skills = await asyncio.to_thread(studio_service(http_request).list_skills)
    return {"skills": [snapshot(skill) for skill in skills]}


async def list_skill_sources(http_request: Request | None = None) -> dict[str, Any]:
    roots = await asyncio.to_thread(studio_service(http_request).list_skill_sources)
    return {"roots": [snapshot(root) for root in roots]}


async def import_skill(
    request: SkillImportBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        skill_snapshot = await asyncio.to_thread(
            studio_service(http_request).import_skill,
            request.source_path,
            request.folder_id,
        )
        return snapshot(skill_snapshot)
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def sync_native_skills(http_request: Request | None = None) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).sync_native_skills)
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def install_skill(
    request: SkillInstallBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            studio_service(http_request).install_skill_command,
            request.command,
            request.folder_id,
        )
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def update_skill(
    skill_id: str,
    request: SkillUpdateBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        skill_snapshot = await asyncio.to_thread(
            studio_service(http_request).update_skill,
            skill_id,
            payload,
        )
        return snapshot(skill_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def delete_skill(
    skill_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).delete_skill, skill_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 不存在") from exc


async def list_skill_folders(http_request: Request | None = None) -> dict[str, Any]:
    payload = await asyncio.to_thread(studio_service(http_request).list_skill_folders)
    uncategorized = payload.get("uncategorized")
    return {
        "folders": [snapshot(folder) for folder in payload.get("folders") or []],
        "uncategorized": snapshot(uncategorized) if uncategorized is not None else None,
    }


async def create_skill_folder(
    request: SkillFolderBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        folder_snapshot = await asyncio.to_thread(
            studio_service(http_request).create_skill_folder,
            payload,
        )
        return snapshot(folder_snapshot)
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def update_skill_folder(
    folder_id: str,
    request: SkillFolderBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        folder_snapshot = await asyncio.to_thread(
            studio_service(http_request).update_skill_folder,
            folder_id,
            payload,
        )
        return snapshot(folder_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def delete_skill_folder(
    folder_id: str,
    delete_skills: bool = False,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            studio_service(http_request).delete_skill_folder,
            folder_id,
            delete_skills,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Skill 文件夹不存在") from exc


async def list_memories(
    include_deleted: bool = False,
    limit: int = 100,
    http_request: Request | None = None,
) -> dict[str, Any]:
    memories = await asyncio.to_thread(
        studio_service(http_request).list_memories,
        include_deleted,
        max(1, min(500, int(limit or 100))),
    )
    return {"memories": [snapshot(memory) for memory in memories]}


async def create_memory(
    request: MemoryBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        memory_snapshot = await asyncio.to_thread(
            studio_service(http_request).create_memory,
            payload,
        )
        return snapshot(memory_snapshot)
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def update_memory(
    memory_id: str,
    request: MemoryBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        payload = request.model_dump(exclude_none=True)
        memory_snapshot = await asyncio.to_thread(
            studio_service(http_request).update_memory,
            memory_id,
            payload,
        )
        return snapshot(memory_snapshot)
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def delete_memory(
    memory_id: str,
    reason: str = "",
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            studio_service(http_request).delete_memory,
            memory_id,
            reason,
        )
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def list_future_tasks(
    include_finished: bool = True,
    limit: int = 100,
    http_request: Request | None = None,
) -> dict[str, Any]:
    future_tasks = await asyncio.to_thread(
        studio_service(http_request).list_future_tasks,
        include_finished,
        max(1, min(500, int(limit or 100))),
    )
    return {"future_tasks": [snapshot(future_task) for future_task in future_tasks]}


async def trigger_due_future_tasks(
    request: FutureTaskTriggerBody | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    body = request or FutureTaskTriggerBody()
    try:
        triggered = await asyncio.to_thread(
            studio_service(http_request).trigger_due_future_tasks,
            body.now_epoch,
            max(1, min(200, int(body.limit or 20))),
        )
        return {"ok": True, "triggered": [snapshot(item) for item in triggered]}
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def cancel_future_task(
    future_task_id: str,
    request: FutureTaskCancelBody | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        future_task_snapshot = await asyncio.to_thread(
            studio_service(http_request).cancel_future_task,
            future_task_id,
            request.reason if request is not None else "",
        )
        return {"ok": True, "future_task": snapshot(future_task_snapshot)}
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="FutureTask 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def list_groups(http_request: Request | None = None) -> dict[str, Any]:
    groups = await asyncio.to_thread(studio_service(http_request).list_groups)
    return {"groups": [snapshot(group) for group in groups]}


async def save_group(
    request: SaveAgentGroupRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        group_snapshot = await asyncio.to_thread(studio_service(http_request).save_group, request)
        return snapshot(group_snapshot)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise bad_request(exc) from exc


async def get_group(
    group_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        group_snapshot = await asyncio.to_thread(studio_service(http_request).get_group, group_id)
        return snapshot(group_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="AgentGroup 不存在") from exc


async def start_group_run(
    group_id: str,
    request: StartGroupRunBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_request = StartGroupRunRequest(
            group_id=group_id,
            objective=request.objective,
            title=request.title,
            client_run_id=request.client_run_id,
        )
        group_run_snapshot = await asyncio.to_thread(
            studio_service(http_request).start_group_run,
            run_request,
        )
        return snapshot(group_run_snapshot)
    except NotImplementedError as exc:
        raise HTTPException(status_code=501, detail=str(exc)) from exc
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise bad_request(exc) from exc


async def list_group_runs(
    limit: int = 50,
    http_request: Request | None = None,
) -> dict[str, Any]:
    group_runs = await asyncio.to_thread(
        studio_service(http_request).list_group_runs,
        max(1, min(200, int(limit or 50))),
    )
    return {"group_runs": [snapshot(group_run) for group_run in group_runs]}


async def get_group_run(
    group_run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        group_run_snapshot = await asyncio.to_thread(
            studio_service(http_request).get_group_run,
            group_run_id,
        )
        return snapshot(group_run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="GroupRun 不存在") from exc
