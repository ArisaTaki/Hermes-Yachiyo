import { FormEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ClipboardEvent as ReactClipboardEvent,
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react';

import { useConfirmDialog } from '../components/ConfirmDialog';
import {
  clipboardImageFiles,
  fileFromDesktopImageSelection,
  fileFromE2EImageDetail,
  MAX_ATTACHMENT_BYTES,
  readPendingAttachment,
  withResolvedAttachmentUrls,
} from '../features/yachiyo-chat/attachments';
import { createClientMessageId } from '../features/yachiyo-chat/clientMessages';
import { isImeComposing } from '../features/yachiyo-chat/composerEvents';
import { ChatComposer } from '../features/yachiyo-chat/components/ChatComposer';
import { ChatFullPageLoading } from '../features/yachiyo-chat/components/ChatFullPageLoading';
import { composerApprovalStatusText } from '../features/yachiyo-chat/components/ComposerApprovalNotice';
import { ChatGroupDialog } from '../features/yachiyo-chat/components/ChatGroupDialog';
import { ChatHeader } from '../features/yachiyo-chat/components/ChatHeader';
import { ChatSessionSidebar } from '../features/yachiyo-chat/components/ChatSessionSidebar';
import { SessionIdDialog } from '../features/yachiyo-chat/components/SessionIdDialog';
import { MessageBubble } from '../features/yachiyo-chat/components/MessageBubble';
import type { TaskPermissionRecoveryAction } from '../features/yachiyo-chat/components/AgentTaskCard';
import type { ApprovalRequestDetails } from '../features/yachiyo-chat/components/MessageApprovalRequestCard';
import {
  approvalRequiredItems,
  approvalRequiredMessages,
  forgetRunApprovalOverride,
  rememberRunApprovalOverride,
  type ChatApprovalRun,
  type RunApprovalDetailOverride,
} from '../features/yachiyo-chat/approvalItems';
import {
  activityRunId,
  chatStatusLabel,
  compactStatusText,
  isRetryableMessage,
  latestFailedMessage,
  latestVisibleActivity,
  messageMatchesPendingAssistantReply,
  messageErrorText,
  messageRunId,
  messageRunStatus,
  messageText,
} from '../features/yachiyo-chat/messageState';
import {
  COMPOSER_HEIGHT_STORAGE_KEY,
  COMPOSER_MAX_HEIGHT,
  COMPOSER_MIN_HEIGHT,
  attachmentHelpText,
  canAttachImages,
  clampComposerHeight,
  formatShortTime,
  formatTokenCount,
  headerStatusText,
  imageInputBlockedNoticeText,
  normalizedTokenCount,
  sessionSideLabel,
  storedComposerHeight,
} from '../features/yachiyo-chat/displayState';
import { openYachiyoStudioRun, openYachiyoWorkflowStudio } from '../features/yachiyo-chat/studioNavigation';
import {
  activeMentions,
  mentionOptionsForQuery,
  mentionQueryAtEnd,
  mentionTextForOption,
  replaceTrailingMentionQuery,
  yachiyoDailyDesktopTaskPrompt,
  yachiyoPublicTaskPrompt,
  yachiyoPublicTaskTarget,
  type MentionOption,
} from '../features/yachiyo-chat/mentions';
import { codeBlockStateKey } from '../features/yachiyo-chat/markdown';
import { deriveChatSessionState } from '../features/yachiyo-chat/sessionDerivedState';
import {
  clearRetainedComposerDraft,
  retainedComposerDraftSnapshot,
  retainComposerDraft,
} from '../features/yachiyo-chat/sessionState';
import { useYachiyoTaskActions } from '../features/yachiyo-chat/hooks/useYachiyoTaskActions';
import { useChatAssistantProfile } from '../features/yachiyo-chat/hooks/useChatAssistantProfile';
import { useChatCopyFeedback } from '../features/yachiyo-chat/hooks/useChatCopyFeedback';
import { useChatExecutor } from '../features/yachiyo-chat/hooks/useChatExecutor';
import { useChatGroupDialog } from '../features/yachiyo-chat/hooks/useChatGroupDialog';
import { useChatNotice } from '../features/yachiyo-chat/hooks/useChatNotice';
import { useChatRouteHandoff } from '../features/yachiyo-chat/hooks/useChatRouteHandoffParams';
import { useChatRunApprovalActions } from '../features/yachiyo-chat/hooks/useChatRunApprovalActions';
import { useChatRunPolling } from '../features/yachiyo-chat/hooks/useChatRunPolling';
import { useChatRunnables } from '../features/yachiyo-chat/hooks/useChatRunnables';
import { useChatSessions } from '../features/yachiyo-chat/hooks/useChatSessions';
import { useLegacyChatRunnableResult } from '../features/yachiyo-chat/hooks/useLegacyChatRunnableResult';
import { useYachiyoTaskSnapshots } from '../features/yachiyo-chat/hooks/useYachiyoTaskSnapshots';
import { useYachiyoTaskSubmit } from '../features/yachiyo-chat/hooks/useYachiyoTaskSubmit';
import {
  createChatGroupSession,
  getYachiyoReadiness,
  retryLegacyChatMessage,
  sendLegacyChatMessage,
  updateChatGroupSessionWithRecovery,
} from '../features/yachiyo-chat/api';
import {
  displayMessageText,
  shouldContinueTyping,
  syncRenderStates,
} from '../features/yachiyo-chat/renderState';
import { chatDesktopPermissionNotice } from '../features/yachiyo-chat/readiness';
import {
  CHAT_SIDEBAR_BASE_MAX_WIDTH,
  CHAT_SIDEBAR_MIN_WIDTH,
  clampChatSidebarWidth,
  isMessageTextSelectionActive,
  isNearBottom,
  responsiveChatSidebarMaxWidth,
} from '../features/yachiyo-chat/layoutState';
import { publicTaskSnapshotForMessage } from '../features/yachiyo-chat/taskSnapshots';
import {
  runtimeToolRecoveryActionTaskStart,
} from '../features/runtime-shared/toolRecoveryActions';
import type {
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  ChatE2EImageDetail,
  ChatMessage,
  ChatSessionContext,
  MessagesPayload,
  PendingAttachment,
  RenderState,
} from '../features/yachiyo-chat/types';
import { apiGet, apiPost, bridgeUrl, canChooseChatImages, chooseChatImages, copyText, openAppView, openExternalUrl, type ChatImageSelection } from '../lib/bridge';

type ChatViewProps = {
  embedded?: boolean;
};

const ACTIVE_POLL_INTERVAL_MS = 500;
const IDLE_POLL_INTERVAL_MS = 3000;
const EXECUTOR_POLL_INTERVAL_MS = 3000;
const TYPE_BASE_CHARS_PER_SECOND = 85;
const TYPE_MAX_CHARS_PER_SECOND = 360;
const MAX_ATTACHMENTS = 4;
const MIN_LOADING_MS = 1400;
const CHAT_E2E_ADD_IMAGE_EVENT = 'oha-chat-e2e-add-image';

export function ChatView({ embedded = false }: ChatViewProps = {}) {
  const initialComposerDraft = retainedComposerDraftSnapshot();
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [sessionContext, setSessionContext] = useState<ChatSessionContext | null>(null);
  const [input, setInput] = useState(() => initialComposerDraft.input);
  const [attachments, setAttachments] = useState<PendingAttachment[]>(() => initialComposerDraft.attachments);
  const [status, setStatus] = useState('就绪');
  const [isProcessing, setIsProcessing] = useState(false);
  const [processingCount, setProcessingCount] = useState(0);
  const [isSending, setIsSending] = useState(false);
  const [conversationTokenCount, setConversationTokenCount] = useState(0);
  const { executor, refreshExecutor } = useChatExecutor(EXECUTOR_POLL_INTERVAL_MS);
  const { assistantProfile, assistantProfileLoading, refreshAssistantProfile } = useChatAssistantProfile();
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
  const runnables = useChatRunnables(!embedded);
  const [sessionTab, setSessionTab] = useState<'agents' | 'groups'>('agents');
  const [expandedAgents, setExpandedAgents] = useState<Set<string>>(new Set());
  const {
    avatarUrl: groupAvatarUrl,
    changeAvatarUrl: changeGroupAvatarUrl,
    changeName: changeGroupName,
    close: closeGroupDialog,
    error: groupDialogError,
    isCreating: isCreatingGroup,
    mode: groupDialogMode,
    name: groupName,
    open: groupDialogOpen,
    openCreate: openGroupDialog,
    openEdit: openGroupSettingsDialog,
    reportAvatarError: reportGroupAvatarError,
    resetAfterCreate: resetGroupDialogAfterCreate,
    selectedAgentIds: selectedGroupAgentIds,
    setError: setGroupDialogError,
    setIsCreating: setIsCreatingGroup,
    toggleAgent: toggleGroupAgent,
  } = useChatGroupDialog();
  const [mentionActiveIndex, setMentionActiveIndex] = useState(0);
  const [dismissedMentionInput, setDismissedMentionInput] = useState('');
  const [, setRenderTick] = useState(0);
  const { confirmDialog, requestConfirm } = useConfirmDialog();
  const {
    copiedCodeBlockKey,
    copiedMessageId,
    copiedSessionId,
    markCodeBlockCopied,
    markMessageCopied,
    markSessionCopied,
  } = useChatCopyFeedback();
  const { dismissNotice, notice, showNotice } = useChatNotice();
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
  const messagesLoadedRef = useRef(false);
  const messageLoadTokenRef = useRef(0);
  const conversationLoadTokenRef = useRef(0);
  const conversationTransitionRef = useRef(false);
  const messageTextSelectingRef = useRef(false);
  const messageNodeRefs = useRef<Map<string, HTMLElement>>(new Map());
  const isProcessingRef = useRef(false);
  const pendingReplyScrollRef = useRef(false);
  const pendingReplyTaskIdRef = useRef('');
  const highlightedScrollTargetRef = useRef('');
  const highlightClearTimerRef = useRef<number | null>(null);
  const approvalSessionIdRef = useRef('');
  const desktopReadinessNoticeShownRef = useRef(false);
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
  const {
    debouncedSessionQuery,
    loadSessions,
    sessions,
    sessionsLoaded,
    sessionQuery,
    setSessionQuery,
  } = useChatSessions({
    activePollIntervalMs: ACTIVE_POLL_INTERVAL_MS,
    idlePollIntervalMs: IDLE_POLL_INTERVAL_MS,
    isProcessing,
    refreshYachiyoTasksForSession,
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
    resolveApprovalItem,
    resolveApprovalMessage,
  } = useChatRunApprovalActions({
    approvalActionMessageId,
    createDelegatedRunSummaryOptions: delegatedRunSummaryOptions,
    focusComposerSoon,
    forgetRunApprovalDetails,
    isProcessingRef,
    loadSessions,
    pollAgentRunInBackground,
    refreshMessages,
    rememberRunApprovalDetails,
    setApprovalActionMessageId,
    setIsProcessing,
    setProcessingCount,
    setResolvedComposerApprovalIds,
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
  const { handleLegacyChatRunnableResult } = useLegacyChatRunnableResult({
    clearPendingReplyTask: () => {
      pendingReplyTaskIdRef.current = '';
    },
    expectPendingAssistantReply,
    loadSessions,
    onRunning: () => {
      stickToBottomRef.current = true;
    },
    onSettled: () => {
      pendingReplyScrollRef.current = false;
    },
    pollAgentRunInBackground,
    refreshMessages,
    refreshYachiyoTaskById,
    rememberYachiyoTasks,
    setStatus,
  });
  const { startPublicYachiyoTask } = useYachiyoTaskSubmit({
    expectPendingAssistantReply,
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

  const runYachiyoTaskRecoveryAction = useCallback(async (
    task: AgentTaskSnapshot,
    action: TaskPermissionRecoveryAction,
  ) => {
    const recoveryStart = runtimeToolRecoveryActionTaskStart(action, {
      source_task_id: task.task_id,
      source_task_title: task.title || '',
    });
    const prompt = recoveryStart.prompt;
    if (!prompt || approvalActionMessageId) return;
    const busyId = `task:${task.task_id || 'unknown'}:recovery:${action.permission_target || action.tool}`;
    setApprovalActionMessageId(busyId);
    setStatus(`正在执行权限恢复：${action.label || prompt}...`);
    try {
      const handled = await startPublicYachiyoTask({
        clientMessageId: createClientMessageId(),
        conversationId: sessions?.current_session_id || latestChatSnapshotRef.current.currentSessionId || null,
        prompt,
        runnableId: null,
        runnableKind: 'main',
        metadata: recoveryStart.metadata,
      });
      if (!handled) setStatus('权限恢复动作提交失败');
    } finally {
      setApprovalActionMessageId('');
      focusComposerSoon();
    }
  }, [
    approvalActionMessageId,
    focusComposerSoon,
    sessions?.current_session_id,
    setApprovalActionMessageId,
    setStatus,
    startPublicYachiyoTask,
  ]);

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

  useChatRouteHandoff({
    loadSessions,
    refreshAssistantProfile,
    refreshExecutor,
    refreshMessages,
    revealMessage,
    setStatus,
  });

  useEffect(() => {
    if (embedded || desktopReadinessNoticeShownRef.current) return undefined;
    let cancelled = false;
    void getYachiyoReadiness()
      .then((readiness) => {
        if (cancelled) return;
        const desktopNotice = chatDesktopPermissionNotice(readiness);
        if (!desktopNotice) return;
        desktopReadinessNoticeShownRef.current = true;
        showNotice(desktopNotice.title, desktopNotice.detail, desktopNotice.kind, {
          action_label: desktopNotice.action_label,
          action_view: desktopNotice.action_view,
          action_params: desktopNotice.action_params,
        });
      })
      .catch(() => undefined);
    return () => {
      cancelled = true;
    };
  }, [embedded, showNotice]);

  useEffect(() => {
    const interval = isProcessing ? ACTIVE_POLL_INTERVAL_MS : IDLE_POLL_INTERVAL_MS;
    const timer = window.setInterval(refreshMessages, interval);
    return () => window.clearInterval(timer);
  }, [isProcessing, refreshMessages]);

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
        return clampChatSidebarWidth(width, maxWidth);
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
      const shouldTryPublicTask = (
        outgoingAttachments.length === 0
        && String(activeSessionContext?.conversation_kind || '') !== 'group'
      );
      const publicTaskTarget = shouldTryPublicTask
        ? yachiyoPublicTaskTarget(text, runnables, assistantProfile)
        : null;
      const dailyDesktopTaskPrompt = shouldTryPublicTask && !publicTaskTarget
        ? yachiyoDailyDesktopTaskPrompt(text)
        : null;
      if (shouldTryPublicTask) {
        const handled = await startPublicYachiyoTask({
          clientMessageId,
          conversationId: sessions?.current_session_id || latestChatSnapshotRef.current.currentSessionId || null,
          prompt: publicTaskTarget ? yachiyoPublicTaskPrompt(text, publicTaskTarget) : dailyDesktopTaskPrompt || text,
          runnableId: publicTaskTarget?.id || null,
          runnableKind: publicTaskTarget?.kind || 'main',
          metadata: {
            daily_desktop_intent: Boolean(dailyDesktopTaskPrompt),
            planner_entrypoint: publicTaskTarget
              ? 'mentioned_runnable'
              : dailyDesktopTaskPrompt
                ? 'daily_desktop'
                : 'chat_default',
          },
        });
        if (handled) {
          return;
        }
      }
      const result = await sendLegacyChatMessage({
        text,
        attachments: outgoingAttachments,
        client_message_id: clientMessageId,
      });
      if (result.ok === false) throw new Error(result.error || '发送失败');
      transientEmptySessionIdRef.current = '';
      if (await handleLegacyChatRunnableResult(result, { refreshTaskSnapshot: true })) return;
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

  function openGroupSettings() {
    openGroupSettingsDialog({
      activeSessionContext,
      currentSessionId,
      currentTitle,
    });
  }

  function toggleAgentGroup(agentId: string) {
    setExpandedAgents((prev) => {
      const next = new Set(prev);
      if (next.has(agentId)) {
        next.delete(agentId);
      } else {
        next.add(agentId);
      }
      return next;
    });
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
        const result = await updateChatGroupSessionWithRecovery(
          {
            avatarUrl: groupAvatarUrl,
            defaultName: defaultGroupName,
            name: groupName,
            participantIds: selectedGroupAgentIds,
            sessionId: currentSessionId,
          },
          {
            onRestarting: () => setStatus('Bridge 正在重启以加载群组编辑接口...'),
          },
        );
        setSessionContext(result.session_context || activeSessionContext);
        closeGroupDialog();
        setStatus('群组资料已更新');
        await loadSessions();
        await refreshMessages({ allowDuringTransition: true });
        return;
      }
      const result = await createChatGroupSession({
        avatarUrl: groupAvatarUrl,
        defaultName: defaultGroupName,
        name: groupName,
        participantIds: selectedGroupAgentIds,
      });
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
      resetGroupDialogAfterCreate();
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
    const targetLabel = deleteTarget;
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
      markMessageCopied(message.id || '');
      setStatus('已复制');
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
      const retryText = messageText(message);
      const shouldTryPublicTask = (
        !message.attachments?.length
        && String(activeSessionContext?.conversation_kind || '') !== 'group'
      );
      const publicTaskTarget = shouldTryPublicTask
        ? yachiyoPublicTaskTarget(retryText, runnables, assistantProfile)
        : null;
      const retryDailyDesktopTaskPrompt = shouldTryPublicTask && !publicTaskTarget
        ? yachiyoDailyDesktopTaskPrompt(retryText)
        : null;
      if (shouldTryPublicTask) {
        const handled = await startPublicYachiyoTask({
          clientMessageId: createClientMessageId(),
          conversationId: sessions?.current_session_id || latestChatSnapshotRef.current.currentSessionId || null,
          prompt: publicTaskTarget
            ? yachiyoPublicTaskPrompt(retryText, publicTaskTarget)
            : retryDailyDesktopTaskPrompt || retryText,
          runnableId: publicTaskTarget?.id || null,
          runnableKind: publicTaskTarget?.kind || 'main',
          metadata: {
            daily_desktop_intent: Boolean(retryDailyDesktopTaskPrompt),
            planner_entrypoint: publicTaskTarget
              ? 'mentioned_runnable'
              : retryDailyDesktopTaskPrompt
                ? 'daily_desktop'
                : 'chat_default',
            retry_of_message_id: message.id,
          },
        });
        if (handled) return;
      }
      const result = await retryLegacyChatMessage(message.id);
      if (result.ok === false) throw new Error(result.error || '重试失败');
      if (await handleLegacyChatRunnableResult(result)) return;
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
      markCodeBlockCopied(codeBlockKey);
      setStatus('已复制代码');
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
      markSessionCopied(sessionId);
      setStatus('已复制会话调试 ID');
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
    openYachiyoStudioRun(runId, studioUrl);
  }

  function openWorkflowStudio(runnableId = '', suggestedGoal = '') {
    openYachiyoWorkflowStudio(runnableId, suggestedGoal);
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
      const nextWidth = clampChatSidebarWidth(startWidth + moveEvent.clientX - startX, sidebarMaxWidth);
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
      setSidebarWidth((value) => clampChatSidebarWidth(value - 12, sidebarMaxWidth));
    } else if (event.key === 'ArrowRight') {
      event.preventDefault();
      setSidebarWidth((value) => clampChatSidebarWidth(value + 12, sidebarMaxWidth));
    } else if (event.key === 'Home') {
      event.preventDefault();
      setSidebarWidth(CHAT_SIDEBAR_MIN_WIDTH);
    } else if (event.key === 'End') {
      event.preventDefault();
      setSidebarWidth(sidebarMaxWidth);
    }
  }

  function showImageInputBlocked() {
    const detail = imageInputBlockedNoticeText({
      attachmentCount: attachments.length,
      executor,
      isSending,
      maxAttachments: MAX_ATTACHMENTS,
    });
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
    return nextMessages.some((message) => messageMatchesPendingAssistantReply(message, taskId));
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

  const {
    activeSessionContext,
    agentGroups,
    agentRunnables,
    currentSession,
    currentSessionId,
    currentTitle,
    defaultGroupName,
    deleteTarget,
    groupSessions,
    normalizedSessionQuery,
    sessionItems,
    unassignedSessions,
    visibleSessions,
  } = useMemo(() => deriveChatSessionState({
    assistantProfile,
    debouncedSessionQuery,
    messages,
    runnables,
    selectedGroupAgentIds,
    sessionContext,
    sessions,
  }), [assistantProfile, debouncedSessionQuery, messages, runnables, selectedGroupAgentIds, sessionContext, sessions]);

  // 初始化展开状态（默认全部展开）
  const initializedAgentsRef = useRef(false);
  useEffect(() => {
    if (!initializedAgentsRef.current && agentGroups.length > 0) {
      initializedAgentsRef.current = true;
      setExpandedAgents(new Set(agentGroups.map((g) => g.agent_id)));
    }
  }, [agentGroups]);
  useEffect(() => {
    if (approvalSessionIdRef.current === currentSessionId) return;
    approvalSessionIdRef.current = currentSessionId;
    setRunApprovalDetailOverrides({});
    setResolvedComposerApprovalIds([]);
    setComposerApprovalMessageId('');
  }, [currentSessionId]);
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
          {notice.action_label && notice.action_view ? (
            <button
              type="button"
              className="chat-toast-action"
              onClick={() => {
                dismissNotice();
                void openAppView(notice.action_view || 'diagnostics', notice.action_params || {});
              }}
            >
              {notice.action_label}
            </button>
          ) : null}
          <button
            type="button"
            className="chat-toast-close"
            aria-label="关闭提示"
            onClick={dismissNotice}
          >
            ×
          </button>
        </div>
      ) : null}

      <div
        className={`chat-layout hy-chat-workspace${embedded ? '' : ' resizable-chat-workspace'}`}
        style={chatWorkspaceStyle}
      >
        <ChatSessionSidebar
          agentGroups={agentGroups}
          assistantProfile={assistantProfile}
          assistantProfileLoading={assistantProfileLoading}
          currentSessionId={sessions?.current_session_id || ''}
          expandedAgentIds={expandedAgents}
          formatSessionSideLabel={sessionSideLabel}
          formatTokenCount={formatTokenCount}
          groupSessions={groupSessions}
          normalizedSessionQuery={normalizedSessionQuery}
          onCreate={handleSessionTabCreate}
          onSearchChange={setSessionQuery}
          onSwitchSession={switchSession}
          onTabChange={setSessionTab}
          onToggleAgentGroup={toggleAgentGroup}
          runnables={runnables}
          sessionItemsCount={sessionItems.length}
          sessionsLoaded={sessionsLoaded}
          sessionQuery={sessionQuery}
          sessionTab={sessionTab}
          unassignedSessions={unassignedSessions}
          visibleSessions={visibleSessions}
        />

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
          <ChatHeader
            assistantProfile={assistantProfile}
            assistantProfileLoading={assistantProfileLoading}
            attachmentHelpText={attachmentHelpText(executor)}
            copiedSessionId={copiedSessionId}
            currentSessionId={currentSessionId}
            currentTitle={currentTitle}
            deleteTarget={deleteTarget}
            hasSessions={Boolean(sessions?.sessions?.length)}
            imageAttachDisabled={imageAttachDisabled}
            isProcessing={isProcessing}
            onCancelProcessing={() => void cancelProcessing()}
            onClearSession={() => void clearSession()}
            onOpenGroupSettings={openGroupSettings}
            onOpenImageAttachmentPicker={() => void openImageAttachmentPicker()}
            onOpenSessionIdDialog={openSessionIdDialog}
            onRequestDeleteSession={requestDeleteSession}
            runnables={runnables}
            sessionContext={activeSessionContext}
            statusText={computedHeaderStatusText}
          />

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
                    formatTime={formatShortTime}
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
                    onRunTaskRecoveryAction={(task, action) => void runYachiyoTaskRecoveryAction(task, action)}
                    registerMessageNode={registerMessageNode}
                    runnables={runnables}
                  />
                );
              })}
              <div className="chat-bottom-anchor" ref={bottomAnchorRef} aria-hidden="true" />
            </div>
          </section>

          <ChatComposer
            activeMentionChips={activeMentionChips}
            activeMentionOptionId={activeMentionOptionId}
            attachmentHelpText={attachmentHelpText(executor)}
            attachments={attachments}
            composerApprovalBusy={Boolean(composerApprovalItem && approvalActionMessageId === composerApprovalItem.id)}
            composerApprovalCount={composerApprovalCount}
            composerApprovalDetails={composerApprovalDetails}
            composerApprovalIndex={composerApprovalIndex}
            composerApprovalItem={composerApprovalItem}
            composerHeight={composerHeight}
            composerMaxHeight={COMPOSER_MAX_HEIGHT}
            composerMinHeight={COMPOSER_MIN_HEIGHT}
            fileInputRef={fileInputRef}
            imageAttachDisabled={imageAttachDisabled}
            input={input}
            inputRef={inputRef}
            isProcessing={isProcessing}
            isSending={isSending}
            mentionActiveIndex={mentionActiveIndex}
            mentionSuggestions={mentionSuggestions}
            processingCount={processingCount}
            onApproveComposerApproval={() => {
              if (composerApprovalItem) void resolveApprovalItem(composerApprovalItem, 'approve');
            }}
            onCancelProcessing={() => void cancelProcessing()}
            onComposerCompositionEnd={() => {
              composerComposingRef.current = false;
            }}
            onComposerCompositionStart={() => {
              composerComposingRef.current = true;
            }}
            onComposerKeyDown={handleComposerKeyDown}
            onComposerPaste={(event) => void handlePaste(event)}
            onComposerResizeKeyDown={handleComposerResizeKeyDown}
            onComposerResizePointerDown={startComposerResize}
            onFileInputChange={(event) => {
              const files = Array.from(event.target.files || []);
              event.target.value = '';
              if (files.length === 0) return;
              if (imageAttachDisabled) {
                showImageInputBlocked();
                return;
              }
              void addImageFiles(files);
            }}
            onInputChange={setInput}
            onMentionHover={setMentionActiveIndex}
            onMentionSelect={insertMention}
            onOpenComposerApprovalDetails={() => {
              if (composerApprovalItem) openRunDetails(composerApprovalItem.runId);
            }}
            onOpenImageAttachmentPicker={() => void openImageAttachmentPicker()}
            onPreviousComposerApproval={() => selectComposerApproval(-1)}
            onRejectComposerApproval={() => {
              if (composerApprovalItem) void resolveApprovalItem(composerApprovalItem, 'reject');
            }}
            onRemoveAttachment={removeAttachment}
            onRevealComposerApproval={() => {
              if (composerApprovalItem) revealMessage(composerApprovalItem.messageId);
            }}
            onNextComposerApproval={() => selectComposerApproval(1)}
            onSubmit={submit}
          />
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
          onAvatarUrlChange={changeGroupAvatarUrl}
          onAvatarError={(message) => {
            reportGroupAvatarError(message);
            setStatus(message);
          }}
          onClose={closeGroupDialog}
          onNameChange={changeGroupName}
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
