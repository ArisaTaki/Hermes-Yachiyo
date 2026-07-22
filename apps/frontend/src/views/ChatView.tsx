import { FormEvent, MouseEvent as ReactMouseEvent, useCallback, useEffect, useMemo, useRef, useState } from 'react';
import type {
  ClipboardEvent as ReactClipboardEvent,
  CSSProperties,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
} from 'react';

import { useConfirmDialog } from '../components/ConfirmDialog';
import { replanContinuationBlockedStatusMessage } from '../features/runtime-shared/replanContinuationStatus';
import {
  clipboardImageFiles,
  fileFromDesktopImageSelection,
  fileFromE2EImageDetail,
  MAX_ATTACHMENT_BYTES,
  readPendingAttachment,
  withResolvedAttachmentUrls,
} from '../features/yachiyo-chat/attachments';
import {
  conversationClientMessageKey,
  conversationClientMessageSessionPrefix,
  createClientMessageId,
  createOptimisticUserMessage,
  reconcileOptimisticUserMessages,
  removeOptimisticUserMessage,
} from '../features/yachiyo-chat/clientMessages';
import { isImeComposing } from '../features/yachiyo-chat/composerEvents';
import { ChatComposer } from '../features/yachiyo-chat/components/ChatComposer';
import { ChatFullPageLoading } from '../features/yachiyo-chat/components/ChatFullPageLoading';
import { composerApprovalStatusText } from '../features/yachiyo-chat/components/ComposerApprovalNotice';
import { ChatGroupDialog } from '../features/yachiyo-chat/components/ChatGroupDialog';
import { ChatHeader } from '../features/yachiyo-chat/components/ChatHeader';
import { ChatSessionSidebar } from '../features/yachiyo-chat/components/ChatSessionSidebar';
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
  messageMatchesPendingAssistantReply,
  messageErrorText,
  messageRunId,
  messageRunStatus,
  messageText,
  retrySourceUserMessage,
  shouldShowPendingAssistantReply,
} from '../features/yachiyo-chat/messageState';
import {
  COMPOSER_HEIGHT_STORAGE_KEY,
  COMPOSER_MAX_HEIGHT,
  COMPOSER_MIN_HEIGHT,
  attachmentHelpText,
  canAttachImages,
  clampComposerHeight,
  formatShortTime,
  headerStatusText,
  imageInputBlockedNoticeText,
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
  legacyChatDeliveryDisposition,
  retryLegacyChatMessage,
  sendLegacyChatMessage,
  startYachiyoTaskNextReplanContinuation,
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
  startYachiyoTaskRecoveryAction,
  yachiyoTaskNextAutoReplanContinuation,
} from '../features/yachiyo-chat/taskRecoveryActions';
import type {
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  ChatE2EImageDetail,
  ChatMessage,
  ChatSessionContext,
  ConversationIdentity,
  MessagesPayload,
  PendingAttachment,
  RenderState,
} from '../features/yachiyo-chat/types';
import { apiGet, apiPost, bridgeUrl, canChooseChatImages, chooseChatImages, copyText, openAppView, openExternalUrl, type ChatImageSelection } from '../lib/bridge';

type ChatViewProps = {
  embedded?: boolean;
};

type ChatMessagesRefreshResult = {
  is_processing: boolean;
  processing_count?: number;
  messages: ChatMessage[];
} | undefined;

type ChatMessagesRefreshOptions = {
  allowDuringTransition?: boolean;
  anchorMessageId?: string;
  poll?: boolean;
};

const PENDING_ASSISTANT_REPLY: ChatMessage = {
  id: 'local:pending-assistant-reply',
  role: 'assistant',
  status: 'processing',
};

type MarkedSessionSwitchError = Error & {
  sessionSwitchUncertain?: boolean;
};

type ActiveChatSubmission = {
  clientMessageId: string;
  conversationToken: number;
  phase: 'public' | 'legacy' | 'accepted';
  sessionId: string;
};

type OptimisticDeliveryState = 'pending' | 'accepted' | 'uncertain';

type OptimisticDeliveryReconciliation = {
  clientMessageId: string;
  conversationToken: number;
  deadlineAt: number;
  messageKey: string;
  sessionId: string;
  timer: number | null;
};

type DeferredRouteHandoff = {
  sessionId: string;
  resolve: (result: ChatMessagesRefreshResult) => void;
};

type ComposerDraftSnapshot = {
  input: string;
  attachments: PendingAttachment[];
};

function isUncertainSessionSwitchFailure(error: unknown): boolean {
  if (!(error instanceof Error)) return false;
  return error.name === 'TimeoutError'
    || error.name === 'AbortError'
    || error.message.includes('无法连接本地 Bridge');
}

function markSessionSwitchFailureUncertain(error: unknown): MarkedSessionSwitchError {
  const marked = (error instanceof Error ? error : new Error('切换会话失败')) as MarkedSessionSwitchError;
  marked.sessionSwitchUncertain = true;
  return marked;
}

function isMarkedSessionSwitchFailureUncertain(error: unknown): boolean {
  return Boolean((error as MarkedSessionSwitchError | null)?.sessionSwitchUncertain);
}

function chatRequestTimeoutMs(): number {
  if (!import.meta.env.DEV) return DEFAULT_CHAT_REQUEST_TIMEOUT_MS;
  const requested = Number(new URLSearchParams(window.location.search).get('chatRequestTimeoutMs') || 0);
  if (!Number.isFinite(requested) || requested <= 0) return DEFAULT_CHAT_REQUEST_TIMEOUT_MS;
  return Math.max(50, Math.min(DEFAULT_CHAT_REQUEST_TIMEOUT_MS, Math.floor(requested)));
}

function composerDraftIsEmpty(draft: ComposerDraftSnapshot) {
  return !draft.input.trim() && draft.attachments.length === 0;
}

function composerDraftsEqual(left: ComposerDraftSnapshot, right: ComposerDraftSnapshot) {
  if (left.input !== right.input || left.attachments.length !== right.attachments.length) return false;
  return left.attachments.every((attachment, index) => {
    const candidate = right.attachments[index];
    return Boolean(candidate)
      && attachment.id === candidate.id
      && attachment.name === candidate.name
      && attachment.mime_type === candidate.mime_type
      && attachment.size === candidate.size
      && attachment.data_url === candidate.data_url;
  });
}

function canonicalClientDeliveryIsTerminal(messages: ChatMessage[], clientMessageId: string) {
  const canonicalUserMessage = messages.find((message) => (
    message.role === 'user'
    && message.metadata?.client_optimistic !== true
    && String(message.metadata?.client_message_id || '').trim() === clientMessageId
  ));
  if (!canonicalUserMessage) return false;
  const terminalStatuses = new Set(['completed', 'failed', 'cancelled']);
  const taskId = String(canonicalUserMessage.task_id || '').trim();
  if (!taskId) return terminalStatuses.has(String(canonicalUserMessage.status || '').trim());
  const canonicalAssistantMessage = messages.find((message) => (
    message.role === 'assistant' && String(message.task_id || '').trim() === taskId
  ));
  return Boolean(
    canonicalAssistantMessage
    && terminalStatuses.has(String(canonicalAssistantMessage.status || '').trim()),
  );
}

const ACTIVE_POLL_INTERVAL_MS = 1000;
const IDLE_POLL_INTERVAL_MS = 5000;
const EXECUTOR_POLL_INTERVAL_MS = 3000;
const DEFAULT_CHAT_REQUEST_TIMEOUT_MS = 15_000;
const CHAT_REQUEST_TIMEOUT_MS = chatRequestTimeoutMs();
const OPTIMISTIC_RECONCILIATION_INTERVAL_MS = 1000;
const OPTIMISTIC_RECONCILIATION_TIMEOUT_MS = 90_000;
const TYPE_BASE_CHARS_PER_SECOND = 85;
const TYPE_MAX_CHARS_PER_SECOND = 360;
const TYPEWRITER_FRAME_INTERVAL_MS = 1000 / 30;
const MAX_OPTIMISTIC_DELIVERY_STATES = 64;
const MAX_ATTACHMENTS = 4;
const MIN_LOADING_MS = 180;
const MOBILE_SESSIONS_MAX_WIDTH = 760;
const CHAT_E2E_ADD_IMAGE_EVENT = 'oha-chat-e2e-add-image';
const CHAT_DRAWER_FOCUSABLE_SELECTOR = [
  'button:not([disabled])',
  'input:not([disabled])',
  'select:not([disabled])',
  'textarea:not([disabled])',
  '[tabindex]:not([tabindex="-1"])',
].join(',');

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
  const { executor, refreshExecutor } = useChatExecutor(EXECUTOR_POLL_INTERVAL_MS);
  const { assistantProfile, assistantProfileLoading, refreshAssistantProfile } = useChatAssistantProfile();
  const [retryingMessageId, setRetryingMessageId] = useState('');
  const [approvalActionMessageId, setApprovalActionMessageId] = useState('');
  const [composerApprovalMessageId, setComposerApprovalMessageId] = useState('');
  const [resolvedComposerApprovalIds, setResolvedComposerApprovalIds] = useState<string[]>([]);
  const [runApprovalDetailOverrides, setRunApprovalDetailOverrides] = useState<Record<string, RunApprovalDetailOverride>>({});
  const [highlightedMessageId, setHighlightedMessageId] = useState('');
  const [messagesLoaded, setMessagesLoaded] = useState(false);
  const [messagesVisible, setMessagesVisible] = useState(false);
  const [conversationTransitionLocked, setConversationTransitionLocked] = useState(false);
  const [chatBootstrapped, setChatBootstrapped] = useState(false);
  const [sidebarMaxWidth, setSidebarMaxWidth] = useState(() => responsiveChatSidebarMaxWidth());
  const [sidebarWidth, setSidebarWidth] = useState(CHAT_SIDEBAR_BASE_MAX_WIDTH);
  const [mobileSessionsOpen, setMobileSessionsOpen] = useState(false);
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
    markCodeBlockCopied,
    markMessageCopied,
  } = useChatCopyFeedback();
  const { dismissNotice, notice, showNotice } = useChatNotice();
  const listRef = useRef<HTMLDivElement>(null);
  const inputRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const sessionCloseButtonRef = useRef<HTMLButtonElement>(null);
  const sessionToggleButtonRef = useRef<HTMLButtonElement>(null);
  const composerComposingRef = useRef(false);
  const renderStateRef = useRef<Map<string, RenderState>>(new Map());
  const animationFrameRef = useRef<number | null>(null);
  const scrollFrameRef = useRef<number | null>(null);
  const scrollForceRef = useRef(false);
  const typewriterLastTsRef = useRef(0);
  const stickToBottomRef = useRef(true);
  const lastScrollTopRef = useRef(0);
  const messagesLoadedRef = useRef(false);
  const messageLoadTokenRef = useRef(0);
  const messageExplicitRefreshEpochRef = useRef(0);
  const messageRefreshInFlightRef = useRef<Promise<ChatMessagesRefreshResult> | null>(null);
  const messageRequestAbortControllerRef = useRef<AbortController | null>(null);
  const messageRequestIsPollRef = useRef(false);
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
  const autoReplanContinuationKeysRef = useRef<Set<string>>(new Set());
  const loadSessionsRef = useRef<() => Promise<void>>(async () => undefined);
  const activeChatSubmissionRef = useRef<ActiveChatSubmission | null>(null);
  const optimisticDeliveryStateRef = useRef<Map<string, OptimisticDeliveryState>>(new Map());
  const optimisticOutboxRef = useRef<Map<string, ChatMessage>>(new Map());
  const optimisticReconciliationRef = useRef<Map<string, OptimisticDeliveryReconciliation>>(new Map());
  const submittedMessageSequenceRef = useRef(0);
  const submittedMessageSequencesRef = useRef<Map<string, number>>(new Map());
  const deferredRouteHandoffRef = useRef<DeferredRouteHandoff | null>(null);
  const latestMessagesRef = useRef<ChatMessage[]>([]);
  const latestComposerDraftRef = useRef<ComposerDraftSnapshot>({ input, attachments });
  const chatMountedRef = useRef(true);
  const conversationMutationTailRef = useRef<Promise<void>>(Promise.resolve());
  const sessionSwitchAbortControllerRef = useRef<AbortController | null>(null);
  const sessionSwitchRequestIdRef = useRef(0);
  const latestSessionSwitchTargetRef = useRef('');
  const transientEmptySessionIdRef = useRef('');
  const latestChatSnapshotRef = useRef({
    currentSessionId: '',
    messageCount: 0,
    isProcessing: false,
    isSending: false,
  });
  latestComposerDraftRef.current = { input, attachments };

  function rememberOptimisticDeliveryState(
    sessionId: string,
    clientMessageId: string,
    deliveryState: OptimisticDeliveryState,
  ) {
    const messageKey = conversationClientMessageKey(sessionId, clientMessageId);
    if (!messageKey) return;
    const deliveryStates = optimisticDeliveryStateRef.current;
    deliveryStates.delete(messageKey);
    deliveryStates.set(messageKey, deliveryState);
    while (deliveryStates.size > MAX_OPTIMISTIC_DELIVERY_STATES) {
      const oldestClientMessageId = [...deliveryStates.keys()].find((candidate) => (
        !optimisticOutboxRef.current.has(candidate)
      ));
      if (!oldestClientMessageId) break;
      deliveryStates.delete(oldestClientMessageId);
    }
  }

  function rememberOptimisticOutboxMessage(message: ChatMessage) {
    const clientMessageId = String(message.metadata?.client_message_id || '').trim();
    const sessionId = String(message.metadata?.client_session_id || '').trim();
    const messageKey = conversationClientMessageKey(sessionId, clientMessageId);
    if (!messageKey) return;
    optimisticOutboxRef.current.set(messageKey, message);
  }

  function optimisticOutboxMessagesForConversation(
    conversationToken: number,
    sessionId: string,
  ) {
    const messages: ChatMessage[] = [];
    for (const [messageKey, message] of optimisticOutboxRef.current) {
      if (String(message.metadata?.client_session_id || '').trim() !== sessionId) continue;
      const reboundMessage = {
        ...message,
        metadata: {
          ...message.metadata,
          client_conversation_token: conversationToken,
        },
      };
      optimisticOutboxRef.current.set(messageKey, reboundMessage);
      messages.push(reboundMessage);
    }
    return messages;
  }

  function forgetOptimisticOutboxMessage(
    sessionId: string,
    clientMessageId: string,
    preserveSubmittedSequence = false,
  ) {
    const messageKey = conversationClientMessageKey(sessionId, clientMessageId);
    if (!messageKey) return;
    optimisticOutboxRef.current.delete(messageKey);
    optimisticDeliveryStateRef.current.delete(messageKey);
    if (!preserveSubmittedSequence) submittedMessageSequencesRef.current.delete(messageKey);
  }

  function forgetOptimisticOutboxSession(sessionId: string) {
    const sessionPrefix = conversationClientMessageSessionPrefix(sessionId);
    if (!sessionPrefix) return;
    for (const messageKey of optimisticOutboxRef.current.keys()) {
      if (messageKey.startsWith(sessionPrefix)) optimisticOutboxRef.current.delete(messageKey);
    }
    for (const messageKey of optimisticDeliveryStateRef.current.keys()) {
      if (messageKey.startsWith(sessionPrefix)) optimisticDeliveryStateRef.current.delete(messageKey);
    }
    for (const messageKey of submittedMessageSequencesRef.current.keys()) {
      if (messageKey.startsWith(sessionPrefix)) submittedMessageSequencesRef.current.delete(messageKey);
    }
  }

  function pruneSubmittedMessageSequencesForSession(sessionId: string) {
    const sessionPrefix = conversationClientMessageSessionPrefix(sessionId);
    if (!sessionPrefix) return;
    const hasPendingOutbox = [...optimisticOutboxRef.current.keys()].some((messageKey) => (
      messageKey.startsWith(sessionPrefix)
    ));
    if (hasPendingOutbox) return;
    for (const messageKey of submittedMessageSequencesRef.current.keys()) {
      if (messageKey.startsWith(sessionPrefix)) submittedMessageSequencesRef.current.delete(messageKey);
    }
  }

  function enqueueConversationMutation<T>(mutation: () => Promise<T>): Promise<T> {
    const pending = conversationMutationTailRef.current
      .catch(() => undefined)
      .then(mutation);
    conversationMutationTailRef.current = pending.then(() => undefined, () => undefined);
    return pending;
  }
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
    loadSessionsSnapshot,
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

  const runMessagesRefresh = useCallback(async (
    options: Omit<ChatMessagesRefreshOptions, 'poll'>,
    conversationToken: number,
    poll: boolean,
    refreshEpoch: number,
  ): Promise<ChatMessagesRefreshResult> => {
    if (!chatMountedRef.current) return undefined;
    if (poll && refreshEpoch !== messageExplicitRefreshEpochRef.current) return undefined;
    if (conversationToken !== conversationLoadTokenRef.current) return undefined;
    if (conversationTransitionRef.current && !options.allowDuringTransition) return undefined;
    const token = ++messageLoadTokenRef.current;
    const startedAt = Date.now();
    const shouldHoldLoading = !messagesLoadedRef.current;
    const anchorMessageId = (options.anchorMessageId || '').trim();
    const isCurrentRequest = () => (
      chatMountedRef.current
      && conversationToken === conversationLoadTokenRef.current
      && token === messageLoadTokenRef.current
      && (!poll || refreshEpoch === messageExplicitRefreshEpochRef.current)
    );
    const requestController = new AbortController();
    messageRequestAbortControllerRef.current = requestController;
    messageRequestIsPollRef.current = poll;
    try {
      const query = new URLSearchParams();
      query.set('limit', anchorMessageId ? '220' : '0');
      if (anchorMessageId) query.set('anchor_message_id', anchorMessageId);
      const payload = await apiGet<MessagesPayload>(`/ui/chat/messages?${query.toString()}`, {
        signal: requestController.signal,
        timeoutMs: CHAT_REQUEST_TIMEOUT_MS,
      });
      if (payload.ok === false) throw new Error(payload.error || '读取消息失败');
      if (!isCurrentRequest()) return undefined;
      const baseUrl = await bridgeUrl();
      const nextMessages = withResolvedAttachmentUrls(payload.messages || [], baseUrl);
      const responseSessionId = String(
        payload.session_id || latestChatSnapshotRef.current.currentSessionId || '',
      ).trim();
      settleOptimisticDeliveryReconciliations(nextMessages, responseSessionId);
      const canonicalClientMessageIds = new Set(nextMessages.map((message) => (
        String(message.metadata?.client_message_id || '').trim()
      )).filter(Boolean));
      const outboxMessages = optimisticOutboxMessagesForConversation(
        conversationToken,
        responseSessionId,
      );
      const unresolvedOptimisticMessage = outboxMessages.find((message) => {
        const optimisticClientMessageId = String(message.metadata?.client_message_id || '').trim();
        return Boolean(optimisticClientMessageId)
          && !canonicalClientMessageIds.has(optimisticClientMessageId);
      });
      const unresolvedDeliveryState = optimisticDeliveryStateRef.current.get(
        conversationClientMessageKey(
          responseSessionId,
          String(unresolvedOptimisticMessage?.metadata?.client_message_id || '').trim(),
        ),
      );
      const unresolvedDeliveryStatus = unresolvedDeliveryState === 'uncertain'
        ? '投递状态待确认，正在同步对话…'
        : unresolvedDeliveryState === 'accepted'
          ? '消息已发送，正在同步对话…'
          : '';
      if (!isCurrentRequest()) return undefined;
      setSessionContext(payload.session_context || null);
      const nextProcessingCount = Math.max(0, Number(payload.processing_count || 0));
      const processing = Boolean(payload.is_processing || nextProcessingCount > 0);
      const processingChanged = processing !== isProcessingRef.current;
      void refreshYachiyoTaskSnapshotsFromMessages(nextMessages);
      isProcessingRef.current = processing;
      const failed = latestFailedMessage(nextMessages);
      if (!shouldHoldLoading && isMessageSelectionPaused()) {
        setIsProcessing(processing);
        setProcessingCount(nextProcessingCount);
        setStatus(unresolvedDeliveryStatus || chatStatusLabel(processing, failed, nextMessages, nextProcessingCount));
        if (processingChanged) void loadSessionsRef.current();
        return { is_processing: processing, processing_count: nextProcessingCount, messages: nextMessages };
      }
      syncRenderStates(nextMessages, renderStateRef.current);
      const elapsed = Date.now() - startedAt;
      const remaining = Math.max(0, MIN_LOADING_MS - elapsed);
      if (shouldHoldLoading && remaining > 0) await new Promise((r) => setTimeout(r, remaining));
      if (!isCurrentRequest()) return undefined;
      if (anchorMessageId) {
        const anchorFound = nextMessages.some((message) => message.id === anchorMessageId);
        if (highlightClearTimerRef.current !== null) {
          window.clearTimeout(highlightClearTimerRef.current);
          highlightClearTimerRef.current = null;
        }
        highlightedScrollTargetRef.current = anchorFound ? anchorMessageId : '';
        setHighlightedMessageId(anchorFound ? anchorMessageId : '');
      }
      setMessages((currentMessages) => {
        const reconciledMessages = reconcileOptimisticUserMessages(
          nextMessages,
          currentMessages,
          conversationToken,
          responseSessionId,
          outboxMessages,
          submittedMessageSequencesRef.current,
        );
        for (const clientMessageId of canonicalClientMessageIds) {
          forgetOptimisticOutboxMessage(responseSessionId, clientMessageId, true);
        }
        pruneSubmittedMessageSequencesForSession(responseSessionId);
        latestMessagesRef.current = reconciledMessages;
        return reconciledMessages;
      });
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
      if (!isCurrentRequest()) return undefined;
      messagesLoadedRef.current = true;
      setMessagesVisible(true);
      setMessagesLoaded(true);
      if (unresolvedDeliveryStatus) {
        setStatus(unresolvedDeliveryStatus);
      } else if (processing) {
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
      if (!isCurrentRequest()) return undefined;
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
      const optimisticMessage = latestMessagesRef.current.find((message) => (
        message.metadata?.client_optimistic === true
        && message.metadata?.client_conversation_token === conversationToken
      ));
      const optimisticClientMessageId = String(optimisticMessage?.metadata?.client_message_id || '').trim();
      const optimisticSessionId = String(optimisticMessage?.metadata?.client_session_id || '').trim();
      const deliveryState = optimisticDeliveryStateRef.current.get(
        conversationClientMessageKey(optimisticSessionId, optimisticClientMessageId),
      );
      if (deliveryState === 'pending' || deliveryState === 'uncertain') {
        setStatus('投递状态待确认，正在同步对话…');
      } else if (deliveryState === 'accepted') {
        setStatus('消息已发送，正在同步对话…');
      } else {
        setStatus(error instanceof Error ? error.message : '读取消息失败');
      }
      return undefined;
    } finally {
      if (messageRequestAbortControllerRef.current === requestController) {
        messageRequestAbortControllerRef.current = null;
        messageRequestIsPollRef.current = false;
      }
    }
  }, []);

  const refreshMessages = useCallback((
    options: ChatMessagesRefreshOptions = {},
  ): Promise<ChatMessagesRefreshResult> => {
    if (conversationTransitionRef.current && !options.allowDuringTransition) {
      return Promise.resolve(undefined);
    }
    const current = messageRefreshInFlightRef.current;
    if (options.poll && current) return current;

    const poll = Boolean(options.poll);
    const refreshEpoch = poll
      ? messageExplicitRefreshEpochRef.current
      : ++messageExplicitRefreshEpochRef.current;
    if (!poll && messageRequestIsPollRef.current) {
      messageRequestAbortControllerRef.current?.abort();
    }
    const conversationToken = conversationLoadTokenRef.current;
    const refreshOptions = {
      allowDuringTransition: options.allowDuringTransition,
      anchorMessageId: options.anchorMessageId,
    };
    const execute = () => runMessagesRefresh(
      refreshOptions,
      conversationToken,
      poll,
      refreshEpoch,
    );
    const pending = current
      ? current.catch(() => undefined).then(execute)
      : execute();
    let tracked: Promise<ChatMessagesRefreshResult>;
    tracked = pending.finally(() => {
      if (messageRefreshInFlightRef.current === tracked) {
        messageRefreshInFlightRef.current = null;
      }
    });
    messageRefreshInFlightRef.current = tracked;
    return tracked;
  }, [runMessagesRefresh]);

  function stopOptimisticDeliveryReconciliation(messageKey: string) {
    const reconciliation = optimisticReconciliationRef.current.get(messageKey);
    if (!reconciliation) return;
    if (reconciliation.timer !== null) window.clearTimeout(reconciliation.timer);
    optimisticReconciliationRef.current.delete(messageKey);
  }

  function cancelOptimisticDeliveryReconciliations(sessionId = '') {
    const sessionPrefix = conversationClientMessageSessionPrefix(sessionId);
    for (const messageKey of [...optimisticReconciliationRef.current.keys()]) {
      if (!sessionPrefix || messageKey.startsWith(sessionPrefix)) {
        stopOptimisticDeliveryReconciliation(messageKey);
      }
    }
  }

  function settleOptimisticDeliveryReconciliations(
    messages: ChatMessage[],
    sessionId: string,
  ) {
    for (const reconciliation of optimisticReconciliationRef.current.values()) {
      if (reconciliation.sessionId !== sessionId) continue;
      if (canonicalClientDeliveryIsTerminal(messages, reconciliation.clientMessageId)) {
        stopOptimisticDeliveryReconciliation(reconciliation.messageKey);
      }
    }
  }

  function scheduleOptimisticDeliveryReconciliation(
    reconciliation: OptimisticDeliveryReconciliation,
    delayMs: number,
  ) {
    if (reconciliation.timer !== null) return;
    if (Date.now() >= reconciliation.deadlineAt) {
      stopOptimisticDeliveryReconciliation(reconciliation.messageKey);
      return;
    }
    reconciliation.timer = window.setTimeout(() => {
      reconciliation.timer = null;
      void (async () => {
        if (
          optimisticReconciliationRef.current.get(reconciliation.messageKey) !== reconciliation
          || !chatMountedRef.current
          || !isSubmissionConversationCurrent({
            conversationToken: reconciliation.conversationToken,
            sessionId: reconciliation.sessionId,
          })
        ) {
          stopOptimisticDeliveryReconciliation(reconciliation.messageKey);
          return;
        }
        await refreshMessages({ allowDuringTransition: true });
        if (optimisticReconciliationRef.current.get(reconciliation.messageKey) !== reconciliation) return;
        scheduleOptimisticDeliveryReconciliation(
          reconciliation,
          OPTIMISTIC_RECONCILIATION_INTERVAL_MS,
        );
      })();
    }, Math.max(0, delayMs));
  }

  function beginOptimisticDeliveryReconciliation(identity: ConversationIdentity, clientMessageId: string) {
    const messageKey = conversationClientMessageKey(identity.sessionId, clientMessageId);
    if (!messageKey || optimisticReconciliationRef.current.has(messageKey)) return;
    const reconciliation: OptimisticDeliveryReconciliation = {
      clientMessageId,
      conversationToken: identity.conversationToken,
      deadlineAt: Date.now() + OPTIMISTIC_RECONCILIATION_TIMEOUT_MS,
      messageKey,
      sessionId: identity.sessionId,
      timer: null,
    };
    optimisticReconciliationRef.current.set(messageKey, reconciliation);
    scheduleOptimisticDeliveryReconciliation(reconciliation, 0);
  }

  useEffect(() => {
    chatMountedRef.current = true;
    return () => {
      chatMountedRef.current = false;
      messageLoadTokenRef.current += 1;
      conversationLoadTokenRef.current += 1;
      messageExplicitRefreshEpochRef.current += 1;
      messageRequestAbortControllerRef.current?.abort();
      sessionSwitchAbortControllerRef.current?.abort();
      optimisticDeliveryStateRef.current.clear();
      optimisticOutboxRef.current.clear();
      cancelOptimisticDeliveryReconciliations();
      submittedMessageSequencesRef.current.clear();
      deferredRouteHandoffRef.current?.resolve(undefined);
      deferredRouteHandoffRef.current = null;
    };
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
    isConversationCurrent: isSubmissionConversationCurrent,
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
    getConversationIdentity: currentConversationIdentity,
    isProcessingRef,
    isConversationCurrent: isSubmissionConversationCurrent,
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
    getConversationIdentity: currentConversationIdentity,
    isConversationCurrent: isSubmissionConversationCurrent,
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
    isConversationCurrent: isSubmissionConversationCurrent,
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
    isConversationCurrent: isSubmissionConversationCurrent,
    loadSessions,
    onAccepted: (acceptedClientMessageId) => {
      transientEmptySessionIdRef.current = '';
      pendingReplyTaskIdRef.current = '';
      const activeSubmission = activeChatSubmissionRef.current;
      if (activeSubmission?.clientMessageId === acceptedClientMessageId) {
        rememberOptimisticDeliveryState(
          activeSubmission.sessionId,
          acceptedClientMessageId,
          'accepted',
        );
        activeSubmission.phase = 'accepted';
      }
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
    const prompt = action.prompt || action.label || action.tool;
    if (!prompt || approvalActionMessageId) return;
    const busyId = `task:${task.task_id || 'unknown'}:recovery:${action.permission_target || action.tool}`;
    setApprovalActionMessageId(busyId);
    setStatus(`正在执行权限恢复：${action.label || prompt}...`);
    try {
      const identity = currentConversationIdentity();
      if (!identity) {
        setStatus('当前会话尚未准备好，请稍后再试');
        return;
      }
      const result = await startYachiyoTaskRecoveryAction({
        action,
        conversationId: identity.sessionId,
        onStartedTask: (startedTask) => {
          if (isSubmissionConversationCurrent(identity)) rememberYachiyoTasks([startedTask]);
        },
        startFallbackTask: (recoveryStart) => startPublicYachiyoTask({
          clientMessageId: createClientMessageId(),
          identity,
          prompt: recoveryStart.prompt,
          runnableId: null,
          runnableKind: 'main',
          metadata: recoveryStart.metadata,
        }),
        task,
      });
      if (!isSubmissionConversationCurrent(identity)) return;
      if (result.mode === 'replan') {
        setStatus(
          result.statusMessage
          || `已启动恢复动作：${action.label || result.title || result.prompt}`,
        );
      } else if (result.mode === 'desktop_provider_session') {
        setStatus(result.statusMessage || '已请求启动可选隔离桌面 Provider');
      } else if (result.fallbackResult === false) {
        setStatus('权限恢复动作提交失败');
      }
    } finally {
      setApprovalActionMessageId('');
      focusComposerSoon();
    }
  }, [
    approvalActionMessageId,
    focusComposerSoon,
    rememberYachiyoTasks,
    sessions?.current_session_id,
    setApprovalActionMessageId,
    setStatus,
    startPublicYachiyoTask,
  ]);

  useEffect(() => {
    if (approvalActionMessageId) return;
    const currentSessionId = sessions?.current_session_id || latestChatSnapshotRef.current.currentSessionId || '';
    const candidate = uniqueCurrentTaskSnapshots(agentTaskSnapshotsById, currentSessionId)
      .map((task) => yachiyoTaskNextAutoReplanContinuation(task, currentSessionId || null))
      .find((item) => Boolean(item));
    if (!candidate) return;
    if (autoReplanContinuationKeysRef.current.has(candidate.key)) return;
    autoReplanContinuationKeysRef.current.add(candidate.key);
    const taskId = String(candidate.recovery.task_id || candidate.request.metadata?.source_task_id || '').trim()
      || candidate.key.split(':')[0];
    setStatus(`正在自动恢复：${candidate.action.label || candidate.action.tool}...`);
    void startYachiyoTaskNextReplanContinuation(taskId, candidate.request)
      .then((result) => {
        if (result.started && result.task) {
          rememberYachiyoTasks([result.task]);
          setStatus(`已自动启动恢复动作：${candidate.action.label || candidate.action.tool}`);
          void refreshMessages({ allowDuringTransition: true });
          return;
        }
        setStatus(replanContinuationBlockedStatusMessage(result));
      })
      .catch(() => {
        setStatus('自动恢复动作提交失败');
      });
  }, [
    agentTaskSnapshotsById,
    approvalActionMessageId,
    refreshMessages,
    rememberYachiyoTasks,
    sessions?.current_session_id,
    setStatus,
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
    switchConversation: switchRouteConversation,
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
    let timer: number | null = null;
    let disposed = false;

    const clearTimer = () => {
      if (timer === null) return;
      window.clearTimeout(timer);
      timer = null;
    };
    const scheduleNextPoll = () => {
      clearTimer();
      if (disposed || document.hidden) return;
      timer = window.setTimeout(() => {
        timer = null;
        void refreshMessages({ poll: true })
          .catch(() => undefined)
          .finally(scheduleNextPoll);
      }, interval);
    };
    const handleVisibilityChange = () => {
      clearTimer();
      if (disposed || document.hidden) return;
      void refreshMessages()
        .catch(() => undefined)
        .finally(scheduleNextPoll);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    scheduleNextPoll();
    return () => {
      disposed = true;
      clearTimer();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
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
      if (window.innerWidth > MOBILE_SESSIONS_MAX_WIDTH) {
        const shouldFocusComposer = document.activeElement === sessionCloseButtonRef.current;
        setMobileSessionsOpen(false);
        if (shouldFocusComposer) {
          window.requestAnimationFrame(() => inputRef.current?.focus({ preventScroll: true }));
        }
      }
    };
    syncResponsiveSidebarWidth();
    window.addEventListener('resize', syncResponsiveSidebarWidth);
    return () => window.removeEventListener('resize', syncResponsiveSidebarWidth);
  }, [embedded]);

  useEffect(() => {
    latestMessagesRef.current = messages;
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
      node.scrollIntoView({
        behavior: window.matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth',
        block: 'center',
      });
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
      if (mobileSessionsOpen && event.key === 'Tab') {
        trapMobileSessionsFocus(event);
        return;
      }
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'n') {
        event.preventDefault();
        void clearSession();
      } else if ((event.metaKey || event.ctrlKey) && event.key === '.') {
        event.preventDefault();
        void cancelProcessing();
      } else if (event.key === 'Escape') {
        if (mobileSessionsOpen) {
          event.preventDefault();
          closeMobileSessions(true);
        } else {
          inputRef.current?.focus();
        }
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
    if (!typewriterLastTsRef.current) {
      typewriterLastTsRef.current = timestamp - TYPEWRITER_FRAME_INTERVAL_MS;
    }
    const elapsedMs = timestamp - typewriterLastTsRef.current;
    if (elapsedMs < TYPEWRITER_FRAME_INTERVAL_MS) {
      animationFrameRef.current = window.requestAnimationFrame(tickTypewriter);
      return;
    }
    const elapsed = elapsedMs / 1000;
    typewriterLastTsRef.current = timestamp;
    let pending = false;
    let advanced = false;

    for (const state of renderStateRef.current.values()) {
      if (state.shown.length >= state.target.length) continue;
      const remaining = state.target.length - state.shown.length;
      const speed = Math.min(
        TYPE_MAX_CHARS_PER_SECOND,
        TYPE_BASE_CHARS_PER_SECOND + Math.floor(remaining / 4),
      );
      const step = Math.max(1, Math.floor(speed * elapsed));
      state.shown = state.target.slice(0, state.shown.length + step);
      advanced = true;
      if (state.shown.length < state.target.length) pending = true;
    }

    if (advanced) {
      setRenderTick((value) => value + 1);
      scrollToConversationBottom();
    }
    animationFrameRef.current = pending ? window.requestAnimationFrame(tickTypewriter) : null;
  }

  function scrollToConversationBottom(force = false) {
    if (force) {
      stickToBottomRef.current = true;
      scrollForceRef.current = true;
    }
    if (!scrollForceRef.current && (!stickToBottomRef.current || isMessageSelectionPaused())) return;
    if (scrollFrameRef.current !== null) return;
    scrollFrameRef.current = window.requestAnimationFrame(() => {
      scrollFrameRef.current = null;
      const shouldForce = scrollForceRef.current;
      scrollForceRef.current = false;
      const list = listRef.current;
      if (!list || (!shouldForce && (!stickToBottomRef.current || isMessageSelectionPaused()))) return;
      list.scrollTop = list.scrollHeight;
      lastScrollTopRef.current = list.scrollTop;
    });
  }

  function closeMobileSessions(restoreFocus = false) {
    setMobileSessionsOpen(false);
    if (restoreFocus) {
      window.requestAnimationFrame(() => sessionToggleButtonRef.current?.focus({ preventScroll: true }));
    }
  }

  function openMobileSessions() {
    setMobileSessionsOpen(true);
    window.requestAnimationFrame(() => sessionCloseButtonRef.current?.focus({ preventScroll: true }));
  }

  function toggleMobileSessions() {
    if (mobileSessionsOpen) closeMobileSessions();
    else openMobileSessions();
  }

  function trapMobileSessionsFocus(event: KeyboardEvent) {
    const sidebar = document.getElementById('chat-session-sidebar');
    if (!sidebar) return;
    const focusable = Array.from(
      sidebar.querySelectorAll<HTMLElement>(CHAT_DRAWER_FOCUSABLE_SELECTOR),
    ).filter((element) => element.tabIndex >= 0 && element.getClientRects().length > 0);
    const first = focusable[0];
    const last = focusable[focusable.length - 1];
    if (!first || !last) return;

    const active = document.activeElement;
    if (event.shiftKey && (active === first || !sidebar.contains(active))) {
      event.preventDefault();
      last.focus();
    } else if (!event.shiftKey && (active === last || !sidebar.contains(active))) {
      event.preventDefault();
      first.focus();
    }
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
    if (
      (!text && attachments.length === 0)
      || isSending
      || Boolean(activeChatSubmissionRef.current)
      || Boolean(retryingMessageId)
      || conversationTransitionLocked
      || conversationTransitionRef.current
    ) return;
    if (attachments.length > 0 && !canAttachImages(executor)) {
      showImageInputBlocked();
      return;
    }
    const submissionSessionId = sessions?.current_session_id
      || latestChatSnapshotRef.current.currentSessionId
      || '';
    if (!submissionSessionId) {
      retainComposerDraft(text, attachments);
      setStatus('正在准备会话，请稍后再发送');
      void loadSessions();
      return;
    }
    const outgoingAttachments = attachments;
    const clientMessageId = createClientMessageId();
    const submittedSequence = ++submittedMessageSequenceRef.current;
    submittedMessageSequencesRef.current.set(
      conversationClientMessageKey(submissionSessionId, clientMessageId),
      submittedSequence,
    );
    const submissionConversationToken = conversationLoadTokenRef.current;
    const optimisticMessage = createOptimisticUserMessage({
      attachments: outgoingAttachments,
      clientMessageId,
      content: text,
      conversationToken: submissionConversationToken,
      sessionId: submissionSessionId,
      submittedSequence,
    });
    rememberOptimisticOutboxMessage(optimisticMessage);
    rememberOptimisticDeliveryState(submissionSessionId, clientMessageId, 'pending');
    setMessages((currentMessages) => {
      const nextMessages = [
        ...removeOptimisticUserMessage(currentMessages, submissionSessionId, clientMessageId),
        optimisticMessage,
      ];
      latestMessagesRef.current = nextMessages;
      return nextMessages;
    });
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
    let submissionAccepted = false;
    let submissionRejected = false;
    try {
      const isGroupConversation = String(activeSessionContext?.conversation_kind || '') === 'group';
      const publicTaskCandidate = !isGroupConversation
        ? yachiyoPublicTaskTarget(text, runnables, assistantProfile)
        : null;
      const shouldTryPublicTask = !isGroupConversation && (
        outgoingAttachments.length === 0 || !publicTaskCandidate
      );
      const publicTaskTarget = shouldTryPublicTask ? publicTaskCandidate : null;
      const dailyDesktopTaskPrompt = shouldTryPublicTask
        && !publicTaskTarget
        && outgoingAttachments.length === 0
        ? yachiyoDailyDesktopTaskPrompt(text)
        : null;
      activeChatSubmissionRef.current = {
        clientMessageId,
        conversationToken: submissionConversationToken,
        phase: shouldTryPublicTask ? 'public' : 'legacy',
        sessionId: submissionSessionId,
      };
      if (shouldTryPublicTask) {
        const handled = await startPublicYachiyoTask({
          attachments: outgoingAttachments,
          clientMessageId,
          identity: {
            conversationToken: submissionConversationToken,
            sessionId: submissionSessionId,
          },
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
      if (!isSubmissionConversationCurrent(submissionConversationToken, submissionSessionId)) {
        setMessages((currentMessages) => {
          const nextMessages = removeOptimisticUserMessage(
            currentMessages,
            submissionSessionId,
            clientMessageId,
          );
          latestMessagesRef.current = nextMessages;
          return nextMessages;
        });
        return;
      }
      if (activeChatSubmissionRef.current?.clientMessageId === clientMessageId) {
        activeChatSubmissionRef.current.phase = 'legacy';
      }
      const result = await sendLegacyChatMessage({
        text,
        attachments: outgoingAttachments,
        client_message_id: clientMessageId,
      }, { timeoutMs: CHAT_REQUEST_TIMEOUT_MS });
      const deliveryDisposition = legacyChatDeliveryDisposition(result);
      if (deliveryDisposition === 'rejected') {
        submissionRejected = true;
        throw new Error(result.error || '消息未发送');
      }
      submissionAccepted = deliveryDisposition === 'accepted';
      rememberOptimisticDeliveryState(submissionSessionId, clientMessageId, deliveryDisposition);
      if (activeChatSubmissionRef.current?.clientMessageId === clientMessageId) {
        activeChatSubmissionRef.current.phase = 'accepted';
      }
      transientEmptySessionIdRef.current = '';
      if (deliveryDisposition === 'uncertain') {
        setStatus('投递状态待确认，正在同步对话…');
        void loadSessions();
        beginOptimisticDeliveryReconciliation({
          conversationToken: submissionConversationToken,
          sessionId: submissionSessionId,
        }, clientMessageId);
        return;
      }
      if (await handleLegacyChatRunnableResult(result, {
        identity: {
          conversationToken: submissionConversationToken,
          sessionId: submissionSessionId,
        },
        refreshTaskSnapshot: true,
      })) {
        return;
      }
      const taskId = String(result.task_id || '');
      pendingReplyTaskIdRef.current = taskId;
      if (!taskId) pendingReplyScrollRef.current = false;
      setStatus('等待回复...');
      void loadSessions();
      const refreshed = await refreshMessages();
      await loadSessions();
      if (!refreshed) setStatus('消息已发送，正在同步对话…');
    } catch (error) {
      if (!isSubmissionConversationCurrent(submissionConversationToken, submissionSessionId)) return;
      if (!submissionRejected) {
        rememberOptimisticDeliveryState(
          submissionSessionId,
          clientMessageId,
          submissionAccepted ? 'accepted' : 'uncertain',
        );
        setStatus(submissionAccepted ? '消息已发送，正在同步对话…' : '投递状态待确认，正在同步对话…');
        beginOptimisticDeliveryReconciliation({
          conversationToken: submissionConversationToken,
          sessionId: submissionSessionId,
        }, clientMessageId);
        return;
      }
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      setMessages((currentMessages) => {
        const nextMessages = removeOptimisticUserMessage(
          currentMessages,
          submissionSessionId,
          clientMessageId,
        );
        latestMessagesRef.current = nextMessages;
        return nextMessages;
      });
      forgetOptimisticOutboxMessage(submissionSessionId, clientMessageId);
      pruneSubmittedMessageSequencesForSession(submissionSessionId);
      if (submissionConversationToken === conversationLoadTokenRef.current) {
        retainComposerDraft(text, outgoingAttachments);
        setInput(text);
        setAttachments(outgoingAttachments);
      }
      setStatus(error instanceof Error ? error.message : '发送失败');
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
    } finally {
      if (activeChatSubmissionRef.current?.clientMessageId === clientMessageId) {
        activeChatSubmissionRef.current = null;
      }
      setIsSending(false);
      replayDeferredRouteHandoff();
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
    if (conversationTransitionRef.current) return;
    if (sessionTab === 'groups') {
      openGroupDialog();
      return;
    }
    void clearSession();
  }

  async function submitGroupDialog(event: FormEvent) {
    event.preventDefault();
    if (isCreatingGroup || selectedGroupAgentIds.length === 0) return;
    if (
      groupDialogMode === 'create'
      && (conversationTransitionRef.current || blockConversationTransitionDuringSubmission())
    ) return;
    const conversationToken = groupDialogMode === 'create'
      ? beginConversationLoading()
      : conversationLoadTokenRef.current;
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
      const result = await enqueueConversationMutation(() => createChatGroupSession({
        avatarUrl: groupAvatarUrl,
        defaultName: defaultGroupName,
        name: groupName,
        participantIds: selectedGroupAgentIds,
      }));
      if (conversationToken !== conversationLoadTokenRef.current) return;
      const nextSessionId = String(result.session_id || '');
      transientEmptySessionIdRef.current = '';
      latestChatSnapshotRef.current = {
        ...latestChatSnapshotRef.current,
        currentSessionId: nextSessionId,
        messageCount: 0,
      };
      renderStateRef.current.clear();
      latestMessagesRef.current = [];
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
      if (conversationToken === conversationLoadTokenRef.current) unlockConversationTransition();
    } catch (error) {
      if (groupDialogMode === 'create' && conversationToken === conversationLoadTokenRef.current) {
        unlockConversationTransition();
        messagesLoadedRef.current = true;
        setMessagesLoaded(true);
        setMessagesVisible(true);
      }
      const message = error instanceof Error ? error.message : (groupDialogMode === 'edit' ? '保存群组失败' : '创建群组失败');
      setGroupDialogError(message);
      setStatus(message);
    } finally {
      setIsCreatingGroup(false);
    }
  }

  async function clearSession() {
    if (conversationTransitionRef.current) return;
    if (blockConversationTransitionDuringSubmission()) return;
    const conversationToken = beginConversationLoading();
    try {
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      const result = await enqueueConversationMutation(() => (
        apiPost<{ ok?: boolean; error?: string; session_id?: string }>('/ui/chat/session/clear')
      ));
      if (result.ok === false) throw new Error(result.error || '新建对话失败');
      if (conversationToken !== conversationLoadTokenRef.current) return;
      const nextSessionId = String(result.session_id || '');
      forgetOptimisticOutboxSession(nextSessionId);
      transientEmptySessionIdRef.current = nextSessionId;
      latestChatSnapshotRef.current = {
        ...latestChatSnapshotRef.current,
        currentSessionId: nextSessionId,
        messageCount: 0,
      };
      renderStateRef.current.clear();
      latestMessagesRef.current = [];
      setMessages([]);
      setSessionContext(null);
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
      setStatus('新对话已创建');
      await loadSessions();
      if (conversationToken === conversationLoadTokenRef.current) {
        messagesLoadedRef.current = true;
        setMessagesLoaded(true);
        setMessagesVisible(true);
        unlockConversationTransition();
      }
    } catch (error) {
      if (conversationToken !== conversationLoadTokenRef.current) return;
      unlockConversationTransition();
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
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

  async function deleteSession(targetLabel: string, targetSessionId: string) {
    if (!targetSessionId) return;
    if (conversationTransitionRef.current) return;
    if (blockDangerousConversationMutationDuringSubmission()) return;
    const conversationToken = beginConversationLoading();
    try {
      await enqueueConversationMutation(() => apiPost('/ui/chat/session/delete', {
        session_id: targetSessionId,
      }));
      if (conversationToken !== conversationLoadTokenRef.current) return;
      renderStateRef.current.clear();
      forgetOptimisticOutboxSession(targetSessionId);
      latestMessagesRef.current = [];
      stickToBottomRef.current = true;
      await loadSessions();
      await refreshMessages({ allowDuringTransition: true });
      if (conversationToken === conversationLoadTokenRef.current) unlockConversationTransition();
      setStatus(`已删除此${targetLabel}`);
    } catch (error) {
      if (conversationToken !== conversationLoadTokenRef.current) return;
      unlockConversationTransition();
      messagesLoadedRef.current = true;
      setMessagesLoaded(true);
      setMessagesVisible(true);
      setStatus(error instanceof Error ? error.message : '删除失败');
    }
  }

  function requestDeleteSession() {
    const targetLabel = deleteTarget;
    const targetSessionId = currentSessionId;
    if (!targetSessionId) return;
    requestConfirm({
      title: `删除此${targetLabel}？`,
      description: `当前${targetLabel}记录会从本机删除，此操作不可恢复。`,
      confirmLabel: `删除${targetLabel}`,
      variant: 'danger',
      onConfirm: () => void deleteSession(targetLabel, targetSessionId),
    });
  }

  function switchRouteConversation(sessionId: string): Promise<ChatMessagesRefreshResult> {
    const submissionPhase = activeChatSubmissionRef.current?.phase;
    if (!submissionPhase || submissionPhase === 'accepted') {
      return switchSession(sessionId);
    }
    return new Promise((resolve) => {
      deferredRouteHandoffRef.current?.resolve(undefined);
      deferredRouteHandoffRef.current = { sessionId, resolve };
      setStatus('消息发送完成后将打开目标会话');
    });
  }

  function replayDeferredRouteHandoff() {
    const deferredHandoff = deferredRouteHandoffRef.current;
    if (!deferredHandoff) return;
    deferredRouteHandoffRef.current = null;
    void switchSession(deferredHandoff.sessionId).then(
      deferredHandoff.resolve,
      () => deferredHandoff.resolve(undefined),
    );
  }

  async function switchSession(sessionId: string, anchorMessageId = '') {
    if (!sessionId) return;
    if (blockConversationTransitionDuringSubmission()) return;
    if (
      sessionId === sessions?.current_session_id
      && !latestSessionSwitchTargetRef.current
      && !conversationTransitionRef.current
    ) {
      const refreshed = await refreshMessages({ allowDuringTransition: true, anchorMessageId });
      if (anchorMessageId) setStatus('已定位到匹配消息');
      return refreshed;
    }
    const switchRequestId = ++sessionSwitchRequestIdRef.current;
    latestSessionSwitchTargetRef.current = sessionId;
    const conversationToken = beginConversationLoading();
    setStatus('正在切换会话...');
    const mutation = enqueueConversationMutation(async () => {
      if (!chatMountedRef.current) return;
      const executeMutation = async () => {
        const requestController = new AbortController();
        sessionSwitchAbortControllerRef.current = requestController;
        try {
          const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/chat/sessions/load', {
            session_id: sessionId,
          }, {
            signal: requestController.signal,
            timeoutMs: CHAT_REQUEST_TIMEOUT_MS,
          });
          if (result.ok === false) throw new Error(result.error || '切换会话失败');
        } finally {
          if (sessionSwitchAbortControllerRef.current === requestController) {
            sessionSwitchAbortControllerRef.current = null;
          }
        }
      };
      try {
        await executeMutation();
      } catch (error) {
        if (!chatMountedRef.current || !isUncertainSessionSwitchFailure(error)) throw error;
        try {
          await executeMutation();
        } catch (retryError) {
          throw markSessionSwitchFailureUncertain(retryError);
        }
      }
    });
    try {
      await mutation;
      if (
        switchRequestId !== sessionSwitchRequestIdRef.current
        || conversationToken !== conversationLoadTokenRef.current
      ) return;
      renderStateRef.current.clear();
      stickToBottomRef.current = true;
      await loadSessions();
      if (
        switchRequestId !== sessionSwitchRequestIdRef.current
        || conversationToken !== conversationLoadTokenRef.current
      ) return;
      const refreshed = await refreshMessages({ allowDuringTransition: true, anchorMessageId });
      if (conversationToken === conversationLoadTokenRef.current) unlockConversationTransition();
      setStatus(anchorMessageId ? '已定位到匹配消息' : '已切换会话');
      return refreshed;
    } catch (error) {
      if (
        switchRequestId !== sessionSwitchRequestIdRef.current
        || conversationToken !== conversationLoadTokenRef.current
      ) return;
      const failureMessage = error instanceof Error ? error.message : '切换失败';
      if (isMarkedSessionSwitchFailureUncertain(error)) {
        messagesLoadedRef.current = false;
        setMessagesLoaded(false);
        setMessagesVisible(false);
        setStatus(`${failureMessage}；服务端最终会话尚无法确认，请重试切换`);
        return;
      }

      setStatus(`${failureMessage}；正在恢复服务端当前会话...`);
      const authoritativeSessions = await loadSessionsSnapshot();
      const authoritativeSessionId = String(authoritativeSessions?.current_session_id || '').trim();
      const refreshed = authoritativeSessionId
        ? await refreshMessages({ allowDuringTransition: true })
        : undefined;
      if (
        switchRequestId !== sessionSwitchRequestIdRef.current
        || conversationToken !== conversationLoadTokenRef.current
      ) return;
      if (authoritativeSessionId && refreshed) {
        latestChatSnapshotRef.current = {
          ...latestChatSnapshotRef.current,
          currentSessionId: authoritativeSessionId,
        };
        unlockConversationTransition();
        setStatus(`${failureMessage}；已恢复到服务端当前会话`);
        return refreshed;
      } else {
        messagesLoadedRef.current = false;
        setMessagesLoaded(false);
        setMessagesVisible(false);
        setStatus(`${failureMessage}；无法确认服务端当前会话，请重试切换`);
      }
    } finally {
      if (switchRequestId === sessionSwitchRequestIdRef.current) {
        latestSessionSwitchTargetRef.current = '';
      }
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
    if (isUncertainOptimisticMessage(message)) {
      await retryUncertainOptimisticMessage(message);
      return;
    }
    if (
      !message.id
      || isSending
      || isProcessing
      || retryingMessageId
      || activeChatSubmissionRef.current
      || conversationTransitionLocked
      || conversationTransitionRef.current
    ) return;
    const retrySessionId = sessions?.current_session_id
      || latestChatSnapshotRef.current.currentSessionId
      || '';
    if (!retrySessionId) {
      setStatus('正在准备会话，请稍后再重试');
      void loadSessions();
      return;
    }
    const retryConversationToken = conversationLoadTokenRef.current;
    const retrySourceMessage = retrySourceUserMessage(message, messages) || message;
    const retryClientMessageId = createClientMessageId();
    const retryText = messageText(retrySourceMessage);
    const retryAttachments = retrySourceMessage.attachments || message.attachments || [];
    const shouldTryPublicTask = (
      retryAttachments.length === 0
      && String(activeSessionContext?.conversation_kind || '') !== 'group'
    );
    const publicTaskTarget = shouldTryPublicTask
      ? yachiyoPublicTaskTarget(retryText, runnables, assistantProfile)
      : null;
    const retryDailyDesktopTaskPrompt = shouldTryPublicTask && !publicTaskTarget
      ? yachiyoDailyDesktopTaskPrompt(retryText)
      : null;
    rememberOptimisticDeliveryState(retrySessionId, retryClientMessageId, 'pending');
    activeChatSubmissionRef.current = {
      clientMessageId: retryClientMessageId,
      conversationToken: retryConversationToken,
      phase: shouldTryPublicTask ? 'public' : 'legacy',
      sessionId: retrySessionId,
    };
    setRetryingMessageId(message.id);
    setIsSending(true);
    setStatus('正在重试...');
    isProcessingRef.current = true;
    pendingReplyScrollRef.current = true;
    pendingReplyTaskIdRef.current = '';
    setIsProcessing(true);
    setProcessingCount((current) => Math.max(1, current || 1));
    stickToBottomRef.current = true;
    let retryAccepted = false;
    let retryRejected = false;
    try {
      if (shouldTryPublicTask) {
        const handled = await startPublicYachiyoTask({
          clientMessageId: retryClientMessageId,
          identity: {
            conversationToken: retryConversationToken,
            sessionId: retrySessionId,
          },
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
      if (!isSubmissionConversationCurrent(retryConversationToken, retrySessionId)) return;
      if (activeChatSubmissionRef.current?.clientMessageId === retryClientMessageId) {
        activeChatSubmissionRef.current.phase = 'legacy';
      }
      const result = await retryLegacyChatMessage(
        message.id,
        retryClientMessageId,
        { timeoutMs: CHAT_REQUEST_TIMEOUT_MS },
      );
      const deliveryDisposition = legacyChatDeliveryDisposition(result);
      if (deliveryDisposition === 'rejected') {
        retryRejected = true;
        throw new Error(result.error || '消息未重新发送');
      }
      retryAccepted = deliveryDisposition === 'accepted';
      rememberOptimisticDeliveryState(retrySessionId, retryClientMessageId, deliveryDisposition);
      if (activeChatSubmissionRef.current?.clientMessageId === retryClientMessageId) {
        activeChatSubmissionRef.current.phase = 'accepted';
      }
      if (deliveryDisposition === 'uncertain') {
        setStatus('重试投递状态待确认，正在同步对话…');
        beginOptimisticDeliveryReconciliation({
          conversationToken: retryConversationToken,
          sessionId: retrySessionId,
        }, retryClientMessageId);
        return;
      }
      if (await handleLegacyChatRunnableResult(result, {
        identity: {
          conversationToken: retryConversationToken,
          sessionId: retrySessionId,
        },
      })) return;
      const taskId = String(result.task_id || '');
      pendingReplyTaskIdRef.current = taskId;
      if (!taskId) pendingReplyScrollRef.current = false;
      setStatus('已重新发送，等待回复...');
      void loadSessions();
      await refreshMessages();
      await loadSessions();
    } catch (error) {
      if (!isSubmissionConversationCurrent(retryConversationToken, retrySessionId)) return;
      if (!retryRejected) {
        rememberOptimisticDeliveryState(
          retrySessionId,
          retryClientMessageId,
          retryAccepted ? 'accepted' : 'uncertain',
        );
        setStatus(retryAccepted ? '重试已接收，正在同步对话…' : '重试投递状态待确认，正在同步对话…');
        beginOptimisticDeliveryReconciliation({
          conversationToken: retryConversationToken,
          sessionId: retrySessionId,
        }, retryClientMessageId);
        return;
      }
      optimisticDeliveryStateRef.current.delete(
        conversationClientMessageKey(retrySessionId, retryClientMessageId),
      );
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
      setStatus(error instanceof Error ? error.message : '重试失败');
    } finally {
      if (activeChatSubmissionRef.current?.clientMessageId === retryClientMessageId) {
        activeChatSubmissionRef.current = null;
      }
      setRetryingMessageId('');
      setIsSending(false);
      replayDeferredRouteHandoff();
      focusComposerSoon();
    }
  }

  function isUncertainOptimisticMessage(message: ChatMessage) {
    const clientMessageId = String(message.metadata?.client_message_id || '').trim();
    const sessionId = String(message.metadata?.client_session_id || '').trim();
    return message.role === 'user'
      && message.metadata?.client_optimistic === true
      && Boolean(clientMessageId)
      && optimisticDeliveryStateRef.current.get(
        conversationClientMessageKey(sessionId, clientMessageId),
      ) === 'uncertain';
  }

  function pendingAttachmentsFromOptimisticMessage(message: ChatMessage): PendingAttachment[] {
    return (message.attachments || []).flatMap((attachment, index) => {
      const dataUrl = String(attachment.url || '').trim();
      if (!dataUrl.startsWith('data:')) return [];
      return [{
        id: String(attachment.id || `retry-attachment-${index}`),
        name: String(attachment.name || `image-${index + 1}`),
        mime_type: String(attachment.mime_type || 'image/png'),
        size: Math.max(0, Number(attachment.size || 0)),
        data_url: dataUrl,
      }];
    });
  }

  async function retryUncertainOptimisticMessage(message: ChatMessage) {
    if (
      !message.id
      || isSending
      || retryingMessageId
      || activeChatSubmissionRef.current
      || conversationTransitionRef.current
    ) return;
    const clientMessageId = String(message.metadata?.client_message_id || '').trim();
    const identity: ConversationIdentity = {
      conversationToken: Number(message.metadata?.client_conversation_token),
      sessionId: String(message.metadata?.client_session_id || '').trim(),
    };
    if (!clientMessageId || !isSubmissionConversationCurrent(identity)) {
      setStatus('这条消息已不属于当前会话，无法重新确认投递');
      return;
    }
    const text = messageText(message);
    const outgoingAttachments = pendingAttachmentsFromOptimisticMessage(message);
    const composerDraftAtRetry = latestComposerDraftRef.current;
    activeChatSubmissionRef.current = {
      clientMessageId,
      conversationToken: identity.conversationToken,
      phase: 'legacy',
      sessionId: identity.sessionId,
    };
    rememberOptimisticDeliveryState(identity.sessionId, clientMessageId, 'pending');
    setRetryingMessageId(message.id);
    setIsSending(true);
    setStatus('正在确认消息投递...');
    let rejected = false;
    try {
      const result = await sendLegacyChatMessage({
        text,
        attachments: outgoingAttachments,
        client_message_id: clientMessageId,
      }, { timeoutMs: CHAT_REQUEST_TIMEOUT_MS });
      const deliveryDisposition = legacyChatDeliveryDisposition(result);
      if (deliveryDisposition === 'rejected') {
        rejected = true;
        throw new Error(result.error || '消息未发送');
      }
      rememberOptimisticDeliveryState(identity.sessionId, clientMessageId, deliveryDisposition);
      if (activeChatSubmissionRef.current?.clientMessageId === clientMessageId) {
        activeChatSubmissionRef.current.phase = 'accepted';
      }
      if (!isSubmissionConversationCurrent(identity)) return;
      if (deliveryDisposition === 'uncertain') {
        setStatus('投递状态仍待确认，正在同步对话…');
        beginOptimisticDeliveryReconciliation(identity, clientMessageId);
        return;
      }
      if (await handleLegacyChatRunnableResult(result, { identity })) return;
      const refreshed = await refreshMessages();
      if (!isSubmissionConversationCurrent(identity)) return;
      await loadSessions();
      if (!refreshed) setStatus('消息已发送，正在同步对话…');
    } catch (error) {
      if (!isSubmissionConversationCurrent(identity)) return;
      if (!rejected) {
        rememberOptimisticDeliveryState(identity.sessionId, clientMessageId, 'uncertain');
        setStatus('投递状态待确认，正在同步对话…');
        beginOptimisticDeliveryReconciliation(identity, clientMessageId);
        return;
      }
      forgetOptimisticOutboxMessage(identity.sessionId, clientMessageId);
      pruneSubmittedMessageSequencesForSession(identity.sessionId);
      pendingReplyScrollRef.current = false;
      pendingReplyTaskIdRef.current = '';
      setMessages((currentMessages) => {
        const nextMessages = removeOptimisticUserMessage(
          currentMessages,
          identity.sessionId,
          clientMessageId,
        );
        latestMessagesRef.current = nextMessages;
        return nextMessages;
      });
      const currentComposerDraft = latestComposerDraftRef.current;
      const composerUnchangedSinceRetry = composerDraftsEqual(
        currentComposerDraft,
        composerDraftAtRetry,
      );
      const composerAlreadyContainsRetry = composerDraftsEqual(currentComposerDraft, {
        input: text,
        attachments: outgoingAttachments,
      });
      if (
        composerAlreadyContainsRetry
        || (composerDraftIsEmpty(composerDraftAtRetry) && composerUnchangedSinceRetry)
      ) {
        retainComposerDraft(text, outgoingAttachments);
        setInput(text);
        setAttachments(outgoingAttachments);
        setStatus(error instanceof Error ? error.message : '消息未发送');
      } else {
        retainComposerDraft(currentComposerDraft.input, currentComposerDraft.attachments);
        setStatus(`${error instanceof Error ? error.message : '消息未发送'}；当前草稿已保留`);
      }
      isProcessingRef.current = false;
      setIsProcessing(false);
      setProcessingCount(0);
    } finally {
      if (activeChatSubmissionRef.current?.clientMessageId === clientMessageId) {
        activeChatSubmissionRef.current = null;
      }
      setRetryingMessageId('');
      setIsSending(false);
      replayDeferredRouteHandoff();
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

  function delegatedRunSummaryOptions(identity: ConversationIdentity) {
    return {
      expectPendingAssistantReply,
      identity,
      isConversationCurrent: isSubmissionConversationCurrent,
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

  function currentConversationIdentity(): ConversationIdentity | null {
    const currentSessionId = latestChatSnapshotRef.current.currentSessionId
      || sessions?.current_session_id
      || '';
    if (!currentSessionId) return null;
    return {
      conversationToken: conversationLoadTokenRef.current,
      sessionId: currentSessionId,
    };
  }

  function isSubmissionConversationCurrent(
    identityOrConversationToken: ConversationIdentity | number,
    requestedSessionId = '',
  ) {
    const identity = typeof identityOrConversationToken === 'number'
      ? {
        conversationToken: identityOrConversationToken,
        sessionId: requestedSessionId,
      }
      : identityOrConversationToken;
    if (!identity.sessionId || identity.conversationToken !== conversationLoadTokenRef.current) return false;
    const currentSessionId = latestChatSnapshotRef.current.currentSessionId
      || sessions?.current_session_id
      || '';
    return Boolean(currentSessionId) && identity.sessionId === currentSessionId;
  }

  function blockConversationTransitionDuringSubmission() {
    const phase = activeChatSubmissionRef.current?.phase;
    if (!phase || phase === 'accepted') return false;
    setStatus(phase === 'public'
      ? '消息正在提交，请稍候再切换会话'
      : '消息正在发送，请稍候再切换会话');
    return true;
  }

  function blockDangerousConversationMutationDuringSubmission() {
    const phase = activeChatSubmissionRef.current?.phase;
    if (!phase || phase === 'accepted') return false;
    setStatus('消息投递尚未确认，请稍候再删除会话');
    return true;
  }

  function lockConversationTransition() {
    conversationTransitionRef.current = true;
    setConversationTransitionLocked(true);
  }

  function unlockConversationTransition() {
    conversationTransitionRef.current = false;
    setConversationTransitionLocked(false);
  }

  function beginConversationLoading() {
    const conversationToken = ++conversationLoadTokenRef.current;
    cancelOptimisticDeliveryReconciliations();
    messageRequestAbortControllerRef.current?.abort();
    pendingReplyScrollRef.current = false;
    pendingReplyTaskIdRef.current = '';
    highlightedScrollTargetRef.current = '';
    if (highlightClearTimerRef.current !== null) {
      window.clearTimeout(highlightClearTimerRef.current);
      highlightClearTimerRef.current = null;
    }
    lockConversationTransition();
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
      const minFrames = 2;
      const maxFrames = 10;
      const requiredStableFrames = 2;

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
  const composerApprovalItems = useMemo(
    () => approvalRequiredItems(messages, resolvedComposerApprovalIds, runApprovalDetailOverrides),
    [messages, resolvedComposerApprovalIds, runApprovalDetailOverrides],
  );
  const fallbackApprovalItemsByMessageId = useMemo(() => {
    const byMessageId = new Map<string, (typeof composerApprovalItems)[number]>();
    composerApprovalItems.forEach((item) => {
      if (!item.messageId || item.source === 'message') return;
      byMessageId.set(item.messageId, item);
    });
    return byMessageId;
  }, [composerApprovalItems]);
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
  const computedHeaderStatusText = headerStatusText(
    isProcessing,
    null,
    status,
    executor,
    activeSessionContext,
  );
  const imageAttachDisabled = conversationTransitionLocked
    || isSending
    || !canAttachImages(executor)
    || attachments.length >= MAX_ATTACHMENTS;
  const chatWorkspaceStyle = embedded
    ? undefined
    : ({ '--chat-sidebar-width': `${sidebarWidth}px` } as CSSProperties);
  const initialChatLoading = !embedded && !chatBootstrapped;
  const conversationLoading = !messagesLoaded;
  const visibleMessages = shouldShowPendingAssistantReply(
    messages,
    messagesLoaded && (isSending || isProcessing),
  )
    ? [...messages, PENDING_ASSISTANT_REPLY]
    : messages;

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
        className={`chat-layout hy-chat-workspace${embedded ? '' : ' resizable-chat-workspace'}${mobileSessionsOpen ? ' sessions-open' : ''}`}
        style={chatWorkspaceStyle}
      >
        <button
          type="button"
          className={`chat-session-backdrop${mobileSessionsOpen ? ' is-visible' : ''}`}
          aria-hidden={!mobileSessionsOpen}
          aria-label="关闭会话列表"
          tabIndex={-1}
          onClick={() => closeMobileSessions(true)}
        />
        <ChatSessionSidebar
          agentGroups={agentGroups}
          assistantProfile={assistantProfile}
          assistantProfileLoading={assistantProfileLoading}
          currentSessionId={sessions?.current_session_id || ''}
          conversationMutationLocked={conversationTransitionLocked}
          closeButtonRef={sessionCloseButtonRef}
          expandedAgentIds={expandedAgents}
          formatSessionSideLabel={sessionSideLabel}
          groupSessions={groupSessions}
          mobileOpen={mobileSessionsOpen}
          normalizedSessionQuery={normalizedSessionQuery}
          onClose={() => closeMobileSessions(true)}
          onCreate={() => {
            closeMobileSessions();
            handleSessionTabCreate();
          }}
          onSearchChange={setSessionQuery}
          onSwitchSession={(sessionId, anchorMessageId) => {
            closeMobileSessions();
            const switching = switchSession(sessionId, anchorMessageId);
            window.requestAnimationFrame(() => inputRef.current?.focus({ preventScroll: true }));
            return switching.then(() => undefined);
          }}
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

        <section className="chat-main hy-chat-mainpane" inert={mobileSessionsOpen}>
          <ChatHeader
            assistantProfile={assistantProfile}
            assistantProfileLoading={assistantProfileLoading}
            attachmentHelpText={attachmentHelpText(executor)}
            conversationTransitionLocked={conversationTransitionLocked}
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
            onRequestDeleteSession={requestDeleteSession}
            onToggleSessions={toggleMobileSessions}
            runnables={runnables}
            sessionContext={activeSessionContext}
            sessionsPanelOpen={mobileSessionsOpen}
            sessionsToggleRef={sessionToggleButtonRef}
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
              {visibleMessages.map((message, index) => {
                const publicTaskSnapshot = publicTaskSnapshotForMessage(message, agentTaskSnapshotsById);
                const uncertainOptimisticDelivery = isUncertainOptimisticMessage(message);
                const fallbackApprovalItem = message.id
                  ? fallbackApprovalItemsByMessageId.get(message.id) || null
                  : null;
                return (
                  <MessageBubble
                    assistantProfile={assistantProfile}
                    assistantProfileLoading={assistantProfileLoading}
                    copied={copiedMessageId === message.id}
                    displayContent={displayMessageText(message, renderStateRef.current)}
                    fallbackApprovalItem={fallbackApprovalItem}
                    formatTime={formatShortTime}
                    key={message.id || index}
                    highlighted={message.id === highlightedMessageId}
                    message={message}
                    copiedCodeBlockKey={copiedCodeBlockKey}
                    publicTaskSnapshot={publicTaskSnapshot}
                    retryDisabled={Boolean(
                      isSending
                      || retryingMessageId
                      || conversationTransitionLocked
                      || (isProcessing && !uncertainOptimisticDelivery)
                    )}
                    retrying={retryingMessageId === message.id}
                    showRetry={uncertainOptimisticDelivery || isRetryableMessage(message, messages)}
                    approvalBusy={Boolean(
                      (
                        message.id
                        && (
                          approvalActionMessageId === message.id
                          || approvalActionMessageId.startsWith(`message:${message.id}:`)
                        )
                      )
                      || (
                        publicTaskSnapshot?.task_id
                        && approvalActionMessageId.startsWith(`task:${publicTaskSnapshot.task_id}:`)
                      )
                      || (fallbackApprovalItem && approvalActionMessageId === fallbackApprovalItem.id),
                    )}
                    onCopy={() => void copyMessage(message)}
                    onRetry={() => void retryMessage(message)}
                    onApprove={() => void (
                      fallbackApprovalItem
                        ? resolveApprovalItem(fallbackApprovalItem, 'approve')
                        : resolveApprovalMessage(message, 'approve')
                    )}
                    onApproveTaskApproval={(task, approval) => void resolveYachiyoTaskApproval(task, approval, 'approve')}
                    onCancelTask={cancelYachiyoTaskFromCard}
                    onReject={() => void (
                      fallbackApprovalItem
                        ? resolveApprovalItem(fallbackApprovalItem, 'reject')
                        : resolveApprovalMessage(message, 'reject')
                    )}
                    onRejectTaskApproval={(task, approval) => void resolveYachiyoTaskApproval(task, approval, 'reject')}
                    onOpenRunDetails={openRunDetails}
                    onOpenWorkflowStudio={openWorkflowStudio}
                    onRunTaskRecoveryAction={(task, action) => void runYachiyoTaskRecoveryAction(task, action)}
                    registerMessageNode={registerMessageNode}
                    runnables={runnables}
                  />
                );
              })}
              <div className="chat-bottom-anchor" aria-hidden="true" />
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
            conversationTransitionLocked={conversationTransitionLocked}
            fileInputRef={fileInputRef}
            imageAttachDisabled={imageAttachDisabled}
            input={input}
            inputRef={inputRef}
            isProcessing={isProcessing}
            isSending={isSending}
            mentionActiveIndex={mentionActiveIndex}
            mentionSuggestions={mentionSuggestions}
            processingCount={processingCount}
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

function uniqueCurrentTaskSnapshots(
  snapshotsById: Record<string, AgentTaskSnapshot>,
  currentSessionId: string,
): AgentTaskSnapshot[] {
  const seen = new Set<string>();
  const tasks: AgentTaskSnapshot[] = [];
  Object.values(snapshotsById).forEach((task) => {
    const taskId = String(task.task_id || '').trim();
    if (!taskId || seen.has(taskId)) return;
    const conversationId = String(task.conversation_id || '').trim();
    if (currentSessionId && conversationId && conversationId !== currentSessionId) return;
    seen.add(taskId);
    tasks.push(task);
  });
  return tasks;
}
