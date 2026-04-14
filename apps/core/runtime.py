"""Hermes Agent 运行时生命周期管理

Core Runtime 职责：
- Hermes Agent 封装与生命周期
- 任务编排与状态管理
- 不直接暴露 HTTP 路由（由 apps/bridge 负责）
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from apps.core.state import AppState

if TYPE_CHECKING:
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


class HermesRuntime:
    """Hermes Agent 运行时

    管理应用生命周期、任务状态、Hermes Agent 集成。
    """

    def __init__(self, config: "AppConfig") -> None:
        self._config = config
        self._state = AppState()
        self._start_time: float | None = None
        self._running = False

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def running(self) -> bool:
        return self._running

    @property
    def uptime(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    def start(self) -> None:
        """启动运行时"""
        if self._running:
            return
        self._start_time = time.time()
        self._running = True
        logger.info("Hermes Runtime 已启动")

    def stop(self) -> None:
        """停止运行时"""
        if not self._running:
            return
        self._running = False
        logger.info("Hermes Runtime 已停止")

    def get_status(self) -> dict:
        """获取运行时状态摘要"""
        return {
            "service": "hermes-yachiyo",
            "version": "0.1.0",
            "running": self._running,
            "uptime_seconds": self.uptime,
            "task_counts": self._state.get_task_counts(),
        }
