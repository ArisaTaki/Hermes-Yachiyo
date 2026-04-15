"""最小任务执行器

MVP 阶段：模拟任务状态推进
  PENDING → RUNNING（约 2 秒后）
  RUNNING → COMPLETED（再约 5 秒后）

当 Hermes Agent 真正集成后，_execute() 负责将任务提交给 Hermes 并回传结果。
不直接暴露 HTTP，不依赖 Bridge 层。
"""

from __future__ import annotations

import asyncio
import logging

from apps.core.state import AppState
from packages.protocol.enums import TaskStatus

logger = logging.getLogger(__name__)

_POLL_INTERVAL: float = 2.0   # 轮询间隔（秒）
_RUN_DELAY: float = 2.0       # PENDING → RUNNING 延迟（秒）
_COMPLETE_DELAY: float = 5.0  # RUNNING → COMPLETED 延迟（秒）


class TaskRunner:
    """最小任务状态推进器

    轮询 AppState 中的 PENDING 任务并推进其生命周期。
    每个任务在独立的 asyncio.Task 中执行，互不阻塞。
    """

    def __init__(self, state: AppState) -> None:
        self._state = state
        self._in_progress: dict[str, asyncio.Task] = {}
        self._running = False
        self._loop_task: asyncio.Task | None = None

    async def start(self) -> None:
        """启动后台轮询循环"""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(
            self._poll_loop(), name="task-runner-poll"
        )
        logger.info("TaskRunner 已启动（poll_interval=%.1fs）", _POLL_INTERVAL)

    async def stop(self) -> None:
        """停止轮询循环及所有进行中的任务子协程"""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        for t in list(self._in_progress.values()):
            t.cancel()
        logger.info("TaskRunner 已停止")

    # ── 内部方法 ────────────────────────────────────────────

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                self._dispatch_pending()
            except Exception:
                logger.exception("TaskRunner poll 异常")
            await asyncio.sleep(_POLL_INTERVAL)

    def _dispatch_pending(self) -> None:
        """将所有尚未分派的 PENDING 任务提交到独立协程"""
        for task in self._state.list_tasks():
            if (
                task.status == TaskStatus.PENDING
                and task.task_id not in self._in_progress
            ):
                coro_task = asyncio.create_task(
                    self._execute(task.task_id, task.description),
                    name=f"task-{task.task_id}",
                )
                self._in_progress[task.task_id] = coro_task
                coro_task.add_done_callback(
                    lambda ft, tid=task.task_id: self._in_progress.pop(tid, None)
                )

    async def _execute(self, task_id: str, description: str) -> None:
        """执行单个任务：PENDING → RUNNING → COMPLETED/FAILED"""
        try:
            await asyncio.sleep(_RUN_DELAY)
            self._state.update_task_status(task_id, TaskStatus.RUNNING)
            logger.info("任务开始执行: %s", task_id)

            await asyncio.sleep(_COMPLETE_DELAY)

            # MVP 阶段：直接标记完成，result 为占位说明
            # 真实集成时：在此处调用 Hermes Agent 并填写实际结果
            self._state.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                result=f"已完成（占位）：{description[:60]}",
            )
            logger.info("任务已完成: %s", task_id)

        except asyncio.CancelledError:
            # 外部取消（stop() 时），静默退出
            logger.info("任务协程已取消: %s", task_id)

        except (KeyError, ValueError) as exc:
            # 任务已被 cancel_task() 直接置为终态，忽略状态更新冲突
            logger.debug("任务状态跳过 (%s): %s", task_id, exc)

        except Exception:
            logger.exception("任务执行异常: %s", task_id)
            try:
                self._state.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error="执行器内部异常",
                )
            except Exception:
                pass
