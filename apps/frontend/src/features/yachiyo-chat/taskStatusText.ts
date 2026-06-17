export function chatRunnableRunningStatusText(label: string) {
  return `${chatRunnableLabel(label)} 执行中...`;
}

export function chatRunnableSettledStatusText({
  error = '',
  hasRunId = false,
  label,
  status,
}: {
  error?: string;
  hasRunId?: boolean;
  label: string;
  status?: string;
}) {
  const runnableLabel = chatRunnableLabel(label);
  if (status === 'approval_required' || status === 'waiting_approval') return `${runnableLabel} 等待审批...`;
  if (status === 'failed') return error || `${runnableLabel} 任务失败。`;
  if (status === 'completed') return `${runnableLabel} 任务已完成。`;
  if (hasRunId) return `${runnableLabel} 任务已处理。`;
  return error || 'Agent/Workflow 任务已处理。';
}

function chatRunnableLabel(label: string) {
  return String(label || '').trim() || 'Agent/Workflow';
}
