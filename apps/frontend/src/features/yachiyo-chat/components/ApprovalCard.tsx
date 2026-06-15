import type { ReactNode } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import { RuntimeApprovalGate } from '../../runtime-shared/components/RuntimeApprovalGate';
import type { ApprovalCardSnapshot } from '../types';

export function ApprovalCard({
  actions,
  approval,
  busy = false,
  onApprove,
  onReject,
}: {
  actions?: ReactNode;
  approval: ApprovalCardSnapshot;
  busy?: boolean;
  onApprove?: () => void;
  onReject?: () => void;
}) {
  if (onApprove || onReject) {
    return (
      <RuntimeApprovalGate
        actionsClassName="yachiyo-agent-task-approval-actions"
        actionsTestId="yachiyo-task-approval-actions"
        approval={approval}
        approveContent={<><UiIcon name="check" /><span>批准</span></>}
        approveTestId="yachiyo-task-approval-approve"
        busy={busy}
        cardClassName="yachiyo-task-approval"
        cardTestId="yachiyo-task-approval-card"
        className="yachiyo-task-approval-gate"
        onApprove={onApprove}
        onReject={onReject}
        rejectContent={<><UiIcon name="close" /><span>拒绝</span></>}
        rejectTestId="yachiyo-task-approval-reject"
        testId="yachiyo-task-approval-gate"
      />
    );
  }

  return (
    <RuntimeApprovalCard
      actions={actions}
      actionsClassName="yachiyo-agent-task-approval-actions"
      actionsTestId="yachiyo-task-approval-actions"
      approval={approval}
      className="yachiyo-task-approval"
      testId="yachiyo-task-approval-card"
    />
  );
}
