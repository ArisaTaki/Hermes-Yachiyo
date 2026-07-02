import type { ReactNode } from 'react';

import type { ApprovalCardSnapshot } from '../types';
import {
  approvalPreviewRecord,
  approvalPreviewTarget,
  approvalPreviewValue,
  runtimeToolDisplayLabel,
} from '../approval';

export type RuntimeApprovalCardSnapshot = Pick<
  ApprovalCardSnapshot,
  | 'approval_id'
  | 'capability_id'
  | 'description'
  | 'decision_id'
  | 'group_id'
  | 'group_run_id'
  | 'input_preview'
  | 'intent_kind'
  | 'open_in_studio_url'
  | 'plan_id'
  | 'policy_reason'
  | 'planning_reason'
  | 'planner_step_id'
  | 'requested_at'
  | 'replan_signal_ids'
  | 'resolved_at'
  | 'replan_triggers'
  | 'replan_request_id'
  | 'replan_trigger'
  | 'requires_observation'
  | 'requires_post_action_verification'
  | 'risk_level'
  | 'run_id'
  | 'runtime_doctrine'
  | 'runtime_role'
  | 'runtime_stage'
  | 'source_run_id'
  | 'source_runnable_id'
  | 'source_runnable_name'
  | 'status'
  | 'step_id'
  | 'title'
  | 'tool_name'
  | 'tool_plan_id'
  | 'workflow_id'
  | 'workflow_node_id'
  | 'workflow_node_label'
  | 'workflow_run_id'
>;

export type RuntimeApprovalVariant = 'compact' | 'inspector';

export function RuntimeApprovalCard({
  actions,
  actionsClassName = 'runtime-approval-actions',
  actionsTestId = 'runtime-approval-actions',
  approval,
  className = 'yachiyo-task-approval',
  testId = 'runtime-approval-card',
  variant = 'compact',
}: {
  actions?: ReactNode;
  actionsClassName?: string;
  actionsTestId?: string;
  approval: RuntimeApprovalCardSnapshot;
  className?: string;
  testId?: string;
  variant?: RuntimeApprovalVariant;
}) {
  const toolName = approval.tool_name || 'tool';
  const status = approval.status || 'pending';
  const preview = approvalPreviewRecord(approval.input_preview);
  const target = approvalPreviewTarget(preview, toolName);
  const displayTool = variant === 'compact' ? runtimeToolDisplayLabel(toolName) : toolName;
  const title = variant === 'compact'
    ? compactApprovalTitle(approval.title, toolName, displayTool)
    : approval.title || toolName;
  const metadata = variant === 'inspector' ? approvalMetadataItems(approval, toolName) : [];
  const reason = variant === 'inspector' ? approvalReasonText(approval, toolName, preview) : '';
  return (
    <div
      className={className}
      data-approval-id={approval.approval_id}
      data-approval-capability-id={approval.capability_id || ''}
      data-approval-decision-id={approval.decision_id || ''}
      data-approval-group-id={approval.group_id || ''}
      data-approval-group-run-id={approval.group_run_id || ''}
      data-approval-intent-kind={approval.intent_kind || ''}
      data-approval-plan-id={approval.plan_id || ''}
      data-approval-risk-level={approval.risk_level || ''}
      data-approval-run-id={approval.run_id || ''}
      data-approval-runtime-doctrine={approval.runtime_doctrine || ''}
      data-approval-runtime-role={approval.runtime_role || ''}
      data-approval-runtime-stage={approval.runtime_stage || ''}
      data-approval-source-runnable-id={approval.source_runnable_id || ''}
      data-approval-source-run-id={approval.source_run_id || ''}
      data-approval-status={status}
      data-approval-step-id={approval.step_id || approval.planner_step_id || ''}
      data-approval-replan-request-id={approval.replan_request_id || ''}
      data-approval-replan-signal-ids={(approval.replan_signal_ids || []).join(',')}
      data-approval-replan-trigger={approval.replan_trigger || approval.replan_triggers?.[0] || ''}
      data-approval-tool={toolName}
      data-approval-tool-plan-id={approval.tool_plan_id || ''}
      data-approval-variant={variant}
      data-approval-workflow-id={approval.workflow_id || ''}
      data-approval-workflow-node-id={approval.workflow_node_id || ''}
      data-approval-workflow-run-id={approval.workflow_run_id || ''}
      data-testid={testId}
    >
      <span>{status === 'pending' ? '待审批' : approvalStatusLabel(status)}</span>
      <strong>{title}</strong>
      {approval.description ? <p>{approval.description}</p> : null}
      {target || displayTool ? <code>{target || displayTool}</code> : null}
      {reason ? (
        <div className="runtime-approval-reason" data-testid={`${testId}-reason`}>
          <small>为什么需要确认</small>
          <p>{reason}</p>
        </div>
      ) : null}
      {metadata.length ? (
        <div className="runtime-approval-meta" data-testid={`${testId}-metadata`}>
          {metadata.map(({ label, value }) => (
            <span key={`${label}:${value}`}>{label} {value}</span>
          ))}
        </div>
      ) : null}
      {actions ? (
        <div className={actionsClassName} data-testid={actionsTestId}>
          {actions}
        </div>
      ) : null}
    </div>
  );
}

function compactApprovalTitle(title: string | null | undefined, toolName: string, displayTool: string) {
  const rawTitle = String(title || '').trim();
  if (!rawTitle) return displayTool;
  if (rawTitle === toolName || rawTitle === `Approve ${toolName}` || rawTitle.includes(toolName)) {
    return displayTool;
  }
  return rawTitle;
}

function approvalMetadataItems(approval: RuntimeApprovalCardSnapshot, toolName: string) {
  const items = [
    { label: 'approval', value: approval.approval_id },
    { label: 'run', value: approval.run_id || '' },
    { label: 'source', value: approval.source_run_id || '' },
    { label: 'agent', value: approval.source_runnable_name || approval.source_runnable_id || '' },
    { label: 'workflow', value: approval.workflow_node_label || approval.workflow_node_id || approval.workflow_run_id || approval.workflow_id || '' },
    { label: 'group', value: approval.group_run_id || approval.group_id || '' },
    { label: 'step', value: approval.step_id || approval.planner_step_id || '' },
    { label: 'capability', value: approval.capability_id || '' },
    { label: 'stage', value: approval.runtime_stage || '' },
    { label: 'role', value: approval.runtime_role || '' },
    { label: 'doctrine', value: approval.runtime_doctrine || '' },
    { label: 'observe', value: approval.requires_observation ? 'required' : '' },
    { label: 'verify', value: approval.requires_post_action_verification ? 'required' : '' },
    { label: 'tool', value: toolName },
    { label: 'plan', value: approval.tool_plan_id || approval.plan_id || '' },
    { label: 'decision', value: approval.decision_id || '' },
    { label: 'intent', value: approval.intent_kind || '' },
    { label: 'replan', value: approval.replan_request_id || approval.replan_trigger || approval.replan_triggers?.join(', ') || '' },
    { label: 'signals', value: approval.replan_signal_ids?.join(', ') || '' },
    { label: 'risk', value: approval.risk_level || '' },
    { label: 'requested', value: approval.requested_at || '' },
    { label: 'resolved', value: approval.resolved_at || '' },
    { label: 'policy', value: approval.policy_reason || '' },
  ];
  return items.filter((item) => String(item.value || '').trim());
}

function approvalReasonText(
  approval: RuntimeApprovalCardSnapshot,
  toolName: string,
  preview: Record<string, unknown>,
) {
  const policyReason = String(approval.policy_reason || '').trim();
  if (policyReason) return policyReason;
  const criteria = approvalPreviewValue(preview, ['criteria']);
  if (toolName === 'workflow.approval') {
    return criteria
      ? `Workflow 审批条件：${criteria}`
      : '这个 Workflow 节点被配置为人工审批检查点。';
  }
  if (approval.risk_level === 'high') {
    return '高风险工具调用会被当前工具策略拦截，需要人工确认。';
  }
  return '';
}

function approvalStatusLabel(status: string) {
  if (status === 'approved') return '已批准';
  if (status === 'rejected') return '已拒绝';
  if (status === 'cancelled') return '已取消';
  if (status === 'expired') return '已过期';
  return status || '审批';
}
