"""Agent definition route handlers for Agent Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import AgentSkillBody, StartAgentRunBody
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    snapshot,
    studio_service,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import (
    AgentDeskFileEventRequest,
    SaveAgentDeskFileRequest,
    SaveAgentDeskNoteRequest,
    SaveAgentRequest,
    StartAgentRunRequest,
)


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


async def update_agent(
    agent_id: str,
    request: SaveAgentRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    return await save_agent(request.model_copy(update={"agent_id": agent_id}), http_request)


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


async def get_agent_desk(
    agent_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        desk_snapshot = await asyncio.to_thread(
            studio_service(http_request).get_agent_desk,
            agent_id,
        )
        return snapshot(desk_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def write_agent_desk_note(
    agent_id: str,
    request: SaveAgentDeskNoteRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        desk_snapshot = await asyncio.to_thread(
            studio_service(http_request).write_agent_desk_note,
            agent_id,
            request,
        )
        return snapshot(desk_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def write_agent_desk_file(
    agent_id: str,
    request: SaveAgentDeskFileRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        desk_snapshot = await asyncio.to_thread(
            studio_service(http_request).write_agent_desk_file,
            agent_id,
            request,
        )
        return snapshot(desk_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def trigger_agent_desk_file_event(
    agent_id: str,
    request: AgentDeskFileEventRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        future_task = await asyncio.to_thread(
            studio_service(http_request).trigger_agent_desk_file_event,
            agent_id,
            request,
        )
        return snapshot(future_task)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Agent 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def start_agent_run(
    agent_id: str,
    request: StartAgentRunBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_request = StartAgentRunRequest(
            agent_id=agent_id,
            objective=request.objective,
            title=request.title,
            client_run_id=request.client_run_id,
        )
        run_snapshot = await asyncio.to_thread(
            studio_service(http_request).start_agent_run,
            run_request,
        )
        return snapshot(run_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
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
