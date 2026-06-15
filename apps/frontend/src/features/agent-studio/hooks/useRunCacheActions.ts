import { useCallback, type Dispatch, type SetStateAction } from 'react';

import {
  type RunGroupSpec,
  type RunSpec,
} from '../../../lib/agents';
import { getYachiyoGroupRun } from '../../yachiyo-studio/api';
import { publicGroupRunToRunGroupSpec } from '../utils/runs';

type UseRunCacheActionsOptions = {
  acceptedRunUpdates: (runs: RunSpec[]) => RunSpec[];
  setRunDetailCache: Dispatch<SetStateAction<RunSpec[]>>;
  setRunGroups: Dispatch<SetStateAction<RunGroupSpec[]>>;
  setRuns: Dispatch<SetStateAction<RunSpec[]>>;
};

export function useRunCacheActions({
  acceptedRunUpdates,
  setRunDetailCache,
  setRunGroups,
  setRuns,
}: UseRunCacheActionsOptions) {
  const upsertRunGroups = useCallback((nextGroups: RunGroupSpec[]) => {
    if (!nextGroups.length) return;
    setRunGroups((current) => {
      const nextById = new Map(current.map((group) => [group.run_group_id, group]));
      nextGroups.forEach((group) => nextById.set(group.run_group_id, group));
      return Array.from(nextById.values());
    });
  }, [setRunGroups]);

  const upsertRunDetailCache = useCallback((nextRuns: RunSpec[]) => {
    const visibleRuns = acceptedRunUpdates(nextRuns);
    if (!visibleRuns.length) return;
    setRunDetailCache((current) => {
      const nextById = new Map(current.map((run) => [run.run_id, run]));
      visibleRuns.forEach((run) => nextById.set(run.run_id, run));
      return Array.from(nextById.values());
    });
    setRuns((current) => {
      const nextById = new Map(visibleRuns.map((run) => [run.run_id, run]));
      let changed = false;
      const merged = current.map((run) => {
        const next = nextById.get(run.run_id);
        if (!next) return run;
        changed = true;
        return next;
      });
      return changed ? merged : current;
    });
  }, [acceptedRunUpdates, setRunDetailCache, setRuns]);

  const refreshRunGroupsForRuns = useCallback(async (
    nextRuns: RunSpec[],
    shouldApply: () => boolean = () => true,
  ) => {
    const groupIds = Array.from(new Set(nextRuns.map((run) => String(run.run_group_id || '')).filter(Boolean)));
    if (!groupIds.length) return;
    const loadedGroups = (await Promise.all(groupIds.map((groupId) => (
      getYachiyoGroupRun(groupId).then(publicGroupRunToRunGroupSpec).catch(() => null)
    ))))
      .filter((group): group is RunGroupSpec => Boolean(group));
    if (!shouldApply()) return;
    upsertRunGroups(loadedGroups);
  }, [upsertRunGroups]);

  const refreshRunGroupById = useCallback(async (
    runGroupId: string,
    shouldApply: () => boolean = () => true,
  ) => {
    if (!runGroupId) return null;
    const group = publicGroupRunToRunGroupSpec(await getYachiyoGroupRun(runGroupId));
    if (shouldApply()) upsertRunGroups([group]);
    return group;
  }, [upsertRunGroups]);

  return {
    refreshRunGroupById,
    refreshRunGroupsForRuns,
    upsertRunDetailCache,
    upsertRunGroups,
  };
}
