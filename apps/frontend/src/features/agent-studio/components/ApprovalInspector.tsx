import type { RunSpec } from '../types';
import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import type { RunTimelineSnapshot } from '../../yachiyo-studio/types';
import { RunApprovalRequest } from './RunApprovalRequest';

export type RunPendingApproval = NonNullable<RunSpec['pending_approval']> & {
  risk_level?: string;
  status?: string;
};

type ApprovalInspectorProps = {
  busy: boolean;
  onApproveSelectedRun: () => Promise<unknown>;
  onRejectSelectedRun: () => Promise<unknown>;
  onRunAction: (action: () => Promise<unknown> | unknown, label: string) => void;
  runKindLabel: (kind: string) => string;
  selectedPublicRunTimeline: RunTimelineSnapshot | null;
  selectedRun: RunSpec;
  selectedRunApproval: RunPendingApproval | null;
};

export function ApprovalInspector({
  busy,
  onApproveSelectedRun,
  onRejectSelectedRun,
  onRunAction,
  runKindLabel,
  selectedPublicRunTimeline,
  selectedRun,
  selectedRunApproval,
}: ApprovalInspectorProps) {
  const hasPendingPublicApproval = Boolean(
    selectedPublicRunTimeline?.pending_approval
    || selectedPublicRunTimeline?.approvals?.some((approval) => approval.status === 'pending'),
  );
  if (!(selectedRun.status === 'approval_required' || hasPendingPublicApproval) || !selectedRunApproval?.tool) {
    return null;
  }

  return (
    <section className="run-approval-box" data-testid="agent-run-detail-approval">
      <RuntimeApprovalCard
        approval={{
          approval_id: selectedRunApproval.approval_id || selectedRun.run_id,
          description: selectedRunApproval.tool === 'workflow.approval'
            ? '这个 Workflow 审批节点需要人工确认后才会继续。'
            : '这个工具调用需要人工确认后才会继续当前 Run。',
          input_preview: typeof selectedRunApproval.input_preview === 'string'
            ? { preview: selectedRunApproval.input_preview }
            : selectedRunApproval.input_preview,
          status: selectedRunApproval.status || 'pending',
          title: `Approval Required · ${selectedRunApproval.tool}`,
          tool_name: selectedRunApproval.tool,
        }}
        actions={(
          <>
            <button type="button" className="primary-action" data-testid="agent-run-detail-approval-approve" disabled={busy} onClick={() => onRunAction(onApproveSelectedRun, '批准工具调用')}>批准</button>
            <button type="button" className="danger-action" data-testid="agent-run-detail-approval-reject" disabled={busy} onClick={() => onRunAction(onRejectSelectedRun, '拒绝工具调用')}>拒绝</button>
          </>
        )}
        actionsClassName="run-approval-actions"
        actionsTestId="agent-run-detail-approval-actions"
        className="studio-runtime-approval"
        testId="agent-run-detail-approval-card"
      />
      <RunApprovalRequest
        inputPreview={selectedRunApproval.input_preview}
        runGoal={selectedRun.user_goal || ''}
        runId={selectedRun.run_id}
        runLabel={selectedRun.runnable_name || runKindLabel(selectedRun.kind)}
        tool={selectedRunApproval.tool}
      />
    </section>
  );
}
