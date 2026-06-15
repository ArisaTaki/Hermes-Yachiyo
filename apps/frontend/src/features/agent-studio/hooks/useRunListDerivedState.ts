import { useMemo } from 'react';

import type {
  AgentSpec,
  RunnableSummary,
  RunSpec,
  WorkflowSpec,
} from '../types';
import {
  runHistoryGroupsFor,
  runMatchesFilter,
  runMatchesSearch,
  runMatchesStatusFilter,
  runSearchTextByRunnableIdFor,
  type RunKindFilter,
  type RunStatusFilter,
} from '../utils/runs';

type UseRunListDerivedStateOptions = {
  agents: AgentSpec[];
  runDetailCache: RunSpec[];
  runKindFilter: RunKindFilter;
  runSearchQuery: string;
  runs: RunSpec[];
  runStatusFilter: RunStatusFilter;
  runnables: RunnableSummary[];
  selectedRunId: string;
  workflows: WorkflowSpec[];
};

export function useRunListDerivedState({
  agents,
  runDetailCache,
  runKindFilter,
  runSearchQuery,
  runs,
  runStatusFilter,
  runnables,
  selectedRunId,
  workflows,
}: UseRunListDerivedStateOptions) {
  const runById = useMemo(
    () => {
      const next = new Map<string, RunSpec>();
      runDetailCache.forEach((run) => next.set(run.run_id, run));
      runs.forEach((run) => next.set(run.run_id, run));
      return next;
    },
    [runDetailCache, runs],
  );
  const selectedRun = useMemo(
    () => selectedRunId ? runById.get(selectedRunId) || null : null,
    [runById, selectedRunId],
  );
  const selectedRunReplayRefreshKey = useMemo(
    () => selectedRunId
      ? [
          selectedRunId,
          selectedRun?.updated_at || '',
          selectedRun?.status || '',
          selectedRun?.timeline?.length || 0,
        ].join('|')
      : '',
    [selectedRun, selectedRunId],
  );
  const runFilterCounts = useMemo(
    () => ({
      all: runs.filter((run) => runMatchesFilter(run, 'all')).length,
      workflow: runs.filter((run) => runMatchesFilter(run, 'workflow')).length,
      agent: runs.filter((run) => runMatchesFilter(run, 'agent')).length,
    }),
    [runs],
  );
  const runKindFilteredRuns = useMemo(
    () => runs.filter((run) => runMatchesFilter(run, runKindFilter)),
    [runs, runKindFilter],
  );
  const runStatusFilterCounts = useMemo(
    () => ({
      all: runKindFilteredRuns.length,
      completed: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'completed')).length,
      failed: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'failed')).length,
      active: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'active')).length,
    }),
    [runKindFilteredRuns],
  );
  const runStatusFilteredRuns = useMemo(
    () => runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, runStatusFilter)),
    [runKindFilteredRuns, runStatusFilter],
  );
  const runSearchActive = Boolean(runSearchQuery.trim());
  const runSearchTextByRunnableId = useMemo(
    () => runSearchTextByRunnableIdFor(runnables, agents, workflows),
    [agents, runnables, workflows],
  );
  const filteredRuns = useMemo(
    () => runStatusFilteredRuns.filter((run) => (
      runMatchesSearch(run, runSearchQuery, runSearchTextByRunnableId.get(run.runnable_id) || '')
    )),
    [runSearchQuery, runSearchTextByRunnableId, runStatusFilteredRuns],
  );
  const filteredRunIds = useMemo(
    () => filteredRuns.map((run) => run.run_id).filter(Boolean),
    [filteredRuns],
  );
  const runHistoryGroups = useMemo(
    () => runHistoryGroupsFor(filteredRuns, runnables, agents),
    [agents, filteredRuns, runnables],
  );

  return {
    filteredRunIds,
    filteredRuns,
    runById,
    runFilterCounts,
    runHistoryGroups,
    runSearchActive,
    runStatusFilterCounts,
    runStatusFilteredRuns,
    selectedRun,
    selectedRunReplayRefreshKey,
  };
}
