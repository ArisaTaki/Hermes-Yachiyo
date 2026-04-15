"""AstrBot handler 输出格式测试

使用 mock HTTP 响应测试 handler 的输出格式、错误处理和边界覆盖。
不依赖真实 Bridge 运行。
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

# ── 注册 astrbot-plugin 为可导入包 ─────────────────────────
_PLUGIN_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "integrations",
    "astrbot-plugin",
)


def _register_plugin_package():
    """将 integrations/astrbot-plugin 注册为 astrbot_plugin 包"""
    if "astrbot_plugin" in sys.modules:
        return

    spec = importlib.util.spec_from_file_location(
        "astrbot_plugin",
        os.path.join(_PLUGIN_DIR, "__init__.py"),
        submodule_search_locations=[_PLUGIN_DIR],
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["astrbot_plugin"] = mod
    spec.loader.exec_module(mod)

    for sub_name in ("config", "api_client", "command_router", "main"):
        sub_path = os.path.join(_PLUGIN_DIR, f"{sub_name}.py")
        if os.path.exists(sub_path):
            sub_spec = importlib.util.spec_from_file_location(
                f"astrbot_plugin.{sub_name}", sub_path
            )
            sub_mod = importlib.util.module_from_spec(sub_spec)
            sys.modules[f"astrbot_plugin.{sub_name}"] = sub_mod
            sub_spec.loader.exec_module(sub_mod)

    handlers_dir = os.path.join(_PLUGIN_DIR, "handlers")
    h_spec = importlib.util.spec_from_file_location(
        "astrbot_plugin.handlers",
        os.path.join(handlers_dir, "__init__.py"),
        submodule_search_locations=[handlers_dir],
    )
    h_mod = importlib.util.module_from_spec(h_spec)
    sys.modules["astrbot_plugin.handlers"] = h_mod
    h_spec.loader.exec_module(h_mod)

    for h_name in ("utils", "status", "tasks", "do", "check", "cancel",
                    "screen", "window", "codex"):
        h_path = os.path.join(handlers_dir, f"{h_name}.py")
        if os.path.exists(h_path):
            hs = importlib.util.spec_from_file_location(
                f"astrbot_plugin.handlers.{h_name}", h_path
            )
            hm = importlib.util.module_from_spec(hs)
            sys.modules[f"astrbot_plugin.handlers.{h_name}"] = hm
            hs.loader.exec_module(hm)


_register_plugin_package()

from astrbot_plugin.config import PluginConfig
from astrbot_plugin.handlers import utils
from astrbot_plugin.main import on_y_command, parse_y_command


# ── 公共 fixtures ────────────────────────────────────────

@pytest.fixture()
def config():
    return PluginConfig(hermes_url="http://test:8420")


# ── parse_y_command ──────────────────────────────────────

class TestParseYCommand:
    def test_basic(self):
        sub, args = parse_y_command("/y status")
        assert sub == "status"
        assert args == ""

    def test_with_args(self):
        sub, args = parse_y_command("/y do 测试任务描述")
        assert sub == "do"
        assert args == "测试任务描述"

    def test_no_sub(self):
        sub, args = parse_y_command("/y")
        assert sub == ""
        assert args == ""

    def test_case_insensitive(self):
        sub, args = parse_y_command("/y STATUS")
        assert sub == "status"


# ── ACL 权限测试 ─────────────────────────────────────────

class TestACL:
    @pytest.mark.asyncio
    async def test_unauthorized_rejected(self):
        cfg = PluginConfig(allowed_senders=["123456"])
        result = await on_y_command("/y status", sender_id="999", config=cfg)
        assert "无权限" in result

    @pytest.mark.asyncio
    async def test_authorized_allowed(self):
        cfg = PluginConfig(allowed_senders=["123456"])
        with patch(
            "astrbot_plugin.command_router.route",
            new_callable=AsyncMock,
            return_value="ok",
        ):
            result = await on_y_command("/y help", sender_id="123456", config=cfg)
            assert "命令列表" in result

    @pytest.mark.asyncio
    async def test_empty_acl_allows_all(self):
        cfg = PluginConfig(allowed_senders=[])
        result = await on_y_command("/y help", sender_id="anyone", config=cfg)
        assert "命令列表" in result


# ── 帮助和未知命令 ───────────────────────────────────────

class TestHelpAndUnknown:
    @pytest.mark.asyncio
    async def test_help(self):
        result = await on_y_command("/y help")
        assert "命令列表" in result
        assert "/y status" in result

    @pytest.mark.asyncio
    async def test_empty_sub(self):
        result = await on_y_command("/y")
        assert "命令列表" in result

    @pytest.mark.asyncio
    async def test_unknown_command(self):
        result = await on_y_command("/y xyz")
        assert "未知命令" in result


# ── Handler 输出格式 ─────────────────────────────────────

class TestStatusHandler:
    @pytest.mark.asyncio
    async def test_output_format(self, config):
        mock_data = {
            "version": "0.1.0",
            "uptime_seconds": 3661,
            "hermes_ready": True,
            "task_counts": {"pending": 2, "running": 1, "completed": 5, "failed": 0},
        }
        with patch(
            "astrbot_plugin.handlers.status.HermesClient"
        ) as MockClient:
            MockClient.return_value.get_status = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.status import handle
            result = await handle("", config)

        assert "📊" in result
        assert "v0.1.0" in result
        assert "1h" in result
        assert "已就绪" in result


class TestDoHandler:
    @pytest.mark.asyncio
    async def test_create_task(self, config):
        mock_data = {
            "task": {
                "task_id": "abc12345def0",
                "description": "写单元测试",
                "status": "pending",
            }
        }
        with patch(
            "astrbot_plugin.handlers.do.HermesClient"
        ) as MockClient:
            MockClient.return_value.create_task = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.do import handle
            result = await handle("写单元测试", config)

        assert "✅ 任务已提交" in result
        assert "abc12345" in result
        assert "/y check" in result

    @pytest.mark.asyncio
    async def test_empty_description(self, config):
        from astrbot_plugin.handlers.do import handle
        result = await handle("", config)
        assert "用法" in result


class TestCheckHandler:
    @pytest.mark.asyncio
    async def test_check_completed_task(self, config):
        mock_data = {
            "task": {
                "task_id": "abc123",
                "description": "测试",
                "status": "completed",
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T10:05:00Z",
                "result": "执行成功",
                "error": None,
            }
        }
        with patch(
            "astrbot_plugin.handlers.check.HermesClient"
        ) as MockClient:
            MockClient.return_value.get_task = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.check import handle
            result = await handle("abc123", config)

        assert "🔍" in result
        assert "已完成" in result
        assert "执行成功" in result

    @pytest.mark.asyncio
    async def test_check_failed_task(self, config):
        mock_data = {
            "task": {
                "task_id": "fail1",
                "description": "失败任务",
                "status": "failed",
                "created_at": "2025-01-15T10:00:00Z",
                "updated_at": "2025-01-15T10:01:00Z",
                "result": None,
                "error": "命令超时",
            }
        }
        with patch(
            "astrbot_plugin.handlers.check.HermesClient"
        ) as MockClient:
            MockClient.return_value.get_task = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.check import handle
            result = await handle("fail1", config)

        assert "已失败" in result
        assert "命令超时" in result

    @pytest.mark.asyncio
    async def test_empty_id(self, config):
        from astrbot_plugin.handlers.check import handle
        result = await handle("", config)
        assert "用法" in result


class TestCancelHandler:
    @pytest.mark.asyncio
    async def test_cancel(self, config):
        mock_data = {
            "task": {
                "task_id": "c1",
                "description": "取消测试",
                "status": "cancelled",
            }
        }
        with patch(
            "astrbot_plugin.handlers.cancel.HermesClient"
        ) as MockClient:
            MockClient.return_value.cancel_task = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.cancel import handle
            result = await handle("c1", config)

        assert "🚫" in result
        assert "已取消" in result

    @pytest.mark.asyncio
    async def test_empty_id(self, config):
        from astrbot_plugin.handlers.cancel import handle
        result = await handle("", config)
        assert "用法" in result


class TestTasksHandler:
    @pytest.mark.asyncio
    async def test_empty_list(self, config):
        mock_data = {"tasks": [], "total": 0}
        with patch(
            "astrbot_plugin.handlers.tasks.HermesClient"
        ) as MockClient:
            MockClient.return_value.list_tasks = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.tasks import handle
            result = await handle("", config)

        assert "没有任务" in result

    @pytest.mark.asyncio
    async def test_with_tasks(self, config):
        mock_data = {
            "tasks": [
                {
                    "task_id": "t1abc",
                    "description": "测试任务一",
                    "status": "pending",
                    "updated_at": "2025-01-15T10:00:00Z",
                },
                {
                    "task_id": "t2def",
                    "description": "测试任务二",
                    "status": "completed",
                    "updated_at": "2025-01-15T11:00:00Z",
                },
            ],
            "total": 2,
        }
        with patch(
            "astrbot_plugin.handlers.tasks.HermesClient"
        ) as MockClient:
            MockClient.return_value.list_tasks = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.tasks import handle
            result = await handle("", config)

        assert "共 2 条" in result


class TestCodexHandler:
    @pytest.mark.asyncio
    async def test_placeholder(self, config):
        from astrbot_plugin.handlers.codex import handle
        result = await handle("write code", config)
        assert "即将推出" in result

    @pytest.mark.asyncio
    async def test_empty_args(self, config):
        from astrbot_plugin.handlers.codex import handle
        result = await handle("", config)
        assert "用法" in result


class TestScreenHandler:
    @pytest.mark.asyncio
    async def test_output(self, config):
        mock_data = {
            "width": 1920,
            "height": 1080,
            "format": "png",
            "captured_at": "2025-01-15T10:00:00Z",
            "image_base64": "abc",
        }
        with patch(
            "astrbot_plugin.handlers.screen.HermesClient"
        ) as MockClient:
            MockClient.return_value.get_screen = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.screen import handle
            result = await handle("", config)

        assert "📸" in result
        assert "1920" in result


class TestWindowHandler:
    @pytest.mark.asyncio
    async def test_output(self, config):
        mock_data = {
            "title": "终端 — bash",
            "app_name": "Terminal",
            "pid": 1234,
            "queried_at": "2025-01-15T10:00:00Z",
        }
        with patch(
            "astrbot_plugin.handlers.window.HermesClient"
        ) as MockClient:
            MockClient.return_value.get_active_window = AsyncMock(return_value=mock_data)
            from astrbot_plugin.handlers.window import handle
            result = await handle("", config)

        assert "🪟" in result
        assert "Terminal" in result
        assert "1234" in result


# ── 错误格式化测试 ───────────────────────────────────────

class TestErrorFormatting:
    def test_runtime_error_with_status_code(self):
        exc = RuntimeError("[404] 任务 xxx 不存在")
        result = utils.fmt_error(exc, "check")
        assert "资源不存在" in result

    def test_runtime_error_500(self):
        exc = RuntimeError("[500] 内部错误")
        result = utils.fmt_error(exc, "status")
        assert "内部错误" in result

    def test_runtime_error_503(self):
        exc = RuntimeError("[503] Agent 未就绪")
        result = utils.fmt_error(exc)
        assert "未就绪" in result

    def test_generic_runtime_error(self):
        exc = RuntimeError("something went wrong")
        result = utils.fmt_error(exc)
        assert "执行失败" in result

    def test_unknown_exception(self):
        exc = ValueError("bad value")
        result = utils.fmt_error(exc)
        assert "未知错误" in result

    def test_status_utils(self):
        assert "等待中" in utils.fmt_status("pending")
        assert "❓" in utils.fmt_status("unknown_status")
        assert utils.fmt_status_icon("completed") == "✅"

    def test_uptime_format(self):
        assert utils.fmt_uptime(5) == "5s"
        assert utils.fmt_uptime(65) == "1m 5s"
        assert utils.fmt_uptime(3661) == "1h 1m 1s"

    def test_dt_format(self):
        assert utils.fmt_dt("2025-01-15T10:30:45Z") == "01-15 10:30:45"
        assert utils.fmt_dt("") == "—"
        assert utils.fmt_dt(None) == "—"
