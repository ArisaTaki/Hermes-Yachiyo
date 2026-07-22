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
    const approvalId = String(currentRun?.pending_approval?.approval_id || '').trim();
    if (!approvalId) throw new Error('审批信息已过期，请刷新后重试。');
    try {
      const run = publicRunTimelineToStudioRunSpec(
        await approveYachiyoRunApproval(runId, approvalId),
      );
      rememberApprovedRun(currentRun);
      const selectedAfterRun = selectedAfterAction !== runId ? runById.get(selectedAfterAction) || null : null;
      rememberApprovedRun(selectedAfterRun);
      const updatedRuns = [run];
      if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
        try {
          updatedRuns.push(publicRunTimelineToStudioRunSpec(await getYachiyoRunTimeline(nextSelectedRunId)));
        } catch {
          // The follow-up polling path will retry; approval already succeeded.
        }
      }
      upsertRunDetailCache(updatedRuns);
      await refreshRunGroupsForRuns(updatedRuns);
      if (isApprovalFollowupCurrent(selectedAfterAction)) {
        setSelectedRunId(selectedAfterAction);
        setStatus(approvedRunStatusMessage(run));
      }
      void pollApprovedRunProgress(runId, selectedAfterAction).catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '刷新审批后的 Run 进度失败');
      });
      return {
        selectedRunId: selectedAfterAction,
        statusMessage: approvedRunStatusMessage(run),
        skipRefresh: true,
      };
    } catch (error) {
      await refresh(approvalFollowupRefreshOptions(selectedAfterAction)).catch(() => undefined);
      throw error;
    }
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
    const currentRun = runById.get(runId) || null;
    const approvalId = String(currentRun?.pending_approval?.approval_id || '').trim();
    if (!approvalId) throw new Error('审批信息已过期，请刷新后重试。');
    const selectedAfterAction = nextSelectedRunId || runId;
    try {
      const run = publicRunTimelineToStudioRunSpec(
        await rejectYachiyoRunApproval(runId, approvalId),
      );
      const updatedRuns = [run];
      if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
        try {
          updatedRuns.push(publicRunTimelineToStudioRunSpec(await getYachiyoRunTimeline(nextSelectedRunId)));
        } catch {
          // The normal refresh/polling path will retry; rejection already succeeded.
        }
      }
      upsertRunDetailCache(updatedRuns);
      await refreshRunGroupsForRuns(updatedRuns);
      setSelectedRunId(selectedAfterAction);
      return { selectedRunId: selectedAfterAction, statusMessage: '已拒绝，Run 已终止。' };
    } catch (error) {
      await refresh(approvalFollowupRefreshOptions(selectedAfterAction)).catch(() => undefined);
      throw error;
    }
  }, [
    approvalFollowupRefreshOptions,
    refresh,
    refreshRunGroupsForRuns,
    runById,
    setSelectedRunId,
    upsertRunDetailCache,
  ]);

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
