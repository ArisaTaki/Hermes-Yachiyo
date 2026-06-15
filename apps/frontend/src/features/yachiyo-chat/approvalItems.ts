import type { ComposerApprovalSource } from './components/ComposerApprovalNotice';
import type { ApprovalRequestDetails } from './components/MessageApprovalRequestCard';

export type ChatApprovalParticipant = {
  kind?: 'main' | 'agent' | 'workflow' | 'group' | string;
  id?: string;
  name?: string;
  nickname?: string;
};

export type ChatApprovalPending = {
  approval_id?: unknown;
  tool?: unknown;
  input_preview?: unknown;
  requested_at?: unknown;
};

export type ChatApprovalMetadata = {
  sender?: ChatApprovalParticipant;
  delegated_goal?: unknown;
  group_goal?: unknown;
  run_id?: unknown;
  workflow_run_id?: unknown;
  run_status?: unknown;
  workflow_status?: unknown;
  pending_approval?: ChatApprovalPending | Record<string, unknown>;
  workflow_waiting_child_run_id?: unknown;
  workflow_waiting_node?: unknown;
  workflow_waiting_tool?: unknown;
  workflow_waiting_pending_approval?: ChatApprovalPending | Record<string, unknown>;
};

export type ChatApprovalMessage = {
  id?: string;
  role?: string;
  content?: string;
  text?: string;
  created_at?: string;
  metadata?: ChatApprovalMetadata;
  activity_events?: ChatApprovalActivityEvent[];
};

export type ChatApprovalActivityEvent = {
  event_id?: string;
  title?: string;
  detail?: string;
  tool_name?: string;
  status?: string;
  created_at?: string;
  metadata?: {
    run_id?: unknown;
    workflow_run_id?: unknown;
    run_status?: unknown;
    pending_approval?: ChatApprovalPending | Record<string, unknown>;
  };
};

export type ChatApprovalRun = {
  run_id?: string;
  agent_run_id?: string;
  workflow_run_id?: string;
  kind?: string;
  runnable_name?: string;
  status?: string;
  user_goal?: string;
  updated_at?: string;
  pending_approval?: ChatApprovalPending | Record<string, unknown>;
};

export type RunApprovalDetailOverride = {
  signature: string;
  details: ApprovalRequestDetails;
  createdAt?: string;
};

export type ComposerApprovalItem = {
  id: string;
  approvalId?: string;
  messageId?: string;
  runId: string;
  runStatus: string;
  createdAt?: string;
  details: ApprovalRequestDetails;
  source: ComposerApprovalSource;
};

export function approvalRequestDetails(message: ChatApprovalMessage): ApprovalRequestDetails {
  const pending = message.metadata?.pending_approval || {};
  const preview = pending.input_preview;
  const text = message.content || message.text || '';
  const tool = String(pending.tool || approvalToolFromContent(text) || 'tool');
  const requester = participantDisplayName(message.metadata?.sender) || messageRoleLabel(message);
  const goal = String(message.metadata?.delegated_goal || message.metadata?.group_goal || approvalGoalFromContent(text) || '').trim();
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
      codeLanguage = tool === 'workspace.write_patch' ? detectApprovalCodeLanguage(content) || 'text' : 'text';
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
    const command = approvalCommandFromContent(text);
    if (command) {
      codeLanguage = 'bash';
      codeText = command;
    }
  }

  return { requester, tool, goal, codeLanguage, codeText, summary };
}

export function approvalRequestDetailsFromRun(
  run: ChatApprovalRun,
  fallbackDetails: ApprovalRequestDetails | null = null,
): ApprovalRequestDetails {
  const pending = run.pending_approval || {};
  return approvalRequestDetails({
    id: run.run_id,
    role: 'assistant',
    content: '',
    metadata: {
      delegated_goal: String(run.user_goal || fallbackDetails?.goal || ''),
      pending_approval: pending,
      sender: {
        kind: run.kind === 'workflow_run' ? 'workflow' : 'agent',
        name: String(run.runnable_name || fallbackDetails?.requester || 'Agent'),
      },
    },
  });
}

export function runApprovalOverrideFromRun(
  run: ChatApprovalRun,
  fallbackDetails: ApprovalRequestDetails | null = null,
): { runId: string; override: RunApprovalDetailOverride | null } {
  const runId = chatApprovalRunId(run);
  const pending = run.pending_approval;
  if (!runId || normalizeRunStatus(run.status) !== 'approval_required' || !pending?.tool) {
    return { runId, override: null };
  }
  return {
    runId,
    override: {
      details: approvalRequestDetailsFromRun(run, fallbackDetails),
      signature: approvalSignatureFromPending(pending),
      createdAt: String(pending.requested_at || run.updated_at || new Date().toISOString()),
    },
  };
}

export function rememberRunApprovalOverride(
  current: Record<string, RunApprovalDetailOverride>,
  run: ChatApprovalRun,
  fallbackDetails: ApprovalRequestDetails | null = null,
) {
  const { runId, override } = runApprovalOverrideFromRun(run, fallbackDetails);
  if (!runId) return current;
  if (!override) return forgetRunApprovalOverride(current, runId);
  return {
    ...current,
    [runId]: override,
  };
}

export function forgetRunApprovalOverride(
  current: Record<string, RunApprovalDetailOverride>,
  runId: string,
) {
  const normalizedRunId = String(runId || '').trim();
  if (!normalizedRunId || !current[normalizedRunId]) return current;
  const next = { ...current };
  delete next[normalizedRunId];
  return next;
}

export function isWorkflowApprovalDetails(details: ApprovalRequestDetails) {
  return details.tool === 'workflow.approval';
}

export function messageApprovalSignature(message: ChatApprovalMessage) {
  return approvalSignatureFromPending(message.metadata?.pending_approval);
}

export function approvalSignatureFromPending(pending: unknown) {
  if (!isRecord(pending)) return 'none';
  const approvalId = stringValue(pending.approval_id);
  const requestedAt = stringValue(pending.requested_at);
  const tool = stringValue(pending.tool);
  const preview = approvalPreviewFallback(pending.input_preview).slice(0, 220);
  const raw = [approvalId, requestedAt, tool, preview].filter(Boolean).join('|') || 'pending';
  return raw.replace(/[^A-Za-z0-9_.:-]+/g, '_').slice(0, 240);
}

export function approvalIdFromPending(pending: unknown) {
  return isRecord(pending) ? stringValue(pending.approval_id) : '';
}

export function nextApprovalStatusText(run: { pending_approval?: { tool?: unknown; input_preview?: unknown } | Record<string, unknown> }) {
  const pending = isRecord(run.pending_approval) ? run.pending_approval : {};
  const tool = String(pending.tool || 'tool');
  const preview = pending.input_preview;
  let detail = '';
  if (isRecord(preview)) {
    detail = stringValue(preview.command || preview.path || preview.file || preview.filename);
  } else {
    detail = stringValue(preview);
  }
  const suffix = detail ? `：${compactApprovalStatusText(detail, 54)}` : '';
  return `还有新的工具审批待确认：${tool}${suffix}`;
}

export function approvalRequiredMessages(messages: ChatApprovalMessage[]) {
  return messages.filter((message) => (
    hasActionableApproval(message)
    && Boolean(message.id)
  ));
}

export function approvalRequiredItems(
  messages: ChatApprovalMessage[],
  resolvedItemIds: string[] = [],
  runApprovalOverrides: Record<string, RunApprovalDetailOverride> = {},
): ComposerApprovalItem[] {
  const resolved = new Set(resolvedItemIds);
  const messageApprovals = approvalRequiredMessages(messages).map((message) => {
    const runId = messageRunId(message);
    const override = runId ? runApprovalOverrides[runId] : undefined;
    const signature = override?.signature || messageApprovalSignature(message);
    return {
      id: `message:${message.id || ''}:${signature}`,
      approvalId: approvalIdFromPending(message.metadata?.pending_approval),
      messageId: message.id,
      runId,
      runStatus: messageRunStatus(message),
      createdAt: override?.createdAt || message.created_at,
      details: override?.details || approvalRequestDetails(message),
      source: 'message' as const,
    };
  }).filter((item) => item.id && item.runId && !resolved.has(item.id));
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
      const runStatus = normalizeRunStatus(event.metadata?.run_status || event.status || 'approval_required');
      activityApprovals.push({
        id: itemId,
        approvalId: approvalIdFromPending(event.metadata?.pending_approval),
        messageId: message.id,
        runId,
        runStatus,
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
    const override = runApprovalOverrides[runId];
    const signature = override?.signature || workflowWaitingChildApprovalSignature(message);
    const itemId = `workflow-child:${message.id || messageIndex}:${signature}`;
    if (resolved.has(itemId)) continue;
    workflowChildApprovals.push({
      id: itemId,
      approvalId: approvalIdFromPending(message.metadata?.workflow_waiting_pending_approval),
      messageId: message.id,
      runId,
      runStatus: 'approval_required',
      createdAt: override?.createdAt || message.created_at,
      details: override?.details || approvalRequestDetailsFromWorkflowWaitingChild(message),
      source: 'workflow-child',
    });
  }

  return [...messageApprovals, ...activityApprovals, ...workflowChildApprovals].sort((a, b) => (
    approvalItemTime(a) - approvalItemTime(b)
  ));
}

export function hasActionableApproval(message?: ChatApprovalMessage | null) {
  const pending = message?.metadata?.pending_approval;
  return (
    messageRunStatus(message) === 'approval_required'
    && Boolean(messageRunId(message))
    && Boolean(pending && typeof pending === 'object' && String(pending.tool || '').trim())
  );
}

function approvalRequestDetailsFromActivity(event: ChatApprovalActivityEvent): ApprovalRequestDetails {
  const pending = event.metadata?.pending_approval || {};
  return approvalRequestDetails({
    id: event.event_id,
    role: 'assistant',
    content: `${event.title || ''}\n${event.detail || ''}`,
    metadata: {
      pending_approval: pending,
      sender: { kind: 'agent', name: activityApprovalRequester(event) },
    },
  });
}

function approvalRequestDetailsFromWorkflowWaitingChild(message: ChatApprovalMessage): ApprovalRequestDetails {
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
  const pending = isRecord(metadata.workflow_waiting_pending_approval)
    ? metadata.workflow_waiting_pending_approval
    : null;
  if (pending?.tool) {
    const details = approvalRequestDetails({
      id: message.id,
      role: 'assistant',
      content: message.content || message.text || '',
      metadata: {
        delegated_goal: approvalGoalFromContent(message.content || message.text || ''),
        pending_approval: pending,
        sender: { kind: 'agent', name: requester },
      },
    });
    return {
      ...details,
      requester,
      goal: details.goal,
      summary: [...summary, ...details.summary],
    };
  }
  return {
    requester,
    tool,
    goal: approvalGoalFromContent(message.content || message.text || ''),
    codeLanguage: tool === 'terminal.run' ? 'bash' : 'text',
    codeText: '',
    summary,
  };
}

function activityApprovalRequester(event: ChatApprovalActivityEvent) {
  const title = String(event.title || '').trim();
  return title
    .replace(/\s*(等待审批|请求执行工具调用|请求工具调用|委派失败|委派完成)\s*$/u, '')
    .trim() || String(event.tool_name || 'Agent').trim();
}

function activityApprovalSignature(event: ChatApprovalActivityEvent) {
  return approvalSignatureFromPending(event.metadata?.pending_approval);
}

function workflowWaitingChildApprovalSignature(message: ChatApprovalMessage) {
  const metadata = message.metadata || {};
  const raw = [
    metadata.workflow_waiting_child_run_id,
    metadata.workflow_waiting_tool,
    metadata.workflow_waiting_node,
    approvalSignatureFromPending(metadata.workflow_waiting_pending_approval),
    messageRunId(message),
  ].map(stringValue).filter(Boolean).join('|') || 'workflow-child-approval';
  return raw.replace(/[^A-Za-z0-9_.:-]+/g, '_').slice(0, 240);
}

function hasActionableActivityApproval(event?: ChatApprovalActivityEvent | null) {
  const eventStatus = String(event?.status || '').trim();
  if (['completed', 'success', 'failed', 'error', 'cancelled'].includes(eventStatus)) return false;
  const pending = event?.metadata?.pending_approval;
  return (
    (eventStatus === 'approval_required' || String(event?.metadata?.run_status || '').trim() === 'approval_required')
    && Boolean(activityRunId(event))
    && Boolean(pending && typeof pending === 'object' && String(pending.tool || '').trim())
  );
}

function workflowWaitingChildApprovalRunId(message?: ChatApprovalMessage | null) {
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

function participantDisplayName(participant?: ChatApprovalParticipant | null) {
  return String(participant?.nickname || participant?.name || participant?.id || '').trim();
}

function messageRoleLabel(message: ChatApprovalMessage) {
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

function messageRunStatus(message?: ChatApprovalMessage | null) {
  return normalizeRunStatus(message?.metadata?.run_status || message?.metadata?.workflow_status || '');
}

function messageRunId(message?: ChatApprovalMessage | null) {
  return String(message?.metadata?.run_id || message?.metadata?.workflow_run_id || '').trim();
}

function chatApprovalRunId(run?: ChatApprovalRun | null) {
  return String(run?.run_id || run?.agent_run_id || run?.workflow_run_id || '').trim();
}

function activityRunId(event?: ChatApprovalActivityEvent | null) {
  return String(event?.metadata?.run_id || event?.metadata?.workflow_run_id || '').trim();
}

function normalizeRunStatus(status?: unknown) {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

function compactApprovalStatusText(text: string, maxLength = 96) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (!normalized) return '任务执行失败';
  return normalized.length > maxLength ? `${normalized.slice(0, maxLength - 3)}...` : normalized;
}

function detectApprovalCodeLanguage(code: string) {
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
  if (/^@@\s|(?:^|\n)\+[^+\n]/.test(trimmed) && /(?:^|\n)-[^-\n]/.test(trimmed)) return 'diff';
  if (/\bfunc\s+\w+\s*\(|\bpackage\s+main\b|:=/.test(trimmed)) return 'go';
  if (/\b(def|class|from|import)\s+\w+|__name__/.test(trimmed)) return 'python';
  if (/\b(const|let|var|function|interface|type)\s+\w+|=>/.test(trimmed)) return 'typescript';
  if (/^\s*(#!|npm\s|pnpm\s|yarn\s|curl\s|git\s)/m.test(trimmed)) return 'bash';
  if (/^\s*[\w.-]+\s*:\s+\S/m.test(trimmed)) return 'yaml';
  return '';
}

function stringValue(value: unknown) {
  if (value === undefined || value === null) return '';
  return String(value).trim();
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value && typeof value === 'object' && !Array.isArray(value));
}
