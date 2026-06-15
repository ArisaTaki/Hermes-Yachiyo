import { useCallback, useEffect, useRef } from 'react';

import type { RunSpec } from '../../../lib/agents';
import { getYachiyoRunTimeline } from '../../yachiyo-studio/api';
import {
  approvedRunStatusMessage,
  isActiveRunStatus,
  normalizeRunStatus,
  publicRunTimelineToRunSpec,
} from '../utils/runs';

type ApprovalFollowupRefreshOptions = {
  selectedRunId?: string;
};

type UseRunApprovalFollowupOptions = {
  acceptedRunUpdates: (runs: RunSpec[]) => RunSpec[];
  refresh: (options?: ApprovalFollowupRefreshOptions) => Promise<void>;
  refreshRunGroupsForRuns: (runs: RunSpec[]) => Promise<void>;
  selectedRunId: string;
  setStatus: (message: string) => void;
  upsertRunDetailCache: (runs: RunSpec[]) => void;
};

const runApprovalPollAttempts = 100;
const runApprovalPollIntervalMs = 1200;

export function useRunApprovalFollowup({
  acceptedRunUpdates,
  refresh,
  refreshRunGroupsForRuns,
  selectedRunId,
  setStatus,
  upsertRunDetailCache,
}: UseRunApprovalFollowupOptions) {
  const selectedRunIdRef = useRef(selectedRunId);

  useEffect(() => {
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  const isApprovalFollowupCurrent = useCallback((selectedAfterAction: string): boolean => (
    selectedRunIdRef.current === selectedAfterAction
  ), []);

  const approvalFollowupRefreshOptions = useCallback((
    selectedAfterAction: string,
  ): ApprovalFollowupRefreshOptions => (
    isApprovalFollowupCurrent(selectedAfterAction) ? { selectedRunId: selectedAfterAction } : {}
  ), [isApprovalFollowupCurrent]);

  const pollApprovedRunProgress = useCallback(async (
    runId: string,
    selectedAfterAction: string,
  ) => {
    const pollRunIds = Array.from(new Set([runId, selectedAfterAction].filter(Boolean)));
    if (!pollRunIds.length) return;
    for (let attempt = 0; attempt < runApprovalPollAttempts; attempt += 1) {
      await new Promise<void>((resolve) => {
        window.setTimeout(resolve, attempt === 0 ? 300 : runApprovalPollIntervalMs);
      });
      const loadedRuns = (await Promise.all(pollRunIds.map((id) => (
        getYachiyoRunTimeline(id).then(publicRunTimelineToRunSpec).catch(() => null)
      ))))
        .filter((run): run is RunSpec => Boolean(run));
      const visibleRuns = acceptedRunUpdates(loadedRuns);
      if (!visibleRuns.length) continue;
      upsertRunDetailCache(visibleRuns);
      await refreshRunGroupsForRuns(visibleRuns);
      const approvedRun = visibleRuns.find((run) => run.run_id === runId) || null;
      const selectedRunUpdate = visibleRuns.find((run) => run.run_id === selectedAfterAction) || null;
      const watchedRun = selectedRunUpdate || approvedRun;
      if (!watchedRun) continue;
      const watchedStatus = normalizeRunStatus(watchedRun.status);
      if (watchedStatus === 'approval_required') {
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setStatus('Run 需要处理下一次审批。');
        }
        await refresh(approvalFollowupRefreshOptions(selectedAfterAction));
        return;
      }
      if (!isActiveRunStatus(watchedRun.status)) {
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setStatus(approvedRunStatusMessage(watchedRun));
        }
        await refresh(approvalFollowupRefreshOptions(selectedAfterAction));
        return;
      }
    }
    await refresh(approvalFollowupRefreshOptions(selectedAfterAction));
  }, [
    acceptedRunUpdates,
    approvalFollowupRefreshOptions,
    isApprovalFollowupCurrent,
    refresh,
    refreshRunGroupsForRuns,
    setStatus,
    upsertRunDetailCache,
  ]);

  return {
    approvalFollowupRefreshOptions,
    isApprovalFollowupCurrent,
    pollApprovedRunProgress,
  };
}
