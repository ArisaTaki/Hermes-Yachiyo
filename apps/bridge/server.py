"""Bridge/API 服务器

内部 FastAPI 实例，运行在后台线程中。
仅供 Shell UI 层和 AstrBot 插件调用，不是产品本体。

连通方式：
  shell/app.py 调用 deps.set_runtime() 注入 Core Runtime 实例，
  bridge 路由通过 deps.get_runtime() 访问 core 层的 state/task 能力。
"""

from __future__ import annotations

import logging
import threading
import time
from contextlib import asynccontextmanager
from typing import AsyncIterator

import uvicorn
from fastapi import FastAPI

from apps.bridge.routes import hermes, screen, status, system, tasks

logger = logging.getLogger(__name__)


@asynccontextmanager
async def _lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Bridge 启动/停止时管理后台 TaskRunner"""
    from apps.bridge.deps import get_runtime
    from apps.core.executor import select_executor
    from apps.core.task_runner import TaskRunner

    runner: TaskRunner | None = None
    try:
        rt = get_runtime()
        runner = TaskRunner(rt.state, executor=select_executor(rt))
        await runner.start()
    except RuntimeError:
        logger.warning("Bridge lifespan: Runtime 未注入，TaskRunner 跳过启动")

    yield

    if runner is not None:
        await runner.stop()


app = FastAPI(
    title="Hermes-Yachiyo Bridge",
    description="内部通信 API，非产品本体",
    version="0.1.0",
    lifespan=_lifespan,
)

app.include_router(status.router)
app.include_router(tasks.router)
app.include_router(screen.router)
app.include_router(system.router)
app.include_router(hermes.router)

_server: uvicorn.Server | None = None
_bridge_thread: threading.Thread | None = None

# Bridge 运行状态：not_started | running | failed
_state: str = "not_started"
# 当前实际使用的 host/port
_running_host: str = ""
_running_port: int = 0


def get_bridge_state() -> str:
    """返回 Bridge 当前运行状态"""
    return _state


def get_running_config() -> dict[str, object]:
    """返回 Bridge 当前运行时使用的配置。"""
    return {"host": _running_host, "port": _running_port}


def start_bridge(host: str = "127.0.0.1", port: int = 8420) -> None:
    """启动 Bridge API（阻塞，应在后台线程调用）"""
    global _server, _state, _running_host, _running_port
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    _server = uvicorn.Server(config)
    _state = "running"
    _running_host = host
    _running_port = port
    logger.info("Bridge API 启动: http://%s:%d", host, port)
    try:
        _server.run()
    except Exception:
        _state = "failed"
        logger.exception("Bridge API 异常退出")
        raise
    finally:
        # uvicorn.run() 正常退出（被 should_exit 停止）时也走到这里
        if _state == "running":
            _state = "not_started"


def stop_bridge() -> None:
    """请求停止 Bridge API"""
    if _server is not None:
        _server.should_exit = True
        logger.info("Bridge API 停止请求已发送")


def restart_bridge(host: str, port: int) -> dict[str, object]:
    """停止当前 Bridge 并用新配置重启。

    在调用者线程中执行停止，然后启动新的后台线程。
    返回操作结果字典，供 UI 层消费。
    """
    global _bridge_thread, _state

    # 1. 停止旧实例
    if _server is not None and _state == "running":
        logger.info("正在停止 Bridge 以便重启...")
        stop_bridge()
        # 等待旧线程退出（最多 5 秒）
        if _bridge_thread is not None and _bridge_thread.is_alive():
            _bridge_thread.join(timeout=5.0)
            if _bridge_thread.is_alive():
                logger.warning("Bridge 旧线程未在 5 秒内退出")
                return {
                    "ok": False,
                    "error": "Bridge 停止超时，请稍后重试或重启应用",
                }

    # 2. 端口基本校验
    if not (1024 <= port <= 65535):
        return {"ok": False, "error": f"端口 {port} 不在有效范围 (1024-65535)"}

    # 3. 启动新线程
    _state = "not_started"
    _bridge_thread = threading.Thread(
        target=start_bridge,
        kwargs={"host": host, "port": port},
        daemon=True,
        name="bridge-api",
    )
    _bridge_thread.start()

    # 4. 等待短暂时间确认启动成功
    time.sleep(0.8)
    if _state == "running":
        logger.info("Bridge 已重启: http://%s:%d", host, port)
        return {"ok": True, "host": host, "port": port}
    elif _state == "failed":
        return {"ok": False, "error": f"Bridge 启动失败，请检查端口 {port} 是否被占用"}
    else:
        # 可能仍在启动中
        return {"ok": True, "host": host, "port": port, "pending": True}
