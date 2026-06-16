import { useCallback, useEffect, useMemo, useState } from 'react';

import { getYachiyoGroupRun, listYachiyoGroupRunEvents } from '../../yachiyo-studio/api';
import type { GroupRunSnapshot, PublicRunEvent } from '../../yachiyo-studio/types';
import { mergeRunEventReplayPages } from '../utils/runTimeline';

type GroupRunEventReplayState = {
  events: PublicRunEvent[];
  limit: number;
  nextAfterSequence: number;
  hasMore: boolean;
  loading: boolean;
  error?: string;
};

const defaultGroupRunEventReplayPageSize = 200;

export function useGroupRunSnapshot(
  groupRunId: string,
  refreshKey = '',
  pageSize = defaultGroupRunEventReplayPageSize,
) {
  const [groupRunById, setGroupRunById] = useState<Record<string, GroupRunSnapshot>>({});
  const [eventReplayByGroupRunId, setEventReplayByGroupRunId] = useState<Record<string, GroupRunEventReplayState>>({});
  const selectedGroupRunSnapshot = useMemo(
    () => groupRunId ? groupRunById[groupRunId] || null : null,
    [groupRunById, groupRunId],
  );
  const selectedGroupRunReplayState = useMemo(
    () => groupRunId ? eventReplayByGroupRunId[groupRunId] || null : null,
    [eventReplayByGroupRunId, groupRunId],
  );
  const selectedGroupRunReplayEvents = useMemo(
    () => selectedGroupRunReplayState?.events || [],
    [selectedGroupRunReplayState],
  );
  const selectedGroupRunReplayHasMore = Boolean(selectedGroupRunReplayState?.hasMore);
  const selectedGroupRunReplayLoading = Boolean(selectedGroupRunReplayState?.loading);
  const selectedGroupRunReplayError = selectedGroupRunReplayState?.error || '';

  useEffect(() => {
    if (!groupRunId) return;
    let disposed = false;
    getYachiyoGroupRun(groupRunId)
      .then((snapshot) => {
        if (disposed) return;
        setGroupRunById((current) => ({
          ...current,
          [groupRunId]: snapshot,
        }));
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [groupRunId, refreshKey]);

  useEffect(() => {
    if (!groupRunId) return;
    let disposed = false;
    setEventReplayByGroupRunId((current) => ({
      ...current,
      [groupRunId]: {
        events: current[groupRunId]?.events || [],
        limit: pageSize,
        nextAfterSequence: current[groupRunId]?.nextAfterSequence ?? 0,
        hasMore: current[groupRunId]?.hasMore || false,
        loading: true,
        error: '',
      },
    }));
    listYachiyoGroupRunEvents(groupRunId, 0, pageSize)
      .then((page) => {
        if (disposed) return;
        const events = page.events || [];
        const limit = page.limit || pageSize;
        const nextAfterSequence = groupRunEventPageCursor(page, events, 0);
        setEventReplayByGroupRunId((current) => ({
          ...current,
          [groupRunId]: {
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
        setEventReplayByGroupRunId((current) => ({
          ...current,
          [groupRunId]: {
            events: current[groupRunId]?.events || [],
            limit: current[groupRunId]?.limit || pageSize,
            nextAfterSequence: current[groupRunId]?.nextAfterSequence ?? 0,
            hasMore: current[groupRunId]?.hasMore || false,
            loading: false,
            error: err instanceof Error ? err.message : '读取 GroupRun Event replay 失败',
          },
        }));
      });
    return () => {
      disposed = true;
    };
  }, [groupRunId, pageSize, refreshKey]);

  const loadMoreSelectedGroupRunEvents = useCallback(async () => {
    if (!groupRunId) return 0;
    const currentState = eventReplayByGroupRunId[groupRunId];
    const currentEvents = currentState?.events || [];
    const afterSequence = currentState?.nextAfterSequence ?? groupRunEventSequenceCursor(currentEvents, 0);
    setEventReplayByGroupRunId((current) => ({
      ...current,
      [groupRunId]: {
        events: current[groupRunId]?.events || currentEvents,
        limit: current[groupRunId]?.limit || pageSize,
        nextAfterSequence: current[groupRunId]?.nextAfterSequence ?? afterSequence,
        hasMore: current[groupRunId]?.hasMore ?? true,
        loading: true,
        error: '',
      },
    }));
    try {
      const page = await listYachiyoGroupRunEvents(groupRunId, afterSequence, pageSize);
      const incomingEvents = page.events || [];
      const limit = page.limit || pageSize;
      setEventReplayByGroupRunId((current) => {
        const previous = current[groupRunId];
        const events = mergeRunEventReplayPages(previous?.events || currentEvents, incomingEvents);
        const nextAfterSequence = groupRunEventPageCursor(page, events, afterSequence);
        return {
          ...current,
          [groupRunId]: {
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
      setEventReplayByGroupRunId((current) => ({
        ...current,
        [groupRunId]: {
          events: current[groupRunId]?.events || currentEvents,
          limit: current[groupRunId]?.limit || pageSize,
          nextAfterSequence: current[groupRunId]?.nextAfterSequence ?? afterSequence,
          hasMore: current[groupRunId]?.hasMore ?? true,
          loading: false,
          error: err instanceof Error ? err.message : '读取更多 GroupRun Event replay 失败',
        },
      }));
      return 0;
    }
  }, [eventReplayByGroupRunId, groupRunId, pageSize]);

  return {
    groupRunById,
    loadMoreSelectedGroupRunEvents,
    selectedGroupRunReplayError,
    selectedGroupRunReplayEvents,
    selectedGroupRunReplayHasMore,
    selectedGroupRunReplayLoading,
    selectedGroupRunReplayNextAfterSequence: selectedGroupRunReplayState?.nextAfterSequence ?? 0,
    selectedGroupRunReplayState,
    selectedGroupRunSnapshot,
  };
}

function groupRunEventPageCursor(
  page: { next_after_sequence?: number },
  events: PublicRunEvent[],
  fallback: number,
): number {
  return Number.isFinite(page.next_after_sequence)
    ? Number(page.next_after_sequence)
    : groupRunEventSequenceCursor(events, fallback);
}

function groupRunEventSequenceCursor(events: PublicRunEvent[], fallback: number): number {
  return events.reduce(
    (max, event) => Math.max(max, Number(event.sequence) || 0),
    fallback,
  );
}
