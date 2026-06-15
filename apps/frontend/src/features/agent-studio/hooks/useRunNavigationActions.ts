import type { Dispatch, SetStateAction } from 'react';

import type { RunSpec } from '../types';
import { navigateTo } from '../../../lib/view';
import type { GroupRunSnapshot } from '../../yachiyo-studio/types';
import { groupRunTimelineRunId } from '../utils/groups';
import {
  runHistoryGroupKey,
  runMatchesFilter,
  runMatchesStatusFilter,
  type RunKindFilter,
  type RunStatusFilter,
} from '../utils/runs';

type UseRunNavigationActionsOptions = {
  runs: RunSpec[];
  selectedRun: RunSpec | null;
  selectedRunId: string;
  setCollapsedRunHistoryGroups: Dispatch<SetStateAction<Set<string>>>;
  setError: (message: string) => void;
  setRunKindFilter: (filter: RunKindFilter) => void;
  setRunSearchQuery: (query: string) => void;
  setRunStatusFilter: (filter: RunStatusFilter) => void;
  setSelectedRunId: (runId: string) => void;
  setTab: (tab: 'runs') => void;
};

export function useRunNavigationActions({
  runs,
  selectedRun,
  selectedRunId,
  setCollapsedRunHistoryGroups,
  setError,
  setRunKindFilter,
  setRunSearchQuery,
  setRunStatusFilter,
  setSelectedRunId,
  setTab,
}: UseRunNavigationActionsOptions) {
  function openRunDetail(runId: string, options: { revealInHistory?: boolean; groupRunId?: string } = {}) {
    if (options.revealInHistory) {
      setRunKindFilter('all');
      setRunStatusFilter('all');
      setRunSearchQuery('');
    }
    setSelectedRunId(runId);
    setTab('runs');
    const run = runs.find((item) => item.run_id === runId);
    if (run) {
      const groupKey = runHistoryGroupKey(run);
      setCollapsedRunHistoryGroups((current) => {
        if (!current.has(groupKey)) return current;
        const next = new Set(current);
        next.delete(groupKey);
        return next;
      });
    }
    navigateTo('agents', {
      run: runId,
      ...(options.groupRunId ? { group_run: options.groupRunId } : {}),
    }, ['tab', 'target', 'goal']);
  }

  function openAgentGroupRunTimeline(groupRun: GroupRunSnapshot | null) {
    const runId = groupRunTimelineRunId(groupRun);
    if (!runId) {
      setError('这个 GroupRun 暂时没有可打开的子 Run。');
      return;
    }
    openRunDetail(runId, { groupRunId: groupRun?.group_run_id || '', revealInHistory: true });
  }

  function toggleRunHistoryGroup(groupKey: string) {
    setCollapsedRunHistoryGroups((current) => {
      const next = new Set(current);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  }

  function selectRunKindFilter(nextFilter: RunKindFilter) {
    setRunKindFilter(nextFilter);
    if (selectedRun && runMatchesFilter(selectedRun, nextFilter)) return;
    if (selectedRunId) {
      setSelectedRunId('');
      setTab('runs');
      navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
    }
  }

  function selectRunStatusFilter(nextFilter: RunStatusFilter) {
    setRunStatusFilter(nextFilter);
    if (selectedRun && runMatchesStatusFilter(selectedRun, nextFilter)) return;
    if (selectedRunId) {
      setSelectedRunId('');
      setTab('runs');
      navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
    }
  }

  return {
    openAgentGroupRunTimeline,
    openRunDetail,
    selectRunKindFilter,
    selectRunStatusFilter,
    toggleRunHistoryGroup,
  };
}
