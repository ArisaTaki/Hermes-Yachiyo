import {
  approvalPreviewRecord,
  approvalPreviewValue,
  formatApprovalInput,
} from '../../runtime-shared/approval';

export function RunApprovalRequest({
  inputPreview,
  runGoal = '',
  runId = '',
  runLabel = '',
  tool,
}: {
  inputPreview: unknown;
  runGoal?: string;
  runId?: string;
  runLabel?: string;
  tool: string;
}) {
  const preview = approvalPreviewRecord(inputPreview);
  const checkpoint = approvalPreviewValue(preview, ['checkpoint', 'label', 'approval']);
  const criteria = approvalPreviewValue(preview, ['criteria', 'approval_criteria', 'instructions']);
  const workdir = approvalPreviewValue(preview, ['cwd', 'workdir', 'working_dir']);
  const path = approvalPreviewValue(preview, ['path', 'file', 'target']);
  const command = tool === 'terminal.run' ? approvalPreviewValue(preview, ['command', 'cmd']) : '';
  const rows = [
    ['Tool', tool],
    runId ? ['Run', runLabel ? `${runLabel} · ${runId}` : runId] : null,
    runGoal ? ['关联任务', runGoal] : null,
    checkpoint ? ['审批节点', checkpoint] : null,
    criteria ? ['审批说明', criteria] : null,
    workdir ? ['工作目录', workdir] : null,
    path ? ['路径', path] : null,
  ].filter((row): row is string[] => Boolean(row));
  const contentLabel = command ? 'BASH' : tool === 'workflow.approval' ? '审批上下文' : '请求内容';
  const content = command || formatApprovalInput(inputPreview);
  return (
    <div className="run-approval-request" data-testid="agent-run-approval-request">
      <div className="run-approval-summary-grid">
        {rows.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <code>{value}</code>
          </div>
        ))}
      </div>
      <div className="run-approval-request-content">
        <span>{contentLabel}</span>
        <pre><code>{content || '无请求内容'}</code></pre>
      </div>
    </div>
  );
}
