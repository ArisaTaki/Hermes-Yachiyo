import type { RunSpec } from '../types';
import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import { RuntimeApprovalGate } from '../../runtime-shared/components/RuntimeApprovalGate';
import type { ApprovalCardSnapshot, RunTimelineSnapshot } from '../../yachiyo-studio/types';
import { RunApprovalRequest } from './RunApprovalRequest';

export type RunPendingApproval = NonNullable<RunSpec['pending_approval']> & {
  risk_level?: string;
  status?: string;
};

type ApprovalInspectorProps = {
  approvalHistory?: ApprovalCardSnapshot[];
  approvalHistorySource?: string;
  busy: boolean;
  onApproveRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onRejectRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onRunAction: (action: () => Promise<unknown> | unknown, label: string) => void;
  runKindLabel: (kind: string) => string;
  selectedPublicRunTimeline: RunTimelineSnapshot | null;
  selectedRun: RunSpec;
  selectedRunApproval: RunPendingApproval | null;
};

export function ApprovalInspector({
  approvalHistory,
  approvalHistorySource = 'RunTimelineSnapshot approval facts',
  busy,
  onApproveRunById,
  onRejectRunById,
  onRunAction,
  runKindLabel,
  selectedPublicRunTimeline,
  selectedRun,
  selectedRunApproval,
}: ApprovalInspectorProps) {
  const approvals = approvalHistory || selectedPublicRunTimeline?.approvals || [];
  const hasPendingPublicApproval = Boolean(
    selectedPublicRunTimeline?.pending_approval
    || selectedPublicRunTimeline?.approvals?.some((approval) => approval.status === 'pending'),
  );
  const showApprovalGate = (
    (selectedRun.status === 'approval_required' || hasPendingPublicApproval)
    && Boolean(selectedRunApproval?.tool)
  );
  const approvalActionRunId = (
    selectedRunApproval?.source_run_id
    || selectedRunApproval?.run_id
    || selectedRun.run_id
  );
  const approvalSelectedRunId = approvalActionRunId === selectedRun.run_id ? undefined : selectedRun.run_id;
  if (!showApprovalGate && !approvals.length) {
    return null;
  }

  return (
    <>
      {showApprovalGate && selectedRunApproval ? (
        <RuntimeApprovalGate
          actionsClassName="run-approval-actions"
          actionsTestId="agent-run-detail-approval-actions"
          approval={{
            approval_id: selectedRunApproval.approval_id || selectedRun.run_id,
            description: selectedRunApproval.tool === 'workflow.approval'
              ? '这个 Workflow 审批节点需要人工确认后才会继续。'
              : '这个工具调用需要人工确认后才会继续当前 Run。',
            input_preview: typeof selectedRunApproval.input_preview === 'string'
              ? { preview: selectedRunApproval.input_preview }
              : selectedRunApproval.input_preview,
            open_in_studio_url: selectedRunApproval.open_in_studio_url,
            policy_reason: selectedRunApproval.policy_reason,
            planning_reason: selectedRunApproval.planning_reason,
            decision_id: selectedRunApproval.decision_id,
            plan_id: selectedRunApproval.plan_id,
            tool_plan_id: selectedRunApproval.tool_plan_id,
            intent_kind: selectedRunApproval.intent_kind,
            step_id: selectedRunApproval.step_id,
            planner_step_id: selectedRunApproval.planner_step_id,
            capability_id: selectedRunApproval.capability_id,
            replan_request_id: selectedRunApproval.replan_request_id,
            replan_trigger: selectedRunApproval.replan_trigger,
            replan_triggers: selectedRunApproval.replan_triggers,
            replan_signal_ids: selectedRunApproval.replan_signal_ids,
            runtime_doctrine: selectedRunApproval.runtime_doctrine,
            runtime_stage: selectedRunApproval.runtime_stage,
            runtime_role: selectedRunApproval.runtime_role,
            requires_observation: selectedRunApproval.requires_observation,
            requires_post_action_verification: selectedRunApproval.requires_post_action_verification,
            task_workspace_items: selectedRunApproval.task_workspace_items,
            task_verification_targets: selectedRunApproval.task_verification_targets,
            requested_at: selectedRunApproval.requested_at,
            resolved_at: selectedRunApproval.resolved_at,
            risk_level: selectedRunApproval.risk_level,
            run_id: selectedRunApproval.run_id || selectedRun.run_id,
            source_run_id: selectedRunApproval.source_run_id || undefined,
            status: selectedRunApproval.status || 'pending',
            title: `Approval Required · ${selectedRunApproval.tool}`,
            tool_name: selectedRunApproval.tool,
          }}
          approveButtonClassName="primary-action"
          approveTestId="agent-run-detail-approval-approve"
          busy={busy}
          cardClassName="studio-runtime-approval"
          cardTestId="agent-run-detail-approval-card"
          cardVariant="inspector"
          className="run-approval-box"
          onApprove={() => onRunAction(
            () => onApproveRunById(approvalActionRunId, approvalSelectedRunId),
            '批准工具调用',
          )}
          onReject={() => onRunAction(
            () => onRejectRunById(approvalActionRunId, approvalSelectedRunId),
            '拒绝工具调用',
          )}
          rejectButtonClassName="danger-action"
          rejectTestId="agent-run-detail-approval-reject"
          testId="agent-run-detail-approval"
        >
          <RunApprovalRequest
            inputPreview={selectedRunApproval.input_preview}
            runGoal={selectedRun.user_goal || ''}
            runId={selectedRun.run_id}
            runLabel={selectedRun.runnable_name || runKindLabel(selectedRun.kind)}
            tool={selectedRunApproval.tool || 'approval'}
          />
        </RuntimeApprovalGate>
      ) : null}
      {approvals.length ? (
        <details className="run-detail-block run-detail-fold run-approval-history" data-testid="agent-run-detail-approval-history" open>
          <summary className="run-detail-section-head">
            <div>
              <h4>Approval History · {approvals.length}</h4>
              <span>{approvalHistorySource}</span>
            </div>
          </summary>
          <div className="run-detail-fold-body run-approval-history-list" data-testid="agent-run-detail-approval-history-list">
            {approvals.map((approval, index) => (
              <RuntimeApprovalCard
                approval={approval}
                className="studio-runtime-approval history"
                key={approval.approval_id || `${approval.run_id || 'approval'}-${index}`}
                testId="agent-run-detail-approval-history-card"
                variant="inspector"
              />
            ))}
          </div>
        </details>
      ) : null}
    </>
  );
}
