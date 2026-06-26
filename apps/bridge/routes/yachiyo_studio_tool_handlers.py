"""Tool catalog route handlers for Agent Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import HTTPException, Request

from apps.bridge.routes.yachiyo_models import (
    PlanTaskBody,
    RestrictedToolPluginInstallBody,
    RestrictedToolPluginUpdateBody,
)
from apps.bridge.routes.yachiyo_services import snapshot, studio_service
from apps.bridge.routes.yachiyo_services import bad_request
from apps.shell.agent_runtime import AgentRuntimeError


async def list_tool_catalog(http_request: Request | None = None) -> dict[str, Any]:
    catalog = await asyncio.to_thread(studio_service(http_request).list_tool_catalog)
    return snapshot(catalog)


async def plan_task(
    request: PlanTaskBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    decision = await asyncio.to_thread(
        studio_service(http_request).plan_task,
        request.prompt,
        allowed_tools=request.allowed_tools,
        metadata=request.metadata,
    )
    return snapshot(decision)


async def list_restricted_tool_plugins(http_request: Request | None = None) -> dict[str, Any]:
    plugins = await asyncio.to_thread(studio_service(http_request).list_restricted_tool_plugins)
    return {"plugins": [snapshot(plugin) for plugin in plugins]}


async def install_restricted_tool_plugin(
    request: RestrictedToolPluginInstallBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        plugin = await asyncio.to_thread(
            studio_service(http_request).install_restricted_tool_plugin,
            request,
        )
        return snapshot(plugin)
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def update_restricted_tool_plugin(
    plugin_id: str,
    request: RestrictedToolPluginUpdateBody,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        plugin = await asyncio.to_thread(
            studio_service(http_request).update_restricted_tool_plugin,
            plugin_id,
            request,
        )
        return snapshot(plugin)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Restricted tool plugin 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc


async def uninstall_restricted_tool_plugin(
    plugin_id: str,
    http_request: Request | None = None,
) -> dict[str, Any]:
    try:
        plugin = await asyncio.to_thread(
            studio_service(http_request).uninstall_restricted_tool_plugin,
            plugin_id,
        )
        return snapshot(plugin)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Restricted tool plugin 不存在") from exc
    except AgentRuntimeError as exc:
        raise bad_request(exc) from exc
