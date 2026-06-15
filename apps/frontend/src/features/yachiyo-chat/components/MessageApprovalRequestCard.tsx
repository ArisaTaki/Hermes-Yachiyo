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
      <div className="message-approval-card-header">
        <span className="message-approval-eyebrow">需要审批</span>
        <div>
          <strong>{workflowApproval ? `${details.requester} 等待人工确认` : `${details.requester} 请求执行工具调用`}</strong>
          <span>{workflowApproval ? '批准后会继续当前 Workflow' : '批准后会继续当前任务'}</span>
        </div>
        <span className="message-approval-header-side">
          <code>{details.tool}</code>
          {runId ? (
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
        </span>
      </div>
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
