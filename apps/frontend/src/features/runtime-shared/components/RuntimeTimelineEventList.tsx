import { ExpandableRuntimeContent } from './ExpandableRuntimeContent';

export type RuntimeTimelineEventRecord = Record<string, unknown>;

export type RuntimeTimelineEventListProps = {
  className: string;
  childRunTestId?: string;
  eventTestId: string;
  events: RuntimeTimelineEventRecord[];
  testId: string;
  variant?: 'compact' | 'full';
  formatEventTime?: (value?: string) => string;
  getChildRunId?: (event: RuntimeTimelineEventRecord) => string;
  getChildRunStatus?: (childRunId: string, eventStatus: string) => string;
  getEventCode?: (event: RuntimeTimelineEventRecord) => string;
  getEventName?: (event: RuntimeTimelineEventRecord) => string;
  getEventPayload?: (event: RuntimeTimelineEventRecord) => string;
  getEventStatus?: (event: RuntimeTimelineEventRecord) => string;
  getEventTime?: (event: RuntimeTimelineEventRecord) => string;
  getEventTitle?: (event: RuntimeTimelineEventRecord) => string;
  getEventTone?: (event: RuntimeTimelineEventRecord) => string;
  onOpenChildRun?: (runId: string) => void;
  runStatusLabel?: (status: string) => string;
  runStatusTone?: (status: string) => string;
};

export function RuntimeTimelineEventList({
  className,
  childRunTestId,
  eventTestId,
  events,
  testId,
  variant = 'compact',
  formatEventTime = defaultFormatEventTime,
  getChildRunId = defaultChildRunId,
  getChildRunStatus = defaultChildRunStatus,
  getEventCode = defaultEventCode,
  getEventName = defaultEventName,
  getEventPayload = defaultEventPayload,
  getEventStatus = defaultEventStatus,
  getEventTime = defaultEventTime,
  getEventTitle = defaultEventTitle,
  getEventTone = defaultEventTone,
  onOpenChildRun,
  runStatusLabel = defaultStatusLabel,
  runStatusTone = defaultStatusTone,
}: RuntimeTimelineEventListProps) {
  return (
    <ol className={className} data-testid={testId}>
      {events.map((event, index) => {
        const eventName = getEventName(event);
        const eventStatus = getEventStatus(event);
        const eventSequence = defaultEventSequence(event);
        const eventId = defaultEventId(event);
        const eventRunId = defaultEventRunId(event);
        const eventTitle = getEventTitle(event);
        const detail = defaultEventDetail(event);
        if (variant === 'full') {
          const childRunId = getChildRunId(event);
          const childRunStatus = childRunId ? getChildRunStatus(childRunId, eventStatus) : '';
          const eventTone = getEventTone(event);
          const payload = getEventPayload(event);
          return (
            <li
              className={`run-execution-step ${eventTone}`}
              data-child-run-id={childRunId || ''}
              data-run-event={eventName}
              data-run-event-actor={defaultEventActor(event)}
              data-run-event-id={eventId}
              data-run-event-run-id={eventRunId}
              data-run-event-sequence={eventSequence}
              data-run-event-sensitivity={defaultEventSensitivity(event)}
              data-run-event-schema-version={defaultEventSchemaVersion(event)}
              data-run-event-status={eventStatus || ''}
              data-run-event-tone={eventTone}
              data-run-event-visibility={defaultEventVisibility(event)}
              data-testid={eventTestId}
              key={`${eventName || 'event'}-${index}`}
            >
              <span className="run-step-rail"><i aria-hidden="true" /></span>
              <div className="run-step-card">
                <div className="run-step-head">
                  <div>
                    <strong>{eventTitle}</strong>
                    <span>{formatEventTime(getEventTime(event))}</span>
                  </div>
                  <code>{getEventCode(event)}</code>
                </div>
                {detail && detail !== eventTitle ? <p>{detail}</p> : null}
                {eventStatus ? (
                  <em className={`run-status-pill ${runStatusTone(eventStatus)}`}>
                    {runStatusLabel(eventStatus)}
                  </em>
                ) : null}
                {payload ? (
                  <ExpandableRuntimeContent
                    content={payload}
                    label="展开完整事件内容"
                    defaultOpen={eventTone === 'danger' || eventTone === 'approval'}
                  />
                ) : null}
                {childRunId && onOpenChildRun ? (
                  <button
                    type="button"
                    className="run-timeline-child"
                    data-run-id={childRunId}
                    data-run-status={childRunStatus}
                    data-testid={childRunTestId || `${eventTestId}-open-child-run`}
                    onClick={() => onOpenChildRun(childRunId)}
                  >
                    Child Run {childRunStatus ? `· ${runStatusLabel(childRunStatus)}` : ''} · {childRunId}
                  </button>
                ) : null}
              </div>
            </li>
          );
        }
        return (
          <li
            data-run-event={eventName}
            data-run-event-id={eventId}
            data-run-event-run-id={eventRunId}
            data-run-event-sequence={eventSequence}
            data-run-event-status={eventStatus}
            data-testid={eventTestId}
            key={eventId || `${eventName}-${eventSequence || index}`}
          >
            <span>{eventTitle}</span>
            {detail ? <p>{detail}</p> : null}
            {eventStatus ? <em>{runStatusLabel(eventStatus)}</em> : null}
          </li>
        );
      })}
    </ol>
  );
}

function defaultString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function defaultEventName(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.event_type) || defaultString(event.event) || defaultString(event.title) || 'event';
}

function defaultEventTitle(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.title) || defaultEventName(event) || '运行事件';
}

function defaultEventDetail(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.detail);
}

function defaultEventStatus(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.status);
}

function defaultEventId(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.event_id);
}

function defaultEventRunId(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.run_id);
}

function defaultEventSequence(event: RuntimeTimelineEventRecord): string {
  const value = event.sequence;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return defaultString(value);
}

function defaultEventActor(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.actor);
}

function defaultEventVisibility(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.visibility);
}

function defaultEventSensitivity(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.sensitivity);
}

function defaultEventSchemaVersion(event: RuntimeTimelineEventRecord): string {
  const value = event.schema_version;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return defaultString(value);
}

function defaultEventTime(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.created_at) || defaultString(event.time);
}

function defaultFormatEventTime(value?: string): string {
  return value || '';
}

function defaultEventCode(event: RuntimeTimelineEventRecord): string {
  const name = defaultEventName(event);
  return name.includes('.') ? name.split('.').slice(-2).join('.') : name || 'event';
}

function defaultEventPayload(): string {
  return '';
}

function defaultChildRunId(event: RuntimeTimelineEventRecord): string {
  return defaultString(event.child_run_id);
}

function defaultChildRunStatus(_childRunId: string, eventStatus: string): string {
  return eventStatus;
}

function defaultEventTone(event: RuntimeTimelineEventRecord): string {
  const name = defaultEventName(event);
  const status = defaultEventStatus(event);
  if (status === 'failed' || status === 'cancelled' || name.includes('failed') || name.includes('cancelled')) return 'danger';
  if (status === 'completed' || name.includes('completed')) return 'ready';
  if (status === 'approval_required' || name.includes('approval')) return 'approval';
  if (status === 'running' || status === 'processing') return 'running';
  return 'neutral';
}

function defaultStatusTone(status: string): string {
  if (status === 'failed' || status === 'cancelled') return 'danger';
  if (status === 'completed') return 'ready';
  if (status === 'approval_required' || status === 'waiting_approval') return 'approval';
  if (status === 'running' || status === 'processing') return 'running';
  return 'neutral';
}

function defaultStatusLabel(status: string): string {
  return status;
}
