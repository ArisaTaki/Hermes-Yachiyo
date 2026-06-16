import { useGroupRunSnapshot } from './useGroupRunSnapshot';
import { useRunEventReplay } from './useRunEventReplay';
import { useRunTimeline } from './useRunTimeline';
import type { RunSpec } from '../types';

type UseAgentStudioRunSnapshotsOptions = {
  selectedRouteGroupRunId: string;
  selectedRun: RunSpec | null | undefined;
  selectedRunId: string;
  selectedRunReplayRefreshKey: string;
};

export function useAgentStudioRunSnapshots({
  selectedRouteGroupRunId,
  selectedRun,
  selectedRunId,
  selectedRunReplayRefreshKey,
}: UseAgentStudioRunSnapshotsOptions) {
  const selectedGroupRunSnapshotId = selectedRouteGroupRunId || selectedRun?.run_group_id || '';
  const groupRunSnapshot = useGroupRunSnapshot(
    selectedGroupRunSnapshotId,
    selectedRunReplayRefreshKey,
  );
  const { selectedPublicRunTimeline } = useRunTimeline(selectedRunId, selectedRunReplayRefreshKey);
  const runEventReplay = useRunEventReplay(selectedRunId, selectedRunReplayRefreshKey);

  return {
    selectedGroupRunSnapshotId,
    loadMoreGroupRunReplayEvents: groupRunSnapshot.loadMoreSelectedGroupRunEvents,
    selectedGroupRunReplayError: groupRunSnapshot.selectedGroupRunReplayError,
    selectedGroupRunReplayEvents: groupRunSnapshot.selectedGroupRunReplayEvents,
    selectedGroupRunReplayHasMore: groupRunSnapshot.selectedGroupRunReplayHasMore,
    selectedGroupRunReplayLoading: groupRunSnapshot.selectedGroupRunReplayLoading,
    selectedGroupRunReplayNextAfterSequence: groupRunSnapshot.selectedGroupRunReplayNextAfterSequence,
    selectedGroupRunSnapshot: groupRunSnapshot.selectedGroupRunSnapshot,
    selectedPublicRunTimeline,
    clearRunEventReplay: runEventReplay.clearRunEventReplay,
    loadMoreRunReplayEvents: runEventReplay.loadMoreSelectedRunEvents,
    selectedRunReplayError: runEventReplay.selectedReplayError,
    selectedRunReplayEvents: runEventReplay.selectedReplayEvents,
    selectedRunReplayHasMore: runEventReplay.selectedReplayHasMore,
    selectedRunReplayLoading: runEventReplay.selectedReplayLoading,
    selectedRunReplayState: runEventReplay.selectedReplayState,
  };
}
