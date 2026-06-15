import {
  approveYachiyoRunApproval,
  getYachiyoRunTimeline,
  rejectYachiyoRunApproval,
} from '../yachiyo-studio/api';
import type { ApprovalCardSnapshot, RunTimelineSnapshot } from '../runtime-shared/types';
import type { ChatApprovalPending, ChatApprovalRun } from './approvalItems';

export async function getChatRunSnapshot(runId: string): Promise<ChatApprovalRun> {
  return chatRunSnapshotFromTimeline(await getYachiyoRunTimeline(runId));
}

export async function approveChatRunApproval(runId: string): Promise<ChatApprovalRun> {
  return chatRunSnapshotFromTimeline(await approveYachiyoRunApproval(runId));
}

export async function rejectChatRunApproval(
  runId: string,
  reason = '',
): Promise<ChatApprovalRun> {
  return chatRunSnapshotFromTimeline(await rejectYachiyoRunApproval(runId, reason));
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
