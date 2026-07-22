"""Memory and future task route handlers for Agent Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import (
    FutureTaskCancelBody,
    FutureTaskTriggerBody,
    MemoryBody,
)
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    runtime_from_request,
    snapshot,
    studio_service,
)
from apps.shell.agent.runtime.memory_services import issue_user_memory_consent_capability
from apps.shell.agent_runtime import AgentRuntimeError


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


async def issue_memory_consent_capability(
    memory_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        runtime = runtime_from_request(http_request)
        return await asyncio.to_thread(
            issue_user_memory_consent_capability,
            runtime.memory_services,
            memory_id,
        )
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
