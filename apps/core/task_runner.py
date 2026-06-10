"""任务调度器

TaskRunner 只负责：
  - 轮询 AppState 中的 PENDING 任务
  - 将每个任务分派到独立 asyncio.Task
  - 推进任务状态（PENDING → RUNNING → COMPLETED/FAILED）
  - 将具体"如何执行"委托给 ExecutionStrategy

默认使用 SimulatedExecutor（MVP 占位）。
不直接暴露 HTTP，不依赖 Bridge 层。
"""

from __future__ import annotations

import asyncio
import logging

from apps.core.executor import ExecutionStrategy, SimulatedExecutor
from apps.core.state import AppState
from packages.protocol.enums import TaskStatus

logger = logging.getLogger(__name__)

_POLL_INTERVAL: float = 2.0  # 轮询间隔（秒）


class TaskRunner:
    """任务调度器

    轮询 AppState 中的 PENDING 任务并推进其生命周期。
    每个任务在独立的 asyncio.Task 中执行，互不阻塞。

    Args:
        state:    AppState 实例（由 Core Runtime 持有）
        executor: 执行策略，默认 SimulatedExecutor。
    """

    def __init__(
        self,
        state: AppState,
        executor: ExecutionStrategy | None = None,
    ) -> None:
        self._state = state
        self._executor: ExecutionStrategy = executor or SimulatedExecutor()
        self._in_progress: dict[str, asyncio.Task] = {}
        self._running = False
        self._loop_task: asyncio.Task | None = None

    @property
    def executor(self) -> ExecutionStrategy:
        return self._executor

    def set_executor(self, executor: ExecutionStrategy) -> str:
        """切换后续任务使用的执行器，返回切换前的执行器名称。"""
        previous = self._executor.name
        self._executor = executor
        logger.info("TaskRunner 执行器已切换: %s -> %s", previous, executor.name)
        return previous

    def cancel_task(self, task_id: str) -> bool:
        """取消已经分派到事件循环中的任务协程。"""
        task = self._in_progress.get(task_id)
        if task is None:
            return False
        task.cancel()
        logger.info("TaskRunner 已请求取消任务协程: %s", task_id)
        return True

    async def start(self) -> None:
        """启动后台轮询循环"""
        if self._running:
            return
        self._running = True
        self._loop_task = asyncio.create_task(
            self._poll_loop(), name="task-runner-poll"
        )
        logger.info(
            "TaskRunner 已启动（executor=%s, poll_interval=%.1fs）",
            type(self._executor).__name__,
            _POLL_INTERVAL,
        )

    async def stop(self) -> None:
        """停止轮询循环及所有进行中的任务子协程"""
        self._running = False
        if self._loop_task:
            self._loop_task.cancel()
            try:
                await self._loop_task
            except asyncio.CancelledError:
                pass
        tasks = list(self._in_progress.values())
        for t in tasks:
            t.cancel()
        if tasks:
            await asyncio.gather(
                *tasks,
                return_exceptions=True,
            )
            self._in_progress.clear()
        logger.info("TaskRunner 已停止")

    # ── 内部调度 ────────────────────────────────────────────────

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
                    self._execute_with_state(task.task_id),
                    name=f"task-{task.task_id}",
                )
                self._in_progress[task.task_id] = coro_task
                coro_task.add_done_callback(
                    lambda ft, tid=task.task_id: self._in_progress.pop(tid, None)
                )

    async def _execute_with_state(self, task_id: str) -> None:
        """状态机包装层：推进状态，将实际执行委托给 self._executor。

        调用链：
          PENDING  →（executor.run() 开始前）→  RUNNING
          RUNNING  →（executor.run() 成功后）→  COMPLETED
          RUNNING  →（executor.run() 抛出）  →  FAILED
          任何阶段 → asyncio.CancelledError   →  静默退出
          终态冲突（task 已被 cancel）         →  静默跳过
        """
        task = self._state.get_task(task_id)
        if task is None:
            return

        try:
            # ① 标记 RUNNING（在 executor.run() 开始前，体现"正在处理"）
            self._state.update_task_status(task_id, TaskStatus.RUNNING, progress_label="正在启动 Agent")
            self._sync_task_message(task_id)
            self._record_task_activity(task_id, "task_start", "Yachiyo 开始处理", "running")
            logger.info("任务开始执行: %s [%s]", task_id, type(self._executor).__name__)

            # ② 委托给执行策略（模拟 or Native Agent）
            result = await self._executor.run(task)

            # ③ 标记 COMPLETED
            self._state.update_task_status(
                task_id,
                TaskStatus.COMPLETED,
                result=result,
                progress_label="已完成",
            )
            self._sync_task_message(task_id)
            self._finalize_task_activity(task_id, "completed")
            self._record_task_activity(task_id, "task_complete", "Yachiyo 回复完成", "completed")
            logger.info("任务已完成: %s", task_id)

        except asyncio.CancelledError:
            logger.info("任务协程已取消: %s", task_id)

        except (KeyError, ValueError) as exc:
            # 任务已被 cancel_task() 直接置为终态，终态保护触发，静默忽略
            logger.debug("任务状态跳过 (%s): %s", task_id, exc)

        except Exception as exc:
            # Agent adapters may expose a concise user-safe error formatter.
            formatter = getattr(exc, "to_error_string", None)
            if callable(formatter):
                error_str = str(formatter())
                logger.warning("任务执行失败: %s | %s", task_id, error_str)
            else:
                error_str = f"{type(exc).__name__}: {exc}"
                logger.exception("任务执行失败: %s", task_id)
            try:
                self._state.update_task_status(
                    task_id,
                    TaskStatus.FAILED,
                    error=error_str,
                    progress_label="执行失败",
                )
                self._sync_task_message(task_id)
                self._finalize_task_activity(task_id, "failed")
                self._record_task_activity(task_id, "task_failed", "Yachiyo 回复失败", "failed")
            except Exception:
                pass

    def _sync_task_message(self, task_id: str) -> None:
        """将任务状态写回创建它的聊天会话，支持后台会话继续执行。"""
        task = self._state.get_task(task_id)
        session_id = str(getattr(task, "chat_session_id", "") or "") if task is not None else ""
        if task is None or not session_id:
            return
        try:
            from apps.core.chat_session import ChatSession, MessageStatus
            from apps.core.chat_store import get_chat_store

            session = ChatSession(session_id=session_id)
            session.attach_store(
                get_chat_store(),
                load_existing=True,
                fail_active_messages=False,
            )
            if task.status == TaskStatus.COMPLETED:
                session.upsert_assistant_message(
                    task_id=task.task_id,
                    content=task.result or "[任务已完成，无输出]",
                    status=MessageStatus.COMPLETED,
                )
            elif task.status == TaskStatus.FAILED:
                error = task.error or "任务执行失败"
                session.upsert_assistant_message(
                    task_id=task.task_id,
                    content=f"❌ {error}",
                    status=MessageStatus.FAILED,
                    error=error,
                )
            elif task.status == TaskStatus.RUNNING:
                assistant = session.get_assistant_message_for_task(task.task_id)
                session.upsert_assistant_message(
                    task_id=task.task_id,
                    content=assistant.content if assistant is not None else "",
                    status=MessageStatus.PROCESSING,
                    error=assistant.error if assistant is not None else None,
                    attachments=assistant.attachments if assistant is not None else None,
                )
        except Exception:
            logger.debug("同步任务消息失败: %s", task_id, exc_info=True)

    def _finalize_task_activity(self, task_id: str, status: str) -> None:
        """Mark in-flight activity rows terminal once the owning task finishes."""
        try:
            from apps.core.activity_store import get_activity_store

            get_activity_store().finalize_task_events(task_id, status=status)
        except Exception:
            logger.debug("收尾任务活动事件失败: %s", task_id, exc_info=True)

    def _record_task_activity(self, task_id: str, phase: str, title: str, status: str) -> None:
        """Record a compact milestone for dashboard activity."""
        task = self._state.get_task(task_id)
        if task is None:
            return
        try:
            from apps.core.activity_store import get_activity_store

            get_activity_store().record_event(
                session_id=str(getattr(task, "chat_session_id", "") or ""),
                task_id=task_id,
                tool_name="native_agent",
                phase=phase,
                title=title,
                detail=str(getattr(task, "description", "") or ""),
                status=status,
            )
        except Exception:
            logger.debug("记录任务活动节点失败: %s", task_id, exc_info=True)
