"""Native Run event routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from apps.shell.agent_runtime import AgentRuntimeError, get_native_run_engine
from packages.security import redact_api_error_detail

router = APIRouter(tags=["Runs"])


class RunCreateRequest(BaseModel):
    runnable_id: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=160)
    run_group_id: str | None = Field(default=None, max_length=160)
    client_run_id: str | None = Field(default=None, max_length=160)
    client_request_id: str | None = Field(default=None, max_length=160)
    user_goal: str | None = Field(default=None, max_length=60000)
    goal: str | None = Field(default=None, max_length=60000)
    upstream: str | None = Field(default=None, max_length=60000)


def _create_payload(model: RunCreateRequest, request: Request | None) -> dict[str, Any]:
    payload = model.model_dump(exclude_unset=True, exclude_none=True)
    headers = getattr(request, "headers", None)
    if not payload.get("client_run_id") and not payload.get("client_request_id") and headers is not None:
        key = str(headers.get("idempotency-key", "") or "").strip()
        if key:
            payload["client_run_id"] = key
    return payload


def _native_run_engine(request: Request | None = None) -> Any:
    state = getattr(getattr(request, "app", None), "state", None)
    runtime = getattr(state, "runtime", None)
    if runtime is not None:
        service = getattr(runtime, "agent_runtime_service", None)
        if service is not None:
            return service
        getter = getattr(runtime, "get_agent_runtime_service", None)
        if callable(getter):
            service = getter()
            if service is not None:
                return service
    return get_native_run_engine()


@router.post("/runs")
async def create_run(
    request: RunCreateRequest,
    http_request: Request = None,  # type: ignore[assignment]
) -> dict[str, Any]:
    payload = _create_payload(request, http_request)
    if str(payload.get("run_group_id") or "").strip():
        raise HTTPException(
            status_code=400,
            detail="public_run_group_attachment_forbidden",
        )
    try:
        service = _native_run_engine(http_request)
        return await asyncio.to_thread(
            service.create_run_for_runnable,
            runnable_id=str(payload.get("runnable_id") or ""),
            name=str(payload.get("name") or ""),
            user_goal=str(payload.get("user_goal") or payload.get("goal") or ""),
            run_group_id=str(payload.get("run_group_id") or ""),
            upstream=str(payload.get("upstream") or ""),
            client_run_id=str(payload.get("client_run_id") or ""),
            client_request_id=str(payload.get("client_request_id") or ""),
        )
    except (AgentRuntimeError, KeyError) as exc:
        raise HTTPException(status_code=400, detail=redact_api_error_detail(exc)) from exc


@router.get("/runs/{run_id}/events")
async def list_run_events(
    run_id: str,
    http_request: Request = None,  # type: ignore[assignment]
    after_sequence: int = 0,
    limit: int = 200,
) -> dict:
    try:
        service = _native_run_engine(http_request)
        return await asyncio.to_thread(
            service.list_run_events,
            run_id,
            after_sequence=after_sequence,
            limit=limit,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Run 不存在") from exc
