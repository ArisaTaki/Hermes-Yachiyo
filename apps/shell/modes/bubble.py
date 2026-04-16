"""气泡模式

轻量悬浮小窗口，显示状态摘要 + 聊天入口 + 打开主窗口 / 关闭入口。
共享 ChatSession，三模式消息互通。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.installer.workspace_init import get_workspace_status
from apps.shell.chat_api import ChatAPI
from apps.shell.integration_status import get_integration_snapshot

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
            padding: 12px;
            line-height: 1.5;
            user-select: none;
            height: 100vh;
            display: flex;
            flex-direction: column;
        }
        .header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding-bottom: 8px;
            border-bottom: 1px solid #333;
            margin-bottom: 8px;
            flex-shrink: 0;
        }
        .header .title { color: #6495ed; font-size: 0.95em; font-weight: 600; }
        .header .mode-tag {
            background: #2d2d54;
            color: #888;
            font-size: 0.7em;
            padding: 2px 6px;
            border-radius: 10px;
        }
        /* 聊天区域 */
        .chat-area {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 0;
        }
        .chat-messages {
            flex: 1;
            overflow-y: auto;
            background: #12122a;
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 8px;
            font-size: 0.82em;
            min-height: 60px;
        }
        .chat-msg {
            margin-bottom: 6px;
            padding: 5px 8px;
            border-radius: 5px;
            line-height: 1.4;
        }
        .chat-msg.user {
            background: #3a4a7a;
            margin-left: 15px;
            border-left: 2px solid #6495ed;
        }
        .chat-msg.assistant {
            background: #2a3a3a;
            margin-right: 15px;
            border-left: 2px solid #90ee90;
        }
        .chat-msg.system {
            background: #2a2a3a;
            text-align: center;
            color: #666;
            font-size: 0.9em;
        }
        .chat-msg .content { color: #ddd; white-space: pre-wrap; word-break: break-word; }
        .chat-msg.pending .content { color: #aaa; }
        .chat-msg.error .content { color: #ffaaaa; }
        .chat-input-row {
            display: flex;
            gap: 6px;
            flex-shrink: 0;
        }
        .chat-input {
            flex: 1;
            background: #2d2d54;
            color: #e0e0e0;
            border: 1px solid #444;
            border-radius: 5px;
            padding: 7px 10px;
            font-size: 0.85em;
            outline: none;
        }
        .chat-input:focus { border-color: #6495ed; }
        .chat-input::placeholder { color: #555; }
        .chat-send {
            background: #4a6a9a;
            border: none;
            color: #fff;
            padding: 7px 12px;
            border-radius: 5px;
            cursor: pointer;
            font-size: 0.85em;
        }
        .chat-send:hover { background: #5a7aaa; }
        .chat-send:disabled { background: #3a3a5a; color: #666; cursor: not-allowed; }
        /* 底部工具栏 */
        .actions {
            display: flex;
            gap: 6px;
            margin-top: 8px;
            flex-shrink: 0;
        }
        .btn {
            flex: 1;
            background: #2d2d54;
            border: 1px solid #444;
            color: #ccc;
            padding: 6px 0;
            border-radius: 5px;
            font-size: 0.78em;
            cursor: pointer;
            text-align: center;
        }
        .btn:hover { background: #3a3a6a; border-color: #6495ed; color: #fff; }
        .btn.primary { border-color: #6495ed; color: #6495ed; }
        .btn.danger:hover { border-color: #ff6b6b; color: #ff6b6b; background: #2d2424; }
        .status-row {
            font-size: 0.72em;
            color: #555;
            text-align: center;
            margin-top: 4px;
            flex-shrink: 0;
        }
        .status-row .ok { color: #6a9a6a; }
    </style>
</head>
<body>
    <div class="header">
        <span class="title">💬 Yachiyo</span>
        <span class="mode-tag">气泡</span>
    </div>

    <div class="chat-area">
        <div class="chat-messages" id="chat-messages">
            <div class="chat-msg system"><span class="content">发送消息开始对话</span></div>
        </div>
        <div class="chat-input-row">
            <input type="text" class="chat-input" id="chat-input" 
                   placeholder="输入消息..." 
                   onkeypress="if(event.key==='Enter') sendMessage()">
            <button class="chat-send" id="chat-send" onclick="sendMessage()">发送</button>
        </div>
    </div>

    <div class="actions">
        <div class="btn primary" onclick="openMain()">🖥 主窗口</div>
        <div class="btn" onclick="clearChat()">清空</div>
        <div class="btn danger" onclick="closeBubble()">✕</div>
    </div>
    <div class="status-row">
        <span id="hermes-status">—</span> · <span class="ok" id="executor-info">—</span>
    </div>

    <script>
    let isSending = false;
    let pollTimer = null;

    async function sendMessage() {{
        if (isSending) return;
        const input = document.getElementById('chat-input');
        const text = (input.value || '').trim();
        if (!text) return;

        isSending = true;
        document.getElementById('chat-send').disabled = true;
        input.disabled = true;

        try {{
            if (!window.pywebview || !window.pywebview.api) throw new Error('API 不可用');
            const r = await window.pywebview.api.send_message(text);
            if (!r.ok) throw new Error(r.error || '发送失败');
            input.value = '';
            await refreshMessages();
            startPolling();
        }} catch(e) {{
            console.error('sendMessage error:', e);
        }} finally {{
            isSending = false;
            document.getElementById('chat-send').disabled = false;
            input.disabled = false;
            input.focus();
        }}
    }}

    async function refreshMessages() {{
        try {{
            if (!window.pywebview || !window.pywebview.api) return;
            const r = await window.pywebview.api.get_messages(20);
            if (!r.ok) return;
            renderMessages(r.messages);
            if (!r.is_processing) stopPolling();
        }} catch(e) {{}}
    }}

    function renderMessages(messages) {{
        const container = document.getElementById('chat-messages');
        if (!messages || messages.length === 0) {{
            container.innerHTML = '<div class="chat-msg system"><span class="content">发送消息开始对话</span></div>';
            return;
        }}
        // 只显示最近几条
        const recent = messages.slice(-6);
        let html = '';
        for (const m of recent) {{
            const cls = m.role + (m.status === 'failed' ? ' error' : (m.status === 'pending' || m.status === 'processing' ? ' pending' : ''));
            html += '<div class="chat-msg ' + cls + '"><span class="content">' + escapeHtml(m.content) + '</span></div>';
        }}
        container.innerHTML = html;
        container.scrollTop = container.scrollHeight;
    }}

    function escapeHtml(text) {{
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }}

    function startPolling() {{
        if (pollTimer) return;
        pollTimer = setInterval(refreshMessages, 1500);
    }}

    function stopPolling() {{
        if (pollTimer) {{ clearInterval(pollTimer); pollTimer = null; }}
    }}

    async function clearChat() {{
        try {{
            if (window.pywebview && window.pywebview.api) {{
                await window.pywebview.api.clear_session();
                await refreshMessages();
            }}
        }} catch(e) {{}}
    }}

    async function openMain() {{
        try {{
            if (window.pywebview && window.pywebview.api)
                await window.pywebview.api.open_main_window();
        }} catch(e) {{}}
    }}

    async function closeBubble() {{
        try {{
            if (window.pywebview && window.pywebview.api)
                await window.pywebview.api.close_bubble();
        }} catch(e) {{}}
    }}

    async function loadStatus() {{
        try {{
            if (!window.pywebview || !window.pywebview.api) return;
            const d = await window.pywebview.api.get_bubble_data();
            if (d.error) return;
            document.getElementById('hermes-status').textContent = d.hermes.ready ? '✅ Hermes' : '⚠️ Hermes';
            const ex = await window.pywebview.api.get_executor_info();
            document.getElementById('executor-info').textContent = ex.executor === 'HermesExecutor' ? '🚀 Hermes' : '🔬 模拟';
        }} catch(e) {{}}
    }}

    document.addEventListener('DOMContentLoaded', function() {{
        if (window.pywebview) {{ refreshMessages(); loadStatus(); }}
    }});
    window.addEventListener('pywebviewready', function() {{ refreshMessages(); loadStatus(); }});
    </script>
</body>
</html>
"""


class BubbleWindowAPI:
    """气泡模式 WebView API（含聊天功能）"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_api = ChatAPI(runtime)
        self._bubble_window = None  # 由 run() 注入
        self._bridge_boot_config = {
            "enabled": config.bridge_enabled,
            "host": config.bridge_host,
            "port": config.bridge_port,
        }

    def _bridge_status(self) -> str:
        """组合 config.bridge_enabled 与实际运行状态，返回四状态字符串。"""
        snap = get_integration_snapshot(self._config, self._bridge_boot_config)
        return snap.bridge.state

    def get_bubble_data(self) -> Dict[str, Any]:
        """获取气泡状态摘要"""
        try:
            status = self._runtime.get_status()
            workspace = get_workspace_status()
            snap = get_integration_snapshot(self._config, self._bridge_boot_config)
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
                "bridge": {
                    "enabled": self._config.bridge_enabled,
                    "running": snap.bridge.state,
                    "addr": f"{self._config.bridge_host}:{self._config.bridge_port}",
                    "config_dirty": snap.bridge.config_dirty,
                },
                "astrbot": snap.astrbot.to_dict(),
            }
        except Exception as e:
            logger.error("获取气泡数据失败: %s", e)
            return {"error": str(e)}

    # ── 聊天 API（委托 ChatAPI）──────────────────────────────────────────────

    def send_message(self, text: str) -> Dict[str, Any]:
        """发送用户消息"""
        return self._chat_api.send_message(text)

    def get_messages(self, limit: int = 20) -> Dict[str, Any]:
        """获取消息列表"""
        return self._chat_api.get_messages(limit)

    def clear_session(self) -> Dict[str, Any]:
        """清空会话"""
        return self._chat_api.clear_session()

    def get_executor_info(self) -> Dict[str, Any]:
        """获取当前执行器信息"""
        runner = self._runtime.task_runner
        if runner is None:
            return {"executor": "none", "available": False}
        return {"executor": runner.executor.name, "available": True}

    # ── 窗口操作 ────────────────────────────────────────────────────────────

    def open_main_window(self) -> None:
        """在当前 pywebview 会话中打开完整主窗口"""
        try:
            import webview  # type: ignore[import]
            from apps.shell.window import _STATUS_HTML

            html = _STATUS_HTML.replace("{{HOST}}", self._config.bridge_host).replace(
                "{{PORT}}", str(self._config.bridge_port)
            )
            webview.create_window(
                title="Hermes-Yachiyo — 主窗口",
                html=html,
                width=560,
                height=620,
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
            height=380,  # 增加高度以容纳聊天区域
            resizable=False,
            on_top=True,
            js_api=api,
        )
        api._bubble_window = win
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，气泡模式无法展示")


