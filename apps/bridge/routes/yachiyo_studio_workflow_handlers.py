"""Workflow route handlers for Agent Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import StartWorkflowRunBody
from apps.bridge.routes.yachiyo_services import (
    bad_request,
    snapshot,
    studio_service,
)
from apps.shell.agent_runtime import AgentRuntimeError
from apps.shell.yachiyo_agent import (
    SaveWorkflowRequest,
    StartWorkflowRunRequest,
)


async def list_workflows(http_request: Request | None = None) -> dict[str, Any]:
    workflows = await asyncio.to_thread(studio_service(http_request).list_workflows)
    return {"workflows": [snapshot(workflow) for workflow in workflows]}


async def save_workflow(
    request: SaveWorkflowRequest,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        workflow_snapshot = await asyncio.to_thread(studio_service(http_request).save_workflow, request)
        return snapshot(workflow_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc


async def get_workflow(
    workflow_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        workflow_snapshot = await asyncio.to_thread(
            studio_service(http_request).get_workflow,
            workflow_id,
        )
        return snapshot(workflow_snapshot)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc


async def delete_workflow(
    workflow_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(studio_service(http_request).delete_workflow, workflow_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Workflow 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def start_workflow_run(
    workflow_id: str,
    request: StartWorkflowRunBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        run_request = StartWorkflowRunRequest(
            workflow_id=workflow_id,
            objective=request.objective,
            title=request.title,
            client_run_id=request.client_run_id,
        )
        run_snapshot = await asyncio.to_thread(
            studio_service(http_request).start_workflow_run,
            run_request,
        )
        return snapshot(run_snapshot)
    except (AgentRuntimeError, KeyError) as exc:
        raise bad_request(exc) from exc
