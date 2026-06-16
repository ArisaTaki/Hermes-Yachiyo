import { useRunApprovalActions, type RunApprovalActionRefreshOptions } from './useRunApprovalActions';
import { useRunApprovalFollowup } from './useRunApprovalFollowup';
import type { RunSpec } from '../types';

type UseAgentStudioRunApprovalControlsOptions = {
  acceptedRunUpdates: (runs: RunSpec[]) => RunSpec[];
  refresh: (options?: RunApprovalActionRefreshOptions) => Promise<void>;
  refreshRunGroupsForRuns: (runs: RunSpec[]) => Promise<void>;
  rememberApprovedRun: (run: RunSpec | null | undefined) => void;
  runById: Map<string, RunSpec>;
  selectedRun: RunSpec | null;
  selectedRunId: string;
  setError: (message: string) => void;
  setSelectedRunId: (runId: string) => void;
  setStatus: (message: string) => void;
  upsertRunDetailCache: (runs: RunSpec[]) => void;
};

export function useAgentStudioRunApprovalControls({
  acceptedRunUpdates,
  refresh,
  refreshRunGroupsForRuns,
  rememberApprovedRun,
  runById,
  selectedRun,
  selectedRunId,
  setError,
  setSelectedRunId,
  setStatus,
  upsertRunDetailCache,
}: UseAgentStudioRunApprovalControlsOptions) {
  const {
    approvalFollowupRefreshOptions,
    isApprovalFollowupCurrent,
    pollApprovedRunProgress,
  } = useRunApprovalFollowup({
    acceptedRunUpdates,
    refresh,
    refreshRunGroupsForRuns,
    selectedRunId,
    setStatus,
    upsertRunDetailCache,
  });

  return useRunApprovalActions({
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
  });
}
