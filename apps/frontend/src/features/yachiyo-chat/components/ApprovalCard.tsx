import type { ReactNode } from 'react';

import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import type { ApprovalCardSnapshot } from '../types';

export function ApprovalCard({
  actions,
  approval,
}: {
  actions?: ReactNode;
  approval: ApprovalCardSnapshot;
}) {
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
