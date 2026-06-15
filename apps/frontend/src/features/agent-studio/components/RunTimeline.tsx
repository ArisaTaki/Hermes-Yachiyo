import { RuntimeTimelineEventList } from '../../runtime-shared/components/RuntimeTimelineEventList';
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
    <details className="run-detail-block run-detail-fold run-execution-block" data-testid="agent-run-detail-execution" open>
      <summary className="run-detail-section-head">
        <div>
          <h4>Execution · {events.length}</h4>
          <span>{replayEventCount ? 'RunEvent replay facts' : '模型响应、工具调用、审批与完成节点'}</span>
        </div>
      </summary>
      <RuntimeTimelineEventList
        childRunTestId="agent-run-detail-execution-open-child-run"
        className="run-detail-fold-body run-execution-steps"
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
        onOpenChildRun={onOpenRunDetail}
        runStatusLabel={runStatusLabel}
        runStatusTone={runStatusTone}
        testId="agent-run-detail-execution-events"
        variant="full"
      />
      {replayError ? <p className="run-replay-status">{replayError}</p> : null}
      {replayEventCount && replayHasMore ? (
        <div className="run-replay-more">
          <button
            type="button"
            data-testid="agent-run-detail-load-more-events"
            disabled={replayLoading}
            onClick={() => void onLoadMoreEvents()}
          >
            {replayLoading ? '加载中...' : '加载更多 RunEvent'}
          </button>
        </div>
      ) : null}
    </details>
  );
}
