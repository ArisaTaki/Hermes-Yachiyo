"""Tool catalog route handlers for Agent Studio."""

from __future__ import annotations

import asyncio
from typing import Any

from fastapi import Request

from apps.bridge.routes.yachiyo_services import snapshot, studio_service


async def list_tool_catalog(http_request: Request | None = None) -> dict[str, Any]:
    catalog = await asyncio.to_thread(studio_service(http_request).list_tool_catalog)
    return snapshot(catalog)
