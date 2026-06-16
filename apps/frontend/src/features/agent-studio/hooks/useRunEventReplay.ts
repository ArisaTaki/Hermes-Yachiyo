import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  mergeRuntimeRunEventPages,
  runEventPageNextCursor,
  runEventSequenceCursor,
} from '../../runtime-shared/runEvents';
import { listYachiyoRunEvents } from '../../yachiyo-studio/api';
import type { PublicRunEvent } from '../../yachiyo-studio/types';

export type RunEventReplayState = {
  events: PublicRunEvent[];
  limit: number;
  nextAfterSequence: number;
  hasMore: boolean;
  loading: boolean;
  error?: string;
};

const defaultRunEventReplayPageSize = 200;

export function useRunEventReplay(
  runId: string,
  refreshKey: string,
  pageSize = defaultRunEventReplayPageSize,
) {
  const [replayByRunId, setReplayByRunId] = useState<Record<string, RunEventReplayState>>({});
  const selectedReplayState = useMemo(
    () => runId ? replayByRunId[runId] || null : null,
    [replayByRunId, runId],
  );
  const selectedReplayEvents = useMemo(
    () => selectedReplayState?.events || [],
    [selectedReplayState],
  );
  const selectedReplayHasMore = Boolean(selectedReplayState?.hasMore);
  const selectedReplayLoading = Boolean(selectedReplayState?.loading);
  const selectedReplayError = selectedReplayState?.error || '';

  useEffect(() => {
    if (!runId) return;
    let disposed = false;
    setReplayByRunId((current) => ({
      ...current,
      [runId]: {
        events: current[runId]?.events || [],
        limit: pageSize,
        nextAfterSequence: current[runId]?.nextAfterSequence ?? 0,
        hasMore: current[runId]?.hasMore || false,
        loading: true,
        error: '',
      },
    }));
    listYachiyoRunEvents(runId, 0, pageSize)
      .then((page) => {
        if (disposed) return;
        const events = page.events || [];
        const limit = page.limit || pageSize;
        const nextAfterSequence = runEventPageNextCursor(page, events, 0);
        setReplayByRunId((current) => ({
          ...current,
          [runId]: {
            events,
            limit,
            nextAfterSequence,
            hasMore: page.has_more ?? events.length >= limit,
            loading: false,
            error: '',
          },
        }));
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setReplayByRunId((current) => ({
          ...current,
          [runId]: {
            events: current[runId]?.events || [],
            limit: current[runId]?.limit || pageSize,
            nextAfterSequence: current[runId]?.nextAfterSequence ?? 0,
            hasMore: current[runId]?.hasMore || false,
            loading: false,
            error: err instanceof Error ? err.message : '读取 RunEvent replay 失败',
          },
        }));
      });
    return () => {
      disposed = true;
    };
  }, [pageSize, refreshKey, runId]);

  const loadMoreSelectedRunEvents = useCallback(async () => {
    if (!runId) return 0;
    const currentState = replayByRunId[runId];
    const currentEvents = currentState?.events || [];
    const afterSequence = currentState?.nextAfterSequence ?? runEventSequenceCursor(currentEvents, 0);
    setReplayByRunId((current) => ({
      ...current,
      [runId]: {
        events: current[runId]?.events || currentEvents,
        limit: current[runId]?.limit || pageSize,
        nextAfterSequence: current[runId]?.nextAfterSequence ?? afterSequence,
        hasMore: current[runId]?.hasMore ?? true,
        loading: true,
        error: '',
      },
    }));
    try {
      const page = await listYachiyoRunEvents(runId, afterSequence, pageSize);
      const incomingEvents = page.events || [];
      const limit = page.limit || pageSize;
      setReplayByRunId((current) => {
        const previous = current[runId];
        const events = mergeRuntimeRunEventPages(previous?.events || currentEvents, incomingEvents);
        const nextAfterSequence = runEventPageNextCursor(page, events, afterSequence);
        return {
          ...current,
          [runId]: {
            events,
            limit,
            nextAfterSequence,
            hasMore: page.has_more ?? incomingEvents.length >= limit,
            loading: false,
            error: '',
          },
        };
      });
      return incomingEvents.length;
    } catch (err) {
      setReplayByRunId((current) => ({
        ...current,
        [runId]: {
          events: current[runId]?.events || currentEvents,
          limit: current[runId]?.limit || pageSize,
          nextAfterSequence: current[runId]?.nextAfterSequence ?? afterSequence,
          hasMore: current[runId]?.hasMore ?? true,
          loading: false,
          error: err instanceof Error ? err.message : '读取更多 RunEvent replay 失败',
        },
      }));
      return 0;
    }
  }, [pageSize, replayByRunId, runId]);

  const clearRunEventReplay = useCallback((runIds: Iterable<string>) => {
    setReplayByRunId((current) => {
      let changed = false;
      const next = { ...current };
      for (const runIdToDelete of runIds) {
        if (Object.prototype.hasOwnProperty.call(next, runIdToDelete)) {
          delete next[runIdToDelete];
          changed = true;
        }
      }
      return changed ? next : current;
    });
  }, []);

  return {
    clearRunEventReplay,
    loadMoreSelectedRunEvents,
    replayByRunId,
    selectedReplayError,
    selectedReplayEvents,
    selectedReplayHasMore,
    selectedReplayLoading,
    selectedReplayState,
  };
}
