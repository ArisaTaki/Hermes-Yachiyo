import { useGroupRunDebugActions } from './useGroupRunDebugActions';
import { useRunDebugActions } from './useRunDebugActions';
import type { RunSpec } from '../types';

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

type UseAgentStudioRunDebugControlsOptions = {
  cancelSelectedRun: () => Promise<RunDebugRefreshOptions>;
  loadMoreGroupRunReplayEvents: () => Promise<number>;
  loadMoreRunReplayEvents: () => Promise<number>;
  runAction: (action: () => Promise<RunDebugRefreshOptions | void>, label: string) => void;
  selectedRun: RunSpec | null;
  setStatus: (message: string) => void;
  showConfirmDialog: (dialog: ConfirmDialogRequest) => void;
};

export function useAgentStudioRunDebugControls({
  cancelSelectedRun,
  loadMoreGroupRunReplayEvents,
  loadMoreRunReplayEvents,
  runAction,
  selectedRun,
  setStatus,
  showConfirmDialog,
}: UseAgentStudioRunDebugControlsOptions) {
  const {
    loadMoreSelectedRunEvents,
    requestCancelSelectedRun,
  } = useRunDebugActions({
    cancelSelectedRun,
    loadMoreRunReplayEvents,
    runAction,
    selectedRun,
    setStatus,
    showConfirmDialog,
  });
  const { loadMoreSelectedGroupRunEvents } = useGroupRunDebugActions({
    loadMoreGroupRunReplayEvents,
    setStatus,
  });

  return {
    loadMoreSelectedGroupRunEvents,
    loadMoreSelectedRunEvents,
    requestCancelSelectedRun,
  };
}
