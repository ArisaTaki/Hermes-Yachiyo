import { FormEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useRef, useState } from 'react';
import type {
  ClipboardEvent as ReactClipboardEvent,
  KeyboardEvent as ReactKeyboardEvent,
} from 'react';

import { ImageAttachmentViewer } from '../components/ImageAttachmentViewer';
import { apiGet, apiPost, bridgeUrl, copyText, openAppView, openExternalUrl } from '../lib/bridge';

type PendingAttachment = {
  id: string;
  name: string;
  mime_type: string;
  size: number;
  data_url: string;
};

type ChatAttachment = {
  id?: string;
  kind?: string;
  name?: string;
  mime_type?: string;
  size?: number;
  url?: string;
  source?: string;
  spoken_text?: string;
};

type ChatMessage = {
  id?: string;
  role?: string;
  content?: string;
  text?: string;
  status?: string;
  error?: string;
  attachments?: ChatAttachment[];
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

type ImageInputPayload = {
  can_attach_images?: boolean;
  mode?: string;
  route?: string;
  supports_native_vision?: boolean | null;
  requires_vision_pipeline?: boolean;
  label?: string;
  reason?: string;
};

type ExecutorPayload = {
  executor?: string;
  available?: boolean;
  image_input?: ImageInputPayload;
};

type RenderState = {
  shown: string;
  target: string;
};

type ChatNotice = {
  id: number;
  kind: 'warn' | 'danger';
  title: string;
  detail: string;
};

const ACTIVE_POLL_INTERVAL_MS = 500;
const IDLE_POLL_INTERVAL_MS = 3000;
const EXECUTOR_POLL_INTERVAL_MS = 3000;
const TYPE_BASE_CHARS_PER_SECOND = 85;
const TYPE_MAX_CHARS_PER_SECOND = 360;
const SCROLL_BOTTOM_THRESHOLD = 14;
const COPY_FEEDBACK_MS = 1500;
const MAX_ATTACHMENTS = 4;
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;

export function ChatView() {
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [status, setStatus] = useState('就绪');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [sessions, setSessions] = useState<SessionsPayload | null>(null);
  const [executor, setExecutor] = useState<ExecutorPayload | null>(null);
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const [copiedMessageId, setCopiedMessageId] = useState('');
  const [, setRenderTick] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerComposingRef = useRef(false);
  const renderStateRef = useRef<Map<string, RenderState>>(new Map());
  const animationFrameRef = useRef<number | null>(null);
  const typewriterLastTsRef = useRef(0);
  const stickToBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const noticeTimerRef = useRef<number | null>(null);

  const refreshMessages = useCallback(async () => {
    try {
      const payload = await apiGet<MessagesPayload>('/ui/chat/messages?limit=80');
      if (payload.ok === false) throw new Error(payload.error || '读取消息失败');
      const baseUrl = await bridgeUrl();
      const nextMessages = withResolvedAttachmentUrls(payload.messages || [], baseUrl);
      const processing = Boolean(payload.is_processing);
      const failed = latestFailedMessage(nextMessages);
      setMessages(nextMessages);
      setIsProcessing(processing);
      if (processing) {
        setStatus('处理中...');
      } else if (failed) {
        setStatus(`处理失败：${compactStatusText(messageErrorText(failed))}`);
      } else {
        setStatus('就绪');
      }
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
    const timer = window.setInterval(() => {
      void loadExecutor();
    }, EXECUTOR_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadExecutor]);

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
      if (noticeTimerRef.current !== null) window.clearTimeout(noticeTimerRef.current);
    };
  }, []);

  useEffect(() => {
    function handleKeyDown(event: KeyboardEvent) {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault();
        void clearSession();
      } else if ((event.metaKey || event.ctrlKey) && event.key === '.') {
        event.preventDefault();
        void cancelProcessing();
      } else if (event.key === 'Escape') {
        inputRef.current?.focus();
      }
    }
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  });

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
    if ((!text && attachments.length === 0) || isSending) return;
    if (attachments.length > 0 && !canAttachImages(executor)) {
      showImageInputBlocked();
      return;
    }
    const outgoingAttachments = attachments;
    setInput('');
    setAttachments([]);
    setIsSending(true);
    setIsProcessing(true);
    setStatus(outgoingAttachments.length ? '发送图片中...' : '发送中...');
    stickToBottomRef.current = true;
    try {
      const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/chat/messages', {
        text,
        attachments: outgoingAttachments,
      });
      if (result.ok === false) throw new Error(result.error || '发送失败');
      setStatus('等待回复...');
      await refreshMessages();
      await loadSessions();
    } catch (error) {
      setInput(text);
      setAttachments(outgoingAttachments);
      setStatus(error instanceof Error ? error.message : '发送失败');
      setIsProcessing(false);
    } finally {
      setIsSending(false);
    }
  }

  async function handlePaste(event: ReactClipboardEvent<HTMLTextAreaElement>) {
    const files = clipboardImageFiles(event.clipboardData);
    if (files.length === 0) return;
    event.preventDefault();
    if (!canAttachImages(executor)) {
      showImageInputBlocked();
      return;
    }
    await addImageFiles(files);
  }

  function handleComposerKeyDown(event: ReactKeyboardEvent<HTMLTextAreaElement>) {
    if (event.key !== 'Enter' || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) return;
    if (isImeComposing(event, composerComposingRef.current)) return;
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  }

  async function addImageFiles(files: File[]) {
    if (!canAttachImages(executor)) {
      showImageInputBlocked();
      return;
    }
    const remaining = MAX_ATTACHMENTS - attachments.length;
    if (remaining <= 0) {
      setStatus(`一次最多附加 ${MAX_ATTACHMENTS} 张图片`);
      return;
    }
    const accepted = files.filter((file) => file.type.startsWith('image/')).slice(0, remaining);
    if (accepted.length === 0) {
      setStatus('剪贴板里没有可用图片');
      return;
    }
    const tooLarge = accepted.find((file) => file.size > MAX_ATTACHMENT_BYTES);
    if (tooLarge) {
      setStatus(`图片 ${tooLarge.name || '未命名'} 超过 8 MB`);
      return;
    }
    try {
      const next = await Promise.all(accepted.map(readPendingAttachment));
      setAttachments((current) => [...current, ...next].slice(0, MAX_ATTACHMENTS));
      setStatus(next.length > 1 ? `已附加 ${next.length} 张图片` : '已附加图片');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '读取图片失败');
    }
  }

  function removeAttachment(id: string) {
    setAttachments((current) => current.filter((attachment) => attachment.id !== id));
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

  async function cancelProcessing() {
    if (!isProcessing) return;
    try {
      const result = await apiPost<MessagesPayload & { cancelled_tasks?: number }>('/ui/chat/session/cancel');
      if (result.ok === false) throw new Error(result.error || '取消失败');
      setMessages(result.messages || []);
      setIsProcessing(Boolean(result.is_processing));
      setStatus(result.cancelled_tasks ? `已取消 ${result.cancelled_tasks} 个任务` : '没有可取消任务');
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '取消失败');
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

  function handleMessageListClick(event: ReactMouseEvent<HTMLDivElement>) {
    const anchor = (event.target instanceof Element ? event.target.closest('a[href]') : null) as HTMLAnchorElement | null;
    if (!anchor) return;
    event.preventDefault();
    void openExternalUrl(anchor.href);
  }

  function showNotice(title: string, detail: string, kind: ChatNotice['kind'] = 'warn') {
    if (noticeTimerRef.current !== null) window.clearTimeout(noticeTimerRef.current);
    setNotice({ id: Date.now(), kind, title, detail });
    noticeTimerRef.current = window.setTimeout(() => setNotice(null), 5200);
  }

  function showImageInputBlocked() {
    showNotice('当前不能发送图片', imageInputUnavailableText(executor), 'warn');
    setStatus('图片未附加');
  }

  return (
    <main className="app-shell chat-shell refined-chat-shell">
      {notice ? (
        <div className={`chat-toast ${notice.kind}`} role="status">
          <strong>{notice.title}</strong>
          <span>{notice.detail}</span>
          <button type="button" aria-label="关闭提示" onClick={() => setNotice(null)}>×</button>
        </div>
      ) : null}
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
          <button type="button" className="ghost-button" onClick={() => void cancelProcessing()} disabled={!isProcessing}>停止</button>
          <button type="button" className="ghost-button" onClick={() => void clearSession()}>新对话</button>
          <button type="button" className="ghost-button danger-action" onClick={() => void deleteSession()} disabled={!sessions?.sessions?.length}>删除</button>
        </div>
      </header>

      <section className="chat-list refined-chat-list" ref={listRef} onClick={handleMessageListClick} onScroll={handleScroll}>
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
        <div className="composer-body">
          {attachments.length ? (
            <div className="composer-attachments" aria-label="已附加图片">
              {attachments.map((attachment) => (
                <figure className="composer-attachment" key={attachment.id}>
                  <img src={attachment.data_url} alt={attachment.name} />
                  <figcaption>{attachment.name}</figcaption>
                  <button
                    type="button"
                    aria-label={`移除 ${attachment.name}`}
                    onClick={() => removeAttachment(attachment.id)}
                  >
                    ×
                  </button>
                </figure>
              ))}
            </div>
          ) : null}
          <textarea
            ref={inputRef}
            value={input}
            onChange={(event) => setInput(event.target.value)}
            onCompositionEnd={() => {
              composerComposingRef.current = false;
            }}
            onCompositionStart={() => {
              composerComposingRef.current = true;
            }}
            onKeyDown={handleComposerKeyDown}
            onPaste={(event) => void handlePaste(event)}
            placeholder="输入消息，或直接粘贴图片..."
            disabled={isSending}
            rows={1}
          />
        </div>
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          hidden
          onChange={(event) => {
            const files = Array.from(event.target.files || []);
            event.target.value = '';
            void addImageFiles(files);
          }}
        />
        <button
          type="button"
          className="composer-attach-button"
          disabled={isSending || !canAttachImages(executor) || attachments.length >= MAX_ATTACHMENTS}
          title={imageInputHelpText(executor)}
          onClick={() => fileInputRef.current?.click()}
        >
          图片
        </button>
        <button type="submit" disabled={isSending || (!input.trim() && attachments.length === 0)}>发送</button>
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
      {message.attachments?.length ? (
        <div className="message-attachments">
          {message.attachments.map((attachment) => (
            <ImageAttachmentViewer attachment={attachment} key={attachment.id || attachment.name} />
          ))}
        </div>
      ) : null}
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

function messageErrorText(message: ChatMessage) {
  return String(
    message.error || message.content || message.text || '任务执行失败',
  ).trim();
}

function latestFailedMessage(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const status = messages[index]?.status;
    if (!status) continue;
    if (status === 'failed') return messages[index];
    if (status === 'pending' || status === 'processing' || status === 'completed') {
      return null;
    }
  }
  return null;
}

function compactStatusText(text: string, maxLength = 96) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '任务执行失败';
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 3)}...` : normalized;
}

function isImeComposing(event: ReactKeyboardEvent<HTMLElement>, fallback = false) {
  const nativeEvent = event.nativeEvent as KeyboardEvent & { isComposing?: boolean };
  return Boolean(fallback || nativeEvent.isComposing || nativeEvent.keyCode === 229);
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

function canAttachImages(executor: ExecutorPayload | null) {
  return executor?.available === true && executor.image_input?.can_attach_images === true;
}

function imageInputUnavailableText(executor: ExecutorPayload | null) {
  return executor?.image_input?.reason
    || '当前主模型不能直接读取图片。请在主控台切换支持图片的模型，或单独设置图片识别模型后再发送。';
}

function imageInputHelpText(executor: ExecutorPayload | null) {
  const imageInput = executor?.image_input;
  if (!imageInput) return '附加图片';
  return imageInput.reason || imageInput.label || '附加图片';
}

function sessionLabel(session: SessionItem) {
  const title = session.title || session.session_id.slice(0, 8);
  return `${title} (${session.message_count || 0})`;
}

function withResolvedAttachmentUrls(messages: ChatMessage[], baseUrl: string): ChatMessage[] {
  return messages.map((message) => {
    if (!message.attachments?.length) return message;
    return {
      ...message,
      attachments: message.attachments.map((attachment) => ({
        ...attachment,
        url: resolveAttachmentUrl(attachment.url, baseUrl),
      })),
    };
  });
}

function resolveAttachmentUrl(url: string | undefined, baseUrl: string) {
  if (!url) return '';
  if (/^https?:\/\//i.test(url) || url.startsWith('data:')) return url;
  if (!url.startsWith('/')) return url;
  return `${baseUrl}${url}`;
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

function clipboardImageFiles(data: DataTransfer | null) {
  if (!data) return [];
  const files: File[] = [];
  for (const item of Array.from(data.items || [])) {
    if (item.kind !== 'file' || !item.type.startsWith('image/')) continue;
    const file = item.getAsFile();
    if (file) files.push(file);
  }
  if (files.length) return files;
  return Array.from(data.files || []).filter((file) => file.type.startsWith('image/'));
}

function readPendingAttachment(file: File): Promise<PendingAttachment> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onerror = () => reject(new Error(`读取图片失败：${file.name || '未命名'}`));
    reader.onload = () => {
      const dataUrl = typeof reader.result === 'string' ? reader.result : '';
      if (!dataUrl.startsWith('data:image/')) {
        reject(new Error('只支持图片附件'));
        return;
      }
      resolve({
        id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name || 'pasted-image.png',
        mime_type: file.type || 'image/png',
        size: file.size,
        data_url: dataUrl,
      });
    };
    reader.readAsDataURL(file);
  });
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

  for (let index = 0; index < lines.length; index += 1) {
    const line = lines[index];
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

    const nextLine = lines[index + 1] || '';
    if (isMarkdownTableHeader(line, nextLine)) {
      flushParagraph();
      closeList();
      const headers = splitMarkdownTableRow(line);
      const alignments = splitMarkdownTableRow(nextLine).map(markdownTableAlignment);
      const rows: string[][] = [];
      index += 2;
      while (index < lines.length && lineLooksLikeMarkdownTableRow(lines[index])) {
        rows.push(splitMarkdownTableRow(lines[index]));
        index += 1;
      }
      index -= 1;
      html += renderMarkdownTable(headers, alignments, rows);
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

function isMarkdownTableHeader(headerLine: string, separatorLine: string) {
  const headerCells = splitMarkdownTableRow(headerLine);
  if (headerCells.length < 2) return false;
  return isMarkdownTableSeparator(separatorLine, headerCells.length);
}

function isMarkdownTableSeparator(line: string, expectedCells: number) {
  const cells = splitMarkdownTableRow(line);
  if (cells.length < 2 || cells.length < expectedCells) return false;
  return cells.every((cell) => /^:?-{3,}:?$/.test(cell.replace(/\s+/g, '')));
}

function lineLooksLikeMarkdownTableRow(line: string) {
  if (!line.trim()) return false;
  return splitMarkdownTableRow(line).length >= 2;
}

function splitMarkdownTableRow(line: string) {
  let value = line.trim();
  if (value.startsWith('|')) value = value.slice(1);
  if (value.endsWith('|')) value = value.slice(0, -1);
  const cells: string[] = [];
  let current = '';
  let inCode = false;
  for (let index = 0; index < value.length; index += 1) {
    const char = value[index];
    const previous = value[index - 1];
    if (char === '`' && previous !== '\\') inCode = !inCode;
    if (char === '|' && previous !== '\\' && !inCode) {
      cells.push(current.trim().replace(/\\\|/g, '|'));
      current = '';
      continue;
    }
    current += char;
  }
  cells.push(current.trim().replace(/\\\|/g, '|'));
  return cells;
}

function markdownTableAlignment(cell: string): '' | 'left' | 'center' | 'right' {
  const value = cell.replace(/\s+/g, '');
  if (value.startsWith(':') && value.endsWith(':')) return 'center';
  if (value.endsWith(':')) return 'right';
  if (value.startsWith(':')) return 'left';
  return '';
}

function renderMarkdownTable(headers: string[], alignments: Array<'' | 'left' | 'center' | 'right'>, rows: string[][]) {
  const columnCount = headers.length;
  const alignAttr = (index: number) => (alignments[index] ? ` class="align-${alignments[index]}"` : '');
  const headerHtml = headers
    .map((cell, index) => `<th${alignAttr(index)}>${renderInlineMarkdown(cell)}</th>`)
    .join('');
  const bodyHtml = rows
    .map((row) => {
      const cells = Array.from({ length: columnCount }, (_unused, index) => row[index] || '');
      return `<tr>${cells.map((cell, index) => `<td${alignAttr(index)}>${renderInlineMarkdown(cell)}</td>`).join('')}</tr>`;
    })
    .join('');
  return `<div class="markdown-table-wrap"><table><thead><tr>${headerHtml}</tr></thead><tbody>${bodyHtml}</tbody></table></div>`;
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
