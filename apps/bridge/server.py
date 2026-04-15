"""Bridge/API 服务器

内部 FastAPI 实例，运行在后台线程中。
仅供 Shell UI 层和 AstrBot 插件调用，不是产品本体。

连通方式：
  shell/app.py 调用 deps.set_runtime() 注入 Core Runtime 实例，
  bridge 路由通过 deps.get_runtime() 访问 core 层的 state/task 能力。
"""

from __future__ import annotations

import logging
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
        # Runtime 尚未注入（测试场景），跳过
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

# Bridge 运行状态：not_started | running | failed
_state: str = "not_started"


def get_bridge_state() -> str:
    """返回 Bridge 当前运行状态"""
    return _state


def start_bridge(host: str = "127.0.0.1", port: int = 8420) -> None:
    """启动 Bridge API（阻塞，应在后台线程调用）"""
    global _server, _state
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    _server = uvicorn.Server(config)
    _state = "running"
    logger.info("Bridge API 启动: http://%s:%d", host, port)
    try:
        _server.run()
    except Exception:
        _state = "failed"
        logger.exception("Bridge API 异常退出")
        raise


def stop_bridge() -> None:
    """请求停止 Bridge API"""
    if _server is not None:
        _server.should_exit = True
        logger.info("Bridge API 停止请求已发送")
