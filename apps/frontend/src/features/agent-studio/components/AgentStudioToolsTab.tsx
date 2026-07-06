import { type FormEvent, useEffect, useMemo, useState } from 'react';

import {
  planYachiyoStudioExecution,
  planYachiyoStudioTask,
  startYachiyoStudioDesktopProviderSession,
  startYachiyoStudioPlannerOrchestration,
  stopYachiyoStudioDesktopProviderSession,
  type YachiyoStudioDesktopProviderSessionSnapshot,
} from '../../yachiyo-studio/api';
import type {
  LegacyCleanupCoverageSnapshot,
  PlannerDecisionSnapshot,
  PlannerOrchestrationStartSnapshot,
  RuntimeExecutionEnvelopeSnapshot,
  ToolCatalogItemSnapshot,
  ToolCatalogSnapshot,
  ToolPlanStepSnapshot,
} from '../../yachiyo-studio/types';
import { RuntimeExecutionEnvelopeSummary } from '../../runtime-shared/components/RuntimeExecutionEnvelopeSummary';
import { TaskCoreInspector, TaskProgressInspector } from './PlannerTraceInspector';

type RiskFilter = 'all' | 'low' | 'medium' | 'high' | 'unknown';

const emptyCatalog: ToolCatalogSnapshot = {
  tools: [],
  capabilities: {},
};

type AgentStudioToolsTabProps = {
  catalog: ToolCatalogSnapshot | null;
  error: string;
  loading: boolean;
  onReload: () => void;
  onPlannerOrchestrationStarted?: (result: PlannerOrchestrationStartSnapshot) => Promise<void> | void;
};

export function AgentStudioToolsTab({
  catalog: rawCatalog,
  error,
  loading,
  onReload,
  onPlannerOrchestrationStarted,
}: AgentStudioToolsTabProps) {
  const catalog = rawCatalog || emptyCatalog;
  const [selectedToolName, setSelectedToolName] = useState('');
  const [search, setSearch] = useState('');
  const [riskFilter, setRiskFilter] = useState<RiskFilter>('all');
  const [capabilityFilter, setCapabilityFilter] = useState('all');
  const [plannerPrompt, setPlannerPrompt] = useState('');
  const [plannerDecision, setPlannerDecision] = useState<PlannerDecisionSnapshot | null>(null);
  const [plannerError, setPlannerError] = useState('');
  const [plannerLoading, setPlannerLoading] = useState(false);
  const [plannerStartError, setPlannerStartError] = useState('');
  const [plannerStartLoading, setPlannerStartLoading] = useState(false);
  const [plannerStartResult, setPlannerStartResult] = useState<PlannerOrchestrationStartSnapshot | null>(null);
  const [plannerExecutionEnvelope, setPlannerExecutionEnvelope] = useState<RuntimeExecutionEnvelopeSnapshot | null>(null);
  const [plannerExecutionError, setPlannerExecutionError] = useState('');
  const [plannerExecutionLoading, setPlannerExecutionLoading] = useState(false);
  const [providerSessionBusy, setProviderSessionBusy] = useState<'start' | 'stop' | ''>('');
  const [providerSessionError, setProviderSessionError] = useState('');
  const [providerSessionResult, setProviderSessionResult] = useState<YachiyoStudioDesktopProviderSessionSnapshot | null>(null);
  const legacyCleanupCoverage = catalog.legacy_cleanup_coverage || null;

  useEffect(() => {
    const tools = catalog.tools || [];
    setSelectedToolName((current) => (
      tools.some((tool) => tool.tool_name === current) ? current : tools[0]?.tool_name || ''
    ));
  }, [catalog.tools]);

  const capabilityOptions = useMemo(() => {
    const ids = new Set<string>();
    Object.keys(catalog.capabilities || {}).forEach((capabilityId) => ids.add(capabilityId));
    catalog.tools.forEach((tool) => {
      if (tool.capability_id) ids.add(tool.capability_id);
    });
    return Array.from(ids).sort();
  }, [catalog]);

  const filteredTools = useMemo(() => {
    const query = search.trim().toLowerCase();
    return catalog.tools.filter((tool) => {
      const risk = normalizedRisk(tool);
      if (riskFilter !== 'all' && risk !== riskFilter) return false;
      if (capabilityFilter !== 'all' && tool.capability_id !== capabilityFilter) return false;
      if (!query) return true;
      return [
        tool.tool_name,
        tool.function_name,
        tool.description,
        tool.capability_id || '',
        tool.provider_id || '',
        tool.provider_kind || '',
        tool.provider_ready ? 'provider ready sandbox ready' : '',
        tool.provider_supported ? 'provider supported sandbox provider' : '',
      ].some((value) => String(value || '').toLowerCase().includes(query));
    });
  }, [capabilityFilter, catalog.tools, riskFilter, search]);

  const selectedTool = useMemo(() => {
    return catalog.tools.find((tool) => tool.tool_name === selectedToolName) || filteredTools[0] || null;
  }, [catalog.tools, filteredTools, selectedToolName]);

  const plannerAllowedTools = useMemo(() => catalog.tools
    .map((tool) => tool.tool_name)
    .filter((toolName): toolName is string => Boolean(toolName)), [catalog.tools]);

  function handlePlannerPromptChange(value: string) {
    setPlannerPrompt(value);
    setPlannerStartError('');
    setPlannerStartResult(null);
    setPlannerExecutionError('');
    setPlannerExecutionEnvelope(null);
  }

  async function handlePlannerSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const prompt = plannerPrompt.trim();
    if (!prompt || plannerLoading) return;
    setPlannerLoading(true);
    setPlannerError('');
    try {
      const decision = await planYachiyoStudioTask({
        prompt,
        allowed_tools: plannerAllowedTools,
        metadata: { surface: 'agent_studio_tools' },
      });
      setPlannerDecision(decision);
      setPlannerStartError('');
      setPlannerStartResult(null);
      setPlannerExecutionError('');
      setPlannerExecutionEnvelope(null);
    } catch (error) {
      setPlannerError(errorMessage(error));
    } finally {
      setPlannerLoading(false);
    }
  }

  async function handlePlannerExecutionPreview() {
    const prompt = plannerPrompt.trim();
    if (!prompt || plannerExecutionLoading) return;
    setPlannerExecutionLoading(true);
    setPlannerExecutionError('');
    setPlannerExecutionEnvelope(null);
    try {
      const envelope = await planYachiyoStudioExecution({
        prompt,
        allowed_tools: plannerAllowedTools,
        metadata: { surface: 'agent_studio_tools', preview: 'runtime_execution_envelope' },
      });
      setPlannerExecutionEnvelope(envelope);
    } catch (error) {
      setPlannerExecutionError(errorMessage(error));
    } finally {
      setPlannerExecutionLoading(false);
    }
  }

  async function handlePlannerStartOrchestration() {
    const prompt = plannerPrompt.trim();
    if (!prompt || plannerStartLoading) return;
    setPlannerStartLoading(true);
    setPlannerStartError('');
    setPlannerStartResult(null);
    try {
      const result = await startYachiyoStudioPlannerOrchestration({
        prompt,
        allowed_tools: plannerAllowedTools,
        metadata: { surface: 'agent_studio_tools' },
      });
      setPlannerStartResult(result);
      if (result.status === 'started') {
        await onPlannerOrchestrationStarted?.(result);
      }
    } catch (error) {
      setPlannerStartError(errorMessage(error));
    } finally {
      setPlannerStartLoading(false);
    }
  }

  async function handleProviderSessionStart() {
    if (providerSessionBusy) return;
    setProviderSessionBusy('start');
    setProviderSessionError('');
    try {
      const result = await startYachiyoStudioDesktopProviderSession();
      setProviderSessionResult(result);
      onReload();
    } catch (error) {
      setProviderSessionError(errorMessage(error));
    } finally {
      setProviderSessionBusy('');
    }
  }

  async function handleProviderSessionStop() {
    if (providerSessionBusy) return;
    setProviderSessionBusy('stop');
    setProviderSessionError('');
    try {
      const result = await stopYachiyoStudioDesktopProviderSession();
      setProviderSessionResult(result);
      onReload();
    } catch (error) {
      setProviderSessionError(errorMessage(error));
    } finally {
      setProviderSessionBusy('');
    }
  }

  return (
    <section className="agent-studio-grid agent-studio-tools-grid" data-testid="agent-studio-tools-tab">
      <aside className="agent-studio-panel studio-tool-list-panel">
        <div className="section-heading-row">
          <div>
            <h2>Tools</h2>
            <span>{filteredTools.length} / {catalog.tools.length}</span>
          </div>
          <button
            type="button"
            className="hy-btn hy-btn-ghost"
            disabled={loading}
            onClick={onReload}
          >
            刷新
          </button>
        </div>

        <div className="studio-tool-filters">
          <label>
            <span>Search</span>
            <input
              className="hy-input"
              value={search}
              onChange={(event) => setSearch(event.target.value)}
            />
          </label>
          <label>
            <span>Risk</span>
            <select
              className="hy-select"
              value={riskFilter}
              onChange={(event) => setRiskFilter(event.target.value as RiskFilter)}
            >
              <option value="all">All</option>
              <option value="low">Low</option>
              <option value="medium">Medium</option>
              <option value="high">High</option>
              <option value="unknown">Unknown</option>
            </select>
          </label>
          <label>
            <span>Capability</span>
            <select
              className="hy-select"
              value={capabilityFilter}
              onChange={(event) => setCapabilityFilter(event.target.value)}
            >
              <option value="all">All</option>
              {capabilityOptions.map((capabilityId) => (
                <option key={capabilityId} value={capabilityId}>{capabilityLabel(capabilityId)}</option>
              ))}
            </select>
          </label>
        </div>

        <LegacyCleanupCoveragePanel coverage={legacyCleanupCoverage} />

        <DesktopProviderSessionPanel
          busy={providerSessionBusy}
          catalog={catalog}
          error={providerSessionError}
          latestResult={providerSessionResult}
          onStart={() => void handleProviderSessionStart()}
          onStop={() => void handleProviderSessionStop()}
        />

        {error ? <div className="notice danger">{error}</div> : null}
        <div className="studio-tool-list" data-testid="agent-studio-tool-list">
          {filteredTools.map((tool) => (
            <button
              type="button"
              key={tool.tool_name}
              className={tool.tool_name === selectedTool?.tool_name ? 'studio-tool-item active' : 'studio-tool-item'}
              aria-pressed={tool.tool_name === selectedTool?.tool_name}
              onClick={() => setSelectedToolName(tool.tool_name)}
            >
              <span>
                <strong>{tool.tool_name}</strong>
                <small>{capabilityLabel(tool.capability_id || '')}</small>
              </span>
              <span className={`studio-tool-risk ${normalizedRisk(tool)}`}>{riskLabel(tool)}</span>
            </button>
          ))}
          {!filteredTools.length ? <span className="studio-tool-empty">No tools</span> : null}
        </div>
      </aside>

      <div className="agent-studio-panel studio-tool-detail" data-testid="agent-studio-tool-detail">
        <RuntimePlannerPreview
          decision={plannerDecision}
          error={plannerError}
          executionEnvelope={plannerExecutionEnvelope}
          executionError={plannerExecutionError}
          executionLoading={plannerExecutionLoading}
          loading={plannerLoading}
          onPromptChange={handlePlannerPromptChange}
          onPlanExecution={() => void handlePlannerExecutionPreview()}
          onStartOrchestration={() => void handlePlannerStartOrchestration()}
          onSubmit={handlePlannerSubmit}
          prompt={plannerPrompt}
          startError={plannerStartError}
          startLoading={plannerStartLoading}
          startResult={plannerStartResult}
        />
        {selectedTool ? <ToolDetail tool={selectedTool} catalog={catalog} /> : null}
        {!selectedTool && !loading ? <span className="studio-tool-empty">No tool selected</span> : null}
        {loading ? <span className="studio-tool-empty">Loading tools</span> : null}
      </div>
    </section>
  );
}

function DesktopProviderSessionPanel({
  busy,
  catalog,
  error,
  latestResult,
  onStart,
  onStop,
}: {
  busy: 'start' | 'stop' | '';
  catalog: ToolCatalogSnapshot;
  error: string;
  latestResult: YachiyoStudioDesktopProviderSessionSnapshot | null;
  onStart: () => void;
  onStop: () => void;
}) {
  const diagnostics = objectRecord(catalog.controlled_provider_diagnostics);
  const managedSession = objectRecord(diagnostics.session_manager);
  const resultRecord = latestResult ? objectRecord(latestResult) : {};
  const session = latestResult ? resultRecord : managedSession;
  const running = latestResult ? latestResult.running === true : session.running === true;
  const status = stringValue(session.status) || (running ? 'running' : 'stopped');
  const providerId = stringValue(session.provider_id) || stringValue(diagnostics.provider_id);
  const url = stringValue(session.url);
  const pid = stringValue(session.pid);
  const command = stringArray(session.command);
  const source = stringValue(session.source);
  return (
    <section
      className="studio-tool-inspector-section"
      data-provider-session-command={command.join(' ')}
      data-provider-session-pid={pid}
      data-provider-session-running={String(running)}
      data-provider-session-source={source}
      data-provider-session-status={status}
      data-provider-session-url={url}
      data-testid="studio-desktop-provider-session"
    >
      <div className="studio-tool-inspector-heading">
        <h3>Desktop Session</h3>
        <span>{status}</span>
      </div>
      <div className="studio-tool-pill-row">
        {providerId ? (
          <span className="studio-tool-permission" data-provider-session-id={providerId}>
            {providerId}
          </span>
        ) : null}
        {url ? (
          <span className="studio-tool-permission" data-provider-session-url={url}>
            {url}
          </span>
        ) : null}
        {pid ? (
          <span className="studio-tool-permission" data-provider-session-pid={pid}>
            pid {pid}
          </span>
        ) : null}
        {!providerId && !url && !pid ? (
          <span className="studio-tool-permission missing">isolated provider stopped</span>
        ) : null}
      </div>
      {error ? <div className="notice danger">{error}</div> : null}
      <div className="studio-planner-actions">
        <button
          type="button"
          className="hy-btn hy-btn-primary"
          disabled={Boolean(busy) || running}
          onClick={onStart}
        >
          {busy === 'start' ? '启动中' : '启动'}
        </button>
        <button
          type="button"
          className="hy-btn hy-btn-ghost"
          disabled={Boolean(busy) || !running}
          onClick={onStop}
        >
          {busy === 'stop' ? '停止中' : '停止'}
        </button>
      </div>
    </section>
  );
}

function LegacyCleanupCoveragePanel({
  coverage,
}: {
  coverage: LegacyCleanupCoverageSnapshot | null;
}) {
  if (!coverage) return null;
  const areas = Object.entries(coverage.areas || {});
  const prompts = coverage.prompts || [];
  const areaContracts = coverage.area_contracts || [];
  const sampleContracts = coverage.sample_contracts || [];
  const plannerOwnedEntrypoints = coverage.planner_owned_entrypoints || [];
  const remainingFallbacks = coverage.remaining_fallback_contracts || [];
  return (
    <section
      className="studio-tool-inspector-section studio-legacy-cleanup-coverage"
      data-covered-capabilities={(coverage.covered_capabilities || []).join(',')}
      data-covered-intents={(coverage.covered_intents || []).join(',')}
      data-covered-tools={(coverage.covered_tools || []).join(',')}
      data-legacy-boundary={coverage.legacy_boundary || ''}
      data-planner-owner={coverage.planner_owner || ''}
      data-planner-owned-entrypoints={plannerOwnedEntrypoints.map((entrypoint) => entrypoint.entrypoint_id).join(',')}
      data-remaining-fallbacks={remainingFallbacks.map((fallback) => fallback.fallback_id).join(',')}
      data-testid="studio-legacy-cleanup-coverage"
      data-total-samples={coverage.total_samples || 0}
    >
      <div className="studio-tool-inspector-heading">
        <h3>Legacy Cleanup Coverage</h3>
        <span>{coverage.planner_owner || 'planner'} · {coverage.legacy_boundary || 'legacy boundary'}</span>
      </div>
      <div className="studio-tool-detail-grid">
        <span>
          <small>Samples</small>
          <strong>{coverage.total_samples || prompts.length}</strong>
        </span>
        <span>
          <small>Areas</small>
          <strong>{areas.length || 'None'}</strong>
        </span>
        <span>
          <small>Planner Contracts</small>
          <strong>{sampleContracts.length || areaContracts.length || 'None'}</strong>
        </span>
        <span>
          <small>Owned Entry</small>
          <strong>{plannerOwnedEntrypoints.length || 'None'}</strong>
        </span>
        <span>
          <small>Fallbacks</small>
          <strong>{remainingFallbacks.length || 'None'}</strong>
        </span>
      </div>
      {areas.length ? (
        <div className="studio-tool-pill-row" data-testid="studio-legacy-cleanup-areas">
          {areas.slice(0, 10).map(([area, count]) => (
            <span className="studio-tool-permission" data-cleanup-area={area} key={area}>
              {area} · {count}
            </span>
          ))}
        </div>
      ) : null}
      {areaContracts.length ? (
        <div className="studio-planner-step-list compact" data-testid="studio-legacy-cleanup-contracts">
          {areaContracts.slice(0, 5).map((contract) => (
            <span
              className="studio-tool-empty"
              data-cleanup-contract-area={contract.area}
              data-cleanup-contract-capabilities={(contract.planner_capabilities || []).join(',')}
              data-cleanup-contract-intents={(contract.planner_intents || []).join(',')}
              data-cleanup-contract-tools={(contract.planner_tools || []).join(',')}
              key={contract.area}
            >
              {contract.area} · {(contract.planner_intents || []).join(',') || 'planner'}
            </span>
          ))}
        </div>
      ) : null}
      {plannerOwnedEntrypoints.length ? (
        <div className="studio-planner-step-list compact" data-testid="studio-legacy-cleanup-owned-entrypoints">
          {plannerOwnedEntrypoints.slice(0, 5).map((entrypoint) => (
            <span
              className="studio-tool-empty"
              data-cleanup-owned-entrypoint={entrypoint.entrypoint_id}
              data-cleanup-owned-tools={(entrypoint.tools || []).join(',')}
              data-cleanup-owned-shape-preserved={String(entrypoint.legacy_shape_preserved !== false)}
              key={entrypoint.entrypoint_id}
            >
              {entrypoint.title || entrypoint.entrypoint_id}
            </span>
          ))}
        </div>
      ) : null}
      {remainingFallbacks.length ? (
        <div className="studio-planner-step-list compact" data-testid="studio-legacy-cleanup-fallbacks">
          {remainingFallbacks.slice(0, 5).map((fallback) => (
            <span
              className="studio-tool-empty"
              data-cleanup-fallback={fallback.fallback_id}
              data-cleanup-fallback-status={fallback.status || ''}
              title={fallback.reason || fallback.title}
              key={fallback.fallback_id}
            >
              {fallback.title || fallback.fallback_id}
            </span>
          ))}
        </div>
      ) : null}
      {prompts.length ? (
        <div className="studio-planner-step-list compact" data-testid="studio-legacy-cleanup-prompts">
          {prompts.slice(0, 5).map((prompt) => (
            <span className="studio-tool-empty" data-cleanup-prompt={prompt} key={prompt}>{prompt}</span>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function RuntimePlannerPreview({
  decision,
  error,
  executionEnvelope,
  executionError,
  executionLoading,
  loading,
  onPromptChange,
  onPlanExecution,
  onStartOrchestration,
  onSubmit,
  prompt,
  startError,
  startLoading,
  startResult,
}: {
  decision: PlannerDecisionSnapshot | null;
  error: string;
  executionEnvelope: RuntimeExecutionEnvelopeSnapshot | null;
  executionError: string;
  executionLoading: boolean;
  loading: boolean;
  onPromptChange: (value: string) => void;
  onPlanExecution: () => void;
  onStartOrchestration: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  prompt: string;
  startError: string;
  startLoading: boolean;
  startResult: PlannerOrchestrationStartSnapshot | null;
}) {
  const plan = decision?.plan;
  const toolPlan = plan?.tool_plan;
  const steps = toolPlan?.steps || [];
  const missingCapabilities = toolPlan?.missing_capabilities || [];
  const requiredCapabilities = toolPlan?.required_capabilities || [];
  const openQuestions = toolPlan?.open_questions || [];
  const candidateIntents = decision?.candidate_intents || [];
  return (
    <div className="studio-tool-inspector-section studio-planner-preview" data-testid="studio-runtime-planner-preview">
      <div className="studio-tool-inspector-heading">
        <h3>Runtime Planner</h3>
        <span>{decision ? decision.selected_intent.kind : 'Ready'}</span>
      </div>
      <form className="studio-planner-form" onSubmit={onSubmit}>
        <textarea
          className="hy-input agent-textarea compact"
          data-testid="studio-runtime-planner-prompt"
          value={prompt}
          onChange={(event) => onPromptChange(event.target.value)}
        />
        <div className="studio-planner-actions">
          <button
            type="submit"
            className="hy-btn hy-btn-primary"
            disabled={loading || !prompt.trim()}
            data-testid="studio-runtime-planner-run"
          >
            {loading ? 'Planning...' : 'Plan'}
          </button>
          <button
            type="button"
            className="hy-btn hy-btn-secondary"
            disabled={executionLoading || loading || !prompt.trim()}
            data-testid="studio-runtime-planner-build-execution"
            onClick={onPlanExecution}
          >
            {executionLoading ? 'Building...' : 'Build Envelope'}
          </button>
          <button
            type="button"
            className="hy-btn hy-btn-secondary"
            disabled={startLoading || loading || !prompt.trim()}
            data-testid="studio-runtime-planner-start-orchestration"
            onClick={onStartOrchestration}
          >
            {startLoading ? 'Starting...' : 'Start in Studio'}
          </button>
        </div>
      </form>
      {error ? <div className="notice danger" data-testid="studio-runtime-planner-error">{error}</div> : null}
      {executionError ? <div className="notice danger" data-testid="studio-runtime-planner-execution-error">{executionError}</div> : null}
      {startError ? <div className="notice danger" data-testid="studio-runtime-planner-start-error">{startError}</div> : null}
      {startResult ? <PlannerOrchestrationStartResult result={startResult} /> : null}
      {executionEnvelope ? <RuntimeExecutionEnvelopePreview envelope={executionEnvelope} /> : null}
      {decision ? (
        <div className="studio-planner-result" data-testid="studio-runtime-planner-result">
          <div className="studio-tool-detail-grid">
            <span>
              <small>Intent</small>
              <strong>{decision.selected_intent.kind}</strong>
            </span>
            <span>
              <small>Route</small>
              <strong>{plan?.route_to_studio ? 'Studio' : 'Direct'}</strong>
            </span>
            <span>
              <small>Missing</small>
              <strong>{missingCapabilities.length || 'None'}</strong>
            </span>
            <span>
              <small>Open Questions</small>
              <strong>{openQuestions.length || 'None'}</strong>
            </span>
            <span>
              <small>Candidates</small>
              <strong>{candidateIntents.length || 'None'}</strong>
            </span>
          </div>
          {requiredCapabilities.length || openQuestions.length || candidateIntents.length ? (
            <div className="studio-tool-pill-row" data-testid="studio-runtime-planner-debug-pills">
              {requiredCapabilities.map((capabilityId) => (
                <span
                  className="studio-tool-permission"
                  data-required-capability={capabilityId}
                  key={`required:${capabilityId}`}
                >
                  required · {capabilityId}
                </span>
              ))}
              {openQuestions.map((question) => (
                <span
                  className="studio-tool-permission missing"
                  data-open-question={question}
                  key={`question:${question}`}
                >
                  question · {question}
                </span>
              ))}
              {candidateIntents.map((intent) => (
                <span
                  className="studio-tool-permission"
                  data-candidate-intent={intent.kind}
                  key={`candidate:${intent.intent_id || intent.kind}`}
                >
                  candidate · {intent.kind}
                </span>
              ))}
            </div>
          ) : null}
          {missingCapabilities.length ? (
            <div className="studio-tool-pill-row">
              {missingCapabilities.map((capabilityId) => (
                <span className="studio-tool-permission missing" key={capabilityId}>{capabilityId}</span>
              ))}
            </div>
          ) : null}
          <div className="studio-planner-step-list">
            {steps.map((step, index) => (
              <PlannerStepRow key={step.step_id || `${step.title}-${index}`} step={step} index={index} />
            ))}
            {!steps.length ? <span className="studio-tool-empty">No planned steps</span> : null}
          </div>
          {plan?.task_core ? <TaskCoreInspector taskCore={plan.task_core} /> : null}
        </div>
      ) : null}
    </div>
  );
}

function RuntimeExecutionEnvelopePreview({
  envelope,
}: {
  envelope: RuntimeExecutionEnvelopeSnapshot;
}) {
  return (
    <div className="studio-planner-result">
      <RuntimeExecutionEnvelopeSummary
        debugPillsTestId="studio-runtime-execution-debug-pills"
        envelope={envelope}
        requestListTestId="studio-runtime-execution-requests"
        requestTestId="studio-runtime-execution-request"
        showRequests
        testId="studio-runtime-execution-envelope"
        variant="studio"
      />
      {envelope.task_core ? <TaskCoreInspector taskCore={envelope.task_core} /> : null}
      {envelope.task_progress ? (
        <TaskProgressInspector
          replanRecoveries={[]}
          taskProgress={envelope.task_progress}
        />
      ) : null}
    </div>
  );
}

function PlannerOrchestrationStartResult({
  result,
}: {
  result: PlannerOrchestrationStartSnapshot;
}) {
  const runId = plannerOrchestrationRunId(result);
  return (
    <div
      className="studio-tool-inspector-section"
      data-orchestration-kind={result.kind}
      data-orchestration-run-id={runId}
      data-orchestration-status={result.status}
      data-orchestration-target-id={result.target_id || ''}
      data-testid="studio-runtime-planner-orchestration-start"
    >
      <div className="studio-tool-inspector-heading">
        <h3>Studio Orchestration</h3>
        <span>{result.status}</span>
      </div>
      <div className="studio-tool-detail-grid">
        <span>
          <small>Kind</small>
          <strong>{result.kind || 'unknown'}</strong>
        </span>
        <span>
          <small>Target</small>
          <strong>{result.target_name || result.target_id || 'None'}</strong>
        </span>
        <span>
          <small>Run</small>
          <strong>{runId || 'Not started'}</strong>
        </span>
        <span>
          <small>Route</small>
          <strong>{result.route_to_studio ? 'Studio' : 'Direct'}</strong>
        </span>
      </div>
      {result.message ? (
        <div className="notice">{result.message}</div>
      ) : null}
    </div>
  );
}

function PlannerStepRow({
  index,
  step,
}: {
  index: number;
  step: ToolPlanStepSnapshot;
}) {
  return (
    <div className="studio-planner-step" data-testid="studio-runtime-planner-step">
      <div>
        <strong>{index + 1}. {step.title}</strong>
        <span>{step.tool_name || step.capability_id}</span>
      </div>
      <small>{step.status}{step.approval_required ? ' / approval' : ''}</small>
    </div>
  );
}

function plannerOrchestrationRunId(result: PlannerOrchestrationStartSnapshot): string {
  if (result.run_id) return result.run_id;
  if (result.workflow_run_id) return result.workflow_run_id;
  if (result.group_run_id) return result.group_run_id;
  if (result.workflow_run?.run_id) return result.workflow_run.run_id;
  const groupRun = result.group_run;
  return groupRun?.runs?.[0]?.run_id || groupRun?.child_run_ids?.[0] || '';
}

function ToolDetail({
  catalog,
  tool,
}: {
  catalog: ToolCatalogSnapshot;
  tool: ToolCatalogItemSnapshot;
}) {
  const capability = tool.capability_id ? catalog.capabilities?.[tool.capability_id] : undefined;
  const inputSchema = toolInputSchema(tool);
  const schemaProperties = schemaPropertyRows(inputSchema);
  const missingPermissions = tool.missing_permissions || [];
  const blockingConditions = uniqueStrings([
    ...(tool.blocking_conditions || []),
    ...(capability?.blocking_conditions || []),
  ]);
  const fallbackNotes = tool.fallback_notes || [];
  const diagnosticRoute = tool.diagnostic_route || capability?.diagnostic_route || '';
  const modelFunctionName = modelToolFunctionName(tool) || tool.function_name;
  const providerState = toolProviderState(tool, catalog);
  return (
    <>
      <div className="section-heading-row">
        <div>
          <h2>{tool.tool_name}</h2>
          <span>{modelFunctionName}</span>
        </div>
        <span className={`studio-tool-risk ${normalizedRisk(tool)}`}>{riskLabel(tool)}</span>
      </div>

      <div className="studio-tool-detail-grid">
        <span data-testid="studio-tool-risk-detail">
          <small>Risk</small>
          <strong>{riskLabel(tool)}</strong>
        </span>
        <span>
          <small>Capability</small>
          <strong>{capabilityLabel(tool.capability_id || '')}</strong>
        </span>
        <span>
          <small>Approval</small>
          <strong>{tool.approval_required ? 'Required' : 'Not required'}</strong>
        </span>
        <span>
          <small>Diagnostic</small>
          <strong data-testid="studio-tool-diagnostic-route">{diagnosticRoute || 'None'}</strong>
        </span>
        <span>
          <small>Source</small>
          <strong>{tool.source || 'runtime'}</strong>
        </span>
        <span>
          <small>Function</small>
          <strong>{tool.function_name}</strong>
        </span>
        <span data-testid="studio-tool-provider-state">
          <small>Provider</small>
          <strong>{providerState.label}</strong>
        </span>
      </div>

      {tool.description ? <p className="studio-tool-description">{tool.description}</p> : null}

      <div className="studio-tool-inspector-section" data-testid="studio-tool-permissions">
        <div className="studio-tool-inspector-heading">
          <h3>Permissions</h3>
          <span>{missingPermissions.length ? 'Missing requirements' : 'Ready'}</span>
        </div>
        <div className="studio-tool-pill-row">
          {missingPermissions.map((permission) => (
            <span className="studio-tool-permission missing" key={permission}>{permission}</span>
          ))}
          {!missingPermissions.length ? (
            <span className="studio-tool-permission">permissions ready</span>
          ) : null}
        </div>
      </div>

      <div className="studio-tool-inspector-section" data-testid="studio-tool-runtime-blockers">
        <div className="studio-tool-inspector-heading">
          <h3>Runtime Conditions</h3>
          <span>{blockingConditions.length ? 'Blocked' : 'Ready'}</span>
        </div>
        <div className="studio-tool-pill-row">
          {blockingConditions.map((condition) => (
            <span
              className="studio-tool-permission missing"
              data-runtime-blocker={condition}
              key={condition}
            >
              {runtimeBlockingLabel(condition)}
            </span>
          ))}
          {!blockingConditions.length ? (
            <span className="studio-tool-permission">runtime conditions ready</span>
          ) : null}
        </div>
      </div>

      <div
        className="studio-tool-inspector-section"
        data-controlled-provider-command={providerState.controlledCommand.join(' ')}
        data-controlled-provider-blockers={providerState.controlledBlockingConditions.join(',')}
        data-controlled-provider-configured={String(providerState.controlledConfigured)}
        data-controlled-provider-env-url={providerState.controlledEnvUrl}
        data-controlled-provider-endpoint-origin={providerState.controlledEndpointOrigin}
        data-controlled-provider-endpoint-path={providerState.controlledEndpointPath}
        data-controlled-provider-id={providerState.controlledProviderId}
        data-controlled-provider-ready={String(providerState.controlledReady)}
        data-controlled-provider-reason={providerState.controlledReason}
        data-controlled-provider-requires-approval={String(providerState.controlledRequiresApproval)}
        data-controlled-provider-session-isolated={String(providerState.controlledSessionIsolated)}
        data-controlled-provider-session-kind={providerState.controlledSessionKind}
        data-controlled-provider-session-manager-running={String(providerState.controlledSessionManagerRunning)}
        data-controlled-provider-session-manager-status={providerState.controlledSessionManagerStatus}
        data-controlled-provider-session-manager-url={providerState.controlledSessionManagerUrl}
        data-controlled-provider-status={providerState.controlledStatus}
        data-controlled-provider-takeover-required={String(providerState.controlledForegroundTakeoverRequired)}
        data-provider-ready={String(providerState.ready)}
        data-provider-requires-real-sandbox-for={providerState.requiresRealSandboxFor.join(',')}
        data-provider-status={providerState.status}
        data-provider-supported={String(providerState.supported)}
        data-testid="studio-tool-provider-readiness"
      >
        <div className="studio-tool-inspector-heading">
          <h3>Desktop Provider</h3>
          <span>{providerState.label}</span>
        </div>
        <div className="studio-tool-pill-row">
          <span className={providerState.ready ? 'studio-tool-permission' : 'studio-tool-permission missing'}>
            {providerState.detail}
          </span>
          {providerState.providerId ? (
            <span className="studio-tool-permission" data-provider-id={providerState.providerId}>
              {providerState.providerId}
            </span>
          ) : null}
          {providerState.providerKind ? (
            <span className="studio-tool-permission" data-provider-kind={providerState.providerKind}>
              {providerState.providerKind}
            </span>
          ) : null}
          {providerState.supportedTools.map((toolName) => (
            <span className="studio-tool-permission" data-provider-tool={toolName} key={toolName}>
              {toolName}
            </span>
          ))}
          {providerState.requiresRealSandboxFor
            .filter((toolName) => toolName === tool.tool_name)
            .map((toolName) => (
              <span
                className="studio-tool-permission missing"
                data-provider-real-sandbox-tool={toolName}
                key={toolName}
              >
                {toolName}
              </span>
            ))}
          {providerState.controlledCommand.length ? (
            <span
              className="studio-tool-permission missing"
              data-controlled-provider-launch-command={providerState.controlledCommand.join(' ')}
              data-controlled-provider-smoke-command={providerState.controlledSmokeCommand.join(' ')}
              title={providerState.controlledCommand.join(' ')}
            >
              controlled · {providerState.controlledProviderId || 'launch provider'}
            </span>
          ) : null}
          {providerState.controlledEnvUrl ? (
            <span className="studio-tool-permission" data-controlled-provider-env-url={providerState.controlledEnvUrl}>
              {providerState.controlledEnvUrl}
            </span>
          ) : null}
          {providerState.controlledStatus ? (
            <span
              className={providerState.controlledReady ? 'studio-tool-permission' : 'studio-tool-permission missing'}
              data-controlled-provider-status={providerState.controlledStatus}
            >
              {providerState.controlledStatus}
            </span>
          ) : null}
          {providerState.controlledSessionManagerStatus ? (
            <span
              className={providerState.controlledSessionManagerRunning ? 'studio-tool-permission' : 'studio-tool-permission missing'}
              data-controlled-provider-session-manager-status={providerState.controlledSessionManagerStatus}
              data-controlled-provider-session-manager-url={providerState.controlledSessionManagerUrl}
            >
              {providerState.controlledSessionManagerStatus}
            </span>
          ) : null}
          {providerState.controlledSessionKind ? (
            <span
              className={providerState.controlledSessionIsolated ? 'studio-tool-permission' : 'studio-tool-permission missing'}
              data-controlled-provider-session-kind={providerState.controlledSessionKind}
              data-controlled-provider-session-isolated={String(providerState.controlledSessionIsolated)}
            >
              {providerState.controlledSessionKind}
            </span>
          ) : null}
          {providerState.controlledEndpointOrigin ? (
            <span className="studio-tool-permission" data-controlled-provider-endpoint-origin={providerState.controlledEndpointOrigin}>
              {providerState.controlledEndpointOrigin}{providerState.controlledEndpointPath}
            </span>
          ) : null}
          {providerState.controlledBlockingConditions.map((condition) => (
            <span
              className="studio-tool-permission missing"
              data-controlled-provider-blocker={condition}
              key={condition}
            >
              {runtimeBlockingLabel(condition)}
            </span>
          ))}
          {providerState.blockingConditions.map((condition) => (
            <span
              className="studio-tool-permission missing"
              data-provider-blocker={condition}
              key={condition}
            >
              {runtimeBlockingLabel(condition)}
            </span>
          ))}
        </div>
      </div>

      <div className="studio-tool-inspector-section" data-testid="studio-tool-fallback-notes">
        <div className="studio-tool-inspector-heading">
          <h3>Fallback</h3>
          <span>{fallbackNotes.length ? 'Runtime fallback path' : 'No fallback registered'}</span>
        </div>
        <div className="studio-tool-note-list">
          {fallbackNotes.map((note) => <span key={note}>{note}</span>)}
          {!fallbackNotes.length ? <span>No fallback registered for this tool.</span> : null}
        </div>
      </div>

      <div className="studio-tool-inspector-section" data-testid="studio-tool-schema-properties">
        <div className="studio-tool-inspector-heading">
          <h3>Schema Properties</h3>
          <span>{schemaProperties.length} parameters</span>
        </div>
        {schemaProperties.length ? (
          <div className="studio-tool-schema-property-list">
            {schemaProperties.map((property) => (
              <div className="studio-tool-schema-property" key={property.name}>
                <div>
                  <strong>{property.name}</strong>
                  {property.required ? <small>required</small> : null}
                </div>
                <span>{property.type}</span>
                {property.description ? <p>{property.description}</p> : null}
              </div>
            ))}
          </div>
        ) : (
          <span className="studio-tool-empty">No input properties</span>
        )}
      </div>

      <details className="run-detail-block run-detail-fold studio-tool-schema" data-testid="studio-tool-input-schema" open>
        <summary className="run-detail-section-head">
          <div>
            <h4>Input Schema</h4>
            <span>Model parameters</span>
          </div>
        </summary>
        <pre>{JSON.stringify(inputSchema, null, 2)}</pre>
      </details>

      <details className="run-detail-block run-detail-fold studio-tool-schema" data-testid="studio-tool-model-schema">
        <summary className="run-detail-section-head">
          <div>
            <h4>Model Tool Schema</h4>
            <span>{modelFunctionName}</span>
          </div>
        </summary>
        <pre>{JSON.stringify(tool.model_tool_schema || {}, null, 2)}</pre>
      </details>
    </>
  );
}

type ToolProviderState = {
  label: string;
  detail: string;
  ready: boolean;
  supported: boolean;
  providerId: string;
  providerKind: string;
  status: string;
  blockingConditions: string[];
  supportedTools: string[];
  requiresRealSandboxFor: string[];
  controlledProviderId: string;
  controlledCommand: string[];
  controlledSmokeCommand: string[];
  controlledEnvUrl: string;
  controlledRequiresApproval: boolean;
  controlledReady: boolean;
  controlledConfigured: boolean;
  controlledStatus: string;
  controlledReason: string;
  controlledBlockingConditions: string[];
  controlledSessionManagerRunning: boolean;
  controlledSessionManagerStatus: string;
  controlledSessionManagerUrl: string;
  controlledSessionKind: string;
  controlledSessionIsolated: boolean;
  controlledForegroundTakeoverRequired: boolean;
  controlledEndpointOrigin: string;
  controlledEndpointPath: string;
};

function toolProviderState(tool: ToolCatalogItemSnapshot, catalog: ToolCatalogSnapshot): ToolProviderState {
  const provider = catalog.sandbox_provider || null;
  const controlledDiagnostics = objectRecord(catalog.controlled_provider_diagnostics);
  const ready = tool.provider_ready === true;
  const supported = tool.provider_supported === true;
  const providerId = stringValue(tool.provider_id) || stringValue(provider?.provider_id);
  const providerKind = stringValue(tool.provider_kind) || stringValue(provider?.provider_kind);
  const status = stringValue(provider?.status) || (ready ? 'ready' : supported ? 'supported' : 'runtime_only');
  const supportedTools = stringArray(provider?.supported_tools);
  const requiresRealSandboxFor = stringArray(provider?.requires_real_sandbox_for);
  const blockingConditions = stringArray(provider?.blocking_conditions);
  const launchHint = objectRecord(provider?.launch_hint);
  const controlledProvider = Object.keys(objectRecord(launchHint.isolated_provider)).length
    ? objectRecord(launchHint.isolated_provider)
    : objectRecord(launchHint.controlled_provider);
  const controlledEnv = objectRecord(controlledDiagnostics.env).OHA_YACHIYO_DESKTOP_PROVIDER_URL
    ? objectRecord(controlledDiagnostics.env)
    : objectRecord(controlledProvider.env);
  const controlledProviderId = stringValue(controlledDiagnostics.provider_id)
    || stringValue(controlledProvider.provider_id);
  const controlledCommand = stringArray(controlledDiagnostics.launch_command).length
    ? stringArray(controlledDiagnostics.launch_command)
    : stringArray(controlledProvider.command);
  const controlledSmokeCommand = stringArray(controlledDiagnostics.smoke_command).length
    ? stringArray(controlledDiagnostics.smoke_command)
    : stringArray(controlledProvider.smoke_command);
  const controlledEnvUrl = stringValue(controlledEnv.OHA_YACHIYO_DESKTOP_PROVIDER_URL);
  const controlledRequiresApproval = controlledDiagnostics.requires_runtime_approval === true
    || controlledProvider.requires_runtime_approval === true;
  const controlledReady = controlledDiagnostics.ready === true;
  const controlledConfigured = controlledDiagnostics.configured === true;
  const controlledStatus = stringValue(controlledDiagnostics.status);
  const controlledReason = stringValue(controlledDiagnostics.reason);
  const controlledBlockingConditions = stringArray(controlledDiagnostics.blocking_conditions);
  const controlledSessionManager = objectRecord(controlledDiagnostics.session_manager);
  const controlledSessionManagerRunning = controlledSessionManager.running === true;
  const controlledSessionManagerStatus = stringValue(controlledSessionManager.status);
  const controlledSessionManagerUrl = stringValue(controlledSessionManager.url);
  const controlledSessionKind = stringValue(controlledDiagnostics.desktop_session_kind)
    || stringValue(controlledProvider.desktop_session_kind);
  const controlledSessionIsolated = controlledDiagnostics.desktop_session_isolated === true
    || controlledProvider.desktop_session_isolated === true;
  const controlledForegroundTakeoverRequired =
    controlledDiagnostics.foreground_takeover_required === true
    || controlledProvider.foreground_takeover_required === true;
  const controlledEndpointOrigin = stringValue(controlledDiagnostics.endpoint_origin);
  const controlledEndpointPath = stringValue(controlledDiagnostics.endpoint_path);
  const requiresRealSandbox = Boolean(tool.tool_name && requiresRealSandboxFor.includes(tool.tool_name));
  const baseState = {
    providerId,
    providerKind,
    status,
    blockingConditions,
    supportedTools,
    requiresRealSandboxFor,
    controlledProviderId,
    controlledCommand,
    controlledSmokeCommand,
    controlledEnvUrl,
    controlledRequiresApproval,
    controlledReady,
    controlledConfigured,
    controlledStatus,
    controlledReason,
    controlledBlockingConditions,
    controlledSessionManagerRunning,
    controlledSessionManagerStatus,
    controlledSessionManagerUrl,
    controlledSessionKind,
    controlledSessionIsolated,
    controlledForegroundTakeoverRequired,
    controlledEndpointOrigin,
    controlledEndpointPath,
  };
  if (ready) {
    return {
      label: 'Provider ready',
      detail: `${providerId || providerKind || 'sandbox provider'} can run this tool`,
      ready,
      supported,
      ...baseState,
    };
  }
  if (supported) {
    return {
      label: 'Provider supported',
      detail: `${providerId || providerKind || 'sandbox provider'} supports this tool but is not ready`,
      ready,
      supported,
      ...baseState,
    };
  }
  if (requiresRealSandbox) {
    return {
      label: 'Sandbox required',
      detail: controlledCommand.length
        ? `${controlledProviderId || 'controlled provider'} can be started for this keyboard or mouse action`
        : `${providerId || providerKind || 'desktop provider'} needs a real sandbox/control provider for this keyboard or mouse action`,
      ready,
      supported,
      ...baseState,
    };
  }
  return {
    label: 'Runtime path',
    detail: provider ? 'No provider route for this tool' : 'No desktop provider advertised',
    ready,
    supported,
    ...baseState,
  };
}

function normalizedRisk(tool: ToolCatalogItemSnapshot): RiskFilter {
  const risk = String(tool.risk_level || '').trim().toLowerCase();
  if (risk === 'low' || risk === 'medium' || risk === 'high') return risk;
  return 'unknown';
}

function riskLabel(tool: ToolCatalogItemSnapshot): string {
  const risk = normalizedRisk(tool);
  if (risk === 'unknown') return 'unknown';
  return risk;
}

function capabilityLabel(value: string): string {
  if (!value) return 'Unscoped';
  return value.replace(/_/g, ' ');
}

function runtimeBlockingLabel(value: string): string {
  if (value === 'desktop_session_locked') return 'desktop session locked';
  if (value === 'foreground_focus_unavailable') return 'foreground focus unavailable';
  if (value === 'screen_capture_blank') return 'screen capture blank';
  if (value === 'sandbox_keyboard_mouse_provider_required') return 'sandbox keyboard/mouse provider required';
  return value.replace(/_/g, ' ');
}

type SchemaPropertyRow = {
  name: string;
  type: string;
  description: string;
  required: boolean;
};

function toolInputSchema(tool: ToolCatalogItemSnapshot): Record<string, unknown> {
  const directSchema = objectRecord(tool.input_schema);
  if (Object.keys(directSchema).length) return directSchema;
  const modelSchema = objectRecord(tool.model_tool_schema);
  const functionSchema = objectRecord(modelSchema.function);
  return objectRecord(functionSchema.parameters);
}

function modelToolFunctionName(tool: ToolCatalogItemSnapshot): string {
  const modelSchema = objectRecord(tool.model_tool_schema);
  const functionSchema = objectRecord(modelSchema.function);
  return typeof functionSchema.name === 'string' ? functionSchema.name : '';
}

function errorMessage(error: unknown): string {
  if (error instanceof Error && error.message) return error.message;
  return 'Planner request failed';
}

function schemaPropertyRows(schema: Record<string, unknown>): SchemaPropertyRow[] {
  const properties = objectRecord(schema.properties);
  const required = new Set(stringArray(schema.required));
  return Object.entries(properties).map(([name, value]) => {
    const property = objectRecord(value);
    return {
      name,
      type: schemaPropertyType(property),
      description: typeof property.description === 'string' ? property.description : '',
      required: required.has(name),
    };
  });
}

function schemaPropertyType(property: Record<string, unknown>): string {
  const typeValue = property.type;
  if (typeof typeValue === 'string' && typeValue.trim()) return typeValue;
  if (Array.isArray(typeValue)) {
    const types = stringArray(typeValue);
    if (types.length) return types.join(' | ');
  }
  const anyOfTypes = Array.isArray(property.anyOf)
    ? property.anyOf
      .map((item) => objectRecord(item).type)
      .flatMap((item) => stringArray(Array.isArray(item) ? item : [item]))
    : [];
  if (anyOfTypes.length) return Array.from(new Set(anyOfTypes)).join(' | ');
  if (Array.isArray(property.enum) && property.enum.length) return `enum(${property.enum.length})`;
  return 'unknown';
}

function objectRecord(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
}

function stringValue(value: unknown): string {
  return String(value || '').trim();
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}
