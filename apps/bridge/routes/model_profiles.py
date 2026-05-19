"""Model profile management routes."""

from __future__ import annotations

import asyncio
import sqlite3
from typing import Any

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from apps.shell.model_profiles import ModelProfileError, get_model_profile_service

router = APIRouter(prefix="/ui", tags=["Model Profiles"])


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


def _payload(model: BaseModel) -> dict[str, Any]:
    return model.model_dump(exclude_unset=True, exclude_none=True)


def _bad_request(exc: Exception) -> HTTPException:
    return HTTPException(status_code=400, detail=str(exc))


@router.get("/model-profiles")
async def list_model_profiles() -> dict[str, Any]:
    return await asyncio.to_thread(get_model_profile_service().list_profiles)


@router.get("/model-sources")
async def list_model_sources() -> dict[str, Any]:
    return await asyncio.to_thread(get_model_profile_service().list_sources)


@router.post("/model-sources")
async def create_model_source(request: ModelSourceRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_profile_service().create_source, _payload(request))
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("提供商源名称必须唯一")) from exc
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
        return await asyncio.to_thread(get_model_profile_service().update_source, source_id, _payload(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("提供商源名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.delete("/model-sources/{source_id}")
async def delete_model_source(source_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(get_model_profile_service().delete_source, source_id)


@router.post("/model-sources/{source_id}/test")
async def test_model_source(source_id: str, request: ModelSourceTestRequest | None = None) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
            get_model_profile_service().test_source,
            source_id,
            _payload(request) if request is not None else {},
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc


@router.post("/model-sources/{source_id}/models/fetch")
async def fetch_model_source_models(source_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_profile_service().fetch_source_models, source_id)
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
        return await asyncio.to_thread(get_model_profile_service().create_profile, payload)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型提供商源不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("Profile 名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.post("/model-sources/{source_id}/models/test-and-save")
async def test_and_save_model_source_profile(source_id: str, request: ModelProfileRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(
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
        return await asyncio.to_thread(get_model_profile_service().create_profile, _payload(request))
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("Profile 名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.patch("/model-profiles/defaults")
async def update_model_profile_defaults(request: ModelProfileDefaultsRequest) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_profile_service().set_defaults, _payload(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型 Profile 不存在") from exc
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
        return await asyncio.to_thread(get_model_profile_service().update_profile, profile_id, _payload(request))
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型 Profile 不存在") from exc
    except sqlite3.IntegrityError as exc:
        raise _bad_request(ModelProfileError("Profile 名称必须唯一")) from exc
    except ModelProfileError as exc:
        raise _bad_request(exc) from exc


@router.delete("/model-profiles/{profile_id}")
async def delete_model_profile(profile_id: str) -> dict[str, Any]:
    return await asyncio.to_thread(get_model_profile_service().delete_profile, profile_id)


@router.post("/model-profiles/{profile_id}/test")
async def test_model_profile(profile_id: str) -> dict[str, Any]:
    try:
        return await asyncio.to_thread(get_model_profile_service().test_profile, profile_id)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="模型 Profile 不存在") from exc
