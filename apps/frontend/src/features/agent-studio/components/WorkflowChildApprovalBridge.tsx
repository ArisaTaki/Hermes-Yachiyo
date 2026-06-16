import { RuntimeApprovalGate } from '../../runtime-shared/components/RuntimeApprovalGate';
import type { RuntimeApprovalCardSnapshot } from '../../runtime-shared/components/RuntimeApprovalCard';
import type { RunSpec } from '../types';
import { RunApprovalRequest } from './RunApprovalRequest';

export type RunDetailWorkflowStepRef = {
  key: string;
  kind: 'start' | 'agent' | 'approval' | 'artifact' | 'condition' | 'parallel' | 'workflow' | 'loop' | 'unknown';
  nodeId?: string;
  label: string;
  status: string;
  childRunId?: string;
  payload?: string;
  artifactPath?: string;
  artifactCount?: number;
  task?: string;
};

type WorkflowChildApprovalBridgeProps = {
  busy: boolean;
  onApproveRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onCancelRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onOpenRunDetail: (runId: string) => void;
  onRejectRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onRunAction: (action: () => Promise<unknown> | unknown, label: string) => void;
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedRun: RunSpec;
  selectedWorkflowApprovalChildRun: RunSpec | null;
  selectedWorkflowApprovalChildRunId: string;
  selectedWorkflowApprovalStep?: RunDetailWorkflowStepRef | null;
};

export function WorkflowChildApprovalBridge({
  busy,
  onApproveRunById,
  onCancelRunById,
  onOpenRunDetail,
  onRejectRunById,
  onRunAction,
  runStatusLabel,
  runStatusTone,
  selectedRun,
  selectedWorkflowApprovalChildRun,
  selectedWorkflowApprovalChildRunId,
  selectedWorkflowApprovalStep,
}: WorkflowChildApprovalBridgeProps) {
  const pendingApproval = selectedWorkflowApprovalChildRun?.pending_approval;
  return (
    <section className="run-approval-box workflow-approval-bridge" data-testid="agent-run-detail-workflow-child-approval">
      <div className="workflow-approval-bridge-head" data-testid="agent-run-detail-workflow-child-approval-head">
        <div>
          <h4>Workflow 正在等待子 Agent 审批</h4>
          <p>
            {selectedWorkflowApprovalStep?.label || selectedWorkflowApprovalChildRun?.runnable_name || selectedWorkflowApprovalChildRunId}
            {' '}需要确认工具调用，处理后 Workflow 会继续执行后续步骤。
          </p>
          {selectedWorkflowApprovalStep?.task ? (
            <small>Step Task：{selectedWorkflowApprovalStep.task}</small>
          ) : null}
        </div>
        <span className={`run-status-pill ${runStatusTone(selectedWorkflowApprovalChildRun?.status || 'approval_required')}`}>
          {selectedWorkflowApprovalChildRun ? runStatusLabel(selectedWorkflowApprovalChildRun.status) : '加载中'}
        </span>
      </div>
      {selectedWorkflowApprovalChildRun && pendingApproval?.tool ? (
        <RuntimeApprovalGate
          actionsClassName="run-approval-actions"
          actionsTestId="agent-run-detail-workflow-child-approval-actions"
          approval={workflowChildApprovalCard(
            selectedWorkflowApprovalChildRun,
            selectedWorkflowApprovalChildRunId,
          )}
          approveButtonClassName="primary-action"
          approveLabel="批准子 Agent"
          approveTestId="agent-run-detail-workflow-child-approve"
          busy={busy}
          cardClassName="studio-runtime-approval workflow-child-runtime-approval-card"
          cardTestId="agent-run-detail-workflow-child-approval-card"
          cardVariant="inspector"
          className="workflow-child-runtime-approval"
          onApprove={() => onRunAction(
            () => onApproveRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),
            '批准子 Agent 工具调用',
          )}
          onReject={() => onRunAction(
            () => onRejectRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),
            '拒绝子 Agent 工具调用',
          )}
          rejectButtonClassName="danger-action"
          rejectLabel="拒绝子 Agent"
          rejectTestId="agent-run-detail-workflow-child-reject"
          testId="agent-run-detail-workflow-child-approval-gate"
        >
          <RunApprovalRequest
            inputPreview={pendingApproval.input_preview}
            runGoal={selectedWorkflowApprovalChildRun.user_goal || ''}
            runId={selectedWorkflowApprovalChildRun.run_id}
            runLabel={selectedWorkflowApprovalChildRun.runnable_name || 'Child Run'}
            tool={pendingApproval.tool}
          />
          <div
            className="run-approval-actions workflow-child-secondary-actions"
            data-testid="agent-run-detail-workflow-child-secondary-actions"
          >
            <button
              type="button"
              className="danger-action"
              data-testid="agent-run-detail-workflow-child-cancel"
              disabled={busy}
              onClick={() => onRunAction(
                () => onCancelRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),
                '取消子 Agent Run',
              )}
            >
              取消子 Run
            </button>
            <button
              type="button"
              className="run-timeline-child"
              data-run-id={selectedWorkflowApprovalChildRunId}
              data-run-status={selectedWorkflowApprovalChildRun?.status || 'approval_required'}
              data-testid="agent-run-detail-workflow-child-open-run"
              onClick={() => onOpenRunDetail(selectedWorkflowApprovalChildRunId)}
            >
              打开子 Run
            </button>
          </div>
        </RuntimeApprovalGate>
      ) : (
        <>
          <pre>{selectedWorkflowApprovalChildRun ? (selectedWorkflowApprovalChildRun.result || 'Child run has no approval payload.') : 'Loading child run...'}</pre>
          <div className="run-approval-actions" data-testid="agent-run-detail-workflow-child-approval-actions">
            <button
              type="button"
              className="run-timeline-child"
              data-run-id={selectedWorkflowApprovalChildRunId}
              data-run-status={selectedWorkflowApprovalChildRun?.status || 'approval_required'}
              data-testid="agent-run-detail-workflow-child-open-run"
              onClick={() => onOpenRunDetail(selectedWorkflowApprovalChildRunId)}
            >
              打开子 Run
            </button>
          </div>
        </>
      )}
    </section>
  );
}

function workflowChildApprovalCard(
  childRun: RunSpec,
  fallbackRunId: string,
): RuntimeApprovalCardSnapshot {
  const pendingApproval = childRun.pending_approval;
  const tool = pendingApproval?.tool || 'approval';
  return {
    approval_id: pendingApproval?.approval_id || fallbackRunId,
    description: '这个子 Agent 工具调用需要人工确认后，父 Workflow 才会继续。',
    input_preview: approvalInputPreview(pendingApproval?.input_preview),
    open_in_studio_url: pendingApproval?.open_in_studio_url,
    policy_reason: pendingApproval?.policy_reason,
    requested_at: pendingApproval?.requested_at,
    resolved_at: pendingApproval?.resolved_at,
    risk_level: pendingApproval?.risk_level,
    run_id: pendingApproval?.run_id || childRun.run_id,
    status: approvalStatus(pendingApproval?.status),
    title: `Child Agent Approval · ${tool}`,
    tool_name: tool,
  };
}

function approvalInputPreview(value: unknown): Record<string, unknown> {
  if (typeof value === 'string') return { preview: value };
  if (value && typeof value === 'object' && !Array.isArray(value)) {
    return value as Record<string, unknown>;
  }
  return {};
}

function approvalStatus(value: unknown): RuntimeApprovalCardSnapshot['status'] {
  if (value === 'approved' || value === 'rejected' || value === 'cancelled' || value === 'expired') {
    return value;
  }
  return 'pending';
}
