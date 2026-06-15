import { ExpandableRuntimeContent as RunExpandableContent } from '../../runtime-shared/components/ExpandableRuntimeContent';
import {
  timelineChildRunId,
  timelineEventCode,
  timelineEventName,
  timelineEventPayload,
  timelineEventSequence,
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
      <ol className="run-detail-fold-body run-execution-steps" data-testid="agent-run-detail-execution-events">
        {events.map((event, index) => {
          const childRunId = timelineChildRunId(event);
          const eventStatus = timelineStatus(event);
          const childRunStatus = childRunId ? getChildRunStatus(childRunId, eventStatus) : '';
          const payload = timelineEventPayload(event);
          const detail = String(event.detail || '').trim();
          const eventTone = timelineEventTone(event);
          const eventName = timelineEventName(event);
          const eventSequence = timelineEventSequence(event);
          const eventId = String(event.event_id || '').trim();
          const eventRunId = String(event.run_id || '').trim();
          const eventActor = String(event.actor || '').trim();
          const eventVisibility = String(event.visibility || '').trim();
          const eventSensitivity = String(event.sensitivity || '').trim();
          const eventSchemaVersion = String(event.schema_version || '').trim();
          return (
            <li
              className={`run-execution-step ${eventTone}`}
              data-child-run-id={childRunId || ''}
              data-run-event={eventName}
              data-run-event-actor={eventActor}
              data-run-event-id={eventId}
              data-run-event-run-id={eventRunId}
              data-run-event-sequence={eventSequence}
              data-run-event-sensitivity={eventSensitivity}
              data-run-event-schema-version={eventSchemaVersion}
              data-run-event-status={eventStatus || ''}
              data-run-event-tone={eventTone}
              data-run-event-visibility={eventVisibility}
              data-testid="agent-run-detail-execution-event"
              key={`${eventName || 'event'}-${index}`}
            >
              <span className="run-step-rail"><i aria-hidden="true" /></span>
              <div className="run-step-card">
                <div className="run-step-head">
                  <div>
                    <strong>{timelineEventTitle(event)}</strong>
                    <span>{formatRunDate(timelineEventTime(event))}</span>
                  </div>
                  <code>{timelineEventCode(event)}</code>
                </div>
                {detail && detail !== timelineEventTitle(event) ? <p>{detail}</p> : null}
                {eventStatus ? (
                  <em className={`run-status-pill ${runStatusTone(eventStatus)}`}>
                    {runStatusLabel(eventStatus)}
                  </em>
                ) : null}
                {payload ? (
                  <RunExpandableContent
                    content={payload}
                    label="展开完整事件内容"
                    defaultOpen={eventTone === 'danger' || eventTone === 'approval'}
                  />
                ) : null}
                {childRunId ? (
                  <button
                    type="button"
                    className="run-timeline-child"
                    data-run-id={childRunId}
                    data-run-status={childRunStatus}
                    data-testid="agent-run-detail-execution-open-child-run"
                    onClick={() => onOpenRunDetail(childRunId)}
                  >
                    Child Run {childRunStatus ? `· ${runStatusLabel(childRunStatus)}` : ''} · {childRunId}
                  </button>
                ) : null}
              </div>
            </li>
          );
        })}
      </ol>
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
