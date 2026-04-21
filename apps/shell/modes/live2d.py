"""Live2D 模式。

当前阶段先实现“角色聊天壳”而不实现真正 renderer：
- 角色舞台 + 最近回复泡泡
- 最小输入入口
- 打开完整 Chat Window 入口
- 统一读取 ChatSession 状态
- 保留未来 renderer / moc3 / 动作系统接入位
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.bridge.server import get_bridge_state
from apps.installer.workspace_init import get_workspace_status
from apps.shell.chat_bridge import ChatBridge
from apps.shell.mode_settings import _serialize_summary

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_LIVE2D_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo — Live2D Mode</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: linear-gradient(180deg, #17192b 0%, #111320 100%);
            color: #eef1ff;
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        .stage {
            position: relative;
            height: 250px;
            flex-shrink: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: radial-gradient(circle at top, rgba(97, 129, 255, 0.22), transparent 55%), #13162a;
            border-bottom: 1px solid rgba(255,255,255,0.06);
        }
        .badge {
            position: absolute;
            top: 12px;
            right: 12px;
            font-size: 0.72rem;
            color: #c0c8ef;
            border: 1px solid rgba(126, 152, 255, 0.28);
            background: rgba(20, 22, 40, 0.75);
            border-radius: 999px;
            padding: 4px 8px;
        }
        .model-status {
            position: absolute;
            top: 12px;
            left: 12px;
            font-size: 0.72rem;
            color: #c6cefa;
            background: rgba(20, 22, 40, 0.82);
            border-radius: 999px;
            padding: 4px 8px;
        }
        .character {
            width: 150px;
            height: 150px;
            border-radius: 50%;
            display: grid;
            place-items: center;
            font-size: 4rem;
            background: linear-gradient(180deg, rgba(112, 140, 255, 0.36), rgba(52, 68, 122, 0.3));
            box-shadow: 0 16px 40px rgba(0, 0, 0, 0.28);
            animation: float 3s ease-in-out infinite;
        }
        @keyframes float {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-8px); }
        }
        @keyframes thinking-dot {
            0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-1px); }
        }
        .reply-bubble {
            position: absolute;
            max-width: 280px;
            bottom: 24px;
            right: 24px;
            background: rgba(20, 24, 40, 0.94);
            border: 1px solid rgba(126, 152, 255, 0.24);
            border-radius: 14px;
            padding: 10px 12px;
            color: #dde4ff;
            font-size: 0.84rem;
            line-height: 1.45;
            box-shadow: 0 12px 24px rgba(0, 0, 0, 0.2);
        }
        .reply-bubble.hidden { display: none; }
        .panel {
            flex: 1;
            min-height: 0;
            display: flex;
            flex-direction: column;
            gap: 10px;
            padding: 12px;
        }
        .summary {
            flex: 1;
            min-height: 0;
            overflow-y: auto;
            background: rgba(12, 14, 24, 0.72);
            border-radius: 14px;
            padding: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .message {
            padding: 10px 12px;
            border-radius: 12px;
            line-height: 1.5;
            font-size: 0.84rem;
        }
        .message.user { background: rgba(91, 122, 230, 0.16); margin-left: 36px; }
        .message.assistant { background: rgba(68, 130, 88, 0.18); margin-right: 36px; }
        .message.system { background: rgba(58, 61, 80, 0.72); color: #b0b6d8; }
        .message.failed { color: #ffaaaa; }
        .message.processing { color: #ffd36a; }
        .thinking { display: inline-flex; align-items: center; gap: 2px; }
        .thinking .dot {
            animation: thinking-dot 1.2s ease-in-out infinite;
            display: inline-block;
        }
        .thinking .dot:nth-child(2) { animation-delay: 0.15s; }
        .thinking .dot:nth-child(3) { animation-delay: 0.3s; }
        .empty-hint {
            text-align: center;
            color: #7d85ad;
            padding: 18px 8px;
            font-size: 0.84rem;
        }
        .input-row {
            display: flex;
            gap: 8px;
        }
        .input-row.hidden { display: none; }
        .input {
            flex: 1;
            min-width: 0;
            background: rgba(12, 14, 24, 0.84);
            color: #eef1ff;
            border: 1px solid rgba(126, 152, 255, 0.22);
            border-radius: 12px;
            padding: 10px 12px;
        }
        .input:focus { outline: none; border-color: #7e98ff; }
        .btn-row {
            display: flex;
            gap: 8px;
            flex-wrap: wrap;
        }
        .btn {
            flex: 1;
            min-width: 110px;
            padding: 9px 12px;
            border-radius: 10px;
            border: 1px solid rgba(126, 152, 255, 0.24);
            background: #20243b;
            color: #eef1ff;
            cursor: pointer;
            font-size: 0.8rem;
        }
        .btn.primary {
            background: #4056a0;
            border-color: #6381ff;
        }
        .status-row {
            display: flex;
            gap: 8px;
            align-items: center;
            flex-wrap: wrap;
        }
        .chip {
            padding: 4px 8px;
            border-radius: 999px;
            background: rgba(26, 28, 46, 0.82);
            color: #bbc4ef;
            font-size: 0.74rem;
        }
        .chip.ok { color: #8fe3a3; }
        .chip.warn { color: #ffd36a; }
    </style>
</head>
<body>
    <div class="stage">
        <div class="model-status" id="model-status">模型读取中…</div>
        <div class="badge">角色聊天壳 · renderer 预留</div>
        <div class="character" id="character-icon">🎭</div>
        <div class="reply-bubble" id="reply-bubble">等待回复…</div>
    </div>

    <div class="panel">
        <div class="status-row">
            <span class="chip" id="chip-hermes">Hermes …</span>
            <span class="chip" id="chip-executor">执行器 …</span>
            <span class="chip" id="chip-bridge">Bridge …</span>
            <span class="chip" id="chip-session">会话 …</span>
        </div>

        <div class="summary" id="summary">
            <div class="empty-hint">从当前会话继续对话，或打开完整聊天窗口。</div>
        </div>

        <div class="input-row" id="input-row">
            <input class="input" id="msg-input" placeholder="输入消息…" onkeypress="if(event.key==='Enter') sendMsg()">
            <button class="btn primary" id="send-btn" type="button" onclick="sendMsg()">发送</button>
        </div>

        <div class="btn-row">
            <button class="btn primary" type="button" onclick="openChat()">完整对话</button>
            <button class="btn" type="button" onclick="openMainWindow()">主窗口</button>
            <button class="btn" type="button" onclick="openSettings()">设置</button>
        </div>
    </div>

    <script>
    const ACTIVE_POLL_INTERVAL_MS = 1200;
    const IDLE_POLL_INTERVAL_MS = 5000;
    let polling = null;
    let pollingIntervalMs = null;
    let sending = false;

    function escapeHtml(value) {
        const div = document.createElement('div');
        div.textContent = value || '';
        return div.innerHTML;
    }

    function setPollingInterval(intervalMs) {
        if (polling && pollingIntervalMs === intervalMs) return;
        stopPolling();
        pollingIntervalMs = intervalMs;
        polling = setInterval(refreshLive2D, intervalMs);
    }

    function startActivePolling() { setPollingInterval(ACTIVE_POLL_INTERVAL_MS); }
    function startIdlePolling() { setPollingInterval(IDLE_POLL_INTERVAL_MS); }
    function stopPolling() {
        if (polling) clearInterval(polling);
        polling = null;
        pollingIntervalMs = null;
    }

    function renderThinking() {
        return '<span class="thinking" aria-label="正在思考">'
            + '<span class="dot" aria-hidden="true">.</span>'
            + '<span class="dot" aria-hidden="true">.</span>'
            + '<span class="dot" aria-hidden="true">.</span>'
            + '</span>';
    }

    function renderLive2D(view) {
        const live2d = view.live2d || {};
        const chat = view.chat || {};

        const modelStateLabels = {
            not_configured: '⚪ 模型未配置',
            path_invalid: '❌ 模型路径不存在',
            path_not_live2d: '⚠️ 目录无模型文件',
            path_valid: '✅ 模型目录就绪 · renderer 待接入',
            loaded: '✅ 模型已加载',
        };
        document.getElementById('model-status').textContent =
            modelStateLabels[live2d.model_state] || (live2d.model_name || '角色聊天壳');

        const replyBubble = document.getElementById('reply-bubble');
        replyBubble.classList.toggle('hidden', !live2d.show_reply_bubble);
        replyBubble.textContent = chat.latest_reply || '等待回复…';

        document.getElementById('chip-hermes').textContent = view.hermes.ready ? '✅ Hermes' : '⚠️ Hermes';
        document.getElementById('chip-hermes').className = 'chip ' + (view.hermes.ready ? 'ok' : 'warn');
        document.getElementById('chip-executor').textContent = view.executor_label || '执行器未知';
        document.getElementById('chip-bridge').textContent = view.bridge_label || 'Bridge 未知';
        document.getElementById('chip-session').textContent = chat.status_label || '会话未知';
        document.getElementById('character-icon').textContent = chat.is_processing ? '⚡' : '🎭';

        const inputRow = document.getElementById('input-row');
        inputRow.classList.toggle('hidden', !live2d.enable_quick_input);

        const container = document.getElementById('summary');
        if (chat.empty || !chat.messages || chat.messages.length === 0) {
            container.innerHTML = '<div class="empty-hint">从当前会话继续对话，或打开完整聊天窗口。</div>';
            startIdlePolling();
            return;
        }

        let html = '';
        for (const msg of chat.messages) {
            const cls = 'message ' + msg.role + ' ' + (msg.status || '');
            const content = msg.status === 'processing' && msg.role === 'assistant' && !msg.content
                ? renderThinking()
                : escapeHtml(msg.content);
            html += '<div class="' + cls + '">' + content + '</div>';
        }
        container.innerHTML = html;
        container.scrollTop = container.scrollHeight;
        if (chat.is_processing) startActivePolling();
        else startIdlePolling();
    }

    async function refreshLive2D() {
        try {
            if (!window.pywebview || !window.pywebview.api) return;
            const view = await window.pywebview.api.get_live2d_view();
            if (!view.ok) return;
            renderLive2D(view);
        } catch (error) {}
    }

    async function sendMsg() {
        if (sending) return;
        const input = document.getElementById('msg-input');
        const text = (input.value || '').trim();
        if (!text) return;
        sending = true;
        document.getElementById('send-btn').disabled = true;
        input.disabled = true;
        try {
            const result = await window.pywebview.api.send_quick_message(text);
            if (!result.ok) throw new Error(result.error || '发送失败');
            input.value = '';
            await refreshLive2D();
            startActivePolling();
        } catch (error) {
            console.error(error);
        } finally {
            sending = false;
            document.getElementById('send-btn').disabled = false;
            input.disabled = false;
        }
    }

    async function openChat() {
        if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_chat();
    }

    async function openMainWindow() {
        if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_main_window();
    }

    async function openSettings() {
        if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_settings();
    }

    function bootstrap() {
        refreshLive2D();
        startIdlePolling();
    }

    document.addEventListener('DOMContentLoaded', function() { setTimeout(bootstrap, 300); });
    window.addEventListener('pywebviewready', bootstrap);
    </script>
</body>
</html>
"""


class Live2DWindowAPI:
    """Live2D 模式 WebView API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)

    def get_live2d_view(self) -> Dict[str, Any]:
        live2d = self._config.live2d_mode
        chat = self._chat_bridge.get_conversation_overview(summary_count=3, session_limit=3)
        runner = self._runtime.task_runner
        executor_label = "执行器不可用"
        if runner is not None:
            executor_label = "🚀 Hermes" if runner.executor.name == "HermesExecutor" else "🔬 模拟"

        bridge_state = get_bridge_state()
        bridge_label_map = {
            "running": "✅ Bridge",
            "failed": "❌ Bridge",
        }

        return {
            "ok": True,
            "chat": chat,
            "hermes": {
                "ready": self._runtime.is_hermes_ready(),
                "status": self._runtime.get_status().get("hermes", {}).get("install_status", "unknown"),
            },
            "workspace": {
                "initialized": get_workspace_status().get("initialized", False),
            },
            "live2d": {
                "model_state": live2d.validate().value,
                "model_name": live2d.model_name or "",
                "model_path": live2d.model_path or "",
                "show_reply_bubble": live2d.show_reply_bubble,
                "enable_quick_input": live2d.enable_quick_input,
                "click_action": live2d.click_action,
                "default_open_behavior": live2d.default_open_behavior,
                "summary": _serialize_summary(live2d.scan()),
            },
            "bridge_label": bridge_label_map.get(bridge_state, "⏳ Bridge"),
            "executor_label": executor_label,
        }

    def send_quick_message(self, text: str) -> Dict[str, Any]:
        return self._chat_bridge.send_quick_message(text)

    def open_chat(self) -> Dict[str, Any]:
        from apps.shell.chat_window import open_chat_window

        return {"ok": open_chat_window(self._runtime)}

    def open_main_window(self) -> Dict[str, Any]:
        from apps.shell.window import open_main_window

        return {"ok": open_main_window(self._runtime, self._config)}

    def open_settings(self) -> Dict[str, Any]:
        from apps.shell.settings import open_mode_settings_window

        return {"ok": open_mode_settings_window(self._config, "live2d")}


def run(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """Live2D 模式入口（阻塞主线程）。"""
    logger.info("启动 Live2D 模式（角色聊天壳）")
    try:
        import webview  # type: ignore[import]

        live2d = config.live2d_mode
        api = Live2DWindowAPI(runtime, config)
        webview.create_window(
            title="Hermes-Yachiyo Live2D",
            html=_LIVE2D_HTML,
            width=live2d.width,
            height=live2d.height,
            resizable=True,
            on_top=live2d.window_on_top,
            js_api=api,
        )
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，Live2D 模式无法展示")
