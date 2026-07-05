import { apiGet, apiPatch, apiPost, restartDesktopBridge } from '../../lib/bridge';
import { isMissingGroupEditRouteError } from './messageGroups';
import type {
  AgentTaskSnapshot,
  ArtifactContentSnapshot,
  ChatRunnableCatalogSnapshot,
  ChatSessionContext,
  PendingAttachment,
  RuntimeExecutionEnvelopeSnapshot,
  RunEventPageSnapshot,
  RunTimelineSnapshot,
  StartChatTaskRequest,
  YachiyoReadinessSnapshot,
} from './types';

export type LegacyChatMessageResult = {
  agent_task?: AgentTaskSnapshot | null;
  ok?: boolean;
  error?: string;
  task_id?: string;
  runnable_command?: boolean;
  agent_run_id?: string;
  workflow_run_id?: string;
  run_id?: string;
  run_status?: string;
  status?: string;
};

export type LegacyChatRunnableResultSnapshot = {
  runnableCommand: boolean;
  runId: string;
  status: string;
  label: 'Agent' | 'Workflow';
  error: string;
};

export type SendLegacyChatMessageRequest = {
  text: string;
  attachments: PendingAttachment[];
  client_message_id: string;
};

export type ChatGroupSessionResult = {
  ok?: boolean;
  error?: string;
  session_id?: string;
  session_context?: ChatSessionContext;
};

type ChatGroupSessionRequest = {
  avatarUrl: string;
  defaultName: string;
  name: string;
  participantIds: string[];
};

type UpdateChatGroupSessionRequest = ChatGroupSessionRequest & {
  sessionId: string;
};

export async function getYachiyoReadiness(): Promise<YachiyoReadinessSnapshot> {
  return apiGet('/yachiyo/readiness');
}

export async function sendLegacyChatMessage(
  request: SendLegacyChatMessageRequest,
): Promise<LegacyChatMessageResult> {
  return apiPost('/ui/chat/messages', request);
}

export async function retryLegacyChatMessage(messageId: string): Promise<LegacyChatMessageResult> {
  return apiPost('/ui/chat/messages/retry', {
    message_id: messageId,
  });
}

export async function createChatGroupSession(
  request: ChatGroupSessionRequest,
): Promise<ChatGroupSessionResult> {
  const result = await apiPost<ChatGroupSessionResult>('/ui/chat/groups', {
    name: request.name.trim() || request.defaultName,
    avatar_url: request.avatarUrl.trim(),
    participant_ids: request.participantIds,
  });
  if (result.ok === false) throw new Error(result.error || '创建群组失败');
  return result;
}

export async function updateChatGroupSession(
  request: UpdateChatGroupSessionRequest,
): Promise<ChatGroupSessionResult> {
  if (!request.sessionId) throw new Error('当前群组不可用');
  const result = await apiPatch<ChatGroupSessionResult>(
    `/ui/chat/groups/${encodeURIComponent(request.sessionId)}`,
    {
      name: request.name.trim() || request.defaultName,
      avatar_url: request.avatarUrl.trim(),
      participant_ids: request.participantIds,
    },
  );
  if (result.ok === false) throw new Error(result.error || '保存群组失败');
  return result;
}

export async function updateChatGroupSessionWithRecovery(
  request: UpdateChatGroupSessionRequest,
  options: { onRestarting?: () => void } = {},
): Promise<ChatGroupSessionResult> {
  try {
    return await updateChatGroupSession(request);
  } catch (error) {
    if (!isMissingGroupEditRouteError(error)) throw error;
    options.onRestarting?.();
    const restartResult = await restartDesktopBridge();
    if (!restartResult.success) {
      throw new Error('当前 Bridge 尚未加载群组编辑接口，请重启 Oha-Yachiyo 后重试');
    }
    return await updateChatGroupSession(request);
  }
}

export function legacyChatRunnableResult(
  result: LegacyChatMessageResult,
): LegacyChatRunnableResultSnapshot {
  return {
    runnableCommand: Boolean(result.runnable_command),
    runId: String(result.run_id || result.agent_run_id || result.workflow_run_id || '').trim(),
    status: normalizeLegacyRunStatus(result.run_status || result.status || ''),
    label: result.workflow_run_id ? 'Workflow' : 'Agent',
    error: String(result.error || '').trim(),
  };
}

function normalizeLegacyRunStatus(status?: unknown) {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

export async function listYachiyoTasks(conversationId?: string): Promise<AgentTaskSnapshot[]> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
  const payload = await apiGet<{ tasks?: AgentTaskSnapshot[] }>(`/yachiyo/tasks${query}`);
  return payload.tasks || [];
}

export async function startYachiyoTask(request: StartChatTaskRequest): Promise<AgentTaskSnapshot> {
  return apiPost('/yachiyo/tasks', request);
}

export type YachiyoTaskReplanRecoveryActionRequest = {
  request_id: string;
  action_id?: string;
  title?: string;
  continue_to_model?: boolean;
  conversation_id?: string | null;
  metadata?: Record<string, unknown>;
};

export async function startYachiyoTaskReplanRecoveryAction(
  taskId: string,
  request: YachiyoTaskReplanRecoveryActionRequest,
): Promise<AgentTaskSnapshot> {
  return apiPost(
    `/yachiyo/tasks/${encodeURIComponent(taskId)}/replan-recovery-actions/start`,
    request,
  );
}

export type PlanYachiyoTaskExecutionRequest = {
  prompt: string;
  allowed_tools?: string[];
  metadata?: Record<string, unknown>;
  direct?: boolean;
};

export async function planYachiyoTaskExecution(
  request: PlanYachiyoTaskExecutionRequest,
): Promise<RuntimeExecutionEnvelopeSnapshot> {
  return apiPost('/yachiyo/tasks/plan', request);
}

export async function getYachiyoTask(taskId: string): Promise<AgentTaskSnapshot> {
  return apiGet(`/yachiyo/tasks/${encodeURIComponent(taskId)}`);
}

export async function getYachiyoTaskTimeline(taskId: string): Promise<RunTimelineSnapshot> {
  return apiGet(`/yachiyo/tasks/${encodeURIComponent(taskId)}/timeline`);
}

export async function listYachiyoTaskEvents(
  taskId: string,
  afterSequence = 0,
  limit = 200,
): Promise<RunEventPageSnapshot> {
  const query = new URLSearchParams({
    after_sequence: String(Math.max(0, afterSequence)),
    limit: String(Math.max(1, Math.min(500, limit))),
  });
  return apiGet(`/yachiyo/tasks/${encodeURIComponent(taskId)}/events?${query.toString()}`);
}

export async function readYachiyoTaskArtifact(
  taskId: string,
  path: string,
): Promise<ArtifactContentSnapshot> {
  const encodedPath = path.split('/').map((part) => encodeURIComponent(part)).join('/');
  return apiGet(`/yachiyo/tasks/${encodeURIComponent(taskId)}/artifacts/${encodedPath}`);
}

export async function readYachiyoChatRunArtifact(
  runId: string,
  path: string,
): Promise<ArtifactContentSnapshot> {
  const encodedPath = path.split('/').map((part) => encodeURIComponent(part)).join('/');
  return apiGet(`/ui/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}`);
}

export async function listYachiyoChatRunnableCatalog(): Promise<ChatRunnableCatalogSnapshot> {
  const payload = await apiGet<Partial<ChatRunnableCatalogSnapshot>>('/yachiyo/runnables');
  return {
    agents: payload.agents || [],
    workflows: payload.workflows || [],
    groups: payload.groups || [],
  };
}

export async function getYachiyoChatRunTaskSnapshot(runId: string): Promise<AgentTaskSnapshot> {
  return getYachiyoTask(runId);
}

export async function getLegacyChatRunSnapshot(runId: string): Promise<RunTimelineSnapshot> {
  return apiGet(`/ui/runs/${encodeURIComponent(runId)}`);
}

export async function approveYachiyoChatRunApproval(runId: string): Promise<AgentTaskSnapshot> {
  return approveYachiyoTask(runId);
}

export async function rejectYachiyoChatRunApproval(
  runId: string,
  reason = '',
): Promise<AgentTaskSnapshot> {
  return rejectYachiyoTask(runId, undefined, reason);
}

export async function approveLegacyChatRunApproval(runId: string): Promise<RunTimelineSnapshot> {
  return apiPost(`/ui/runs/${encodeURIComponent(runId)}/approval/approve`, {});
}

export async function rejectLegacyChatRunApproval(
  runId: string,
  reason = '',
): Promise<RunTimelineSnapshot> {
  return apiPost(`/ui/runs/${encodeURIComponent(runId)}/approval/reject`, reason ? { reason } : {});
}

export async function approveYachiyoTask(
  taskId: string,
  approvalId?: string,
): Promise<AgentTaskSnapshot> {
  return apiPost(yachiyoTaskApprovalPath(taskId, approvalId, 'approve'), {
    approval_id: approvalId || undefined,
  });
}

export async function rejectYachiyoTask(
  taskId: string,
  approvalId?: string,
  reason = '',
): Promise<AgentTaskSnapshot> {
  return apiPost(yachiyoTaskApprovalPath(taskId, approvalId, 'reject'), {
    approval_id: approvalId || undefined,
    reason: reason || undefined,
  });
}

export async function cancelYachiyoTask(taskId: string): Promise<AgentTaskSnapshot> {
  return apiPost(`/yachiyo/tasks/${encodeURIComponent(taskId)}/cancel`, {});
}

function yachiyoTaskApprovalPath(
  taskId: string,
  approvalId: string | undefined,
  action: 'approve' | 'reject',
) {
  const encodedTaskId = encodeURIComponent(taskId);
  const cleanApprovalId = String(approvalId || '').trim();
  if (!cleanApprovalId) return `/yachiyo/tasks/${encodedTaskId}/${action}`;
  return `/yachiyo/tasks/${encodedTaskId}/approvals/${encodeURIComponent(cleanApprovalId)}/${action}`;
}
