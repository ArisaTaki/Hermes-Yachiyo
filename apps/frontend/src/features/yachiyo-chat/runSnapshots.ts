import {
  approveYachiyoChatRunApproval,
  getYachiyoChatRunTaskSnapshot,
  getYachiyoTaskTimeline,
  rejectYachiyoChatRunApproval,
} from './api';
import type { ChatApprovalPending, ChatApprovalRun } from './approvalItems';
import { yachiyoTaskRunId } from './taskSnapshots';
import type { AgentTaskSnapshot, ApprovalCardSnapshot, RunTimelineSnapshot } from './types';

export async function getChatRunSnapshot(runId: string): Promise<ChatApprovalRun> {
  try {
    return chatRunSnapshotFromTimeline(await getYachiyoTaskTimeline(runId));
  } catch {
    return chatRunSnapshotFromTaskSnapshot(await getYachiyoChatRunTaskSnapshot(runId));
  }
}

export async function approveChatRunApproval(runId: string): Promise<ChatApprovalRun> {
  return chatRunSnapshotFromTaskSnapshot(await approveYachiyoChatRunApproval(runId));
}

export async function rejectChatRunApproval(
  runId: string,
  reason = '',
): Promise<ChatApprovalRun> {
  return chatRunSnapshotFromTaskSnapshot(await rejectYachiyoChatRunApproval(runId, reason));
}

export function chatRunSnapshotFromTaskSnapshot(snapshot: AgentTaskSnapshot): ChatApprovalRun {
  const runId = yachiyoTaskRunId(snapshot) || snapshot.task_id;
  const workflowRunId = chatTaskWorkflowRunId(snapshot, runId);
  const kind = workflowRunId ? 'workflow_run' : 'agent_run';
  return {
    run_id: runId,
    agent_run_id: kind === 'agent_run' ? runId : undefined,
    workflow_run_id: workflowRunId || undefined,
    kind,
    runnable_name: snapshot.title || undefined,
    status: chatRunStatusFromTaskStatus(snapshot.status),
    user_goal: snapshot.title || snapshot.summary || '',
    updated_at: snapshot.updated_at || snapshot.created_at,
    pending_approval: chatPendingApprovalFromTask(snapshot),
  };
}

export function chatRunSnapshotFromTimeline(snapshot: RunTimelineSnapshot): ChatApprovalRun {
  const kind = snapshot.workflow_run_id ? 'workflow_run' : 'agent_run';
  return {
    run_id: snapshot.run_id,
    agent_run_id: kind === 'agent_run' ? snapshot.run_id : undefined,
    workflow_run_id: kind === 'workflow_run' ? snapshot.workflow_run_id || snapshot.run_id : undefined,
    kind,
    runnable_name: snapshot.title || undefined,
    status: snapshot.status,
    user_goal: snapshot.title || '',
    updated_at: snapshot.updated_at || snapshot.created_at,
    pending_approval: chatPendingApprovalFromTimeline(snapshot),
  };
}

function chatTaskWorkflowRunId(snapshot: AgentTaskSnapshot, runId: string): string {
  for (const event of snapshot.recent_events || []) {
    const payload = event.payload || {};
    const workflowRunId = typeof payload.workflow_run_id === 'string'
      ? payload.workflow_run_id.trim()
      : '';
    if (workflowRunId) return workflowRunId;
  }
  return runId.startsWith('workflow-') ? runId : '';
}

function chatRunStatusFromTaskStatus(status: AgentTaskSnapshot['status']): string {
  if (status === 'waiting_approval') return 'approval_required';
  if (status === 'running') return 'processing';
  return status || '';
}

function chatPendingApprovalFromTask(
  snapshot: AgentTaskSnapshot,
): ChatApprovalPending | undefined {
  const approval = (snapshot.pending_approvals || [])
    .find((item) => item.status === 'pending')
    || snapshot.pending_approvals?.[0];
  if (!approval) return undefined;
  return {
    approval_id: approval.approval_id,
    tool: approval.tool_name,
    input_preview: approval.input_preview,
    requested_at: approval.requested_at,
  };
}

function chatPendingApprovalFromTimeline(
  snapshot: RunTimelineSnapshot,
): ChatApprovalPending | undefined {
  const approvals = [
    snapshot.pending_approval,
    ...(snapshot.approvals || []),
  ].filter((approval): approval is ApprovalCardSnapshot => Boolean(approval));
  const approval = approvals.find((item) => item.status === 'pending') || approvals[0];
  if (!approval) return undefined;
  return {
    approval_id: approval.approval_id,
    tool: approval.tool_name,
    input_preview: approval.input_preview,
    requested_at: approval.requested_at,
  };
}
