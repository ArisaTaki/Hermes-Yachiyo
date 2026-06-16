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
import {
  clipboardImageFiles,
  fileFromDesktopImageSelection,
  fileFromE2EImageDetail,
  MAX_ATTACHMENT_BYTES,
  readPendingAttachment,
  withResolvedAttachmentUrls,
} from '../features/yachiyo-chat/attachments';
import { createDelegatedRunSummary } from '../features/yachiyo-chat/delegatedSummary';
import {
  ComposerApprovalNotice,
  composerApprovalStatusText,
} from '../features/yachiyo-chat/components/ComposerApprovalNotice';
import { ChatGroupDialog } from '../features/yachiyo-chat/components/ChatGroupDialog';
import { SessionIdDialog } from '../features/yachiyo-chat/components/SessionIdDialog';
import { AgentRunProgressCard } from '../features/yachiyo-chat/components/AgentRunProgressCard';
import { MessageAgentTaskCard } from '../features/yachiyo-chat/components/MessageAgentTaskCard';
import {
  MessageApprovalRequestCard,
  type ApprovalRequestDetails,
} from '../features/yachiyo-chat/components/MessageApprovalRequestCard';
import { MessageActivityList } from '../features/yachiyo-chat/components/MessageActivityList';
import {
  approvalIdFromPending,
  approvalRequestDetails,
  approvalRequiredItems,
  approvalRequiredMessages,
  forgetRunApprovalOverride,
  hasActionableApproval,
  isWorkflowApprovalDetails,
  rememberRunApprovalOverride,
  messageApprovalSignature,
  nextApprovalStatusText,
  type ChatApprovalRun,
  type ComposerApprovalItem,
  type RunApprovalDetailOverride,
} from '../features/yachiyo-chat/approvalItems';
import {
  activityLabel,
  activityRunId,
  chatStatusLabel,
  compactStatusText,
  groupAgentSummaryNotice,
  groupFollowupNotice,
  latestFailedMessage,
  latestVisibleActivity,
  messageErrorText,
  messageRunId,
  messageRunStatus,
  messageText,
  normalizeRunStatus,
  runnableResultRunId,
  runnableResultStatus,
} from '../features/yachiyo-chat/messageState';
import {
  chatApprovalRejectionCompletionStatusText,
  chatRunCompletionProcessingState,
} from '../features/yachiyo-chat/runPolling';
import { groupRunIdFromStudioUrl } from '../features/runtime-shared/studioLinks';
import {
  activeMentions,
  mentionKindLabel,
  mentionOptionsForQuery,
  mentionQueryAtEnd,
  mentionTextForOption,
  replaceTrailingMentionQuery,
  yachiyoPublicTaskPrompt,
  yachiyoPublicTaskTarget,
  type MentionOption,
} from '../features/yachiyo-chat/mentions';
import { codeBlockStateKey, fencedCode, renderMarkdown } from '../features/yachiyo-chat/markdown';
import {
  contextFromSession,
  conversationDisplayName,
  deleteTargetLabel,
  groupDefaultName,
  groupMemberCount,
  isUnassignedSession,
  normalizeSessionContext,
  participantDisplayName,
  participantInitial,
  primaryParticipant,
  sessionDisplayName,
  sessionKindLabel,
  sessionPreview,
} from '../features/yachiyo-chat/sessionState';
import { useYachiyoTaskActions } from '../features/yachiyo-chat/hooks/useYachiyoTaskActions';
import { useChatRunPolling } from '../features/yachiyo-chat/hooks/useChatRunPolling';
import { useYachiyoTaskSnapshots } from '../features/yachiyo-chat/hooks/useYachiyoTaskSnapshots';
import { useYachiyoTaskSubmit } from '../features/yachiyo-chat/hooks/useYachiyoTaskSubmit';
import { approveChatRunApproval, rejectChatRunApproval } from '../features/yachiyo-chat/runSnapshots';
import { listYachiyoChatRunnables, type ChatRunnableSummary as RunnableSummary } from '../features/yachiyo-chat/runnables';
import { publicTaskSnapshotForMessage } from '../features/yachiyo-chat/taskSnapshots';
import type {
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  AssistantProfilePayload,
  ChatActivityEvent,
  ChatE2EImageDetail,
  ChatMessage,
  ChatNotice,
  ChatParticipant,
  ChatSessionContext,
  ExecutorPayload,
  MessagesPayload,
  PendingAttachment,
  RenderState,
  SessionItem,
  SessionsPayload,
} from '../features/yachiyo-chat/types';
import logoUrl from '../../../../docs/open-design/logo.png';
import { type AssistantProfileSeed, useAssistantProfileSeed } from '../lib/assistantProfileSeed';
import { apiGet, apiPatch, apiPost, bridgeUrl, canChooseChatImages, chooseChatImages, copyText, openAppView, openExternalUrl, restartDesktopBridge, type ChatImageSelection } from '../lib/bridge';
import { ROUTE_CHANGE_EVENT, currentParam, navigateTo } from '../lib/view';

function metadataListAttribute(value: unknown): string {
  if (!Array.isArray(value)) return '';
  return value.map((item) => String(item || '').trim()).filter(Boolean).join(',');
}

type ChatViewProps = {
  embedded?: boolean;
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
const MIN_LOADING_MS = 1400;
const CHAT_SIDEBAR_MIN_WIDTH = 220;
const CHAT_SIDEBAR_BASE_MAX_WIDTH = 280;
const CHAT_SIDEBAR_WIDE_MAX_WIDTH = 360;
const CHAT_WIDE_VIEWPORT_WIDTH = 1500;
const COMPOSER_MIN_HEIGHT = 48;
const COMPOSER_MAX_HEIGHT = 260;
const COMPOSER_HEIGHT_STORAGE_KEY = 'oha.chat.composerHeight';
const ASSISTANT_PROFILE_UPDATED_EVENT = 'oha-assistant-profile-updated';
const CHAT_E2E_ADD_IMAGE_EVENT = 'oha-chat-e2e-add-image';

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
  const [conversationTokenCount, setConversationTokenCount] = useState(0);
  const [executor, setExecutor] = useState<ExecutorPayload | null>(null);
  const [assistantProfile, setAssistantProfile] = useState<AssistantProfilePayload | null>(() => cachedAssistantProfile || profileFromSeed(assistantProfileSeed));
  const [assistantProfileLoading, setAssistantProfileLoading] = useState(() => !(cachedAssistantProfile || profileFromSeed(assistantProfileSeed)));
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const [sessionQuery, setSessionQuery] = useState('');
  const [debouncedSessionQuery, setDebouncedSessionQuery] = useState('');
  const [routeSessionId, setRouteSessionId] = useState(() => currentParam('session_id').trim());
  const [routeTaskId, setRouteTaskId] = useState(() => currentParam('task_id').trim());
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
  const {
    agentTaskSnapshotsById,
    rememberYachiyoTasks,
    refreshYachiyoTaskById,
    refreshYachiyoTasksForSession,
    refreshYachiyoTaskSnapshotsForRunIds,
  } = useYachiyoTaskSnapshots();

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
      void refreshYachiyoTaskSnapshotsFromMessages(nextMessages);
      setConversationTokenCount(normalizedTokenCount(payload.token_count));
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
      if (!isMessageSelectionPaused() && shouldTriggerPendingReplyScroll(nextMessages)) {
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
      query.set('limit', '0');
      if (debouncedSessionQuery) query.set('query', debouncedSessionQuery);
      const payload = await apiGet<SessionsPayload>(`/ui/chat/sessions?${query.toString()}`);
      if (payload.ok === false) throw new Error('读取会话失败');
      setSessions(payload);
      if (payload.current_session_id) void refreshYachiyoTasksForSession(payload.current_session_id);
    } catch {
      setSessions(null);
    } finally {
      setSessionsLoaded(true);
    }
  }, [debouncedSessionQuery]);

  useEffect(() => {
    loadSessionsRef.current = loadSessions;
  }, [loadSessions]);

  function refreshYachiyoTaskSnapshotsFromMessages(nextMessages: ChatMessage[]) {
    refreshYachiyoTaskSnapshotsForRunIds(nextMessages.map(messageRunId));
  }

  const {
    pollAgentRunInBackground,
  } = useChatRunPolling({
    activePollIntervalMs: ACTIVE_POLL_INTERVAL_MS,
    createDelegatedRunSummaryOptions: delegatedRunSummaryOptions,
    forgetRunApprovalDetails,
    isProcessingRef,
    loadSessions,
    refreshMessages,
    rememberRunApprovalDetails,
    setIsProcessing,
    setProcessingCount,
    setStatus,
  });

  const {
    cancelYachiyoTaskFromCard,
    resolveYachiyoTaskApproval,
  } = useYachiyoTaskActions({
    approvalActionMessageId,
    focusComposerSoon,
    loadSessions,
    pollAgentRunInBackground,
    refreshMessages,
    rememberYachiyoTasks,
    setApprovalActionMessageId,
    setStatus,
  });
  const { startPublicYachiyoTask } = useYachiyoTaskSubmit({
    loadSessions,
    onAccepted: () => {
      transientEmptySessionIdRef.current = '';
      pendingReplyTaskIdRef.current = '';
    },
    onRunning: () => {
      stickToBottomRef.current = true;
    },
    onSettled: () => {
      pendingReplyScrollRef.current = false;
    },
    pollAgentRunInBackground,
    refreshMessages,
    rememberYachiyoTasks,
    setStatus,
  });

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
        const payload = await listYachiyoChatRunnables();
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
    const syncRouteChatHandoffParams = () => {
      setRouteSessionId(currentParam('session_id').trim());
      setRouteTaskId(currentParam('task_id').trim());
    };
    window.addEventListener('hashchange', syncRouteChatHandoffParams);
    window.addEventListener('popstate', syncRouteChatHandoffParams);
    window.addEventListener(ROUTE_CHANGE_EVENT, syncRouteChatHandoffParams);
    syncRouteChatHandoffParams();
    return () => {
      window.removeEventListener('hashchange', syncRouteChatHandoffParams);
      window.removeEventListener('popstate', syncRouteChatHandoffParams);
      window.removeEventListener(ROUTE_CHANGE_EVENT, syncRouteChatHandoffParams);
    };
  }, []);

  useEffect(() => {
    const requestedSessionId = routeSessionId;
    const requestedTaskId = routeTaskId;
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
      const [messagePayload] = await Promise.all([refreshMessages(), loadSessions()]);
      if (requestedTaskId && messagePayload?.messages) {
        const messageId = taskHandoffMessageId(messagePayload.messages, requestedTaskId);
        if (messageId) {
          revealMessage(messageId);
          setStatus('已定位到关联任务消息');
        }
      }
    })();
  }, [loadAssistantProfile, loadExecutor, loadSessions, refreshMessages, routeSessionId, routeTaskId]);

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
    window.addEventListener(ASSISTANT_PROFILE_UPDATED_EVENT, refreshProfile);
    return () => window.removeEventListener(ASSISTANT_PROFILE_UPDATED_EVENT, refreshProfile);
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
    const clientMessageId = createClientMessageId();
    try {
      const publicTaskTarget = outgoingAttachments.length === 0
        ? yachiyoPublicTaskTarget(text, runnables, assistantProfile)
        : null;
      if (publicTaskTarget) {
        const handled = await startPublicYachiyoTask({
          clientMessageId,
          conversationId: sessions?.current_session_id || latestChatSnapshotRef.current.currentSessionId || null,
          prompt: yachiyoPublicTaskPrompt(text, publicTaskTarget),
          runnableId: publicTaskTarget.id,
          runnableKind: publicTaskTarget.kind,
        });
        if (handled) {
          return;
        }
      }
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
        client_message_id: clientMessageId,
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
          void refreshYachiyoTaskById(resultRunId);
          await refreshMessages();
          pollAgentRunInBackground(resultRunId);
          return;
        }
        if (resultRunId) void refreshYachiyoTaskById(resultRunId);
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
    if (imageAttachDisabled) {
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
    if (isSending || !canAttachImages(executor)) {
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

  async function addDesktopImageSelections(selections: ChatImageSelection[]) {
    const files = (await Promise.all(selections.map(fileFromDesktopImageSelection))).filter((file): file is File => Boolean(file));
    if (files.length === 0) {
      setStatus('没有选择可用图片');
      return;
    }
    await addImageFiles(files);
  }

  async function openImageAttachmentPicker() {
    if (imageAttachDisabled) {
      showImageInputBlocked();
      return;
    }
    if (!canChooseChatImages()) {
      fileInputRef.current?.click();
      return;
    }
    try {
      const selections = await chooseChatImages();
      if (!Array.isArray(selections) || selections.length === 0) return;
      await addDesktopImageSelections(selections);
    } catch (error) {
      const message = error instanceof Error ? error.message : '选择图片失败';
      setStatus(message);
      showNotice('选择图片失败', message, 'warn');
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
        throw new Error('当前 Bridge 尚未加载群组编辑接口，请重启 Oha-Yachiyo 后重试');
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
      setConversationTokenCount(0);
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
      setConversationTokenCount(normalizedTokenCount(result.token_count));
      isProcessingRef.current = nextProcessing;
      setIsProcessing(nextProcessing);
      setProcessingCount(nextProcessingCount);
      setStatus(result.cancelled_tasks ? `已取消 ${result.cancelled_tasks} 个任务` : '没有可取消任务');
      await loadSessions();
    } catch (error) {
      setStatus(error instanceof Error ? error.message : '取消失败');
    }
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
    if (action === 'approve') {
      const approvalPromise = approveChatRunApproval(runId);
      const approvalTargetLabel = fallbackApprovalDetails && isWorkflowApprovalDetails(fallbackApprovalDetails) ? 'Workflow' : 'Agent';
      if (composerItemId) {
        setResolvedComposerApprovalIds((current) => (
          current.includes(composerItemId) ? current : [...current.slice(-20), composerItemId]
        ));
      }
      forgetRunApprovalDetails(runId);
      setIsProcessing(true);
      isProcessingRef.current = true;
      setProcessingCount((current) => Math.max(1, current || 1));
      setStatus(`已批准，${approvalTargetLabel} 正在继续执行...`);
      setApprovalActionMessageId('');
      pollAgentRunInBackground(runId, { summarizeDelegatedRun, ignoreInitialApprovalRequired: true });
      void approvalPromise
        .then(async (run) => {
          const refreshed = await refreshMessages();
          await loadSessions();
          const chatStillProcessing = Boolean(refreshed?.is_processing);
          const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
          const runStatus = normalizeRunStatus(run.status);
          if (runStatus === 'approval_required') {
            rememberRunApprovalDetails(run, fallbackApprovalDetails);
            isProcessingRef.current = true;
            setIsProcessing(true);
            setProcessingCount(Math.max(1, chatProcessingCount));
            setStatus(nextApprovalStatusText(run));
          } else if (runStatus === 'processing') {
            forgetRunApprovalDetails(runId);
            isProcessingRef.current = true;
            setIsProcessing(true);
            setProcessingCount(Math.max(1, chatProcessingCount));
          } else if (!chatStillProcessing) {
            isProcessingRef.current = false;
            setIsProcessing(false);
            setProcessingCount(chatProcessingCount);
          }
        })
        .catch(async (error) => {
          setStatus(error instanceof Error ? error.message : '批准失败');
          try {
            await refreshMessages();
            await loadSessions();
          } catch {
            // The approval error itself is the useful user-facing status here.
          }
        });
      return;
    }
    try {
      const run = await rejectChatRunApproval(runId, 'Rejected from chat');
      const refreshed = await refreshMessages();
      await loadSessions();
      const chatStillProcessing = Boolean(refreshed?.is_processing);
      const chatProcessingCount = Math.max(0, Number(refreshed?.processing_count || 0));
      const runStatus = normalizeRunStatus(run.status);
      let delegatedSummary = { created: false, error: '', taskId: '', isProcessing: false, processingCount: 0 };
      if (summarizeDelegatedRun && ['completed', 'failed', 'cancelled'].includes(runStatus)) {
        delegatedSummary = await createDelegatedRunSummary(runId, delegatedRunSummaryOptions());
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
          setStatus('已批准，Run 正在继续执行...');
          pollAgentRunInBackground(runId, { summarizeDelegatedRun });
        }
      } else {
        forgetRunApprovalDetails(runId);
        const { nextProcessing, nextProcessingCount } = chatRunCompletionProcessingState(
          delegatedSummary,
          chatStillProcessing,
          chatProcessingCount,
        );
        setIsProcessing(nextProcessing);
        isProcessingRef.current = nextProcessing;
        setProcessingCount(nextProcessingCount);
        setStatus(chatApprovalRejectionCompletionStatusText({
          chatStillProcessing,
          delegatedSummary,
          runStatus,
        }));
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

  function openRunDetails(runId: string | undefined, studioUrl = '') {
    const clean = String(runId || '').trim();
    if (!clean) return;
    const groupRunId = groupRunIdFromStudioUrl(studioUrl);
    navigateTo('agents', {
      run: clean,
      ...(groupRunId ? { group_run: groupRunId } : {}),
    }, ['tab', 'target', 'goal']);
  }

  function openWorkflowStudio(runnableId = '', suggestedGoal = '') {
    const cleanRunnableId = String(runnableId || '').trim();
    if (cleanRunnableId) {
      navigateTo('agents', {
        tab: 'runs',
        target: cleanRunnableId,
        goal: String(suggestedGoal || '').trim(),
      }, ['run']);
      return;
    }
    navigateTo('agents', { tab: 'workflows' }, ['run', 'target', 'goal']);
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

  function imageInputBlockedNoticeText() {
    if (isSending) return '正在发送中，稍后再添加图片';
    if (attachments.length >= MAX_ATTACHMENTS) return `一次最多附加 ${MAX_ATTACHMENTS} 张图片`;
    return imageInputUnavailableText(executor);
  }

  function showImageInputBlocked() {
    const detail = imageInputBlockedNoticeText();
    showNotice('当前不能发送图片', detail, 'warn');
    setStatus(detail);
  }

  useEffect(() => {
    if (!import.meta.env.DEV) return undefined;
    const handleE2EAddImage = (event: Event) => {
      const detail = (event as CustomEvent<ChatE2EImageDetail | ChatE2EImageDetail[]>).detail;
      const payloads = Array.isArray(detail) ? detail : [detail];
      void (async () => {
        const files = (await Promise.all(payloads.map(fileFromE2EImageDetail))).filter((file): file is File => Boolean(file));
        if (files.length === 0) {
          setStatus('E2E 图片附件 payload 无效');
          return;
        }
        await addImageFiles(files);
      })();
    };
    window.addEventListener(CHAT_E2E_ADD_IMAGE_EVENT, handleE2EAddImage as EventListener);
    return () => window.removeEventListener(CHAT_E2E_ADD_IMAGE_EVENT, handleE2EAddImage as EventListener);
  }, [attachments.length, executor, isSending]);

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

  function delegatedRunSummaryOptions() {
    return {
      expectPendingAssistantReply,
      loadSessions,
      refreshMessages,
    };
  }

  function rememberRunApprovalDetails(run: ChatApprovalRun, fallbackDetails: ApprovalRequestDetails | null = null) {
    setRunApprovalDetailOverrides((current) => rememberRunApprovalOverride(current, run, fallbackDetails));
  }

  function forgetRunApprovalDetails(runId: string) {
    setRunApprovalDetailOverrides((current) => forgetRunApprovalOverride(current, runId));
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
  const footerStatus = composerApprovalDetails
    ? composerApprovalStatusText(composerApprovalDetails, composerApprovalIndex, composerApprovalCount)
    : status;
  const currentTokenCount = conversationTokenCount || normalizedTokenCount(currentSession?.token_count);
  const currentTokenLabel = currentTokenCount ? ` · ${formatTokenCount(currentTokenCount)}` : '';
  const computedHeaderStatusText = `${headerStatusText(isProcessing, headerActivity, status, executor, activeSessionContext)}${currentTokenLabel}`;
  const imageAttachDisabled = isSending || !canAttachImages(executor) || attachments.length >= MAX_ATTACHMENTS;
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
              data-testid="chat-session-tab-agents"
              onClick={() => setSessionTab('agents')}
            >
              Agent
            </button>
            <button
              type="button"
              className={`session-tab ${sessionTab === 'groups' ? 'active' : ''}`}
              data-testid="chat-session-tab-groups"
              onClick={() => setSessionTab('groups')}
            >
              群组
            </button>
            <button
              type="button"
              className="session-tab-create"
              data-testid="chat-session-tab-create"
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
                      <span className="chat-item-token">{formatTokenCount(session.token_count)}</span>
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
                        <span className="chat-item-token">{formatTokenCount(session.token_count)}</span>
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
                                <span className="chat-item-token">{formatTokenCount(session.token_count)}</span>
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
                      <span className="chat-item-token">{formatTokenCount(session.token_count)}</span>
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
                  <span>{computedHeaderStatusText}</span>
                </div>
              </div>
            </div>
            <div className="chat-header-actions">
              {activeSessionContext.conversation_kind === 'group' ? (
                <button
                  type="button"
                  className="chat-action-btn"
                  data-testid="chat-group-settings"
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
              <button
                type="button"
                className="chat-action-btn"
                title={attachmentHelpText(executor)}
                aria-label="附加图片"
                data-testid="chat-header-image-attach-button"
                disabled={imageAttachDisabled}
                onClick={() => void openImageAttachmentPicker()}
              >
                <UiIcon name="image" />
              </button>
              <button type="button" className="chat-action-btn" title="停止生成" aria-label="停止生成" data-testid="chat-header-stop-button" onClick={() => void cancelProcessing()} disabled={!isProcessing}>
                <UiIcon name="stop" />
              </button>
              <button type="button" className="chat-action-btn" title="新对话" aria-label="新对话" onClick={() => void clearSession()}>
                <UiIcon name="plus" />
              </button>
              <button type="button" className="chat-action-btn danger-action" title={`删除${deleteTarget}`} aria-label={`删除${deleteTarget}`} onClick={requestDeleteSession} disabled={!sessions?.sessions?.length}>
                <UiIcon name="trash" />
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
              {messages.map((message, index) => {
                const publicTaskSnapshot = publicTaskSnapshotForMessage(message, agentTaskSnapshotsById);
                return (
                  <MessageBubble
                    assistantProfile={assistantProfile}
                    assistantProfileLoading={assistantProfileLoading}
                    copied={copiedMessageId === message.id}
                    displayContent={displayMessageText(message, renderStateRef.current)}
                    key={message.id || index}
                    highlighted={message.id === highlightedMessageId}
                    message={message}
                    copiedCodeBlockKey={copiedCodeBlockKey}
                    publicTaskSnapshot={publicTaskSnapshot}
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
                    onApproveTaskApproval={(task, approval) => void resolveYachiyoTaskApproval(task, approval, 'approve')}
                    onCancelTask={cancelYachiyoTaskFromCard}
                    onReject={() => void resolveApprovalMessage(message, 'reject')}
                    onRejectTaskApproval={(task, approval) => void resolveYachiyoTaskApproval(task, approval, 'reject')}
                    onOpenRunDetails={openRunDetails}
                    onOpenWorkflowStudio={openWorkflowStudio}
                    registerMessageNode={registerMessageNode}
                    runnables={runnables}
                  />
                );
              })}
              <div className="chat-bottom-anchor" ref={bottomAnchorRef} aria-hidden="true" />
            </div>
          </section>

          <form className="chat-input-area composer refined-composer" onSubmit={submit}>
            {composerApprovalItem && composerApprovalDetails ? (
              <ComposerApprovalNotice
                approvalId={composerApprovalItem.approvalId}
                busy={approvalActionMessageId === composerApprovalItem.id}
                currentIndex={composerApprovalIndex}
                details={composerApprovalDetails}
                itemId={composerApprovalItem.id}
                onApprove={() => void resolveApprovalItem(composerApprovalItem, 'approve')}
                onReject={() => void resolveApprovalItem(composerApprovalItem, 'reject')}
                onOpenDetails={() => openRunDetails(composerApprovalItem.runId)}
                onPrevious={() => selectComposerApproval(-1)}
                onReveal={() => revealMessage(composerApprovalItem.messageId)}
                onNext={() => selectComposerApproval(1)}
                runId={composerApprovalItem.runId}
                runStatus={composerApprovalItem.runStatus}
                source={composerApprovalItem.source}
                total={composerApprovalCount}
              />
            ) : null}
            <div className={`chat-input-wrapper${isProcessing ? ' is-processing' : ''}`}>
              <div className="composer-body">
                {attachments.length ? (
                  <div className="composer-attachments" aria-label="已添加图片附件">
                    {attachments.map((attachment) => (
                      <figure
                        className="composer-attachment"
                        data-testid="chat-composer-attachment-preview"
                        data-attachment-id={attachment.id}
                        data-attachment-mime={attachment.mime_type}
                        data-attachment-name={attachment.name}
                        data-attachment-size={attachment.size}
                        data-attachment-width={attachment.width || ''}
                        data-attachment-height={attachment.height || ''}
                        key={attachment.id}
                      >
                        <img src={attachment.data_url} alt={attachment.name} />
                        <figcaption>{attachment.name}</figcaption>
                        <button
                          type="button"
                          aria-label={`移除 ${attachment.name}`}
                          data-testid="chat-composer-attachment-remove"
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
                  data-testid="chat-composer-input"
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
                disabled={imageAttachDisabled}
                title={attachmentHelpText(executor)}
                aria-label="添加附件，当前仅支持图片"
                data-testid="chat-composer-image-attach-button"
                onClick={() => void openImageAttachmentPicker()}
              >
                <UiIcon name="paperclip" />
              </button>
              {isProcessing ? (
                <button
                  type="button"
                  className="chat-stop-btn"
                  aria-label={processingCount > 1 ? `停止当前 ${processingCount} 项任务` : '停止当前任务'}
                  title={processingCount > 1 ? `停止当前 ${processingCount} 项任务` : '停止当前任务'}
                  data-testid="chat-composer-stop-button"
                  onClick={() => void cancelProcessing()}
                >
                  <UiIcon name="stop" />
                </button>
              ) : null}
              <button
                type="submit"
                className="chat-send-btn neon-glow"
                data-testid="chat-composer-send"
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
              disabled={imageAttachDisabled}
              data-testid="chat-image-file-input"
              onChange={(event) => {
                const files = Array.from(event.target.files || []);
                event.target.value = '';
                if (files.length === 0) return;
                if (imageAttachDisabled) {
                  showImageInputBlocked();
                  return;
                }
                void addImageFiles(files);
              }}
            />
          </form>
          <footer className="status-line refined-status-line">{footerStatus}</footer>
        </section>
      </div>

      {groupDialogOpen ? (
        <ChatGroupDialog
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

function MessageBubble({ approvalBusy, assistantProfile, assistantProfileLoading, copied, copiedCodeBlockKey, displayContent, highlighted, message, publicTaskSnapshot = null, retryDisabled, retrying, showRetry, onApprove, onApproveTaskApproval, onCancelTask, onCopy, onOpenRunDetails, onOpenWorkflowStudio, onReject, onRejectTaskApproval, onRetry, registerMessageNode, runnables }: {
  approvalBusy: boolean;
  assistantProfile: AssistantProfilePayload | null;
  assistantProfileLoading: boolean;
  copied: boolean;
  copiedCodeBlockKey: string;
  displayContent: string;
  highlighted: boolean;
  message: ChatMessage;
  publicTaskSnapshot?: AgentTaskSnapshot | null;
  retryDisabled: boolean;
  retrying: boolean;
  showRetry: boolean;
  onApprove: () => void;
  onApproveTaskApproval: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void;
  onCancelTask: (task: AgentTaskSnapshot) => void;
  onCopy: () => void;
  onOpenRunDetails: (runId: string, studioUrl?: string) => void;
  onOpenWorkflowStudio: (runnableId?: string, suggestedGoal?: string) => void;
  onReject: () => void;
  onRejectTaskApproval: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void;
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
  const runStatus = messageRunStatus(message);
  const showApprovalActions = hasActionableApproval(message) && Boolean(runId);
  const approvalDetails = showApprovalActions ? approvalRequestDetails(message) : null;
  const approvalId = approvalDetails ? approvalIdFromPending(message.metadata?.pending_approval) : '';
  const approvalSignature = approvalDetails ? messageApprovalSignature(message) : '';
  const showAgentProgress = isProcessingEmpty && Boolean(runId || message.metadata?.runnable_kind === 'agent' || message.metadata?.runnable_kind === 'workflow');
  const progressSender = message.metadata?.sender;
  const progressName = participantDisplayName(progressSender) || messageRoleLabel(message);
  const progressTitle = String(message.metadata?.run_progress_title || 'Agent 正在执行');
  const progressDetail = String(message.metadata?.run_progress_detail || `${progressName} 正在继续处理当前任务。`);
  const progressRunnableKind = String(message.metadata?.runnable_kind || progressSender?.kind || '').trim();
  const progressRunnableId = String(message.metadata?.runnable_id || progressSender?.id || '').trim();
  const progressRunGroupId = String(message.metadata?.run_group_id || '').trim();
  const showInlineRunDetails = role === 'assistant' && Boolean(runId) && !approvalDetails && !showAgentProgress;
  const artifactCount = Number(message.metadata?.run_artifact_count || 0);
  const duplicateError = Boolean(message.error && displayContent.trim() && message.error.trim() === displayContent.trim());
  const summaryNotice = groupAgentSummaryNotice(message);
  const followupNotice = groupFollowupNotice(message);
  const summaryTaskId = String(message.metadata?.group_agent_summary_task_id || '').trim();
  const summaryStatus = String(message.metadata?.group_agent_summary_status || (message.metadata?.group_agent_summary_pending ? 'pending' : '')).trim();
  const summaryRunGroupId = String(message.metadata?.group_dispatch_run_group_id || message.metadata?.run_group_id || '').trim();
  const followupTaskIds = metadataListAttribute(message.metadata?.group_followup_for_task_ids);
  const followupAgentMessageIds = metadataListAttribute(message.metadata?.group_followup_for_agent_message_ids);
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
            <MessageApprovalRequestCard
              approvalId={approvalId}
              approvalSignature={approvalSignature}
              details={approvalDetails}
              onOpenDetails={() => onOpenRunDetails(runId)}
              renderCodePreview={(codeText, codeLanguage) => (
                renderMarkdown(fencedCode(codeText, codeLanguage), message.id || '', copiedCodeBlockKey)
              )}
              runId={runId}
              runStatus={runStatus}
            />
          ) : showAgentProgress ? (
            <AgentRunProgressCard
              detail={progressDetail}
              onOpenDetails={() => onOpenRunDetails(runId)}
              runGroupId={progressRunGroupId}
              runId={runId}
              runStatus={runStatus}
              runnableId={progressRunnableId}
              runnableKind={progressRunnableKind}
              title={progressTitle}
            />
          ) : isProcessingEmpty ? (
            <TypingIndicator />
          ) : (
            <div className="message-content markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(displayContent, message.id || '', copiedCodeBlockKey) }} />
          )}
          {message.attachments?.length ? (
            <div className="message-attachments" data-testid="chat-message-attachments">
              {message.attachments.map((attachment) => (
                <ImageAttachmentViewer
                  attachment={attachment}
                  key={attachment.id || attachment.name}
                  testId="chat-message-attachment-item"
                />
              ))}
            </div>
          ) : null}
          {message.error && !duplicateError ? <div className="message-error">{message.error}</div> : null}
          {summaryNotice ? (
            <div
              className={`message-summary-status ${summaryNotice.tone}`}
              data-run-group-id={summaryRunGroupId}
              data-summary-status={summaryStatus}
              data-summary-task-id={summaryTaskId}
              data-testid="chat-message-summary-status"
              data-summary-tone={summaryNotice.tone}
            >
              {summaryNotice.text}
            </div>
          ) : null}
        </div>
        <MessageActivityList
          events={message.activity_events || []}
          formatTime={formatShortTime}
          messageStatus={message.status}
          onOpenRunDetails={onOpenRunDetails}
          progressLabel={message.progress_label}
        />
        <MessageAgentTaskCard
          busy={approvalBusy}
          displayContent={displayContent}
          hidden={Boolean(approvalDetails || showAgentProgress)}
          message={message}
          onApproveApproval={onApproveTaskApproval}
          onCancelTask={onCancelTask}
          onOpenStudio={onOpenRunDetails}
          onRejectApproval={onRejectTaskApproval}
          publicTaskSnapshot={publicTaskSnapshot}
        />
        {followupNotice ? (
          <div
            className="message-followup-status"
            data-followup-agent-message-ids={followupAgentMessageIds}
            data-followup-task-ids={followupTaskIds}
            data-testid="chat-message-followup-status"
          >
            {followupNotice}
          </div>
        ) : null}
        {showApprovalActions ? (
          <div
            className="message-approval-actions"
            data-approval-id={approvalId}
            data-approval-kind={approvalDetails && isWorkflowApprovalDetails(approvalDetails) ? 'workflow' : 'tool'}
            data-approval-requester={approvalDetails?.requester || ''}
            data-approval-signature={approvalSignature}
            data-approval-source="message"
            data-approval-tool={approvalDetails?.tool || ''}
            data-run-id={runId}
            data-testid="chat-message-approval-actions"
          >
            <button type="button" className="message-approval-approve" data-testid="chat-message-approval-approve" disabled={approvalBusy} onClick={onApprove}>
              {approvalBusy ? '处理中...' : '批准'}
            </button>
            <button type="button" className="message-approval-reject" data-testid="chat-message-approval-reject" disabled={approvalBusy} onClick={onReject}>
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
              data-run-id={runId}
              data-run-status={runStatus}
              data-testid="chat-message-open-run-detail"
              onClick={() => onOpenRunDetails(runId)}
            >
              Agent Studio
            </button>
          ) : null}
          {showWorkflowStudioAction ? (
            <button
              className="message-run-detail-button"
              type="button"
              onClick={() => onOpenWorkflowStudio(
                String(message.metadata?.runnable_id || ''),
                String(message.metadata?.suggested_goal || ''),
              )}
            >
              {message.metadata?.runnable_id ? '去 Runs 运行' : '打开 Workflow Studio'}
            </button>
          ) : null}
          {showRetry ? (
            <button
              className={`message-retry-button ${retrying ? 'retrying' : ''}`}
              type="button"
              data-testid="chat-message-retry"
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
            data-testid="chat-message-copy"
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

function stringValue(value: unknown) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
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

function taskHandoffMessageId(messages: ChatMessage[], taskId: string) {
  const clean = String(taskId || '').trim();
  if (!clean) return '';
  for (let index = messages.length - 1; index >= 0; index -= 1) {
    const message = messages[index];
    if (!message?.id) continue;
    if (messageMatchesTaskHandoff(message, clean)) return message.id;
  }
  return '';
}

function messageMatchesTaskHandoff(message: ChatMessage, taskId: string) {
  const metadata = message.metadata || {};
  if (String(message.task_id || '').trim() === taskId) return true;
  if (stringValue(metadata.group_agent_summary_task_id) === taskId) return true;
  if (stringValue(metadata.group_agent_summary_for_task_id) === taskId) return true;
  if (stringValue(metadata.delegated_run_source_task_id) === taskId) return true;
  if (metadataListAttribute(metadata.group_followup_for_task_ids).split(',').includes(taskId)) return true;
  return false;
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

function createClientMessageId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

function executorLabel(executor: ExecutorPayload | null) {
  if (!executor?.available) return '未就绪';
  if (executor.executor === 'NativeAgentExecutor') return 'Native Agent';
  return executor.executor || '可用';
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

function sessionSideLabel(session: SessionItem) {
  const approvalCount = Number(session.approval_count || 0);
  if (approvalCount > 0) return approvalCount > 1 ? `待审批 ${approvalCount}` : '待审批';
  return session.is_processing ? '处理中' : formatShortTime(session.updated_at || session.created_at);
}

function normalizedTokenCount(value?: number) {
  const numeric = Number(value || 0);
  return Number.isFinite(numeric) && numeric > 0 ? Math.round(numeric) : 0;
}

function formatTokenCount(value?: number) {
  const count = normalizedTokenCount(value);
  if (count >= 1_000_000) return `≈${formatCompactNumber(count / 1_000_000)}m tok`;
  if (count >= 1_000) return `≈${formatCompactNumber(count / 1_000)}k tok`;
  return `≈${count} tok`;
}

function formatCompactNumber(value: number) {
  return value >= 10 ? Math.round(value).toString() : value.toFixed(1).replace(/\.0$/, '');
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
    compact.includes('ohagroupdispatch')
    || compact.includes('nativegroupdispatch')
    || compact.includes('dispatchgroupagent')
    || compact.includes('runohaagent')
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
