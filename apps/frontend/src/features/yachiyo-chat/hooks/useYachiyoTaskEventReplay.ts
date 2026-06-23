import { useCallback, useEffect, useState } from 'react';

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

export function useYachiyoTaskEventReplay(task: AgentTaskSnapshot) {
  const [replayEvents, setReplayEvents] = useState<PublicRunEvent[]>([]);
  const [replayError, setReplayError] = useState('');
  const [replayHasMore, setReplayHasMore] = useState(false);
  const [replayLoading, setReplayLoading] = useState(false);
  const [replayNextAfterSequence, setReplayNextAfterSequence] = useState(0);
  const approvals = task.pending_approvals || [];
  const artifacts = task.artifacts || [];
  const toolCalls = task.tool_calls || [];
  const recentEvents = task.recent_events || [];
  const timelineEvents = replayEvents.length ? replayEvents : recentEvents;
  const replayApprovals = replayEvents.length ? approvalsFromRunEventReplay(replayEvents) : [];
  const replayArtifacts = replayEvents.length ? artifactsFromRunEventReplay(replayEvents) : [];
  const replayToolCalls = replayEvents.length ? toolCallsFromRunEventReplay(replayEvents) : [];
  const approvalFacts = mergeApprovalSnapshots(approvals, replayApprovals);
  const artifactFacts = mergeArtifactSnapshots(artifacts, replayArtifacts) as ArtifactSnapshot[];
  const toolCallFacts = mergeToolCallSnapshots(toolCalls, replayToolCalls) as ToolCallSnapshot[];
  const timelineSummaryEvents = timelineEvents.slice(-3);
  const timelineEventSource = replayEvents.length ? 'run_event_page' : 'task_snapshot';

  useEffect(() => {
    const taskId = String(task.task_id || '').trim();
    setReplayEvents([]);
    setReplayError('');
    setReplayHasMore(false);
    setReplayLoading(false);
    setReplayNextAfterSequence(0);
    if (!taskId) return undefined;
    let disposed = false;
    setReplayLoading(true);
    void listYachiyoTaskEvents(taskId, 0, TASK_EVENT_PAGE_SIZE)
      .then((page) => {
        if (disposed) return;
        const events = page.events || [];
        setReplayEvents(events);
        setReplayHasMore(page.has_more ?? events.length >= (page.limit || TASK_EVENT_PAGE_SIZE));
        setReplayNextAfterSequence(runEventPageNextCursor(page, events, 0));
        setReplayError('');
      })
      .catch((err: unknown) => {
        if (disposed) return;
        setReplayEvents([]);
        setReplayError(err instanceof Error ? err.message : '读取任务事件失败');
      })
      .finally(() => {
        if (!disposed) setReplayLoading(false);
      });
    return () => {
      disposed = true;
    };
  }, [task.task_id, task.updated_at]);

  const loadMoreTaskEvents = useCallback(async () => {
    const taskId = String(task.task_id || '').trim();
    if (!taskId || replayLoading) return;
    const afterSequence = replayNextAfterSequence || runEventSequenceCursor(replayEvents, 0);
    setReplayLoading(true);
    setReplayError('');
    try {
      const page = await listYachiyoTaskEvents(taskId, afterSequence, TASK_EVENT_PAGE_SIZE);
      const incomingEvents = page.events || [];
      const events = mergeRuntimeRunEventPages(replayEvents, incomingEvents);
      setReplayEvents(events);
      setReplayHasMore(page.has_more ?? incomingEvents.length >= (page.limit || TASK_EVENT_PAGE_SIZE));
      setReplayNextAfterSequence(runEventPageNextCursor(page, events, afterSequence));
    } catch (err) {
      setReplayError(err instanceof Error ? err.message : '读取更多任务事件失败');
    } finally {
      setReplayLoading(false);
    }
  }, [replayEvents, replayLoading, replayNextAfterSequence, task.task_id]);

  return {
    approvalFacts,
    artifactFacts,
    loadMoreTaskEvents,
    replayError,
    replayEvents,
    replayHasMore,
    replayLoading,
    replayNextAfterSequence,
    timelineEvents,
    timelineEventSource,
    timelineSummaryEvents,
    toolCallFacts,
  };
}
