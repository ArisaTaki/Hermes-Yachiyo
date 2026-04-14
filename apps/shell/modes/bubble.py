"""气泡模式

轻量悬浮小窗口，显示状态摘要并提供打开主窗口 / 关闭入口。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.installer.workspace_init import get_workspace_status

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_BUBBLE_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 16px;
            line-height: 1.5;
            user-select: none;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 12px;
            border-bottom: 1px solid #333;
            margin-bottom: 12px;
        }
        .header .title { color: #6495ed; font-size: 1em; font-weight: 600; }
        .header .mode-tag {
            background: #2d2d54;
            color: #888;
            font-size: 0.75em;
            padding: 2px 8px;
            border-radius: 10px;
        }
        .status-block {
            background: #2d2d54;
            border-radius: 6px;
            padding: 10px 12px;
            margin-bottom: 10px;
        }
        .status-row {
            display: flex;
            justify-content: space-between;
            font-size: 0.85em;
            padding: 3px 0;
        }
        .status-row .label { color: #999; }
        .status-row .value { color: #e0e0e0; }
        .status-row .value.ok { color: #90ee90; }
        .status-row .value.warn { color: #ffd700; }
        .actions {
            display: flex;
            gap: 8px;
            margin-top: 12px;
        }
        .btn {
            flex: 1;
            background: #2d2d54;
            border: 1px solid #444;
            color: #ccc;
            padding: 8px 0;
            border-radius: 5px;
            font-size: 0.82em;
            cursor: pointer;
            text-align: center;
            transition: background 0.15s, border-color 0.15s;
        }
        .btn:hover { background: #3a3a6a; border-color: #6495ed; color: #fff; }
        .btn.primary { border-color: #6495ed; color: #6495ed; }
        .btn.primary:hover { background: #4a4a8a; color: #fff; }
        .btn.danger:hover { border-color: #ff6b6b; color: #ff6b6b; background: #2d2424; }
        .refresh-hint {
            text-align: center;
            font-size: 0.72em;
            color: #555;
            margin-top: 8px;
        }
    </style>
</head>
<body>
    <div class="header">
        <span class="title">💬 Hermes-Yachiyo</span>
        <span class="mode-tag">气泡模式</span>
    </div>

    <div class="status-block">
        <div class="status-row">
            <span class="label">Hermes Agent</span>
            <span class="value" id="hermes-status">检测中…</span>
        </div>
        <div class="status-row">
            <span class="label">工作空间</span>
            <span class="value" id="ws-status">检测中…</span>
        </div>
        <div class="status-row">
            <span class="label">运行时间</span>
            <span class="value" id="uptime">—</span>
        </div>
    </div>

    <div class="actions">
        <div class="btn primary" onclick="openMain()">🖥 主窗口</div>
        <div class="btn" onclick="refreshData()">↺ 刷新</div>
        <div class="btn danger" onclick="closeBubble()">✕</div>
    </div>
    <div class="refresh-hint" id="hint">正在加载…</div>

    <script>
    async function refreshData() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const d = await window.pywebview.api.get_bubble_data();
            if (d.error) { document.getElementById('hint').textContent = '数据获取失败'; return; }

            const hsEl = document.getElementById('hermes-status');
            hsEl.textContent = d.hermes.ready ? '✅ 已就绪' : '⚠️ ' + d.hermes.status;
            hsEl.className = 'value ' + (d.hermes.ready ? 'ok' : 'warn');

            const wsEl = document.getElementById('ws-status');
            wsEl.textContent = d.workspace.initialized ? '✅ 已初始化' : '⚠️ 未初始化';
            wsEl.className = 'value ' + (d.workspace.initialized ? 'ok' : 'warn');

            const sec = d.app.uptime_seconds;
            const m = Math.floor(sec / 60), s = Math.floor(sec % 60);
            document.getElementById('uptime').textContent = m > 0 ? m + '分' + s + '秒' : s + '秒';

            document.getElementById('hint').textContent = '已更新';
            setTimeout(function(){ document.getElementById('hint').textContent = ''; }, 2000);
        } catch(e) {
            document.getElementById('hint').textContent = '加载失败';
        }
    }
    async function openMain() {
        try {
            if (window.pywebview && window.pywebview.api)
                await window.pywebview.api.open_main_window();
        } catch(e) {}
    }
    async function closeBubble() {
        try {
            if (window.pywebview && window.pywebview.api)
                await window.pywebview.api.close_bubble();
        } catch(e) {}
    }

    document.addEventListener('DOMContentLoaded', function() {
        if (window.pywebview) refreshData();
        setInterval(refreshData, 15000);
    });
    window.addEventListener('pywebviewready', function() { refreshData(); });
    </script>
</body>
</html>
"""


class BubbleWindowAPI:
    """气泡模式 WebView API"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._bubble_window = None  # 由 run() 注入

    def get_bubble_data(self) -> Dict[str, Any]:
        """获取气泡状态摘要"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            hermes_info = status.get("hermes", {})
            return {
                "hermes": {
                    "status": hermes_info.get("install_status", "unknown"),
                    "ready": self._runtime.is_hermes_ready(),
                },
                "workspace": {
                    "initialized": workspace.get("initialized", False),
                },
                "app": {
                    "uptime_seconds": round(status.get("uptime_seconds", 0), 1),
                    "version": status.get("version", "0.1.0"),
                },
            }
        except Exception as e:
            logger.error("获取气泡数据失败: %s", e)
            return {"error": str(e)}

    def open_main_window(self) -> None:
        """在当前 pywebview 会话中打开完整主窗口"""
        try:
            import webview  # type: ignore[import]
            from apps.shell.window import _STATUS_HTML

            html = _STATUS_HTML.replace("{{HOST}}", self._config.bridge_host).replace(
                "{{PORT}}", str(self._config.bridge_port)
            )
            # 创建主窗口，共享当前会话；主窗口使用 MainWindowAPI 需独立 api，
            # 此处直接展示只读仪表盘（不绑定可写 API）供用户查看状态。
            webview.create_window(
                title="Hermes-Yachiyo — 主窗口",
                html=html,
                width=560,
                height=520,
                resizable=True,
            )
        except Exception as e:
            logger.error("打开主窗口失败: %s", e)

    def close_bubble(self) -> None:
        """关闭气泡窗口"""
        try:
            if self._bubble_window is not None:
                self._bubble_window.destroy()
        except Exception as e:
            logger.error("关闭气泡窗口失败: %s", e)


def run(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """运行气泡模式（阻塞主线程）"""
    logger.info("启动气泡模式")
    try:
        import webview  # type: ignore[import]

        api = BubbleWindowAPI(runtime, config)
        win = webview.create_window(
            title="Hermes-Yachiyo",
            html=_BUBBLE_HTML,
            width=320,
            height=280,
            resizable=False,
            on_top=True,
        )
        api._bubble_window = win
        webview.start(api=api, debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，气泡模式无法展示")


