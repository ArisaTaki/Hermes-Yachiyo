import { useMemo, useState, type Dispatch, type SetStateAction } from 'react';

import {
  deleteRun,
  type RunGroupSpec,
  type RunSpec,
} from '../../../lib/agents';
import { navigateTo } from '../../../lib/view';
import { isActiveRunStatus } from '../utils/runs';

type RunHistoryRefreshOptions = {
  selectedRunId?: string;
};

type ConfirmDialogRequest = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

type UseRunHistoryManagementOptions = {
  clearRunEventReplay: (runIds: Iterable<string>) => void;
  filteredRunIds: string[];
  filteredRuns: RunSpec[];
  runAction: (action: () => Promise<RunHistoryRefreshOptions | void>, label: string) => void;
  selectedRunId: string;
  setArtifactPreview: (preview: { path: string; content: string; truncated?: boolean } | null) => void;
  setRunDetailCache: Dispatch<SetStateAction<RunSpec[]>>;
  setRunGroups: Dispatch<SetStateAction<RunGroupSpec[]>>;
  setRuns: Dispatch<SetStateAction<RunSpec[]>>;
  setSelectedRunId: (runId: string) => void;
  showConfirmDialog: (dialog: ConfirmDialogRequest) => void;
};

function toggleSelectedId(current: string[], id: string): string[] {
  if (current.includes(id)) return current.filter((item) => item !== id);
  return [...current, id];
}

export function useRunHistoryManagement({
  clearRunEventReplay,
  filteredRunIds,
  filteredRuns,
  runAction,
  selectedRunId,
  setArtifactPreview,
  setRunDetailCache,
  setRunGroups,
  setRuns,
  setSelectedRunId,
  showConfirmDialog,
}: UseRunHistoryManagementOptions) {
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [runHistoryManagementMode, setRunHistoryManagementMode] = useState(false);
  const selectedRunIdSet = useMemo(() => new Set(selectedRunIds), [selectedRunIds]);
  const selectedHistoryRuns = useMemo(
    () => filteredRuns.filter((run) => selectedRunIdSet.has(run.run_id)),
    [filteredRuns, selectedRunIdSet],
  );
  const selectedHistoryActiveRunCount = useMemo(
    () => selectedHistoryRuns.filter((run) => isActiveRunStatus(run.status)).length,
    [selectedHistoryRuns],
  );
  const runBulkDeleteDisabledReason = selectedHistoryActiveRunCount
    ? `有 ${selectedHistoryActiveRunCount} 个 Run 仍在进行中或待审批，请先取消或等待结束后再删除。`
    : '';
  const allHistoryRunsSelected = filteredRunIds.length > 0 && selectedHistoryRuns.length === filteredRunIds.length;

  function pruneDeletedRunState(deletedRunIds: Set<string>) {
    if (!deletedRunIds.size) return;
    setRuns((current) => current.filter((run) => !deletedRunIds.has(run.run_id)));
    setRunDetailCache((current) => current.filter((run) => !deletedRunIds.has(run.run_id)));
    clearRunEventReplay(deletedRunIds);
    setRunGroups((current) => current.filter((group) => {
      const childRunIds = group.child_run_ids || [];
      return !childRunIds.length || childRunIds.some((runId) => !deletedRunIds.has(runId));
    }));
  }

  function toggleRunSelected(runId: string) {
    setSelectedRunIds((current) => toggleSelectedId(current, runId));
  }

  function finishRunHistoryManagement() {
    setRunHistoryManagementMode(false);
    setSelectedRunIds([]);
  }

  function requestDeleteSelectedRuns() {
    const targets = selectedHistoryRuns.slice();
    if (!targets.length || selectedHistoryActiveRunCount) return;
    showConfirmDialog({
      title: `删除 ${targets.length} 条 Run History？`,
      description: '这些 Run 记录会从 Runs History 移除，对应 artifacts 也会删除；Workflow Run 会连带删除同一次 Workflow 的子 Agent Run。',
      confirmLabel: `删除 ${targets.length} 条记录`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        const deletedRunIds = new Set<string>();
        for (const run of targets) {
          const result = await deleteRun(run.run_id);
          const resultIds = Array.isArray(result.deleted_run_ids) ? result.deleted_run_ids : [run.run_id];
          resultIds.forEach((id) => {
            if (id) deletedRunIds.add(id);
          });
        }
        pruneDeletedRunState(deletedRunIds);
        setSelectedRunIds((current) => current.filter((id) => !deletedRunIds.has(id)));
        if (selectedRunId && deletedRunIds.has(selectedRunId)) {
          setSelectedRunId('');
          setArtifactPreview(null);
          navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
          return { selectedRunId: '' };
        }
        return undefined;
      }, '批量删除 Run History'),
    });
  }

  return {
    allHistoryRunsSelected,
    finishRunHistoryManagement,
    requestDeleteSelectedRuns,
    runBulkDeleteDisabledReason,
    runHistoryManagementMode,
    selectedHistoryRuns,
    selectedRunIdSet,
    setRunHistoryManagementMode,
    setSelectedRunIds,
    toggleRunSelected,
  };
}
