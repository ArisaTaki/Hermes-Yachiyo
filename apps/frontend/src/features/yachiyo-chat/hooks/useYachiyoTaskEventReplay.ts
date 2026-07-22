import { useCallback, useEffect, useMemo, useRef, useState } from 'react';

import {
  approvalsFromRunEventReplay,
  artifactsFromRunEventReplay,
  mergeApprovalSnapshots,
  mergeArtifactSnapshots,
  mergeToolCallSnapshots,
  toolCallsFromRunEventReplay,
} from '../../runtime-shared/runEventFacts';
import {
  mergeRuntimeRunEventPages,
  runEventPageNextCursor,
  runEventSequenceCursor,
} from '../../runtime-shared/runEvents';
import { listYachiyoTaskEvents } from '../api';
import type { AgentTaskSnapshot, ArtifactSnapshot, PublicRunEvent, ToolCallSnapshot } from '../types';

const TASK_EVENT_PAGE_SIZE = 200;
const EMPTY_RUN_EVENTS: PublicRunEvent[] = [];

export function useYachiyoTaskEventReplay(
  task: AgentTaskSnapshot,
  { enabled = true }: { enabled?: boolean } = {},
) {
  const [replayEvents, setReplayEvents] = useState<PublicRunEvent[]>([]);
  const [replayError, setReplayError] = useState('');
  const [replayHasMore, setReplayHasMore] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayNextAfterSequence, setReplayNextAfterSequence] = useState(0);
  const replayEventsRef = useRef<PublicRunEvent[]>([]);
  const replayNextAfterSequenceRef = useRef(0);
  const replayRequestIdRef = useRef(0);
  const replayTaskIdRef = useRef(String(task.task_id || '').trim());
  const taskId = String(task.task_id || '').trim();
  const replayBelongsToTask = replayTaskIdRef.current === taskId;
  const currentReplayEvents = replayBelongsToTask ? replayEvents : EMPTY_RUN_EVENTS;
  const {
    approvalFacts,
    artifactFacts,
    timelineEvents,
    timelineEventSource,
    timelineSummaryEvents,
    toolCallFacts,
  } = useMemo(() => {
    const approvals = task.pending_approvals || [];
    const artifacts = task.artifacts || [];
    const toolCalls = task.tool_calls || [];
    const recentEvents = task.recent_events || [];
    const derivedTimelineEvents = currentReplayEvents.length ? currentReplayEvents : recentEvents;
    const replayApprovals = currentReplayEvents.length
      ? approvalsFromRunEventReplay(currentReplayEvents)
      : [];
    const replayArtifacts = currentReplayEvents.length
      ? artifactsFromRunEventReplay(currentReplayEvents)
      : [];
    const replayToolCalls = currentReplayEvents.length
      ? toolCallsFromRunEventReplay(currentReplayEvents)
      : [];
    return {
      approvalFacts: mergeApprovalSnapshots(approvals, replayApprovals),
      artifactFacts: mergeArtifactSnapshots(artifacts, replayArtifacts) as ArtifactSnapshot[],
      timelineEvents: derivedTimelineEvents,
      timelineEventSource: currentReplayEvents.length ? 'run_event_page' : 'task_snapshot',
      timelineSummaryEvents: derivedTimelineEvents.slice(-3),
      toolCallFacts: mergeToolCallSnapshots(toolCalls, replayToolCalls) as ToolCallSnapshot[],
    };
  }, [
    currentReplayEvents,
    task.artifacts,
    task.pending_approvals,
    task.recent_events,
    task.tool_calls,
  ]);

  useEffect(() => {
    const taskId = String(task.task_id || '').trim();
    const taskChanged = replayTaskIdRef.current !== taskId;
    if (taskChanged) {
      replayTaskIdRef.current = taskId;
      replayRequestIdRef.current += 1;
      replayEventsRef.current = [];
      replayNextAfterSequenceRef.current = 0;
      setReplayEvents([]);
      setReplayError('');
      setReplayHasMore(false);
      setReplayLoading(false);
      setReplayNextAfterSequence(0);
    }
    if (!enabled || !taskId) {
      replayRequestIdRef.current += 1;
      setReplayLoading(false);
      return undefined;
    }
    const afterSequence = taskChanged
      ? 0
      : replayNextAfterSequenceRef.current || runEventSequenceCursor(replayEventsRef.current, 0);
    const requestId = replayRequestIdRef.current + 1;
    replayRequestIdRef.current = requestId;
    setReplayLoading(true);
    setReplayError('');
    void listYachiyoTaskEvents(taskId, afterSequence, TASK_EVENT_PAGE_SIZE)
      .then((page) => {
        if (requestId !== replayRequestIdRef.current || replayTaskIdRef.current !== taskId) return;
        const incomingEvents = page.events || [];
        const events = mergeRuntimeRunEventPages(taskChanged ? [] : replayEventsRef.current, incomingEvents);
        const nextAfterSequence = runEventPageNextCursor(page, events, afterSequence);
        replayEventsRef.current = events;
        replayNextAfterSequenceRef.current = nextAfterSequence;
        setReplayEvents(events);
        setReplayNextAfterSequence(nextAfterSequence);
        setReplayHasMore(page.has_more ?? incomingEvents.length >= (page.limit || TASK_EVENT_PAGE_SIZE));
        setReplayError('');
      })
      .catch((err: unknown) => {
        if (requestId !== replayRequestIdRef.current || replayTaskIdRef.current !== taskId) return;
        setReplayError(err instanceof Error ? err.message : '读取任务事件失败');
      })
      .finally(() => {
        if (requestId === replayRequestIdRef.current && replayTaskIdRef.current === taskId) {
          setReplayLoading(false);
        }
      });
    return () => {
      if (requestId === replayRequestIdRef.current) replayRequestIdRef.current += 1;
    };
  }, [enabled, task.task_id, task.updated_at]);

  const loadMoreTaskEvents = useCallback(async () => {
    const taskId = String(task.task_id || '').trim();
    if (!enabled || !taskId || replayLoading || replayTaskIdRef.current !== taskId) return;
    const afterSequence = replayNextAfterSequenceRef.current || runEventSequenceCursor(replayEventsRef.current, 0);
    const requestId = replayRequestIdRef.current + 1;
    replayRequestIdRef.current = requestId;
    setReplayLoading(true);
    setReplayError('');
    try {
      const page = await listYachiyoTaskEvents(taskId, afterSequence, TASK_EVENT_PAGE_SIZE);
      if (requestId !== replayRequestIdRef.current || replayTaskIdRef.current !== taskId) return;
      const incomingEvents = page.events || [];
      const events = mergeRuntimeRunEventPages(replayEventsRef.current, incomingEvents);
      const nextAfterSequence = runEventPageNextCursor(page, events, afterSequence);
      replayEventsRef.current = events;
      replayNextAfterSequenceRef.current = nextAfterSequence;
      setReplayEvents(events);
      setReplayNextAfterSequence(nextAfterSequence);
      setReplayHasMore(page.has_more ?? incomingEvents.length >= (page.limit || TASK_EVENT_PAGE_SIZE));
    } catch (err) {
      if (requestId !== replayRequestIdRef.current || replayTaskIdRef.current !== taskId) return;
      setReplayError(err instanceof Error ? err.message : '读取更多任务事件失败');
    } finally {
      if (requestId === replayRequestIdRef.current && replayTaskIdRef.current === taskId) {
        setReplayLoading(false);
      }
    }
  }, [enabled, replayLoading, task.task_id]);

  return {
    approvalFacts,
    artifactFacts,
    loadMoreTaskEvents,
    replayError,
    replayEvents: currentReplayEvents,
    replayHasMore,
    replayLoading,
    replayNextAfterSequence,
    timelineEvents,
    timelineEventSource,
    timelineSummaryEvents,
    toolCallFacts,
  };
}
