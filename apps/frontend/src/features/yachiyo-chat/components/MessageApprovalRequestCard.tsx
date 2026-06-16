import { runtimeToolDisplayLabel } from '../../runtime-shared/approval';
import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import type { ApprovalCardSnapshot } from '../types';

export type ApprovalRequestDetails = {
  requester: string;
  tool: string;
  goal: string;
  codeLanguage: string;
  codeText: string;
  summary: Array<{ label: string; value: string }>;
};

export function MessageApprovalRequestCard({
  approvalId,
  approvalSignature,
  details,
  onOpenDetails,
  renderCodePreview,
  runId,
  runStatus,
}: {
  approvalId?: string;
  approvalSignature?: string;
  details: ApprovalRequestDetails;
  onOpenDetails: () => void;
  renderCodePreview: (codeText: string, codeLanguage: string) => string;
  runId: string;
  runStatus: string;
}) {
  const workflowApproval = details.tool === 'workflow.approval';
  const toolLabel = runtimeToolDisplayLabel(details.tool);
  const approval = messageApprovalSnapshot({
    approvalId,
    details,
    runId,
    toolLabel,
  });
  return (
    <div
      className="message-content message-approval-card"
      data-approval-id={approvalId || ''}
      data-approval-kind={workflowApproval ? 'workflow' : 'tool'}
      data-approval-requester={details.requester}
      data-approval-signature={approvalSignature || ''}
      data-approval-source="message"
      data-approval-tool={details.tool}
      data-run-id={runId}
      data-testid="chat-message-approval-card"
    >
      <RuntimeApprovalCard
        actions={runId ? (
          <button
            type="button"
            data-run-id={runId}
            data-run-status={runStatus}
            data-testid="chat-message-approval-open-run-detail"
            onClick={onOpenDetails}
          >
            Agent Studio
          </button>
        ) : null}
        actionsClassName="message-approval-header-side"
        actionsTestId="chat-message-approval-open-run-detail-actions"
        approval={approval}
        className="message-approval-runtime-card"
        testId="chat-message-approval-runtime-card"
        variant="compact"
      />
      {details.goal ? (
        <section className="message-approval-section">
          <span>关联任务</span>
          <p>{details.goal}</p>
        </section>
      ) : null}
      <section className="message-approval-section">
        <span>{workflowApproval ? '审批内容' : '请求内容'}</span>
        {details.summary.length ? (
          <dl className="message-approval-summary">
            {details.summary.map((item) => (
              <div key={`${item.label}:${item.value}`}>
                <dt>{item.label}</dt>
                <dd>{item.value}</dd>
              </div>
            ))}
          </dl>
        ) : null}
        {details.codeText ? (
          <div
            className="message-approval-code markdown"
            dangerouslySetInnerHTML={{
              __html: renderCodePreview(details.codeText, details.codeLanguage),
            }}
          />
        ) : details.summary.length ? null : <p>没有可展示的参数预览。</p>}
      </section>
    </div>
  );
}

function messageApprovalSnapshot({
  approvalId,
  details,
  runId,
  toolLabel,
}: {
  approvalId?: string;
  details: ApprovalRequestDetails;
  runId: string;
  toolLabel: string;
}): ApprovalCardSnapshot {
  const workflowApproval = details.tool === 'workflow.approval';
  const title = workflowApproval
    ? `${details.requester} 等待人工确认`
    : `${details.requester} 请求${toolLabel}`;
  return {
    approval_id: approvalId || runId || `${details.tool}:message`,
    description: workflowApproval ? '批准后会继续当前 Workflow' : '批准后会继续当前任务',
    input_preview: messageApprovalInputPreview(details),
    run_id: runId || undefined,
    status: 'pending',
    title,
    tool_name: details.tool,
  };
}

function messageApprovalInputPreview(details: ApprovalRequestDetails): Record<string, unknown> {
  const preview: Record<string, unknown> = {};
  if (details.goal) preview.goal = details.goal;
  if (details.codeText) preview.command = details.codeText;
  details.summary.forEach((item) => {
    if (item.label && item.value) preview[item.label] = item.value;
  });
  return preview;
}
