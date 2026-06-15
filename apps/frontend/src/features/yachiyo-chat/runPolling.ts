import type { DelegatedRunSummaryResult } from './types';

export type ChatRunLike = {
  kind?: string;
};

export function chatRunLabel(run: ChatRunLike) {
  return run.kind === 'workflow_run' ? 'Workflow Run' : 'Agent Run';
}

export function isChatRunTerminalStatus(status: string) {
  return status === 'completed' || status === 'failed' || status === 'cancelled' || status === 'approval_required';
}

export function chatRunProgressStatusText(runLabel: string, attempt: number, intervalMs: number) {
  return `${runLabel} 执行中... (${Math.floor(attempt * intervalMs / 1000)}s)`;
}

export function chatRunPollingTimeoutStatusText(chatStillProcessing: boolean) {
  return chatStillProcessing ? 'Agent Run 轮询超时，仍在等待后续处理...' : 'Agent Run 轮询超时';
}

export function chatRunCompletionProcessingState(
  delegatedSummary: DelegatedRunSummaryResult,
  chatStillProcessing: boolean,
  chatProcessingCount: number,
) {
  return {
    nextProcessing: delegatedSummary.created ? delegatedSummary.isProcessing : chatStillProcessing,
    nextProcessingCount: delegatedSummary.created ? delegatedSummary.processingCount : chatProcessingCount,
  };
}

export function chatRunCompletionStatusText({
  chatStillProcessing,
  delegatedSummary,
  runLabel,
  status,
}: {
  chatStillProcessing: boolean;
  delegatedSummary: DelegatedRunSummaryResult;
  runLabel: string;
  status: string;
}) {
  if (delegatedSummary.created) return `${runLabel} 已结束，等待主模型整理委派结果...`;
  if (delegatedSummary.error) return `审批后执行结束，但整理任务未创建：${delegatedSummary.error}`;
  if (chatStillProcessing) {
    if (status === 'completed') return `${runLabel} 已完成，等待主模型汇总...`;
    if (status === 'cancelled') return `${runLabel} 已取消，等待主模型整理结果...`;
    return `${runLabel} 执行失败，等待主模型整理结果...`;
  }
  if (status === 'completed') return `${runLabel} 已完成。`;
  if (status === 'cancelled') return `${runLabel} 已取消。`;
  return `${runLabel} 执行失败。`;
}
