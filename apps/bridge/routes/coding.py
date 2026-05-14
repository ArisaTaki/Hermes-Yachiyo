"""Coding Execution Service UI routes."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.shell.coding_execution import CodingExecutionError, get_coding_execution_service

router = APIRouter(prefix="/ui/coding", tags=["Coding"])


class CreateCodingJobRequest(BaseModel):
    user_request: str = Field(..., min_length=1, max_length=12000)
    repo_path: str = Field(..., min_length=1, max_length=2000)
    task_type: str = Field(default="custom", max_length=80)
    writable_scopes: list[str] = Field(default_factory=lambda: ["."])
    readonly_scopes: list[str] = Field(default_factory=list)
    design_mode: str = Field(default="none", max_length=80)
    preferred_provider: str = Field(default="local_claude_code", max_length=120)
    review_strategy: str = Field(default="codex_if_available", max_length=120)
    allow_install_suggestions: bool = True
    branch_policy: dict[str, Any] | None = None
    test_commands: list[str] = Field(default_factory=list)
    build_commands: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)


class UpdateCodingConfigRequest(BaseModel):
    default_repo_path: str | None = Field(default=None, max_length=2000)
    default_writable_scopes: list[str] | str | None = None
    default_provider: str | None = Field(default=None, max_length=120)
    default_review_strategy: str | None = Field(default=None, max_length=120)
    default_design_mode: str | None = Field(default=None, max_length=120)
    hapi_url: str | None = Field(default=None, max_length=2000)
    opendesign_artifact_dir: str | None = Field(default=None, max_length=2000)
    opendesign_daemon_url: str | None = Field(default=None, max_length=2000)
    opendesign_web_url: str | None = Field(default=None, max_length=2000)
    opendesign_auth_token: str | None = Field(default=None, max_length=4000)
    opendesign_app_path: str | None = Field(default=None, max_length=2000)
    opendesign_auto_start: bool | None = None
    claude_credential_mode: str | None = Field(default=None, max_length=40)
    anthropic_base_url: str | None = Field(default=None, max_length=2000)
    anthropic_api_key: str | None = Field(default=None, max_length=4000)
    codex_credential_mode: str | None = Field(default=None, max_length=40)
    codex_base_url: str | None = Field(default=None, max_length=2000)
    codex_api_key: str | None = Field(default=None, max_length=4000)


class ProviderInstallRequest(BaseModel):
    action: str = Field(default="install", max_length=40)


@router.get("/config")
async def get_coding_config() -> dict[str, Any]:
    service = get_coding_execution_service()
    return await asyncio.to_thread(service.get_config)


@router.patch("/config")
async def update_coding_config(request: UpdateCodingConfigRequest) -> dict[str, Any]:
    service = get_coding_execution_service()
    return await asyncio.to_thread(
        service.update_config,
        request.model_dump(exclude_unset=True),
    )


@router.get("/providers")
async def get_coding_providers() -> dict[str, Any]:
    service = get_coding_execution_service()
    return {"ok": True, "providers": await asyncio.to_thread(service.provider_statuses)}


@router.post("/providers/{provider_id}/health-check")
async def health_check_provider(provider_id: str) -> dict[str, Any]:
    service = get_coding_execution_service()
    return {"ok": True, "provider": await asyncio.to_thread(service.health_check_provider, provider_id)}


@router.post("/providers/{provider_id}/test-config")
async def test_provider_config(provider_id: str) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.test_provider_config, provider_id)
    except CodingExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/review-providers")
async def get_review_providers() -> dict[str, Any]:
    service = get_coding_execution_service()
    return {"ok": True, "providers": await asyncio.to_thread(service.review_provider_statuses)}


@router.post("/providers/{provider_id}/install")
async def install_coding_provider(provider_id: str, request: ProviderInstallRequest) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.install_provider, provider_id, request.action)
    except CodingExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/provider-installs/{install_id}")
async def get_provider_install(install_id: str) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.get_provider_install, install_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="provider install 不存在") from exc


@router.post("/jobs")
async def create_coding_job(request: CreateCodingJobRequest) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.create_job, request.model_dump())
    except CodingExecutionError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/jobs")
async def list_coding_jobs(limit: int = 50) -> dict[str, Any]:
    service = get_coding_execution_service()
    return await asyncio.to_thread(service.list_jobs, limit)


@router.get("/jobs/{job_id}")
async def get_coding_job(job_id: str) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.get_job, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="coding job 不存在") from exc


@router.post("/jobs/{job_id}/approve")
async def approve_coding_job(job_id: str) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.approve_job, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="coding job 不存在") from exc


@router.post("/jobs/{job_id}/cancel")
async def cancel_coding_job(job_id: str) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.cancel_job, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="coding job 不存在") from exc


@router.get("/jobs/{job_id}/artifacts")
async def get_coding_job_artifacts(job_id: str) -> dict[str, Any]:
    service = get_coding_execution_service()
    try:
        return await asyncio.to_thread(service.list_artifacts, job_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="coding job 不存在") from exc
