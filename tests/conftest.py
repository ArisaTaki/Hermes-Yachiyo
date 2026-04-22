"""测试基础设施

提供公共 fixtures、mock 辅助、模块级 mock 注入。
"""

from __future__ import annotations

import sys
import types
from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest


# ── 在任何 apps.bridge.server 导入前注入 mock ──────────────────────
# 测试环境可能没有 uvicorn/fastapi，需要在 conftest 阶段完成注入。

def _ensure_bridge_mocks() -> None:
    """为 apps.bridge.server 及其依赖注入最小 mock 模块。"""
    class _MockMiddlewareEntry:
        def __init__(self, cls, **options):
            self.cls = cls
            self.options = options

    class _MockFastAPI:
        def __init__(self, **kw):
            self.routes = []
            self.user_middleware = []

        def include_router(self, r):
            return None

        def add_middleware(self, cls, **options):
            self.user_middleware.append(_MockMiddlewareEntry(cls, **options))

    mocks_needed = {
        "uvicorn": {"Config": type("Config", (), {"__init__": lambda s, *a, **kw: None}),
                    "Server": type("Server", (), {"__init__": lambda s, *a: None,
                                                   "run": lambda s: None,
                                                   "should_exit": False})},
        "fastapi": {"FastAPI": _MockFastAPI,
                    "APIRouter": type("APIRouter", (), {"__init__": lambda s, **kw: None})},
        "fastapi.middleware.cors": {"CORSMiddleware": type("CORSMiddleware", (), {})},
    }
    route_modules = [
        "apps.bridge.routes",
        "apps.bridge.routes.hermes",
        "apps.bridge.routes.screen",
        "apps.bridge.routes.status",
        "apps.bridge.routes.system",
        "apps.bridge.routes.tasks",
    ]
    dep_modules = [
        "apps.bridge.deps",
    ]

    for name, attrs in mocks_needed.items():
        if name not in sys.modules:
            mod = types.ModuleType(name)
            for k, v in attrs.items():
                setattr(mod, k, v)
            sys.modules[name] = mod

    for name in route_modules:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            mod.router = MagicMock()  # type: ignore[attr-defined]
            if name == "apps.bridge.routes":
                mod.__path__ = []  # type: ignore[attr-defined]
            sys.modules[name] = mod

    for name in dep_modules:
        if name not in sys.modules:
            mod = types.ModuleType(name)
            sys.modules[name] = mod


_ensure_bridge_mocks()


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture()
def app_state():
    """创建干净的 AppState 实例。"""
    from apps.core.state import AppState
    return AppState()


@pytest.fixture()
def sample_config():
    """创建默认 AppConfig 实例。"""
    from apps.shell.config import AppConfig
    return AppConfig()
