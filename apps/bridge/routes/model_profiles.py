"""Model profile management routes."""

from __future__ import annotations

import asyncio
import logging
import sqlite3
from collections.abc import Callable
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.bridge.deps import get_runtime
from apps.shell.model_profiles import ModelProfileError, get_model_profile_service
from apps.shell.provider_catalog_sync import (
    list_provider_catalog_adapters,
    load_provider_catalog_cache,
    sync_provider_catalogs,
)
from packages.security import redact_api_error_detail

router = APIRouter(prefix="/ui", tags=["Model Profiles"])
logger = logging.getLogger(__name__)


class ModelProfileRequest(BaseModel):
    profile_id: str | None = Field(default=None, max_length=160)
    source_id: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=160)
    capability: str | None = Field(default=None, max_length=40)
    provider: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=4000)
    model: str | None = Field(default=None, max_length=400)
    api_key: str | None = Field(default=None, max_length=8000)
    options: dict[str, Any] | None = None
    enabled: bool | None = None


class ModelSourceRequest(BaseModel):
    source_id: str | None = Field(default=None, max_length=160)
    name: str | None = Field(default=None, max_length=160)
    capability: str | None = Field(default=None, max_length=40)
    provider: str | None = Field(default=None, max_length=80)
    base_url: str | None = Field(default=None, max_length=4000)
    api_key: str | None = Field(default=None, max_length=8000)
    options: dict[str, Any] | None = None
    enabled: bool | None = None


class ModelSourceTestRequest(BaseModel):
    model: str | None = Field(default=None, max_length=400)


class ModelProfileDefaultsRequest(BaseModel):
    chat: str | None = Field(default=None, max_length=160)
    vision: str | None = Field(default=None, max_length=160)
    tts: str | None = Field(default=None, max_length=160)


class TtsProviderSyncRequest(BaseModel):
    enabled: bool | None = None
    provider: str | None = Field(default=None, max_length=80)
    name: str | None = Field(default=None, max_length=160)
    base_url: str | None = Field(default=None, max_length=4000)
    endpoint: str | None = Field(default=None, max_length=4000)
    voice: str | None = Field(default=None, max_length=400)
    model: str | None = Field(default=None, max_length=400)
    options: dict[str, Any] | None = None


class ProviderCatalogSyncRequest(BaseModel):
    providers: list[str] = Field(default_factory=list)
    if_stale: bool = False
    max_age_seconds: int = Field(default=24 * 60 * 60, ge=60, le=30 * 24 * 60 * 60)


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True, exclude_none=True)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=redact_api_error_detail(exc))


def _refresh_task_runner_executor() -> dict[str, Any]:
    try:
        result = get_runtime().refresh_task_runner_executor()
    except Exception as exc:
        logger.warning("刷新 Chat TaskRunner 执行器失败", exc_info=True)
        return {
            "updated": False,
            "executor": "unknown",
            "previous_executor": None,
            "reason": str(exc),
        }
    reason = str(result.get("reason") or "").strip()
    if reason and reason != "task_runner_not_started":
        logger.warning("刷新 Chat TaskRunner 执行器未完成: %s", reason)
    return result


async def _run_model_profile_mutation(
    operation: Callable[..., dict[str, Any]],
    *args: Any,
) -> dict[str, Any]:
    result = await asyncio.to_thread(operation, *args)
    await asyncio.to_thread(_refresh_task_runner_executor)
    return result


@router.get("/model-profiles")
async def list_model_profiles() -> dict[str, Any]:
    return await asyncio.to_thread(get_model_profile_service().list_profiles)


@router.get("/model-sources")
async def list_model_sources() -> dict[str, Any]:
    return await asyncio.to_thread(get_model_profile_service().list_sources)


@router.get("/model-provider-capabilities")
async def get_model_provider_capabilities() -> dict[str, Any]:
    cache = await asyncio.to_thread(load_provider_catalog_cache)
    return {
        "ok": True,
        "cache": cache,
        "adapters": list_provider_catalog_adapters(),
    }


@router.post("/model-provider-capabilities/sync")
async def sync_model_provider_capabilities(request: ProviderCatalogSyncRequest) -> dict[str, Any]:
    return await asyncio.to_thread(
        sync_provider_catalogs,
        providers=request.providers or None,
        if_stale=request.if_stale,
        max_age_seconds=request.max_age_seconds,
    )


@router.post("/model-sources")
async def create_model_source(request: ModelSourceRequest) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().create_source,
            _payload(request),
        )
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("提供商源 ID 在当前类型下必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.get("/model-sources/{source_id}")
async def get_model_source(source_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_profile_service().get_source, source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc


@router.patch("/model-sources/{source_id}")
async def update_model_source(source_id: str, request: ModelSourceRequest) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().update_source,
            source_id,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("提供商源 ID 在当前类型下必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.delete("/model-sources/{source_id}")
async def delete_model_source(source_id: str) -> dict[str, Any]:
    return await _run_model_profile_mutation(
        get_model_profile_service().delete_source,
        source_id,
    )


@router.post("/model-sources/{source_id}/test")
async def test_model_source(source_id: str, request: ModelSourceTestRequest | None = None) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().test_source,
            source_id,
            _payload(request) if request is not None else {},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc


@router.post("/model-sources/{source_id}/models/fetch")
async def fetch_model_source_models(source_id: str) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().fetch_source_models,
            source_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.get("/model-sources/{source_id}/models")
async def list_model_source_profiles(source_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_profile_service().list_source_profiles, source_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc


@router.post("/model-sources/{source_id}/models")
async def create_model_source_profile(source_id: str, request: ModelProfileRequest) -> dict[str, Any]:
    try:
        payload = _payload(request)
        payload["source_id"] = source_id
        return await _run_model_profile_mutation(
            get_model_profile_service().create_profile,
            payload,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("Profile 名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.post("/model-sources/{source_id}/models/test-and-save")
async def test_and_save_model_source_profile(source_id: str, request: ModelProfileRequest) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().test_and_save_profile,
            source_id,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源或 Profile 不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("Profile 名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.post("/model-profiles")
async def create_model_profile(request: ModelProfileRequest) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().create_profile,
            _payload(request),
        )
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("Profile 名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.patch("/model-profiles/defaults")
async def update_model_profile_defaults(request: ModelProfileDefaultsRequest) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().set_defaults,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型 Profile 不存在") from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.post("/model-profiles/tts/sync")
async def sync_tts_provider(request: TtsProviderSyncRequest) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().sync_tts_provider,
            _payload(request),
        )
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("TTS 语音源名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.get("/model-profiles/{profile_id}")
async def get_model_profile(profile_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_profile_service().get_profile, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型 Profile 不存在") from exc


@router.patch("/model-profiles/{profile_id}")
async def update_model_profile(profile_id: str, request: ModelProfileRequest) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().update_profile,
            profile_id,
            _payload(request),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型 Profile 不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("Profile 名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.delete("/model-profiles/{profile_id}")
async def delete_model_profile(profile_id: str) -> dict[str, Any]:
    return await _run_model_profile_mutation(
        get_model_profile_service().delete_profile,
        profile_id,
    )


@router.post("/model-profiles/{profile_id}/test")
async def test_model_profile(profile_id: str) -> dict[str, Any]:
    try:
        return await _run_model_profile_mutation(
            get_model_profile_service().test_profile,
            profile_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型 Profile 不存在") from exc
