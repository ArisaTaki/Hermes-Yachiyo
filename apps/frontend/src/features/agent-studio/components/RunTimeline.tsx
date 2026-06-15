import { RuntimeTimelinePanel } from '../../runtime-shared/components/RuntimeTimelinePanel';
import {
  timelineChildRunId,
  timelineEventCode,
  timelineEventName,
  timelineEventPayload,
  timelineEventTime,
  timelineEventTitle,
  timelineEventTone,
  timelineStatus,
} from '../utils/runTimeline';

type RunTimelineProps = {
  events: Record<string, unknown>[];
  replayError: string;
  replayEventCount: number;
  replayHasMore: boolean;
  replayLoading: boolean;
  formatRunDate: (value?: string) => string;
  getChildRunStatus: (childRunId: string, eventStatus: string) => string;
  onLoadMoreEvents: () => Promise<void> | void;
  onOpenRunDetail: (runId: string) => void;
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
};

export function RunTimeline({
  events,
  replayError,
  replayEventCount,
  replayHasMore,
  replayLoading,
  formatRunDate,
  getChildRunStatus,
  onLoadMoreEvents,
  onOpenRunDetail,
  runStatusLabel,
  runStatusTone,
}: RunTimelineProps) {
  return (
    <RuntimeTimelinePanel
      bodyClassName="run-detail-fold-body run-execution-steps"
      childRunTestId="agent-run-detail-execution-open-child-run"
      className="run-detail-block run-detail-fold run-execution-block"
      eventListTestId="agent-run-detail-execution-events"
      eventTestId="agent-run-detail-execution-event"
      events={events}
      formatEventTime={formatRunDate}
      getChildRunId={timelineChildRunId}
      getChildRunStatus={getChildRunStatus}
      getEventCode={timelineEventCode}
      getEventName={timelineEventName}
      getEventPayload={timelineEventPayload}
      getEventStatus={timelineStatus}
      getEventTime={timelineEventTime}
      getEventTitle={timelineEventTitle}
      getEventTone={timelineEventTone}
      loadMoreClassName="run-replay-more"
      loadMoreTestId="agent-run-detail-load-more-events"
      onLoadMoreEvents={replayEventCount ? onLoadMoreEvents : undefined}
      onOpenChildRun={onOpenRunDetail}
      panelTestId="agent-run-detail-execution"
      replayError={replayError}
      replayErrorClassName="run-replay-status"
      replayHasMore={Boolean(replayEventCount && replayHasMore)}
      replayLoading={replayLoading}
      runStatusLabel={runStatusLabel}
      runStatusTone={runStatusTone}
      subtitle={replayEventCount ? 'RunEvent replay facts' : '模型响应、工具调用、审批与完成节点'}
      summaryClassName="run-detail-section-head"
      title={`Execution · ${events.length}`}
      variant="full"
    />
  );
}
