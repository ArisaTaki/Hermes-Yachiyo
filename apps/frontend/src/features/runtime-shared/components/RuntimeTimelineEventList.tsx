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
  getEventDetail?: (event: RuntimeTimelineEventRecord) => string;
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
  getEventDetail = defaultEventDetail,
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
        const eventIsSecret = defaultEventIsSecret(event);
        const eventTitle = eventIsSecret ? defaultSecretEventTitle(event) : getEventTitle(event);
        const detail = eventIsSecret ? '' : getEventDetail(event);
        if (variant === 'full') {
          const childRunId = getChildRunId(event);
          const childRunStatus = childRunId ? getChildRunStatus(childRunId, eventStatus) : '';
          const eventTone = getEventTone(event);
          const payload = eventIsSecret ? '' : getEventPayload(event);
          const payloadRecord = runtimeEventPayloadRecord(event);
          const traceContext = runtimeEventTraceContext(event, payloadRecord);
          const plannerContext = runtimeEventPlannerContext(event, payloadRecord);
          const eventMetadata = runtimeEventMetadata(
            event,
            payloadRecord,
            traceContext,
            plannerContext,
            eventSequence,
            eventRunId,
          );
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
              data-run-event-group-id={traceContext.groupId}
              data-run-event-group-run-id={traceContext.groupRunId}
              data-run-event-member-agent-id={traceContext.memberAgentId}
              data-run-event-launcher-mode={plannerContext.launcherMode}
              data-run-event-launcher-surface={plannerContext.launcherSurface}
              data-run-event-entrypoint-source={plannerContext.entrypointSource}
              data-run-event-planner-entrypoint={plannerContext.plannerEntrypoint}
              data-run-event-runnable-kind={plannerContext.runnableKind}
              data-run-event-selection-role={plannerContext.selectionRole}
              data-run-event-selection-source={plannerContext.selectionSource}
              data-run-event-status={eventStatus || ''}
              data-run-event-tone={eventTone}
              data-run-event-visibility={defaultEventVisibility(event)}
              data-run-event-workflow-id={traceContext.workflowId}
              data-run-event-workflow-node-id={traceContext.workflowNodeId}
              data-run-event-workflow-run-id={traceContext.workflowRunId}
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
                {eventMetadata.length ? (
                  <div className="run-step-meta" data-testid={`${eventTestId}-metadata`}>
                    {eventMetadata.map(({ label, value }) => (
                      <span key={`${label}:${value}`}>{label} {value}</span>
                    ))}
                  </div>
                ) : null}
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

function defaultSecretEventTitle(event: RuntimeTimelineEventRecord): string {
  return defaultEventName(event) || '运行事件';
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

function defaultEventIsSecret(event: RuntimeTimelineEventRecord): boolean {
  return defaultEventSensitivity(event) === 'secret';
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

function runtimeEventMetadata(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  traceContext: RuntimeTimelineTraceContext,
  plannerContext: RuntimeTimelinePlannerContext,
  eventSequence: string,
  eventRunId: string,
): Array<{ label: string; value: string }> {
  return [
    { label: '#', value: eventSequence },
    { label: 'run', value: eventRunId },
    { label: 'tool', value: runtimeEventString(event, payload, 'tool_call_id') },
    {
      label: 'approval',
      value: runtimeEventString(event, payload, 'approval_id')
        || runtimeEventNestedString(payload, 'pending_approval', 'approval_id')
        || runtimeEventNestedString(payload, 'approval', 'approval_id'),
    },
    { label: 'artifact', value: runtimeEventString(event, payload, 'artifact_id') },
    { label: 'memory', value: runtimeEventMemoryId(event, payload) },
    { label: 'skill', value: runtimeEventSkillId(event, payload) },
    {
      label: 'workflow',
      value: traceContext.workflowNodeLabel
        || traceContext.workflowNodeId
        || traceContext.workflowRunId
        || traceContext.workflowId,
    },
    {
      label: 'planner',
      value: plannerContext.selectionRole || plannerContext.selectionSource,
    },
    {
      label: 'entrypoint',
      value: plannerContext.plannerEntrypoint || plannerContext.entrypointSource,
    },
    {
      label: 'surface',
      value: plannerContext.launcherSurface || plannerContext.launcherMode,
    },
    { label: 'runnable', value: plannerContext.runnableKind },
    { label: 'group', value: traceContext.groupRunId || traceContext.groupId },
    { label: 'member', value: traceContext.memberAgentName || traceContext.memberAgentId },
    { label: 'child', value: defaultChildRunId(event) || runtimeEventString(event, payload, 'child_run_id') },
    { label: 'actor', value: defaultEventActor(event) },
    { label: 'visibility', value: defaultEventVisibility(event) },
    { label: 'sensitivity', value: defaultEventSensitivity(event) },
    { label: 'schema', value: defaultEventSchemaVersion(event) },
  ].filter((item) => item.value);
}

type RuntimeTimelineTraceContext = {
  groupId: string;
  groupRunId: string;
  memberAgentId: string;
  memberAgentName: string;
  workflowId: string;
  workflowNodeId: string;
  workflowNodeLabel: string;
  workflowRunId: string;
};

type RuntimeTimelinePlannerContext = {
  entrypointSource: string;
  launcherMode: string;
  launcherSurface: string;
  plannerEntrypoint: string;
  runnableKind: string;
  selectionRole: string;
  selectionSource: string;
};

function runtimeEventTraceContext(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelineTraceContext {
  const approvalContext = runtimeEventNestedRecord(payload, 'pending_approval')
    || runtimeEventNestedRecord(payload, 'approval')
    || {};
  return {
    groupId: runtimeEventTraceString(event, payload, approvalContext, 'group_id'),
    groupRunId: runtimeEventTraceString(event, payload, approvalContext, 'group_run_id', 'run_group_id'),
    memberAgentId: runtimeEventTraceString(
      event,
      payload,
      approvalContext,
      'member_agent_id',
      'source_runnable_id',
      'source_agent_id',
      'agent_id',
    ),
    memberAgentName: runtimeEventTraceString(
      event,
      payload,
      approvalContext,
      'member_agent_name',
      'source_runnable_name',
      'source_agent_name',
      'agent_name',
    ),
    workflowId: runtimeEventTraceString(event, payload, approvalContext, 'workflow_id'),
    workflowNodeId: runtimeEventTraceString(event, payload, approvalContext, 'workflow_node_id'),
    workflowNodeLabel: runtimeEventTraceString(event, payload, approvalContext, 'workflow_node_label'),
    workflowRunId: runtimeEventTraceString(event, payload, approvalContext, 'workflow_run_id'),
  };
}

function runtimeEventPlannerContext(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelinePlannerContext {
  return {
    entrypointSource: runtimeEventString(event, payload, 'entrypoint_source'),
    launcherMode: runtimeEventString(event, payload, 'launcher_mode'),
    launcherSurface: runtimeEventString(event, payload, 'launcher_surface'),
    plannerEntrypoint: runtimeEventString(event, payload, 'planner_entrypoint'),
    runnableKind: runtimeEventString(event, payload, 'runnable_kind'),
    selectionRole: runtimeEventString(event, payload, 'selection_role'),
    selectionSource: runtimeEventString(event, payload, 'selection_source'),
  };
}

function runtimeEventPayloadRecord(event: RuntimeTimelineEventRecord): RuntimeTimelineEventRecord {
  const payload = event.payload;
  return payload && typeof payload === 'object' && !Array.isArray(payload)
    ? payload as RuntimeTimelineEventRecord
    : {};
}

function runtimeEventString(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  key: string,
): string {
  return defaultString(event[key]) || defaultString(payload[key]);
}

function runtimeEventTraceString(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  nested: RuntimeTimelineEventRecord,
  ...keys: string[]
): string {
  for (const key of keys) {
    const value = runtimeEventString(event, payload, key) || defaultString(nested[key]);
    if (value) return value;
  }
  return '';
}

function runtimeEventMemoryId(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): string {
  const memories = payload.memories;
  const firstMemory = Array.isArray(memories) ? memories[0] : null;
  const firstMemoryId = firstMemory && typeof firstMemory === 'object' && !Array.isArray(firstMemory)
    ? defaultString((firstMemory as RuntimeTimelineEventRecord).memory_id)
    : '';
  return runtimeEventString(event, payload, 'memory_id') || firstMemoryId;
}

function runtimeEventSkillId(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): string {
  return runtimeEventString(event, payload, 'skill_id')
    || runtimeEventNestedString(payload, 'result', 'skill_id')
    || runtimeEventNestedString(payload, 'result', 'name');
}

function runtimeEventNestedString(
  payload: RuntimeTimelineEventRecord,
  key: string,
  nestedKey: string,
): string {
  const record = runtimeEventNestedRecord(payload, key);
  return record ? defaultString(record[nestedKey]) : '';
}

function runtimeEventNestedRecord(
  payload: RuntimeTimelineEventRecord,
  key: string,
): RuntimeTimelineEventRecord | null {
  const value = payload[key];
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as RuntimeTimelineEventRecord;
}
