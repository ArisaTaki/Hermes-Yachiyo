"""Agent Studio-facing Yachiyo route handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import AgentSkillBody
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    snapshot,
    studio_service,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import SaveAgentRequest


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
