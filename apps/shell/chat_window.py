"""独立聊天窗口

从主窗口拆出的聊天面板，作为独立 pywebview 窗口运行。
三种模式（window / bubble / live2d）统一通过此窗口进入聊天。
"""

from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any, Dict

from apps.shell.chat_api import ChatAPI

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

    def new_session(self) -> Dict[str, Any]:
        """创建一个新会话。"""
        return self._chat_api.clear_session()

    def delete_current_session(self) -> Dict[str, Any]:
        """删除当前会话。"""
        return self._chat_api.delete_current_session()

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
            "current_session_id": self._runtime.chat_session.session_id,
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

    def load_session(self, session_id: str) -> Dict[str, Any]:
        """切换到指定的历史会话"""
        if not session_id:
            return {"ok": False, "error": "session_id 不能为空"}
        try:
            self._runtime.switch_session(session_id)
            self._chat_api = ChatAPI(self._runtime)
            return {
                "ok": True,
                "session_id": session_id,
                "message_count": self._runtime.chat_session.message_count(),
            }
        except Exception as exc:
            logger.error("切换会话失败: %s", exc)
            return {"ok": False, "error": str(exc)}


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


def close_chat_window() -> bool:
    """关闭独立聊天窗口。

    返回值表示调用时是否存在需要关闭的聊天窗口。
    """
    global _chat_window

    if not _HAS_WEBVIEW:
        return False

    with _chat_window_lock:
        window = _chat_window
        if window is None:
            return False
        _chat_window = None

    try:
        window.destroy()
        logger.info("聊天窗口已关闭")
    except Exception as exc:
        logger.warning("关闭聊天窗口失败: %s", exc)
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
        .header .meta {
            font-size: 0.78em;
            color: #888;
            display: flex;
            align-items: center;
            gap: 8px;
        }
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
            white-space: normal;
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
        .msg .content { white-space: normal; }
        .markdown p { margin: 0 0 0.75em; }
        .markdown p:last-child,
        .markdown ul:last-child,
        .markdown ol:last-child,
        .markdown blockquote:last-child,
        .markdown pre:last-child { margin-bottom: 0; }
        .markdown h1,
        .markdown h2,
        .markdown h3 {
            color: #eef2f2;
            font-weight: 700;
            line-height: 1.35;
            margin: 0.95em 0 0.35em;
        }
        .markdown h1:first-child,
        .markdown h2:first-child,
        .markdown h3:first-child { margin-top: 0; }
        .markdown h1 { font-size: 1.25em; }
        .markdown h2 { font-size: 1.14em; }
        .markdown h3 { font-size: 1.05em; }
        .markdown ul,
        .markdown ol {
            margin: 0.2em 0 0.75em 1.35em;
            padding-left: 0.55em;
        }
        .markdown li { margin: 0.15em 0; }
        .markdown strong { color: #f0f4f4; font-weight: 700; }
        .markdown em { color: #e2e8e8; }
        .markdown code {
            background: rgba(8, 12, 20, 0.45);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 4px;
            font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
            font-size: 0.92em;
            padding: 0.08em 0.28em;
        }
        .markdown pre {
            background: rgba(8, 12, 20, 0.62);
            border: 1px solid rgba(255, 255, 255, 0.08);
            border-radius: 6px;
            margin: 0.45em 0 0.85em;
            overflow-x: auto;
            padding: 8px 10px;
            white-space: pre;
        }
        .markdown pre code {
            background: transparent;
            border: none;
            display: block;
            padding: 0;
            white-space: pre;
        }
        .markdown blockquote {
            border-left: 3px solid #90ee90;
            color: #c7d0d0;
            margin: 0.4em 0 0.8em;
            padding-left: 0.8em;
        }
        .markdown a { color: #9cbcff; text-decoration: underline; }
        .msg.error { border-left-color: #ff6b6b; }
        .msg.error .content { color: #ffaaaa; }
        .msg.pending { opacity: 0.7; }
        .msg.processing {
            opacity: 0.85;
            border-left-color: #f0c060;
        }
        .msg.processing .content { color: #bbb; }
        .typing-indicator {
            display: inline-flex;
            gap: 2px;
            align-items: center;
            font-weight: 700;
            color: #ddd;
        }
        .typing-indicator span {
            animation: typing-breathe 1.25s ease-in-out infinite;
            opacity: 0.25;
        }
        .typing-indicator span:nth-child(2) { animation-delay: 0.18s; }
        .typing-indicator span:nth-child(3) { animation-delay: 0.36s; }
        @keyframes typing-breathe {
            0%, 80%, 100% { opacity: 0.25; transform: translateY(0); }
            40% { opacity: 1; transform: translateY(-1px); }
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
        .header-btn {
            background: transparent;
            border: 1px solid #444;
            color: #888;
            padding: 2px 8px;
            border-radius: 4px;
            cursor: pointer;
            font-size: 0.82em;
        }
        .header-btn:hover { border-color: #888; color: #ccc; }
        .header-btn:disabled { opacity: 0.45; cursor: not-allowed; }
        .header-btn:disabled:hover { border-color: #444; color: #888; }
        .session-select {
            background: #2d2d54;
            color: #aaa;
            border: 1px solid #444;
            border-radius: 4px;
            padding: 2px 6px;
            font-size: 0.78em;
            cursor: pointer;
            max-width: 140px;
        }
        .session-select:focus { border-color: #6495ed; outline: none; }
    </style>
</head>
<body>
    <div class="header">
        <h2>💬 Yachiyo</h2>
        <div class="meta">
            <select class="session-select" id="session-select" onchange="switchSession(this.value)" title="切换会话"></select>
            <span class="executor" id="executor-badge">—</span>
            <button class="header-btn" onclick="newChat()">新对话</button>
            <button class="header-btn" id="delete-session-btn" onclick="deleteChat()" title="删除此对话">删除</button>
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
const POLL_INTERVAL_MS = 500;
const TYPE_BASE_CHARS_PER_SECOND = 85;
const TYPE_MAX_CHARS_PER_SECOND = 360;
const SCROLL_BOTTOM_THRESHOLD = 12;
let typewriterFrame = null;
let typewriterLastTs = 0;
let stickToBottom = true;
let lastMessageScrollTop = 0;
const messageRenderState = new Map();

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
        stickToBottom = true;
        await refreshMessages();
        await loadSessions();
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
        messageRenderState.clear();
        container.innerHTML = '<div class="empty-hint">发送消息开始对话 ✨</div>';
        stickToBottom = true;
        return;
    }
    const shouldScroll = shouldAutoScroll(container);
    const previousScrollTop = container.scrollTop;
    let html = '';
    let needsTypewriter = false;
    const visibleIds = new Set();
    for (const m of msgs) {
        visibleIds.add(m.id);
        const label = m.role === 'user' ? '你' : (m.role === 'assistant' ? 'Yachiyo' : '系统');
        const isProcessing = m.status === 'processing';
        const sc = m.status === 'failed' ? 'error' : (isProcessing ? 'processing' : (m.status === 'pending' ? 'pending' : ''));
        const suffix = m.status === 'pending' ? ' · 等待中' : '';

        let displayContent;
        if (isProcessing && m.role === 'assistant') {
            displayContent = renderAssistantContent(m);
            needsTypewriter = needsTypewriter || shouldContinueTyping(m.id);
        } else if (m.role === 'assistant' && m.content) {
            displayContent = renderAssistantContent(m);
            needsTypewriter = needsTypewriter || shouldContinueTyping(m.id);
        } else {
            messageRenderState.delete(m.id);
            displayContent = renderMarkdown(m.content);
        }

        html += '<div class="msg ' + m.role + ' ' + sc + '">';
        html += '<div class="role">' + label + suffix + '</div>';
        html += '<div class="content markdown" data-message-id="' + escapeHtml(m.id) + '">' + displayContent + '</div>';
        html += '</div>';
    }
    for (const id of Array.from(messageRenderState.keys())) {
        if (!visibleIds.has(id)) messageRenderState.delete(id);
    }
    container.innerHTML = html;
    if (shouldScroll) {
        scrollToBottom(container);
    } else {
        container.scrollTop = previousScrollTop;
    }
    if (needsTypewriter) startTypewriter();
}

function escapeHtml(t) {
    const d = document.createElement('div');
    d.textContent = t;
    return d.innerHTML;
}

function renderMarkdown(text) {
    const source = String(text || '').replace(/\r\n/g, '\n');
    if (!source) return '';

    const lines = source.split('\n');
    let html = '';
    let paragraph = [];
    let listType = null;
    let inCode = false;
    let codeLines = [];

    function flushParagraph() {
        if (paragraph.length === 0) return;
        html += '<p>' + paragraph.map(renderInlineMarkdown).join('<br>') + '</p>';
        paragraph = [];
    }

    function closeList() {
        if (!listType) return;
        html += '</' + listType + '>';
        listType = null;
    }

    function openList(type) {
        if (listType === type) return;
        closeList();
        listType = type;
        html += '<' + type + '>';
    }

    function flushCode() {
        html += '<pre><code>' + escapeHtml(codeLines.join('\n')) + '</code></pre>';
        codeLines = [];
        inCode = false;
    }

    for (const line of lines) {
        if (line.trim().startsWith('```')) {
            if (inCode) {
                flushCode();
            } else {
                flushParagraph();
                closeList();
                inCode = true;
                codeLines = [];
            }
            continue;
        }

        if (inCode) {
            codeLines.push(line);
            continue;
        }

        if (!line.trim()) {
            flushParagraph();
            closeList();
            continue;
        }

        const heading = line.match(/^(#{1,3})\s+(.+)$/);
        if (heading) {
            flushParagraph();
            closeList();
            const level = heading[1].length;
            html += '<h' + level + '>' + renderInlineMarkdown(heading[2]) + '</h' + level + '>';
            continue;
        }

        const quote = line.match(/^>\s?(.*)$/);
        if (quote) {
            flushParagraph();
            closeList();
            html += '<blockquote>' + renderInlineMarkdown(quote[1]) + '</blockquote>';
            continue;
        }

        const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
        if (unordered) {
            flushParagraph();
            openList('ul');
            html += '<li>' + renderInlineMarkdown(unordered[1]) + '</li>';
            continue;
        }

        const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
        if (ordered) {
            flushParagraph();
            openList('ol');
            html += '<li>' + renderInlineMarkdown(ordered[1]) + '</li>';
            continue;
        }

        closeList();
        paragraph.push(line);
    }

    if (inCode) flushCode();
    flushParagraph();
    closeList();
    return html;
}

function renderInlineMarkdown(text) {
    const codes = [];
    let value = escapeHtml(text);
    value = value.replace(/`([^`]+)`/g, function(_, code) {
        const token = '\u0000CODE' + codes.length + '\u0000';
        codes.push('<code>' + code + '</code>');
        return token;
    });
    value = value.replace(/\[([^\]]+)\]\(([^)\s]+)\)/g, function(_, label, url) {
        const safeUrl = sanitizeMarkdownUrl(url);
        if (!safeUrl) return label;
        return '<a href="' + safeUrl + '" target="_blank" rel="noreferrer">' + label + '</a>';
    });
    value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
    value = value.replace(/__([^_]+)__/g, '<strong>$1</strong>');
    value = value.replace(/(^|[^*])\*([^*\s][^*]*?)\*/g, '$1<em>$2</em>');
    value = value.replace(/(^|[^_])_([^_\s][^_]*?)_/g, '$1<em>$2</em>');
    codes.forEach(function(code, i) {
        value = value.replace('\u0000CODE' + i + '\u0000', code);
    });
    return value;
}

function sanitizeMarkdownUrl(url) {
    const value = String(url || '').trim();
    if (!value) {
        return '';
    }
    try {
        const parsed = new URL(value);
        if (
            parsed.protocol === 'http:' ||
            parsed.protocol === 'https:' ||
            parsed.protocol === 'mailto:'
        ) {
            return value;
        }
    } catch (e) {
        return '';
    }
    return '';
}

function renderAssistantContent(m) {
    if (!m.content) {
        if (!messageRenderState.has(m.id)) {
            messageRenderState.set(m.id, { shown: '', target: '' });
        }
        return '<span class="typing-indicator"><span>.</span><span>.</span><span>.</span></span>';
    }
    let state = messageRenderState.get(m.id);
    if (!state) {
        state = {
            shown: m.status === 'processing' ? '' : m.content,
            target: m.content
        };
        messageRenderState.set(m.id, state);
    } else if (state.target !== m.content) {
        state.target = m.content;
        if (!state.target.startsWith(state.shown)) {
            state.shown = m.status === 'processing' ? '' : state.target;
        }
    }
    return renderMarkdown(state.shown);
}

function shouldContinueTyping(id) {
    const state = messageRenderState.get(id);
    return !!state && state.shown.length < state.target.length;
}

function startTypewriter() {
    if (typewriterFrame) return;
    typewriterLastTs = 0;
    typewriterFrame = requestAnimationFrame(tickTypewriter);
}

function tickTypewriter(ts) {
    if (!typewriterLastTs) typewriterLastTs = ts;
    const elapsed = Math.max(0.016, (ts - typewriterLastTs) / 1000);
    typewriterLastTs = ts;
    let pending = false;

    for (const [id, state] of messageRenderState.entries()) {
        if (state.shown.length >= state.target.length) continue;
        const remaining = state.target.length - state.shown.length;
        const speed = Math.min(
            TYPE_MAX_CHARS_PER_SECOND,
            TYPE_BASE_CHARS_PER_SECOND + Math.floor(remaining / 4)
        );
        const step = Math.max(1, Math.floor(speed * elapsed));
        state.shown = state.target.slice(0, state.shown.length + step);
        const el = document.querySelector('[data-message-id="' + cssEscape(id) + '"]');
        if (el) el.innerHTML = renderMarkdown(state.shown);
        if (state.shown.length < state.target.length) pending = true;
    }

    const container = document.getElementById('messages');
    if (container && shouldAutoScroll(container)) scrollToBottom(container);
    if (pending) {
        typewriterFrame = requestAnimationFrame(tickTypewriter);
    } else {
        typewriterFrame = null;
    }
}

function cssEscape(value) {
    if (window.CSS && CSS.escape) return CSS.escape(value);
    return String(value).replace(/"/g, '\\"');
}

function isNearBottom(container) {
    return container.scrollHeight - container.scrollTop - container.clientHeight <= SCROLL_BOTTOM_THRESHOLD;
}

function shouldAutoScroll(container) {
    return stickToBottom;
}

function scrollToBottom(container) {
    container.scrollTop = container.scrollHeight;
    lastMessageScrollTop = container.scrollTop;
    stickToBottom = true;
}

function bindMessageScroll() {
    const container = document.getElementById('messages');
    if (!container) return;
    lastMessageScrollTop = container.scrollTop;
    container.addEventListener('wheel', function(event) {
        if (event.deltaY < 0) stickToBottom = false;
    }, { passive: true });
    container.addEventListener('scroll', function() {
        const currentTop = container.scrollTop;
        if (currentTop < lastMessageScrollTop) {
            stickToBottom = false;
        } else if (isNearBottom(container)) {
            stickToBottom = true;
        }
        lastMessageScrollTop = currentTop;
    }, { passive: true });
}

function setStatus(t) {
    const el = document.getElementById('status');
    if (el) el.textContent = t;
}

function startPolling() {
    if (polling) return;
    polling = setInterval(refreshMessages, POLL_INTERVAL_MS);
}

function stopPolling() {
    if (polling) { clearInterval(polling); polling = null; }
}

async function deleteChat() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        if (!confirm('删除此对话？此操作不可恢复。')) return;
        stopPolling();
        const r = await window.pywebview.api.delete_current_session();
        if (!r.ok) throw new Error(r.error || '删除失败');
        await loadSessions();
        stickToBottom = true;
        await refreshMessages();
        setStatus(r.empty ? '暂无对话' : '已删除此对话');
    } catch(e) {
        setStatus('❌ ' + e.message);
    }
}

async function newChat() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        stopPolling();
        await window.pywebview.api.new_session();
        await loadSessions();
        stickToBottom = true;
        await refreshMessages();
        setStatus('新对话已创建');
        const input = document.getElementById('input');
        if (input) input.focus();
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

async function loadSessions() {
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        const r = await window.pywebview.api.list_sessions();
        if (!r.ok) return;
        const sel = document.getElementById('session-select');
        if (!sel) return;
        sel.innerHTML = '';
        const deleteBtn = document.getElementById('delete-session-btn');
        if (!r.sessions || r.sessions.length === 0) {
            const opt = document.createElement('option');
            opt.value = '';
            opt.textContent = '无对话';
            opt.selected = true;
            sel.appendChild(opt);
            if (deleteBtn) deleteBtn.disabled = true;
            return;
        }
        if (deleteBtn) deleteBtn.disabled = false;
        for (const s of r.sessions) {
            const opt = document.createElement('option');
            opt.value = s.session_id;
            const label = s.title || s.session_id.substring(0, 8);
            opt.textContent = label + ' (' + s.message_count + ')';
            if (s.session_id === r.current_session_id) opt.selected = true;
            sel.appendChild(opt);
        }
    } catch(e) {}
}

async function switchSession(sessionId) {
    if (!sessionId) return;
    try {
        if (!window.pywebview || !window.pywebview.api) return;
        stopPolling();
        const r = await window.pywebview.api.load_session(sessionId);
        if (!r.ok) { setStatus('❌ ' + (r.error || '切换失败')); return; }
        await loadSessions();
        stickToBottom = true;
        await refreshMessages();
        setStatus('已切换会话');
    } catch(e) {
        setStatus('❌ ' + e.message);
    }
}

// 启动
document.addEventListener('DOMContentLoaded', function() {
    setTimeout(function() {
        bindMessageScroll();
        loadExecutor();
        loadSessions();
        refreshMessages();
    }, 500);
});
</script>
</body>
</html>
"""
