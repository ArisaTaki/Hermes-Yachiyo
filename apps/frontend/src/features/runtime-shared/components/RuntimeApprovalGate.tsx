import type { ReactNode } from 'react';

import {
  RuntimeApprovalCard,
  type RuntimeApprovalCardSnapshot,
  type RuntimeApprovalVariant,
} from './RuntimeApprovalCard';

type RuntimeApprovalGateProps = {
  actionsClassName?: string;
  actionsTestId?: string;
  approval: RuntimeApprovalCardSnapshot;
  approveButtonClassName?: string;
  approveContent?: ReactNode;
  approveLabel?: string;
  approveTestId?: string;
  busy?: boolean;
  cardClassName?: string;
  cardTestId?: string;
  cardVariant?: RuntimeApprovalVariant;
  children?: ReactNode;
  className?: string;
  onApprove?: () => void;
  onReject?: () => void;
  rejectButtonClassName?: string;
  rejectContent?: ReactNode;
  rejectLabel?: string;
  rejectTestId?: string;
  testId?: string;
};

export function RuntimeApprovalGate({
  actionsClassName = 'runtime-approval-actions',
  actionsTestId = 'runtime-approval-actions',
  approval,
  approveButtonClassName,
  approveContent,
  approveLabel = '批准',
  approveTestId,
  busy = false,
  cardClassName = 'runtime-approval-card',
  cardTestId = 'runtime-approval-card',
  cardVariant = 'compact',
  children,
  className = 'runtime-approval-gate',
  onApprove,
  onReject,
  rejectButtonClassName,
  rejectContent,
  rejectLabel = '拒绝',
  rejectTestId,
  testId = 'runtime-approval-gate',
}: RuntimeApprovalGateProps) {
  const actions = onApprove || onReject ? (
    <>
      {onApprove ? (
        <button
          type="button"
          className={approveButtonClassName}
          data-approval-id={approval.approval_id}
          data-testid={approveTestId}
          disabled={busy}
          onClick={onApprove}
        >
          {approveContent || approveLabel}
        </button>
      ) : null}
      {onReject ? (
        <button
          type="button"
          className={rejectButtonClassName}
          data-approval-id={approval.approval_id}
          data-testid={rejectTestId}
          disabled={busy}
          onClick={onReject}
        >
          {rejectContent || rejectLabel}
        </button>
      ) : null}
    </>
  ) : undefined;

  return (
    <section className={className} data-testid={testId}>
      <RuntimeApprovalCard
        actions={actions}
        actionsClassName={actionsClassName}
        actionsTestId={actionsTestId}
        approval={approval}
        className={cardClassName}
        testId={cardTestId}
        variant={cardVariant}
      />
      {children}
    </section>
  );
}
