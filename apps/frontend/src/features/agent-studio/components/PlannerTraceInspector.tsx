import { publicRunEventIsSecret } from '../../runtime-shared/runEvents';
import type {
  CapabilitySnapshot,
  PublicRunEvent,
  RuntimePlanSnapshot,
  TaskIntentSnapshot,
  ToolPlanSnapshot,
  ToolPlanStepSnapshot,
} from '../../yachiyo-studio/types';

type PlannerTrace = {
  candidateIntents: TaskIntentSnapshot[];
  decisionId: string;
  eventCount: number;
  intent: TaskIntentSnapshot | null;
  plan: RuntimePlanSnapshot | null;
  planId: string;
  routeToStudio?: boolean;
  source: string;
  steps: ToolPlanStepSnapshot[];
  toolPlan: ToolPlanSnapshot | null;
};

type PlannerTraceInspectorProps = {
  events?: PublicRunEvent[];
  sourceLabel?: string;
  testId?: string;
};

export function PlannerTraceInspector({
  events = [],
  sourceLabel = 'Intent / Capability / Plan 的 Runtime Planner replay 事实',
  testId = 'agent-run-detail-planner-trace',
}: PlannerTraceInspectorProps) {
  const trace = plannerTraceFromEvents(events);
  if (!trace) return null;

  const intent = trace.intent || trace.plan?.intent || null;
  const toolPlan = trace.toolPlan || trace.plan?.tool_plan || null;
  const capabilities = trace.plan?.capabilities || [];
  const capabilityById = new Map(capabilities.map((capability) => [capability.capability_id, capability]));
  const requiredCapabilities = uniqueStrings([
    ...(intent?.required_capabilities || []),
    ...(toolPlan?.required_capabilities || []),
  ]);
  const preferredCapabilities = uniqueStrings(intent?.preferred_capabilities || []);
  const visibleCapabilityIds = uniqueStrings([
    ...requiredCapabilities,
    ...preferredCapabilities,
    ...capabilities.map((capability) => capability.capability_id),
  ]);
  const missingCapabilities = uniqueStrings(toolPlan?.missing_capabilities || []);
  const approvalsRequired = uniqueStrings(toolPlan?.approvals_required || []);
  const artifactsExpected = uniqueStrings(toolPlan?.artifacts_expected || []);
  const openQuestions = uniqueStrings(toolPlan?.open_questions || []);
  const confidence = confidenceLabel(intent?.confidence);

  return (
    <details
      className="run-detail-block run-detail-fold run-planner-trace"
      data-decision-id={trace.decisionId}
      data-intent-kind={intent?.kind || ''}
      data-plan-id={trace.planId}
      data-route-to-studio={trace.routeToStudio === undefined ? '' : String(trace.routeToStudio)}
      data-testid={testId}
      open
    >
      <summary className="run-detail-section-head">
        <div>
          <h4>Runtime Planner</h4>
          <span>{sourceLabel}</span>
        </div>
      </summary>
      <div className="run-detail-fold-body studio-planner-result">
        <div className="studio-tool-detail-grid" data-testid="agent-run-detail-planner-intent">
          <span>
            <small>Intent</small>
            <strong>{intent?.kind || 'unknown'}</strong>
          </span>
          <span>
            <small>Confidence</small>
            <strong>{confidence || 'Unknown'}</strong>
          </span>
          <span>
            <small>Route</small>
            <strong>{routeLabel(trace.routeToStudio)}</strong>
          </span>
          <span>
            <small>Decision</small>
            <strong>{trace.decisionId || 'None'}</strong>
          </span>
          <span>
            <small>Plan</small>
            <strong>{trace.planId || toolPlan?.plan_id || 'None'}</strong>
          </span>
          <span>
            <small>Events</small>
            <strong>{trace.eventCount}</strong>
          </span>
        </div>

        {intent?.title || intent?.description ? (
          <div className="studio-planner-step" data-testid="agent-run-detail-planner-intent-summary">
            <div>
              <strong>{intent.title || intent.kind}</strong>
              {intent.description ? <span>{intent.description}</span> : null}
            </div>
            <small>{intent.risk_level || 'risk unknown'}</small>
          </div>
        ) : null}

        {visibleCapabilityIds.length || missingCapabilities.length ? (
          <section data-testid="agent-run-detail-planner-capabilities">
            <div className="studio-tool-inspector-heading">
              <h3>Capabilities</h3>
              <span>{missingCapabilities.length ? `${missingCapabilities.length} missing` : 'available plan'}</span>
            </div>
            <div className="studio-tool-pill-row">
              {visibleCapabilityIds.map((capabilityId) => (
                <PlannerCapabilityPill
                  capabilityById={capabilityById}
                  capabilityId={capabilityId}
                  key={capabilityId}
                  missing={missingCapabilities.includes(capabilityId)}
                  state={missingCapabilities.includes(capabilityId) ? 'missing' : capabilityState(capabilityId, requiredCapabilities, preferredCapabilities)}
                />
              ))}
              {missingCapabilities
                .filter((capabilityId) => !visibleCapabilityIds.includes(capabilityId))
                .map((capabilityId) => (
                  <PlannerCapabilityPill
                    capabilityById={capabilityById}
                    capabilityId={capabilityId}
                    key={capabilityId}
                    missing
                    state="missing"
                  />
                ))}
            </div>
          </section>
        ) : null}

        <div className="studio-planner-step-list" data-testid="agent-run-detail-planner-steps">
          {trace.steps.map((step, index) => (
            <PlannerTraceStepRow key={step.step_id || `${step.title}-${index}`} step={step} index={index} />
          ))}
          {!trace.steps.length ? <span className="studio-tool-empty">No planned steps</span> : null}
        </div>

        {approvalsRequired.length || artifactsExpected.length || openQuestions.length ? (
          <section data-testid="agent-run-detail-planner-outputs">
            <div className="studio-tool-inspector-heading">
              <h3>Approvals / Artifacts</h3>
              <span>{trace.source || 'runtime planner'}</span>
            </div>
            <div className="studio-tool-pill-row">
              {approvalsRequired.map((approval) => (
                <span className="studio-tool-permission missing" data-planner-output-kind="approval" key={`approval:${approval}`}>
                  approval · {approval}
                </span>
              ))}
              {artifactsExpected.map((artifact) => (
                <span className="studio-tool-permission" data-planner-output-kind="artifact" key={`artifact:${artifact}`}>
                  artifact · {artifact}
                </span>
              ))}
              {openQuestions.map((question) => (
                <span className="studio-tool-permission missing" data-planner-output-kind="question" key={`question:${question}`}>
                  question · {question}
                </span>
              ))}
            </div>
          </section>
        ) : null}

        {trace.candidateIntents.length > 1 ? (
          <section data-testid="agent-run-detail-planner-candidates">
            <div className="studio-tool-inspector-heading">
              <h3>Candidate Intents</h3>
              <span>{trace.candidateIntents.length}</span>
            </div>
            <div className="studio-tool-pill-row">
              {trace.candidateIntents.map((candidate) => (
                <span className="studio-tool-permission" data-intent-kind={candidate.kind} key={candidate.intent_id || candidate.kind}>
                  {candidate.kind}{confidenceLabel(candidate.confidence) ? ` · ${confidenceLabel(candidate.confidence)}` : ''}
                </span>
              ))}
            </div>
          </section>
        ) : null}
      </div>
    </details>
  );
}

function PlannerCapabilityPill({
  capabilityById,
  capabilityId,
  missing,
  state,
}: {
  capabilityById: Map<string, CapabilitySnapshot>;
  capabilityId: string;
  missing: boolean;
  state: string;
}) {
  const capability = capabilityById.get(capabilityId);
  const discoveryActions = uniqueStrings(capability?.discovery_actions || []);
  const executionActions = uniqueStrings(capability?.execution_actions || []);
  const actionSummary = capabilityActionSummary(discoveryActions, executionActions);
  return (
    <span
      className={missing ? 'studio-tool-permission missing' : 'studio-tool-permission'}
      data-capability-discovery-actions={discoveryActions.join(',')}
      data-capability-execution-actions={executionActions.join(',')}
      data-capability-id={capabilityId}
      data-capability-state={state}
      title={actionSummary || undefined}
    >
      {capabilityLabel(capabilityId, capabilityById)}
      {actionSummary ? ` (${actionSummary})` : ''}
    </span>
  );
}

function PlannerTraceStepRow({
  index,
  step,
}: {
  index: number;
  step: ToolPlanStepSnapshot;
}) {
  return (
    <div
      className="studio-planner-step"
      data-approval-required={String(Boolean(step.approval_required))}
      data-capability-id={step.capability_id}
      data-planner-step-id={step.step_id}
      data-risk-level={step.risk_level || ''}
      data-step-status={step.status || 'planned'}
      data-testid="agent-run-detail-planner-step"
      data-tool-name={step.tool_name || ''}
    >
      <div>
        <strong>{index + 1}. {step.title}</strong>
        {step.capability_id ? <span>capability: {step.capability_id}</span> : null}
        {step.tool_name ? <span>tool: {step.tool_name}</span> : null}
        {step.reason ? <span>{step.reason}</span> : null}
      </div>
      <small>{step.status || 'planned'}{step.approval_required ? ' / approval' : ''}</small>
    </div>
  );
}

function plannerTraceFromEvents(events: PublicRunEvent[]): PlannerTrace | null {
  let intent: TaskIntentSnapshot | null = null;
  let plan: RuntimePlanSnapshot | null = null;
  let toolPlan: ToolPlanSnapshot | null = null;
  let candidateIntents: TaskIntentSnapshot[] = [];
  let source = '';
  let decisionId = '';
  let planId = '';
  let routeToStudio: boolean | undefined;
  let eventCount = 0;
  const stepById = new Map<string, ToolPlanStepSnapshot>();

  for (const event of events) {
    if (publicRunEventIsSecret(event)) continue;
    const eventType = String(event.event_type || '').trim();
    if (!eventType.startsWith('agent.plan.') && eventType !== 'agent.intent.selected') continue;
    const payload = objectRecord(event.payload);
    eventCount += 1;
    source = stringValue(payload.source) || source;
    decisionId = stringValue(payload.decision_id) || decisionId;
    planId = stringValue(payload.plan_id) || planId;

    if (eventType === 'agent.intent.selected') {
      intent = taskIntentSnapshot(payload.intent) || intent;
      candidateIntents = arrayRecords(payload.candidate_intents)
        .map(taskIntentSnapshot)
        .filter((candidate): candidate is TaskIntentSnapshot => Boolean(candidate));
      routeToStudio = booleanValue(payload.route_to_studio, routeToStudio);
      continue;
    }

    if (eventType === 'agent.plan.created') {
      plan = runtimePlanSnapshot(payload.plan) || plan;
      if (plan) {
        intent = intent || plan.intent;
        toolPlan = plan.tool_plan || toolPlan;
        planId = plan.plan_id || planId;
        routeToStudio = plan.route_to_studio ?? routeToStudio;
        for (const step of plan.tool_plan?.steps || []) {
          addPlannerStep(stepById, step);
        }
      }
      continue;
    }

    if (eventType === 'agent.plan.step') {
      const step = toolPlanStepSnapshot(payload.step);
      if (step) addPlannerStep(stepById, step);
    }
  }

  if (!intent && !plan && !stepById.size) return null;
  return {
    candidateIntents,
    decisionId,
    eventCount,
    intent,
    plan,
    planId,
    routeToStudio,
    source,
    steps: Array.from(stepById.values()),
    toolPlan,
  };
}

function addPlannerStep(stepById: Map<string, ToolPlanStepSnapshot>, step: ToolPlanStepSnapshot) {
  const key = step.step_id || `${step.capability_id}:${step.tool_name || step.title}`;
  stepById.set(key, step);
}

function taskIntentSnapshot(value: unknown): TaskIntentSnapshot | null {
  const record = objectRecord(value);
  if (!stringValue(record.intent_id) && !stringValue(record.kind) && !stringValue(record.title)) return null;
  return record as TaskIntentSnapshot;
}

function runtimePlanSnapshot(value: unknown): RuntimePlanSnapshot | null {
  const record = objectRecord(value);
  if (!stringValue(record.plan_id) && !record.intent && !record.tool_plan) return null;
  return record as RuntimePlanSnapshot;
}

function toolPlanStepSnapshot(value: unknown): ToolPlanStepSnapshot | null {
  const record = objectRecord(value);
  if (!stringValue(record.step_id) && !stringValue(record.title) && !stringValue(record.capability_id)) return null;
  return record as ToolPlanStepSnapshot;
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function arrayRecords(value: unknown): Array<Record<string, unknown>> {
  return Array.isArray(value) ? value.map(objectRecord).filter((record) => Object.keys(record).length > 0) : [];
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function booleanValue(value: unknown, fallback?: boolean): boolean | undefined {
  if (typeof value === 'boolean') return value;
  return fallback;
}

function confidenceLabel(value: unknown): string {
  return typeof value === 'number' && Number.isFinite(value) ? `${Math.round(value * 100)}%` : '';
}

function routeLabel(routeToStudio?: boolean): string {
  if (routeToStudio === undefined) return 'Unknown';
  return routeToStudio ? 'Studio' : 'Direct';
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(
    new Set(values.map((value) => stringValue(value)).filter(Boolean)),
  );
}

function capabilityState(
  capabilityId: string,
  requiredCapabilities: string[],
  preferredCapabilities: string[],
): string {
  if (requiredCapabilities.includes(capabilityId)) return 'required';
  if (preferredCapabilities.includes(capabilityId)) return 'preferred';
  return 'planned';
}

function capabilityLabel(
  capabilityId: string,
  capabilityById: Map<string, CapabilitySnapshot>,
): string {
  const title = capabilityById.get(capabilityId)?.title || '';
  return title && title !== capabilityId ? `${title} · ${capabilityId}` : capabilityId;
}

function capabilityActionSummary(
  discoveryActions: string[],
  executionActions: string[],
): string {
  const parts: string[] = [];
  if (discoveryActions.length) parts.push(`discover: ${discoveryActions.slice(0, 3).join(', ')}`);
  if (executionActions.length) parts.push(`execute: ${executionActions.slice(0, 3).join(', ')}`);
  return parts.join('; ');
}
