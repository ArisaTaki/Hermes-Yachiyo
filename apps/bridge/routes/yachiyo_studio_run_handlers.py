"""Run timeline, approval, artifact, and event route handlers for Agent Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import TaskApprovalRequest
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    snapshot,
    studio_service,
)
from apps.shell.agent_runtime import AgentRuntimeError


async def get_run_timeline(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).get_run_timeline, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


async def list_runs(
    limit: int = 50,
    http_request: Request | None = None,
) -> dict[str, Any]:
    runs = await asyncio.to_thread(
        studio_service(http_request).list_run_timelines,
        max(1, min(200, int(limit or 50))),
    )
    return {"runs": [snapshot(run) for run in runs]}


async def rerun_run(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).rerun_run, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def cancel_run(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).cancel_run, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc


async def delete_run(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).delete_run, run_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def approve_run_approval(
    run_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(studio_service(http_request).approve_run_approval, run_id)
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def reject_run_approval(
    run_id: str,
    request: TaskApprovalRequest | None = None,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_snapshot = await asyncio.to_thread(
            studio_service(http_request).reject_run_approval,
            run_id,
            request.reason if request is not None else "",
        )
        return snapshot(run_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def read_run_artifact(
    run_id: str,
    artifact_path: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        artifact = await asyncio.to_thread(
            studio_service(http_request).read_run_artifact,
            run_id,
            artifact_path,
        )
        return snapshot(artifact)
    except (AgentRuntimeError, KeyError) as exc:
        raise HTTPException(status_code=404, detail="Artifact 不存在") from exc


async def get_run_events(
    run_id: str,
    after_sequence: int = 0,
    limit: int = 200,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        event_page = await asyncio.to_thread(
            studio_service(http_request).get_run_event_page,
            run_id,
            after_sequence,
            limit,
        )
        return snapshot(event_page)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
