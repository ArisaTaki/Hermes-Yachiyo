import { FormEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ClipboardEvent as ReactClipboardEvent,
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  ReactNode,
} from 'react';

import { ImageAttachmentViewer } from '../components/ImageAttachmentViewer';
import { useConfirmDialog } from '../components/ConfirmDialog';
import { UiIcon } from '../components/UiIcon';
import logoUrl from '../../../../docs/open-design/logo.png';
import { type AssistantProfileSeed, useAssistantProfileSeed } from '../lib/assistantProfileSeed';
import { approveRunApproval, listRunnables, type RunnableSummary, type RunSpec, getRun, rejectRunApproval } from '../lib/agents';
import { apiGet, apiPatch, apiPost, bridgeUrl, chooseAvatarImage, copyText, openExternalUrl, restartDesktopBridge } from '../lib/bridge';
import { currentParam, navigateTo } from '../lib/view';

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
  metadata?: {
    run_id?: string;
    workflow_run_id?: string;
    run_status?: string;
    pending_approval?: Record<string, unknown>;
  } & Record<string, unknown>;
};

type ChatParticipant = {
  kind?: 'main' | 'agent' | 'workflow' | 'group' | string;
  id?: string;
  name?: string;
  nickname?: string;
  description?: string;
  avatar_url?: string;
  category?: string;
  participants?: ChatParticipant[];
};

type ChatMessageMetadata = {
  sender?: ChatParticipant;
  target?: ChatParticipant;
  runnable_kind?: string;
  runnable_id?: string;
  run_id?: string;
  run_group_id?: string;
  run_status?: string;
  group_goal?: string;
  delegated_goal?: string;
  pending_approval?: {
    approval_id?: string;
    tool?: string;
    input_preview?: unknown;
    requested_at?: string;
  };
  run_progress_title?: string;
  run_progress_detail?: string;
  run_artifact_count?: number;
  run_artifacts?: Array<{ path?: string; kind?: string }>;
  workflow_run_id?: string;
  workflow_status?: string;
  workflow_node?: string;
  workflow_waiting_child_run_id?: string;
  workflow_waiting_node?: string;
  workflow_waiting_tool?: string;
  group_dispatch_count?: number;
  group_dispatch_run_group_id?: string;
  group_dispatch_skipped?: string[];
  group_agent_summary_pending?: boolean;
  group_agent_summary_status?: string;
  group_agent_summary_error?: string;
  group_followup_for_task_ids?: string[];
  group_followup_for_agent_message_ids?: string[];
  guidance_type?: string;
};

type MentionOption = {
  id: string;
  name: string;
  nickname?: string;
  avatar_url?: string;
  kind: 'main' | 'agent' | 'workflow';
  participants?: ChatParticipant[];
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
  metadata?: ChatMessageMetadata;
};

type MessagesPayload = {
  ok?: boolean;
  error?: string;
  is_processing?: boolean;
  processing_count?: number;
  messages?: ChatMessage[];
  anchor_message_id?: string;
  session_context?: ChatSessionContext;
};

type SessionSearchMatch = {
  kind?: string;
  query?: string;
  message_id?: string;
  role?: string;
  snippet?: string;
  created_at?: string;
  match_count?: number;
};

type SessionItem = {
  session_id: string;
  title?: string;
  conversation_kind?: 'main' | 'agent' | 'workflow' | 'group' | string;
  runnable_id?: string;
  runnable_name?: string;
  run_group_id?: string;
  avatar_url?: string;
  participants?: ChatParticipant[];
  created_at?: string;
  updated_at?: string;
  message_count?: number;
  is_processing?: boolean;
  processing_count?: number;
  approval_count?: number;
  latest_activity?: ChatActivityEvent | null;
  latest_message_preview?: string;
  latest_message_status?: string;
  search_match?: SessionSearchMatch | null;
};

type SessionsPayload = {
  ok?: boolean;
  current_session_id?: string;
  sessions?: SessionItem[];
};

type ChatSessionContext = {
  conversation_kind?: 'main' | 'agent' | 'workflow' | 'group' | 'unassigned' | string;
  runnable_id?: string;
  runnable_name?: string;
  run_group_id?: string;
  avatar_url?: string;
  participants?: ChatParticipant[];
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
let retainedComposerDraft = {
  input: '',
  attachments: [] as PendingAttachment[],
};

function retainComposerDraft(input: string, attachments: PendingAttachment[]) {
  retainedComposerDraft = {
    input,
    attachments: [...attachments],
  };
}

function clearRetainedComposerDraft() {
  retainComposerDraft('', []);
}

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
const CODE_COPY_FEEDBACK_MS = 2600;
const MAX_ATTACHMENTS = 4;
const MAX_ATTACHMENT_BYTES = 8 * 1024 * 1024;
const GROUP_AVATAR_MAX_BYTES = 1024 * 1024;
const GROUP_AVATAR_MAX_DATA_URL_CHARS = Math.ceil((GROUP_AVATAR_MAX_BYTES * 4) / 3) + 128;
const MIN_LOADING_MS = 1400;
const CHAT_SIDEBAR_MIN_WIDTH = 220;
const CHAT_SIDEBAR_BASE_MAX_WIDTH = 280;
const CHAT_SIDEBAR_WIDE_MAX_WIDTH = 360;
const CHAT_WIDE_VIEWPORT_WIDTH = 1500;
const COMPOSER_MIN_HEIGHT = 48;
const COMPOSER_MAX_HEIGHT = 260;
const COMPOSER_HEIGHT_STORAGE_KEY = 'hermes.chat.composerHeight';
const CODE_COPY_ICON_HTML = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"><rect x="8" y="8" width="11" height="11" rx="2"></rect><path d="M5 15H4a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h8a2 2 0 0 1 2 2v1"></path></svg>';
const CODE_CHECK_ICON_HTML = '<svg aria-hidden="true" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.9" stroke-linecap="round" stroke-linejoin="round"><path d="m5 12.5 4.2 4.2L19 7"></path></svg>';

export function ChatView({ embedded = false }: ChatViewProps = {}) {
  const assistantProfileSeed = useAssistantProfileSeed();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionContext, setSessionContext] = useState<ChatSessionContext | null>(null);
  const [input, setInput] = useState(() => retainedComposerDraft.input);
  const [attachments, setAttachments] = useState<PendingAttachment[]>(() => [...retainedComposerDraft.attachments]);
  const [status, setStatus] = useState('就绪');
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingCount, setProcessingCount] = useState(0);
  const [isSending, setIsSending] = useState(false);
  const [sessions, setSessions] = useState<SessionsPayload | null>(null);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [executor, setExecutor] = useState<ExecutorPayload | null>(null);
  const [assistantProfile, setAssistantProfile] = useState<AssistantProfilePayload | null>(() => cachedAssistantProfile || profileFromSeed(assistantProfileSeed));
  const [assistantProfileLoading, setAssistantProfileLoading] = useState(() => !(cachedAssistantProfile || profileFromSeed(assistantProfileSeed)));
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const [sessionQuery, setSessionQuery] = useState('');
  const [debouncedSessionQuery, setDebouncedSessionQuery] = useState('');
  const [copiedMessageId, setCopiedMessageId] = useState('');
  const [copiedCodeBlockKey, setCopiedCodeBlockKey] = useState('');
  const [copiedSessionId, setCopiedSessionId] = useState('');
  const [sessionIdDialogOpen, setSessionIdDialogOpen] = useState(false);
  const [sessionIdCopyError, setSessionIdCopyError] = useState('');
  const [retryingMessageId, setRetryingMessageId] = useState('');
  const [approvalActionMessageId, setApprovalActionMessageId] = useState('');
  const [composerApprovalMessageId, setComposerApprovalMessageId] = useState('');
  const [resolvedComposerApprovalIds, setResolvedComposerApprovalIds] = useState<string[]>([]);
  const [runApprovalDetailOverrides, setRunApprovalDetailOverrides] = useState<Record<string, RunApprovalDetailOverride>>({});
  const [highlightedMessageId, setHighlightedMessageId] = useState('');
  const [messagesLoaded, setMessagesLoaded] = useState(false);
  const [messagesVisible, setMessagesVisible] = useState(false);
  const [chatBootstrapped, setChatBootstrapped] = useState(false);
  const [sidebarMaxWidth, setSidebarMaxWidth] = useState(() => responsiveChatSidebarMaxWidth());
  const [sidebarWidth, setSidebarWidth] = useState(CHAT_SIDEBAR_BASE_MAX_WIDTH);
  const [composerHeight, setComposerHeight] = useState(() => storedComposerHeight());
  const [runnables, setRunnables] = useState<RunnableSummary[]>([]);
  const [sessionTab, setSessionTab] = useState<'agents' | 'groups'>('agents');
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const [groupDialogOpen, setGroupDialogOpen] = useState(false);
  const [groupDialogMode, setGroupDialogMode] = useState<'create' | 'edit'>('create');
  const [groupDialogError, setGroupDialogError] = useState('');
  const [groupName, setGroupName] = useState('');
  const [groupAvatarUrl, setGroupAvatarUrl] = useState('');
  const [selectedGroupAgentIds, setSelectedGroupAgentIds] = useState<string[]>([]);
  const [isCreatingGroup, setIsCreatingGroup] = useState(false);
  const [mentionActiveIndex, setMentionActiveIndex] = useState(0);
  const [dismissedMentionInput, setDismissedMentionInput] = useState('');
  const [, setRenderTick] = useState(0);
  const { confirmDialog, requestConfirm } = useConfirmDialog();
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
  const codeCopyTimerRef = useRef<number | null>(null);
  const messagesLoadedRef = useRef(false);
  const messageLoadTokenRef = useRef(0);
  const conversationLoadTokenRef = useRef(0);
  const conversationTransitionRef = useRef(false);
  const assistantProfileSeedRef = useRef(assistantProfileSeed);
  const messageTextSelectingRef = useRef(false);
  const messageNodeRefs = useRef<Map<string, HTMLElement>>(new Map());
  const isProcessingRef = useRef(false);
  const pendingReplyScrollRef = useRef(false);
  const pendingReplyTaskIdRef = useRef('');
  const highlightedScrollTargetRef = useRef('');
  const highlightClearTimerRef = useRef<number | null>(null);
  const approvalSessionIdRef = useRef('');
  const loadSessionsRef = useRef<() => Promise<void>>(async () => undefined);
  const transientEmptySessionIdRef = useRef('');
  const latestChatSnapshotRef = useRef({
    currentSessionId: '',
    messageCount: 0,
    isProcessing: false,
    isSending: false,
  });

  const refreshMessages = useCallback(async (options: { allowDuringTransition?: boolean; anchorMessageId?: string } = {}) => {
    if (conversationTransitionRef.current && !options.allowDuringTransition) return;
    const token = ++messageLoadTokenRef.current;
    const startedAt = Date.now();
    const shouldHoldLoading = !messagesLoadedRef.current;
    const anchorMessageId = (options.anchorMessageId || '').trim();
    try {
      const query = new URLSearchParams();
      query.set('limit', anchorMessageId ? '220' : '0');
      if (anchorMessageId) query.set('anchor_message_id', anchorMessageId);
      const payload = await apiGet<MessagesPayload>(`/ui/chat/messages?${query.toString()}`);
      if (payload.ok === false) throw new Error(payload.error || '读取消息失败');
      const baseUrl = await bridgeUrl();
      const nextMessages = withResolvedAttachmentUrls(payload.messages || [], baseUrl);
      setSessionContext(payload.session_context || null);
      const nextProcessingCount = Math.max(0, Number(payload.processing_count || 0));
      const processing = Boolean(payload.is_processing || nextProcessingCount > 0);
      const processingChanged = processing !== isProcessingRef.current;
      isProcessingRef.current = processing;
      const failed = latestFailedMessage(nextMessages);
      if (!shouldHoldLoading && isMessageSelectionPaused()) {
        setIsProcessing(processing);
        setProcessingCount(nextProcessingCount);
        setStatus(chatStatusLabel(processing, failed, nextMessages, nextProcessingCount));
        if (processingChanged) void loadSessionsRef.current();
        return { is_processing: processing, processing_count: nextProcessingCount, messages: nextMessages };
      }
      syncRenderStates(nextMessages, renderStateRef.current);
      const elapsed = Date.now() - startedAt;
      const remaining = Math.max(0, MIN_LOADING_MS - elapsed);
      if (shouldHoldLoading && remaining > 0) await new Promise((r) => setTimeout(r, remaining));
      if (token !== messageLoadTokenRef.current) return;
      if (anchorMessageId) {
        const anchorFound = nextMessages.some((message) => message.id === anchorMessageId);
        if (highlightClearTimerRef.current !== null) {
          window.clearTimeout(highlightClearTimerRef.current);
          highlightClearTimerRef.current = null;
        }
        highlightedScrollTargetRef.current = anchorFound ? anchorMessageId : '';
        setHighlightedMessageId(anchorFound ? anchorMessageId : '');
      }
      setMessages(nextMessages);
      setIsProcessing(processing);
      setProcessingCount(nextProcessingCount);
      if (shouldTriggerPendingReplyScroll(nextMessages)) {
        pendingReplyScrollRef.current = false;
        pendingReplyTaskIdRef.current = '';
        scrollToConversationBottom(true);
      }
      if (shouldHoldLoading) {
        await settleMessagesAtBottom(token);
      }
      if (token === messageLoadTokenRef.current) {
        messagesLoadedRef.current = true;
        setMessagesVisible(true);
        setMessagesLoaded(true);
      }
      if (processing) {
        setStatus(chatStatusLabel(processing, failed, nextMessages, nextProcessingCount));
      } else if (failed) {
        setStatus(`处理失败：${compactStatusText(messageErrorText(failed))}`);
      } else {
        setStatus('就绪');
      }
      if (processingChanged) void loadSessionsRef.current();
      return { is_processing: processing, processing_count: nextProcessingCount, messages: nextMessages };
    } catch (error) {
      const elapsed = Date.now() - startedAt;
      const remaining = Math.max(0, MIN_LOADING_MS - elapsed);
      if (shouldHoldLoading && remaining > 0) await new Promise((r) => setTimeout(r, remaining));
      if (token !== messageLoadTokenRef.current) return;
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
      setStatus(error instanceof Error ? error.message : '读取消息失败');
      return { is_processing: false, messages: [] };
    }
  }, []);

  const loadSessions = useCallback(async () => {
    try {
      const query = new URLSearchParams();
      query.set('limit', debouncedSessionQuery ? '80' : '20');
      if (debouncedSessionQuery) query.set('query', debouncedSessionQuery);
      const payload = await apiGet<SessionsPayload>(`/ui/chat/sessions?${query.toString()}`);
      if (payload.ok === false) throw new Error('读取会话失败');
      setSessions(payload);
    } catch {
      setSessions(null);
    } finally {
      setSessionsLoaded(true);
    }
  }, [debouncedSessionQuery]);

  useEffect(() => {
    loadSessionsRef.current = loadSessions;
  }, [loadSessions]);

  useEffect(() => {
    const currentSessionId = sessions?.current_session_id || latestChatSnapshotRef.current.currentSessionId;
    latestChatSnapshotRef.current = {
      currentSessionId,
      messageCount: messages.length,
      isProcessing,
      isSending,
    };
    if (currentSessionId === transientEmptySessionIdRef.current && messages.length > 0) {
      transientEmptySessionIdRef.current = '';
    }
  }, [isProcessing, isSending, messages.length, sessions?.current_session_id]);

  useEffect(() => {
    void loadSessions();
  }, [loadSessions]);

  useEffect(() => {
    if (embedded) return;
    let disposed = false;
    async function refreshRunnables() {
      try {
        const payload = await listRunnables();
        if (disposed) return;
        setRunnables(payload.filter((item) => item.enabled !== false));
      } catch {
        if (!disposed) setRunnables([]);
      }
    }
    void refreshRunnables();
    const timer = window.setInterval(refreshRunnables, 10_000);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [embedded]);

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
    const timer = window.setTimeout(() => {
      setDebouncedSessionQuery(sessionQuery.trim());
    }, 180);
    return () => window.clearTimeout(timer);
  }, [sessionQuery]);

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
    if (highlightedMessageId) return;
    scrollToConversationBottom();
  }, [messages, isProcessing, highlightedMessageId]);

  useEffect(() => {
    if (!highlightedMessageId || !messagesVisible) return undefined;
    const messageExists = messages.some((message) => message.id === highlightedMessageId);
    if (!messageExists) return undefined;
    if (highlightedScrollTargetRef.current !== highlightedMessageId) return undefined;
    const scrollTimer = window.setTimeout(() => {
      const node = messageNodeRefs.current.get(highlightedMessageId);
      if (!node) return;
      stickToBottomRef.current = false;
      highlightedScrollTargetRef.current = '';
      node.scrollIntoView({ behavior: 'smooth', block: 'center' });
      if (highlightClearTimerRef.current !== null) window.clearTimeout(highlightClearTimerRef.current);
      highlightClearTimerRef.current = window.setTimeout(() => {
        setHighlightedMessageId((current) => (current === highlightedMessageId ? '' : current));
        highlightClearTimerRef.current = null;
      }, 1800);
    }, 80);
    return () => {
      window.clearTimeout(scrollTimer);
    };
  }, [highlightedMessageId, messages, messagesVisible]);

  useEffect(() => {
    window.localStorage.setItem(COMPOSER_HEIGHT_STORAGE_KEY, String(composerHeight));
  }, [composerHeight]);

  useEffect(() => {
    retainComposerDraft(input, attachments);
  }, [attachments, input]);

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
      if (codeCopyTimerRef.current !== null) window.clearTimeout(codeCopyTimerRef.current);
      if (highlightClearTimerRef.current !== null) window.clearTimeout(highlightClearTimerRef.current);
      const snapshot = latestChatSnapshotRef.current;
      const transientSessionId = transientEmptySessionIdRef.current;
      if (
        !embedded
        && transientSessionId
        && snapshot.currentSessionId === transientSessionId
        && snapshot.messageCount === 0
        && !snapshot.isProcessing
        && !snapshot.isSending
      ) {
        transientEmptySessionIdRef.current = '';
        clearRetainedComposerDraft();
        void apiPost('/ui/chat/session/discard-empty').catch(() => undefined);
      }
    };
  }, [embedded]);

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
    if ((!text && attachments.length === 0) || isSending) return;
    if (attachments.length > 0 && !canAttachImages(executor)) {
      showImageInputBlocked();
      return;
    }
    const outgoingAttachments = attachments;
    clearRetainedComposerDraft();
    setInput('');
    setAttachments([]);
    setIsSending(true);
    isProcessingRef.current = true;
    pendingReplyScrollRef.current = true;
    pendingReplyTaskIdRef.current = '';
    setIsProcessing(true);
    setProcessingCount((current) => Math.max(1, current + 1));
    setStatus(outgoingAttachments.length ? '发送图片中...' : '发送中...');
    stickToBottomRef.current = true;
    focusComposerSoon();
    try {
      const result = await apiPost<{
        ok?: boolean;
        error?: string;
        task_id?: string;
        runnable_command?: boolean;
        agent_run_id?: string;
        workflow_run_id?: string;
        run_id?: string;
        run_status?: string;
        status?: string;
      }>('/ui/chat/messages', {
        text,
        attachments: outgoingAttachments,
      });
      if (result.ok === false) throw new Error(result.error || '发送失败');
      transientEmptySessionIdRef.current = '';
      if (result.runnable_command) {
        pendingReplyTaskIdRef.current = '';
        const resultRunId = runnableResultRunId(result);
        const resultRunStatus = runnableResultStatus(result);
        const runnableLabel = result.workflow_run_id ? 'Workflow' : 'Agent';
        if (resultRunStatus === 'processing' && resultRunId) {
          setStatus(`${runnableLabel} 执行中...`);
          stickToBottomRef.current = true;
          await refreshMessages();
          pollAgentRunInBackground(resultRunId);
          return;
        }
        pendingReplyScrollRef.current = false;
        setStatus(resultRunStatus === 'approval_required'
          ? `${runnableLabel} 等待审批...`
          : resultRunId
            ? `${runnableLabel} Run 已处理。`
            : result.error || 'Agent/Workflow 指令已处理。');
        await refreshMessages();
        await loadSessions();
        return;
      }
      const taskId = String(result.task_id || '');
      pendingReplyTaskIdRef.current = taskId;
      if (!taskId) pendingReplyScrollRef.current = false;
      setStatus('等待回复...');
      void loadSessions();
      await refreshMessages();
      await loadSessions();
    } catch (error) {
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      retainComposerDraft(text, outgoingAttachments);
      setInput(text);
      setAttachments(outgoingAttachments);
      setStatus(error instanceof Error ? error.message : '发送失败');
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
    } finally {
      setIsSending(false);
      focusComposerSoon();
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
    if (mentionSuggestions.length && !isImeComposing(event, composerComposingRef.current)) {
      if (event.key === 'ArrowDown') {
        event.preventDefault();
        setMentionActiveIndex((current) => (current + 1) % mentionSuggestions.length);
        return;
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault();
        setMentionActiveIndex((current) => (current - 1 + mentionSuggestions.length) % mentionSuggestions.length);
        return;
      }
      if (event.key === 'Enter' || event.key === 'Tab') {
        event.preventDefault();
        insertMention(mentionSuggestions[mentionActiveIndex] || mentionSuggestions[0]);
        return;
      }
      if (event.key === 'Escape') {
        event.preventDefault();
        setDismissedMentionInput(input);
        return;
      }
    }
    if (event.key !== 'Enter' || event.shiftKey || event.metaKey || event.ctrlKey || event.altKey) return;
    if (isImeComposing(event, composerComposingRef.current)) return;
    event.preventDefault();
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
      setStatus(next.length > 1 ? `已添加 ${next.length} 张图片附件` : '已添加图片附件');
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '读取图片失败');
    }
  }

  function removeAttachment(id: string) {
    setAttachments((current) => current.filter((attachment) => attachment.id !== id));
  }

  function insertMention(option: MentionOption) {
    setInput((current) => replaceTrailingMentionQuery(current, mentionTextForOption(option)));
    setDismissedMentionInput('');
    setMentionActiveIndex(0);
    window.requestAnimationFrame(() => {
      inputRef.current?.focus({ preventScroll: true });
    });
  }

  function toggleGroupAgent(agentId: string) {
    setGroupDialogError('');
    setSelectedGroupAgentIds((current) => (
      current.includes(agentId)
        ? current.filter((item) => item !== agentId)
        : [...current, agentId]
    ));
  }

  function openGroupDialog() {
    setGroupDialogMode('create');
    setGroupDialogOpen(true);
    setGroupDialogError('');
    setGroupName('');
    setGroupAvatarUrl('');
    setSelectedGroupAgentIds([]);
  }

  function openGroupSettings() {
    if (!currentSessionId || activeSessionContext.conversation_kind !== 'group') return;
    const currentAgentIds = (activeSessionContext.participants || [])
      .filter((participant) => participant.kind === 'agent' && participant.id)
      .map((participant) => String(participant.id));
    setGroupDialogMode('edit');
    setGroupDialogOpen(true);
    setGroupDialogError('');
    setGroupName(activeSessionContext.runnable_name || currentTitle || '');
    setGroupAvatarUrl(activeSessionContext.avatar_url || '');
    setSelectedGroupAgentIds(currentAgentIds);
  }

  function closeGroupDialog() {
    setGroupDialogOpen(false);
    setGroupDialogError('');
  }

  async function updateCurrentGroupSession() {
    if (!currentSessionId) throw new Error('当前群组不可用');
    const result = await apiPatch<{
      ok?: boolean;
      error?: string;
      session_id?: string;
      session_context?: ChatSessionContext;
    }>(`/ui/chat/groups/${encodeURIComponent(currentSessionId)}`, {
      name: groupName.trim() || defaultGroupName,
      avatar_url: groupAvatarUrl.trim(),
      participant_ids: selectedGroupAgentIds,
    });
    if (result.ok === false) throw new Error(result.error || '保存群组失败');
    return result;
  }

  async function updateCurrentGroupSessionWithRecovery() {
    try {
      return await updateCurrentGroupSession();
    } catch (error) {
      if (!isMissingGroupEditRouteError(error)) throw error;
      setStatus('Bridge 正在重启以加载群组编辑接口...');
      const restartResult = await restartDesktopBridge();
      if (!restartResult.success) {
        throw new Error('当前 Bridge 尚未加载群组编辑接口，请重启 Hermes-Yachiyo 后重试');
      }
      return await updateCurrentGroupSession();
    }
  }

  function handleSessionTabCreate() {
    if (sessionTab === 'groups') {
      openGroupDialog();
      return;
    }
    void clearSession();
  }

  async function submitGroupDialog(event: FormEvent) {
    event.preventDefault();
    if (isCreatingGroup || selectedGroupAgentIds.length === 0) return;
    setIsCreatingGroup(true);
    setGroupDialogError('');
    try {
      if (groupDialogMode === 'edit') {
        const result = await updateCurrentGroupSessionWithRecovery();
        setSessionContext(result.session_context || activeSessionContext);
        setGroupDialogOpen(false);
        setStatus('群组资料已更新');
        await loadSessions();
        await refreshMessages({ allowDuringTransition: true });
        return;
      }
      const result = await apiPost<{
        ok?: boolean;
        error?: string;
        session_id?: string;
        session_context?: ChatSessionContext;
      }>('/ui/chat/groups', {
        name: groupName.trim() || defaultGroupName,
        avatar_url: groupAvatarUrl.trim(),
        participant_ids: selectedGroupAgentIds,
      });
      if (result.ok === false) throw new Error(result.error || '创建群组失败');
      const nextSessionId = String(result.session_id || '');
      transientEmptySessionIdRef.current = '';
      latestChatSnapshotRef.current = {
        ...latestChatSnapshotRef.current,
        currentSessionId: nextSessionId,
        messageCount: 0,
      };
      renderStateRef.current.clear();
      setMessages([]);
      setSessionContext(result.session_context || null);
      setSessionTab('groups');
      setGroupDialogOpen(false);
      setGroupName('');
      setGroupAvatarUrl('');
      setSelectedGroupAgentIds([]);
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
      setStatus('群组已创建');
      await loadSessions();
      await refreshMessages({ allowDuringTransition: true });
    } catch (error) {
      const message = error instanceof Error ? error.message : (groupDialogMode === 'edit' ? '保存群组失败' : '创建群组失败');
      setGroupDialogError(message);
      setStatus(message);
    } finally {
      setIsCreatingGroup(false);
    }
  }

  async function clearSession() {
    try {
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      const result = await apiPost<{ ok?: boolean; error?: string; session_id?: string }>('/ui/chat/session/clear');
      if (result.ok === false) throw new Error(result.error || '新建对话失败');
      const nextSessionId = String(result.session_id || '');
      transientEmptySessionIdRef.current = nextSessionId;
      latestChatSnapshotRef.current = {
        ...latestChatSnapshotRef.current,
        currentSessionId: nextSessionId,
        messageCount: 0,
      };
      renderStateRef.current.clear();
      setMessages([]);
      setSessionContext(null);
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
      setStatus('新对话已创建');
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '新建对话失败');
    }
  }

  async function cancelProcessing() {
    if (!isProcessing) return;
    try {
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      const result = await apiPost<MessagesPayload & { cancelled_tasks?: number }>('/ui/chat/session/cancel');
      if (result.ok === false) throw new Error(result.error || '取消失败');
      setMessages(result.messages || []);
      const nextProcessingCount = Math.max(0, Number(result.processing_count || 0));
      const nextProcessing = Boolean(result.is_processing || nextProcessingCount > 0);
      isProcessingRef.current = nextProcessing;
      setIsProcessing(nextProcessing);
      setProcessingCount(nextProcessingCount);
      setStatus(result.cancelled_tasks ? `已取消 ${result.cancelled_tasks} 个任务` : '没有可取消任务');
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '取消失败');
    }
  }

  async function pollAgentRunCompletion(runId: string) {
    const maxAttempts = 600; // 最多轮询 600 次（约 5 分钟）
    const interval = ACTIVE_POLL_INTERVAL_MS;
    for (let attempt = 0; attempt < maxAttempts; attempt++) {
      try {
        const run = await getRun(runId);
        const status = normalizeRunStatus(run.status);
        const runLabel = run.kind === 'workflow_run' ? 'Workflow Run' : 'Agent Run';
        if (status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'approval_required') {
          // 执行完成，刷新消息
          const refreshed = await refreshMessages();
          await loadSessions();
          const chatStillProcessing = Boolean(refreshed?.is_processing);
          const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
          if (status === 'approval_required') {
            rememberRunApprovalDetails(run);
            isProcessingRef.current = true;
            setIsProcessing(true);
            setProcessingCount(Math.max(1, chatProcessingCount));
            setStatus(nextApprovalStatusText(run));
          } else {
            forgetRunApprovalDetails(runId);
            isProcessingRef.current = chatStillProcessing;
            setIsProcessing(chatStillProcessing);
            setProcessingCount(chatProcessingCount);
            if (chatStillProcessing) {
              setStatus(
                status === 'completed'
                  ? `${runLabel} 已完成，等待主模型汇总...`
                  : status === 'cancelled'
                    ? `${runLabel} 已取消，等待主模型整理结果...`
                    : `${runLabel} 执行失败，等待主模型整理结果...`,
              );
            } else {
              setStatus(
                status === 'completed'
                  ? `${runLabel} 已完成。`
                  : status === 'cancelled'
                    ? `${runLabel} 已取消。`
                    : `${runLabel} 执行失败。`,
              );
            }
          }
          return;
        }
        // 更新状态文本
        if (attempt % 10 === 0) {
          setStatus(`Agent 执行中... (${Math.floor(attempt * interval / 1000)}s)`);
        }
      } catch (error) {
        console.error('轮询 Agent Run 状态失败:', error);
      }
      await new Promise((resolve) => setTimeout(resolve, interval));
    }
    // 超时
    const refreshed = await refreshMessages();
    await loadSessions();
    const chatStillProcessing = Boolean(refreshed?.is_processing);
    const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
    isProcessingRef.current = chatStillProcessing;
    setIsProcessing(chatStillProcessing);
    setProcessingCount(chatProcessingCount);
    setStatus(chatStillProcessing ? 'Agent Run 轮询超时，仍在等待后续处理...' : 'Agent Run 轮询超时');
  }

  function pollAgentRunInBackground(runId: string) {
    void pollAgentRunCompletion(runId).catch((error) => {
      console.error('后台轮询 Agent Run 状态失败:', error);
      setStatus(error instanceof Error ? error.message : 'Agent Run 状态刷新失败');
    });
  }

  async function deleteSession(targetLabel = '对话') {
    const conversationToken = beginConversationLoading();
    try {
      await apiPost('/ui/chat/session/delete');
      if (conversationToken !== conversationLoadTokenRef.current) return;
      renderStateRef.current.clear();
      stickToBottomRef.current = true;
      await loadSessions();
      await refreshMessages({ allowDuringTransition: true });
      if (conversationToken === conversationLoadTokenRef.current) conversationTransitionRef.current = false;
      setStatus(`已删除此${targetLabel}`);
    } catch (error) {
      if (conversationToken !== conversationLoadTokenRef.current) return;
      conversationTransitionRef.current = false;
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
      setStatus(error instanceof Error ? error.message : '删除失败');
    }
  }

  function requestDeleteSession() {
    const targetLabel = deleteTargetLabel(activeSessionContext);
    requestConfirm({
      title: `删除此${targetLabel}？`,
      description: `当前${targetLabel}记录会从本机删除，此操作不可恢复。`,
      confirmLabel: `删除${targetLabel}`,
      variant: 'danger',
      onConfirm: () => void deleteSession(targetLabel),
    });
  }

  async function switchSession(sessionId: string, anchorMessageId = '') {
    if (!sessionId) return;
    if (sessionId === sessions?.current_session_id) {
      if (anchorMessageId) {
        await refreshMessages({ allowDuringTransition: true, anchorMessageId });
        setStatus('已定位到匹配消息');
      }
      return;
    }
    const conversationToken = beginConversationLoading();
    setStatus('正在切换会话...');
    try {
      await apiPost('/ui/chat/sessions/load', { session_id: sessionId });
      if (conversationToken !== conversationLoadTokenRef.current) return;
      renderStateRef.current.clear();
      stickToBottomRef.current = true;
      await loadSessions();
      await refreshMessages({ allowDuringTransition: true, anchorMessageId });
      if (conversationToken === conversationLoadTokenRef.current) conversationTransitionRef.current = false;
      setStatus(anchorMessageId ? '已定位到匹配消息' : '已切换会话');
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

  async function retryMessage(message: ChatMessage) {
    if (!message.id || isSending || isProcessing || retryingMessageId) return;
    setRetryingMessageId(message.id);
    setStatus('正在重试...');
    isProcessingRef.current = true;
    pendingReplyScrollRef.current = true;
    pendingReplyTaskIdRef.current = '';
    setIsProcessing(true);
    setProcessingCount((current) => Math.max(1, current || 1));
    stickToBottomRef.current = true;
    try {
      const result = await apiPost<{
        ok?: boolean;
        error?: string;
        task_id?: string;
        runnable_command?: boolean;
        agent_run_id?: string;
        workflow_run_id?: string;
        run_id?: string;
        run_status?: string;
        status?: string;
      }>('/ui/chat/messages/retry', {
        message_id: message.id,
      });
      if (result.ok === false) throw new Error(result.error || '重试失败');
      if (result.runnable_command) {
        pendingReplyTaskIdRef.current = '';
        const resultRunId = runnableResultRunId(result);
        const resultRunStatus = runnableResultStatus(result);
        const runnableLabel = result.workflow_run_id ? 'Workflow' : 'Agent';
        if (resultRunStatus === 'processing' && resultRunId) {
          setStatus(`${runnableLabel} 执行中...`);
          await refreshMessages();
          pollAgentRunInBackground(resultRunId);
          return;
        }
        pendingReplyScrollRef.current = false;
        setStatus(resultRunStatus === 'approval_required'
          ? `${runnableLabel} 等待审批...`
          : resultRunId
            ? `${runnableLabel} Run 已处理。`
            : 'Agent/Workflow 指令已处理。');
        await refreshMessages();
        await loadSessions();
        return;
      }
      const taskId = String(result.task_id || '');
      pendingReplyTaskIdRef.current = taskId;
      if (!taskId) pendingReplyScrollRef.current = false;
      setStatus('已重新发送，等待回复...');
      void loadSessions();
      await refreshMessages();
      await loadSessions();
    } catch (error) {
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
      setStatus(error instanceof Error ? error.message : '重试失败');
    } finally {
      setRetryingMessageId('');
      focusComposerSoon();
    }
  }

  async function resolveApprovalMessage(message: ChatMessage, action: 'approve' | 'reject') {
    const runId = messageRunId(message);
    if (!message.id) return;
    await resolveApprovalRun({
      action,
      busyId: message.id,
      runId,
    });
  }

  async function resolveApprovalItem(item: ComposerApprovalItem, action: 'approve' | 'reject') {
    await resolveApprovalRun({
      action,
      busyId: item.id,
      composerItemId: item.id,
      runId: item.runId,
      fallbackApprovalDetails: item.details,
      summarizeDelegatedRun: item.source === 'activity',
    });
  }

  async function resolveApprovalRun({ action, busyId, composerItemId, fallbackApprovalDetails, runId, summarizeDelegatedRun }: {
    action: 'approve' | 'reject';
    busyId: string;
    composerItemId?: string;
    fallbackApprovalDetails?: ApprovalRequestDetails;
    runId: string;
    summarizeDelegatedRun?: boolean;
  }) {
    if (!runId || approvalActionMessageId) return;
    setApprovalActionMessageId(busyId);
    setStatus(action === 'approve' ? '正在批准工具调用...' : '正在拒绝工具调用...');
    try {
      const run = action === 'approve'
        ? await approveRunApproval(runId)
        : await rejectRunApproval(runId, 'Rejected from chat');
      const refreshed = await refreshMessages();
      await loadSessions();
      const chatStillProcessing = Boolean(refreshed?.is_processing);
      const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
      const runStatus = normalizeRunStatus(run.status);
      let delegatedSummaryCreated = false;
      let delegatedSummaryError = '';
      let delegatedSummaryTaskId = '';
      if (summarizeDelegatedRun && ['completed', 'failed', 'cancelled'].includes(runStatus)) {
        try {
          const summary = await apiPost<{
            ok?: boolean;
            error?: string;
            summary_created?: boolean;
            task_id?: string;
          }>('/ui/chat/delegated-run-summary', { run_id: runId });
          if (summary.ok === false) throw new Error(summary.error || '创建主模型整理任务失败');
          delegatedSummaryTaskId = String(summary.task_id || '');
          delegatedSummaryCreated = Boolean(summary.summary_created && delegatedSummaryTaskId);
          if (delegatedSummaryCreated) {
            expectPendingAssistantReply(delegatedSummaryTaskId);
            await refreshMessages();
            await loadSessions();
          }
        } catch (error) {
          delegatedSummaryError = error instanceof Error ? error.message : '创建主模型整理任务失败';
        }
      }
      if (composerItemId && runStatus !== 'approval_required') {
        setResolvedComposerApprovalIds((current) => (
          current.includes(composerItemId) ? current : [...current.slice(-20), composerItemId]
        ));
      }
      if (runStatus === 'processing' || runStatus === 'approval_required') {
        setIsProcessing(true);
        isProcessingRef.current = true;
        setProcessingCount(Math.max(1, chatProcessingCount));
        if (runStatus === 'approval_required') {
          rememberRunApprovalDetails(run, fallbackApprovalDetails);
          setStatus(nextApprovalStatusText(run));
        } else {
          forgetRunApprovalDetails(runId);
          setStatus('已批准，Agent 正在继续执行...');
          pollAgentRunInBackground(runId);
        }
      } else {
        forgetRunApprovalDetails(runId);
        const nextProcessing = chatStillProcessing || delegatedSummaryCreated;
        setIsProcessing(nextProcessing);
        isProcessingRef.current = nextProcessing;
        setProcessingCount(delegatedSummaryCreated ? Math.max(1, chatProcessingCount) : chatProcessingCount);
        if (delegatedSummaryCreated) {
          setStatus('Agent 已结束，等待主模型整理委派结果...');
        } else if (delegatedSummaryError) {
          setStatus(`审批后执行结束，但整理任务未创建：${delegatedSummaryError}`);
        } else if (chatStillProcessing) {
          setStatus(action === 'approve' ? '已批准，等待主模型汇总...' : '已拒绝，等待主模型整理结果...');
        } else {
          setStatus(runStatus === 'completed' ? '审批后执行完成。' : '审批后执行结束。');
        }
      }
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '处理审批失败');
    } finally {
      setApprovalActionMessageId('');
      focusComposerSoon();
    }
  }

  async function copyCodeBlock(button: HTMLButtonElement) {
    const block = button.closest('.markdown-code-block');
    const messageNode = button.closest('[data-message-id]') as HTMLElement | null;
    const code = block?.querySelector('code');
    const content = code?.textContent || '';
    if (!content) {
      setStatus('没有可复制代码');
      return;
    }
    const blockIndex = block?.getAttribute('data-code-index') || '0';
    const codeBlockKey = codeBlockStateKey(messageNode?.dataset.messageId || '', blockIndex);
    try {
      await copyText(content);
      setCopiedCodeBlockKey(codeBlockKey);
      setStatus('已复制代码');
      if (codeCopyTimerRef.current !== null) window.clearTimeout(codeCopyTimerRef.current);
      codeCopyTimerRef.current = window.setTimeout(() => {
        setCopiedCodeBlockKey((current) => (current === codeBlockKey ? '' : current));
        codeCopyTimerRef.current = null;
      }, CODE_COPY_FEEDBACK_MS);
    } catch {
      setStatus('复制代码失败');
    }
  }

  async function copySessionId(sessionId: string, event?: ReactMouseEvent<HTMLElement>) {
    event?.stopPropagation();
    if (!sessionId) {
      setStatus('没有可复制的 Session ID');
      return;
    }
    setSessionIdCopyError('');
    try {
      await copyText(sessionId);
      setCopiedSessionId(sessionId);
      setStatus('已复制会话调试 ID');
      window.setTimeout(() => setCopiedSessionId(''), COPY_FEEDBACK_MS);
    } catch (error) {
      setSessionIdDialogOpen(true);
      setSessionIdCopyError(error instanceof Error ? error.message : '复制失败');
      setStatus('复制会话调试 ID 失败');
    }
  }

  function openSessionIdDialog() {
    if (!currentSessionId) {
      setStatus('没有可查看的 Session ID');
      return;
    }
    setSessionIdCopyError('');
    setSessionIdDialogOpen(true);
  }

  function registerMessageNode(messageId: string | undefined, node: HTMLElement | null) {
    if (!messageId) return;
    if (node) messageNodeRefs.current.set(messageId, node);
    else messageNodeRefs.current.delete(messageId);
  }

  function revealMessage(messageId: string | undefined) {
    if (!messageId) return;
    if (highlightClearTimerRef.current !== null) {
      window.clearTimeout(highlightClearTimerRef.current);
      highlightClearTimerRef.current = null;
    }
    highlightedScrollTargetRef.current = messageId;
    setHighlightedMessageId(messageId);
  }

  function openRunDetails(runId: string | undefined) {
    const clean = String(runId || '').trim();
    if (!clean) return;
    navigateTo('agents', { run: clean }, ['tab']);
  }

  function openWorkflowStudio() {
    navigateTo('agents', { tab: 'workflows' }, ['run']);
  }

  function handleMessageListClick(event: ReactMouseEvent<HTMLDivElement>) {
    const target = event.target instanceof Element ? event.target : null;
    const codeCopyButton = target?.closest('[data-code-copy]') as HTMLButtonElement | null;
    if (codeCopyButton) {
      event.preventDefault();
      event.stopPropagation();
      void copyCodeBlock(codeCopyButton);
      return;
    }
    const anchor = (target?.closest('a[href]') || null) as HTMLAnchorElement | null;
    if (!anchor) return;
    event.preventDefault();
    void openExternalUrl(anchor.href);
  }

  function handleMessagePointerDown(event: ReactPointerEvent<HTMLDivElement>) {
    const target = event.target instanceof Element ? event.target : null;
    if (target?.closest('[data-code-copy], .message-copy-button, .message-retry-button')) return;
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

  function focusComposerSoon() {
    window.requestAnimationFrame(() => {
      inputRef.current?.focus({ preventScroll: true });
    });
  }

  function expectPendingAssistantReply(taskId: string) {
    const normalizedTaskId = String(taskId || '').trim();
    pendingReplyTaskIdRef.current = normalizedTaskId;
    pendingReplyScrollRef.current = Boolean(normalizedTaskId);
    if (normalizedTaskId) stickToBottomRef.current = true;
  }

  function rememberRunApprovalDetails(run: RunSpec, fallbackDetails: ApprovalRequestDetails | null = null) {
    const runId = String(run.run_id || run.agent_run_id || run.workflow_run_id || '').trim();
    const pending = run.pending_approval;
    if (!runId || normalizeRunStatus(run.status) !== 'approval_required' || !pending?.tool) {
      if (runId) forgetRunApprovalDetails(runId);
      return;
    }
    const details = approvalRequestDetailsFromRun(run, fallbackDetails);
    const signature = approvalSignatureFromPending(pending);
    setRunApprovalDetailOverrides((current) => ({
      ...current,
      [runId]: {
        details,
        signature,
        createdAt: String(pending.requested_at || run.updated_at || new Date().toISOString()),
      },
    }));
  }

  function forgetRunApprovalDetails(runId: string) {
    const normalizedRunId = String(runId || '').trim();
    if (!normalizedRunId) return;
    setRunApprovalDetailOverrides((current) => {
      if (!current[normalizedRunId]) return current;
      const next = { ...current };
      delete next[normalizedRunId];
      return next;
    });
  }

  function shouldTriggerPendingReplyScroll(nextMessages: ChatMessage[]) {
    if (!pendingReplyScrollRef.current) return false;
    const taskId = pendingReplyTaskIdRef.current;
    if (!taskId) return false;
    return nextMessages.some((message) => (
      message.role === 'assistant'
      && message.task_id === taskId
      && (
        message.status === 'processing'
        || Boolean(messageText(message).trim())
        || Boolean(message.activity_events?.length)
      )
    ));
  }

  function beginConversationLoading() {
    const conversationToken = ++conversationLoadTokenRef.current;
    pendingReplyScrollRef.current = false;
    pendingReplyTaskIdRef.current = '';
    highlightedScrollTargetRef.current = '';
    if (highlightClearTimerRef.current !== null) {
      window.clearTimeout(highlightClearTimerRef.current);
      highlightClearTimerRef.current = null;
    }
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
  const normalizedSessionQuery = debouncedSessionQuery.trim();
  const visibleSessions = sessionItems;
  const agentRunnables = useMemo(
    () => runnables.filter((item) => item.kind === 'agent' && item.enabled !== false),
    [runnables],
  );
  const defaultGroupName = useMemo(
    () => groupDefaultName(agentRunnables, selectedGroupAgentIds, assistantProfile),
    [agentRunnables, assistantProfile, selectedGroupAgentIds],
  );
  const unassignedSessions = useMemo(
    () => sessionItems.filter((session) => isUnassignedSession(session)),
    [sessionItems],
  );

  // Agent 分组逻辑
  type AgentGroup = {
    agent_id: string;
    agent_name: string;
    agent_avatar?: string;
    sessions: SessionItem[];
  };

  const agentGroups = useMemo(() => {
    const groups = new Map<string, AgentGroup>();

    sessionItems
      .filter((s) => !isUnassignedSession(s) && (s.conversation_kind === 'main' || s.conversation_kind === 'agent'))
      .forEach((session) => {
        const agentId = session.runnable_id || 'main';

        // 从 runnables 中获取最新的 Agent 名称
        const runnable = runnables.find((r) => r.id === agentId);
        const agentName = agentId === 'main'
          ? (assistantProfile?.agent_nickname || assistantProfile?.agent_name || '主模型')
          : runnable?.nickname || runnable?.name || session.runnable_name || 'Agent';

        if (!groups.has(agentId)) {
          groups.set(agentId, {
            agent_id: agentId,
            agent_name: agentName,
            sessions: [],
          });
        }
        groups.get(agentId)!.sessions.push(session);
      });

    return Array.from(groups.values());
  }, [sessionItems, runnables, assistantProfile]);

  const groupSessions = useMemo(() => {
    return sessionItems.filter((s) => s.conversation_kind === 'workflow' || s.conversation_kind === 'group');
  }, [sessionItems]);

  // 初始化展开状态（默认全部展开）
  const initializedAgentsRef = useRef(false);
  useEffect(() => {
    if (!initializedAgentsRef.current && agentGroups.length > 0) {
      initializedAgentsRef.current = true;
      setExpandedAgents(new Set(agentGroups.map((g) => g.agent_id)));
    }
  }, [agentGroups]);
  const currentSession = sessionItems.find((session) => session.session_id === sessions?.current_session_id);
  const currentSessionId = sessions?.current_session_id || '';
  const currentIsUnassigned = currentSession
    ? isUnassignedSession(currentSession)
    : messages.length === 0 && normalizeSessionContext(sessionContext).conversation_kind === 'main';
  const activeSessionContext = currentIsUnassigned
    ? { ...normalizeSessionContext(currentSession ? contextFromSession(currentSession) : sessionContext), conversation_kind: 'unassigned' }
    : currentSession ? contextFromSession(currentSession) : normalizeSessionContext(sessionContext);
  useEffect(() => {
    if (approvalSessionIdRef.current === currentSessionId) return;
    approvalSessionIdRef.current = currentSessionId;
    setRunApprovalDetailOverrides({});
    setResolvedComposerApprovalIds([]);
    setComposerApprovalMessageId('');
  }, [currentSessionId]);
  const currentTitle = conversationDisplayName(
    currentSession,
    activeSessionContext,
    assistantProfile,
    messages,
  );
  const deleteTarget = deleteTargetLabel(activeSessionContext);
  const mentionQuery = mentionQueryAtEnd(input);
  const rawMentionSuggestions = useMemo(
    () => mentionOptionsForQuery(runnables, mentionQuery, assistantProfile, activeSessionContext),
    [activeSessionContext, assistantProfile, mentionQuery, runnables],
  );
  const mentionSuggestions = dismissedMentionInput === input ? [] : rawMentionSuggestions;
  const activeMentionOption = mentionSuggestions[mentionActiveIndex] || mentionSuggestions[0];
  const activeMentionOptionId = activeMentionOption ? `composer-mention-option-${mentionActiveIndex}` : undefined;
  const activeMentionChips = useMemo(
    () => activeMentions(input, runnables, assistantProfile),
    [assistantProfile, input, runnables],
  );
  const headerActivity = latestVisibleActivity(messages);
  const composerApprovalItems = useMemo(
    () => approvalRequiredItems(messages, resolvedComposerApprovalIds, runApprovalDetailOverrides),
    [messages, resolvedComposerApprovalIds, runApprovalDetailOverrides],
  );
  const composerApprovalItem = useMemo(() => {
    if (!composerApprovalItems.length) return null;
    const selected = composerApprovalItems.find((item) => item.id === composerApprovalMessageId);
    return selected || composerApprovalItems[composerApprovalItems.length - 1] || null;
  }, [composerApprovalMessageId, composerApprovalItems]);
  const composerApprovalIndex = composerApprovalItem
    ? composerApprovalItems.findIndex((item) => item.id === composerApprovalItem.id)
    : -1;
  const composerApprovalCount = composerApprovalItems.length;
  const composerApprovalDetails = composerApprovalItem?.details || null;
  const chatWorkspaceStyle = embedded
    ? undefined
    : ({ '--chat-sidebar-width': `${sidebarWidth}px` } as CSSProperties);
  const composerInputStyle = { height: `${composerHeight}px` } as CSSProperties;
  const initialChatLoading = !embedded && !chatBootstrapped;
  const conversationLoading = !messagesLoaded;

  useEffect(() => {
    setMentionActiveIndex(0);
  }, [input, rawMentionSuggestions.length]);

  useEffect(() => {
    setMentionActiveIndex((current) => {
      if (!mentionSuggestions.length) return 0;
      return Math.min(Math.max(current, 0), mentionSuggestions.length - 1);
    });
  }, [mentionSuggestions.length]);

  useEffect(() => {
    setComposerApprovalMessageId((current) => {
      if (!composerApprovalItems.length) return '';
      if (current && composerApprovalItems.some((item) => item.id === current)) return current;
      return composerApprovalItems[composerApprovalItems.length - 1]?.id || '';
    });
  }, [composerApprovalItems]);

  function selectComposerApproval(offset: number) {
    if (!composerApprovalCount || composerApprovalIndex < 0) return;
    const nextIndex = (composerApprovalIndex + offset + composerApprovalCount) % composerApprovalCount;
    const nextItem = composerApprovalItems[nextIndex];
    if (!nextItem?.id) return;
    setComposerApprovalMessageId(nextItem.id);
    revealMessage(nextItem.messageId);
  }

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
            {normalizedSessionQuery ? (
              <div className="chat-search-meta">
                {sessionsLoaded ? `找到 ${visibleSessions.length} 个相关会话` : '正在搜索...'}
              </div>
            ) : null}
          </div>

          {/* Tab 切换 */}
          <div className="session-tabs">
            <button
              type="button"
              className={`session-tab ${sessionTab === 'agents' ? 'active' : ''}`}
              onClick={() => setSessionTab('agents')}
            >
              Agent
            </button>
            <button
              type="button"
              className={`session-tab ${sessionTab === 'groups' ? 'active' : ''}`}
              onClick={() => setSessionTab('groups')}
            >
              群组
            </button>
            <button
              type="button"
              className="session-tab-create"
              title={sessionTab === 'groups' ? '创建群组' : '新建对话'}
              aria-label={sessionTab === 'groups' ? '创建群组' : '新建对话'}
              onClick={handleSessionTabCreate}
            >
              <UiIcon name="plus" />
            </button>
          </div>

          <div className="chat-list hy-chat-session-list">
            {/* 搜索结果显示所有匹配的会话 */}
            {normalizedSessionQuery ? (
              visibleSessions.length > 0 ? (
                visibleSessions.map((session) => (
                  <button
                    type="button"
                    className={`chat-item ${session.session_id === sessions?.current_session_id ? 'active' : ''}`}
                    key={session.session_id}
                    onClick={() => void switchSession(session.session_id, session.search_match?.message_id || '')}
                  >
                    <SessionAvatar
                      assistantProfile={assistantProfile}
                      context={contextFromSession(session)}
                      loading={assistantProfileLoading}
                      size="small"
                      runnables={runnables}
                    />
                    <span className="chat-item-info">
                      <strong className="chat-item-name">{sessionDisplayName(session, assistantProfile)}</strong>
                      {session.conversation_kind === 'agent' || session.conversation_kind === 'workflow' || session.conversation_kind === 'group' ? (
                        <span className="chat-item-kind">{sessionKindLabel(session)}</span>
                      ) : null}
                      <span className={session.search_match ? 'chat-item-preview search-hit' : 'chat-item-preview'}>
                        <HighlightedText text={sessionPreview(session)} query={normalizedSessionQuery} />
                      </span>
                    </span>
                    <span className="chat-item-side">
                      <span className="chat-item-time">
                        {sessionSideLabel(session)}
                      </span>
                    </span>
                  </button>
                ))
              ) : (
                <div className="empty-state inline-empty">
                  无匹配会话
                </div>
              )
            ) : sessionTab === 'agents' ? (
              /* Agent 分组视图 */
              unassignedSessions.length > 0 || agentGroups.length > 0 ? (
                <>
                  {unassignedSessions.map((session) => (
                    <button
                      type="button"
                      className={`chat-item unassigned-chat-item ${session.session_id === sessions?.current_session_id ? 'active' : ''}`}
                      key={session.session_id}
                      onClick={() => void switchSession(session.session_id, session.search_match?.message_id || '')}
                    >
                      <SessionAvatar
                        assistantProfile={assistantProfile}
                        context={{ ...contextFromSession(session), conversation_kind: 'unassigned' }}
                        loading={assistantProfileLoading}
                        size="small"
                        runnables={runnables}
                      />
                      <span className="chat-item-info">
                        <strong className="chat-item-name">{sessionDisplayName(session, assistantProfile)}</strong>
                        <span className={session.search_match ? 'chat-item-preview search-hit' : 'chat-item-preview'}>
                          <HighlightedText text={sessionPreview(session)} query={normalizedSessionQuery} />
                        </span>
                      </span>
                      <span className="chat-item-side">
                        <span className="chat-item-time">
                          {sessionSideLabel(session)}
                        </span>
                      </span>
                    </button>
                  ))}
                  {agentGroups.map((group) => {
                  const isExpanded = expandedAgents.has(group.agent_id);
                  return (
                    <div key={group.agent_id} className="agent-group">
                      <button
                        type="button"
                        className="agent-group-header"
                        onClick={() => {
                          setExpandedAgents((prev) => {
                            const next = new Set(prev);
                            if (next.has(group.agent_id)) {
                              next.delete(group.agent_id);
                            } else {
                              next.add(group.agent_id);
                            }
                            return next;
                          });
                        }}
                      >
                        <span className={`agent-group-toggle ${isExpanded ? 'expanded' : ''}`}>
                          {'>'}
                        </span>
                        <span className="agent-group-name">{group.agent_name}</span>
                        <span className="agent-group-count">{group.sessions.length}</span>
                      </button>
                      <div className={`agent-group-sessions ${isExpanded ? 'expanded' : ''}`}>
                        <div className="agent-group-sessions-inner">
                          {group.sessions.map((session) => (
                            <button
                              type="button"
                              className={`chat-item ${session.session_id === sessions?.current_session_id ? 'active' : ''}`}
                              key={session.session_id}
                              onClick={() => void switchSession(session.session_id, session.search_match?.message_id || '')}
                            >
                              <SessionAvatar
                                assistantProfile={assistantProfile}
                                context={contextFromSession(session)}
                                loading={assistantProfileLoading}
                                size="small"
                                runnables={runnables}
                              />
                              <span className="chat-item-info">
                                <strong className="chat-item-name">{sessionDisplayName(session, assistantProfile)}</strong>
                                <span className={session.search_match ? 'chat-item-preview search-hit' : 'chat-item-preview'}>
                                  <HighlightedText text={sessionPreview(session)} query={normalizedSessionQuery} />
                                </span>
                              </span>
                              <span className="chat-item-side">
                                <span className="chat-item-time">
                                  {sessionSideLabel(session)}
                                </span>
                              </span>
                            </button>
                          ))}
                        </div>
                      </div>
                    </div>
                  );
                })}
                </>
              ) : (
                <div className="empty-state inline-empty">
                  {sessionItems.length ? '无匹配会话' : '暂无对话'}
                </div>
              )
            ) : (
              /* 群组视图 (Workflow) */
              groupSessions.length > 0 ? (
                groupSessions.map((session) => (
                  <button
                    type="button"
                    className={`chat-item ${session.session_id === sessions?.current_session_id ? 'active' : ''}`}
                    key={session.session_id}
                    onClick={() => void switchSession(session.session_id, session.search_match?.message_id || '')}
                  >
                    <SessionAvatar
                      assistantProfile={assistantProfile}
                      context={contextFromSession(session)}
                      loading={assistantProfileLoading}
                      size="small"
                      runnables={runnables}
                    />
                    <span className="chat-item-info">
                      <strong className="chat-item-name">{sessionDisplayName(session, assistantProfile)}</strong>
                      <span className="chat-item-kind">{sessionKindLabel(session)}</span>
                      <span className={session.search_match ? 'chat-item-preview search-hit' : 'chat-item-preview'}>
                        <HighlightedText text={sessionPreview(session)} query={normalizedSessionQuery} />
                      </span>
                    </span>
                    <span className="chat-item-side">
                      <span className="chat-item-time">
                        {sessionSideLabel(session)}
                      </span>
                    </span>
                  </button>
                ))
              ) : (
                <div className="empty-state inline-empty">
                  {sessionItems.length ? '无群组会话' : '暂无对话'}
                </div>
              )
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
              <SessionAvatar
                assistantProfile={assistantProfile}
                context={activeSessionContext}
                loading={assistantProfileLoading}
                size="header"
                runnables={runnables}
              />
              <div>
                <div className="chat-header-name">{currentTitle}</div>
                <div className="chat-header-status">
                  <div className={`status-dot ${isProcessing ? 'processing' : 'completed'}`} />
                  <span>{headerStatusText(isProcessing, headerActivity, status, executor, activeSessionContext)}</span>
                </div>
              </div>
            </div>
            <div className="chat-header-actions">
              {activeSessionContext.conversation_kind === 'group' ? (
                <button
                  type="button"
                  className="chat-action-btn"
                  title="群组设置"
                  aria-label="群组设置"
                  disabled={!currentSessionId}
                  onClick={openGroupSettings}
                >
                  <UiIcon name="settings" />
                </button>
              ) : null}
              <button
                type="button"
                className={`chat-action-btn ${copiedSessionId === currentSessionId ? 'copied' : ''}`}
                title={currentSessionId ? `查看/复制会话 ID：${currentSessionId}` : '查看/复制会话 ID'}
                aria-label="查看/复制会话 ID，不复制聊天记录"
                disabled={!currentSessionId}
                onClick={openSessionIdDialog}
              >
                <UiIcon name={copiedSessionId === currentSessionId ? 'check' : 'copy'} />
              </button>
              <button type="button" className="chat-action-btn danger-action" title={`删除${deleteTarget}`} aria-label={`删除${deleteTarget}`} onClick={requestDeleteSession} disabled={!sessions?.sessions?.length}>
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
                  highlighted={message.id === highlightedMessageId}
                  message={message}
                  copiedCodeBlockKey={copiedCodeBlockKey}
                  retryDisabled={isSending || isProcessing || Boolean(retryingMessageId)}
                  retrying={retryingMessageId === message.id}
                  showRetry={isRetryableMessage(message, messages)}
                  approvalBusy={Boolean(
                    message.id
                    && (approvalActionMessageId === message.id || approvalActionMessageId.startsWith(`message:${message.id}:`)),
                  )}
                  onCopy={() => void copyMessage(message)}
                  onRetry={() => void retryMessage(message)}
                  onApprove={() => void resolveApprovalMessage(message, 'approve')}
                  onReject={() => void resolveApprovalMessage(message, 'reject')}
                  onOpenRunDetails={openRunDetails}
                  onOpenWorkflowStudio={openWorkflowStudio}
                  registerMessageNode={registerMessageNode}
                  runnables={runnables}
                />
              ))}
              <div className="chat-bottom-anchor" ref={bottomAnchorRef} aria-hidden="true" />
            </div>
          </section>

          <form className="chat-input-area composer refined-composer" onSubmit={submit}>
            {composerApprovalItem && composerApprovalDetails ? (
              <ComposerApprovalNotice
                busy={approvalActionMessageId === composerApprovalItem.id}
                currentIndex={composerApprovalIndex}
                details={composerApprovalDetails}
                onApprove={() => void resolveApprovalItem(composerApprovalItem, 'approve')}
                onReject={() => void resolveApprovalItem(composerApprovalItem, 'reject')}
                onOpenDetails={() => openRunDetails(composerApprovalItem.runId)}
                onPrevious={() => selectComposerApproval(-1)}
                onReveal={() => revealMessage(composerApprovalItem.messageId)}
                onNext={() => selectComposerApproval(1)}
                runId={composerApprovalItem.runId}
                total={composerApprovalCount}
              />
            ) : null}
            <div className={`chat-input-wrapper${isProcessing ? ' is-processing' : ''}`}>
              <div className="composer-body">
                {attachments.length ? (
                  <div className="composer-attachments" aria-label="已添加图片附件">
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
                {activeMentionChips.length ? (
                  <div className="composer-mention-chips" aria-label="当前提及">
                    {activeMentionChips.map((mention) => (
                      <span className={`composer-mention-chip ${mention.kind}`} key={`${mention.kind}-${mention.id}`}>
                        @{mention.nickname || mention.name}
                      </span>
                    ))}
                  </div>
                ) : null}
                {mentionSuggestions.length ? (
                  <div className="composer-mention-menu" id="composer-mention-menu" role="listbox" aria-label="选择提及对象">
                    {mentionSuggestions.map((option, index) => (
                      <button
                        type="button"
                        className={`composer-mention-option ${option.kind}${index === mentionActiveIndex ? ' active' : ''}`}
                        id={`composer-mention-option-${index}`}
                        key={`${option.kind}-${option.id}`}
                        role="option"
                        aria-selected={index === mentionActiveIndex}
                        onClick={() => insertMention(option)}
                        onMouseEnter={() => setMentionActiveIndex(index)}
                      >
                        <span className="composer-mention-avatar">
                          {option.kind === 'workflow' ? (
                            <AvatarStack participants={option.participants || []} />
                          ) : (
                            participantAvatarContent(option, option.kind === 'main' ? '月' : 'A')
                          )}
                        </span>
                        <span className="composer-mention-text">
                          <strong>{option.nickname || option.name}</strong>
                          <small>{mentionKindLabel(option)}</small>
                        </span>
                      </button>
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
                  aria-activedescendant={activeMentionOptionId}
                  aria-disabled={isSending}
                  aria-controls={mentionSuggestions.length ? 'composer-mention-menu' : undefined}
                  aria-expanded={mentionSuggestions.length > 0}
                  aria-haspopup="listbox"
                  readOnly={isSending}
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
                title={attachmentHelpText(executor)}
                aria-label="添加附件，当前仅支持图片"
                onClick={() => fileInputRef.current?.click()}
              >
                <UiIcon name="paperclip" />
              </button>
              {isProcessing ? (
                <button
                  type="button"
                  className="chat-stop-btn"
                  aria-label={processingCount > 1 ? `停止当前 ${processingCount} 项任务` : '停止当前任务'}
                  title={processingCount > 1 ? `停止当前 ${processingCount} 项任务` : '停止当前任务'}
                  onClick={() => void cancelProcessing()}
                >
                  <UiIcon name="stop" />
                </button>
              ) : null}
              <button
                type="submit"
                className="chat-send-btn neon-glow"
                disabled={isSending || (!input.trim() && attachments.length === 0)}
                aria-label="发送消息"
                title={isProcessing ? '继续发送消息' : '发送消息'}
              >
                <UiIcon name="send" />
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

      {groupDialogOpen ? (
        <CreateGroupDialog
          agentRunnables={agentRunnables}
          assistantProfile={assistantProfile}
          defaultGroupName={defaultGroupName}
          error={groupDialogError}
          groupAvatarUrl={groupAvatarUrl}
          groupName={groupName}
          mode={groupDialogMode}
          isCreating={isCreatingGroup}
          selectedAgentIds={selectedGroupAgentIds}
          onAvatarUrlChange={(value) => {
            setGroupDialogError('');
            setGroupAvatarUrl(value);
          }}
          onAvatarError={(message) => {
            setGroupDialogError(message);
            setStatus(message);
          }}
          onClose={closeGroupDialog}
          onNameChange={(value) => {
            setGroupDialogError('');
            setGroupName(value);
          }}
          onSubmit={submitGroupDialog}
          onToggleAgent={toggleGroupAgent}
        />
      ) : null}

      {sessionIdDialogOpen ? (
        <SessionIdDialog
          copied={copiedSessionId === currentSessionId}
          error={sessionIdCopyError}
          sessionId={currentSessionId}
          onClose={() => setSessionIdDialogOpen(false)}
          onCopy={() => void copySessionId(currentSessionId)}
        />
      ) : null}

      <div
        className={`chat-readiness-overlay${initialChatLoading ? ' is-visible' : ''}`}
        aria-hidden={!initialChatLoading}
      >
        <ChatFullPageLoading
          avatarUrl={assistantProfile?.agent_avatar_url}
          label={assistantProfile?.agent_name || '月見八千代'}
        />
      </div>
      {confirmDialog}
    </section>
  );
}

function isMissingGroupEditRouteError(error: unknown): boolean {
  const message = error instanceof Error ? error.message : String(error || '');
  return /\b(?:HTTP 404|404|Not Found)\b/i.test(message);
}

function CreateGroupDialog({ agentRunnables, assistantProfile, defaultGroupName, error, groupAvatarUrl, groupName, isCreating, mode, selectedAgentIds, onAvatarError, onAvatarUrlChange, onClose, onNameChange, onSubmit, onToggleAgent }: {
  agentRunnables: RunnableSummary[];
  assistantProfile: AssistantProfilePayload | null;
  defaultGroupName: string;
  error: string;
  groupAvatarUrl: string;
  groupName: string;
  isCreating: boolean;
  mode: 'create' | 'edit';
  selectedAgentIds: string[];
  onAvatarError: (message: string) => void;
  onAvatarUrlChange: (value: string) => void;
  onClose: () => void;
  onNameChange: (value: string) => void;
  onSubmit: (event: FormEvent) => void;
  onToggleAgent: (agentId: string) => void;
}) {
  const avatarInputRef = useRef<HTMLInputElement>(null);
  const mainName = assistantProfile?.agent_name || 'Yachiyo';
  const mainNickname = assistantProfile?.agent_nickname || '八千代';
  const memberCount = selectedAgentIds.length + 1;
  const selectedParticipants: ChatParticipant[] = [
    { kind: 'main', name: mainName, nickname: mainNickname, avatar_url: assistantProfile?.agent_avatar_url },
    ...selectedAgentIds
      .map((agentId) => agentRunnables.find((agent) => agent.id === agentId))
      .filter((agent): agent is RunnableSummary => Boolean(agent))
      .map((agent): ChatParticipant => ({
        kind: 'agent',
        id: agent.id,
        name: agent.name,
        nickname: agent.nickname,
        avatar_url: agent.avatar_url,
      })),
  ];
  const dialogTitle = mode === 'edit' ? '群组设置' : '创建群组';
  const submittingText = mode === 'edit' ? '保存中...' : '创建中...';
  const submitText = mode === 'edit' ? '保存' : '创建';

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  function acceptAvatarValue(value: string) {
    const avatar = String(value || '').trim();
    if (!avatar) return;
    if (avatar.startsWith('data:image/') && avatar.length > GROUP_AVATAR_MAX_DATA_URL_CHARS) {
      onAvatarError('群头像不能超过 1 MB');
      return;
    }
    onAvatarUrlChange(avatar);
  }

  async function pickGroupAvatar() {
    try {
      const selection = await chooseAvatarImage();
      const avatar = typeof selection === 'string' ? selection : selection?.data_url || selection?.path || '';
      acceptAvatarValue(avatar);
    } catch (error) {
      const message = error instanceof Error ? error.message : '选择群头像失败';
      if (message.includes('桌面图片选择器')) {
        avatarInputRef.current?.click();
        return;
      }
      onAvatarError(message);
    }
  }

  async function applyAvatarFile(file: File) {
    if (!file.type.startsWith('image/')) {
      onAvatarError('请选择图片作为群头像');
      return;
    }
    if (file.size > GROUP_AVATAR_MAX_BYTES) {
      onAvatarError('群头像不能超过 1 MB');
      return;
    }
    try {
      const attachment = await readPendingAttachment(file);
      onAvatarUrlChange(attachment.data_url);
    } catch (error) {
      onAvatarError(error instanceof Error ? error.message : '读取群头像失败');
    }
  }

  return (
    <div className="chat-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <form className="chat-group-dialog" role="dialog" aria-modal="true" aria-label={dialogTitle} onSubmit={onSubmit}>
        <header className="chat-group-dialog-header">
          <div>
            <strong>{dialogTitle}</strong>
            <span>{memberCount} 成员</span>
          </div>
          <button type="button" className="chat-action-btn" aria-label="关闭" title="关闭" onClick={onClose}>
            <UiIcon name="close" />
          </button>
        </header>
        <div className="chat-group-profile-fields">
          <div className="chat-group-avatar-control">
            <button
              type="button"
              className="chat-group-avatar-preview"
              aria-label="选择群头像"
              title="选择群头像"
              onClick={() => void pickGroupAvatar()}
            >
              {groupAvatarUrl.trim() ? (
                avatarNode(groupAvatarUrl.trim(), groupName || defaultGroupName || '群组', '群')
              ) : (
                <AvatarStack participants={selectedParticipants} />
              )}
            </button>
            <button
              type="button"
              className="chat-group-avatar-clear"
              aria-label="清除群头像"
              title="清除群头像"
              disabled={!groupAvatarUrl.trim()}
              onClick={() => onAvatarUrlChange('')}
            >
              <UiIcon name="close" />
            </button>
            <input
              ref={avatarInputRef}
              type="file"
              accept="image/*"
              hidden
              onChange={(event) => {
                const file = event.target.files?.[0];
                event.target.value = '';
                if (file) void applyAvatarFile(file);
              }}
            />
          </div>
          <div className="chat-group-field-stack">
            <input
              className="chat-group-name-input"
              value={groupName}
              onChange={(event) => onNameChange(event.target.value)}
              placeholder={defaultGroupName ? `默认：${defaultGroupName}` : '群组名称'}
              maxLength={48}
              aria-label="群组名称"
            />
            <div className="chat-group-avatar-actions">
              <button type="button" className="chat-group-secondary-btn" onClick={() => void pickGroupAvatar()}>
                选择头像
              </button>
              <button type="button" className="chat-group-secondary-btn" disabled={!groupAvatarUrl.trim()} onClick={() => onAvatarUrlChange('')}>
                清除
              </button>
            </div>
          </div>
        </div>
        {error ? <div className="chat-group-dialog-error">{error}</div> : null}
        <div className="chat-group-member-list">
          <label className="chat-group-member is-fixed">
            <input type="checkbox" checked readOnly />
            <span className="chat-group-member-avatar">{participantAvatarContent({ kind: 'main', name: mainName, nickname: mainNickname, avatar_url: assistantProfile?.agent_avatar_url }, '月')}</span>
            <span>
              <strong>主模型</strong>
              <small>{mainNickname || mainName}</small>
            </span>
          </label>
          {agentRunnables.map((agent) => {
            const selected = selectedAgentIds.includes(agent.id);
            const participant: ChatParticipant = {
              kind: 'agent',
              id: agent.id,
              name: agent.name,
              nickname: agent.nickname,
              avatar_url: agent.avatar_url,
            };
            return (
              <label className={`chat-group-member ${selected ? 'selected' : ''}`} key={agent.id}>
                <input
                  type="checkbox"
                  checked={selected}
                  onChange={() => onToggleAgent(agent.id)}
                />
                <span className="chat-group-member-avatar">{participantAvatarContent(participant, 'A')}</span>
                <span>
                  <strong>{agent.nickname || agent.name}</strong>
                  <small>{groupAgentMetaLine(agent)}</small>
                  {agent.description ? <em>{agent.description}</em> : null}
                </span>
              </label>
            );
          })}
        </div>
        <footer className="chat-group-dialog-actions">
          <button type="button" className="chat-group-secondary-btn" onClick={onClose}>取消</button>
          <button type="submit" className="chat-group-primary-btn" disabled={isCreating || selectedAgentIds.length === 0}>
            {isCreating ? submittingText : submitText}
          </button>
        </footer>
      </form>
    </div>
  );
}

function groupAgentMetaLine(agent: RunnableSummary): string {
  const parts = [
    agent.name,
    agent.category ? `类别 ${agent.category}` : '',
    agent.output_contract ? `交付 ${agent.output_contract}` : '',
  ].filter(Boolean);
  return parts.join(' · ') || 'Agent';
}

function SessionIdDialog({ copied, error, sessionId, onClose, onCopy }: {
  copied: boolean;
  error: string;
  sessionId: string;
  onClose: () => void;
  onCopy: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);
  useEffect(() => {
    window.setTimeout(() => {
      inputRef.current?.focus({ preventScroll: true });
      inputRef.current?.select();
    }, 30);
  }, []);
  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);
  return (
    <div className="chat-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div className="chat-session-id-dialog" role="dialog" aria-modal="true" aria-label="会话 ID">
        <header className="chat-group-dialog-header">
          <div>
            <strong>会话 ID</strong>
            <span>{error ? '复制失败时可手动选择' : '用于调试，不会复制聊天记录'}</span>
          </div>
          <button type="button" className="chat-action-btn" aria-label="关闭" title="关闭" onClick={onClose}>
            <UiIcon name="close" />
          </button>
        </header>
        <input
          ref={inputRef}
          className="chat-session-id-input"
          value={sessionId}
          readOnly
          onFocus={(event) => event.currentTarget.select()}
        />
        {error ? <div className="chat-session-id-error">剪贴板不可用：{error}</div> : null}
        <footer className="chat-group-dialog-actions">
          <button type="button" className="chat-group-secondary-btn" onClick={onClose}>关闭</button>
          <button type="button" className="chat-group-primary-btn" onClick={onCopy}>
            {copied ? '已复制' : '复制 ID'}
          </button>
        </footer>
      </div>
    </div>
  );
}

function MessageBubble({ approvalBusy, assistantProfile, assistantProfileLoading, copied, copiedCodeBlockKey, displayContent, highlighted, message, retryDisabled, retrying, showRetry, onApprove, onCopy, onOpenRunDetails, onOpenWorkflowStudio, onReject, onRetry, registerMessageNode, runnables }: {
  approvalBusy: boolean;
  assistantProfile: AssistantProfilePayload | null;
  assistantProfileLoading: boolean;
  copied: boolean;
  copiedCodeBlockKey: string;
  displayContent: string;
  highlighted: boolean;
  message: ChatMessage;
  retryDisabled: boolean;
  retrying: boolean;
  showRetry: boolean;
  onApprove: () => void;
  onCopy: () => void;
  onOpenRunDetails: (runId: string) => void;
  onOpenWorkflowStudio: () => void;
  onReject: () => void;
  onRetry: () => void;
  registerMessageNode: (messageId: string | undefined, node: HTMLElement | null) => void;
  runnables: RunnableSummary[];
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
  const runId = messageRunId(message);
  const showApprovalActions = hasActionableApproval(message) && Boolean(runId);
  const approvalDetails = showApprovalActions ? approvalRequestDetails(message) : null;
  const showAgentProgress = isProcessingEmpty && Boolean(runId || message.metadata?.runnable_kind === 'agent' || message.metadata?.runnable_kind === 'workflow');
  const showInlineRunDetails = role === 'assistant' && Boolean(runId) && !approvalDetails && !showAgentProgress;
  const artifactCount = Number(message.metadata?.run_artifact_count || 0);
  const duplicateError = Boolean(message.error && displayContent.trim() && message.error.trim() === displayContent.trim());
  const summaryNotice = groupAgentSummaryNotice(message);
  const followupNotice = groupFollowupNotice(message);
  const showWorkflowStudioAction = message.metadata?.guidance_type === 'workflow_chat_entry_disabled';
  return (
    <article
      className={`message message--${messageVisualRole(role)} refined-message ${role} ${statusClass}${highlighted ? ' search-highlighted' : ''}`}
      data-message-id={message.id || ''}
      ref={(node) => registerMessageNode(message.id, node)}
    >
      <div className="message-avatar">{messageAvatar(message, assistantProfile, assistantProfileLoading, runnables)}</div>
      <div className="message-stack">
        <div className="message-bubble">
          {approvalDetails ? (
            <ApprovalRequestCard copiedCodeBlockKey={copiedCodeBlockKey} details={approvalDetails} messageId={message.id || ''} onOpenDetails={() => onOpenRunDetails(runId)} runId={runId} />
          ) : showAgentProgress ? (
            <AgentRunProgressCard message={message} onOpenDetails={() => onOpenRunDetails(runId)} runId={runId} />
          ) : isProcessingEmpty ? (
            <TypingIndicator />
          ) : (
            <div className="message-content markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(displayContent, message.id || '', copiedCodeBlockKey) }} />
          )}
          {message.attachments?.length ? (
            <div className="message-attachments">
              {message.attachments.map((attachment) => (
                <ImageAttachmentViewer attachment={attachment} key={attachment.id || attachment.name} />
              ))}
            </div>
          ) : null}
          {message.error && !duplicateError ? <div className="message-error">{message.error}</div> : null}
          {summaryNotice ? <div className={`message-summary-status ${summaryNotice.tone}`}>{summaryNotice.text}</div> : null}
        </div>
        <MessageActivityList
          events={message.activity_events || []}
          messageStatus={message.status}
          onOpenRunDetails={onOpenRunDetails}
          progressLabel={message.progress_label}
        />
        {followupNotice ? <div className="message-followup-status">{followupNotice}</div> : null}
        {showApprovalActions ? (
          <div className="message-approval-actions">
            <button type="button" className="message-approval-approve" disabled={approvalBusy} onClick={onApprove}>
              {approvalBusy ? '处理中...' : '批准'}
            </button>
            <button type="button" className="message-approval-reject" disabled={approvalBusy} onClick={onReject}>
              拒绝
            </button>
          </div>
        ) : null}
        <div className="message-time">
          <span>{messageMetaText(message, message.status, message.created_at)}</span>
          {artifactCount > 0 && runId ? (
            <button
              className="message-artifact-detail-button"
              type="button"
              title={message.metadata?.run_artifacts?.map((artifact) => artifact.path).filter(Boolean).join('\n') || '查看运行产物'}
              onClick={() => onOpenRunDetails(runId)}
            >
              产物 {artifactCount}
            </button>
          ) : null}
          {showInlineRunDetails ? (
            <button
              className="message-run-detail-button"
              type="button"
              onClick={() => onOpenRunDetails(runId)}
            >
              运行详情
            </button>
          ) : null}
          {showWorkflowStudioAction ? (
            <button
              className="message-run-detail-button"
              type="button"
              onClick={onOpenWorkflowStudio}
            >
              打开 Workflow Studio
            </button>
          ) : null}
          {showRetry ? (
            <button
              className={`message-retry-button ${retrying ? 'retrying' : ''}`}
              type="button"
              title={retrying ? '重试中' : '重试这条失败消息'}
              aria-label={retrying ? '重试中' : '重试这条失败消息'}
              disabled={retryDisabled}
              onClick={onRetry}
            >
              <UiIcon name="retry" />
            </button>
          ) : null}
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

function MessageActivityList({ events, messageStatus, onOpenRunDetails, progressLabel }: {
  events: ChatActivityEvent[];
  messageStatus?: string;
  onOpenRunDetails: (runId: string) => void;
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
        const runId = activityRunId(event);
        return (
          <div className={`message-activity-row ${activityStatusClass(displayStatus)}${runId ? ' has-detail' : ''}`} key={`${event.event_id || event.title || 'activity'}-${index}`}>
            <span className="message-activity-icon" aria-hidden="true">{activityStatusIcon(displayStatus)}</span>
            <span className="message-activity-text">
              <strong>{event.title || event.tool_name || 'Hermes 活动'}</strong>
              {event.detail ? <small>{event.detail}</small> : null}
            </span>
            <time>{formatShortTime(event.created_at)}</time>
            {runId ? (
              <button type="button" className="message-activity-detail-button" onClick={() => onOpenRunDetails(runId)}>
                详情
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

type ApprovalRequestDetails = {
  requester: string;
  tool: string;
  goal: string;
  codeLanguage: string;
  codeText: string;
  summary: Array<{ label: string; value: string }>;
};

type RunApprovalDetailOverride = {
  signature: string;
  details: ApprovalRequestDetails;
  createdAt?: string;
};

type ComposerApprovalItem = {
  id: string;
  messageId?: string;
  runId: string;
  createdAt?: string;
  details: ApprovalRequestDetails;
  source: 'message' | 'activity' | 'workflow-child';
};

function ApprovalRequestCard({ copiedCodeBlockKey, details, messageId, onOpenDetails, runId }: {
  copiedCodeBlockKey: string;
  details: ApprovalRequestDetails;
  messageId: string;
  onOpenDetails: () => void;
  runId: string;
}) {
  const workflowApproval = isWorkflowApprovalDetails(details);
  return (
    <div className="message-content message-approval-card">
      <div className="message-approval-card-header">
        <span className="message-approval-eyebrow">需要审批</span>
        <div>
          <strong>{workflowApproval ? `${details.requester} 等待人工确认` : `${details.requester} 请求执行工具调用`}</strong>
          <span>{workflowApproval ? '批准后会继续当前 Workflow' : '批准后会继续当前任务'}</span>
        </div>
        <span className="message-approval-header-side">
          <code>{details.tool}</code>
          {runId ? (
            <button type="button" onClick={onOpenDetails}>
              运行详情
            </button>
          ) : null}
        </span>
      </div>
      {details.goal ? (
        <section className="message-approval-section">
          <span>关联任务</span>
          <p>{details.goal}</p>
        </section>
      ) : null}
      <section className="message-approval-section">
        <span>{workflowApproval ? '审批内容' : '请求内容'}</span>
        {details.summary.length ? (
          <dl className="message-approval-summary">
            {details.summary.map((item) => (
              <div key={`${item.label}:${item.value}`}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {details.codeText ? (
          <div
            className="message-approval-code markdown"
            dangerouslySetInnerHTML={{
              __html: renderMarkdown(fencedCode(details.codeText, details.codeLanguage), messageId, copiedCodeBlockKey),
            }}
          />
        ) : details.summary.length ? null : <p>没有可展示的参数预览。</p>}
      </section>
    </div>
  );
}

function ComposerApprovalNotice({ busy, currentIndex, details, onApprove, onNext, onOpenDetails, onPrevious, onReject, onReveal, runId, total }: {
  busy: boolean;
  currentIndex: number;
  details: ApprovalRequestDetails;
  onApprove: () => void;
  onNext: () => void;
  onOpenDetails: () => void;
  onPrevious: () => void;
  onReject: () => void;
  onReveal: () => void;
  runId?: string;
  total: number;
}) {
  const preview = details.codeText || details.summary.map((item) => item.value).join(' ');
  const hasMultiple = total > 1 && currentIndex >= 0;
  const workflowApproval = isWorkflowApprovalDetails(details);
  const subtitle = workflowApproval
    ? workflowApprovalNoticeSubtitle(details, preview)
    : details.goal || compactStatusText(preview, 86) || '需要确认工具调用后继续执行';
  return (
    <div className="composer-approval-notice">
      <div className="composer-approval-main">
        <span className="composer-approval-badge">{hasMultiple ? `待审批 ${currentIndex + 1}/${total}` : '待审批'}</span>
        <div>
          <strong>{workflowApproval ? `${details.requester} 等待人工确认` : `${details.requester} 请求 ${details.tool}`}</strong>
          <span>{subtitle}</span>
        </div>
      </div>
      <div className="composer-approval-actions">
        {hasMultiple ? (
          <span className="composer-approval-nav" aria-label="切换待审批请求">
            <button type="button" disabled={busy} onClick={onPrevious}>上一项</button>
            <button type="button" disabled={busy} onClick={onNext}>下一项</button>
          </span>
        ) : null}
        <button type="button" onClick={onReveal}>定位消息</button>
        {runId ? (
          <button type="button" onClick={onOpenDetails}>运行详情</button>
        ) : null}
        <button type="button" className="approve" disabled={busy} onClick={onApprove}>{busy ? '处理中...' : '批准'}</button>
        <button type="button" className="reject" disabled={busy} onClick={onReject}>拒绝</button>
      </div>
    </div>
  );
}

function workflowApprovalNoticeSubtitle(details: ApprovalRequestDetails, preview: string) {
  const checkpoint = details.summary.find((item) => item.label === '审批节点')?.value || '';
  const criteria = details.summary.find((item) => item.label === '审批说明')?.value || '';
  const primary = [checkpoint, criteria].filter(Boolean).join('：');
  return compactStatusText(primary || preview || details.goal || '需要确认审批节点后继续执行', 86);
}

function AgentRunProgressCard({ message, onOpenDetails, runId }: {
  message: ChatMessage;
  onOpenDetails: () => void;
  runId: string;
}) {
  const sender = message.metadata?.sender;
  const name = participantDisplayName(sender) || messageRoleLabel(message);
  const title = String(message.metadata?.run_progress_title || 'Agent 正在执行');
  const detail = String(message.metadata?.run_progress_detail || `${name} 正在继续处理当前任务。`);
  return (
    <div className="message-content message-agent-progress-card">
      <span className="message-agent-progress-icon loading-ring" aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <span>{detail}</span>
        {runId ? (
          <button type="button" onClick={onOpenDetails}>
            运行详情
          </button>
        ) : null}
      </div>
    </div>
  );
}

function approvalRequestDetails(message: ChatMessage): ApprovalRequestDetails {
  const pending = message.metadata?.pending_approval || {};
  const preview = pending.input_preview;
  const tool = String(pending.tool || approvalToolFromContent(message.content || message.text || '') || 'tool');
  const requester = participantDisplayName(message.metadata?.sender) || messageRoleLabel(message);
  const goal = String(message.metadata?.delegated_goal || message.metadata?.group_goal || approvalGoalFromContent(message.content || message.text || '') || '').trim();
  const summary: Array<{ label: string; value: string }> = [];
  let codeLanguage = tool === 'terminal.run' ? 'bash' : 'text';
  let codeText = '';

  if (isRecord(preview)) {
    const command = stringValue(preview.command);
    if (command) {
      codeLanguage = 'bash';
      codeText = command;
    }
    if (tool === 'workflow.approval') {
      const checkpoint = stringValue(preview.checkpoint || preview.node || preview.label);
      if (checkpoint) summary.push({ label: '审批节点', value: checkpoint });
      const criteria = stringValue(preview.criteria || preview.approval_criteria || preview.instructions);
      if (criteria) summary.push({ label: '审批说明', value: criteria });
      const context = stringValue(preview.context || preview.summary || preview.result);
      if (context) summary.push({ label: '当前上下文', value: context });
    }
    const path = stringValue(preview.path || preview.file || preview.filename);
    if (path) summary.push({ label: '文件', value: path });
    const timeout = stringValue(preview.timeout_seconds || preview.timeout || preview.timeout_ms);
    if (timeout) summary.push({ label: '超时', value: timeout.endsWith('s') ? timeout : `${timeout}s` });
    const content = stringValue(preview.content || preview.body || preview.patch);
    if (!codeText && content) {
      codeLanguage = tool === 'workspace.write_patch' ? detectCodeLanguage(content) || 'text' : 'text';
      codeText = content;
    }
    if (!codeText && !summary.length) {
      const compact = approvalPreviewFallback(preview);
      if (compact) summary.push({ label: '参数', value: compact });
    }
  } else {
    const compact = approvalPreviewFallback(preview);
    if (compact) summary.push({ label: '参数', value: compact });
  }

  if (!codeText) {
    const command = approvalCommandFromContent(message.content || message.text || '');
    if (command) {
      codeLanguage = 'bash';
      codeText = command;
    }
  }

  return { requester, tool, goal, codeLanguage, codeText, summary };
}

function approvalRequestDetailsFromActivity(event: ChatActivityEvent): ApprovalRequestDetails {
  const pending = event.metadata?.pending_approval || {};
  return approvalRequestDetails({
    id: event.event_id,
    role: 'assistant',
    content: `${event.title || ''}\n${event.detail || ''}`,
    metadata: {
      pending_approval: pending as ChatMessageMetadata['pending_approval'],
      sender: { kind: 'agent', name: activityApprovalRequester(event) },
    },
  });
}

function approvalRequestDetailsFromWorkflowWaitingChild(message: ChatMessage): ApprovalRequestDetails {
  const metadata = message.metadata || {};
  const workflowName = participantDisplayName(metadata.sender) || 'Workflow';
  const requester = stringValue(metadata.workflow_waiting_node) || '子 Agent';
  const tool = stringValue(metadata.workflow_waiting_tool) || 'tool';
  const summary = [
    { label: '父 Workflow', value: workflowName },
    { label: 'Workflow 节点', value: requester },
  ];
  const runId = stringValue(metadata.workflow_waiting_child_run_id);
  if (runId) summary.push({ label: '子 Run', value: runId });
  return {
    requester,
    tool,
    goal: approvalGoalFromContent(message.content || message.text || ''),
    codeLanguage: tool === 'terminal.run' ? 'bash' : 'text',
    codeText: '',
    summary,
  };
}

function approvalRequestDetailsFromRun(run: RunSpec, fallbackDetails: ApprovalRequestDetails | null = null): ApprovalRequestDetails {
  const pending = run.pending_approval || {};
  return approvalRequestDetails({
    id: run.run_id,
    role: 'assistant',
    content: '',
    metadata: {
      delegated_goal: String(run.user_goal || fallbackDetails?.goal || ''),
      pending_approval: pending as ChatMessageMetadata['pending_approval'],
      sender: {
        kind: run.kind === 'workflow_run' ? 'workflow' : 'agent',
        name: String(run.runnable_name || fallbackDetails?.requester || 'Agent'),
      },
    },
  });
}

function activityApprovalRequester(event: ChatActivityEvent) {
  const title = String(event.title || '').trim();
  return title
    .replace(/\s*(等待审批|请求执行工具调用|请求工具调用|委派失败|委派完成)\s*$/u, '')
    .trim() || String(event.tool_name || 'Agent').trim();
}

function isWorkflowApprovalDetails(details: ApprovalRequestDetails) {
  return details.tool === 'workflow.approval';
}

function approvalToolFromContent(text: string) {
  const match = String(text || '').match(/工具[:：]\s*([A-Za-z0-9_.-]+)/);
  return match?.[1] || '';
}

function approvalGoalFromContent(text: string) {
  const match = String(text || '').match(/关联任务[:：]\s*([^\n]+)/);
  return match?.[1]?.trim() || '';
}

function approvalCommandFromContent(text: string) {
  const match = String(text || '').match(/(?:命令|command)[:：]\s*(.+)$/is);
  return match?.[1]?.trim() || '';
}

function approvalPreviewFallback(value: unknown) {
  if (value === undefined || value === null || value === '') return '';
  if (typeof value === 'string' || typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function messageApprovalSignature(message: ChatMessage) {
  return approvalSignatureFromPending(message.metadata?.pending_approval);
}

function activityApprovalSignature(event: ChatActivityEvent) {
  return approvalSignatureFromPending(event.metadata?.pending_approval);
}

function approvalSignatureFromPending(pending: unknown) {
  if (!isRecord(pending)) return 'none';
  const approvalId = stringValue(pending.approval_id);
  const requestedAt = stringValue(pending.requested_at);
  const tool = stringValue(pending.tool);
  const preview = approvalPreviewFallback(pending.input_preview).slice(0, 220);
  const raw = [approvalId, requestedAt, tool, preview].filter(Boolean).join('|') || 'pending';
  return raw.replace(/[^A-Za-z0-9_.:-]+/g, '_').slice(0, 240);
}

function workflowWaitingChildApprovalSignature(message: ChatMessage) {
  const metadata = message.metadata || {};
  const raw = [
    metadata.workflow_waiting_child_run_id,
    metadata.workflow_waiting_tool,
    metadata.workflow_waiting_node,
    messageRunId(message),
  ].map(stringValue).filter(Boolean).join('|') || 'workflow-child-approval';
  return raw.replace(/[^A-Za-z0-9_.:-]+/g, '_').slice(0, 240);
}

function nextApprovalStatusText(run: { pending_approval?: { tool?: string; input_preview?: unknown } }) {
  const tool = String(run.pending_approval?.tool || 'tool');
  const preview = run.pending_approval?.input_preview;
  let detail = '';
  if (isRecord(preview)) {
    detail = stringValue(preview.command || preview.path || preview.file || preview.filename);
  } else {
    detail = stringValue(preview);
  }
  const suffix = detail ? `：${compactStatusText(detail, 54)}` : '';
  return `还有新的工具审批待确认：${tool}${suffix}`;
}

function stringValue(value: unknown) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}

function fencedCode(code: string, language: string) {
  const safeCode = String(code || '').replace(/```/g, '`\\`\\`');
  return `\`\`\`${language || 'text'}\n${safeCode}\n\`\`\``;
}

function TypingIndicator() {
  return (
    <span className="typing-indicator loading-dots" aria-label="处理中">
      <span className="loading-dot" /><span className="loading-dot" /><span className="loading-dot" />
    </span>
  );
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const lowerText = text.toLowerCase();
  const lowerNeedle = needle.toLowerCase();
  const index = lowerText.indexOf(lowerNeedle);
  if (index < 0) return <>{text}</>;
  const before = text.slice(0, index);
  const match = text.slice(index, index + needle.length);
  const after = text.slice(index + needle.length);
  return (
    <>
      {before}
      <mark>{match}</mark>
      {after}
    </>
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

function groupAgentSummaryNotice(message: ChatMessage): { tone: 'pending' | 'failed' | 'completed'; text: string } | null {
  const metadata = message.metadata || {};
  const status = String(metadata.group_agent_summary_status || '').trim();
  const subject = groupAgentSummarySubject(metadata);
  if (status === 'failed') {
    const error = String(metadata.group_agent_summary_error || '').trim();
    return {
      tone: 'failed',
      text: error ? `主模型整理${subject}失败：${error}` : `主模型整理${subject}失败，请查看后续消息或重试。`,
    };
  }
  if (status === 'completed') {
    return { tone: 'completed', text: `主模型已整理${subject}。` };
  }
  if (metadata.group_agent_summary_pending) {
    return { tone: 'pending', text: `等待主模型整理${subject}...` };
  }
  return null;
}

function groupAgentSummarySubject(metadata: ChatMessageMetadata) {
  const hasGroupDispatch = (
    metadata.group_dispatch_count !== undefined
    || metadata.group_dispatch_run_group_id
    || Array.isArray(metadata.group_dispatch_skipped)
  );
  return hasGroupDispatch ? '这一轮群组任务' : '这条 Agent 结果';
}

function groupFollowupNotice(message: ChatMessage): string {
  if (message.role !== 'user') return '';
  const metadata = message.metadata || {};
  const taskCount = Array.isArray(metadata.group_followup_for_task_ids)
    ? metadata.group_followup_for_task_ids.filter(Boolean).length
    : 0;
  const agentMessageCount = Array.isArray(metadata.group_followup_for_agent_message_ids)
    ? metadata.group_followup_for_agent_message_ids.filter(Boolean).length
    : 0;
  if (!taskCount && !agentMessageCount) return '';
  if (agentMessageCount && !taskCount) return '已作为当前 Agent 汇总补充';
  return '已作为当前群组任务补充';
}

function latestGroupAgentSummaryNotice(messages: ChatMessage[]) {
  let pendingNotice: { tone: 'pending' | 'failed'; text: string } | null = null;
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const notice = groupAgentSummaryNotice(messages[index]);
    if (!notice) continue;
    if (notice.tone === 'completed') continue;
    if (notice.tone === 'failed') return notice;
    if (notice.tone === 'pending') pendingNotice ||= { tone: 'pending', text: notice.text };
  }
  return pendingNotice;
}

function normalizeRunStatus(status?: string) {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

function runnableResultRunId(result: { run_id?: string; agent_run_id?: string; workflow_run_id?: string }) {
  return String(result.run_id || result.agent_run_id || result.workflow_run_id || '').trim();
}

function runnableResultStatus(result: { run_status?: string; status?: string }) {
  return normalizeRunStatus(result.run_status || result.status || '');
}

function messageRunStatus(message?: ChatMessage | null) {
  return normalizeRunStatus(message?.metadata?.run_status || message?.metadata?.workflow_status || '');
}

function messageRunId(message?: ChatMessage | null) {
  return String(message?.metadata?.run_id || message?.metadata?.workflow_run_id || '').trim();
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

function latestApprovalRequiredMessage(messages: ChatMessage[]) {
  const approvals = approvalRequiredMessages(messages);
  return approvals[approvals.length - 1] || null;
}

function approvalRequiredMessages(messages: ChatMessage[]) {
  return messages.filter((message) => (
    hasActionableApproval(message)
    && Boolean(message.id)
  ));
}

function approvalRequiredItems(
  messages: ChatMessage[],
  resolvedItemIds: string[] = [],
  runApprovalOverrides: Record<string, RunApprovalDetailOverride> = {},
): ComposerApprovalItem[] {
  const resolved = new Set(resolvedItemIds);
  const messageApprovals = approvalRequiredMessages(messages).map((message) => ({
    id: `message:${message.id || ''}:${messageApprovalSignature(message)}`,
    messageId: message.id,
    runId: messageRunId(message),
    createdAt: message.created_at,
    details: approvalRequestDetails(message),
    source: 'message' as const,
  })).filter((item) => item.id && item.runId && !resolved.has(item.id));
  const messageRunIds = new Set(messageApprovals.map((item) => item.runId));
  const seenActivityRunIds = new Set<string>();
  const activityApprovals: ComposerApprovalItem[] = [];

  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex];
    for (const event of message.activity_events || []) {
      const runId = activityRunId(event);
      if (!runId || messageRunIds.has(runId) || seenActivityRunIds.has(runId)) continue;
      const override = runApprovalOverrides[runId];
      if (!hasActionableActivityApproval(event) && !override) continue;
      seenActivityRunIds.add(runId);
      const eventId = String(event.event_id || `${message.id || messageIndex}:${runId}`);
      const signature = override?.signature || activityApprovalSignature(event);
      const itemId = `activity:${eventId}:${signature}`;
      if (resolved.has(itemId)) continue;
      activityApprovals.push({
        id: itemId,
        messageId: message.id,
        runId,
        createdAt: override?.createdAt || event.created_at || message.created_at,
        details: override?.details || approvalRequestDetailsFromActivity(event),
        source: 'activity',
      });
    }
  }

  const knownApprovalRunIds = new Set([
    ...messageRunIds,
    ...activityApprovals.map((item) => item.runId),
  ]);
  const workflowChildApprovals: ComposerApprovalItem[] = [];
  const seenWorkflowChildRunIds = new Set<string>();
  for (let messageIndex = messages.length - 1; messageIndex >= 0; messageIndex -= 1) {
    const message = messages[messageIndex];
    const runId = workflowWaitingChildApprovalRunId(message);
    if (!runId || knownApprovalRunIds.has(runId) || seenWorkflowChildRunIds.has(runId)) continue;
    seenWorkflowChildRunIds.add(runId);
    const signature = workflowWaitingChildApprovalSignature(message);
    const itemId = `workflow-child:${message.id || messageIndex}:${signature}`;
    if (resolved.has(itemId)) continue;
    workflowChildApprovals.push({
      id: itemId,
      messageId: message.id,
      runId,
      createdAt: message.created_at,
      details: approvalRequestDetailsFromWorkflowWaitingChild(message),
      source: 'workflow-child',
    });
  }

  return [...messageApprovals, ...activityApprovals, ...workflowChildApprovals].sort((a, b) => (
    approvalItemTime(a) - approvalItemTime(b)
  ));
}

function hasActionableApproval(message?: ChatMessage | null) {
  const pending = message?.metadata?.pending_approval;
  return (
    messageRunStatus(message) === 'approval_required'
    && Boolean(messageRunId(message))
    && Boolean(pending && typeof pending === 'object' && String(pending.tool || '').trim())
  );
}

function hasActionableActivityApproval(event?: ChatActivityEvent | null) {
  const pending = event?.metadata?.pending_approval;
  return (
    (event?.status === 'approval_required' || String(event?.metadata?.run_status || '').trim() === 'approval_required')
    && Boolean(activityRunId(event))
    && Boolean(pending && typeof pending === 'object' && String(pending.tool || '').trim())
  );
}

function workflowWaitingChildApprovalRunId(message?: ChatMessage | null) {
  const metadata = message?.metadata || {};
  const runId = stringValue(metadata.workflow_waiting_child_run_id);
  if (!runId) return '';
  const tool = stringValue(metadata.workflow_waiting_tool);
  if (!tool) return '';
  const status = messageRunStatus(message);
  const workflowStatus = normalizeRunStatus(metadata.workflow_status);
  if (status !== 'processing' && workflowStatus !== 'approval_required') return '';
  return runId;
}

function approvalItemTime(item: ComposerApprovalItem) {
  const value = item.createdAt ? new Date(item.createdAt).getTime() : 0;
  return Number.isFinite(value) ? value : 0;
}

function isRetryableMessage(message: ChatMessage, messages: ChatMessage[]) {
  if (message.status !== 'failed' || !message.id) return false;
  if (message.role === 'assistant') return true;
  if (message.role !== 'user') return false;
  if (!message.task_id) return true;
  return !messages.some((candidate) => (
    candidate.role === 'assistant'
    && candidate.task_id === message.task_id
  ));
}

function compactStatusText(text: string, maxLength = 96) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '任务执行失败';
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 3)}...` : normalized;
}

function chatStatusLabel(processing: boolean, failed: ChatMessage | null, messages: ChatMessage[], processingCount = 0) {
  const summaryNotice = latestGroupAgentSummaryNotice(messages);
  if (processing) {
    const approval = latestApprovalRequiredMessage(messages);
    if (approval) return nextApprovalStatusText({ pending_approval: approval.metadata?.pending_approval });
    if (summaryNotice?.tone === 'pending') return summaryNotice.text;
    const latest = latestVisibleActivity(messages);
    const countLabel = processingCount > 1 ? `${processingCount} 项 · ` : '';
    return `${countLabel}${compactStatusText(activityLabel(latest) || '处理中...')}`;
  }
  if (summaryNotice?.tone === 'failed') return summaryNotice.text;
  if (failed) return `处理失败：${compactStatusText(messageErrorText(failed))}`;
  return '就绪';
}

function isImeComposing(event: ReactKeyboardEvent<HTMLElement>, fallback = false) {
  const nativeEvent = event.nativeEvent as KeyboardEvent & { isComposing?: boolean };
  return Boolean(fallback || nativeEvent.isComposing || nativeEvent.keyCode === 229);
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

function mentionQueryAtEnd(value: string): string | null {
  const match = String(value || '').match(/(^|[\s，。！？、；;,.!?])@([^\s@，。！？、；;,.!?]*)$/);
  return match ? match[2] : null;
}

function mentionOptionsForQuery(
  runnables: RunnableSummary[],
  query: string | null,
  assistantProfile: AssistantProfilePayload | null,
  context?: ChatSessionContext | null,
): MentionOption[] {
  if (query === null) return [];
  const needle = query.trim().toLowerCase();
  const normalized = normalizeSessionContext(context);
  let scopedRunnables = runnables;
  if (normalized.conversation_kind === 'group') {
    const groupAgentIds = new Set(
      (normalized.participants || [])
        .filter((participant) => participant.kind === 'agent')
        .map((participant) => participant.id)
        .filter(Boolean),
    );
    scopedRunnables = runnables.filter((item) => item.kind === 'agent' && groupAgentIds.has(item.id));
  }
  return allMentionOptions(scopedRunnables, assistantProfile)
    .filter((option) => {
      if (!needle) return true;
      return [
        option.name,
        option.nickname,
        option.kind === 'main' ? 'main model' : '',
        option.kind,
      ].some((value) => String(value || '').toLowerCase().includes(needle));
    })
    .slice(0, 7);
}

function allMentionOptions(
  runnables: RunnableSummary[],
  assistantProfile: AssistantProfilePayload | null,
): MentionOption[] {
  const main: MentionOption = {
    id: 'main',
    name: '主模型',
    nickname: assistantProfile?.agent_nickname || '八千代',
    avatar_url: assistantProfile?.agent_avatar_url,
    kind: 'main',
  };
  const options: MentionOption[] = [
    main,
    ...runnables
      .filter((item) => item.kind === 'agent')
      .map((item) => ({
        id: item.id,
        name: item.name,
        nickname: item.nickname,
        avatar_url: item.avatar_url,
        kind: item.kind,
        participants: (item.participants || []).map((participant) => ({
          id: participant.id,
          name: participant.name,
          nickname: participant.nickname,
          avatar_url: participant.avatar_url,
          kind: participant.kind,
        })),
      })),
  ];
  return options;
}

function mentionKindLabel(option: MentionOption) {
  if (option.kind === 'main') return '主模型';
  if (option.kind === 'workflow') {
    const count = option.participants?.length || 0;
    return count ? `Workflow · ${count} Agents` : 'Workflow';
  }
  return 'Agent';
}

function mentionTextForOption(option: MentionOption) {
  if (option.kind === 'main') return '@主模型 ';
  const name = option.nickname || option.name;
  if (/\s/.test(name)) return `@"${name.replace(/"/g, '\\"')}" `;
  return `@${name} `;
}

function replaceTrailingMentionQuery(value: string, mentionText: string) {
  const match = String(value || '').match(/(^|[\s\S]*[\s，。！？、；;,.!?])@([^\s@，。！？、；;,.!?]*)$/);
  if (match) return `${match[1]}${mentionText}`;
  const spacer = value && !/[\s，。！？、；;,.!?]$/.test(value) ? ' ' : '';
  return `${value}${spacer}${mentionText}`;
}

function activeMentions(
  input: string,
  runnables: RunnableSummary[],
  assistantProfile: AssistantProfilePayload | null,
): MentionOption[] {
  const options = allMentionOptions(runnables, assistantProfile);
  const seen = new Set<string>();
  const result: MentionOption[] = [];
  const mentionRe = /@(?:"([^"]+)"|'([^']+)'|([^\s@，。！？、；;,.!?]+))/g;
  let match: RegExpExecArray | null;
  while ((match = mentionRe.exec(input)) !== null) {
    const label = String(match[1] || match[2] || match[3] || '').toLowerCase();
    const option = options.find((candidate) => [
      candidate.name,
      candidate.nickname,
      candidate.kind === 'main' ? '主模型' : '',
      candidate.kind === 'main' ? 'main' : '',
    ].some((value) => String(value || '').toLowerCase() === label));
    if (!option) continue;
    const key = `${option.kind}-${option.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(option);
  }
  return result;
}

function normalizeSessionContext(context?: ChatSessionContext | null): ChatSessionContext {
  const kind = context?.conversation_kind || 'main';
  return {
    conversation_kind: kind,
    runnable_id: context?.runnable_id || '',
    runnable_name: context?.runnable_name || '',
    run_group_id: context?.run_group_id || '',
    avatar_url: context?.avatar_url || '',
    participants: Array.isArray(context?.participants) ? context?.participants : [],
  };
}

function groupMemberCount(context?: ChatSessionContext | null) {
  const normalized = normalizeSessionContext(context);
  return (normalized.participants || []).filter((participant) => (
    participant.kind || participant.id || participant.name || participant.nickname
  )).length;
}

function isUnassignedSession(session?: SessionItem | null) {
  if (!session) return false;
  return (
    (session.conversation_kind || 'main') === 'main'
    && !session.runnable_id
    && Number(session.message_count || 0) === 0
  );
}

function contextFromSession(session?: SessionItem | null): ChatSessionContext {
  if (!session) return normalizeSessionContext(null);
  return normalizeSessionContext({
    conversation_kind: session.conversation_kind || 'main',
    runnable_id: session.runnable_id || '',
    runnable_name: session.runnable_name || '',
    run_group_id: session.run_group_id || '',
    avatar_url: session.avatar_url || '',
    participants: session.participants || [],
  });
}

function primaryParticipant(context?: ChatSessionContext | null): ChatParticipant | null {
  const normalized = normalizeSessionContext(context);
  return normalized.participants?.[0] || null;
}

function participantDisplayName(participant?: ChatParticipant | null) {
  return String(participant?.nickname || participant?.name || participant?.id || '').trim();
}

function participantInitial(participant?: ChatParticipant | null, fallback = '月') {
  const label = participantDisplayName(participant);
  return Array.from(label || fallback)[0] || fallback;
}

function participantAvatarContent(participant: ChatParticipant | null | undefined, fallback = '月') {
  const label = participantDisplayName(participant) || fallback;
  const url = participant?.avatar_url;
  return avatarNode(url, label, participantInitial(participant, fallback));
}

function AvatarStack({ participants }: { participants: ChatParticipant[] }) {
  const visible = participants.slice(0, 3);
  if (!visible.length) return <>{'W'}</>;
  return (
    <span className="chat-avatar-stack-inner" aria-hidden="true">
      {visible.map((participant, index) => (
        <span className="chat-avatar-stack-face" key={participant.id || participant.name || index}>
          {participantAvatarContent(participant, 'A')}
        </span>
      ))}
    </span>
  );
}

function SessionAvatar({ assistantProfile, context, loading, size, runnables }: {
  assistantProfile: AssistantProfilePayload | null;
  context?: ChatSessionContext | null;
  loading?: boolean;
  size: 'small' | 'header';
  runnables?: RunnableSummary[];
}) {
  const normalized = normalizeSessionContext(context);
  const className = size === 'header' ? 'chat-header-avatar' : 'chat-item-avatar';
  if (normalized.conversation_kind === 'unassigned') {
    return (
      <span className={`${className} chat-neutral-avatar`} title="新对话">
        <UiIcon name="chat" />
      </span>
    );
  }
  if (normalized.conversation_kind === 'workflow' || normalized.conversation_kind === 'group') {
    if (normalized.conversation_kind === 'group' && normalized.avatar_url) {
      const name = normalized.runnable_name || '群组';
      return (
        <span className={`${className} chat-group-custom-avatar`} title={name}>
          {avatarNode(normalized.avatar_url, name, '群', loading)}
        </span>
      );
    }
    // 从 runnables 中获取最新的参与者信息
    const runnable = runnables?.find((r) => r.id === normalized.runnable_id);
    const participants = runnable?.participants || normalized.participants || [];
    return (
      <span className={`${className} chat-avatar-stack`} title={runnable?.name || normalized.runnable_name || '群组'}>
        <AvatarStack participants={participants.map((p) => ({
          kind: p.kind,
          id: p.id,
          name: p.name || p.nickname || '',
          nickname: p.nickname,
          avatar_url: p.avatar_url,
        }))} />
      </span>
    );
  }
  if (normalized.conversation_kind === 'agent') {
    // 从 runnables 中获取最新的 Agent 信息
    const runnable = runnables?.find((r) => r.id === normalized.runnable_id);
    const participant = primaryParticipant(normalized);
    // 如果找到了 runnable，使用它的头像（即使为空），否则使用会话中的旧头像
    const avatarUrl = runnable ? runnable.avatar_url : participant?.avatar_url;
    const name = runnable?.nickname || runnable?.name || participantDisplayName(participant) || normalized.runnable_name || 'Agent';
    return (
      <span className={`${className} chat-agent-avatar`} title={name}>
        {agentAvatarNode(avatarUrl, name)}
      </span>
    );
  }
  return (
    <span className={className}>
      {avatarNode(assistantProfile?.agent_avatar_url, assistantProfile?.agent_name || 'Yachiyo', '月', loading)}
    </span>
  );
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

// Agent Studio 风格的首字母获取函数
function agentInitial(name: string): string {
  const clean = (name || '').trim();
  return clean ? clean.slice(0, 1).toUpperCase() : 'A';
}

function messageAvatar(message: ChatMessage, profile: AssistantProfilePayload | null, profileLoading = false, runnables: RunnableSummary[] = []) {
  const role = message.role || 'system';
  if (role === 'user') return avatarNode(profile?.user_avatar_url, '你', '你', profileLoading);
  if (role === 'assistant') {
    const sender = message.metadata?.sender;
    if (sender?.kind === 'workflow') {
      // 从 runnables 中获取最新的参与者信息
      const runnable = runnables.find((r) => r.id === sender.id);
      const participants = runnable?.participants || sender.participants || [];
      return <AvatarStack participants={participants.map((p) => ({
        kind: p.kind,
        id: p.id,
        name: p.name || p.nickname || '',
        nickname: p.nickname,
        avatar_url: p.avatar_url,
      }))} />;
    }
    if (sender?.kind === 'agent') {
      // 从 runnables 中获取最新的 Agent 信息
      const runnable = runnables.find((r) => r.id === sender.id);
      // 如果找到了 runnable，使用它的信息，否则使用消息中的旧信息
      const avatarUrl = runnable ? runnable.avatar_url : sender.avatar_url;
      const name = runnable?.nickname || runnable?.name || participantDisplayName(sender) || 'Agent';
      // 使用 Agent Studio 风格的头像
      return agentAvatarNode(avatarUrl, name);
    }
    return avatarNode(profile?.agent_avatar_url, profile?.agent_name || 'Yachiyo', '月', profileLoading);
  }
  return 'i';
}

// Agent Studio 风格的头像节点
function agentAvatarNode(avatarUrl: string | undefined, name: string) {
  if (avatarUrl) {
    return (
      <span className="agent-avatar has-image" aria-hidden="true">
        <img src={avatarUrl} alt="" />
      </span>
    );
  }
  return (
    <span className="agent-avatar" aria-hidden="true">
      {agentInitial(name)}
    </span>
  );
}

function messageRoleLabel(message: ChatMessage) {
  const role = message.role || 'system';
  if (role === 'user') return '你';
  if (role === 'assistant') {
    const sender = message.metadata?.sender;
    if (sender?.kind === 'agent' || sender?.kind === 'workflow') {
      return participantDisplayName(sender) || 'Agent';
    }
    return 'Yachiyo';
  }
  return '系统';
}

function messageMetaText(message: ChatMessage, status?: string, createdAt?: string) {
  const runStatus = messageRunStatus(message);
  const hasRunContext = Boolean(messageRunId(message) || message.metadata?.runnable_kind === 'agent' || message.metadata?.runnable_kind === 'workflow');
  const statusText = status === 'pending'
    ? ' · 等待中'
    : runStatus === 'approval_required'
      ? ' · 等待审批'
      : status === 'processing'
        ? hasRunContext ? ' · 处理中' : ' · 输入中'
      : status === 'failed'
        ? ' · 失败'
        : '';
  const timeText = formatShortTime(createdAt);
  return `${messageRoleLabel(message)}${timeText !== '—' ? ` · ${timeText}` : ''}${statusText}`;
}

function executorLabel(executor: ExecutorPayload | null) {
  if (!executor?.available) return '未就绪';
  return executor.executor === 'HermesExecutor' ? 'Hermes' : '不可用';
}

function canAttachImages(executor: ExecutorPayload | null) {
  return executor?.available === true && executor.image_input?.can_attach_images === true;
}

function imageInputUnavailableText(executor: ExecutorPayload | null) {
  return executor?.image_input?.reason
    || '当前 Yachiyo vision 链路不可用。请在主控台切换支持图片的主模型，或单独设置图片识别模型后再发送。';
}

function attachmentHelpText(executor: ExecutorPayload | null) {
  const imageInput = executor?.image_input;
  if (!imageInput) return '添加附件（当前仅支持图片）';
  if (imageInput.reason) return `附件不可用：${imageInput.reason}`;
  return `${imageInput.label || '添加图片附件'}（当前仅支持图片）`;
}

function conversationDisplayName(
  session: SessionItem | undefined,
  context: ChatSessionContext,
  assistantProfile: AssistantProfilePayload | null,
  messages: ChatMessage[],
) {
  const normalized = normalizeSessionContext(context);
  if (normalized.conversation_kind === 'agent') {
    return normalized.runnable_name || participantDisplayName(primaryParticipant(normalized)) || 'Agent';
  }
  if (normalized.conversation_kind === 'workflow') {
    return normalized.runnable_name || 'Workflow 群组';
  }
  if (normalized.conversation_kind === 'group') {
    return normalized.runnable_name || '群组';
  }
  if (normalized.conversation_kind === 'unassigned') {
    return '新对话';
  }
  if (session) return sessionTitle(session);
  return firstUserMessageTitle(messages) || assistantProfile?.agent_name || '月見八千代';
}

function sessionDisplayName(session: SessionItem, assistantProfile: AssistantProfilePayload | null) {
  const context = contextFromSession(session);
  if (context.conversation_kind === 'agent') {
    // 优先使用会话标题（如果已总结），否则使用 Agent 名称
    const title = sessionTitle(session);
    if (title && title !== '新对话') return title;
    return session.runnable_name || participantDisplayName(primaryParticipant(context)) || 'Agent';
  }
  if (context.conversation_kind === 'workflow') {
    // 优先使用会话标题（如果已总结），否则使用 Workflow 名称
    const title = sessionTitle(session);
    if (title && title !== '新对话') return title;
    return session.runnable_name || 'Workflow 群组';
  }
  if (context.conversation_kind === 'group') {
    const title = sessionTitle(session);
    if (title && title !== '新对话') return title;
    return session.runnable_name || '群组';
  }
  return sessionTitle(session) || assistantProfile?.agent_name || '新对话';
}

function sessionKindLabel(session: SessionItem) {
  const context = contextFromSession(session);
  if (context.conversation_kind === 'agent') return 'Agent';
  if (context.conversation_kind === 'workflow') {
    const count = context.participants?.length || 0;
    return count ? `Workflow · ${count} Agents` : 'Workflow';
  }
  if (context.conversation_kind === 'group') {
    const count = groupMemberCount(context);
    return count ? `群组 · ${count} 成员` : '群组';
  }
  return '';
}

function groupDefaultName(
  agentRunnables: RunnableSummary[],
  selectedAgentIds: string[],
  assistantProfile: AssistantProfilePayload | null,
) {
  const names = [
    assistantProfile?.agent_nickname || assistantProfile?.agent_name || '主模型',
    ...selectedAgentIds
      .map((agentId) => agentRunnables.find((agent) => agent.id === agentId))
      .map((agent) => agent?.nickname || agent?.name || '')
      .filter(Boolean),
  ];
  return names.join('、');
}

function deleteTargetLabel(context: ChatSessionContext) {
  const kind = normalizeSessionContext(context).conversation_kind;
  return kind === 'group' || kind === 'workflow' ? '群组' : '对话';
}

function headerStatusText(
  isProcessing: boolean,
  headerActivity: ChatActivityEvent | null,
  status: string,
  executor: ExecutorPayload | null,
  context: ChatSessionContext,
) {
  const base = isProcessing
    ? (
      status.includes('等待审批')
        ? status
        : headerActivity
          ? `处理中 · ${compactStatusText(activityLabel(headerActivity))}`
          : '处理中'
    )
    : status;
  const normalized = normalizeSessionContext(context);
  if (normalized.conversation_kind === 'agent') return `${base} · Agent`;
  if (normalized.conversation_kind === 'workflow') {
    const count = normalized.participants?.length || 0;
    return count ? `${base} · Workflow 群组 · ${count} Agents` : `${base} · Workflow 群组`;
  }
  if (normalized.conversation_kind === 'group') {
    const count = groupMemberCount(normalized);
    return count ? `${base} · 群组 · ${count} 成员` : `${base} · 群组`;
  }
  if (normalized.conversation_kind === 'unassigned') return base;
  return `${base} · ${executorLabel(executor)}`;
}

function sessionTitle(session: SessionItem) {
  const title = stripLeadingMentions((session.title || '').trim());
  if (title && !looksLikeSessionIdTitle(title, session.session_id) && !looksLikeTitlePromptEcho(title)) return title;
  const preview = (session.latest_message_preview || '').trim();
  if (preview) return compactStatusText(preview, 36);
  return '新对话';
}

function sessionPreview(session: SessionItem) {
  if (session.search_match?.snippet) {
    const role = session.search_match.role === 'user'
      ? '你'
      : session.search_match.role === 'assistant'
        ? sessionDisplayName(session, null)
        : '消息';
    const count = session.search_match.match_count && session.search_match.match_count > 1
      ? ` · ${session.search_match.match_count} 处`
      : '';
    return `${role}：${compactStatusText(session.search_match.snippet, 56)}${count}`;
  }
  if (session.search_match?.kind === 'session') return session.search_match.snippet || '会话信息匹配';
  const preview = compactStatusText(session.latest_message_preview || sessionTitle(session), 48);
  const approvalCount = Number(session.approval_count || 0);
  if (approvalCount > 0) {
    const countLabel = approvalCount > 1 ? ` ${approvalCount} 项` : '';
    return `待审批${countLabel}：${preview || '需要确认工具调用'}`;
  }
  if (session.is_processing) {
    const processingCount = Number(session.processing_count || 0);
    const countLabel = processingCount > 1 ? ` ${processingCount} 项` : '';
    return `处理中${countLabel}：${preview || '正在处理'}`;
  }
  if (session.latest_message_status === 'failed') return `处理失败：${preview || '任务执行失败'}`;
  if (session.conversation_kind === 'workflow') {
    const names = (session.participants || []).map((participant) => participantDisplayName(participant)).filter(Boolean).slice(0, 3);
    return names.length ? `${names.join(' / ')} · ${preview || '已创建'}` : `Workflow · ${preview || '已创建'}`;
  }
  if (session.conversation_kind === 'group') {
    const names = (session.participants || [])
      .filter((participant) => participant.kind === 'agent')
      .map((participant) => participantDisplayName(participant))
      .filter(Boolean)
      .slice(0, 3);
    return names.length ? `${names.join(' / ')} · ${preview || '已创建'}` : `群组 · ${preview || '已创建'}`;
  }
  if (session.message_count) return `已完成：${preview || sessionTitle(session)}`;
  if (!session.message_count) return session.conversation_kind === 'agent' ? '新的 Agent 对话' : '新对话';
  return preview;
}

function sessionSideLabel(session: SessionItem) {
  const approvalCount = Number(session.approval_count || 0);
  if (approvalCount > 0) return approvalCount > 1 ? `待审批 ${approvalCount}` : '待审批';
  return session.is_processing ? '处理中' : formatShortTime(session.updated_at || session.created_at);
}

function firstUserMessageTitle(messages: ChatMessage[]) {
  const firstUser = messages.find((message) => message.role === 'user' && messageText(message).trim());
  return firstUser ? compactStatusText(stripLeadingMentions(messageText(firstUser)), 36) : '';
}

function stripLeadingMentions(value: string) {
  let title = String(value || '').replace(/\s+/g, ' ').trim();
  const mentionRe = /^@(?:"[^"]+"|'[^']+'|“[^”]+”|‘[^’]+’|[^\s@:：，。！？、；;,.!?]+)[\s:：,，、;；-]*/;
  while (mentionRe.test(title)) {
    const next = title.replace(mentionRe, '').trim();
    if (next === title) break;
    title = next;
  }
  return title;
}

function looksLikeSessionIdTitle(title: string, sessionId: string) {
  const value = title.trim();
  return value === sessionId.slice(0, 8) || /^[a-f0-9]{8,32}$/i.test(value);
}

function looksLikeTitlePromptEcho(title: string) {
  const normalized = title.replace(/\s+/g, '');
  if (!normalized) return false;
  const markers = [
    '请为这段持续对话生成',
    '会话列表标题',
    '第一条用户消息',
    '最近对话',
    '当前标题',
    '只输出标题',
    '用户要求为这段',
    '要求包括',
  ];
  return markers.some((marker) => normalized.includes(marker)) || /^(首先用户要求|首先，用户要求|用户要求)/.test(normalized);
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

function activityRunId(event?: ChatActivityEvent | null) {
  return String(event?.metadata?.run_id || event?.metadata?.workflow_run_id || '').trim();
}

function activityStatusClass(status?: string) {
  if (status === 'completed' || status === 'success') return 'completed';
  if (status === 'failed' || status === 'error') return 'failed';
  if (status === 'approval_required') return 'approval';
  if (status === 'progress' || status === 'running') return 'running';
  return 'status';
}

function activityStatusIcon(status?: string) {
  if (status === 'completed' || status === 'success') return '✓';
  if (status === 'failed' || status === 'error') return '!';
  if (status === 'approval_required') return '!';
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
    const isApprovalRequired = messageRunStatus(message) === 'approval_required';
    const existing = states.get(message.id);
    if (!existing) {
      states.set(message.id, {
        shown: message.status === 'processing' && !isApprovalRequired ? '' : content,
        target: content,
      });
      continue;
    }
    if (isApprovalRequired) {
      existing.shown = content;
      existing.target = content;
      continue;
    }
    if (existing.target !== content) {
      if (message.status === 'processing' && existing.shown) {
        const shownContainsDispatchPayload = containsGroupDispatchPayload(existing.shown);
        if (!shownContainsDispatchPayload && (!content || content.length < existing.shown.length || !content.startsWith(existing.shown))) {
          existing.target = existing.shown;
          continue;
        }
      }
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

function containsGroupDispatchPayload(text: string) {
  const compact = text.toLowerCase().replace(/[\s_-]+/g, '');
  return (
    compact.includes('yachiyogroupdispatch')
    || compact.includes('dispatchgroupagent')
    || compact.includes('runyachiyoagent')
  );
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

function codeBlockStateKey(messageId: string, blockIndex: string) {
  return `${messageId || 'message'}:${blockIndex}`;
}

function renderMarkdown(text: string, messageId = '', copiedCodeBlockKey = '') {
  const source = String(text || '').replace(/\r\n/g, '\n');
  if (!source) return '';

  const lines = source.split('\n');
  let html = '';
  let paragraph: string[] = [];
  let listType: 'ul' | 'ol' | null = null;
  let inCode = false;
  let codeLines: string[] = [];
  let codeLanguage = '';
  let codeBlockIndex = 0;

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
    const code = codeLines.join('\n');
    const language = codeLanguage || detectCodeLanguage(code);
    const blockIndex = String(codeBlockIndex);
    const copied = copiedCodeBlockKey === codeBlockStateKey(messageId, blockIndex);
    const languageLabel = language ? `<span class="markdown-code-lang">${escapeHtml(language)}</span>` : '<span class="markdown-code-lang">text</span>';
    const copyButtonLabel = copied ? '已复制' : '复制代码';
    const copyButtonIcon = copied ? CODE_CHECK_ICON_HTML : CODE_COPY_ICON_HTML;
    html += `<div class="markdown-code-block" data-code-index="${blockIndex}">${languageLabel}<button type="button" class="markdown-code-copy${copied ? ' copied' : ''}" data-code-copy aria-label="${copyButtonLabel}" title="${copyButtonLabel}">${copyButtonIcon}</button><pre><code class="${language ? `language-${escapeHtml(language)}` : ''}">${renderHighlightedCode(code, language)}</code></pre></div>`;
    codeLines = [];
    codeLanguage = '';
    inCode = false;
    codeBlockIndex += 1;
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
        codeLanguage = normalizeFenceLanguage(line);
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

function normalizeFenceLanguage(fenceLine: string) {
  const raw = fenceLine.trim().slice(3).trim().split(/\s+/)[0] || '';
  return normalizeCodeLanguage(raw);
}

function normalizeCodeLanguage(language: string) {
  const value = String(language || '').trim().toLowerCase().replace(/[^a-z0-9+#.-]/g, '');
  const aliases: Record<string, string> = {
    cjs: 'javascript',
    js: 'javascript',
    jsx: 'javascript',
    mjs: 'javascript',
    node: 'javascript',
    ts: 'typescript',
    tsx: 'typescript',
    py: 'python',
    sh: 'bash',
    shell: 'bash',
    zsh: 'bash',
    yml: 'yaml',
  };
  return aliases[value] || value;
}

function detectCodeLanguage(code: string) {
  const trimmed = code.trim();
  if (!trimmed) return '';
  if ((trimmed.startsWith('{') || trimmed.startsWith('['))) {
    try {
      JSON.parse(trimmed);
      return 'json';
    } catch {
      // Keep looking for a better lightweight guess.
    }
  }
  if (/\bfunc\s+\w+\s*\(|\bpackage\s+main\b|:=/.test(trimmed)) return 'go';
  if (/\b(def|class|from|import)\s+\w+|__name__/.test(trimmed)) return 'python';
  if (/\b(const|let|var|function|interface|type)\s+\w+|=>/.test(trimmed)) return 'typescript';
  if (/^\s*(#!|npm\s|pnpm\s|yarn\s|curl\s|git\s)/m.test(trimmed)) return 'bash';
  if (/^\s*[\w.-]+\s*:\s+\S/m.test(trimmed)) return 'yaml';
  return '';
}

function renderHighlightedCode(code: string, language: string) {
  const normalizedLanguage = normalizeCodeLanguage(language) || detectCodeLanguage(code);
  const keywords = codeKeywordsForLanguage(normalizedLanguage);
  let html = '';
  let index = 0;

  while (index < code.length) {
    const char = code[index];
    const next = code[index + 1];

    if (char === '/' && next === '*') {
      const end = code.indexOf('*/', index + 2);
      const stop = end >= 0 ? end + 2 : code.length;
      html += syntaxSpan('comment', code.slice(index, stop));
      index = stop;
      continue;
    }

    if (char === '/' && next === '/') {
      const end = code.indexOf('\n', index + 2);
      const stop = end >= 0 ? end : code.length;
      html += syntaxSpan('comment', code.slice(index, stop));
      index = stop;
      continue;
    }

    if (char === '#' && (normalizedLanguage === 'python' || normalizedLanguage === 'bash' || normalizedLanguage === 'yaml')) {
      const end = code.indexOf('\n', index + 1);
      const stop = end >= 0 ? end : code.length;
      html += syntaxSpan('comment', code.slice(index, stop));
      index = stop;
      continue;
    }

    if (char === '"' || char === "'" || char === '`') {
      const stop = quotedStringEnd(code, index, char);
      const token = code.slice(index, stop);
      const after = nextNonWhitespaceIndex(code, stop);
      const className = code[after] === ':' ? 'property' : 'string';
      html += syntaxSpan(className, token);
      index = stop;
      continue;
    }

    const numberMatch = code.slice(index).match(/^(?:0x[\da-fA-F]+|\d+(?:\.\d+)?(?:e[+-]?\d+)?)/);
    if (numberMatch) {
      html += syntaxSpan('number', numberMatch[0]);
      index += numberMatch[0].length;
      continue;
    }

    const identifierMatch = code.slice(index).match(/^[A-Za-z_$][\w$]*/);
    if (identifierMatch) {
      const word = identifierMatch[0];
      const after = nextNonWhitespaceIndex(code, index + word.length);
      if (keywords.has(word)) {
        html += syntaxSpan('keyword', word);
      } else if (code[after] === '(') {
        html += syntaxSpan('function', word);
      } else {
        html += escapeHtml(word);
      }
      index += word.length;
      continue;
    }

    if (/[\[\]{}().,:;]/.test(char)) {
      html += syntaxSpan('punctuation', char);
      index += 1;
      continue;
    }

    html += escapeHtml(char);
    index += 1;
  }

  return html;
}

function codeKeywordsForLanguage(language: string) {
  const common = ['false', 'null', 'true'];
  const byLanguage: Record<string, string[]> = {
    bash: ['case', 'do', 'done', 'elif', 'else', 'esac', 'export', 'fi', 'for', 'function', 'if', 'in', 'local', 'then', 'while'],
    go: ['break', 'case', 'chan', 'const', 'continue', 'defer', 'default', 'else', 'fallthrough', 'for', 'func', 'go', 'if', 'import', 'interface', 'map', 'nil', 'package', 'range', 'return', 'select', 'struct', 'switch', 'type', 'var'],
    javascript: ['async', 'await', 'break', 'case', 'catch', 'class', 'const', 'continue', 'default', 'else', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'import', 'let', 'new', 'return', 'switch', 'this', 'throw', 'try', 'typeof', 'var', 'while'],
    json: common,
    python: ['and', 'as', 'async', 'await', 'break', 'class', 'continue', 'def', 'elif', 'else', 'except', 'False', 'finally', 'for', 'from', 'if', 'import', 'in', 'is', 'None', 'not', 'or', 'pass', 'return', 'True', 'try', 'while', 'with', 'yield'],
    typescript: ['async', 'await', 'break', 'case', 'catch', 'class', 'const', 'continue', 'default', 'else', 'export', 'extends', 'finally', 'for', 'from', 'function', 'if', 'implements', 'import', 'interface', 'let', 'new', 'private', 'protected', 'public', 'readonly', 'return', 'switch', 'this', 'throw', 'try', 'type', 'typeof', 'var', 'while'],
    yaml: ['false', 'null', 'true'],
  };
  return new Set([...(byLanguage[language] || []), ...common]);
}

function quotedStringEnd(code: string, start: number, quote: string) {
  let index = start + 1;
  while (index < code.length) {
    const char = code[index];
    if (char === '\\') {
      index += 2;
      continue;
    }
    if (char === quote) return index + 1;
    index += 1;
  }
  return code.length;
}

function nextNonWhitespaceIndex(code: string, start: number) {
  let index = start;
  while (index < code.length && /\s/.test(code[index])) index += 1;
  return index;
}

function syntaxSpan(kind: string, value: string) {
  return `<span class="syntax-${kind}">${escapeHtml(value)}</span>`;
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
  value = renderMentionTokens(value);
  codes.forEach((code, index) => {
    value = value.replace(`\u0000CODE${index}\u0000`, code);
  });
  return value;
}

function renderMentionTokens(value: string) {
  return value.replace(
    /(^|[\s，。！？、；;,.!?])@(&quot;[^&]+&quot;|'[^']+'|[A-Za-z0-9_\-\u4e00-\u9fff.]+)/g,
    (_match, prefix: string, mention: string) => `${prefix}<span class="mention-token">@${mention}</span>`,
  );
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
