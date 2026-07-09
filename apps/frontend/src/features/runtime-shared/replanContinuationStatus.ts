import type { ReplanContinuationSnapshot } from './types';

export type ReplanContinuationBlockedResult = {
  action_id?: string | null;
  approval_required?: boolean;
  auto_start_blockers?: string[];
  auto_start_reason?: string;
  continuation?: ReplanContinuationSnapshot | null;
  manual_start_available?: boolean;
  reason?: string;
  tool_name?: string;
};

export function replanContinuationBlockedStatusMessage(
  result?: ReplanContinuationBlockedResult | null,
  fallback = '未找到可自动执行的恢复动作',
): string {
  if (!result?.manual_start_available && !result?.continuation) return fallback;
  const label = continuationLabel(result);
  const blocker = continuationBlockerLabel(result);
  if (result.approval_required || result.continuation?.approval_required) {
    return blocker
      ? `恢复动作需要审批：${label}（${blocker}）`
      : `恢复动作需要审批：${label}`;
  }
  return blocker
    ? `恢复动作需要手动处理：${label}（${blocker}）`
    : `恢复动作需要手动处理：${label}`;
}

function continuationLabel(result: ReplanContinuationBlockedResult): string {
  return compactStatusText(
    String(
      result.continuation?.title
      || result.continuation?.tool_name
      || result.tool_name
      || result.action_id
      || '恢复动作',
    ),
    48,
  );
}

function continuationBlockerLabel(result: ReplanContinuationBlockedResult): string {
  const blockers = [
    ...(result.auto_start_blockers || []),
    ...(result.continuation?.auto_start_blockers || []),
  ].map((item) => String(item || '').trim()).filter(Boolean);
  const blocker = blockers[0] || result.auto_start_reason || result.reason || '';
  return blockerLabel(blocker);
}

function blockerLabel(value: string): string {
  const clean = value.trim();
  if (!clean) return '';
  if (clean === 'approval_required') return '需要审批';
  if (clean === 'manual_replan_continuation_required') return '需要手动接续';
  if (clean === 'deferred_tool_not_auto_safe') return '后续工具需手动确认';
  if (clean === 'deferred_continuation_tool_not_auto_safe') return '后续步骤需手动确认';
  if (clean === 'tool_not_auto_safe') return '工具需手动确认';
  if (clean === 'high_risk') return '高风险需确认';
  if (clean === 'missing_tool') return '缺少可执行工具';
  return compactStatusText(clean.replace(/_/g, ' '), 48);
}

function compactStatusText(value: string, maxLength: number): string {
  const clean = value.trim();
  if (clean.length <= maxLength) return clean;
  return `${clean.slice(0, Math.max(0, maxLength - 1))}…`;
}
