import { publicRunEventIsSecret } from '../../runtime-shared/runEvents';
import type {
  CapabilitySnapshot,
  PlannerTraceSummarySnapshot,
  PublicRunEvent,
  RuntimePlanSnapshot,
  TaskCoreSnapshot,
  TaskIntentSnapshot,
  TaskReplanRequestSnapshot,
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
  replanRequests: TaskReplanRequestSnapshot[];
  routeToStudio?: boolean;
  selection: PlannerSelection | null;
  source: string;
  steps: ToolPlanStepSnapshot[];
  summaryFallback?: boolean;
  toolPlan: ToolPlanSnapshot | null;
};

type PlannerSelection = {
  approvalsRequired: string[];
  artifactsExpected: string[];
  followupTarget: PlannerFollowupTarget | null;
  legacyTools: string[];
  legacyRequestCount: number;
  missingCapabilities: string[];
  missingCapabilityCount: number;
  openQuestions: string[];
  orchestration: PlannerOrchestration | null;
  planCapabilities: string[];
  planCapabilityCount: number;
  planTools: string[];
  planStepCount: number;
  plannerTools: string[];
  plannerRequestCount: number;
  reason: string;
  requiredCapabilities: string[];
  dailyDesktopIntent: boolean;
  entrypointSource: string;
  launcherMode: string;
  launcherSurface: string;
  legacyFallback: boolean;
  plannerEntrypoint: string;
  runnableKind: string;
  selectedRole: string;
  selectedSource: string;
  selectedTools: string[];
  selectedRequestCount: number;
};

type PlannerOrchestration = {
  entries: Array<{ key: string; value: string }>;
  handoff: boolean;
  kind: string;
  routeToStudio: boolean;
  surface: string;
};

type PlannerFollowupTarget = {
  kind: string;
  entries: Array<{ key: string; value: string }>;
  communicationCompose: Array<{ key: string; value: string }>;
  recommendedTools: string[];
  verifyTools: string[];
};

type PlannerTraceInspectorProps = {
  events?: PublicRunEvent[];
  plannerSummary?: PlannerTraceSummarySnapshot | null;
  sourceLabel?: string;
  testId?: string;
};

export function PlannerTraceInspector({
  events = [],
  plannerSummary = null,
  sourceLabel = 'Intent / Capability / Plan 的 Runtime Planner replay 事实',
  testId = 'agent-run-detail-planner-trace',
}: PlannerTraceInspectorProps) {
  const trace = plannerTraceFromEvents(events) || plannerTraceFromSummary(plannerSummary);
  if (!trace) return null;

  const intent = trace.intent || trace.plan?.intent || null;
  const toolPlan = trace.toolPlan || trace.plan?.tool_plan || null;
  const capabilities = trace.plan?.capabilities || [];
  const capabilityById = new Map(capabilities.map((capability) => [capability.capability_id, capability]));
  const selectionPlanCapabilities = trace.selection?.planCapabilities || [];
  const selectionRequiredCapabilities = trace.selection?.requiredCapabilities || [];
  const toolPlanRequiredCapabilities = uniqueStrings(toolPlan?.required_capabilities || []);
  const intentRequiredCapabilities = uniqueStrings(intent?.required_capabilities || []);
  const requiredCapabilities = uniqueStrings([
    ...(toolPlanRequiredCapabilities.length ? toolPlanRequiredCapabilities : intentRequiredCapabilities),
    ...selectionRequiredCapabilities,
  ]);
  const preferredCapabilities = uniqueStrings(intent?.preferred_capabilities || []);
  const visibleCapabilityIds = uniqueStrings([
    ...requiredCapabilities,
    ...preferredCapabilities,
    ...selectionPlanCapabilities,
    ...capabilities.map((capability) => capability.capability_id),
  ]);
  const missingCapabilities = uniqueStrings([
    ...(toolPlan?.missing_capabilities || []),
    ...(trace.selection?.missingCapabilities || []),
  ]);
  const intentInputEntries = plannerIntentInputEntries(intent?.inputs);
  const expectedOutputs = uniqueStrings(intent?.expected_outputs || []);
  const missingInputs = uniqueStrings(intent?.missing_inputs || []);
  const approvalsRequired = uniqueStrings([
    ...(toolPlan?.approvals_required || []),
    ...(trace.selection?.approvalsRequired || []),
  ]);
  const artifactsExpected = uniqueStrings([
    ...(toolPlan?.artifacts_expected || []),
    ...(trace.selection?.artifactsExpected || []),
  ]);
  const openQuestions = uniqueStrings([
    ...(toolPlan?.open_questions || []),
    ...(trace.selection?.openQuestions || []),
  ]);
  const confidence = confidenceLabel(intent?.confidence);
  const taskCore = trace.plan?.task_core || null;
  const replanRequests = trace.replanRequests || [];

  return (
    <details
      className="run-detail-block run-detail-fold run-planner-trace"
      data-decision-id={trace.decisionId}
      data-intent-kind={intent?.kind || ''}
      data-plan-id={trace.planId}
      data-route-to-studio={trace.routeToStudio === undefined ? '' : String(trace.routeToStudio)}
      data-summary-fallback={String(trace.summaryFallback)}
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

        {intentInputEntries.length || expectedOutputs.length || missingInputs.length ? (
          <section data-testid="agent-run-detail-planner-inputs">
            <div className="studio-tool-inspector-heading">
              <h3>Intent Inputs</h3>
              <span>{intentInputEntries.length ? `${intentInputEntries.length} recorded` : 'none recorded'}</span>
            </div>
            <div className="studio-tool-pill-row">
              {intentInputEntries.map((entry) => (
                <span
                  className="studio-tool-permission"
                  data-intent-input-key={entry.key}
                  data-intent-input-value={entry.value}
                  key={`input:${entry.key}`}
                  title={entry.value}
                >
                  input · {entry.key}: {entry.value}
                </span>
              ))}
              {expectedOutputs.map((output) => (
                <span className="studio-tool-permission" data-intent-output={output} key={`output:${output}`}>
                  output · {output}
                </span>
              ))}
              {missingInputs.map((input) => (
                <span className="studio-tool-permission missing" data-missing-intent-input={input} key={`missing-input:${input}`}>
                  missing input · {input}
                </span>
              ))}
            </div>
          </section>
        ) : null}

        {taskCore ? <TaskCoreInspector taskCore={taskCore} /> : null}

        {replanRequests.length ? <ReplanRequestInspector requests={replanRequests} /> : null}

        {trace.selection ? (
          <section
            data-entrypoint-source={trace.selection.entrypointSource}
            data-legacy-request-count={trace.selection.legacyRequestCount}
            data-legacy-fallback={String(trace.selection.legacyFallback)}
            data-launcher-mode={trace.selection.launcherMode}
            data-launcher-surface={trace.selection.launcherSurface}
            data-missing-capability-count={trace.selection.missingCapabilityCount}
            data-plan-capability-count={trace.selection.planCapabilityCount}
            data-plan-step-count={trace.selection.planStepCount}
            data-planner-entrypoint={trace.selection.plannerEntrypoint}
            data-planner-request-count={trace.selection.plannerRequestCount}
            data-runnable-kind={trace.selection.runnableKind}
            data-selection-role={trace.selection.selectedRole}
            data-selected-request-count={trace.selection.selectedRequestCount}
            data-testid="agent-run-detail-planner-selection"
          >
            <div className="studio-tool-inspector-heading">
              <h3>Direct Selection</h3>
              <span>{trace.selection.selectedRole || trace.selection.selectedSource || 'unknown'}</span>
            </div>
            <div className="studio-tool-pill-row">
              <span className="studio-tool-permission" data-selection-role={trace.selection.selectedRole}>
                role · {trace.selection.selectedRole || 'not recorded'}
              </span>
              {trace.selection.plannerEntrypoint ? (
                <span className="studio-tool-permission" data-planner-entrypoint={trace.selection.plannerEntrypoint}>
                  entrypoint · {trace.selection.plannerEntrypoint}
                </span>
              ) : null}
              {trace.selection.entrypointSource ? (
                <span className="studio-tool-permission" data-entrypoint-source={trace.selection.entrypointSource}>
                  source · {trace.selection.entrypointSource}
                </span>
              ) : null}
              {trace.selection.launcherMode ? (
                <span className="studio-tool-permission" data-launcher-mode={trace.selection.launcherMode}>
                  mode · {trace.selection.launcherMode}
                </span>
              ) : null}
              {trace.selection.launcherSurface ? (
                <span className="studio-tool-permission" data-launcher-surface={trace.selection.launcherSurface}>
                  surface · {trace.selection.launcherSurface}
                </span>
              ) : null}
              {trace.selection.runnableKind ? (
                <span className="studio-tool-permission" data-runnable-kind={trace.selection.runnableKind}>
                  runnable · {trace.selection.runnableKind}
                </span>
              ) : null}
              {trace.selection.dailyDesktopIntent ? (
                <span className="studio-tool-permission" data-daily-desktop-intent="true">
                  daily desktop
                </span>
              ) : null}
              <span className="studio-tool-permission" data-selection-reason={trace.selection.reason}>
                reason · {trace.selection.reason || 'not recorded'}
              </span>
              <span className="studio-tool-permission" data-selection-count-kind="selected">
                selected requests · {trace.selection.selectedRequestCount}
              </span>
              <span className="studio-tool-permission" data-selection-count-kind="plan">
                plan steps · {trace.selection.planStepCount}
              </span>
              <span className="studio-tool-permission" data-selection-count-kind="planner">
                planner requests · {trace.selection.plannerRequestCount}
              </span>
              <span className="studio-tool-permission" data-selection-count-kind="legacy">
                legacy requests · {trace.selection.legacyRequestCount}
              </span>
              {trace.selection.planCapabilities.map((capabilityId) => (
                <span
                  className="studio-tool-permission"
                  data-selection-capability={capabilityId}
                  key={`capability:${capabilityId}`}
                >
                  capability · {capabilityId}
                </span>
              ))}
              {trace.selection.missingCapabilities.map((capabilityId) => (
                <span
                  className="studio-tool-permission missing"
                  data-selection-missing-capability={capabilityId}
                  key={`missing-capability:${capabilityId}`}
                >
                  missing capability · {capabilityId}
                </span>
              ))}
              {trace.selection.selectedTools.map((tool) => (
                <span className="studio-tool-permission" data-selection-tool={tool} key={`selected:${tool}`}>
                  selected · {tool}
                </span>
              ))}
              {trace.selection.planTools.map((tool) => (
                <span className="studio-tool-permission" data-plan-tool={tool} key={`plan:${tool}`}>
                  plan · {tool}
                </span>
              ))}
              {trace.selection.plannerTools.map((tool) => (
                <span className="studio-tool-permission" data-planner-tool={tool} key={`planner:${tool}`}>
                  planner · {tool}
                </span>
              ))}
              {trace.selection.legacyTools.map((tool) => (
                <span className="studio-tool-permission" data-legacy-tool={tool} key={`legacy:${tool}`}>
                  legacy · {tool}
                </span>
              ))}
            </div>
          </section>
        ) : null}

        {trace.selection?.orchestration ? (
          <section
            data-orchestration-handoff={String(trace.selection.orchestration.handoff)}
            data-orchestration-kind={trace.selection.orchestration.kind}
            data-orchestration-route-to-studio={String(trace.selection.orchestration.routeToStudio)}
            data-testid="agent-run-detail-planner-orchestration"
          >
            <div className="studio-tool-inspector-heading">
              <h3>Studio Handoff</h3>
              <span>{trace.selection.orchestration.surface || trace.selection.orchestration.kind || 'orchestration'}</span>
            </div>
            <div className="studio-tool-pill-row">
              {trace.selection.orchestration.entries.map((entry) => (
                <span
                  className="studio-tool-permission"
                  data-orchestration-key={entry.key}
                  data-orchestration-value={entry.value}
                  key={`orchestration:${entry.key}`}
                  title={entry.value}
                >
                  handoff · {entry.key}: {entry.value}
                </span>
              ))}
            </div>
          </section>
        ) : null}

        {trace.selection?.followupTarget ? (
          <section
            data-followup-kind={trace.selection.followupTarget.kind}
            data-testid="agent-run-detail-planner-followup-target"
          >
            <div className="studio-tool-inspector-heading">
              <h3>Follow-up Target</h3>
              <span>{trace.selection.followupTarget.kind || 'target'}</span>
            </div>
            <div className="studio-tool-pill-row">
              {trace.selection.followupTarget.entries.map((entry) => (
                <span
                  className="studio-tool-permission"
                  data-followup-key={entry.key}
                  data-followup-value={entry.value}
                  key={`followup:${entry.key}`}
                  title={entry.value}
                >
                  target · {entry.key}: {entry.value}
                </span>
              ))}
              {trace.selection.followupTarget.communicationCompose.map((entry) => (
                <span
                  className="studio-tool-permission"
                  data-followup-compose-key={entry.key}
                  data-followup-compose-value={entry.value}
                  key={`followup-compose:${entry.key}`}
                  title={entry.value}
                >
                  compose · {entry.key}: {entry.value}
                </span>
              ))}
              {trace.selection.followupTarget.recommendedTools.map((tool) => (
                <span className="studio-tool-permission" data-followup-recommended-tool={tool} key={`followup-tool:${tool}`}>
                  recommended · {tool}
                </span>
              ))}
              {trace.selection.followupTarget.verifyTools.map((tool) => (
                <span className="studio-tool-permission" data-followup-verify-tool={tool} key={`followup-verify:${tool}`}>
                  verify · {tool}
                </span>
              ))}
            </div>
          </section>
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

function TaskCoreInspector({ taskCore }: { taskCore: TaskCoreSnapshot }) {
  const workspaceItems = taskCore.workspace?.items || [];
  const todos = taskCore.todos || [];
  const checkpoints = taskCore.checkpoints || [];
  const replanSignals = taskCore.replan_signals || [];
  return (
    <section
      data-checkpoint-count={checkpoints.length}
      data-core-id={taskCore.core_id}
      data-replan-signal-count={replanSignals.length}
      data-testid="agent-run-detail-task-core"
      data-todo-count={todos.length}
      data-workspace-id={taskCore.workspace?.workspace_id || ''}
    >
      <div className="studio-tool-inspector-heading">
        <h3>Task Core</h3>
        <span>{taskCore.workspace?.title || taskCore.core_id}</span>
      </div>
      <div className="studio-tool-pill-row">
        <span className="studio-tool-permission" data-task-core-count-kind="workspace">
          workspace · {workspaceItems.length}
        </span>
        <span className="studio-tool-permission" data-task-core-count-kind="todo">
          todos · {todos.length}
        </span>
        <span className="studio-tool-permission" data-task-core-count-kind="checkpoint">
          checkpoints · {checkpoints.length}
        </span>
        <span className="studio-tool-permission" data-task-core-count-kind="replan">
          replan · {replanSignals.length}
        </span>
        {workspaceItems.slice(0, 8).map((item) => (
          <span
            className="studio-tool-permission"
            data-task-workspace-item={item.item_id}
            data-task-workspace-item-kind={item.kind || ''}
            key={`workspace:${item.item_id}`}
            title={item.description || item.path || item.title}
          >
            item · {item.kind || 'other'}: {item.title}
          </span>
        ))}
        {todos.slice(0, 8).map((todo) => (
          <span
            className={todo.status === 'blocked' ? 'studio-tool-permission missing' : 'studio-tool-permission'}
            data-task-todo-id={todo.todo_id}
            data-task-todo-status={todo.status || 'pending'}
            key={`todo:${todo.todo_id}`}
            title={todo.reason || todo.tool_name || todo.capability_id}
          >
            todo · {todo.title}
          </span>
        ))}
        {checkpoints.slice(0, 8).map((checkpoint) => (
          <span
            className={checkpoint.status === 'waiting_approval' ? 'studio-tool-permission missing' : 'studio-tool-permission'}
            data-task-checkpoint-id={checkpoint.checkpoint_id}
            data-task-checkpoint-status={checkpoint.status || 'planned'}
            key={`checkpoint:${checkpoint.checkpoint_id}`}
            title={uniqueStrings(checkpoint.verifies || []).join(', ')}
          >
            checkpoint · {checkpoint.title}
          </span>
        ))}
        {replanSignals.slice(0, 8).map((signal) => (
          <span
            className="studio-tool-permission"
            data-task-replan-signal={signal.signal_id}
            data-task-replan-trigger={signal.trigger}
            key={`replan:${signal.signal_id}`}
            title={signal.reason || signal.condition || signal.target}
          >
            replan · {signal.trigger}
          </span>
        ))}
      </div>
    </section>
  );
}

function ReplanRequestInspector({ requests }: { requests: TaskReplanRequestSnapshot[] }) {
  return (
    <section data-replan-request-count={requests.length} data-testid="agent-run-detail-replan-requests">
      <div className="studio-tool-inspector-heading">
        <h3>Replan Requests</h3>
        <span>{requests.length}</span>
      </div>
      <div className="studio-tool-pill-row">
        {requests.map((request) => {
          const fallbackTools = uniqueStrings(request.fallback_tools || []);
          return (
            <span
              className="studio-tool-permission"
              data-replan-request-id={request.request_id}
              data-replan-source-step={request.source_step_id || ''}
              data-replan-status={request.status || 'requested'}
              data-replan-trigger={request.trigger}
              key={request.request_id}
              title={request.failure_detail || request.reason || request.condition}
            >
              replan · {request.trigger}
              {request.source_step_id ? ` · ${request.source_step_id}` : ''}
              {fallbackTools.length ? ` · fallback: ${fallbackTools.join(', ')}` : ''}
            </span>
          );
        })}
      </div>
    </section>
  );
}

function PlannerTraceStepRow({
  index,
  step,
}: {
  index: number;
  step: ToolPlanStepSnapshot;
}) {
  const dependsOn = uniqueStrings(step.depends_on || []);
  const fallbackTools = uniqueStrings(step.fallback_tools || []);
  const inputPreview = plannerStepInputPreview(step.input_preview);
  return (
    <div
      className="studio-planner-step"
      data-action={step.action || ''}
      data-approval-required={String(Boolean(step.approval_required))}
      data-capability-id={step.capability_id}
      data-depends-on={dependsOn.join(',')}
      data-fallback-tools={fallbackTools.join(',')}
      data-input-preview={inputPreview}
      data-planner-step-id={step.step_id}
      data-risk-level={step.risk_level || ''}
      data-step-status={step.status || 'planned'}
      data-testid="agent-run-detail-planner-step"
      data-tool-name={step.tool_name || ''}
    >
      <div>
        <strong>{index + 1}. {step.title}</strong>
        {step.action ? <span>action: {step.action}</span> : null}
        {step.capability_id ? <span>capability: {step.capability_id}</span> : null}
        {step.tool_name ? <span>tool: {step.tool_name}</span> : null}
        {inputPreview ? <span>input: {inputPreview}</span> : null}
        {dependsOn.length ? <span>depends on: {dependsOn.join(', ')}</span> : null}
        {fallbackTools.length ? <span>fallbacks: {fallbackTools.join(', ')}</span> : null}
        {step.reason ? <span>{step.reason}</span> : null}
      </div>
      <small>{step.status || 'planned'}{step.approval_required ? ' / approval' : ''}</small>
    </div>
  );
}

function plannerStepInputPreview(value: unknown): string {
  const record = objectRecord(value);
  if (!Object.keys(record).length) return '';
  try {
    return JSON.stringify(record);
  } catch {
    return '';
  }
}

function plannerIntentInputEntries(value: unknown): Array<{ key: string; value: string }> {
  const record = objectRecord(value);
  return Object.entries(record)
    .map(([key, entryValue]) => ({
      key,
      value: plannerValuePreview(entryValue),
    }))
    .filter((entry) => entry.key && entry.value);
}

function plannerValuePreview(value: unknown): string {
  let preview = '';
  if (typeof value === 'string') {
    preview = value.trim();
  } else if (typeof value === 'number' || typeof value === 'boolean') {
    preview = String(value);
  } else if (value !== null && value !== undefined) {
    try {
      preview = JSON.stringify(value);
    } catch {
      preview = '';
    }
  }
  return truncatePlannerPreview(preview);
}

function truncatePlannerPreview(value: string): string {
  const clean = value.replace(/\s+/g, ' ').trim();
  return clean.length > 160 ? `${clean.slice(0, 157)}...` : clean;
}

function plannerTraceFromEvents(events: PublicRunEvent[]): PlannerTrace | null {
  let intent: TaskIntentSnapshot | null = null;
  let plan: RuntimePlanSnapshot | null = null;
  let toolPlan: ToolPlanSnapshot | null = null;
  let candidateIntents: TaskIntentSnapshot[] = [];
  let source = '';
  let decisionId = '';
  let planId = '';
  let replanRequests: TaskReplanRequestSnapshot[] = [];
  let routeToStudio: boolean | undefined;
  let selection: PlannerSelection | null = null;
  let eventCount = 0;
  const stepById = new Map<string, ToolPlanStepSnapshot>();
  const desktopFallbackStepById = new Map<string, ToolPlanStepSnapshot>();

  for (const event of events) {
    if (publicRunEventIsSecret(event)) continue;
    const eventType = String(event.event_type || '').trim();
    const plannerEventType = runtimePlannerEventType(eventType);
    const payload = objectRecord(event.payload);
    const isRuntimePlannerDesktopIntentEvent = eventType === 'agent.desktop.intent_planned'
      && runtimePlannerDesktopIntentPayload(payload);
    if (!plannerEventType && !isRuntimePlannerDesktopIntentEvent) continue;
    eventCount += 1;
    source = stringValue(payload.source) || source || (isRuntimePlannerDesktopIntentEvent ? 'runtime_planner' : '');
    decisionId = stringValue(payload.decision_id) || decisionId;
    planId = stringValue(payload.plan_id) || planId;

    if (isRuntimePlannerDesktopIntentEvent) {
      if (!plan && !toolPlan) {
        const step = desktopIntentPlanStepFromPayload(payload, desktopFallbackStepById.size + 1);
        if (step) addPlannerStep(desktopFallbackStepById, step);
        routeToStudio = booleanValue(payload.route_to_studio, routeToStudio);
      }
      continue;
    }

    if (plannerEventType === 'agent.intent.selected') {
      intent = taskIntentSnapshot(payload.intent) || intent;
      candidateIntents = arrayRecords(payload.candidate_intents)
        .map(taskIntentSnapshot)
        .filter((candidate): candidate is TaskIntentSnapshot => Boolean(candidate));
      routeToStudio = booleanValue(payload.route_to_studio, routeToStudio);
      continue;
    }

    if (plannerEventType === 'agent.plan.selection') {
      selection = plannerSelectionFromPayload(payload) || selection;
      intent = intent || taskIntentSnapshot(payload.selected_intent) || taskIntentSnapshot(payload.intent);
      const selectionCandidates = arrayRecords(payload.candidate_intents)
        .map(taskIntentSnapshot)
        .filter((candidate): candidate is TaskIntentSnapshot => Boolean(candidate));
      if (!candidateIntents.length && selectionCandidates.length) {
        candidateIntents = selectionCandidates;
      }
      const selectionPlan = runtimePlanSnapshot(payload.runtime_plan) || runtimePlanSnapshot(payload.plan);
      if (!plan && selectionPlan) {
        plan = selectionPlan;
        intent = intent || selectionPlan.intent;
        toolPlan = selectionPlan.tool_plan || toolPlan;
        planId = selectionPlan.plan_id || planId;
        for (const step of selectionPlan.tool_plan?.steps || []) {
          addPlannerStep(stepById, step);
        }
      }
      const selectionToolPlan = toolPlanSnapshot(payload.tool_plan);
      if (!toolPlan && selectionToolPlan) {
        toolPlan = selectionToolPlan;
        planId = selectionToolPlan.plan_id || planId;
        for (const step of selectionToolPlan.steps || []) {
          addPlannerStep(stepById, step);
        }
      }
      routeToStudio = booleanValue(payload.route_to_studio, routeToStudio);
      continue;
    }

    if (plannerEventType === 'agent.plan.created') {
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

    if (plannerEventType === 'agent.plan.step') {
      const step = toolPlanStepSnapshot(payload.step);
      if (step) addPlannerStep(stepById, step);
      continue;
    }

    if (plannerEventType === 'agent.replan.requested') {
      const request = taskReplanRequestSnapshot(payload);
      if (request) {
        replanRequests = [...replanRequests, request];
        decisionId = request.decision_id || decisionId;
        planId = request.plan_id || planId;
        routeToStudio = booleanValue(request.route_to_studio, routeToStudio);
      }
    }
  }

  const fallbackSteps = Array.from(desktopFallbackStepById.values());
  const fallbackToolPlan = !toolPlan && fallbackSteps.length
    ? desktopIntentFallbackToolPlan(fallbackSteps, planId, source)
    : null;
  const effectiveIntent = intent || (fallbackSteps.length ? desktopIntentFallbackIntent(fallbackSteps, source) : null);
  const effectiveToolPlan = toolPlan || fallbackToolPlan;
  const steps = stepById.size ? Array.from(stepById.values()) : fallbackSteps;
  const effectivePlanId = planId || effectiveToolPlan?.plan_id || '';

  if (!effectiveIntent && !plan && !steps.length && !selection && !replanRequests.length) return null;
  return {
    candidateIntents,
    decisionId,
    eventCount,
    intent: effectiveIntent,
    plan,
    planId: effectivePlanId,
    replanRequests,
    routeToStudio,
    selection,
    source,
    steps,
    toolPlan: effectiveToolPlan,
  };
}

function plannerTraceFromSummary(summary: PlannerTraceSummarySnapshot | null | undefined): PlannerTrace | null {
  if (!summary) return null;
  const source = stringValue(summary.source) || 'planner_summary';
  const decisionId = stringValue(summary.decision_id);
  const planId = stringValue(summary.plan_id);
  const intentKind = stringValue(summary.intent_kind);
  const intentTitle = stringValue(summary.intent_title) || intentKind;
  const planTools = uniqueStrings(summary.plan_tools || []);
  const selectedTools = uniqueStrings(summary.selected_tools || []);
  const planCapabilities = uniqueStrings(summary.plan_capabilities || []);
  const requiredCapabilities = uniqueStrings(summary.required_capabilities || []);
  const missingCapabilities = uniqueStrings(summary.missing_capabilities || []);
  const approvalsRequired = uniqueStrings(summary.approvals_required || []);
  const artifactsExpected = uniqueStrings(summary.artifacts_expected || []);
  const openQuestions = uniqueStrings(summary.open_questions || []);
  const stepCount = integerValue(summary.step_count, planTools.length);
  const eventCount = integerValue(summary.event_count, 0);
  const routeToStudio = booleanValue(summary.route_to_studio, undefined);
  const hasIntent = Boolean(intentKind || intentTitle || requiredCapabilities.length || planCapabilities.length);
  const intent: TaskIntentSnapshot | null = hasIntent ? {
    intent_id: decisionId || `planner-summary-${slugValue(intentKind || intentTitle || 'intent')}`,
    kind: intentKind || 'general',
    title: intentTitle || 'Planner Summary Intent',
    required_capabilities: requiredCapabilities.length ? requiredCapabilities : planCapabilities,
    preferred_capabilities: [],
    missing_inputs: openQuestions,
    source,
  } : null;
  const steps = summaryPlanSteps(planTools, planCapabilities, requiredCapabilities, stepCount);
  const hasToolPlan = Boolean(
    planId
    || steps.length
    || requiredCapabilities.length
    || missingCapabilities.length
    || approvalsRequired.length
    || artifactsExpected.length
    || openQuestions.length
  );
  const toolPlan: ToolPlanSnapshot | null = hasToolPlan ? {
    plan_id: planId || 'planner-summary-plan',
    title: 'Runtime Planner Summary Plan',
    steps,
    required_capabilities: requiredCapabilities.length ? requiredCapabilities : planCapabilities,
    missing_capabilities: missingCapabilities,
    approvals_required: approvalsRequired,
    artifacts_expected: artifactsExpected,
    open_questions: openQuestions,
    source,
  } : null;
  const selection = plannerSelectionFromSummary(
    summary,
    planTools,
    selectedTools,
    planCapabilities,
    requiredCapabilities,
    missingCapabilities,
    approvalsRequired,
    artifactsExpected,
    openQuestions,
    stepCount,
  );
  if (!intent && !toolPlan && !selection) return null;
  return {
    candidateIntents: [],
    decisionId,
    eventCount,
    intent,
    plan: null,
    planId: planId || toolPlan?.plan_id || '',
    replanRequests: [],
    routeToStudio,
    selection,
    source,
    steps,
    summaryFallback: true,
    toolPlan,
  };
}

function summaryPlanSteps(
  planTools: string[],
  planCapabilities: string[],
  requiredCapabilities: string[],
  stepCount: number,
): ToolPlanStepSnapshot[] {
  const steps: ToolPlanStepSnapshot[] = planTools.map((tool, index) => ({
    step_id: `summary-step-${index + 1}-${slugValue(tool)}`,
    title: `Use ${tool}`,
    capability_id: planCapabilities[index] || requiredCapabilities[index] || desktopCapabilityForTool(tool),
    action: tool,
    tool_name: tool,
    status: 'planned',
  }));
  const total = Math.max(stepCount, steps.length);
  for (let index = steps.length; index < total; index += 1) {
    steps.push({
      step_id: `summary-step-${index + 1}`,
      title: `Planner step ${index + 1}`,
      capability_id: planCapabilities[index] || requiredCapabilities[index] || 'general.execution',
      status: 'planned',
    });
  }
  return steps;
}

function plannerSelectionFromSummary(
  summary: PlannerTraceSummarySnapshot,
  planTools: string[],
  selectedTools: string[],
  planCapabilities: string[],
  requiredCapabilities: string[],
  missingCapabilities: string[],
  approvalsRequired: string[],
  artifactsExpected: string[],
  openQuestions: string[],
  stepCount: number,
): PlannerSelection | null {
  const selectedSource = stringValue(summary.selection_source);
  const selectedRole = stringValue(summary.selection_role);
  const reason = stringValue(summary.selection_reason);
  const plannerEntrypoint = stringValue(summary.planner_entrypoint);
  const entrypointSource = stringValue(summary.entrypoint_source);
  const launcherMode = stringValue(summary.launcher_mode);
  const launcherSurface = stringValue(summary.launcher_surface);
  const runnableKind = stringValue(summary.runnable_kind);
  const followupTarget = plannerFollowupTargetFromPayload(summary.followup_target);
  const orchestration = plannerOrchestrationFromPayload((summary as Record<string, unknown>).orchestration);
  if (
    !selectedSource
    && !selectedRole
    && !reason
    && !selectedTools.length
    && !planTools.length
    && !planCapabilities.length
    && !missingCapabilities.length
    && !approvalsRequired.length
    && !artifactsExpected.length
    && !openQuestions.length
    && !plannerEntrypoint
    && !entrypointSource
    && !launcherMode
    && !launcherSurface
    && !runnableKind
    && !followupTarget
    && !orchestration
  ) return null;
  return {
    approvalsRequired,
    artifactsExpected,
    dailyDesktopIntent: false,
    entrypointSource,
    followupTarget,
    launcherMode,
    launcherSurface,
    legacyFallback: false,
    legacyRequestCount: 0,
    legacyTools: [],
    missingCapabilities,
    missingCapabilityCount: missingCapabilities.length,
    openQuestions,
    orchestration,
    planCapabilities,
    planCapabilityCount: planCapabilities.length,
    planStepCount: stepCount || planTools.length,
    planTools,
    plannerEntrypoint,
    plannerRequestCount: 0,
    plannerTools: [],
    reason,
    requiredCapabilities,
    runnableKind,
    selectedRequestCount: selectedTools.length,
    selectedRole,
    selectedSource,
    selectedTools,
  };
}

function runtimePlannerEventType(eventType: string): string {
  if (eventType === 'agent.intent.selected') return eventType;
  if (eventType === 'agent.replan.requested') return eventType;
  if (eventType.startsWith('agent.plan.')) return eventType;
  if (eventType === 'group.run.intent.selected') return 'agent.intent.selected';
  if (eventType === 'group.run.plan.created') return 'agent.plan.created';
  if (eventType === 'group.run.plan.step') return 'agent.plan.step';
  if (eventType === 'group.run.plan.selection') return 'agent.plan.selection';
  return '';
}

function addPlannerStep(stepById: Map<string, ToolPlanStepSnapshot>, step: ToolPlanStepSnapshot) {
  const key = step.step_id || `${step.capability_id}:${step.tool_name || step.title}`;
  stepById.set(key, step);
}

function runtimePlannerDesktopIntentPayload(payload: Record<string, unknown>): boolean {
  const source = stringValue(payload.source);
  const planningReason = stringValue(payload.planning_reason);
  return source === 'runtime_planner' || planningReason.startsWith('planner_');
}

function desktopIntentPlanStepFromPayload(
  payload: Record<string, unknown>,
  ordinal: number,
): ToolPlanStepSnapshot | null {
  const toolName = stringValue(payload.tool);
  const detail = stringValue(payload.detail);
  const planningReason = stringValue(payload.planning_reason) || stringValue(payload.reason);
  if (!toolName && !detail && !planningReason) return null;
  const inputPreview = objectRecord(payload.input_preview);
  return {
    step_id: `desktop-intent-${ordinal}-${slugValue(toolName || detail || planningReason || 'tool')}`,
    title: desktopPlannedStepTitle(toolName, detail),
    capability_id: desktopCapabilityForTool(toolName),
    action: planningReason || toolName || 'desktop_intent',
    tool_name: toolName || null,
    input_preview: Object.keys(inputPreview).length ? inputPreview : undefined,
    risk_level: stringValue(payload.risk_level) || 'medium',
    approval_required: booleanValue(payload.approval_required, false),
    reason: planningReason || 'runtime planner desktop intent event',
    status: stringValue(payload.status) || 'planned',
  };
}

function desktopIntentFallbackToolPlan(
  steps: ToolPlanStepSnapshot[],
  planId: string,
  source: string,
): ToolPlanSnapshot {
  return {
    plan_id: planId || 'runtime-planner-desktop-fallback',
    title: 'Runtime Planner Desktop Plan',
    steps,
    required_capabilities: uniqueStrings(steps.map((step) => step.capability_id)),
    missing_capabilities: [],
    approvals_required: steps
      .filter((step) => step.approval_required)
      .map((step) => step.step_id),
    artifacts_expected: [],
    open_questions: [],
    source: source || 'runtime_planner',
  };
}

function desktopIntentFallbackIntent(
  steps: ToolPlanStepSnapshot[],
  source: string,
): TaskIntentSnapshot {
  return {
    intent_id: 'runtime-planner-desktop-intent',
    kind: 'desktop_operation',
    title: 'Desktop Operation',
    description: 'Reconstructed from runtime planner desktop intent events.',
    confidence: 0,
    required_capabilities: uniqueStrings(steps.map((step) => step.capability_id)),
    preferred_capabilities: [],
    missing_inputs: [],
    risk_level: steps.some((step) => step.risk_level === 'high') ? 'high' : 'medium',
    source: source || 'runtime_planner',
  };
}

function desktopPlannedStepTitle(toolName: string, detail: string): string {
  if (detail) return detail;
  if (toolName) return `Use ${toolName}`;
  return 'Desktop operation';
}

function desktopCapabilityForTool(toolName: string): string {
  if (toolName.includes('list_apps') || toolName.includes('running_apps') || toolName.includes('active_window') || toolName.includes('windows')) {
    return 'desktop.app_discovery';
  }
  if (toolName.includes('open_app') || toolName.includes('focus_app') || toolName.includes('app.open') || toolName.includes('app.focus')) {
    return 'desktop.app_control';
  }
  if (toolName.includes('read_ui') || toolName.includes('ui_elements') || toolName.includes('capture')) {
    return 'desktop.app_discovery';
  }
  if (toolName.includes('click') || toolName.includes('type') || toolName.includes('shortcut') || toolName.includes('key') || toolName.includes('hotkey')) {
    return 'desktop.ui_operation';
  }
  return 'desktop.app_control';
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

function toolPlanSnapshot(value: unknown): ToolPlanSnapshot | null {
  const record = objectRecord(value);
  if (!stringValue(record.plan_id) && !stringValue(record.title) && !Array.isArray(record.steps)) return null;
  return record as ToolPlanSnapshot;
}

function toolPlanStepSnapshot(value: unknown): ToolPlanStepSnapshot | null {
  const record = objectRecord(value);
  if (!stringValue(record.step_id) && !stringValue(record.title) && !stringValue(record.capability_id)) return null;
  return record as ToolPlanStepSnapshot;
}

function taskReplanRequestSnapshot(value: unknown): TaskReplanRequestSnapshot | null {
  const record = objectRecord(value);
  const nested = objectRecord(record.request);
  const request = Object.keys(nested).length ? nested : record;
  if (!stringValue(request.request_id) && !stringValue(request.trigger)) return null;
  return request as TaskReplanRequestSnapshot;
}

function plannerSelectionFromPayload(payload: Record<string, unknown>): PlannerSelection | null {
  const selectedSource = stringValue(payload.selection_source);
  const selectedRole = stringValue(payload.selection_role);
  const reason = stringValue(payload.selection_reason);
  const plannerEntrypoint = stringValue(payload.planner_entrypoint);
  const entrypointSource = stringValue(payload.entrypoint_source);
  const launcherMode = stringValue(payload.launcher_mode);
  const launcherSurface = stringValue(payload.launcher_surface);
  const runnableKind = stringValue(payload.runnable_kind);
  const selectedTools = uniqueStrings(Array.isArray(payload.selected_tools) ? payload.selected_tools : []);
  const planTools = uniqueStrings(Array.isArray(payload.plan_tools) ? payload.plan_tools : []);
  const planCapabilities = uniqueStrings(
    Array.isArray(payload.plan_capabilities) ? payload.plan_capabilities : [],
  );
  const requiredCapabilities = uniqueStrings(
    Array.isArray(payload.required_capabilities) ? payload.required_capabilities : [],
  );
  const missingCapabilities = uniqueStrings(
    Array.isArray(payload.missing_capabilities) ? payload.missing_capabilities : [],
  );
  const approvalsRequired = uniqueStrings(
    Array.isArray(payload.approvals_required) ? payload.approvals_required : [],
  );
  const artifactsExpected = uniqueStrings(
    Array.isArray(payload.artifacts_expected) ? payload.artifacts_expected : [],
  );
  const openQuestions = uniqueStrings(
    Array.isArray(payload.open_questions) ? payload.open_questions : [],
  );
  const plannerTools = uniqueStrings(Array.isArray(payload.planner_tools) ? payload.planner_tools : []);
  const legacyTools = uniqueStrings(Array.isArray(payload.legacy_tools) ? payload.legacy_tools : []);
  const selectedRequestCount = integerValue(payload.selected_request_count, selectedTools.length);
  const planStepCount = integerValue(payload.plan_step_count, planTools.length);
  const planCapabilityCount = integerValue(payload.plan_capability_count, planCapabilities.length);
  const missingCapabilityCount = integerValue(payload.missing_capability_count, missingCapabilities.length);
  const plannerRequestCount = integerValue(payload.planner_request_count, plannerTools.length);
  const legacyRequestCount = integerValue(payload.legacy_request_count, legacyTools.length);
  const followupTarget = plannerFollowupTargetFromPayload(payload.followup_target);
  const orchestration = plannerOrchestrationFromPayload(payload.orchestration);
  if (
    !selectedSource
    && !selectedRole
    && !reason
    && !selectedTools.length
    && !planTools.length
    && !planCapabilities.length
    && !missingCapabilities.length
    && !approvalsRequired.length
    && !artifactsExpected.length
    && !openQuestions.length
    && !plannerTools.length
    && !legacyTools.length
    && !plannerEntrypoint
    && !entrypointSource
    && !launcherMode
    && !launcherSurface
    && !runnableKind
    && !followupTarget
    && !orchestration
  ) return null;
  return {
    approvalsRequired,
    artifactsExpected,
    dailyDesktopIntent: booleanValue(payload.entrypoint_daily_desktop_intent, false) || false,
    entrypointSource,
    followupTarget,
    launcherMode,
    launcherSurface,
    legacyTools,
    legacyRequestCount,
    missingCapabilities,
    missingCapabilityCount,
    openQuestions,
    orchestration,
    planCapabilities,
    planCapabilityCount,
    planTools,
    planStepCount,
    plannerTools,
    plannerRequestCount,
    plannerEntrypoint,
    reason,
    requiredCapabilities,
    runnableKind,
    legacyFallback: booleanValue(
      payload.legacy_fallback,
      selectedRole === 'legacy_desktop_intent_fallback',
    ) || false,
    selectedRole,
    selectedSource,
    selectedTools,
    selectedRequestCount,
  };
}

function plannerOrchestrationFromPayload(value: unknown): PlannerOrchestration | null {
  const record = objectRecord(value);
  const entries = plannerRecordEntries(record, ['kind', 'surface', 'handoff', 'route_to_studio']);
  const kind = stringValue(record.kind);
  const surface = stringValue(record.surface);
  const handoff = booleanValue(record.handoff, false) || false;
  const routeToStudio = booleanValue(record.route_to_studio, false) || false;
  if (!kind && !surface && !entries.length && !handoff && !routeToStudio) return null;
  return {
    entries,
    handoff,
    kind,
    routeToStudio,
    surface,
  };
}

function plannerFollowupTargetFromPayload(value: unknown): PlannerFollowupTarget | null {
  const record = objectRecord(value);
  const entries = plannerRecordEntries(record, [
    'communication_compose',
    'recommended_tools',
    'verify_tools',
  ]);
  const communicationCompose = plannerRecordEntries(objectRecord(record.communication_compose));
  const recommendedTools = uniqueStrings(Array.isArray(record.recommended_tools) ? record.recommended_tools : []);
  const verifyTools = uniqueStrings(Array.isArray(record.verify_tools) ? record.verify_tools : []);
  const kind = stringValue(record.kind);
  if (!kind && !entries.length && !communicationCompose.length && !recommendedTools.length && !verifyTools.length) {
    return null;
  }
  return {
    kind,
    entries,
    communicationCompose,
    recommendedTools,
    verifyTools,
  };
}

function plannerRecordEntries(
  record: Record<string, unknown>,
  skipKeys: string[] = [],
): Array<{ key: string; value: string }> {
  const skip = new Set(skipKeys);
  return Object.entries(record)
    .filter(([key]) => key && !skip.has(key))
    .map(([key, entryValue]) => ({
      key,
      value: plannerValuePreview(entryValue),
    }))
    .filter((entry) => entry.value);
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

function slugValue(value: string): string {
  const slug = value.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/(^-|-$)/g, '');
  return slug || 'tool';
}

function booleanValue(value: unknown, fallback?: boolean): boolean | undefined {
  if (typeof value === 'boolean') return value;
  return fallback;
}

function integerValue(value: unknown, fallback: number): number {
  if (typeof value === 'number' && Number.isFinite(value)) return Math.max(0, Math.trunc(value));
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
