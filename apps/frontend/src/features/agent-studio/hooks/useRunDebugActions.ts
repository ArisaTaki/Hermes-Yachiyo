import type { RunSpec } from '../../../lib/agents';
import { isActiveRunStatus } from '../utils/runs';

type RunDebugRefreshOptions = {
  selectedRunId?: string;
  statusMessage?: string;
  skipRefresh?: boolean;
};

type ConfirmDialogRequest = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

type UseRunDebugActionsOptions = {
  cancelSelectedRun: () => Promise<RunDebugRefreshOptions>;
  loadMoreRunReplayEvents: () => Promise<number>;
  runAction: (action: () => Promise<RunDebugRefreshOptions | void>, label: string) => void;
  selectedRun: RunSpec | null;
  setStatus: (message: string) => void;
  showConfirmDialog: (dialog: ConfirmDialogRequest) => void;
};

export function useRunDebugActions({
  cancelSelectedRun,
  loadMoreRunReplayEvents,
  runAction,
  selectedRun,
  setStatus,
  showConfirmDialog,
}: UseRunDebugActionsOptions) {
  async function loadMoreSelectedRunEvents() {
    const loadedCount = await loadMoreRunReplayEvents();
    setStatus(loadedCount ? `已加载 ${loadedCount} 条 RunEvent replay` : '没有更多 RunEvent replay');
  }

  function requestCancelSelectedRun() {
    if (!selectedRun || !isActiveRunStatus(selectedRun.status)) return;
    const runName = selectedRun.runnable_name || selectedRun.runnable_id || 'Run';
    showConfirmDialog({
      title: `取消「${runName}」？`,
      description: '这会终止当前进行中或待审批的 Run；如果它正在等待审批，待审批请求也会被清空。',
      confirmLabel: '取消 Run',
      variant: 'danger',
      onConfirm: () => void runAction(cancelSelectedRun, '取消 Run'),
    });
  }

  return {
    loadMoreSelectedRunEvents,
    requestCancelSelectedRun,
  };
}
