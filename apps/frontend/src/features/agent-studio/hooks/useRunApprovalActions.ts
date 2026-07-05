import { useCallback } from 'react';

import {
  approveYachiyoRunApproval,
  cancelYachiyoRun,
  getYachiyoRunTimeline,
  rejectYachiyoRunApproval,
} from '../../yachiyo-studio/api';
import type { RunSpec } from '../types';
import {
  approvedRunStatusMessage,
  isActiveRunStatus,
  makeRunContinuingAfterApproval,
  publicRunTimelineToStudioRunSpec,
} from '../utils/runs';

export type RunApprovalActionRefreshOptions = {
  selectedRunId?: string;
  statusMessage?: string;
  skipRefresh?: boolean;
};

type UseRunApprovalActionsOptions = {
  approvalFollowupRefreshOptions: (selectedAfterAction: string) => RunApprovalActionRefreshOptions;
  isApprovalFollowupCurrent: (selectedAfterAction: string) => boolean;
  pollApprovedRunProgress: (runId: string, selectedAfterAction: string) => Promise<void>;
  refresh: (options?: RunApprovalActionRefreshOptions) => Promise<void>;
  refreshRunGroupsForRuns: (runs: RunSpec[]) => Promise<void>;
  rememberApprovedRun: (run: RunSpec | null | undefined) => void;
  runById: Map<string, RunSpec>;
  selectedRun: RunSpec | null;
  setError: (message: string) => void;
  setSelectedRunId: (runId: string) => void;
  setStatus: (message: string) => void;
  upsertRunDetailCache: (runs: RunSpec[]) => void;
};

export function useRunApprovalActions({
  approvalFollowupRefreshOptions,
  isApprovalFollowupCurrent,
  pollApprovedRunProgress,
  refresh,
  refreshRunGroupsForRuns,
  rememberApprovedRun,
  runById,
  selectedRun,
  setError,
  setSelectedRunId,
  setStatus,
  upsertRunDetailCache,
}: UseRunApprovalActionsOptions) {
  const approveRunById = useCallback(async (
    runId: string,
    nextSelectedRunId?: string,
  ): Promise<RunApprovalActionRefreshOptions> => {
    if (!runId) throw new Error('请选择待审批 Run');
    const selectedAfterAction = nextSelectedRunId || runId;
    const currentRun = runById.get(runId) || null;
    const selectedAfterRun = selectedAfterAction !== runId ? runById.get(selectedAfterAction) || null : null;
    const optimisticRuns = [
      currentRun ? makeRunContinuingAfterApproval(currentRun, '已批准，Run 正在继续执行。') : null,
      selectedAfterRun && isActiveRunStatus(selectedAfterRun.status)
        ? makeRunContinuingAfterApproval(selectedAfterRun, '已批准子 Agent，Workflow 正在继续执行。')
        : null,
    ].filter((run): run is RunSpec => Boolean(run));
    upsertRunDetailCache(optimisticRuns);
    rememberApprovedRun(currentRun);
    rememberApprovedRun(selectedAfterRun);
    setSelectedRunId(selectedAfterAction);
    const approvalRequest = approveYachiyoRunApproval(runId).then(publicRunTimelineToStudioRunSpec);
    void pollApprovedRunProgress(runId, selectedAfterAction).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : '刷新审批后的 Run 进度失败');
    });
    void approvalRequest
      .then(async (run) => {
        const updatedRuns = [run];
        if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
          try {
            updatedRuns.push(publicRunTimelineToStudioRunSpec(await getYachiyoRunTimeline(nextSelectedRunId)));
          } catch {
            // The background polling path will retry; approval already succeeded.
          }
        }
        upsertRunDetailCache(updatedRuns);
        await refreshRunGroupsForRuns(updatedRuns);
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setSelectedRunId(selectedAfterAction);
          setStatus(approvedRunStatusMessage(run));
        }
      })
      .catch((err: unknown) => {
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setError(err instanceof Error ? err.message : '批准 Run 审批失败');
        }
        void refresh(approvalFollowupRefreshOptions(selectedAfterAction)).catch(() => undefined);
      });
    return {
      selectedRunId: selectedAfterAction,
      statusMessage: '已批准，Run 正在继续执行。',
      skipRefresh: true,
    };
  }, [
    approvalFollowupRefreshOptions,
    isApprovalFollowupCurrent,
    pollApprovedRunProgress,
    refresh,
    refreshRunGroupsForRuns,
    rememberApprovedRun,
    runById,
    setError,
    setSelectedRunId,
    setStatus,
    upsertRunDetailCache,
  ]);

  const rejectRunById = useCallback(async (
    runId: string,
    nextSelectedRunId?: string,
  ): Promise<RunApprovalActionRefreshOptions> => {
    if (!runId) throw new Error('请选择待审批 Run');
    const run = publicRunTimelineToStudioRunSpec(await rejectYachiyoRunApproval(runId));
    const selectedAfterAction = nextSelectedRunId || run.run_id;
    const updatedRuns = [run];
    if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
      try {
        updatedRuns.push(publicRunTimelineToStudioRunSpec(await getYachiyoRunTimeline(nextSelectedRunId)));
      } catch {
        // The normal refresh/polling path will retry; rejection already succeeded.
      }
    }
    upsertRunDetailCache(updatedRuns);
    setSelectedRunId(selectedAfterAction);
    return { selectedRunId: selectedAfterAction, statusMessage: '已拒绝，Run 已终止。' };
  }, [setSelectedRunId, upsertRunDetailCache]);

  const cancelRunById = useCallback(async (
    runId: string,
    nextSelectedRunId?: string,
  ): Promise<RunApprovalActionRefreshOptions> => {
    if (!runId) throw new Error('请选择要取消的 Run');
    const currentRun = runById.get(runId) || null;
    if (currentRun && !isActiveRunStatus(currentRun.status)) throw new Error('只能取消进行中或待审批的 Run');
    const run = publicRunTimelineToStudioRunSpec(await cancelYachiyoRun(runId));
    const selectedAfterAction = nextSelectedRunId || run.run_id;
    const updatedRuns = [run];
    if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
      try {
        updatedRuns.push(publicRunTimelineToStudioRunSpec(await getYachiyoRunTimeline(nextSelectedRunId)));
      } catch {
        // The normal refresh/polling path will retry; cancellation already succeeded.
      }
    }
    upsertRunDetailCache(updatedRuns);
    await refreshRunGroupsForRuns(updatedRuns);
    setSelectedRunId(selectedAfterAction);
    return {
      selectedRunId: selectedAfterAction,
      statusMessage: nextSelectedRunId ? '已取消子 Run，Workflow 已终止。' : 'Run 已取消。',
    };
  }, [refreshRunGroupsForRuns, runById, setSelectedRunId, upsertRunDetailCache]);

  const cancelSelectedRun = useCallback(async (): Promise<RunApprovalActionRefreshOptions> => {
    if (!selectedRun) throw new Error('请选择要取消的 Run');
    return cancelRunById(selectedRun.run_id);
  }, [cancelRunById, selectedRun]);

  return {
    approveRunById,
    cancelRunById,
    cancelSelectedRun,
    rejectRunById,
  };
}
