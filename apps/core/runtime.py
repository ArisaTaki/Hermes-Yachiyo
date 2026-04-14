"""Hermes Agent 运行时生命周期管理

Core Runtime 职责：
- Hermes Agent 封装与生命周期
- 任务编排与状态管理  
- Hermes 安装检测与引导
- 不直接暴露 HTTP 路由（由 apps/bridge 负责）
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from apps.core.state import AppState
from apps.installer.hermes_check import check_hermes_installation
from packages.protocol.enums import HermesInstallStatus
from packages.protocol.install import HermesInstallInfo

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
        self._hermes_install_info: HermesInstallInfo | None = None

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

    @property
    def hermes_install_info(self) -> HermesInstallInfo | None:
        """Hermes Agent 安装检测信息"""
        return self._hermes_install_info

    def start(self) -> None:
        """启动运行时"""
        if self._running:
            return
        
        logger.info("正在启动 Hermes Runtime...")
        
        # 1. 检测 Hermes Agent 安装状态
        self._hermes_install_info = check_hermes_installation()
        logger.info(
            "Hermes 安装检测完成: status=%s, platform=%s", 
            self._hermes_install_info.status, 
            self._hermes_install_info.platform
        )
        
        # 2. 根据安装状态决定启动策略
        if self._hermes_install_info.status != HermesInstallStatus.READY:
            logger.warning(
                "Hermes Agent 未正确安装: %s", 
                self._hermes_install_info.status
            )
            # 注意：不阻止启动，允许用户在 UI 中查看安装指导
        
        # 3. 启动核心服务
        self._start_time = time.time()
        self._running = True
        logger.info("Hermes Runtime 已启动 (uptime=%.2fs)", self.uptime)

    def stop(self) -> None:
        """停止运行时"""
        if not self._running:
            return
        self._running = False
        logger.info("Hermes Runtime 已停止")

    def get_status(self) -> dict:
        """获取运行时状态摘要"""
        status = {
            "service": "hermes-yachiyo",
            "version": "0.1.0",
            "running": self._running,
            "uptime_seconds": self.uptime,
            "task_counts": self._state.get_task_counts(),
        }
        
        # 添加 Hermes 安装状态
        if self._hermes_install_info:
            status["hermes"] = {
                "install_status": self._hermes_install_info.status,
                "platform": self._hermes_install_info.platform,
                "command_exists": self._hermes_install_info.command_exists,
                "version": (
                    self._hermes_install_info.version_info.version 
                    if self._hermes_install_info.version_info 
                    else None
                ),
                "hermes_home": self._hermes_install_info.hermes_home,
            }
        
        return status

    def is_hermes_ready(self) -> bool:
        """检查 Hermes Agent 是否就绪可用"""
        if not self._hermes_install_info:
            return False
        return self._hermes_install_info.status == HermesInstallStatus.READY

    def get_hermes_install_guidance(self) -> dict | None:
        """获取 Hermes 安装引导信息"""
        if not self._hermes_install_info:
            return None
        
        from apps.installer.hermes_install import HermesInstallGuide
        return HermesInstallGuide.get_install_instructions(self._hermes_install_info)
