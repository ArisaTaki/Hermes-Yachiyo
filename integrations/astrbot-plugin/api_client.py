"""Hermes-Yachiyo Bridge / Hapi HTTP 客户端。

依赖 httpx（需在 AstrBot 宿主环境中可用）。
仅封装 HTTP 操作，不处理业务逻辑。
"""

from __future__ import annotations

import logging
from typing import Any, Dict

import httpx

from .config import PluginConfig

logger = logging.getLogger(__name__)


def _raise_readable(resp: httpx.Response) -> None:
    """从 HTTP 错误响应中提取可读错误信息并抛出 RuntimeError。"""
    try:
        detail = resp.json().get("detail") or resp.json().get("message")
        if isinstance(detail, dict):
            detail = detail.get("message", str(detail))
        msg = detail or resp.text[:200]
    except Exception:
        msg = resp.text[:200] or f"HTTP {resp.status_code}"
    raise RuntimeError(f"[{resp.status_code}] {msg}")


class HermesClient:
    """Hermes-Yachiyo Bridge API 客户端。

    端点映射：
      GET  /status              → get_status()
      GET  /tasks               → list_tasks()
      POST /tasks               → create_task()
      GET  /screen/current      → get_screen()
      GET  /system/active-window → get_active_window()
    """

    def __init__(self, config: PluginConfig) -> None:
        self._base = config.hermes_url.rstrip("/")
        self._timeout = config.timeout

    async def _get(self, path: str) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.get(f"{self._base}{path}")
            if resp.is_error:
                _raise_readable(resp)
            return resp.json()

    async def _post(self, path: str, body: Dict[str, Any]) -> Dict[str, Any]:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(f"{self._base}{path}", json=body)
            if resp.is_error:
                _raise_readable(resp)
            return resp.json()

    async def get_status(self) -> Dict[str, Any]:
        """GET /status"""
        return await self._get("/status")

    async def list_tasks(self) -> Dict[str, Any]:
        """GET /tasks"""
        return await self._get("/tasks")

    async def create_task(self, description: str) -> Dict[str, Any]:
        """POST /tasks — 创建 general/low 风险任务"""
        return await self._post(
            "/tasks",
            {"description": description, "task_type": "general", "risk_level": "low"},
        )

    async def get_screen(self) -> Dict[str, Any]:
        """GET /screen/current"""
        return await self._get("/screen/current")

    async def get_active_window(self) -> Dict[str, Any]:
        """GET /system/active-window"""
        return await self._get("/system/active-window")


class HapiClient:
    """Hapi（Codex 执行后端）HTTP 客户端。

    当前为占位实现：Hapi /codex 端点设计待确认后完整实现。
    """

    def __init__(self, config: PluginConfig) -> None:
        self._base = config.hapi_url.rstrip("/")
        self._timeout = config.timeout

    async def run_codex(self, task: str) -> Dict[str, Any]:
        """POST /codex — 发起 Codex 任务（占位，端点待确认）"""
        # TODO: 确认 Hapi /codex 请求/响应 schema 后完整实现
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            resp = await client.post(
                f"{self._base}/codex",
                json={"task": task},
            )
            resp.raise_for_status()
            return resp.json()
