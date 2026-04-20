"""气泡模式

轻量悬浮小窗口，显示最近消息摘要 + 快捷发送 + 打开聊天窗口 / 主窗口入口。
共享 ChatSession，三模式消息互通。
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
    <title>Hermes-Yachiyo</title>
    <style>
        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: -apple-system, "Helvetica Neue", "PingFang SC", sans-serif;
            background: #1a1a2e;
            color: #e0e0e0;
            padding: 10px;
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
            padding-bottom: 6px;
            border-bottom: 1px solid #333;
            margin-bottom: 6px;
            flex-shrink: 0;
        }
        .header .title { color: #6495ed; font-size: 0.95em; font-weight: 600; }
        .header .status-tag {
            font-size: 0.7em;
            padding: 2px 6px;
            border-radius: 10px;
        }
        .header .status-tag.ok { background: #1a2e1a; color: #90ee90; }
        .header .status-tag.busy { background: #2e2a1a; color: #ffd700; }
        .header .status-tag.empty { background: #2d2d54; color: #888; }
        /* 消息摘要区 */
        .chat-summary {
            flex: 1;
            overflow-y: auto;
            background: #12122a;
            border-radius: 6px;
            padding: 8px;
            margin-bottom: 6px;
            font-size: 0.82em;
            min-height: 50px;
        }
        .chat-msg {
            margin-bottom: 5px;
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
        .chat-msg.pending .content,
        .chat-msg.processing .content { color: #aaa; }
        .chat-msg.error .content { color: #ffaaaa; }
        .empty-hint { text-align: center; color: #555; padding: 15px 8px; font-size: 0.85em; }
        @keyframes thinking-dots {
            0%, 20% { content: ''; }
            40% { content: '.'; }
            60% { content: '..'; }
            80%, 100% { content: '...'; }
        }
        .thinking::after { animation: thinking-dots 1.4s steps(1) infinite; content: ''; }
        /* 输入区 */
        .chat-input-row {
            display: flex;
            gap: 6px;
            flex-shrink: 0;
            margin-bottom: 6px;
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
            flex-shrink: 0;
        }
        .btn {
            flex: 1;
            background: #2d2d54;
            border: 1px solid #444;
            color: #ccc;
            padding: 5px 0;
            border-radius: 5px;
            font-size: 0.78em;
            cursor: pointer;
            text-align: center;
        }
        .btn:hover { background: #3a3a6a; border-color: #6495ed; color: #fff; }
        .btn.primary { border-color: #6495ed; color: #6495ed; }
        .btn.danger:hover { border-color: #ff6b6b; color: #ff6b6b; background: #2d2424; }
    </style>
</head>
<body>
    <div class="header">
        <span class="title">💬 Yachiyo</span>
        <span class="status-tag empty" id="status-tag">—</span>
    </div>

    <div class="chat-summary" id="chat-summary">
        <div class="empty-hint">发送消息开始对话 ✨</div>
    </div>

    <div class="chat-input-row">
        <input type="text" class="chat-input" id="msg-input"
               placeholder="输入消息…"
               onkeypress="if(event.key==='Enter') sendMsg()">
        <button class="chat-send" id="send-btn" onclick="sendMsg()">发送</button>
    </div>

    <div class="actions">
        <div class="btn primary" onclick="openChat()">💬 完整对话</div>
        <div class="btn primary" onclick="openMain()">🖥 主窗口</div>
        <div class="btn danger" onclick="closeBubble()">✕</div>
    </div>

<script>
let polling = null;
let sending = false;

function escapeHtml(t) {
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
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
        if (!window.pywebview || !window.pywebview.api) throw new Error('API 不可用');
        const r = await window.pywebview.api.send_quick_message(text);
        if (!r.ok) throw new Error(r.error || '发送失败');
        input.value = '';
        await refreshSummary();
        startPolling();
    } catch(e) {
        console.error('send error:', e);
    } finally {
        sending = false;
        document.getElementById('send-btn').disabled = false;
        input.disabled = false;
        input.focus();
    }
}

async function refreshSummary() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        const r = await window.pywebview.api.get_recent_summary(3);
        if (!r.ok) return;

        // 更新状态标签
        const tag = document.getElementById('status-tag');
        if (r.empty) {
            tag.textContent = '暂无对话';
            tag.className = 'status-tag empty';
        } else if (r.is_processing) {
            tag.textContent = '处理中…';
            tag.className = 'status-tag busy';
        } else {
            tag.textContent = '就绪';
            tag.className = 'status-tag ok';
        }

        // 渲染消息摘要
        const container = document.getElementById('chat-summary');
        if (r.empty || !r.messages || r.messages.length === 0) {
            container.innerHTML = '<div class="empty-hint">发送消息开始对话 ✨</div>';
            stopPolling();
            return;
        }

        let html = '';
        for (const m of r.messages) {
            const sc = m.status === 'failed' ? 'error'
                     : m.status === 'processing' ? 'processing'
                     : m.status === 'pending' ? 'pending' : '';
            let content;
            if (m.status === 'processing' && m.role === 'assistant') {
                content = m.content ? escapeHtml(m.content) : '<span class="thinking">正在思考</span>';
            } else {
                content = escapeHtml(m.content);
            }
            html += '<div class="chat-msg ' + m.role + ' ' + sc + '">';
            html += '<div class="content">' + content + '</div>';
            html += '</div>';
        }
        container.innerHTML = html;
        container.scrollTop = container.scrollHeight;

        if (!r.is_processing) stopPolling();
    } catch(e) {}
}

function startPolling() {
    if (polling) return;
    polling = setInterval(refreshSummary, 1200);
}

function stopPolling() {
    if (polling) { clearInterval(polling); polling = null; }
}

async function openChat() {
    try {
        if (window.pywebview && window.pywebview.api)
            await window.pywebview.api.open_chat();
    } catch(e) {}
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
    setTimeout(function() {
        refreshSummary();
    }, 500);
});
</script>
</body>
</html>
"""


class BubbleWindowAPI:
    """气泡模式 WebView API

    聊天相关操作委托 ChatBridge（统一摘要层），
    不直接调用 ChatSession/ChatStore。
    """

    def __init__(self, runtime: "HermesRuntime", config: "AppConfig") -> None:
        self._runtime = runtime
        self._config = config
        self._chat_bridge = ChatBridge(runtime)
        self._bubble_window = None  # 由 run() 注入

    # ── 聊天摘要与快捷发送 ──────────────────────────────────────────────────

    def send_quick_message(self, text: str) -> Dict[str, Any]:
        """快捷发消息到统一 ChatSession"""
        return self._chat_bridge.send_quick_message(text)

    def get_recent_summary(self, count: int = 3) -> Dict[str, Any]:
        """获取最近 N 条消息摘要"""
        return self._chat_bridge.get_recent_summary(count)

    def get_session_status(self) -> Dict[str, Any]:
        """获取会话状态（不含消息内容）"""
        return self._chat_bridge.get_session_status()

    # ── 窗口操作 ────────────────────────────────────────────────────────────

    def open_chat(self) -> Dict[str, Any]:
        """打开独立聊天窗口"""
        from apps.shell.chat_window import open_chat_window
        ok = open_chat_window(self._runtime)
        return {"ok": ok}

    def open_main_window(self) -> None:
        """在当前 pywebview 会话中打开完整主窗口"""
        try:
            import webview  # type: ignore[import]
            from apps.shell.main_api import MainWindowAPI
            from apps.shell.window import _STATUS_HTML

            html = _STATUS_HTML.replace("{{HOST}}", self._config.bridge_host).replace(
                "{{PORT}}", str(self._config.bridge_port)
            )
            api = MainWindowAPI(self._runtime, self._config)
            webview.create_window(
                title="Hermes-Yachiyo — 主窗口",
                html=html,
                width=560,
                height=620,
                resizable=True,
                js_api=api,
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
