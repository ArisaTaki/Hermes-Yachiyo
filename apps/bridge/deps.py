"""Bridge 依赖注入

将 Runtime 引用独立于 server.py，避免路由模块与 server.py 之间的循环导入。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

_runtime: HermesRuntime | None = None


def set_runtime(runtime: "HermesRuntime") -> None:
    """由 Shell 启动时注入 Core Runtime 实例"""
    global _runtime
    _runtime = runtime


def get_runtime() -> "HermesRuntime":
    """供 Bridge 路由获取 Core Runtime（必须先调用 set_runtime）"""
    if _runtime is None:
        raise RuntimeError("Bridge: Runtime 尚未注入，请先调用 set_runtime()")
    return _runtime
