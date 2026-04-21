"""Bubble 模式。

Bubble 是完整模式之一，不是纯快捷入口：
- 共享统一 ChatSession / ChatStore / TaskRunner / Executor
- 提供轻量摘要、短输入、状态反馈和完整聊天窗口入口
- 独立持有 BubbleModeConfig
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any, Dict

from apps.shell.chat_bridge import ChatBridge

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime
    from apps.shell.config import AppConfig

logger = logging.getLogger(__name__)

_BUBBLE_HTML = """
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Hermes-Yachiyo Bubble</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: rgba(18, 20, 34, 0.96);
            color: #eef2ff;
            padding: 10px;
            height: 100vh;
            display: flex;
            flex-direction: column;
            gap: 8px;
        }
        .shell {
            flex: 1;
            display: flex;
            flex-direction: column;
            min-height: 0;
            border-radius: 14px;
            border: 1px solid rgba(118, 140, 255, 0.18);
            background: linear-gradient(180deg, rgba(30,32,52,0.96) 0%, rgba(20,22,38,0.96) 100%);
            overflow: hidden;
        }
        .header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 8px;
            padding: 10px 12px;
            border-bottom: 1px solid rgba(255,255,255,0.06);
            cursor: pointer;
        }
        .identity {
            display: flex;
            align-items: center;
            gap: 8px;
            min-width: 0;
        }
        .avatar {
            width: 32px;
            height: 32px;
            border-radius: 50%;
            display: grid;
            place-items: center;
            background: #364173;
            font-size: 1rem;
        }
        .title-wrap {
            min-width: 0;
        }
        .title {
            font-weight: 700;
            font-size: 0.92rem;
            display: flex;
            align-items: center;
            gap: 6px;
        }
        .subtitle {
            color: #9ca5d4;
            font-size: 0.74rem;
            white-space: nowrap;
            overflow: hidden;
            text-overflow: ellipsis;
            max-width: 180px;
        }
        .dot {
            width: 8px;
            height: 8px;
            border-radius: 50%;
            background: #ff6b6b;
            box-shadow: 0 0 0 0 rgba(255, 107, 107, 0.65);
            animation: unread-pulse 1.6s infinite;
            display: none;
        }
        @keyframes unread-pulse {
            0% { box-shadow: 0 0 0 0 rgba(255, 107, 107, 0.65); }
            70% { box-shadow: 0 0 0 8px rgba(255, 107, 107, 0); }
            100% { box-shadow: 0 0 0 0 rgba(255, 107, 107, 0); }
        }
        @keyframes thinking-dot {
            0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-1px); }
        }
        .status-chip {
            display: inline-flex;
            align-items: center;
            gap: 4px;
            padding: 3px 8px;
            border-radius: 999px;
            font-size: 0.72rem;
            background: #2a2d44;
            color: #c0c7eb;
        }
        .status-chip.processing { color: #ffd36a; }
        .status-chip.failed { color: #ff9f9f; }
        .status-chip.ready { color: #8fe3a3; }
        .toggle-btn {
            background: transparent;
            border: none;
            color: #c8d0ff;
            font-size: 1rem;
            cursor: pointer;
        }
        .body {
            flex: 1;
            min-height: 0;
            display: flex;
            flex-direction: column;
            gap: 8px;
            padding: 10px 12px 12px;
        }
        .body.collapsed {
            display: none;
        }
        .preview {
            background: rgba(10, 12, 22, 0.65);
            border-radius: 12px;
            padding: 10px;
            flex: 1;
            min-height: 0;
            overflow-y: auto;
        }
        .reply-highlight {
            padding: 8px 10px;
            border-radius: 10px;
            background: rgba(84, 111, 224, 0.14);
            border-left: 3px solid #7692ff;
            margin-bottom: 8px;
            font-size: 0.8rem;
            color: #d7defc;
        }
        .summary-list {
            display: flex;
            flex-direction: column;
            gap: 6px;
        }
        .summary-item {
            padding: 8px 10px;
            border-radius: 10px;
            font-size: 0.8rem;
            line-height: 1.45;
            color: #d6dbf5;
        }
        .summary-item.user { background: rgba(84, 111, 224, 0.16); }
        .summary-item.assistant { background: rgba(56, 112, 84, 0.18); }
        .summary-item.system { background: rgba(58, 58, 78, 0.7); color: #adb3d1; }
        .summary-item.processing { color: #ffd36a; }
        .summary-item.failed { color: #ffaaaa; }
        .thinking { display: inline-flex; align-items: center; gap: 2px; }
        .thinking .dot {
            animation: thinking-dot 1.2s ease-in-out infinite;
            display: inline-block;
        }
        .thinking .dot:nth-child(2) { animation-delay: 0.15s; }
        .thinking .dot:nth-child(3) { animation-delay: 0.3s; }
        .recent-sessions {
            display: flex;
            flex-wrap: wrap;
            gap: 6px;
        }
        .session-pill {
            padding: 4px 8px;
            border-radius: 999px;
            background: #20243b;
            color: #b8c1ee;
            font-size: 0.72rem;
            max-width: 100%;
            overflow: hidden;
            text-overflow: ellipsis;
            white-space: nowrap;
        }
        .session-pill.current {
            border: 1px solid rgba(118, 146, 255, 0.5);
            color: #eef2ff;
        }
        .empty-hint {
            color: #7e86af;
            text-align: center;
            padding: 18px 8px;
            font-size: 0.82rem;
        }
        .input-row {
            display: flex;
            gap: 8px;
        }
        .input {
            flex: 1;
            min-width: 0;
            padding: 8px 10px;
            border-radius: 10px;
            border: 1px solid rgba(118, 140, 255, 0.2);
            background: rgba(12, 14, 24, 0.8);
            color: #eef2ff;
        }
        .input:focus { outline: none; border-color: #7692ff; }
        .btn-row {
            display: flex;
            gap: 8px;
        }
        .btn {
            flex: 1;
            border: 1px solid rgba(118, 140, 255, 0.22);
            background: #20243b;
            color: #e6ebff;
            border-radius: 10px;
            padding: 8px 10px;
            font-size: 0.78rem;
            cursor: pointer;
        }
        .btn.primary {
            background: #3d518f;
            border-color: #5e7cff;
        }
    </style>
</head>
<body>
    <div class="shell">
        <div class="header" onclick="toggleExpanded()">
            <div class="identity">
                <div class="avatar">💬</div>
                <div class="title-wrap">
                    <div class="title">
                        <span>Bubble Mode</span>
                        <span class="dot" id="unread-dot"></span>
                    </div>
                    <div class="subtitle" id="bubble-subtitle">轻量常驻聊天模式</div>
                </div>
            </div>
            <div style="display:flex;align-items:center;gap:8px;">
                <span class="status-chip" id="status-chip">读取中…</span>
                <button class="toggle-btn" id="toggle-btn" type="button">▾</button>
            </div>
        </div>

        <div class="body" id="bubble-body">
            <div class="preview" id="preview">
                <div class="empty-hint">发送一条消息，从当前会话继续对话。</div>
            </div>

            <div class="input-row">
                <input class="input" id="msg-input" placeholder="输入短消息…" onkeypress="if(event.key==='Enter') sendMsg()">
                <button class="btn primary" id="send-btn" type="button" onclick="sendMsg()">发送</button>
            </div>

            <div class="btn-row">
                <button class="btn primary" type="button" onclick="openChat()">完整对话</button>
                <button class="btn" type="button" onclick="openMain()">主窗口</button>
                <button class="btn" type="button" onclick="openSettings()">设置</button>
                <button class="btn" type="button" onclick="closeBubble()">关闭</button>
            </div>
        </div>
    </div>

<script>
const ACTIVE_POLL_INTERVAL_MS = 1200;
const IDLE_POLL_INTERVAL_MS = 5000;
let polling = null;
let pollingIntervalMs = null;
let sending = false;
let expanded = true;
let expandedInitialized = false;

function escapeHtml(value) {
    const div = document.createElement('div');
    div.textContent = value || '';
    return div.innerHTML;
}

function renderThinking() {
    return '<span class="thinking" aria-label="正在思考">'
        + '<span class="dot" aria-hidden="true">.</span>'
        + '<span class="dot" aria-hidden="true">.</span>'
        + '<span class="dot" aria-hidden="true">.</span>'
        + '</span>';
}

function setPollingInterval(intervalMs) {
    if (polling && pollingIntervalMs === intervalMs) return;
    stopPolling();
    pollingIntervalMs = intervalMs;
    polling = setInterval(refreshBubble, intervalMs);
}

function startActivePolling() {
    setPollingInterval(ACTIVE_POLL_INTERVAL_MS);
}

function startIdlePolling() {
    setPollingInterval(IDLE_POLL_INTERVAL_MS);
}

function stopPolling() {
    if (polling) clearInterval(polling);
    polling = null;
    pollingIntervalMs = null;
}

function applyExpandedState() {
    const body = document.getElementById('bubble-body');
    const btn = document.getElementById('toggle-btn');
    body.classList.toggle('collapsed', !expanded);
    btn.textContent = expanded ? '▾' : '▸';
}

function toggleExpanded(force) {
    expanded = typeof force === 'boolean' ? force : !expanded;
    applyExpandedState();
}

function renderBubble(view) {
    const chip = document.getElementById('status-chip');
    const preview = document.getElementById('preview');
    const subtitle = document.getElementById('bubble-subtitle');
    const unreadDot = document.getElementById('unread-dot');
    const bubble = view.bubble || {};
    const chat = view.chat || {};

    subtitle.textContent = bubble.subtitle || '轻量常驻聊天模式';
    if (!expandedInitialized) {
        expanded = bubble.expanded_on_start !== false;
        expandedInitialized = true;
    }
    applyExpandedState();

    const latestStatus = bubble.latest_status || 'empty';
    chip.textContent = chat.status_label || '读取中…';
    chip.className = 'status-chip ' + latestStatus;

    unreadDot.style.display = bubble.show_unread_dot && bubble.has_attention ? 'inline-block' : 'none';

    if (chat.empty || !chat.messages || chat.messages.length === 0) {
        preview.innerHTML = '<div class="empty-hint">发送一条消息，从当前会话继续对话。</div>';
        startIdlePolling();
        return;
    }

    let html = '';
    if (chat.latest_reply && bubble.default_display !== 'icon') {
        html += '<div class="reply-highlight">' + escapeHtml(chat.latest_reply) + '</div>';
    }
    html += '<div class="summary-list">';
    for (const msg of chat.messages) {
        const cls = 'summary-item ' + msg.role + ' ' + (msg.status || '');
        const content = msg.status === 'processing' && msg.role === 'assistant' && !msg.content
            ? renderThinking()
            : escapeHtml(msg.content);
        html += '<div class="' + cls + '">' + content + '</div>';
    }
    html += '</div>';
    if (chat.recent_sessions && chat.recent_sessions.length > 0) {
        html += '<div style="margin-top:10px;" class="recent-sessions">';
        for (const session of chat.recent_sessions) {
            const current = session.is_current ? ' current' : '';
            html += '<span class="session-pill' + current + '">' + escapeHtml(session.title) + '</span>';
        }
        html += '</div>';
    }
    preview.innerHTML = html;
    preview.scrollTop = preview.scrollHeight;

    if (chat.is_processing) startActivePolling();
    else startIdlePolling();
}

async function refreshBubble() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        const view = await window.pywebview.api.get_bubble_view();
        if (!view.ok) return;
        renderBubble(view);
    } catch (error) {}
}

async function sendMsg() {
    if (sending) return;
    const input = document.getElementById('msg-input');
    const text = (input.value || '').trim();
    if (!text) return;
    sending = true;
    input.disabled = true;
    document.getElementById('send-btn').disabled = true;
    try {
        const result = await window.pywebview.api.send_quick_message(text);
        if (!result.ok) throw new Error(result.error || '发送失败');
        input.value = '';
        await refreshBubble();
        startActivePolling();
    } catch (error) {
        console.error(error);
    } finally {
        sending = false;
        input.disabled = false;
        document.getElementById('send-btn').disabled = false;
        input.focus();
    }
}

async function openChat() {
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_chat();
}

async function openMain() {
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_main_window();
}

async function openSettings() {
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.open_settings();
}

async function closeBubble() {
    if (window.pywebview && window.pywebview.api) await window.pywebview.api.close_bubble();
}

function bootstrap() {
    refreshBubble();
    startIdlePolling();
}

document.addEventListener('DOMContentLoaded', function() { setTimeout(bootstrap, 300); });
window.addEventListener('pywebviewready', bootstrap);
</script>
</body>
</html>
"""


class BubbleWindowAPI:
    """Bubble 模式 WebView API。"""

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)
        self._bubble_window = None

    def get_bubble_view(self) -> Dict[str, Any]:
        bubble = self._config.bubble_mode
        chat = self._chat_bridge.get_conversation_overview(
            summary_count=bubble.summary_count,
            session_limit=3,
        )
        latest_status = "ready"
        if chat.get("empty"):
            latest_status = "empty"
        elif chat.get("is_processing"):
            latest_status = "processing"
        elif any(item.get("status") == "failed" for item in chat.get("messages", [])):
            latest_status = "failed"

        return {
            "ok": True,
            "chat": chat,
            "bubble": {
                "expanded_on_start": bubble.expanded_on_start,
                "default_display": bubble.default_display,
                "show_unread_dot": bubble.show_unread_dot,
                "has_attention": bool(chat.get("latest_reply")) and not chat.get("is_processing"),
                "latest_status": latest_status,
                "subtitle": (
                    "从当前会话继续对话"
                    if not chat.get("empty")
                    else "轻量常驻聊天模式"
                ),
            },
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

        return {"ok": open_mode_settings_window(self._config, "bubble")}

    def close_bubble(self) -> None:
        try:
            if self._bubble_window is not None:
                self._bubble_window.destroy()
        except Exception as exc:
            logger.error("关闭 Bubble 窗口失败: %s", exc)


def run(runtime: "HermesRuntime", config: "AppConfig") -> None:
    """运行 Bubble 模式（阻塞主线程）。"""
    logger.info("启动 Bubble 模式")
    try:
        import webview  # type: ignore[import]

        bubble = config.bubble_mode
        api = BubbleWindowAPI(runtime, config)
        win = webview.create_window(
            title="Hermes-Yachiyo Bubble",
            html=_BUBBLE_HTML,
            width=bubble.width,
            height=bubble.height,
            resizable=False,
            on_top=bubble.always_on_top,
            js_api=api,
        )
        api._bubble_window = win
        webview.start(debug=False)
    except ImportError:
        logger.warning("pywebview 未安装，Bubble 模式无法展示")
