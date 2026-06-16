"""Chat-facing Yachiyo route handlers."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import TaskApprovalRequest
from apps.bridge.routes.yachiyo_services import (
    agent_service,
    bad_request,
    snapshot,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import ApprovalDecision, StartChatTaskRequest


async def readiness(http_request: Request | None = None) -> dict[str, Any]:
    return snapshot(await asyncio.to_thread(agent_service(http_request).readiness))


async def list_runnables(http_request: Request | None = None) -> dict[str, Any]:
    return snapshot(await asyncio.to_thread(agent_service(http_request).list_runnable_catalog))


async def list_tasks(
    conversation_id: str | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    tasks = await asyncio.to_thread(
        agent_service(http_request).list_recent_tasks,
        conversation_id,
    )
    return {"tasks": [snapshot(task) for task in tasks]}


async def start_task(
    request: StartChatTaskRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(agent_service(http_request).start_chat_task, request)
        return snapshot(task_snapshot)
    except (AgentRuntimeError, KeyError, ValueError) as exc:
        raise bad_request(exc) from exc


async def get_task(
    task_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(agent_service(http_request).get_task_snapshot, task_id)
        return snapshot(task_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


async def get_task_timeline(
    task_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_timeline = await asyncio.to_thread(
            agent_service(http_request).get_task_timeline,
            task_id,
        )
        return snapshot(task_timeline)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


async def get_task_events(
    task_id: str,
    http_request: Request | None = None,
    after_sequence: int = 0,
    limit: int = 200,
) -> dict[str, Any]:
    try:
        task_events = await asyncio.to_thread(
            agent_service(http_request).get_task_event_page,
            task_id,
            after_sequence,
            limit,
        )
        return snapshot(task_events)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc


async def read_task_artifact(
    task_id: str,
    artifact_path: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        artifact = await asyncio.to_thread(
            agent_service(http_request).read_task_artifact,
            task_id,
            artifact_path,
        )
        return snapshot(artifact)
    except (AgentRuntimeError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Artifact 不存在") from exc


async def approve_task(
    task_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request | None = None,
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
        task_snapshot = await asyncio.to_thread(
            agent_service(http_request).approve,
            task_id,
            decision,
        )
        return snapshot(task_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def reject_task(
    task_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(
            agent_service(http_request).reject,
            task_id,
            request.reason if request is not None else "",
        )
        return snapshot(task_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def cancel_task(
    task_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        task_snapshot = await asyncio.to_thread(agent_service(http_request).cancel, task_id)
        return snapshot(task_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Task 不存在") from exc
