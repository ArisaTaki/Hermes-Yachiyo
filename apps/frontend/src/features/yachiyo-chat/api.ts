import { apiGet, apiPost } from '../../lib/bridge';
import type { AgentTaskSnapshot, StartChatTaskRequest, YachiyoReadinessSnapshot } from './types';

export async function getYachiyoReadiness(): Promise<YachiyoReadinessSnapshot> {
  return apiGet('/yachiyo/chat/readiness');
}

export async function listYachiyoTasks(conversationId?: string): Promise<AgentTaskSnapshot[]> {
  const query = conversationId ? `?conversation_id=${encodeURIComponent(conversationId)}` : '';
  const payload = await apiGet<{ tasks?: AgentTaskSnapshot[] }>(`/yachiyo/chat/tasks${query}`);
  return payload.tasks || [];
}

export async function startYachiyoTask(request: StartChatTaskRequest): Promise<AgentTaskSnapshot> {
  return apiPost('/yachiyo/chat/tasks', request);
}

export async function getYachiyoTask(taskId: string): Promise<AgentTaskSnapshot> {
  return apiGet(`/yachiyo/chat/tasks/${encodeURIComponent(taskId)}`);
}

export async function approveYachiyoTask(
  taskId: string,
  approvalId?: string,
): Promise<AgentTaskSnapshot> {
  return apiPost(`/yachiyo/chat/tasks/${encodeURIComponent(taskId)}/approve`, {
    approval_id: approvalId || undefined,
  });
}

export async function rejectYachiyoTask(
  taskId: string,
  approvalId?: string,
  reason = '',
): Promise<AgentTaskSnapshot> {
  return apiPost(`/yachiyo/chat/tasks/${encodeURIComponent(taskId)}/reject`, {
    approval_id: approvalId || undefined,
    reason: reason || undefined,
  });
}

export async function cancelYachiyoTask(taskId: string): Promise<AgentTaskSnapshot> {
  return apiPost(`/yachiyo/chat/tasks/${encodeURIComponent(taskId)}/cancel`, {});
}
