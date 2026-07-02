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
          const runtimeContext = runtimeEventRuntimeContext(event, payloadRecord);
          const recoveryTarget = runtimeEventRecoveryTarget(event, payloadRecord);
          const observedContext = runtimeEventObservedContext(event, payloadRecord);
          const contentSnapshots = eventIsSecret ? [] : runtimeEventContentSnapshots(payloadRecord);
          const capabilityRecovery = eventIsSecret ? [] : runtimeEventCapabilityRecovery(payloadRecord);
          const eventMetadata = runtimeEventMetadata(
            event,
            payloadRecord,
            traceContext,
            plannerContext,
            runtimeContext,
            recoveryTarget,
            observedContext,
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
              data-run-event-runtime-capability-id={runtimeContext.capabilityId}
              data-run-event-runtime-doctrine={runtimeContext.runtimeDoctrine}
              data-run-event-runtime-role={runtimeContext.runtimeRole}
              data-run-event-runtime-stage={runtimeContext.runtimeStage}
              data-run-event-runtime-step-id={runtimeContext.stepId}
              data-run-event-planner-entrypoint={plannerContext.plannerEntrypoint}
              data-run-event-replan-request-id={runtimeContext.replanRequestId}
              data-run-event-replan-signal-ids={runtimeContext.replanSignalIds.join(',')}
              data-run-event-replan-trigger={runtimeContext.replanTrigger || runtimeContext.replanTriggers[0] || ''}
              data-run-event-observed-action-evidence={observedContext.observationEvidence}
              data-run-event-observed-action-target={observedContext.actionTarget}
              data-run-event-observed-center={observedContext.observedCenter}
              data-run-event-recovery-target-app={recoveryTarget.targetAppName}
              data-run-event-recovery-target-query={recoveryTarget.targetAppQuery}
              data-run-event-recovery-target-text={recoveryTarget.targetSearchText}
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
                {contentSnapshots.length === 1 ? (
                  <RuntimeContentSnapshot
                    snapshot={contentSnapshots[0]}
                    testId={`${eventTestId}-content-snapshot`}
                  />
                ) : null}
                {contentSnapshots.length > 1 ? (
                  <div className="run-content-snapshot-list" data-testid={`${eventTestId}-content-snapshots`}>
                    {contentSnapshots.map((snapshot, snapshotIndex) => (
                      <RuntimeContentSnapshot
                        snapshot={snapshot}
                        testId={`${eventTestId}-content-snapshot-${snapshotIndex + 1}`}
                        key={`${defaultString(snapshot.source_tool) || 'snapshot'}-${snapshotIndex}`}
                      />
                    ))}
                  </div>
                ) : null}
                {capabilityRecovery.length ? (
                  <RuntimeCapabilityRecoveryList
                    items={capabilityRecovery}
                    testId={`${eventTestId}-capability-recovery`}
                  />
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

function RuntimeCapabilityRecoveryList({
  items,
  testId,
}: {
  items: RuntimeTimelineEventRecord[];
  testId: string;
}) {
  return (
    <section className="run-capability-recovery" data-testid={testId}>
      <div className="run-capability-recovery-head">
        <strong>能力恢复</strong>
        <span>{items.length} 个 capability</span>
      </div>
      <div className="run-capability-recovery-items">
        {items.map((item, index) => {
          const capabilityId = defaultString(item.capability_id);
          const title = defaultString(item.title) || capabilityId || 'capability';
          const action = defaultString(item.suggested_action);
          const missingTools = runtimeEventStringList(item.missing_tools);
          const recommendedTools = runtimeEventStringList(item.recommended_enable_tools);
          const availableTools = runtimeEventStringList(item.available_tools);
          const permissions = runtimeEventStringList(item.missing_permissions);
          const blockers = runtimeEventStringList(item.blocking_conditions);
          const sourceSteps = runtimeEventStringList(item.source_step_ids);
          return (
            <article
              className="run-capability-recovery-item"
              data-capability-id={capabilityId}
              key={`${capabilityId || title}-${index}`}
            >
              <div className="run-capability-recovery-title">
                <strong>{title}</strong>
                {action ? <code>{action}</code> : null}
              </div>
              {capabilityId ? <p>{capabilityId}</p> : null}
              <RuntimeCapabilityRecoveryValue label="Enable" values={recommendedTools} />
              <RuntimeCapabilityRecoveryValue label="Missing" values={missingTools} />
              <RuntimeCapabilityRecoveryValue label="Available" values={availableTools} />
              <RuntimeCapabilityRecoveryValue label="Permissions" values={permissions} />
              <RuntimeCapabilityRecoveryValue label="Blockers" values={blockers} />
              <RuntimeCapabilityRecoveryValue label="Steps" values={sourceSteps} />
            </article>
          );
        })}
      </div>
    </section>
  );
}

function RuntimeCapabilityRecoveryValue({
  label,
  values,
}: {
  label: string;
  values: string[];
}) {
  if (!values.length) return null;
  const visible = values.slice(0, 6);
  const remaining = values.length - visible.length;
  return (
    <div className="run-capability-recovery-row">
      <span>{label}</span>
      <code>{visible.join(', ')}{remaining > 0 ? ` +${remaining}` : ''}</code>
    </div>
  );
}

function RuntimeContentSnapshot({
  snapshot,
  testId,
}: {
  snapshot: RuntimeTimelineEventRecord;
  testId: string;
}) {
  const text = defaultString(snapshot.text);
  const summary = defaultString(snapshot.summary) || defaultString(snapshot.error);
  const meta = runtimeContentSnapshotMeta(snapshot);
  return (
    <section className="run-content-snapshot" data-testid={testId}>
      <div className="run-content-snapshot-head">
        <strong>上下文快照</strong>
        {meta ? <span>{meta}</span> : null}
      </div>
      {text ? <pre>{text}</pre> : summary ? <p>{summary}</p> : null}
    </section>
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
  runtimeContext: RuntimeTimelineRuntimeContext,
  recoveryTarget: RuntimeTimelineRecoveryTarget,
  observedContext: RuntimeTimelineObservedContext,
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
        || runtimeEventNestedString(payload, 'approval', 'approval_id')
        || runtimeContext.approvalRequired,
    },
    { label: 'step', value: runtimeContext.stepId },
    { label: 'capability', value: runtimeContext.capabilityId },
    { label: 'stage', value: runtimeContext.runtimeStage },
    { label: 'role', value: runtimeContext.runtimeRole },
    { label: 'doctrine', value: runtimeContext.runtimeDoctrine },
    { label: 'observe', value: runtimeContext.requiresObservation },
    { label: 'verify', value: runtimeContext.requiresVerification },
    { label: 'replan', value: runtimeContext.replanTrigger || runtimeContext.replanTriggers.join(', ') },
    { label: 'replan id', value: runtimeContext.replanRequestId },
    { label: 'signals', value: runtimeContext.replanSignalIds.join(', ') },
    { label: 'action', value: observedContext.actionTarget },
    { label: 'observed', value: observedContext.observationEvidence },
    { label: 'center', value: observedContext.observedCenter },
    { label: 'target app', value: recoveryTarget.targetAppName },
    { label: 'target query', value: recoveryTarget.targetAppQuery },
    { label: 'target text', value: recoveryTarget.targetSearchText },
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

type RuntimeTimelineRuntimeContext = {
  approvalRequired: string;
  capabilityId: string;
  replanRequestId: string;
  replanSignalIds: string[];
  replanTrigger: string;
  replanTriggers: string[];
  requiresObservation: string;
  requiresVerification: string;
  runtimeDoctrine: string;
  runtimeRole: string;
  runtimeStage: string;
  stepId: string;
};

type RuntimeTimelineRecoveryTarget = {
  targetAppName: string;
  targetAppQuery: string;
  targetSearchText: string;
};

type RuntimeTimelineObservedContext = {
  actionTarget: string;
  observationEvidence: string;
  observedCenter: string;
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

function runtimeEventRuntimeContext(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelineRuntimeContext {
  const replanTrigger = runtimeEventContextString(
    event,
    payload,
    'replan_trigger',
    'trigger',
    'latest_replan_trigger',
  );
  const replanTriggers = runtimeEventContextStringList(event, payload, 'replan_triggers');
  if (replanTrigger && !replanTriggers.includes(replanTrigger)) {
    replanTriggers.unshift(replanTrigger);
  }
  return {
    approvalRequired: runtimeEventContextBoolLabel(event, payload, 'approval_required'),
    capabilityId: runtimeEventContextString(
      event,
      payload,
      'capability_id',
      'target_capability_id',
    ),
    replanRequestId: runtimeEventContextString(
      event,
      payload,
      'replan_request_id',
      'request_id',
    ),
    replanSignalIds: runtimeEventContextStringList(event, payload, 'replan_signal_ids'),
    replanTrigger,
    replanTriggers,
    requiresObservation: runtimeEventContextBoolLabel(event, payload, 'requires_observation'),
    requiresVerification: runtimeEventContextBoolLabel(
      event,
      payload,
      'requires_post_action_verification',
    ),
    runtimeDoctrine: runtimeEventContextString(event, payload, 'runtime_doctrine'),
    runtimeRole: runtimeEventContextString(event, payload, 'runtime_role'),
    runtimeStage: runtimeEventContextString(event, payload, 'runtime_stage'),
    stepId: runtimeEventContextString(
      event,
      payload,
      'step_id',
      'planner_step_id',
      'source_step_id',
      'after_step_id',
      'latest_replan_step_id',
    ),
  };
}

function runtimeEventRecoveryTarget(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelineRecoveryTarget {
  return {
    targetAppName: runtimeEventContextString(
      event,
      payload,
      'target_app_name',
      'expected_app_name',
      'resolved_app_name',
      'discovered_app_name',
      'requested_app_name',
    ),
    targetAppQuery: runtimeEventContextString(
      event,
      payload,
      'target_app_query',
      'app_query',
      'query',
    ),
    targetSearchText: runtimeEventContextString(
      event,
      payload,
      'target_search_text',
      'search_text',
      'text',
      'value',
    ),
  };
}

function runtimeEventObservedContext(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelineObservedContext {
  const actionTarget = runtimeEventContextNestedRecord(event, payload, 'action_target');
  const observationEvidence = runtimeEventContextNestedRecord(event, payload, 'observation_evidence');
  const observedCenter = runtimeEventObservedCenterSummary(observationEvidence);
  return {
    actionTarget: runtimeEventObservedActionTargetSummary(actionTarget),
    observationEvidence: runtimeEventObservedEvidenceSummary(observationEvidence),
    observedCenter,
  };
}

function runtimeEventObservedActionTargetSummary(value: RuntimeTimelineEventRecord): string {
  if (!Object.keys(value).length) return '';
  const action = defaultString(value.action);
  const target = (
    defaultString(value.target)
    || defaultString(value.label)
    || defaultString(value.name)
    || defaultString(value.title)
    || defaultString(value.text)
    || defaultString(value.role)
  );
  const roleFilter = defaultString(value.role_filter);
  const app = defaultString(value.app_name) || defaultString(value.app) || defaultString(value.bundle_id);
  return [action, target, roleFilter ? `role ${roleFilter}` : '', app].filter(Boolean).join(' · ');
}

function runtimeEventObservedEvidenceSummary(value: RuntimeTimelineEventRecord): string {
  if (!Object.keys(value).length) return '';
  const sourceTool = defaultString(value.source_tool);
  const source = defaultString(value.source);
  const strategy = defaultString(value.strategy);
  const reason = defaultString(value.reason);
  const center = runtimeEventObservedCenterSummary(value);
  return [sourceTool || source, strategy, reason, center ? `center ${center}` : ''].filter(Boolean).join(' · ');
}

function runtimeEventObservedCenterSummary(value: RuntimeTimelineEventRecord): string {
  const center = runtimeEventNestedRecord(value, 'observed_center') || {};
  const legacyCenter = runtimeEventNestedRecord(value, 'center') || {};
  const point = runtimeEventNestedRecord(value, 'point') || {};
  const x = runtimeEventCoordinateValue(center.x ?? legacyCenter.x ?? point.x);
  const y = runtimeEventCoordinateValue(center.y ?? legacyCenter.y ?? point.y);
  return x && y ? `${x},${y}` : '';
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

function runtimeEventContentSnapshots(
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelineEventRecord[] {
  const snapshots = payload.content_snapshots;
  if (Array.isArray(snapshots)) {
    return snapshots
      .filter((snapshot): snapshot is RuntimeTimelineEventRecord => (
        Boolean(snapshot)
        && typeof snapshot === 'object'
        && !Array.isArray(snapshot)
        && Object.keys(snapshot).length > 0
      ));
  }
  const snapshot = runtimeEventNestedRecord(payload, 'content_snapshot');
  return snapshot && Object.keys(snapshot).length ? [snapshot] : [];
}

function runtimeEventCapabilityRecovery(
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelineEventRecord[] {
  const recoveries = payload.capability_recovery;
  if (!Array.isArray(recoveries)) return [];
  return recoveries.filter((item): item is RuntimeTimelineEventRecord => (
    Boolean(item)
    && typeof item === 'object'
    && !Array.isArray(item)
    && Object.keys(item).length > 0
  ));
}

function runtimeContentSnapshotMeta(snapshot: RuntimeTimelineEventRecord): string {
  const textItemCount = runtimeEventNumberString(snapshot, 'text_item_count');
  const elementCount = runtimeEventNumberString(snapshot, 'element_count');
  const rows = runtimeEventNumberString(snapshot, 'rows');
  const columns = runtimeEventArrayLength(snapshot, 'columns');
  const artifactCount = runtimeEventNumberString(snapshot, 'artifact_count');
  const parts = [
    defaultString(snapshot.source_tool),
    defaultString(snapshot.app_name),
    defaultString(snapshot.title),
    defaultString(snapshot.url),
    defaultString(snapshot.source_kind),
    rows ? `${rows} 行` : '',
    columns ? `${columns} 列` : '',
    textItemCount ? `${textItemCount} 条文本` : '',
    elementCount ? `${elementCount} 个元素` : '',
    artifactCount ? `${artifactCount} 个产物` : '',
    defaultString(snapshot.path),
  ].filter(Boolean);
  return parts.join(' · ');
}

function runtimeEventNumberString(
  record: RuntimeTimelineEventRecord,
  key: string,
): string {
  const value = record[key];
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return defaultString(value);
}

function runtimeEventArrayLength(
  record: RuntimeTimelineEventRecord,
  key: string,
): number {
  const value = record[key];
  return Array.isArray(value) ? value.length : 0;
}

function runtimeEventStringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.map(defaultString).filter(Boolean);
  }
  const single = defaultString(value);
  return single ? [single] : [];
}

function runtimeEventString(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  key: string,
): string {
  return defaultString(event[key]) || defaultString(payload[key]);
}

function runtimeEventContextString(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  ...keys: string[]
): string {
  const records = runtimeEventContextRecords(event, payload);
  for (const key of keys) {
    for (const record of records) {
      const value = defaultString(record[key]);
      if (value) return value;
    }
  }
  return '';
}

function runtimeEventContextStringList(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  ...keys: string[]
): string[] {
  const values: string[] = [];
  for (const record of runtimeEventContextRecords(event, payload)) {
    for (const key of keys) {
      for (const value of runtimeEventStringList(record[key])) {
        if (!values.includes(value)) values.push(value);
      }
    }
  }
  return values;
}

function runtimeEventContextBoolLabel(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  key: string,
): string {
  for (const record of runtimeEventContextRecords(event, payload)) {
    if (record[key] === true) return 'required';
    if (record[key] === false) continue;
    const value = defaultString(record[key]).toLowerCase();
    if (value === 'true' || value === 'required') return 'required';
  }
  return '';
}

function runtimeEventContextRecords(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
): RuntimeTimelineEventRecord[] {
  const records: RuntimeTimelineEventRecord[] = [event, payload];
  const seen = new Set<RuntimeTimelineEventRecord>(records);
  const addRecord = (record: RuntimeTimelineEventRecord | null) => {
    if (!record || seen.has(record)) return;
    seen.add(record);
    records.push(record);
  };
  for (const key of ['pending_approval', 'approval', 'tool_request', 'planned_request', 'request', 'result', 'metadata']) {
    addRecord(runtimeEventNestedRecord(payload, key));
  }
  for (const record of records.slice(2)) {
    for (const key of ['tool_request', 'planned_request', 'request', 'result', 'metadata']) {
      const nested = record[key];
      if (nested && typeof nested === 'object' && !Array.isArray(nested)) {
        addRecord(nested as RuntimeTimelineEventRecord);
      }
    }
  }
  return records;
}

function runtimeEventContextNestedRecord(
  event: RuntimeTimelineEventRecord,
  payload: RuntimeTimelineEventRecord,
  key: string,
): RuntimeTimelineEventRecord {
  for (const record of runtimeEventContextRecords(event, payload)) {
    const nested = runtimeEventNestedRecord(record, key);
    if (nested && Object.keys(nested).length) return nested;
  }
  return {};
}

function runtimeEventCoordinateValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) return String(Math.round(value));
  return defaultString(value);
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
