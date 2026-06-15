import type { ReactNode } from 'react';

import type { ApprovalCardSnapshot } from '../types';
import { approvalPreviewRecord, approvalPreviewValue } from '../approval';

export type RuntimeApprovalCardSnapshot = Pick<
  ApprovalCardSnapshot,
  | 'approval_id'
  | 'description'
  | 'input_preview'
  | 'open_in_studio_url'
  | 'policy_reason'
  | 'requested_at'
  | 'resolved_at'
  | 'risk_level'
  | 'run_id'
  | 'status'
  | 'title'
  | 'tool_name'
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
  const target = approvalPreviewValue(preview, ['command', 'cmd', 'path', 'file', 'target']);
  const metadata = variant === 'inspector' ? approvalMetadataItems(approval, toolName) : [];
  return (
    <div
      className={className}
      data-approval-id={approval.approval_id}
      data-approval-risk-level={approval.risk_level || ''}
      data-approval-status={status}
      data-approval-tool={toolName}
      data-approval-variant={variant}
      data-testid={testId}
    >
      <span>{status === 'pending' ? '待审批' : approvalStatusLabel(status)}</span>
      <strong>{approval.title || toolName}</strong>
      {approval.description ? <p>{approval.description}</p> : null}
      {target || toolName ? <code>{target || toolName}</code> : null}
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

function approvalMetadataItems(approval: RuntimeApprovalCardSnapshot, toolName: string) {
  const items = [
    { label: 'approval', value: approval.approval_id },
    { label: 'run', value: approval.run_id || '' },
    { label: 'tool', value: toolName },
    { label: 'risk', value: approval.risk_level || '' },
    { label: 'requested', value: approval.requested_at || '' },
    { label: 'resolved', value: approval.resolved_at || '' },
    { label: 'policy', value: approval.policy_reason || '' },
  ];
  return items.filter((item) => String(item.value || '').trim());
}

function approvalStatusLabel(status: string) {
  if (status === 'approved') return '已批准';
  if (status === 'rejected') return '已拒绝';
  if (status === 'cancelled') return '已取消';
  if (status === 'expired') return '已过期';
  return status || '审批';
}
