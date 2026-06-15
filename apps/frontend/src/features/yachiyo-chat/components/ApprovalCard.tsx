import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import type { ApprovalCardSnapshot } from '../types';

export function ApprovalCard({ approval }: { approval: ApprovalCardSnapshot }) {
  return (
    <RuntimeApprovalCard
      approval={approval}
      className="yachiyo-task-approval"
      testId="yachiyo-task-approval-card"
    />
  );
}
