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
  | 'deferred_context'
  | 'deferred_continuation'
  | 'deferred_input'
  | 'deferred_tool'
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
  | 'task_workspace_items'
  | 'task_verification_targets'
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
  const taskWorkspaceItems = recordList(approval.task_workspace_items);
  const taskVerificationTargets = recordList(approval.task_verification_targets);
  const deferredContinuation = recordList(approval.deferred_continuation);
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
      data-approval-deferred-continuation-count={deferredContinuation.length}
      data-approval-deferred-tool={approval.deferred_tool || ''}
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
      data-approval-task-verification-target-count={taskVerificationTargets.length}
      data-approval-task-workspace-item-count={taskWorkspaceItems.length}
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
  const taskWorkspaceItems = recordList(approval.task_workspace_items);
  const taskVerificationTargets = recordList(approval.task_verification_targets);
  const deferredInput = approvalPreviewRecord(approval.deferred_input);
  const deferredContext = approvalPreviewRecord(approval.deferred_context);
  const deferredContinuation = recordList(approval.deferred_continuation);
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
    { label: 'workspace', value: approvalWorkspaceSummary(taskWorkspaceItems) },
    { label: 'targets', value: approvalVerificationTargetsSummary(taskVerificationTargets) },
    { label: 'tool', value: toolName },
    { label: 'plan', value: approval.tool_plan_id || approval.plan_id || '' },
    { label: 'decision', value: approval.decision_id || '' },
    { label: 'intent', value: approval.intent_kind || '' },
    { label: 'replan', value: approval.replan_request_id || approval.replan_trigger || approval.replan_triggers?.join(', ') || '' },
    { label: 'signals', value: approval.replan_signal_ids?.join(', ') || '' },
    { label: 'deferred', value: approval.deferred_tool || '' },
    { label: 'deferred input', value: approvalObjectSummary(deferredInput) },
    { label: 'deferred context', value: approvalObjectSummary(deferredContext) },
    { label: 'continuation', value: approvalDeferredContinuationSummary(deferredContinuation) },
    { label: 'risk', value: approval.risk_level || '' },
    { label: 'requested', value: approval.requested_at || '' },
    { label: 'resolved', value: approval.resolved_at || '' },
    { label: 'policy', value: approval.policy_reason || '' },
  ];
  return items.filter((item) => String(item.value || '').trim());
}

function approvalObjectSummary(record: Record<string, unknown>): string {
  const entries = Object.entries(record)
    .map(([key, value]) => {
      const text = stringValue(value);
      return text ? `${key}: ${text}` : '';
    })
    .filter(Boolean);
  if (!entries.length) return '';
  const visible = entries.slice(0, 3).join(', ');
  const suffix = entries.length > 3 ? ` +${entries.length - 3}` : '';
  return `${visible}${suffix}`;
}

function approvalDeferredContinuationSummary(items: Array<Record<string, unknown>>): string {
  const parts = items.slice(0, 3).map((item) => (
    stringValue(item.tool)
    || stringValue(item.deferred_tool)
    || stringValue(item.step_id)
    || stringValue(item.capability_id)
  )).filter(Boolean);
  if (!parts.length) return '';
  const suffix = items.length > parts.length ? ` +${items.length - parts.length}` : '';
  return `${parts.join(' -> ')}${suffix}`;
}

function approvalWorkspaceSummary(items: Array<Record<string, unknown>>): string {
  return items
    .slice(0, 3)
    .map((item) => (
      stringValue(item.title)
      || stringValue(item.path)
      || stringValue(item.item_id)
      || stringValue(item.source_step_id)
    ))
    .filter(Boolean)
    .join(', ');
}

function approvalVerificationTargetsSummary(targets: Array<Record<string, unknown>>): string {
  const parts = targets.slice(0, 3).map((target) => {
    const label = (
      stringValue(target.todo_title)
      || stringValue(target.title)
      || stringValue(target.step_id)
      || stringValue(target.todo_id)
      || stringValue(target.tool_name)
    );
    const workspace = [
      ...recordList(target.workspace_items),
      ...recordList(target.task_workspace_items),
    ]
      .slice(0, 2)
      .map((item) => (
        stringValue(item.title)
        || stringValue(item.path)
        || stringValue(item.item_id)
        || stringValue(item.source_step_id)
      ))
      .filter(Boolean)
      .join(', ');
    return [label, workspace ? `workspace: ${workspace}` : ''].filter(Boolean).join(' -> ');
  }).filter(Boolean);
  if (!parts.length) return '';
  const suffix = targets.length > parts.length ? ` +${targets.length - parts.length}` : '';
  return `${parts.join(' | ')}${suffix}`;
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => (
    Boolean(item) && typeof item === 'object' && !Array.isArray(item)
  ));
}

function stringValue(value: unknown): string {
  if (typeof value === 'string') return value.trim();
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return '';
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
