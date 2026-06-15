import { useEffect, type Dispatch, type SetStateAction } from 'react';

import type { RunGroupSpec, RunSpec } from '../types';
import { getStudioRunForView } from '../utils/studioData';
import { isPotentialWorkflowChildAgentRun } from '../utils/runs';
import type { WorkflowChildRunRef } from '../utils/workflow';

type ArtifactPreview = { path: string; content: string; truncated?: boolean } | null;

type UseRunDetailSynchronizationOptions = {
  activeRunPollKey: string;
  refreshRunGroupById: (
    runGroupId: string,
    shouldApply?: () => boolean,
  ) => Promise<RunGroupSpec | null>;
  refreshRunGroupsForRuns: (
    runs: RunSpec[],
    shouldApply?: () => boolean,
  ) => Promise<void>;
  runById: Map<string, RunSpec>;
  runGroups: RunGroupSpec[];
  selectedRun: RunSpec | null;
  selectedRunId: string;
  selectedWorkflowApprovalChildRunId: string;
  selectedWorkflowChildRefs: WorkflowChildRunRef[];
  selectedWorkflowParentRunId: string;
  setArtifactPreview: Dispatch<SetStateAction<ArtifactPreview>>;
  upsertRunDetailCache: (runs: RunSpec[]) => void;
};

export function useRunDetailSynchronization({
  activeRunPollKey,
  refreshRunGroupById,
  refreshRunGroupsForRuns,
  runById,
  runGroups,
  selectedRun,
  selectedRunId,
  selectedWorkflowApprovalChildRunId,
  selectedWorkflowChildRefs,
  selectedWorkflowParentRunId,
  setArtifactPreview,
  upsertRunDetailCache,
}: UseRunDetailSynchronizationOptions) {
  useEffect(() => {
    if (!selectedRunId || selectedRun) return;
    let disposed = false;
    getStudioRunForView(selectedRunId)
      .then((run) => {
        if (!disposed) upsertRunDetailCache([run]);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [selectedRun, selectedRunId, upsertRunDetailCache]);

  useEffect(() => {
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return;
    const runGroupId = selectedRun.run_group_id || '';
    if (!runGroupId) return;
    if (runGroups.some((group) => group.run_group_id === runGroupId)) return;
    let disposed = false;
    refreshRunGroupById(runGroupId, () => !disposed)
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [refreshRunGroupById, runGroups, selectedRun]);

  useEffect(() => {
    if (!selectedWorkflowParentRunId || runById.has(selectedWorkflowParentRunId)) return;
    let disposed = false;
    getStudioRunForView(selectedWorkflowParentRunId)
      .then((run) => {
        if (!disposed) upsertRunDetailCache([run]);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [runById, selectedWorkflowParentRunId, upsertRunDetailCache]);

  useEffect(() => {
    const childRunIds = [
      ...selectedWorkflowChildRefs.map((ref) => ref.childRunId),
      selectedWorkflowApprovalChildRunId,
    ].filter((runId): runId is string => Boolean(runId));
    const uniqueChildRunIds = Array.from(new Set(childRunIds));
    if (!uniqueChildRunIds.length) return;
    let disposed = false;
    Promise.all(uniqueChildRunIds.map((runId) => getStudioRunForView(runId).catch(() => null)))
      .then((childRuns) => {
        if (disposed) return;
        const loaded = childRuns.filter((run): run is RunSpec => Boolean(run));
        if (!loaded.length) return;
        upsertRunDetailCache(loaded);
      });
    return () => {
      disposed = true;
    };
  }, [selectedWorkflowApprovalChildRunId, selectedWorkflowChildRefs, upsertRunDetailCache]);

  useEffect(() => {
    const pollRunIds = activeRunPollKey.split('|').filter(Boolean);
    if (!pollRunIds.length) return;
    let disposed = false;
    let inFlight = false;
    const pollRuns = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const loadedRuns = (await Promise.all(pollRunIds.map((runId) => getStudioRunForView(runId).catch(() => null))))
          .filter((run): run is RunSpec => Boolean(run));
        if (disposed || !loadedRuns.length) return;
        upsertRunDetailCache(loadedRuns);
        await refreshRunGroupsForRuns(loadedRuns, () => !disposed);
      } finally {
        inFlight = false;
      }
    };
    void pollRuns();
    const timer = window.setInterval(() => {
      void pollRuns();
    }, 2500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeRunPollKey, refreshRunGroupsForRuns, upsertRunDetailCache]);

  useEffect(() => {
    setArtifactPreview(null);
  }, [selectedRunId, setArtifactPreview]);
}
