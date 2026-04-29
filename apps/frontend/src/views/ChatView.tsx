import { FormEvent, useCallback, useEffect, useRef, useState } from 'react';

import { apiGet, apiPost, copyText, openAppView } from '../lib/bridge';

type ChatMessage = {
  id?: string;
  role?: string;
  content?: string;
  text?: string;
  status?: string;
  error?: string;
};

type MessagesPayload = {
  ok?: boolean;
  error?: string;
  is_processing?: boolean;
  messages?: ChatMessage[];
};

type SessionItem = {
  session_id: string;
  title?: string;
  message_count?: number;
};

type SessionsPayload = {
  ok?: boolean;
  current_session_id?: string;
  sessions?: SessionItem[];
};

type ExecutorPayload = {
  executor?: string;
  available?: boolean;
};

type RenderState = {
  shown: string;
  target: string;
};

const ACTIVE_POLL_INTERVAL_MS = 500;
const IDLE_POLL_INTERVAL_MS = 3000;
const TYPE_BASE_CHARS_PER_SECOND = 85;
const TYPE_MAX_CHARS_PER_SECOND = 360;
const SCROLL_BOTTOM_THRESHOLD = 14;
const COPY_FEEDBACK_MS = 1500;

export function ChatView() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [status, setStatus] = useState('就绪');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [sessions, setSessions] = useState<SessionsPayload | null>(null);
  const [executor, setExecutor] = useState<ExecutorPayload | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState('');
  const [, setRenderTick] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const renderStateRef = useRef<Map<string, RenderState>>(new Map());
  const animationFrameRef = useRef<number | null>(null);
  const typewriterLastTsRef = useRef(0);
  const stickToBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);

  const refreshMessages = useCallback(async () => {
    try {
      const payload = await apiGet<MessagesPayload>('/ui/chat/messages?limit=80');
      if (payload.ok === false) throw new Error(payload.error || '读取消息失败');
      setMessages(payload.messages || []);
      setIsProcessing(Boolean(payload.is_processing));
      setStatus(payload.is_processing ? '处理中...' : '就绪');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '读取消息失败');
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const payload = await apiGet<SessionsPayload>('/ui/chat/sessions?limit=20');
      if (payload.ok === false) throw new Error('读取会话失败');
      setSessions(payload);
    } catch {
      setSessions(null);
    }
  }, []);

  const loadExecutor = useCallback(async () => {
    try {
      setExecutor(await apiGet<ExecutorPayload>('/ui/chat/executor'));
    } catch {
      setExecutor({ executor: 'none', available: false });
    }
  }, []);

  useEffect(() => {
    void refreshMessages();
    void loadSessions();
    void loadExecutor();
  }, [loadExecutor, loadSessions, refreshMessages]);

  useEffect(() => {
    const interval = isProcessing ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS;
    const timer = window.setInterval(refreshMessages, interval);
    return () => window.clearInterval(timer);
  }, [isProcessing, refreshMessages]);

  useEffect(() => {
    syncRenderStates(messages, renderStateRef.current);
    if (shouldContinueTyping(renderStateRef.current)) startTypewriter();
  }, [messages]);

  useEffect(() => {
    const list = listRef.current;
    if (!list || !stickToBottomRef.current) return;
    list.scrollTo({ top: list.scrollHeight });
    lastScrollTopRef.current = list.scrollTop;
  }, [messages]);

  useEffect(() => {
    return () => {
      if (animationFrameRef.current !== null) window.cancelAnimationFrame(animationFrameRef.current);
    };
  }, []);

  function startTypewriter() {
    if (animationFrameRef.current !== null) return;
    typewriterLastTsRef.current = 0;
    animationFrameRef.current = window.requestAnimationFrame(tickTypewriter);
  }

  function tickTypewriter(timestamp: number) {
    if (!typewriterLastTsRef.current) typewriterLastTsRef.current = timestamp;
    const elapsed = Math.max(0.016, (timestamp - typewriterLastTsRef.current) / 1000);
    typewriterLastTsRef.current = timestamp;
    let pending = false;

    for (const state of renderStateRef.current.values()) {
      if (state.shown.length >= state.target.length) continue;
      const remaining = state.target.length - state.shown.length;
      const speed = Math.min(
        TYPE_MAX_CHARS_PER_SECOND,
        TYPE_BASE_CHARS_PER_SECOND + Math.floor(remaining / 4),
      );
      const step = Math.max(1, Math.floor(speed * elapsed));
      state.shown = state.target.slice(0, state.shown.length + step);
      if (state.shown.length < state.target.length) pending = true;
    }

    setRenderTick((value) => value + 1);
    const list = listRef.current;
    if (list && stickToBottomRef.current) list.scrollTo({ top: list.scrollHeight });
    animationFrameRef.current = pending ? window.requestAnimationFrame(tickTypewriter) : null;
  }

  function handleScroll() {
    const list = listRef.current;
    if (!list) return;
    if (list.scrollTop < lastScrollTopRef.current) {
      stickToBottomRef.current = false;
    } else if (isNearBottom(list)) {
      stickToBottomRef.current = true;
    }
    lastScrollTopRef.current = list.scrollTop;
  }

  async function submit(event: FormEvent) {
    event.preventDefault();
    const text = input.trim();
    if (!text || isSending) return;
    setInput('');
    setIsSending(true);
    setIsProcessing(true);
    setStatus('发送中...');
    stickToBottomRef.current = true;
    try {
      const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/chat/messages', { text });
      if (result.ok === false) throw new Error(result.error || '发送失败');
      setStatus('等待回复...');
      await refreshMessages();
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '发送失败');
      setIsProcessing(false);
    } finally {
      setIsSending(false);
    }
  }

  async function clearSession() {
    try {
      await apiPost('/ui/chat/session/clear');
      renderStateRef.current.clear();
      setMessages([]);
      setIsProcessing(false);
      setStatus('新对话已创建');
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '新建对话失败');
    }
  }

  async function deleteSession() {
    if (!window.confirm('删除此对话？此操作不可恢复。')) return;
    try {
      await apiPost('/ui/chat/session/delete');
      renderStateRef.current.clear();
      stickToBottomRef.current = true;
      await loadSessions();
      await refreshMessages();
      setStatus('已删除此对话');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '删除失败');
    }
  }

  async function switchSession(sessionId: string) {
    if (!sessionId || sessionId === sessions?.current_session_id) return;
    try {
      await apiPost('/ui/chat/sessions/load', { session_id: sessionId });
      renderStateRef.current.clear();
      stickToBottomRef.current = true;
      await loadSessions();
      await refreshMessages();
      setStatus('已切换会话');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '切换失败');
    }
  }

  async function copyMessage(message: ChatMessage) {
    const content = messageText(message);
    if (!content) {
      setStatus('没有可复制内容');
      return;
    }
    try {
      await copyText(content);
      setCopiedMessageId(message.id || '');
      setStatus('已复制');
      window.setTimeout(() => setCopiedMessageId(''), COPY_FEEDBACK_MS);
    } catch {
      setStatus('复制失败');
    }
  }

  return (
    <main className="app-shell chat-shell refined-chat-shell">
      <header className="chat-topbar">
        <div className="chat-title-block">
          <h1>Yachiyo</h1>
          <p>本地会话</p>
        </div>
        <div className="chat-toolbar">
          <select
            className="session-select"
            value={sessions?.current_session_id || ''}
            onChange={(event) => void switchSession(event.target.value)}
            disabled={!sessions?.sessions?.length}
            title="切换会话"
          >
            {sessions?.sessions?.length ? sessions.sessions.map((session) => (
              <option key={session.session_id} value={session.session_id}>
                {sessionLabel(session)}
              </option>
            )) : <option value="">无对话</option>}
          </select>
          <span className="executor-badge">{executorLabel(executor)}</span>
          <button type="button" className="ghost-button" onClick={() => void openAppView('main')}>主控台</button>
          <button type="button" className="ghost-button" onClick={() => void clearSession()}>新对话</button>
          <button type="button" className="ghost-button danger-action" onClick={() => void deleteSession()} disabled={!sessions?.sessions?.length}>删除</button>
        </div>
      </header>

      <section className="chat-list refined-chat-list" ref={listRef} onScroll={handleScroll}>
        {messages.length === 0 ? <div className="empty-state">发送消息开始对话</div> : null}
        {messages.map((message, index) => (
          <MessageBubble
            copied={copiedMessageId === message.id}
            displayContent={displayMessageText(message, renderStateRef.current)}
            key={message.id || index}
            message={message}
            onCopy={() => void copyMessage(message)}
          />
        ))}
      </section>

      <form className="composer refined-composer" onSubmit={submit}>
        <input
          value={input}
          onChange={(event) => setInput(event.target.value)}
          placeholder="输入消息..."
          disabled={isSending}
        />
        <button type="submit" disabled={isSending || !input.trim()}>发送</button>
      </form>
      <footer className="status-line refined-status-line">{status}</footer>
    </main>
  );
}

function MessageBubble({ copied, displayContent, message, onCopy }: {
  copied: boolean;
  displayContent: string;
  message: ChatMessage;
  onCopy: () => void;
}) {
  const role = message.role || 'system';
  const statusClass = message.status === 'failed'
    ? 'error'
    : message.status === 'processing'
      ? 'processing'
      : message.status === 'pending'
        ? 'pending'
        : '';
  const isProcessingEmpty = role === 'assistant' && message.status === 'processing' && !displayContent;
  return (
    <article className={`chat-bubble refined-message ${role} ${statusClass}`}>
      <div className="message-header">
        <span>{roleLabel(role)}{message.status === 'pending' ? ' · 等待中' : ''}</span>
        <button
          className={`message-copy-button ${copied ? 'copied' : ''}`}
          type="button"
          title={copied ? '已复制' : '复制内容'}
          aria-label={copied ? '已复制' : '复制内容'}
          onClick={onCopy}
        >
          {copied ? '✓' : '⧉'}
        </button>
      </div>
      {isProcessingEmpty ? (
        <TypingIndicator />
      ) : (
        <div className="message-content markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(displayContent) }} />
      )}
      {message.error ? <div className="message-error">{message.error}</div> : null}
    </article>
  );
}

function TypingIndicator() {
  return (
    <span className="typing-indicator" aria-label="处理中">
      <span>.</span><span>.</span><span>.</span>
    </span>
  );
}

function messageText(message: ChatMessage) {
  return String(message.content || message.text || '');
}

function roleLabel(role: string) {
  if (role === 'user') return '你';
  if (role === 'assistant') return 'Yachiyo';
  return '系统';
}

function executorLabel(executor: ExecutorPayload | null) {
  if (!executor?.available) return '—';
  return executor.executor === 'HermesExecutor' ? 'Hermes' : '模拟';
}

function sessionLabel(session: SessionItem) {
  const title = session.title || session.session_id.slice(0, 8);
  return `${title} (${session.message_count || 0})`;
}

function syncRenderStates(messages: ChatMessage[], states: Map<string, RenderState>) {
  const visibleIds = new Set<string>();
  for (const message of messages) {
    if (!message.id) continue;
    visibleIds.add(message.id);
    if (message.role !== 'assistant') {
      states.delete(message.id);
      continue;
    }
    const content = messageText(message);
    const existing = states.get(message.id);
    if (!existing) {
      states.set(message.id, {
        shown: message.status === 'processing' ? '' : content,
        target: content,
      });
      continue;
    }
    if (existing.target !== content) {
      existing.target = content;
      if (!content.startsWith(existing.shown)) {
        existing.shown = message.status === 'processing' ? '' : content;
      }
    }
  }
  for (const id of Array.from(states.keys())) {
    if (!visibleIds.has(id)) states.delete(id);
  }
}

function displayMessageText(message: ChatMessage, states: Map<string, RenderState>) {
  if (message.role !== 'assistant' || !message.id) return messageText(message);
  return states.get(message.id)?.shown || '';
}

function shouldContinueTyping(states: Map<string, RenderState>) {
  for (const state of states.values()) {
    if (state.shown.length < state.target.length) return true;
  }
  return false;
}

function isNearBottom(container: HTMLDivElement) {
  return container.scrollHeight - container.scrollTop - container.clientHeight <= SCROLL_BOTTOM_THRESHOLD;
}

function escapeHtml(text: string) {
  return text
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#039;');
}

function renderMarkdown(text: string) {
  const source = String(text || '').replace(/\r\n/g, '\n');
  if (!source) return '';

  const lines = source.split('\n');
  let html = '';
  let paragraph: string[] = [];
  let listType: 'ul' | 'ol' | null = null;
  let inCode = false;
  let codeLines: string[] = [];

  function flushParagraph() {
    if (paragraph.length === 0) return;
    html += `<p>${paragraph.map(renderInlineMarkdown).join('<br>')}</p>`;
    paragraph = [];
  }

  function closeList() {
    if (!listType) return;
    html += `</${listType}>`;
    listType = null;
  }

  function openList(type: 'ul' | 'ol') {
    if (listType === type) return;
    closeList();
    listType = type;
    html += `<${type}>`;
  }

  function flushCode() {
    html += `<pre><code>${escapeHtml(codeLines.join('\n'))}</code></pre>`;
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
      html += `<h${level}>${renderInlineMarkdown(heading[2])}</h${level}>`;
      continue;
    }

    const quote = line.match(/^>\s?(.*)$/);
    if (quote) {
      flushParagraph();
      closeList();
      html += `<blockquote>${renderInlineMarkdown(quote[1])}</blockquote>`;
      continue;
    }

    const unordered = line.match(/^\s*[-*+]\s+(.+)$/);
    if (unordered) {
      flushParagraph();
      openList('ul');
      html += `<li>${renderInlineMarkdown(unordered[1])}</li>`;
      continue;
    }

    const ordered = line.match(/^\s*\d+\.\s+(.+)$/);
    if (ordered) {
      flushParagraph();
      openList('ol');
      html += `<li>${renderInlineMarkdown(ordered[1])}</li>`;
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

function renderInlineMarkdown(text: string) {
  const codes: string[] = [];
  let value = escapeHtml(text);
  value = value.replace(/`([^`]+)`/g, (_match, code: string) => {
    const token = `\u0000CODE${codes.length}\u0000`;
    codes.push(`<code>${escapeHtml(code)}</code>`);
    return token;
  });
  value = value.replace(/\[([^\]]+)]\(([^)\s]+)\)/g, (_match, label: string, url: string) => {
    const safeUrl = sanitizeMarkdownUrl(url);
    if (!safeUrl) return escapeHtml(label);
    return `<a href="${safeUrl}" target="_blank" rel="noreferrer">${escapeHtml(label)}</a>`;
  });
  value = value.replace(/\*\*([^*]+)\*\*/g, '<strong>$1</strong>');
  value = value.replace(/__([^_]+)__/g, '<strong>$1</strong>');
  value = value.replace(/(^|[^*])\*([^*\s][^*]*?)\*/g, '$1<em>$2</em>');
  value = value.replace(/(^|[^_])_([^_\s][^_]*?)_/g, '$1<em>$2</em>');
  codes.forEach((code, index) => {
    value = value.replace(`\u0000CODE${index}\u0000`, code);
  });
  return value;
}

function sanitizeMarkdownUrl(url: string) {
  const value = String(url || '').trim();
  if (!value) return '';
  try {
    const parsed = new URL(value);
    if (parsed.protocol === 'http:' || parsed.protocol === 'https:' || parsed.protocol === 'mailto:') {
      return escapeHtml(value);
    }
  } catch {
    return '';
  }
  return '';
}
