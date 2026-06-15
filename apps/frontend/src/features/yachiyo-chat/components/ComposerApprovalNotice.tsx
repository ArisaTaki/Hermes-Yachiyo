import type { ApprovalRequestDetails } from './MessageApprovalRequestCard';

export type ComposerApprovalSource = 'message' | 'activity' | 'workflow-child';

export function ComposerApprovalNotice({
  approvalId,
  busy,
  currentIndex,
  details,
  itemId,
  onApprove,
  onNext,
  onOpenDetails,
  onPrevious,
  onReject,
  onReveal,
  runId,
  runStatus,
  source,
  total,
}: {
  approvalId?: string;
  busy: boolean;
  currentIndex: number;
  details: ApprovalRequestDetails;
  itemId?: string;
  onApprove: () => void;
  onNext: () => void;
  onOpenDetails: () => void;
  onPrevious: () => void;
  onReject: () => void;
  onReveal: () => void;
  runId?: string;
  runStatus?: string;
  source?: ComposerApprovalSource;
  total: number;
}) {
  const preview = details.codeText || details.summary.map((item) => item.value).join(' ');
  const hasMultiple = total > 1 && currentIndex >= 0;
  const workflowApproval = details.tool === 'workflow.approval';
  const subtitle = workflowApproval
    ? workflowApprovalNoticeSubtitle(details, preview)
    : compactApprovalText(preview, 86) || details.goal || '需要确认工具调用后继续执行';
  return (
    <div
      className="composer-approval-notice"
      data-approval-id={approvalId || ''}
      data-approval-item-id={itemId || ''}
      data-approval-kind={workflowApproval ? 'workflow' : 'tool'}
      data-approval-requester={details.requester}
      data-approval-source={source || ''}
      data-approval-tool={details.tool}
      data-run-id={runId || ''}
      data-run-status={runStatus || ''}
      data-testid="chat-composer-approval-notice"
    >
      <div className="composer-approval-main">
        <span className="composer-approval-badge">{hasMultiple ? `待审批 ${currentIndex + 1}/${total}` : '待审批'}</span>
        <div>
          <strong>{workflowApproval ? `${details.requester} 等待人工确认` : `${details.requester} 请求 ${details.tool}`}</strong>
          <span>{subtitle}</span>
        </div>
      </div>
      <div className="composer-approval-actions">
        {hasMultiple ? (
          <span className="composer-approval-nav" aria-label="切换待审批请求">
            <button type="button" data-testid="chat-composer-approval-previous" disabled={busy} onClick={onPrevious}>上一项</button>
            <button type="button" data-testid="chat-composer-approval-next" disabled={busy} onClick={onNext}>下一项</button>
          </span>
        ) : null}
        <button type="button" data-testid="chat-composer-approval-reveal" onClick={onReveal}>定位消息</button>
        {runId ? (
          <button
            type="button"
            data-run-id={runId}
            data-run-status={runStatus || ''}
            data-testid="chat-composer-approval-open-run-detail"
            onClick={onOpenDetails}
          >
            Agent Studio
          </button>
        ) : null}
        <button type="button" className="approve" data-testid="chat-composer-approval-approve" disabled={busy} onClick={onApprove}>{busy ? '处理中...' : '批准'}</button>
        <button type="button" className="reject" data-testid="chat-composer-approval-reject" disabled={busy} onClick={onReject}>拒绝</button>
      </div>
    </div>
  );
}

export function composerApprovalStatusText(
  details: ApprovalRequestDetails,
  currentIndex: number,
  total: number,
) {
  const position = total > 1 && currentIndex >= 0 ? ` ${currentIndex + 1}/${total}` : '';
  const target = [details.requester, details.tool].filter(Boolean).join(' 请求 ');
  const preview = details.tool === 'workflow.approval'
    ? workflowApprovalNoticeSubtitle(details, '')
    : compactApprovalText(
      details.codeText || details.summary.map((item) => item.value).join(' ') || details.goal,
      72,
    );
  return `待审批${position}：${target || details.tool || '工具调用'}${preview ? ` · ${preview}` : ''}`;
}

function workflowApprovalNoticeSubtitle(details: ApprovalRequestDetails, preview: string) {
  const checkpoint = details.summary.find((item) => item.label === '审批节点')?.value || '';
  const criteria = details.summary.find((item) => item.label === '审批说明')?.value || '';
  const primary = [checkpoint, criteria].filter(Boolean).join('：');
  return compactApprovalText(primary || preview || details.goal || '需要确认审批节点后继续执行', 86);
}

function compactApprovalText(text: string, maxLength = 96) {
  const normalized = String(text || '').replace(/\s+/g, ' ').trim();
  if (normalized.length <= maxLength) return normalized;
  return `${normalized.slice(0, Math.max(0, maxLength - 1)).trim()}…`;
}
