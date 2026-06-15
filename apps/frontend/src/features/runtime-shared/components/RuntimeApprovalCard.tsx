import type { ReactNode } from 'react';

import type { ApprovalCardSnapshot } from '../types';
import { approvalPreviewRecord, approvalPreviewValue } from '../approval';

export type RuntimeApprovalCardSnapshot = Pick<
  ApprovalCardSnapshot,
  'approval_id' | 'description' | 'input_preview' | 'status' | 'title' | 'tool_name'
>;

export function RuntimeApprovalCard({
  actions,
  actionsClassName = 'runtime-approval-actions',
  actionsTestId = 'runtime-approval-actions',
  approval,
  className = 'yachiyo-task-approval',
  testId = 'runtime-approval-card',
}: {
  actions?: ReactNode;
  actionsClassName?: string;
  actionsTestId?: string;
  approval: RuntimeApprovalCardSnapshot;
  className?: string;
  testId?: string;
}) {
  const toolName = approval.tool_name || 'tool';
  const status = approval.status || 'pending';
  const preview = approvalPreviewRecord(approval.input_preview);
  const target = approvalPreviewValue(preview, ['command', 'cmd', 'path', 'file', 'target']);
  return (
    <div
      className={className}
      data-approval-id={approval.approval_id}
      data-approval-status={status}
      data-approval-tool={toolName}
      data-testid={testId}
    >
      <span>{status === 'pending' ? '待审批' : approvalStatusLabel(status)}</span>
      <strong>{approval.title || toolName}</strong>
      {approval.description ? <p>{approval.description}</p> : null}
      {target || toolName ? <code>{target || toolName}</code> : null}
      {actions ? (
        <div className={actionsClassName} data-testid={actionsTestId}>
          {actions}
        </div>
      ) : null}
    </div>
  );
}

function approvalStatusLabel(status: string) {
  if (status === 'approved') return '已批准';
  if (status === 'rejected') return '已拒绝';
  if (status === 'cancelled') return '已取消';
  if (status === 'expired') return '已过期';
  return status || '审批';
}
