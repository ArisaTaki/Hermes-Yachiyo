import { FormEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useRef, useState } from 'react';
import type {
  ClipboardEvent as ReactClipboardEvent,
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from 'react';

import { ImageAttachmentViewer } from '../components/ImageAttachmentViewer';
import { UiIcon } from '../components/UiIcon';
import logoUrl from '../../../../docs/open-design/logo.png';
import { type AssistantProfileSeed, useAssistantProfileSeed } from '../lib/assistantProfileSeed';
import { apiGet, apiPost, bridgeUrl, copyText, openAppView, openExternalUrl } from '../lib/bridge';
import { currentParam } from '../lib/view';

type PendingAttachment = {
  id: string;
  name: string;
  mime_type: string;
  size: number;
  width?: number;
  height?: number;
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

type ChatActivityEvent = {
  event_id?: string;
  session_id?: string;
  task_id?: string;
  tool_name?: string;
  phase?: string;
  title?: string;
  detail?: string;
  status?: string;
  duration_seconds?: number | null;
  created_at?: string;
};

type ChatMessage = {
  id?: string;
  role?: string;
  content?: string;
  text?: string;
  status?: string;
  error?: string;
  created_at?: string;
  task_id?: string;
  progress_label?: string;
  activity_events?: ChatActivityEvent[];
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
  created_at?: string;
  updated_at?: string;
  message_count?: number;
  is_processing?: boolean;
  latest_activity?: ChatActivityEvent | null;
  latest_message_preview?: string;
  latest_message_status?: string;
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

type AssistantProfilePayload = {
  ok?: boolean;
  agent_name?: string;
  agent_nickname?: string;
  agent_avatar_url?: string;
  user_avatar_url?: string;
};

type RenderState = {
  shown: string;
  target: string;
};

type ChatViewProps = {
  embedded?: boolean;
};

type ChatNotice = {
  id: number;
  kind: 'warn' | 'danger';
  title: string;
  detail: string;
};

let cachedAssistantProfile: AssistantProfilePayload | null = null;

function profileFromSeed(seed: AssistantProfileSeed | null): AssistantProfilePayload | null {
  if (!seed?.agent_avatar_url && !seed?.agent_name && !seed?.agent_nickname && !seed?.user_avatar_url) return null;
  return {
    agent_name: seed.agent_name,
    agent_nickname: seed.agent_nickname,
    agent_avatar_url: seed.agent_avatar_url,
    user_avatar_url: seed.user_avatar_url,
  };
}

function mergeAssistantProfileSeed(current: AssistantProfilePayload | null, seed: AssistantProfilePayload): AssistantProfilePayload {
  return {
    ...seed,
    ...(current || {}),
    agent_name: current?.agent_name || seed.agent_name,
    agent_nickname: current?.agent_nickname || seed.agent_nickname,
    agent_avatar_url: current?.agent_avatar_url || seed.agent_avatar_url,
    user_avatar_url: current?.user_avatar_url || seed.user_avatar_url,
  };
}

const ACTIVE_POLL_INTERVAL_MS = 500;
const IDLE_POLL_INTERVAL_MS = 3000;
const EXECUTOR_POLL_INTERVAL_MS = 3000;
const TYPE_BASE_CHARS_PER_SECOND = 85;
const TYPE_MAX_CHARS_PER_SECOND = 360;
const SCROLL_BOTTOM_THRESHOLD = 14;
const COPY_FEEDBACK_MS = 1500;
const MAX_ATTACHMENTS = 4;
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const MIN_LOADING_MS = 1400;
const CHAT_SIDEBAR_MIN_WIDTH = 220;
const CHAT_SIDEBAR_BASE_MAX_WIDTH = 280;
const CHAT_SIDEBAR_WIDE_MAX_WIDTH = 360;
const CHAT_WIDE_VIEWPORT_WIDTH = 1500;
const COMPOSER_MIN_HEIGHT = 48;
const COMPOSER_MAX_HEIGHT = 260;
const COMPOSER_HEIGHT_STORAGE_KEY = 'hermes.chat.composerHeight';

export function ChatView({ embedded = false }: ChatViewProps = {}) {
  const assistantProfileSeed = useAssistantProfileSeed();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [input, setInput] = useState('');
  const [attachments, setAttachments] = useState<PendingAttachment[]>([]);
  const [status, setStatus] = useState('就绪');
  const [isProcessing, setIsProcessing] = useState(false);
  const [isSending, setIsSending] = useState(false);
  const [sessions, setSessions] = useState<SessionsPayload | null>(null);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [executor, setExecutor] = useState<ExecutorPayload | null>(null);
  const [assistantProfile, setAssistantProfile] = useState<AssistantProfilePayload | null>(() => cachedAssistantProfile || profileFromSeed(assistantProfileSeed));
  const [assistantProfileLoading, setAssistantProfileLoading] = useState(() => !(cachedAssistantProfile || profileFromSeed(assistantProfileSeed)));
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const [sessionQuery, setSessionQuery] = useState('');
  const [copiedMessageId, setCopiedMessageId] = useState('');
  const [messagesLoaded, setMessagesLoaded] = useState(false);
  const [messagesVisible, setMessagesVisible] = useState(false);
  const [chatBootstrapped, setChatBootstrapped] = useState(false);
  const [sidebarMaxWidth, setSidebarMaxWidth] = useState(() => responsiveChatSidebarMaxWidth());
  const [sidebarWidth, setSidebarWidth] = useState(CHAT_SIDEBAR_BASE_MAX_WIDTH);
  const [composerHeight, setComposerHeight] = useState(() => storedComposerHeight());
  const [, setRenderTick] = useState(0);
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const composerComposingRef = useRef(false);
  const renderStateRef = useRef<Map<string, RenderState>>(new Map());
  const animationFrameRef = useRef<number | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const typewriterLastTsRef = useRef(0);
  const stickToBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const bottomAnchorRef = useRef<HTMLDivElement>(null);
  const noticeTimerRef = useRef<number | null>(null);
  const messagesLoadedRef = useRef(false);
  const messageLoadTokenRef = useRef(0);
  const conversationLoadTokenRef = useRef(0);
  const conversationTransitionRef = useRef(false);
  const assistantProfileSeedRef = useRef(assistantProfileSeed);
  const messageTextSelectingRef = useRef(false);
  const isProcessingRef = useRef(false);
  const loadSessionsRef = useRef<() => Promise<void>>(async () => undefined);

  const refreshMessages = useCallback(async (options: { allowDuringTransition?: boolean } = {}) => {
    if (conversationTransitionRef.current && !options.allowDuringTransition) return;
    const token = ++messageLoadTokenRef.current;
    const startedAt = Date.now();
    const shouldHoldLoading = !messagesLoadedRef.current;
    try {
      const payload = await apiGet<MessagesPayload>('/ui/chat/messages?limit=80');
      if (payload.ok === false) throw new Error(payload.error || '读取消息失败');
      const baseUrl = await bridgeUrl();
      const nextMessages = withResolvedAttachmentUrls(payload.messages || [], baseUrl);
      const processing = Boolean(payload.is_processing);
      const processingChanged = processing !== isProcessingRef.current;
      isProcessingRef.current = processing;
      const failed = latestFailedMessage(nextMessages);
      if (!shouldHoldLoading && isMessageSelectionPaused()) {
        setIsProcessing(processing);
        setStatus(chatStatusLabel(processing, failed, nextMessages));
        if (processingChanged) void loadSessionsRef.current();
        return;
      }
      syncRenderStates(nextMessages, renderStateRef.current);
      const elapsed = Date.now() - startedAt;
      const remaining = Math.max(0, MIN_LOADING_MS - elapsed);
      if (shouldHoldLoading && remaining > 0) await new Promise((r) => setTimeout(r, remaining));
      if (token !== messageLoadTokenRef.current) return;
      setMessages(nextMessages);
      setIsProcessing(processing);
      if (shouldHoldLoading) {
        await settleMessagesAtBottom(token);
      }
      if (token === messageLoadTokenRef.current) {
        messagesLoadedRef.current = true;
        setMessagesVisible(true);
        setMessagesLoaded(true);
      }
      if (processing) {
        setStatus(chatStatusLabel(processing, failed, nextMessages));
      } else if (failed) {
        setStatus(`处理失败：${compactStatusText(messageErrorText(failed))}`);
      } else {
        setStatus('就绪');
      }
      if (processingChanged) void loadSessionsRef.current();
    } catch (error) {
      const elapsed = Date.now() - startedAt;
      const remaining = Math.max(0, MIN_LOADING_MS - elapsed);
      if (shouldHoldLoading && remaining > 0) await new Promise((r) => setTimeout(r, remaining));
      if (token !== messageLoadTokenRef.current) return;
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
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
    } finally {
      setSessionsLoaded(true);
    }
  }, []);

  useEffect(() => {
    loadSessionsRef.current = loadSessions;
  }, [loadSessions]);

  const loadExecutor = useCallback(async () => {
    try {
      setExecutor(await apiGet<ExecutorPayload>('/ui/chat/executor'));
    } catch {
      setExecutor({ executor: 'none', available: false });
    }
  }, []);

  const loadAssistantProfile = useCallback(async () => {
    try {
      const profile = await apiGet<AssistantProfilePayload>('/assistant/profile');
      if (profile.ok === false) throw new Error('读取助手资料失败');
      cachedAssistantProfile = profile;
      setAssistantProfile(profile);
    } catch {
      const fallback = cachedAssistantProfile || profileFromSeed(assistantProfileSeedRef.current);
      setAssistantProfile(fallback);
    } finally {
      setAssistantProfileLoading(false);
    }
  }, []);

  useEffect(() => {
    assistantProfileSeedRef.current = assistantProfileSeed;
    const seededProfile = profileFromSeed(assistantProfileSeed);
    if (!seededProfile) return;
    setAssistantProfile((current) => {
      const merged = mergeAssistantProfileSeed(current, seededProfile);
      cachedAssistantProfile = merged;
      return merged;
    });
    setAssistantProfileLoading(false);
  }, [assistantProfileSeed]);

  useEffect(() => {
    const requestedSessionId = currentParam('session_id').trim();
    void (async () => {
      await Promise.all([loadAssistantProfile(), loadExecutor()]);
      if (requestedSessionId) {
        try {
          const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/chat/sessions/load', {
            session_id: requestedSessionId,
          });
          if (result.ok === false) throw new Error(result.error || '切换会话失败');
        } catch (error) {
          setStatus(error instanceof Error ? error.message : '切换会话失败');
        }
      }
      await Promise.all([refreshMessages(), loadSessions()]);
    })();
  }, [loadAssistantProfile, loadExecutor, loadSessions, refreshMessages]);

  useEffect(() => {
    const interval = isProcessing ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS;
    const timer = window.setInterval(refreshMessages, interval);
    return () => window.clearInterval(timer);
  }, [isProcessing, refreshMessages]);

  useEffect(() => {
    const timer = window.setInterval(
      () => void loadSessions(),
      isProcessing ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS,
    );
    return () => window.clearInterval(timer);
  }, [isProcessing, loadSessions]);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void loadExecutor();
    }, EXECUTOR_POLL_INTERVAL_MS);
    return () => window.clearInterval(timer);
  }, [loadExecutor]);

  useEffect(() => {
    const refreshProfile = () => void loadAssistantProfile();
    window.addEventListener('hermes-assistant-profile-updated', refreshProfile);
    return () => window.removeEventListener('hermes-assistant-profile-updated', refreshProfile);
  }, [loadAssistantProfile]);

  useEffect(() => {
    if (embedded || chatBootstrapped) return;
    if (messagesLoaded && sessionsLoaded && messagesVisible && !assistantProfileLoading) {
      setChatBootstrapped(true);
    }
  }, [assistantProfileLoading, chatBootstrapped, embedded, messagesLoaded, messagesVisible, sessionsLoaded]);

  useEffect(() => {
    if (embedded) return;
    const syncResponsiveSidebarWidth = () => {
      const maxWidth = responsiveChatSidebarMaxWidth();
      setSidebarMaxWidth(maxWidth);
      setSidebarWidth((width) => {
        return Math.min(Math.max(width, CHAT_SIDEBAR_MIN_WIDTH), maxWidth);
      });
    };
    syncResponsiveSidebarWidth();
    window.addEventListener('resize', syncResponsiveSidebarWidth);
    return () => window.removeEventListener('resize', syncResponsiveSidebarWidth);
  }, [embedded]);

  useEffect(() => {
    syncRenderStates(messages, renderStateRef.current);
    if (shouldContinueTyping(renderStateRef.current)) startTypewriter();
  }, [messages]);

  useEffect(() => {
    scrollToConversationBottom();
  }, [messages, isProcessing]);

  useEffect(() => {
    window.localStorage.setItem(COMPOSER_HEIGHT_STORAGE_KEY, String(composerHeight));
  }, [composerHeight]);

  useEffect(() => {
    const stopSelecting = () => {
      window.setTimeout(() => {
        messageTextSelectingRef.current = false;
      }, 120);
    };
    window.addEventListener('pointerup', stopSelecting);
    window.addEventListener('pointercancel', stopSelecting);
    return () => {
      window.removeEventListener('pointerup', stopSelecting);
      window.removeEventListener('pointercancel', stopSelecting);
    };
  }, []);

  useEffect(() => {
    return () => {
      if (animationFrameRef.current !== null) window.cancelAnimationFrame(animationFrameRef.current);
      if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
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
    scrollToConversationBottom();
    animationFrameRef.current = pending ? window.requestAnimationFrame(tickTypewriter) : null;
  }

  function scrollToConversationBottom(force = false) {
    if (force) stickToBottomRef.current = true;
    if (!force && (!stickToBottomRef.current || isMessageSelectionPaused())) return;
    if (scrollFrameRef.current !== null) window.cancelAnimationFrame(scrollFrameRef.current);
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = window.requestAnimationFrame(() => {
        scrollFrameRef.current = null;
        const list = listRef.current;
        if (!list || (!force && (!stickToBottomRef.current || isMessageSelectionPaused()))) return;
        list.scrollTop = list.scrollHeight;
        bottomAnchorRef.current?.scrollIntoView({ block: 'end' });
        lastScrollTopRef.current = list.scrollTop;
      });
    });
  }

  function isMessageSelectionPaused() {
    return messageTextSelectingRef.current || isMessageTextSelectionActive(listRef.current);
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
    if ((!text && attachments.length === 0) || isSending || isProcessing) return;
    if (attachments.length > 0 && !canAttachImages(executor)) {
      showImageInputBlocked();
      return;
    }
    const outgoingAttachments = attachments;
    setInput('');
    setAttachments([]);
    setIsSending(true);
    isProcessingRef.current = true;
    setIsProcessing(true);
    setStatus(outgoingAttachments.length ? '发送图片中...' : '发送中...');
    stickToBottomRef.current = true;
    scrollToConversationBottom(true);
    try {
      const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/chat/messages', {
        text,
        attachments: outgoingAttachments,
      });
      if (result.ok === false) throw new Error(result.error || '发送失败');
      setStatus('等待回复...');
      void loadSessions();
      await refreshMessages();
      scrollToConversationBottom(true);
      await loadSessions();
    } catch (error) {
      setInput(text);
      setAttachments(outgoingAttachments);
      setStatus(error instanceof Error ? error.message : '发送失败');
      isProcessingRef.current = false;
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
    if (isProcessing) return;
    event.currentTarget.form?.requestSubmit();
  }

  function startComposerResize(event: ReactPointerEvent<HTMLDivElement>) {
    event.preventDefault();
    const startY = event.clientY;
    const startHeight = composerHeight;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture can fail if the handle is detached during route changes.
    }

    const handlePointerMove = (moveEvent: PointerEvent) => {
      const nextHeight = startHeight + startY - moveEvent.clientY;
      setComposerHeight(clampComposerHeight(nextHeight));
    };

    const stopResize = () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', stopResize);
      window.removeEventListener('pointercancel', stopResize);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', stopResize);
    window.addEventListener('pointercancel', stopResize);
  }

  function handleComposerResizeKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setComposerHeight((value) => clampComposerHeight(value + 12));
    } else if (event.key === 'ArrowDown') {
      event.preventDefault();
      setComposerHeight((value) => clampComposerHeight(value - 12));
    } else if (event.key === 'Home') {
      event.preventDefault();
      setComposerHeight(COMPOSER_MIN_HEIGHT);
    } else if (event.key === 'End') {
      event.preventDefault();
      setComposerHeight(COMPOSER_MAX_HEIGHT);
    }
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
      isProcessingRef.current = false;
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
      isProcessingRef.current = Boolean(result.is_processing);
      setIsProcessing(Boolean(result.is_processing));
      setStatus(result.cancelled_tasks ? `已取消 ${result.cancelled_tasks} 个任务` : '没有可取消任务');
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '取消失败');
    }
  }

  async function deleteSession() {
    if (!window.confirm('删除此对话？此操作不可恢复。')) return;
    const conversationToken = beginConversationLoading();
    try {
      await apiPost('/ui/chat/session/delete');
      if (conversationToken !== conversationLoadTokenRef.current) return;
      renderStateRef.current.clear();
      stickToBottomRef.current = true;
      await loadSessions();
      await refreshMessages({ allowDuringTransition: true });
      if (conversationToken === conversationLoadTokenRef.current) conversationTransitionRef.current = false;
      setStatus('已删除此对话');
    } catch (error) {
      if (conversationToken !== conversationLoadTokenRef.current) return;
      conversationTransitionRef.current = false;
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
      setStatus(error instanceof Error ? error.message : '删除失败');
    }
  }

  async function switchSession(sessionId: string) {
    if (!sessionId || sessionId === sessions?.current_session_id) return;
    const conversationToken = beginConversationLoading();
    setStatus('正在切换会话...');
    try {
      await apiPost('/ui/chat/sessions/load', { session_id: sessionId });
      if (conversationToken !== conversationLoadTokenRef.current) return;
      renderStateRef.current.clear();
      stickToBottomRef.current = true;
      await loadSessions();
      await refreshMessages({ allowDuringTransition: true });
      if (conversationToken === conversationLoadTokenRef.current) conversationTransitionRef.current = false;
      setStatus('已切换会话');
    } catch (error) {
      if (conversationToken !== conversationLoadTokenRef.current) return;
      conversationTransitionRef.current = false;
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
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

  function handleMessagePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    const target = event.target instanceof Element ? event.target : null;
    if (!target?.closest('.message-content')) return;
    messageTextSelectingRef.current = true;
    stickToBottomRef.current = false;
  }

  function startSidebarResize(event: ReactPointerEvent<HTMLDivElement>) {
    if (embedded) return;
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = sidebarWidth;
    try {
      event.currentTarget.setPointerCapture(event.pointerId);
    } catch {
      // Pointer capture can fail if the target is detached during a route switch.
    }

    const handlePointerMove = (moveEvent: PointerEvent) => {
      const nextWidth = Math.max(
        CHAT_SIDEBAR_MIN_WIDTH,
        Math.min(sidebarMaxWidth, startWidth + moveEvent.clientX - startX),
      );
      setSidebarWidth(Math.round(nextWidth));
    };

    const stopResize = () => {
      window.removeEventListener('pointermove', handlePointerMove);
      window.removeEventListener('pointerup', stopResize);
      window.removeEventListener('pointercancel', stopResize);
    };

    window.addEventListener('pointermove', handlePointerMove);
    window.addEventListener('pointerup', stopResize);
    window.addEventListener('pointercancel', stopResize);
  }

  function handleSidebarResizerKeyDown(event: ReactKeyboardEvent<HTMLDivElement>) {
    if (embedded) return;
    if (event.key === 'ArrowLeft') {
      event.preventDefault();
      setSidebarWidth((value) => Math.max(CHAT_SIDEBAR_MIN_WIDTH, value - 12));
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      setSidebarWidth((value) => Math.min(sidebarMaxWidth, value + 12));
    } else if (event.key === 'Home') {
      event.preventDefault();
      setSidebarWidth(CHAT_SIDEBAR_MIN_WIDTH);
    } else if (event.key === 'End') {
      event.preventDefault();
      setSidebarWidth(sidebarMaxWidth);
    }
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

  function beginConversationLoading() {
    const conversationToken = ++conversationLoadTokenRef.current;
    conversationTransitionRef.current = true;
    messageLoadTokenRef.current += 1;
    messagesLoadedRef.current = false;
    setMessagesLoaded(false);
    setMessagesVisible(false);
    return conversationToken;
  }

  function settleMessagesAtBottom(token: number) {
    return new Promise<void>((resolve) => {
      let frames = 0;
      let stableFrames = 0;
      let previousHeight = -1;
      const minFrames = 4;
      const maxFrames = 24;
      const requiredStableFrames = 4;

      const settle = () => {
        if (token !== messageLoadTokenRef.current) {
          resolve();
          return;
        }
        const list = listRef.current;
        if (list) {
          const height = list.scrollHeight;
          stableFrames = height === previousHeight ? stableFrames + 1 : 0;
          previousHeight = height;
          stickToBottomRef.current = true;
          list.scrollTop = height;
          lastScrollTopRef.current = list.scrollTop;
        }
        frames += 1;
        if (frames >= maxFrames || (frames >= minFrames && stableFrames >= requiredStableFrames)) {
          resolve();
          return;
        }
        window.requestAnimationFrame(settle);
      };

      window.requestAnimationFrame(settle);
    });
  }

  const sessionItems = sessions?.sessions || [];
  const normalizedSessionQuery = sessionQuery.trim().toLowerCase();
  const visibleSessions = normalizedSessionQuery
    ? sessionItems.filter((session) => {
        const title = sessionTitle(session).toLowerCase();
        return title.includes(normalizedSessionQuery)
          || session.session_id.toLowerCase().includes(normalizedSessionQuery);
      })
    : sessionItems;
  const currentSession = sessionItems.find((session) => session.session_id === sessions?.current_session_id);
  const currentTitle = currentSession
    ? sessionTitle(currentSession)
    : firstUserMessageTitle(messages) || assistantProfile?.agent_name || '月見八千代';
  const headerActivity = latestVisibleActivity(messages);
  const chatWorkspaceStyle = embedded
    ? undefined
    : ({ '--chat-sidebar-width': `${sidebarWidth}px` } as CSSProperties);
  const composerInputStyle = { height: `${composerHeight}px` } as CSSProperties;
  const initialChatLoading = !embedded && !chatBootstrapped;
  const conversationLoading = !messagesLoaded;

  return (
    <section className={`${embedded ? '' : 'app-shell '}chat-shell refined-chat-shell open-chat-shell${embedded ? ' embedded-chat-shell' : ''}${initialChatLoading ? ' is-initializing-chat' : ''}`}>
      {notice ? (
        <div className={`chat-toast ${notice.kind}`} role="status">
          <strong>{notice.title}</strong>
          <span>{notice.detail}</span>
          <button type="button" aria-label="关闭提示" onClick={() => setNotice(null)}>×</button>
        </div>
      ) : null}

      <div
        className={`chat-layout hy-chat-workspace${embedded ? '' : ' resizable-chat-workspace'}`}
        style={chatWorkspaceStyle}
      >
        <aside className="chat-sidebar hy-chat-sessions" aria-label="会话列表">
          <div className="chat-sidebar-header hy-chat-sessions-head">
            <div className="chat-sidebar-title">会话列表</div>
            <input
              type="search"
              className="chat-search"
              value={sessionQuery}
              onChange={(event) => setSessionQuery(event.target.value)}
              placeholder="搜索会话..."
              aria-label="搜索会话"
            />
          </div>
          <div className="chat-list hy-chat-session-list">
            {visibleSessions.length ? visibleSessions.map((session) => (
              <button
                type="button"
                className={`chat-item ${session.session_id === sessions?.current_session_id ? 'active' : ''}`}
                key={session.session_id}
                onClick={() => void switchSession(session.session_id)}
              >
                <span className="chat-item-avatar">{avatarNode(assistantProfile?.agent_avatar_url, assistantProfile?.agent_name || 'Yachiyo', '月', assistantProfileLoading)}</span>
                <span className="chat-item-info">
                  <strong className="chat-item-name">{sessionTitle(session)}</strong>
                  <span className="chat-item-preview">{sessionPreview(session)}</span>
                </span>
                <span className="chat-item-time">
                  {session.is_processing ? '处理中' : formatShortTime(session.updated_at || session.created_at)}
                </span>
              </button>
            )) : (
              <div className="empty-state inline-empty">
                {sessionItems.length ? '无匹配会话' : '暂无对话'}
              </div>
            )}
          </div>
        </aside>

        {embedded ? null : (
          <div
            className="chat-sidebar-resizer"
            role="separator"
            aria-label="调整会话列表宽度"
            aria-orientation="vertical"
            aria-valuemin={CHAT_SIDEBAR_MIN_WIDTH}
            aria-valuemax={sidebarMaxWidth}
            aria-valuenow={sidebarWidth}
            tabIndex={0}
            title="拖动调整会话列表宽度"
            onKeyDown={handleSidebarResizerKeyDown}
            onPointerDown={startSidebarResize}
          />
        )}

        <section className="chat-main hy-chat-mainpane">
          <header className="chat-header">
            <div className="chat-header-info">
              <div className="chat-header-avatar">{avatarNode(assistantProfile?.agent_avatar_url, assistantProfile?.agent_name || 'Yachiyo', '月', assistantProfileLoading)}</div>
              <div>
                <div className="chat-header-name">{currentTitle}</div>
                <div className="chat-header-status">
                  <div className={`status-dot ${isProcessing ? 'processing' : 'completed'}`} />
                  <span>{isProcessing ? (headerActivity ? `处理中 · ${compactStatusText(activityLabel(headerActivity))}` : '处理中') : `${status} · ${executorLabel(executor)}`}</span>
                </div>
              </div>
            </div>
            <div className="chat-header-actions">
              {embedded ? null : (
                <button type="button" className="chat-action-btn" title="主控台" aria-label="打开主控台" onClick={() => void openAppView('main')}>
                  <UiIcon name="home" />
                </button>
              )}
              <button
                type="button"
                className="chat-action-btn"
                title={imageInputHelpText(executor)}
                aria-label="附加图片"
                disabled={isSending || !canAttachImages(executor) || attachments.length >= MAX_ATTACHMENTS}
                onClick={() => fileInputRef.current?.click()}
              >
                <UiIcon name="image" />
              </button>
              <button type="button" className="chat-action-btn" title="停止生成" aria-label="停止生成" onClick={() => void cancelProcessing()} disabled={!isProcessing}>
                <UiIcon name="stop" />
              </button>
              <button type="button" className="chat-action-btn" title="新对话" aria-label="新对话" onClick={() => void clearSession()}>
                <UiIcon name="plus" />
              </button>
              <button type="button" className="chat-action-btn danger-action" title="删除对话" aria-label="删除对话" onClick={() => void deleteSession()} disabled={!sessions?.sessions?.length}>
                <UiIcon name="close" />
              </button>
            </div>
          </header>

          <section
            className={`chat-messages refined-chat-list${conversationLoading ? ' is-loading-conversation' : ''}`}
            ref={listRef}
            onClick={handleMessageListClick}
            onPointerDown={handleMessagePointerDown}
            onScroll={handleScroll}
          >
            {!messagesLoaded ? (
              <div className="chat-loading-state">
                <div className="chat-loading-dots">
                  <span /><span /><span />
                </div>
                <div className="chat-loading-text">正在加载对话…</div>
              </div>
            ) : messages.length === 0 ? (
              <div className="empty-state">发送消息开始对话</div>
            ) : null}
            <div className={`chat-messages-content${messagesVisible ? '' : ' is-hidden'}`}>
              {messages.map((message, index) => (
                <MessageBubble
                  assistantProfile={assistantProfile}
                  assistantProfileLoading={assistantProfileLoading}
                  copied={copiedMessageId === message.id}
                  displayContent={displayMessageText(message, renderStateRef.current)}
                  key={message.id || index}
                  message={message}
                  onCopy={() => void copyMessage(message)}
                />
              ))}
              <div className="chat-bottom-anchor" ref={bottomAnchorRef} aria-hidden="true" />
            </div>
          </section>

          <form className="chat-input-area composer refined-composer" onSubmit={submit}>
            <div className="chat-input-wrapper">
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
                  className="chat-input"
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
                  placeholder="输入消息..."
                  disabled={isSending}
                  rows={1}
                  style={composerInputStyle}
                />
              </div>
              <div
                className="composer-resize-handle"
                role="separator"
                aria-label="调整输入框高度"
                aria-orientation="horizontal"
                aria-valuemin={COMPOSER_MIN_HEIGHT}
                aria-valuemax={COMPOSER_MAX_HEIGHT}
                aria-valuenow={composerHeight}
                tabIndex={0}
                title="拖动或用方向键调整输入框高度"
                onKeyDown={handleComposerResizeKeyDown}
                onPointerDown={startComposerResize}
              />
              <button
                type="button"
                className="chat-attach-btn"
                disabled={isSending || !canAttachImages(executor) || attachments.length >= MAX_ATTACHMENTS}
                title={imageInputHelpText(executor)}
                aria-label="附加图片"
                onClick={() => fileInputRef.current?.click()}
              >
                <UiIcon name="image" />
              </button>
              <button
                type={isProcessing ? 'button' : 'submit'}
                className={`chat-send-btn neon-glow${isProcessing ? ' is-stop' : ''}`}
                disabled={isProcessing ? false : isSending || (!input.trim() && attachments.length === 0)}
                aria-label={isProcessing ? '停止生成' : '发送消息'}
                title={isProcessing ? '停止生成' : '发送消息'}
                onClick={isProcessing ? () => void cancelProcessing() : undefined}
              >
                <UiIcon name={isProcessing ? 'stop' : 'send'} />
              </button>
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
          </form>
          <footer className="status-line refined-status-line">{status}</footer>
        </section>
      </div>

      <div
        className={`chat-readiness-overlay${initialChatLoading ? ' is-visible' : ''}`}
        aria-hidden={!initialChatLoading}
      >
        <ChatFullPageLoading
          avatarUrl={assistantProfile?.agent_avatar_url}
          label={assistantProfile?.agent_name || '月見八千代'}
        />
      </div>
    </section>
  );
}

function MessageBubble({ assistantProfile, assistantProfileLoading, copied, displayContent, message, onCopy }: {
  assistantProfile: AssistantProfilePayload | null;
  assistantProfileLoading: boolean;
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
    <article className={`message message--${messageVisualRole(role)} refined-message ${role} ${statusClass}`}>
      <div className="message-avatar">{messageAvatar(role, assistantProfile, assistantProfileLoading)}</div>
      <div className="message-stack">
        <div className="message-bubble">
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
        </div>
        <MessageActivityList
          events={message.activity_events || []}
          messageStatus={message.status}
          progressLabel={message.progress_label}
        />
        <div className="message-time">
          <span>{messageMetaText(role, message.status, message.created_at)}</span>
          <button
            className={`message-copy-button ${copied ? 'copied' : ''}`}
            type="button"
            title={copied ? '已复制' : '复制内容'}
            aria-label={copied ? '已复制' : '复制内容'}
            onClick={onCopy}
          >
            <UiIcon name={copied ? 'check' : 'copy'} />
          </button>
        </div>
      </div>
    </article>
  );
}

function MessageActivityList({ events, messageStatus, progressLabel }: {
  events: ChatActivityEvent[];
  messageStatus?: string;
  progressLabel?: string;
}) {
  const rows = events.slice(0, 4);
  const fallback = progressLabel && !rows.length
    ? [{ title: progressLabel, status: messageStatus || 'running' } as ChatActivityEvent]
    : [];
  const visibleRows = rows.length ? rows : fallback;
  if (!visibleRows.length) return null;
  return (
    <div className="message-activity-list" aria-label="执行活动">
      {visibleRows.map((event, index) => {
        const displayStatus = activityDisplayStatus(event.status, messageStatus);
        return (
          <div className={`message-activity-row ${activityStatusClass(displayStatus)}`} key={event.event_id || `${event.title}-${index}`}>
            <span className="message-activity-icon" aria-hidden="true">{activityStatusIcon(displayStatus)}</span>
            <span className="message-activity-text">
              <strong>{event.title || event.tool_name || 'Hermes 活动'}</strong>
              {event.detail ? <small>{event.detail}</small> : null}
            </span>
            <time>{formatShortTime(event.created_at)}</time>
          </div>
        );
      })}
    </div>
  );
}

function TypingIndicator() {
  return (
    <span className="typing-indicator loading-dots" aria-label="处理中">
      <span className="loading-dot" /><span className="loading-dot" /><span className="loading-dot" />
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

function chatStatusLabel(processing: boolean, failed: ChatMessage | null, messages: ChatMessage[]) {
  if (processing) {
    const latest = latestVisibleActivity(messages);
    return compactStatusText(activityLabel(latest) || '处理中...');
  }
  if (failed) return `处理失败：${compactStatusText(messageErrorText(failed))}`;
  return '就绪';
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

function messageVisualRole(role: string) {
  if (role === 'user') return 'user';
  if (role === 'assistant') return 'agent';
  return 'system';
}

function avatarNode(url: string | undefined, label: string, fallback: string, loading = false): ReactNode {
  if (loading) return <span className="chat-avatar-loading" aria-hidden="true" />;
  return url ? <img src={url} alt={label} /> : fallback;
}

function ChatFullPageLoading({ avatarUrl, label }: { avatarUrl?: string; label: string }) {
  return (
    <div className="chat-full-page-loading" role="status" aria-live="polite">
      <div className="chat-full-page-avatar">
        <img src={avatarUrl || logoUrl} alt="" />
      </div>
      <div className="chat-loading-dots">
        <span /><span /><span />
      </div>
      <strong>{label}</strong>
      <span>正在准备对话...</span>
    </div>
  );
}

function messageAvatar(role: string, profile: AssistantProfilePayload | null, profileLoading = false) {
  if (role === 'user') return avatarNode(profile?.user_avatar_url, '你', '你', profileLoading);
  if (role === 'assistant') return avatarNode(profile?.agent_avatar_url, profile?.agent_name || 'Yachiyo', '月', profileLoading);
  return 'i';
}

function messageMetaText(role: string, status?: string, createdAt?: string) {
  const statusText = status === 'pending'
    ? ' · 等待中'
    : status === 'processing'
      ? ' · 输入中'
      : status === 'failed'
        ? ' · 失败'
        : '';
  const timeText = formatShortTime(createdAt);
  return `${roleLabel(role)}${timeText !== '—' ? ` · ${timeText}` : ''}${statusText}`;
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
    || '当前 Yachiyo vision 链路不可用。请在主控台切换支持图片的主模型，或单独设置图片识别模型后再发送。';
}

function imageInputHelpText(executor: ExecutorPayload | null) {
  const imageInput = executor?.image_input;
  if (!imageInput) return '附加图片';
  return imageInput.reason || imageInput.label || '附加图片';
}

function sessionTitle(session: SessionItem) {
  const title = (session.title || '').trim();
  if (title && !looksLikeSessionIdTitle(title, session.session_id)) return title;
  const preview = (session.latest_message_preview || '').trim();
  if (preview) return compactStatusText(preview, 36);
  return '新对话';
}

function sessionPreview(session: SessionItem) {
  const preview = compactStatusText(session.latest_message_preview || sessionTitle(session), 48);
  if (session.is_processing) return `处理中：${preview || '正在处理'}`;
  if (session.latest_message_status === 'failed') return `处理失败：${preview || '任务执行失败'}`;
  if (session.message_count) return `已完成：${preview || sessionTitle(session)}`;
  if (!session.message_count) return '新的月夜会话';
  return preview;
}

function firstUserMessageTitle(messages: ChatMessage[]) {
  const firstUser = messages.find((message) => message.role === 'user' && messageText(message).trim());
  return firstUser ? compactStatusText(messageText(firstUser), 36) : '';
}

function looksLikeSessionIdTitle(title: string, sessionId: string) {
  const value = title.trim();
  return value === sessionId.slice(0, 8) || /^[a-f0-9]{8,32}$/i.test(value);
}

function latestVisibleActivity(messages: ChatMessage[]) {
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const events = messages[index]?.activity_events || [];
    if (events.length) return events[0];
    if (messages[index]?.progress_label) {
      return {
        title: messages[index]?.progress_label,
        status: messages[index]?.status,
        created_at: messages[index]?.created_at,
      } as ChatActivityEvent;
    }
  }
  return null;
}

function activityLabel(event?: ChatActivityEvent | null) {
  if (!event) return '';
  return String(event.title || event.detail || event.tool_name || '').trim();
}

function activityStatusClass(status?: string) {
  if (status === 'completed' || status === 'success') return 'completed';
  if (status === 'failed' || status === 'error') return 'failed';
  if (status === 'progress' || status === 'running') return 'running';
  return 'status';
}

function activityStatusIcon(status?: string) {
  if (status === 'completed' || status === 'success') return '✓';
  if (status === 'failed' || status === 'error') return '!';
  return '';
}

function activityDisplayStatus(eventStatus?: string, messageStatus?: string) {
  if (
    (messageStatus === 'completed' || messageStatus === 'failed')
    && (!eventStatus || eventStatus === 'running' || eventStatus === 'progress' || eventStatus === 'status')
  ) {
    return messageStatus;
  }
  return eventStatus;
}

function formatShortTime(value?: string) {
  if (!value) return '—';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(undefined, {
    hour: '2-digit',
    minute: '2-digit',
  });
}

function clampComposerHeight(value: number) {
  return Math.max(COMPOSER_MIN_HEIGHT, Math.min(COMPOSER_MAX_HEIGHT, Math.round(value)));
}

function storedComposerHeight() {
  if (typeof window === 'undefined') return COMPOSER_MIN_HEIGHT;
  const stored = Number(window.localStorage.getItem(COMPOSER_HEIGHT_STORAGE_KEY));
  if (!Number.isFinite(stored)) return COMPOSER_MIN_HEIGHT;
  return clampComposerHeight(stored);
}

function isMessageTextSelectionActive(root: HTMLElement | null) {
  if (typeof window === 'undefined') return false;
  const selection = window.getSelection();
  if (!selection || selection.isCollapsed) return false;
  return selectionNodeInMessageContent(selection.anchorNode, root)
    || selectionNodeInMessageContent(selection.focusNode, root);
}

function selectionNodeInMessageContent(node: Node | null, root: HTMLElement | null) {
  if (!node || !root) return false;
  const element = node instanceof Element ? node : node.parentElement;
  return Boolean(element && root.contains(element) && element.closest('.message-content'));
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

function responsiveChatSidebarMaxWidth() {
  if (typeof window === 'undefined') return CHAT_SIDEBAR_BASE_MAX_WIDTH;
  return window.innerWidth >= CHAT_WIDE_VIEWPORT_WIDTH
    ? CHAT_SIDEBAR_WIDE_MAX_WIDTH
    : CHAT_SIDEBAR_BASE_MAX_WIDTH;
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
    reader.onload = async () => {
      const dataUrl = typeof reader.result === 'string' ? reader.result : '';
      if (!dataUrl.startsWith('data:image/')) {
        reject(new Error('只支持图片附件'));
        return;
      }
      let dimensions: { width: number; height: number };
      try {
        dimensions = await loadImageDimensions(dataUrl);
      } catch {
        reject(new Error(`无法读取图片尺寸：${file.name || '未命名'}`));
        return;
      }
      if (dimensions.width < 16 || dimensions.height < 16) {
        reject(new Error('图片尺寸过小，容易被上游视觉模型判定为不可处理；请换用正常尺寸的截图或图片。'));
        return;
      }
      resolve({
        id: `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 8)}`,
        name: file.name || 'pasted-image.png',
        mime_type: file.type || 'image/png',
        size: file.size,
        width: dimensions.width,
        height: dimensions.height,
        data_url: dataUrl,
      });
    };
    reader.readAsDataURL(file);
  });
}

function loadImageDimensions(dataUrl: string): Promise<{ width: number; height: number }> {
  return new Promise((resolve, reject) => {
    const image = new Image();
    image.onload = () => resolve({ width: image.naturalWidth || image.width, height: image.naturalHeight || image.height });
    image.onerror = () => reject(new Error('image load failed'));
    image.src = dataUrl;
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
