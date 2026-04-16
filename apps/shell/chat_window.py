"""独立聊天窗口

从主窗口拆出的聊天面板，作为独立 pywebview 窗口运行。
三种模式（window / bubble / live2d）统一通过此窗口进入聊天。
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Dict

if TYPE_CHECKING:
    from apps.core.runtime import HermesRuntime

try:
    import webview
    _HAS_WEBVIEW = True
except ImportError:
    _HAS_WEBVIEW = False

logger = logging.getLogger(__name__)

# ── 聊天窗口单例管理 ──────────────────────────────────────────────────────────

_chat_window: Any = None  # webview.Window | None
_chat_window_lock = threading.RLock()


class ChatWindowAPI:
    """聊天窗口专用 API（供 JS 调用）"""

    def __init__(self, runtime: "HermesRuntime") -> None:
        from apps.shell.chat_api import ChatAPI
        self._runtime = runtime
        self._chat_api = ChatAPI(runtime)

    def send_message(self, text: str) -> Dict[str, Any]:
        return self._chat_api.send_message(text)

    def get_messages(self, limit: int = 50) -> Dict[str, Any]:
        return self._chat_api.get_messages(limit)

    def get_session_info(self) -> Dict[str, Any]:
        return self._chat_api.get_session_info()

    def clear_session(self) -> Dict[str, Any]:
        return self._chat_api.clear_session()

    def get_executor_info(self) -> Dict[str, Any]:
        runner = self._runtime.task_runner
        if runner is None:
            return {"executor": "none", "available": False}
        return {"executor": runner.executor.name, "available": True}

    def list_sessions(self) -> Dict[str, Any]:
        """列出历史会话"""
        from apps.core.chat_store import get_chat_store
        store = get_chat_store()
        sessions = store.list_sessions(limit=20)
        return {
            "ok": True,
            "sessions": [
                {
                    "session_id": s.session_id,
                    "title": s.title,
                    "created_at": s.created_at,
                    "message_count": s.message_count,
                }
                for s in sessions
            ],
        }


def open_chat_window(runtime: "HermesRuntime") -> bool:
    """打开聊天窗口（若已打开则激活）

    在 webview.start() 已运行的情况下创建新窗口。
    返回是否成功打开。
    """
    global _chat_window

    if not _HAS_WEBVIEW:
        logger.warning("pywebview 未安装，无法打开聊天窗口")
        return False

    with _chat_window_lock:
        # 如果窗口已存在且未关闭，聚焦
        if _chat_window is not None:
            try:
                _chat_window.show()
                _chat_window.on_top = True
                _chat_window.on_top = False
                return True
            except Exception:
                _chat_window = None

        api = ChatWindowAPI(runtime)
        _chat_window = webview.create_window(
            title="Yachiyo - 对话",
            html=_CHAT_HTML,
            width=420,
            height=600,
            resizable=True,
            js_api=api,
            on_top=False,
        )

        def _on_closed():
            global _chat_window
            with _chat_window_lock:
                _chat_window = None

        _chat_window.events.closed += _on_closed
        logger.info("聊天窗口已创建")
        return True


# ── 聊天窗口 HTML ─────────────────────────────────────────────────────────────

_CHAT_HTML = r"""
<!DOCTYPE html>
<html lang="zh">
<head>
    <meta charset="UTF-8">
    <title>Yachiyo - 对话</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            display: flex;
            flex-direction: column;
            height: 100vh;
            overflow: hidden;
        }
        .header {
            padding: 12px 16px;
            border-bottom: 1px solid #333;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-shrink: 0;
        }
        .header h2 { color: #6495ed; font-size: 1.1em; }
        .header .meta { font-size: 0.78em; color: #888; }
        .header .executor { color: #6a9a6a; }
        .messages {
            flex: 1;
            overflow-y: auto;
            padding: 12px 16px;
            display: flex;
            flex-direction: column;
            gap: 10px;
        }
        .msg {
            padding: 10px 12px;
            border-radius: 8px;
            font-size: 0.9em;
            line-height: 1.6;
            max-width: 88%;
            word-break: break-word;
            white-space: pre-wrap;
        }
        .msg.user {
            background: #3a4a7a;
            align-self: flex-end;
            border-bottom-right-radius: 2px;
        }
        .msg.assistant {
            background: #2a3a3a;
            align-self: flex-start;
            border-bottom-left-radius: 2px;
            border-left: 3px solid #90ee90;
        }
        .msg.system {
            background: #2a2a3a;
            text-align: center;
            color: #888;
            font-size: 0.82em;
            align-self: center;
        }
        .msg .role {
            font-size: 0.72em;
            color: #888;
            margin-bottom: 3px;
        }
        .msg.error { border-left-color: #ff6b6b; }
        .msg.error .content { color: #ffaaaa; }
        .msg.pending { opacity: 0.7; }
        .msg.processing {
            opacity: 0.85;
            border-left-color: #f0c060;
        }
        .msg.processing .content { color: #bbb; }
        @keyframes thinking-dots {
            0%, 20% { content: ''; }
            40% { content: '.'; }
            60% { content: '..'; }
            80%, 100% { content: '...'; }
        }
        .thinking-indicator::after {
            animation: thinking-dots 1.4s steps(1) infinite;
            content: '';
        }
        .input-area {
            padding: 12px 16px;
            border-top: 1px solid #333;
            display: flex;
            gap: 8px;
            flex-shrink: 0;
        }
        .input-area input {
            flex: 1;
            background: #2d2d54;
            color: #e0e0e0;
            border: 1px solid #444;
            border-radius: 8px;
            padding: 10px 14px;
            font-size: 0.92em;
            outline: none;
        }
        .input-area input:focus { border-color: #6495ed; }
        .input-area input::placeholder { color: #555; }
        .input-area button {
            background: #4a6a9a;
            border: none;
            color: #fff;
            padding: 10px 18px;
            border-radius: 8px;
            cursor: pointer;
            font-size: 0.92em;
            transition: background 0.2s;
        }
        .input-area button:hover { background: #5a7aaa; }
        .input-area button:disabled { background: #3a3a5a; color: #666; cursor: not-allowed; }
        .status-bar {
            padding: 4px 16px;
            font-size: 0.75em;
            color: #666;
            text-align: center;
            flex-shrink: 0;
        }
        .empty-hint {
            text-align: center;
            color: #555;
            padding: 40px 20px;
            font-size: 0.9em;
        }
        .clear-btn {
            background: transparent;
            border: 1px solid #444;
            color: #888;
            padding: 2px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.82em;
        }
        .clear-btn:hover { border-color: #888; color: #ccc; }
    </style>
</head>
<body>
    <div class="header">
        <h2>💬 Yachiyo</h2>
        <div class="meta">
            <span class="executor" id="executor-badge">—</span>
            <button class="clear-btn" onclick="clearChat()">清空</button>
        </div>
    </div>
    <div class="messages" id="messages">
        <div class="empty-hint">发送消息开始对话 ✨</div>
    </div>
    <div class="input-area">
        <input type="text" id="input" placeholder="输入消息..."
               onkeypress="if(event.key==='Enter') sendMessage()">
        <button id="send-btn" onclick="sendMessage()">发送</button>
    </div>
    <div class="status-bar" id="status">就绪</div>

<script>
let polling = null;
let sending = false;

async function sendMessage() {
    if (sending) return;
    const input = document.getElementById('input');
    const text = (input.value || '').trim();
    if (!text) return;

    sending = true;
    const btn = document.getElementById('send-btn');
    btn.disabled = true;
    input.disabled = true;
    setStatus('发送中...');

    try {
        if (!window.pywebview || !window.pywebview.api) throw new Error('API 不可用');
        const r = await window.pywebview.api.send_message(text);
        if (!r.ok) throw new Error(r.error || '发送失败');
        input.value = '';
        setStatus('等待回复...');
        await refreshMessages();
        startPolling();
    } catch(e) {
        setStatus('❌ ' + e.message);
    } finally {
        sending = false;
        btn.disabled = false;
        input.disabled = false;
        input.focus();
    }
}

async function refreshMessages() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        const r = await window.pywebview.api.get_messages(50);
        if (!r.ok) return;
        renderMessages(r.messages);
        if (!r.is_processing) {
            stopPolling();
            setStatus('就绪');
        } else {
            setStatus('处理中...');
        }
    } catch(e) {}
}

function renderMessages(msgs) {
    const container = document.getElementById('messages');
    if (!msgs || msgs.length === 0) {
        container.innerHTML = '<div class="empty-hint">发送消息开始对话 ✨</div>';
        return;
    }
    let html = '';
    for (const m of msgs) {
        const label = m.role === 'user' ? '你' : (m.role === 'assistant' ? 'Yachiyo' : '系统');
        const isProcessing = m.status === 'processing';
        const sc = m.status === 'failed' ? 'error' : (isProcessing ? 'processing' : (m.status === 'pending' ? 'pending' : ''));
        const suffix = m.status === 'pending' ? ' · 等待中' : (isProcessing ? ' · 处理中' : '');

        let displayContent;
        if (isProcessing && m.role === 'assistant') {
            displayContent = m.content
                ? escapeHtml(m.content)
                : '<span class="thinking-indicator">正在思考</span>';
        } else {
            displayContent = escapeHtml(m.content);
        }

        html += '<div class="msg ' + m.role + ' ' + sc + '">';
        html += '<div class="role">' + label + suffix + '</div>';
        html += '<div class="content">' + displayContent + '</div>';
        html += '</div>';
    }
    container.innerHTML = html;
    container.scrollTop = container.scrollHeight;
}

function escapeHtml(t) {
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
}

function setStatus(t) {
    const el = document.getElementById('status');
    if (el) el.textContent = t;
}

function startPolling() {
    if (polling) return;
    polling = setInterval(refreshMessages, 800);
}

function stopPolling() {
    if (polling) { clearInterval(polling); polling = null; }
}

async function clearChat() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        await window.pywebview.api.clear_session();
        await refreshMessages();
        setStatus('会话已清空');
    } catch(e) {
        setStatus('❌ ' + e.message);
    }
}

async function loadExecutor() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        const r = await window.pywebview.api.get_executor_info();
        const el = document.getElementById('executor-badge');
        if (el && r.executor) {
            el.textContent = r.executor === 'HermesExecutor' ? '🚀 Hermes' : '🔬 模拟';
        }
    } catch(e) {}
}

// 启动
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        loadExecutor();
        refreshMessages();
    }, 500);
});
</script>
</body>
</html>
"""
