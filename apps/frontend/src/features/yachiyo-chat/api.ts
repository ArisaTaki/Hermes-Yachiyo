import { apiGet, apiPost } from '../../lib/bridge';
import type {
  AgentTaskSnapshot,
  ArtifactContentSnapshot,
  ChatRunnableCatalogSnapshot,
  PendingAttachment,
  RunEventPageSnapshot,
  RunTimelineSnapshot,
  StartChatTaskRequest,
  YachiyoReadinessSnapshot,
} from './types';

export type LegacyChatMessageResult = {
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

export type SendLegacyChatMessageRequest = {
  text: string;
  attachments: PendingAttachment[];
  client_message_id: string;
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

export async function listYachiyoTasks(conversationId?: string): Promise<AgentTaskSnapshot[]> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
  const payload = await apiGet<{ tasks?: AgentTaskSnapshot[] }>(`/yachiyo/tasks${query}`);
  return payload.tasks || [];
}

export async function startYachiyoTask(request: StartChatTaskRequest): Promise<AgentTaskSnapshot> {
  return apiPost('/yachiyo/tasks', request);
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

export async function listYachiyoChatRunnableCatalog(): Promise<ChatRunnableCatalogSnapshot> {
  const payload = await apiGet<Partial<ChatRunnableCatalogSnapshot>>('/yachiyo/runnables');
  return {
    agents: payload.agents || [],
    workflows: payload.workflows || [],
  };
}

export async function getYachiyoChatRunTaskSnapshot(runId: string): Promise<AgentTaskSnapshot> {
  return getYachiyoTask(runId);
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

export async function approveYachiyoTask(
  taskId: string,
  approvalId?: string,
): Promise<AgentTaskSnapshot> {
  return apiPost(`/yachiyo/tasks/${encodeURIComponent(taskId)}/approve`, {
    approval_id: approvalId || undefined,
  });
}

export async function rejectYachiyoTask(
  taskId: string,
  approvalId?: string,
  reason = '',
): Promise<AgentTaskSnapshot> {
  return apiPost(`/yachiyo/tasks/${encodeURIComponent(taskId)}/reject`, {
    approval_id: approvalId || undefined,
    reason: reason || undefined,
  });
}

export async function cancelYachiyoTask(taskId: string): Promise<AgentTaskSnapshot> {
  return apiPost(`/yachiyo/tasks/${encodeURIComponent(taskId)}/cancel`, {});
}
