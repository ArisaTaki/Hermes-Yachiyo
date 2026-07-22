"""Application runtime lifecycle management.

Core Runtime 职责：
- Native Agent 执行适配与生命周期
- 任务编排与状态管理
- 聊天会话管理
- TaskRunner 启动与停止
- 不直接暴露 HTTP 路由（由 apps/bridge 负责）
"""

from __future__ import annotations

import asyncio
import concurrent.futures
import logging
import threading
import time
from typing import TYPE_CHECKING, Any

from apps.core.chat_session import ChatSession, get_chat_session
from apps.core.state import AppState
from apps.core.version import get_app_version

if TYPE_CHECKING:
    from apps.core.activity_store import ActivityStore
    from apps.core.task_runner import TaskRunner
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)


class AppRuntime:
    """Manage application services while preserving the product task contract."""

    def __init__(self, config: "AppConfig") -> None:
        self._config = config
        self._state = AppState()
        self._chat_session: ChatSession = get_chat_session()
        from apps.core.activity_store import get_activity_store

        self._activity_store = get_activity_store()
        self._start_time: float | None = None
        self._running = False
        self._task_runner: "TaskRunner | None" = None
        self._task_runner_thread: threading.Thread | None = None
        self._task_runner_loop: asyncio.AbstractEventLoop | None = None
        self._task_runner_loop_ready = threading.Event()
        self._last_ready_command_probe_at = 0.0
        self._lifecycle_lock = threading.RLock()
        self._startup_reconciliation_lock = threading.RLock()
        self._startup_reconciliation_timer: threading.Timer | None = None
        self._startup_reconciliation_generation = 0
        self._startup_reconciliation_timer_factory = threading.Timer
        self._startup_reconciliation_cutoff = ""
        self._runtime_lease_watchdog_interval_seconds = 5.0
        self._runtime_instance_lock: Any | None = None
        self._runtime_instance_service: Any | None = None
        self._pending_activity_terminal_statuses: dict[str, str] = {}
        self._pending_activity_orphan_task_ids: set[str] = set()
        self._pending_activity_recovery_cutoff = ""
        self._startup_reconciliation_diagnostic: dict[str, Any] = {}

    @property
    def state(self) -> AppState:
        return self._state

    @property
    def config(self) -> "AppConfig":
        return self._config

    @property
    def chat_session(self) -> ChatSession:
        return self._chat_session

    @property
    def activity_store(self) -> "ActivityStore":
        return self._activity_store

    @property
    def running(self) -> bool:
        return self._running

    @property
    def uptime(self) -> float:
        if self._start_time is None:
            return 0.0
        return time.time() - self._start_time

    @property
    def task_runner(self) -> "TaskRunner | None":
        """任务调度器（启动后才有）"""
        return self._task_runner

    @property
    def startup_reconciliation_diagnostic(self) -> dict[str, Any]:
        """Return the bounded fail-closed startup diagnostic, if any."""
        diagnostic = getattr(self, "_startup_reconciliation_diagnostic", {})
        return dict(diagnostic) if isinstance(diagnostic, dict) else {}

    def get_agent_runtime_service(self) -> Any:
        service = getattr(self, "agent_runtime_service", None)
        if service is not None:
            return service
        from apps.shell.agent_runtime import get_agent_runtime_service

        return get_agent_runtime_service()

    def start(self) -> None:
        """启动运行时"""
        with self._runtime_lifecycle_state_lock():
            if self._running:
                return

            from apps.shell.agent.runtime.clock import utc_now_iso

            service = self.get_agent_runtime_service()
            if not self._acquire_runtime_instance_lock(service):
                raise RuntimeError("runtime_instance_already_active")
            try:
                self._startup_reconciliation_cutoff = utc_now_iso()
                logger.info("正在启动 App Runtime...")
                self._start_time = time.time()
                self._running = True

                self._reconcile_runs_after_restart()

                self._start_task_runner()
            except Exception:
                if self._running:
                    self._mark_stopping_and_cancel_startup_reconciliation()
                try:
                    self._stop_task_runner()
                except Exception as cleanup_exc:
                    logger.warning(
                        "TaskRunner 启动失败后清理异常: %s",
                        cleanup_exc,
                    )
                finally:
                    self._release_runtime_instance_lock()
                raise

            logger.info("App Runtime 已启动 (uptime=%.2fs)", self.uptime)

    def _reconcile_activity_after_restart(
        self,
        cutoff: str,
        service: Any,
        interrupted_task_ids: list[str],
    ) -> None:
        projection_reader = getattr(service, "get_task_run_projections", None)
        if not callable(projection_reader):
            return
        try:
            projections = projection_reader(interrupted_task_ids)
            if not isinstance(projections, dict):
                return
            terminal_status_by_task = {
                str(task_id): str(projection.get("status") or "")
                for task_id, projection in projections.items()
                if isinstance(projection, dict)
                and str(projection.get("status") or "")
                in {"completed", "success", "failed", "error", "cancelled", "canceled"}
            }
            self._enqueue_activity_recovery(
                cutoff,
                terminal_status_by_task=terminal_status_by_task,
                orphan_task_ids={
                    str(task_id or "")
                    for task_id in interrupted_task_ids
                    if str(task_id or "") not in projections
                },
            )
        except Exception as exc:
            logger.warning("ActivityStore 启动恢复异常: %s", exc)
            return
        self._flush_pending_activity_recovery()

    def _enqueue_activity_recovery(
        self,
        cutoff: str,
        *,
        terminal_status_by_task: dict[str, str],
        orphan_task_ids: set[str],
    ) -> None:
        from apps.shell.agent.runtime.clock import parse_iso_utc

        lock = self._startup_reconciliation_state_lock()
        with lock:
            pending_statuses = getattr(
                self,
                "_pending_activity_terminal_statuses",
                None,
            )
            if not isinstance(pending_statuses, dict):
                pending_statuses = {}
                self._pending_activity_terminal_statuses = pending_statuses
            pending_orphans = getattr(
                self,
                "_pending_activity_orphan_task_ids",
                None,
            )
            if not isinstance(pending_orphans, set):
                pending_orphans = set()
                self._pending_activity_orphan_task_ids = pending_orphans
            for task_id, status in terminal_status_by_task.items():
                clean_task_id = str(task_id or "")
                if clean_task_id:
                    pending_statuses[clean_task_id] = str(status or "")
                    pending_orphans.discard(clean_task_id)
            pending_orphans.update(
                str(task_id or "")
                for task_id in orphan_task_ids
                if str(task_id or "") and str(task_id or "") not in pending_statuses
            )
            clean_cutoff = str(cutoff or "").strip()
            current_cutoff = str(
                getattr(self, "_pending_activity_recovery_cutoff", "")
            ).strip()
            clean_cutoff_at = parse_iso_utc(clean_cutoff)
            current_cutoff_at = parse_iso_utc(current_cutoff)
            if clean_cutoff_at is not None and (
                current_cutoff_at is None or clean_cutoff_at > current_cutoff_at
            ):
                self._pending_activity_recovery_cutoff = clean_cutoff

    def _flush_pending_activity_recovery(self) -> None:
        lock = self._startup_reconciliation_state_lock()
        with lock:
            pending_statuses = dict(
                getattr(self, "_pending_activity_terminal_statuses", {}) or {}
            )
            pending_orphans = set(
                getattr(self, "_pending_activity_orphan_task_ids", set()) or set()
            )
            cutoff = str(
                getattr(self, "_pending_activity_recovery_cutoff", "")
            ).strip()
            if not cutoff or (not pending_statuses and not pending_orphans):
                return
            try:
                recovered = self._activity_store.reconcile_interrupted_tasks(
                    cutoff,
                    terminal_status_by_task=pending_statuses,
                    orphan_task_ids=pending_orphans,
                )
            except Exception as exc:
                logger.warning("ActivityStore 恢复投影异常，将由 watchdog 重试: %s", exc)
                return
            current_statuses = getattr(
                self,
                "_pending_activity_terminal_statuses",
                {},
            )
            if isinstance(current_statuses, dict):
                for task_id, status in pending_statuses.items():
                    if current_statuses.get(task_id) == status:
                        current_statuses.pop(task_id, None)
            current_orphans = getattr(
                self,
                "_pending_activity_orphan_task_ids",
                set(),
            )
            if isinstance(current_orphans, set):
                current_orphans.difference_update(pending_orphans)
            if not current_statuses and not current_orphans:
                self._pending_activity_recovery_cutoff = ""
            if recovered:
                logger.info(
                    "ActivityStore 恢复投影完成 (interrupted=%d)",
                    recovered,
                )

    def stop(self) -> None:
        """停止运行时"""
        with self._runtime_lifecycle_state_lock():
            if not self._running:
                self._release_runtime_instance_lock()
                return

            self._mark_stopping_and_cancel_startup_reconciliation()

            try:
                # 停止 TaskRunner
                self._stop_task_runner()
                self._stop_native_runtime()
                self._stop_activity_store()
            finally:
                self._release_runtime_instance_lock()

            logger.info("App Runtime 已停止")

    def _reconcile_runs_after_restart(self) -> None:
        from apps.shell.agent.runtime.clock import parse_iso_utc, utc_now_iso
        from apps.shell.agent.runtime.startup_reconciliation import (
            StartupReconciliationIntegrityError,
        )

        try:
            service = (
                getattr(self, "_runtime_instance_service", None)
                or self.get_agent_runtime_service()
            )
        except Exception as exc:
            logger.warning("Agent Runtime 启动恢复异常: %s", exc)
            return
        startup_reconciliation: dict[str, Any] = {}
        observed_at = utc_now_iso()
        startup_cutoff = str(
            getattr(self, "_startup_reconciliation_cutoff", "")
        ).strip()
        if not startup_cutoff:
            startup_cutoff = utc_now_iso()
            self._startup_reconciliation_cutoff = startup_cutoff
        try:
            interrupted_task_ids = self._activity_store.list_interrupted_task_ids(
                startup_cutoff,
            )
        except Exception as exc:
            logger.warning("ActivityStore 中断任务扫描异常: %s", exc)
            interrupted_task_ids = []
        try:
            startup_reconciliation = service.reconcile_startup_runs(
                startup_cutoff,
                observed_at=observed_at,
            )
            logger.info(
                "Agent Runtime 启动恢复完成 "
                "(failed=%d, preserved_approvals=%d, deferred_leases=%d)",
                len(startup_reconciliation.get("failed_run_ids") or []),
                len(startup_reconciliation.get("preserved_approval_run_ids") or []),
                len(startup_reconciliation.get("deferred_lease_run_ids") or []),
            )
        except StartupReconciliationIntegrityError as exc:
            self._startup_reconciliation_diagnostic = {
                "code": exc.code,
                "retryable": False,
                "status": "quarantined",
            }
            logger.error(
                "Agent Runtime 启动恢复完整性故障，已隔离启动 (code=%s)",
                exc.code,
            )
            raise RuntimeError(
                f"agent_runtime_startup_quarantined:{exc.code}"
            ) from exc
        except Exception as exc:
            logger.warning("Agent Runtime 启动恢复异常: %s", exc)
        else:
            self._startup_reconciliation_diagnostic = {}
        lease_watchdog = getattr(service, "reconcile_runtime_leases", None)
        watchdog_enabled = callable(lease_watchdog)
        lease_reconciliation: dict[str, Any] = {}
        if watchdog_enabled:
            try:
                lease_reconciliation = lease_watchdog(observed_at)
            except Exception as exc:
                logger.warning("Agent Runtime 租约 watchdog 异常: %s", exc)
        self._reconcile_activity_after_restart(
            startup_cutoff,
            service,
            interrupted_task_ids,
        )
        expiries = [
            expiry
            for expiry in (
                parse_iso_utc(startup_reconciliation.get("next_lease_expiry_at")),
                parse_iso_utc(lease_reconciliation.get("next_lease_expiry_at")),
            )
            if expiry is not None
        ]
        self._schedule_deferred_startup_reconciliation(
            {
                "next_lease_expiry_at": min(expiries).isoformat() if expiries else "",
            },
            keep_alive=watchdog_enabled,
        )

    def _schedule_deferred_startup_reconciliation(
        self,
        reconciliation: dict[str, Any],
        *,
        keep_alive: bool = False,
    ) -> None:
        from apps.shell.agent.runtime.clock import parse_iso_utc

        expiry = parse_iso_utc(reconciliation.get("next_lease_expiry_at"))
        if expiry is None and not keep_alive:
            return
        watchdog_interval = max(
            0.1,
            float(getattr(self, "_runtime_lease_watchdog_interval_seconds", 5.0)),
        )
        delay = watchdog_interval
        if expiry is not None:
            expiry_delay = max(0.05, expiry.timestamp() - time.time() + 0.01)
            delay = min(delay, expiry_delay) if keep_alive else expiry_delay
        lock = self._startup_reconciliation_state_lock()
        with lock:
            if not self._running:
                return
            current = getattr(self, "_startup_reconciliation_timer", None)
            if current is not None:
                current.cancel()
            generation = int(
                getattr(self, "_startup_reconciliation_generation", 0)
            ) + 1
            self._startup_reconciliation_generation = generation
            timer_factory = getattr(
                self,
                "_startup_reconciliation_timer_factory",
                threading.Timer,
            )
            timer = timer_factory(
                delay,
                lambda: self._run_deferred_startup_reconciliation(generation),
            )
            timer.daemon = True
            self._startup_reconciliation_timer = timer
            timer.start()

    def _run_deferred_startup_reconciliation(self, generation: int) -> None:
        lock = self._startup_reconciliation_state_lock()
        with lock:
            if (
                not self._running
                or generation
                != int(getattr(self, "_startup_reconciliation_generation", 0))
            ):
                return
            self._startup_reconciliation_timer = None
            self._run_runtime_lease_watchdog()

    def _run_runtime_lease_watchdog(self) -> None:
        from apps.shell.agent.runtime.clock import utc_now_iso

        try:
            service = (
                getattr(self, "_runtime_instance_service", None)
                or self.get_agent_runtime_service()
            )
        except Exception as exc:
            logger.warning("Agent Runtime 租约 watchdog 异常: %s", exc)
            self._schedule_deferred_startup_reconciliation({}, keep_alive=True)
            return
        lease_watchdog = getattr(service, "reconcile_runtime_leases", None)
        if not callable(lease_watchdog):
            return
        try:
            observed_at = utc_now_iso()
            reconciliation = lease_watchdog(observed_at)
        except Exception as exc:
            logger.warning("Agent Runtime 租约 watchdog 异常: %s", exc)
            reconciliation = {}
        terminal_tasks = (
            reconciliation.get("terminal_tasks")
            if isinstance(reconciliation, dict)
            else None
        )
        if isinstance(terminal_tasks, dict) and terminal_tasks:
            self._enqueue_activity_recovery(
                observed_at,
                terminal_status_by_task={
                    str(task_id): str(projection.get("status") or "")
                    for task_id, projection in terminal_tasks.items()
                    if isinstance(projection, dict)
                },
                orphan_task_ids=set(),
            )
        self._flush_pending_activity_recovery()
        self._schedule_deferred_startup_reconciliation(
            reconciliation if isinstance(reconciliation, dict) else {},
            keep_alive=True,
        )

    def _mark_stopping_and_cancel_startup_reconciliation(self) -> None:
        lock = self._startup_reconciliation_state_lock()
        with lock:
            self._running = False
            self._startup_reconciliation_generation = int(
                getattr(self, "_startup_reconciliation_generation", 0)
            ) + 1
            self._startup_reconciliation_cutoff = ""
            timer = getattr(self, "_startup_reconciliation_timer", None)
            self._startup_reconciliation_timer = None
            if timer is not None:
                timer.cancel()

    def _startup_reconciliation_state_lock(self) -> Any:
        lock = getattr(self, "_startup_reconciliation_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._startup_reconciliation_lock = lock
        return lock

    def _runtime_lifecycle_state_lock(self) -> Any:
        lock = getattr(self, "_lifecycle_lock", None)
        if lock is None:
            lock = threading.RLock()
            self._lifecycle_lock = lock
        return lock

    def _acquire_runtime_instance_lock(self, service: Any) -> bool:
        if getattr(self, "_runtime_instance_lock", None) is not None:
            return True
        db_path = getattr(service, "db_path", None)
        if db_path is None:
            self._runtime_instance_service = service
            return True
        lock_factory = getattr(self, "_runtime_instance_lock_factory", None)
        if lock_factory is None:
            from apps.shell.agent.runtime.runtime_instance_lock import (
                RuntimeProcessInstanceLock,
            )

            lock_factory = RuntimeProcessInstanceLock
        lock = lock_factory(
            db_path=db_path,
            workspace_dir=getattr(service, "workspace_dir", None),
        )
        if not lock.acquire():
            return False
        self._runtime_instance_lock = lock
        self._runtime_instance_service = service
        return True

    def _release_runtime_instance_lock(self) -> None:
        lock = getattr(self, "_runtime_instance_lock", None)
        self._runtime_instance_lock = None
        self._runtime_instance_service = None
        if lock is not None:
            lock.release()

    def _stop_native_runtime(self) -> None:
        service = getattr(self, "agent_runtime_service", None)
        if service is not None and hasattr(service, "close"):
            try:
                service.close()
            except Exception as exc:
                logger.warning("Injected Native Runtime shutdown 异常: %s", exc)
        try:
            from apps.shell.agent_runtime import close_agent_runtime_service

            close_agent_runtime_service()
        except Exception as exc:
            logger.warning("Native Runtime shutdown 异常: %s", exc)

    def _stop_activity_store(self) -> None:
        try:
            from apps.core.activity_store import close_activity_store

            close_activity_store()
        except Exception as exc:
            logger.warning("ActivityStore shutdown 异常: %s", exc)

    def _start_task_runner(self) -> None:
        """在独立线程中启动 TaskRunner 事件循环"""
        from apps.core.executor import select_executor
        from apps.core.task_runner import TaskRunner

        executor = select_executor(self)
        self._task_runner = TaskRunner(
            self._state,
            executor=executor,
            activity_store=self._activity_store,
        )
        self._task_runner_loop_ready.clear()
        startup_result: concurrent.futures.Future[None] = (
            concurrent.futures.Future()
        )
        startup_errors: list[Exception] = []

        def run_loop() -> None:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            self._task_runner_loop = loop

            async def start_runner() -> None:
                try:
                    await self._task_runner.start()
                except asyncio.CancelledError:
                    if not startup_result.done():
                        startup_result.set_exception(
                            RuntimeError("task_runner_startup_cancelled")
                        )
                except Exception as exc:
                    startup_errors.append(exc)
                    if not startup_result.done():
                        startup_result.set_exception(exc)
                else:
                    if not startup_result.done():
                        startup_result.set_result(None)

            try:
                # create_task schedules the first TaskRunner.start() turn before the
                # readiness callback.  An initialization error raised in that turn
                # is therefore published before the main thread observes readiness;
                # a start() coroutine that remains pending is a valid long-running
                # runner rather than a startup timeout.
                loop.create_task(start_runner(), name="task-runner-start")
                loop.call_soon(self._task_runner_loop_ready.set)
                loop.run_forever()
            except Exception as exc:
                startup_errors.append(exc)
                if not startup_result.done():
                    startup_result.set_exception(exc)
                self._task_runner_loop_ready.set()
                logger.exception("TaskRunner 事件循环异常退出")
            finally:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
                loop.close()

        self._task_runner_thread = threading.Thread(
            target=run_loop,
            name="task-runner-thread",
            daemon=True,
        )
        self._task_runner_thread.start()
        startup_failure: BaseException | None = None
        if not self._task_runner_loop_ready.wait(timeout=3.0):
            startup_failure = RuntimeError("task_runner_startup_timeout")
        elif startup_result.done():
            try:
                startup_result.result()
            except BaseException as exc:
                startup_failure = exc
        if startup_failure is None and (
            self._task_runner_thread is None
            or not self._task_runner_thread.is_alive()
        ):
            startup_failure = (
                startup_errors[0]
                if startup_errors
                else RuntimeError("task_runner_thread_exited_during_startup")
            )
        if startup_failure is not None:
            self._stop_task_runner()
            raise startup_failure
        logger.info(
            "TaskRunner 已在独立线程启动 (executor=%s)",
            type(self._task_runner.executor).__name__,
        )

    def _stop_task_runner(self) -> None:
        """停止 TaskRunner 及其事件循环"""
        task_runner = getattr(self, "_task_runner", None)
        task_runner_thread = getattr(self, "_task_runner_thread", None)
        loop = getattr(self, "_task_runner_loop", None)
        loop_ready = getattr(self, "_task_runner_loop_ready", None)
        if task_runner is None and task_runner_thread is None and loop is None:
            return

        if task_runner_thread is not None and task_runner_thread.is_alive():
            if loop_ready is not None and not loop_ready.wait(timeout=3.0):
                logger.warning("TaskRunner loop 尚未就绪，无法提交停止协程")

        if loop is not None and loop.is_running():
            if task_runner is not None and hasattr(task_runner, "stop"):
                future = asyncio.run_coroutine_threadsafe(task_runner.stop(), loop)
                try:
                    future.result(timeout=3.0)
                except concurrent.futures.TimeoutError:
                    logger.warning("TaskRunner stop 超时，将继续请求事件循环停止")
                except Exception as exc:
                    logger.warning("TaskRunner stop 异常: %s", exc)
            loop.call_soon_threadsafe(loop.stop)

        if task_runner_thread is not None and task_runner_thread.is_alive():
            task_runner_thread.join(timeout=3.0)
            if task_runner_thread.is_alive():
                logger.warning("TaskRunner 线程未在超时时间内退出")

        self._task_runner = None
        self._task_runner_loop = None
        self._task_runner_thread = None
        if loop_ready is not None:
            loop_ready.clear()
        logger.info("TaskRunner 已停止")

    def get_status(self) -> dict:
        """获取运行时状态摘要"""
        native_readiness = self.native_agent_readiness()
        status = {
            "service": "oha-yachiyo",
            "version": get_app_version(),
            "running": self._running,
            "uptime_seconds": self.uptime,
            "task_counts": self._state.get_task_counts(),
            "native_agent": native_readiness,
            "native_agent_ready": bool(native_readiness.get("ready")),
        }
        startup_diagnostic = self.startup_reconciliation_diagnostic
        if startup_diagnostic:
            status["startup_reconciliation"] = startup_diagnostic

        return status

    def is_native_agent_ready(self) -> bool:
        return bool(self.native_agent_readiness().get("ready"))

    def native_agent_readiness(self) -> dict:
        from apps.shell.agent_runtime import get_native_agent_readiness

        return get_native_agent_readiness()

    def main_chat_tool_policy(self) -> dict[str, Any]:
        """Tool policy used by the builtin main-chat Native Agent path."""
        from apps.shell.agent.tools.policy import (
            DAILY_DESKTOP_TOOL_NAMES,
            HIGH_RISK_DESKTOP_TOOL_NAMES,
            MEDIUM_RISK_BROWSER_TOOL_NAMES,
            MEDIUM_RISK_DESKTOP_TOOL_NAMES,
        )

        approval_required = {
            "workspace.write_patch": True,
            "terminal.run": True,
            "file.organize": True,
            **{
                tool: True
                for tool in (
                    *MEDIUM_RISK_DESKTOP_TOOL_NAMES,
                    *HIGH_RISK_DESKTOP_TOOL_NAMES,
                    *MEDIUM_RISK_BROWSER_TOOL_NAMES,
                )
            },
        }
        return {
            "allowed_tools": [
                "workspace.list",
                "workspace.read",
                "data.analyze",
                "workspace.write_patch",
                "file.organize",
                "terminal.run",
                *DAILY_DESKTOP_TOOL_NAMES,
                "memory.add",
                "memory.replace",
                "memory.remove",
                "future_task.schedule",
                "future_task.list",
                "future_task.cancel",
                "artifact.write",
            ],
            "approval_required": approval_required,
        }

    def main_chat_workspace_policy(self) -> dict[str, Any]:
        """Workspace policy for the builtin main-chat Native Agent path."""
        workdir = ""
        try:
            from apps.installer.workspace_init import get_workspace_status

            workspace = get_workspace_status()
            dirs = workspace.get("dirs") if isinstance(workspace.get("dirs"), dict) else {}
            if workspace.get("initialized") and dirs.get("projects"):
                workdir = str(dirs.get("projects") or "")
        except Exception:
            logger.debug("读取主聊天 workspace policy 失败", exc_info=True)
        return {
            "default_workdir": workdir,
            "readable_scopes": ["."],
            "writable_scopes": ["."],
        }

    def _refresh_if_ready_cache_is_stale(self) -> None:
        """Deprecated compatibility hook; Native Agent readiness is live data."""
        return

    def refresh_task_runner_executor(self) -> dict:
        """根据最新 Native Agent 状态切换 TaskRunner 后续任务使用的执行器。

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

    def switch_session(self, session_id: str) -> None:
        """切换到指定会话，更新运行时引用。"""
        from apps.core.chat_session import switch_chat_session
        self._chat_session = switch_chat_session(session_id)
        self._sync_executor_chat_session(self._chat_session)

    def start_new_session(self) -> str:
        """创建新的空会话，旧会话对象保持给后台任务继续写回。"""
        from apps.core.chat_session import reset_chat_session

        self._chat_session = reset_chat_session()
        self._sync_executor_chat_session(self._chat_session)
        return self._chat_session.session_id

    def _sync_executor_chat_session(self, chat_session: ChatSession) -> None:
        """通过执行器公开接口同步 chat_session。"""
        if self._task_runner is not None:
            executor = self._task_runner.executor
            set_chat_session = getattr(executor, "set_chat_session", None)
            if callable(set_chat_session):
                set_chat_session(chat_session)
                return
            if hasattr(executor, "chat_session"):
                setattr(executor, "chat_session", chat_session)
                return
            logger.debug(
                "当前执行器未提供公开的 chat_session 更新接口，跳过同步: executor=%s",
                type(executor).__name__,
            )

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
