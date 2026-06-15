"""Group and group-run route handlers for Agent Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import StartGroupRunBody
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    snapshot,
    studio_service,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import (
    SaveAgentGroupRequest,
    StartGroupRunRequest,
)


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


async def get_group_run_events(
    group_run_id: str,
    http_request: Request | None = None,
    after_sequence: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    try:
        event_page = await asyncio.to_thread(
            studio_service(http_request).get_group_run_event_page,
            group_run_id,
            after_sequence,
            limit,
        )
        return snapshot(event_page)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="GroupRun 不存在") from exc
