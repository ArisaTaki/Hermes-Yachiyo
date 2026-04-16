"""Hermes Agent 运行时生命周期管理

Core Runtime 职责：
- Hermes Agent 封装与生命周期
- 任务编排与状态管理  
- 聊天会话管理
- Hermes 安装检测与引导
- TaskRunner 启动与停止
- 不直接暴露 HTTP 路由（由 apps/bridge 负责）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from typing import TYPE_CHECKING

from apps.core.chat_session import ChatSession, get_chat_session
from apps.core.state import AppState
from apps.installer.hermes_check import check_hermes_installation
from packages.protocol.enums import HermesInstallStatus
from packages.protocol.install import HermesInstallInfo

if TYPE_CHECKING:
    from apps.core.task_runner import TaskRunner
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


class HermesRuntime:
    """Hermes Agent 运行时

    管理应用生命周期、任务状态、聊天会话、Hermes Agent 集成。
    """

    def __init__(self, config: "AppConfig") -> None:
        self._config = config
        self._state = AppState()
        self._chat_session: ChatSession = get_chat_session()
        self._start_time: float | None = None
        self._running = False
        self._hermes_install_info: HermesInstallInfo | None = None
        self._task_runner: "TaskRunner | None" = None
        self._task_runner_thread: threading.Thread | None = None
        self._task_runner_loop: asyncio.AbstractEventLoop | None = None
        self._task_runner_loop_ready = threading.Event()

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def chat_session(self) -> ChatSession:
        return self._chat_session

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

    @property
    def task_runner(self) -> "TaskRunner | None":
        """任务调度器（启动后才有）"""
        return self._task_runner

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
        
        # 4. 启动 TaskRunner（在独立线程的事件循环中）
        self._start_task_runner()
        
        logger.info("Hermes Runtime 已启动 (uptime=%.2fs)", self.uptime)

    def stop(self) -> None:
        """停止运行时"""
        if not self._running:
            return
        
        # 停止 TaskRunner
        self._stop_task_runner()
        
        self._running = False
        logger.info("Hermes Runtime 已停止")

    def _start_task_runner(self) -> None:
        """在独立线程中启动 TaskRunner 事件循环"""
        from apps.core.executor import select_executor
        from apps.core.task_runner import TaskRunner

        executor = select_executor(self)
        self._task_runner = TaskRunner(self._state, executor=executor)
        self._task_runner_loop_ready.clear()

        def run_loop():
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._task_runner_loop = loop
            try:
                loop.run_until_complete(self._task_runner.start())
                loop.call_soon(self._task_runner_loop_ready.set)
                loop.run_forever()
            except Exception:
                self._task_runner_loop_ready.set()
                logger.exception("TaskRunner 事件循环异常退出")
            finally:
                loop.close()

        self._task_runner_thread = threading.Thread(
            target=run_loop,
            name="task-runner-thread",
            daemon=True,
        )
        self._task_runner_thread.start()
        if not self._task_runner_loop_ready.wait(timeout=3.0):
            logger.warning("TaskRunner 事件循环未在超时时间内就绪")
        logger.info(
            "TaskRunner 已在独立线程启动 (executor=%s)",
            type(self._task_runner.executor).__name__,
        )

    def _stop_task_runner(self) -> None:
        """停止 TaskRunner 及其事件循环"""
        if self._task_runner is None:
            return

        if self._task_runner_thread is not None and self._task_runner_thread.is_alive():
            if not self._task_runner_loop_ready.wait(timeout=3.0):
                logger.warning("TaskRunner loop 尚未就绪，无法提交停止协程")

        loop = self._task_runner_loop
        if loop is not None and loop.is_running():
            future = asyncio.run_coroutine_threadsafe(self._task_runner.stop(), loop)
            try:
                future.result(timeout=3.0)
            except concurrent.futures.TimeoutError:
                logger.warning("TaskRunner stop 超时，将继续请求事件循环停止")
            except Exception as exc:
                logger.warning("TaskRunner stop 异常: %s", exc)
            loop.call_soon_threadsafe(loop.stop)

        if self._task_runner_thread is not None:
            self._task_runner_thread.join(timeout=3.0)
            if self._task_runner_thread.is_alive():
                logger.warning("TaskRunner 线程未在超时时间内退出")

        self._task_runner = None
        self._task_runner_loop = None
        self._task_runner_thread = None
        self._task_runner_loop_ready.clear()
        logger.info("TaskRunner 已停止")

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
                "readiness_level": self._hermes_install_info.readiness_level,
                "limited_tools": self._hermes_install_info.limited_tools,
                "doctor_issues_count": self._hermes_install_info.doctor_issues_count,
            }
        
        return status

    def is_hermes_ready(self) -> bool:
        """检查 Hermes Agent 是否就绪可用"""
        if not self._hermes_install_info:
            return False
        return self._hermes_install_info.status == HermesInstallStatus.READY

    def refresh_hermes_installation(self) -> HermesInstallInfo:
        """重新检测 Hermes Agent 状态并写回运行时缓存。"""
        self._hermes_install_info = check_hermes_installation()
        logger.info(
            "Hermes 安装状态已刷新: status=%s, platform=%s",
            self._hermes_install_info.status,
            self._hermes_install_info.platform,
        )
        return self._hermes_install_info

    def refresh_task_runner_executor(self) -> dict:
        """根据最新 Hermes 状态切换 TaskRunner 后续任务使用的执行器。

        仅替换 executor，不重启 TaskRunner，避免已有 RUNNING 任务被取消后
        留在不可收敛状态。
        """
        if self._task_runner is None:
            return {
                "updated": False,
                "executor": "none",
                "previous_executor": None,
                "reason": "task_runner_not_started",
            }

        from apps.core.executor import select_executor

        new_executor = select_executor(self)
        previous = self._task_runner.executor.name

        def apply_executor() -> None:
            self._task_runner.set_executor(new_executor)

        loop = self._task_runner_loop
        if (
            loop is not None
            and loop.is_running()
            and threading.current_thread() is not self._task_runner_thread
        ):
            done = threading.Event()
            errors: list[BaseException] = []

            def apply_in_loop() -> None:
                try:
                    apply_executor()
                except BaseException as exc:
                    errors.append(exc)
                finally:
                    done.set()

            loop.call_soon_threadsafe(apply_in_loop)
            if not done.wait(timeout=3.0):
                logger.warning("TaskRunner 执行器切换超时")
                return {
                    "updated": False,
                    "executor": previous,
                    "previous_executor": previous,
                    "reason": "timeout",
                }
            if errors:
                logger.warning("TaskRunner 执行器切换失败: %s", errors[0])
                return {
                    "updated": False,
                    "executor": previous,
                    "previous_executor": previous,
                    "reason": str(errors[0]),
                }
        else:
            apply_executor()

        return {
            "updated": previous != new_executor.name,
            "executor": new_executor.name,
            "previous_executor": previous,
            "reason": None,
        }

    def cancel_task_runner_task(self, task_id: str) -> bool:
        """取消 TaskRunner 中已经分派的任务协程。"""
        if self._task_runner is None:
            return False

        def cancel_task() -> bool:
            return self._task_runner.cancel_task(task_id)

        loop = self._task_runner_loop
        if (
            loop is not None
            and loop.is_running()
            and threading.current_thread() is not self._task_runner_thread
        ):
            done = threading.Event()
            result = {"cancelled": False}

            def cancel_in_loop() -> None:
                try:
                    result["cancelled"] = cancel_task()
                finally:
                    done.set()

            loop.call_soon_threadsafe(cancel_in_loop)
            if not done.wait(timeout=3.0):
                logger.warning("TaskRunner 任务协程取消超时: %s", task_id)
                return False
            return result["cancelled"]

        return cancel_task()

    def get_hermes_install_guidance(self) -> dict | None:
        """获取 Hermes 安装引导信息"""
        if not self._hermes_install_info:
            return None
        
        from apps.installer.hermes_install import HermesInstallGuide
        return HermesInstallGuide.get_install_instructions(self._hermes_install_info)
