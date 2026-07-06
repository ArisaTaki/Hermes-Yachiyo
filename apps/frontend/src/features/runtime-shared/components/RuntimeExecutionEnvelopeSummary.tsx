import type { ReactNode } from 'react';

import type { RuntimeExecutionEnvelopeSnapshot, RuntimeExecutionRequestSnapshot } from '../types';
import {
  RuntimeRecoveryEvidencePanel,
  runtimeRecoveryActionTargetPreview,
  runtimeRecoveryEvidenceBlocker,
  runtimeRecoveryObservationEvidencePreview,
  runtimeRecoveryObservationRetryPreview,
} from './RuntimeRecoveryEvidencePanel';
import {
  RuntimeRequestReplayEvidencePanel,
  runtimeRequestReplayEvidenceFromRequest,
} from './RuntimeRequestReplayEvidencePanel';

export type RuntimeExecutionEnvelopeSummaryVariant = 'chat' | 'studio';

type RuntimeExecutionEnvelopeSummaryProps = {
  className?: string;
  debugPillsTestId?: string;
  envelope?: RuntimeExecutionEnvelopeSnapshot | null;
  leading?: ReactNode;
  requestListTestId?: string;
  requestLimit?: number;
  requestTestId?: string;
  showRequests?: boolean;
  sourceLabel?: string;
  testId?: string;
  title?: string;
  variant?: RuntimeExecutionEnvelopeSummaryVariant;
};

export function RuntimeExecutionEnvelopeSummary({
  className = '',
  debugPillsTestId,
  envelope,
  leading = null,
  requestListTestId,
  requestLimit,
  requestTestId,
  showRequests = false,
  sourceLabel,
  testId = 'runtime-execution-envelope-summary',
  title,
  variant = 'studio',
}: RuntimeExecutionEnvelopeSummaryProps) {
  if (!envelope) return null;

  const requests = envelope.requests || [];
  const visibleRequests = typeof requestLimit === 'number'
    ? requests.slice(0, Math.max(0, requestLimit))
    : requests;
  const stageCounts = Object.entries(envelope.runtime_stage_counts || {});
  const tools = uniqueStrings(requests.map((request) => request.tool_name).filter(Boolean));
  const approvals = uniqueStrings(envelope.approvals_required || []);
  const artifacts = uniqueStrings(envelope.artifacts_expected || []);
  const openQuestions = uniqueStrings(envelope.open_questions || []);
  const retrySummaries = runtimeExecutionRetrySummaries(requests);
  const retryTools = uniqueStrings(retrySummaries.map((retry) => retry.tool));
  const blockers = runtimeExecutionBlockers(requests);
  const riskCounts = runtimeExecutionRiskCounts(requests);
  const executionPolicy = runtimeExecutionPolicySummary(envelope.desktop_execution_policy, requests);
  const sandboxProvider = runtimeSandboxProviderSummary(envelope.sandbox_provider, requests);
  const executionRoute = runtimeExecutionRouteSummary(envelope.desktop_execution_route, requests);
  const isChat = variant === 'chat';
  const classes = [
    isChat
      ? 'runtime-execution-envelope-summary yachiyo-agent-task-planner yachiyo-agent-task-runtime-execution'
      : 'runtime-execution-envelope-summary studio-tool-inspector-section studio-runtime-execution-envelope',
    className,
  ].filter(Boolean).join(' ');

  return (
    <section
      className={classes}
      data-decision-id={envelope.decision_id || ''}
      data-envelope-id={envelope.envelope_id || ''}
      data-intent-kind={envelope.intent_kind || ''}
      data-plan-id={envelope.plan_id || ''}
      data-runtime-blockers={blockers.join(',')}
      data-desktop-execution-policy={executionPolicy.mode}
      data-desktop-execution-policy-label={executionPolicy.label}
      data-desktop-execution-policy-prefer-isolated={String(executionPolicy.preferIsolatedDesktop === true)}
      data-desktop-execution-policy-avoid-foreground-takeover={
        String(executionPolicy.avoidUserForegroundTakeover === true)
      }
      data-desktop-execution-policy-require-keyboard-mouse-sandbox={
        String(executionPolicy.requireSandboxForKeyboardMouse === true)
      }
      data-sandbox-provider-status={sandboxProvider.status}
      data-sandbox-provider-blockers={sandboxProvider.blockers.join(',')}
      data-sandbox-provider-health-status={sandboxProvider.healthStatus}
      data-sandbox-provider-launch-command={sandboxProvider.launchCommand.join(' ')}
      data-sandbox-provider-launch-provider-id={sandboxProvider.launchProviderId}
      data-sandbox-provider-controlled-command={sandboxProvider.controlledCommand.join(' ')}
      data-sandbox-provider-controlled-env-url={sandboxProvider.controlledEnvUrl}
      data-sandbox-provider-controlled-provider-id={sandboxProvider.controlledProviderId}
      data-sandbox-provider-foreground-mutation-supported={
        sandboxProvider.foregroundMutationSupported === null
          ? ''
          : String(sandboxProvider.foregroundMutationSupported)
      }
      data-sandbox-provider-keyboard-mouse-capture-supported={
        sandboxProvider.keyboardMouseCaptureSupported === null
          ? ''
          : String(sandboxProvider.keyboardMouseCaptureSupported)
      }
      data-sandbox-provider-requires-real-sandbox-for={sandboxProvider.requiresRealSandboxFor.join(',')}
      data-desktop-execution-route-status={executionRoute.status}
      data-desktop-execution-route-blockers={executionRoute.blockers.join(',')}
      data-request-count={requests.length}
      data-risk-levels={riskCounts.map(([risk, count]) => `${risk}:${count}`).join(',')}
      data-route-to-studio={envelope.route_to_studio === undefined ? '' : String(envelope.route_to_studio)}
      data-runtime-doctrine={envelope.runtime_doctrine || ''}
      data-runtime-retry-count={retrySummaries.length}
      data-runtime-retry-tools={retryTools.join(',')}
      data-runtime-stages={stageCounts.map(([stage, count]) => `${stage}:${count}`).join(',')}
      data-testid={testId}
    >
      {leading}
      {isChat ? (
        <div className="yachiyo-agent-task-planner-body">
          <div className="yachiyo-agent-task-planner-head">
            <strong>{title || 'Runtime execution'}</strong>
            <span>{requests.length} requests · {sourceLabel || envelope.runtime_doctrine || envelope.intent_kind || 'planner'}</span>
          </div>
          <RuntimeExecutionEnvelopePills
            approvals={approvals}
            artifacts={artifacts}
            blockers={blockers}
            debugPillsTestId={debugPillsTestId}
            executionRoute={executionRoute}
            executionPolicy={executionPolicy}
            openQuestions={openQuestions}
            retrySummaries={retrySummaries}
            riskCounts={riskCounts}
            sandboxProvider={sandboxProvider}
            stageCounts={stageCounts}
            tools={tools}
            variant={variant}
          />
        </div>
      ) : (
        <>
          <div className="studio-tool-inspector-heading">
            <h3>{title || 'Runtime Execution Envelope'}</h3>
            <span>{sourceLabel || envelope.runtime_doctrine || envelope.source || 'discover / operate / verify'}</span>
          </div>
          <div className="studio-tool-detail-grid">
            <span>
              <small>Envelope</small>
              <strong>{envelope.envelope_id || 'pending'}</strong>
            </span>
            <span>
              <small>Intent</small>
              <strong>{envelope.intent_kind || 'unknown'}</strong>
            </span>
            <span>
              <small>Requests</small>
              <strong>{requests.length}</strong>
            </span>
            <span>
              <small>Route</small>
              <strong>{envelope.route_to_studio ? 'Studio' : 'Direct'}</strong>
            </span>
            <span>
              <small>Execution</small>
              <strong>{executionPolicy.label || 'Default'}</strong>
            </span>
            <span>
              <small>Sandbox</small>
              <strong>{sandboxProvider.label || 'Not needed'}</strong>
            </span>
            <span>
              <small>Provider</small>
              <strong>{executionRoute.label || 'Default'}</strong>
            </span>
          </div>
          <RuntimeExecutionEnvelopePills
            approvals={approvals}
            artifacts={artifacts}
            blockers={blockers}
            debugPillsTestId={debugPillsTestId}
            executionRoute={executionRoute}
            executionPolicy={executionPolicy}
            openQuestions={openQuestions}
            retrySummaries={retrySummaries}
            riskCounts={riskCounts}
            sandboxProvider={sandboxProvider}
            stageCounts={stageCounts}
            tools={tools}
            variant={variant}
          />
          {showRequests ? (
            <div className="studio-planner-step-list" data-testid={requestListTestId || `${testId}-requests`}>
              {visibleRequests.map((request, index) => (
                <RuntimeExecutionRequestRow
                  index={index}
                  key={request.request_id || `${request.tool_name}-${index}`}
                  request={request}
                  testId={requestTestId || `${testId}-request`}
                />
              ))}
              {requests.length > visibleRequests.length ? (
                <span className="studio-tool-empty">+{requests.length - visibleRequests.length} requests</span>
              ) : null}
              {!requests.length ? <span className="studio-tool-empty">No execution requests</span> : null}
            </div>
          ) : null}
        </>
      )}
    </section>
  );
}

function RuntimeExecutionEnvelopePills({
  approvals,
  artifacts,
  blockers,
  debugPillsTestId,
  executionRoute,
  executionPolicy,
  openQuestions,
  retrySummaries,
  riskCounts,
  sandboxProvider,
  stageCounts,
  tools,
  variant,
}: {
  approvals: string[];
  artifacts: string[];
  blockers: string[];
  debugPillsTestId?: string;
  executionRoute: RuntimeExecutionRouteSummary;
  executionPolicy: RuntimeExecutionPolicySummary;
  openQuestions: string[];
  retrySummaries: RuntimeExecutionRetrySummary[];
  riskCounts: Array<[string, number]>;
  sandboxProvider: RuntimeSandboxProviderSummary;
  stageCounts: Array<[string, number]>;
  tools: string[];
  variant: RuntimeExecutionEnvelopeSummaryVariant;
}) {
  const isChat = variant === 'chat';
  if (
    !stageCounts.length
    && !tools.length
    && !approvals.length
    && !artifacts.length
    && !openQuestions.length
    && !retrySummaries.length
    && !riskCounts.length
    && !blockers.length
    && !executionRoute.status
    && !sandboxProvider.status
    && !sandboxProvider.healthStatus
    && !sandboxProvider.launchCommand.length
    && !sandboxProvider.controlledCommand.length
    && !executionPolicy.mode
  ) {
    return null;
  }
  const rowClassName = isChat ? 'yachiyo-agent-task-planner-chips' : 'studio-tool-pill-row';
  const pillClassName = isChat ? 'yachiyo-agent-task-planner-chip' : 'studio-tool-permission';
  const missingClassName = isChat ? `${pillClassName} approval` : `${pillClassName} missing`;
  return (
    <div className={rowClassName} data-testid={debugPillsTestId}>
      {executionPolicy.mode ? (
        <span
          className={pillClassName}
          data-desktop-execution-policy={executionPolicy.mode}
          data-desktop-execution-policy-prefer-isolated={String(
            executionPolicy.preferIsolatedDesktop === true,
          )}
          data-desktop-execution-policy-avoid-foreground-takeover={String(
            executionPolicy.avoidUserForegroundTakeover === true,
          )}
          data-desktop-execution-policy-require-keyboard-mouse-sandbox={String(
            executionPolicy.requireSandboxForKeyboardMouse === true,
          )}
          title={executionPolicy.reason || undefined}
        >
          execution · {executionPolicy.label}
        </span>
      ) : null}
      {executionRoute.status ? (
        <span
          className={executionRoute.canExecute ? pillClassName : missingClassName}
          data-desktop-execution-route-status={executionRoute.status}
          title={executionRoute.reason || undefined}
        >
          route · {executionRoute.label}
        </span>
      ) : null}
      {sandboxProvider.status ? (
        <span
          className={sandboxProvider.available ? pillClassName : missingClassName}
          data-sandbox-provider-status={sandboxProvider.status}
          title={sandboxProvider.reason || undefined}
        >
          sandbox · {sandboxProvider.label}
        </span>
      ) : null}
      {sandboxProvider.healthStatus ? (
        <span
          className={sandboxProvider.healthOk === false ? missingClassName : pillClassName}
          data-sandbox-provider-health-status={sandboxProvider.healthStatus}
          data-sandbox-provider-health-checked={String(sandboxProvider.healthChecked === true)}
          title={sandboxProvider.healthEndpoint || sandboxProvider.healthBlockers[0] || undefined}
        >
          health · {sandboxProvider.healthLabel}
        </span>
      ) : null}
      {sandboxProvider.launchCommand.length ? (
        <span
          className={missingClassName}
          data-sandbox-provider-launch-command={sandboxProvider.launchCommand.join(' ')}
          data-sandbox-provider-launch-provider-id={sandboxProvider.launchProviderId}
          data-sandbox-provider-launch-env-url={sandboxProvider.launchEnvUrl}
          data-sandbox-provider-foreground-mutation-supported={
            sandboxProvider.foregroundMutationSupported === null
              ? ''
              : String(sandboxProvider.foregroundMutationSupported)
          }
          title={sandboxProvider.launchCommand.join(' ')}
        >
          launch · {sandboxProvider.launchLabel}
        </span>
      ) : null}
      {sandboxProvider.controlledCommand.length ? (
        <span
          className={missingClassName}
          data-sandbox-provider-controlled-command={sandboxProvider.controlledCommand.join(' ')}
          data-sandbox-provider-controlled-env-url={sandboxProvider.controlledEnvUrl}
          data-sandbox-provider-controlled-provider-id={sandboxProvider.controlledProviderId}
          data-sandbox-provider-controlled-smoke-command={sandboxProvider.controlledSmokeCommand.join(' ')}
          title={sandboxProvider.controlledCommand.join(' ')}
        >
          control · {sandboxProvider.controlledLabel}
        </span>
      ) : null}
      {stageCounts.map(([stage, count]) => (
        <span className={pillClassName} data-runtime-stage={stage} key={`stage:${stage}`}>
          {isChat ? `${stage} · ${count}` : `stage · ${stage}: ${count}`}
        </span>
      ))}
      {tools.slice(0, isChat ? 5 : 8).map((toolName) => (
        <span className={pillClassName} data-runtime-tool={toolName} key={`tool:${toolName}`}>
          {isChat ? toolName : `tool · ${toolName}`}
        </span>
      ))}
      {riskCounts.slice(0, isChat ? 2 : 4).map(([risk, count]) => (
        <span className={pillClassName} data-runtime-risk={risk} key={`risk:${risk}`}>
          {isChat ? `risk · ${risk}:${count}` : `risk · ${risk}: ${count}`}
        </span>
      ))}
      {isChat && approvals.length ? (
        <span className={missingClassName} data-runtime-approvals={approvals.join(',')}>
          approval · {approvals.length}
        </span>
      ) : null}
      {!isChat ? approvals.map((approval) => (
        <span className={missingClassName} data-execution-approval={approval} key={`approval:${approval}`}>
          approval · {approval}
        </span>
      )) : null}
      {isChat && artifacts.length ? (
        <span className={pillClassName} data-runtime-artifacts={artifacts.join(',')}>
          artifact · {artifacts.length}
        </span>
      ) : null}
      {isChat && retrySummaries.length ? (
        <span
          className={pillClassName}
          data-runtime-retry-count={retrySummaries.length}
          data-runtime-retry-tools={uniqueStrings(retrySummaries.map((retry) => retry.tool)).join(',')}
        >
          retry · {retrySummaries.length}
        </span>
      ) : null}
      {!isChat ? retrySummaries.slice(0, 8).map((retry, index) => (
        <span
          className={pillClassName}
          data-runtime-retry-reason={retry.reason}
          data-runtime-retry-target={retry.target}
          data-runtime-retry-tool={retry.tool}
          key={`retry:${retry.tool}:${retry.reason}:${retry.target}:${index}`}
        >
          retry · {retryPreviewLabel(retry)}
        </span>
      )) : null}
      {isChat && blockers.length ? (
        <span className={missingClassName} data-runtime-blockers={blockers.join(',')}>
          blocker · {blockers.length}
        </span>
      ) : null}
      {!isChat ? blockers.map((blocker) => (
        <span className={missingClassName} data-runtime-blocker={blocker} key={`blocker:${blocker}`}>
          blocker · {blocker}
        </span>
      )) : null}
      {!isChat ? artifacts.map((artifact) => (
        <span className={pillClassName} data-execution-artifact={artifact} key={`artifact:${artifact}`}>
          artifact · {artifact}
        </span>
      )) : null}
      {!isChat ? openQuestions.map((question) => (
        <span className={missingClassName} data-execution-open-question={question} key={`question:${question}`}>
          question · {question}
        </span>
      )) : null}
    </div>
  );
}

function RuntimeExecutionRequestRow({
  index,
  request,
  testId,
}: {
  index: number;
  request: RuntimeExecutionRequestSnapshot;
  testId: string;
}) {
  const stage = request.runtime_stage || request.runtime_role || request.capability_id || '';
  const actionTargetPreview = requestActionTargetPreview(objectRecord(request.action_target));
  const observationEvidencePreview = requestObservationEvidencePreview(objectRecord(request.observation_evidence));
  const observationRetryPreview = requestObservationRetryPreview(objectRecord(request.observation_retry));
  const replayEvidence = runtimeRequestReplayEvidenceFromRequest(request);
  const executionPolicy = runtimeExecutionPolicySummary(request.desktop_execution_policy);
  const sandboxProvider = runtimeSandboxProviderSummary(request.sandbox_provider);
  const executionRoute = runtimeExecutionRouteSummary(request.desktop_execution_route);
  return (
    <div
      className="studio-planner-step"
      data-approval-required={String(request.approval_required === true)}
      data-execution-request-id={request.request_id}
      data-execution-tool={request.tool_name}
      data-desktop-execution-policy={executionPolicy.mode}
      data-desktop-execution-policy-prefer-isolated={String(executionPolicy.preferIsolatedDesktop === true)}
      data-desktop-execution-policy-avoid-foreground-takeover={
        String(executionPolicy.avoidUserForegroundTakeover === true)
      }
      data-desktop-execution-policy-require-keyboard-mouse-sandbox={
        String(executionPolicy.requireSandboxForKeyboardMouse === true)
      }
      data-sandbox-provider-status={sandboxProvider.status}
      data-sandbox-provider-blockers={sandboxProvider.blockers.join(',')}
      data-sandbox-provider-health-status={sandboxProvider.healthStatus}
      data-sandbox-provider-launch-command={sandboxProvider.launchCommand.join(' ')}
      data-desktop-execution-route-status={executionRoute.status}
      data-desktop-execution-route-blockers={executionRoute.blockers.join(',')}
      data-observation-retry={observationRetryPreview}
      data-policy-reason={request.policy_reason || ''}
      data-request-approval-ids={replayEvidence.approvalPreview}
      data-request-artifact-ids={replayEvidence.artifactIdPreview}
      data-request-artifact-paths={replayEvidence.artifactPathPreview}
      data-request-action-target={actionTargetPreview}
      data-request-event-ids={replayEvidence.eventPreview}
      data-request-observation-evidence={observationEvidencePreview}
      data-request-tool-call-ids={replayEvidence.toolCallPreview}
      data-risk-level={request.risk_level || ''}
      data-runtime-stage={request.runtime_stage || ''}
      data-verification-artifact-paths={replayEvidence.verificationArtifactPreview}
      data-verification-event-ids={replayEvidence.verificationEventPreview}
      data-verification-status={replayEvidence.verificationStatus}
      data-verification-step-id={replayEvidence.verificationStepId}
      data-testid={testId}
    >
      <div>
        <strong>{index + 1}. {request.tool_name || request.capability_id || 'runtime request'}</strong>
        <span>{request.step_id || request.capability_id || request.request_id}</span>
        {request.risk_level ? (
          <span title={request.policy_reason || undefined}>risk: {request.risk_level}</span>
        ) : null}
        {executionPolicy.mode ? (
          <span title={executionPolicy.reason || undefined}>execution: {executionPolicy.label}</span>
        ) : null}
        {sandboxProvider.status ? (
          <span title={sandboxProvider.reason || undefined}>sandbox: {sandboxProvider.label}</span>
        ) : null}
        {sandboxProvider.healthStatus ? (
          <span title={sandboxProvider.healthEndpoint || undefined}>health: {sandboxProvider.healthLabel}</span>
        ) : null}
        {sandboxProvider.launchCommand.length ? (
          <span title={sandboxProvider.launchCommand.join(' ')}>launch: {sandboxProvider.launchLabel}</span>
        ) : null}
        {executionRoute.status ? (
          <span title={executionRoute.reason || undefined}>route: {executionRoute.label}</span>
        ) : null}
        <RuntimeRequestReplayEvidencePanel
          className="runtime-execution-request-replay-evidence"
          evidence={replayEvidence}
          testId={`${testId}-replay-evidence`}
        />
        {actionTargetPreview ? <span>target: {actionTargetPreview}</span> : null}
        {observationEvidencePreview ? <span>evidence: {observationEvidencePreview}</span> : null}
        {observationRetryPreview ? <span>retry: {observationRetryPreview}</span> : null}
        <RuntimeRecoveryEvidencePanel
          actionTarget={objectRecord(request.action_target)}
          approvalRequired={request.approval_required === true}
          className="runtime-execution-request-evidence"
          input={objectRecord(request.input)}
          observationEvidence={objectRecord(request.observation_evidence)}
          observationRetry={objectRecord(request.observation_retry)}
          permissionTarget={request.approval_required ? 'approval_required' : ''}
          planningReason={request.planning_reason || ''}
          riskLevel={request.risk_level || ''}
          status={request.status || ''}
          testId={`${testId}-evidence`}
          tool={request.tool_name || ''}
          verificationTargets={mergeRecordLists(
            recordList(request.verification_targets),
            recordList(request.task_verification_targets),
          )}
        />
      </div>
      <small>{stage || 'operate'}{request.approval_required ? ' / approval' : ''}</small>
    </div>
  );
}

function requestActionTargetPreview(target: Record<string, unknown>): string {
  return runtimeRecoveryActionTargetPreview(target);
}

function requestObservationEvidencePreview(evidence: Record<string, unknown>): string {
  return runtimeRecoveryObservationEvidencePreview(evidence);
}

function requestObservationRetryPreview(retry: Record<string, unknown>): string {
  return runtimeRecoveryObservationRetryPreview(retry);
}

function compactPreview(parts: string[]): string {
  const text = parts
    .map((part) => part.trim())
    .filter(Boolean)
    .join(' · ');
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

type RuntimeExecutionRetrySummary = {
  reason: string;
  target: string;
  tool: string;
};

type RuntimeExecutionPolicySummary = {
  allowLiveForeground: boolean | null;
  allowMediaControl: boolean | null;
  avoidUserForegroundTakeover: boolean | null;
  label: string;
  mode: string;
  preferIsolatedDesktop: boolean | null;
  reason: string;
  requireSandboxForKeyboardMouse: boolean | null;
  source: string;
};

type RuntimeExecutionRouteSummary = {
  blockers: string[];
  canAutoStart: boolean | null;
  canExecute: boolean | null;
  fallbackMode: string;
  label: string;
  providerId: string;
  providerKind: string;
  reason: string;
  requestedMode: string;
  sandboxRequired: boolean | null;
  status: string;
};

type RuntimeSandboxProviderSummary = {
  available: boolean;
  blockers: string[];
  controlledCommand: string[];
  controlledEnvUrl: string;
  controlledLabel: string;
  controlledProviderId: string;
  controlledSmokeCommand: string[];
  foregroundMutationSupported: boolean | null;
  keyboardMouseCaptureSupported: boolean | null;
  healthBlockers: string[];
  healthChecked: boolean | null;
  healthEndpoint: string;
  healthLabel: string;
  healthOk: boolean | null;
  healthStatus: string;
  launchCommand: string[];
  launchEnvUrl: string;
  launchLabel: string;
  launchProviderId: string;
  label: string;
  providerId: string;
  providerKind: string;
  reason: string;
  requiresRealSandboxFor: string[];
  status: string;
};

function runtimeExecutionPolicySummary(
  policy: unknown,
  requests: RuntimeExecutionRequestSnapshot[] = [],
): RuntimeExecutionPolicySummary {
  let record = objectRecord(policy);
  if (!Object.keys(record).length) {
    const requestPolicy = requests
      .map((request) => objectRecord(request.desktop_execution_policy))
      .find((candidate) => Object.keys(candidate).length > 0);
    record = requestPolicy || {};
  }
  const mode = stringValue(record.mode);
  const source = stringValue(record.source);
  const reason = stringValue(record.reason);
  const allowLiveForeground = booleanValue(record.allow_live_foreground);
  const allowMediaControl = booleanValue(record.allow_media_control);
  const preferIsolatedDesktop = booleanValue(record.prefer_isolated_desktop);
  const avoidUserForegroundTakeover = booleanValue(record.avoid_user_foreground_takeover);
  const requireSandboxForKeyboardMouse = booleanValue(record.require_sandbox_for_keyboard_mouse);
  return {
    allowLiveForeground,
    allowMediaControl,
    avoidUserForegroundTakeover,
    label: executionPolicyLabel({
      allowLiveForeground,
      allowMediaControl,
      avoidUserForegroundTakeover,
      mode,
      preferIsolatedDesktop,
      requireSandboxForKeyboardMouse,
      source,
    }),
    mode,
    preferIsolatedDesktop,
    reason,
    requireSandboxForKeyboardMouse,
    source,
  };
}

function runtimeExecutionRouteSummary(
  route: unknown,
  requests: RuntimeExecutionRequestSnapshot[] = [],
): RuntimeExecutionRouteSummary {
  let record = objectRecord(route);
  if (!Object.keys(record).length) {
    const requestRoute = requests
      .map((request) => objectRecord(request.desktop_execution_route))
      .find((candidate) => Object.keys(candidate).length > 0);
    record = requestRoute || {};
  }
  const status = stringValue(record.status);
  const providerKind = stringValue(record.selected_provider_kind);
  const providerId = stringValue(record.selected_provider_id);
  const requestedMode = stringValue(record.requested_mode);
  const fallbackMode = stringValue(record.fallback_mode);
  const canExecute = booleanValue(record.can_execute);
  const canAutoStart = booleanValue(record.can_auto_start);
  const sandboxRequired = booleanValue(record.sandbox_required);
  const reason = stringValue(record.reason);
  const blockers = stringArray(record.blocking_conditions);
  return {
    blockers,
    canAutoStart,
    canExecute,
    fallbackMode,
    label: executionRouteLabel({
      blockers,
      canExecute,
      fallbackMode,
      providerId,
      providerKind,
      requestedMode,
      status,
    }),
    providerId,
    providerKind,
    reason,
    requestedMode,
    sandboxRequired,
    status,
  };
}

function executionRouteLabel(route: {
  blockers: string[];
  canExecute: boolean | null;
  fallbackMode: string;
  providerId: string;
  providerKind: string;
  requestedMode: string;
  status: string;
}): string {
  if (!route.status && !route.providerKind && !route.blockers.length) return '';
  return compactPreview([
    route.status,
    route.canExecute === false ? route.blockers[0] : '',
    route.providerId || route.providerKind,
    route.fallbackMode ? `fallback ${route.fallbackMode}` : '',
    route.requestedMode,
  ]);
}

function runtimeSandboxProviderSummary(
  provider: unknown,
  requests: RuntimeExecutionRequestSnapshot[] = [],
): RuntimeSandboxProviderSummary {
  let record = objectRecord(provider);
  if (!Object.keys(record).length) {
    const requestProvider = requests
      .map((request) => objectRecord(request.sandbox_provider))
      .find((candidate) => Object.keys(candidate).length > 0);
    record = requestProvider || {};
  }
  const status = stringValue(record.status);
  const available = booleanValue(record.available) === true;
  const providerId = stringValue(record.provider_id);
  const providerKind = stringValue(record.provider_kind);
  const reason = stringValue(record.reason);
  const blockers = stringArray(record.blocking_conditions);
  const health = objectRecord(record.health);
  const healthStatus = stringValue(health.status);
  const healthOk = booleanValue(health.ok);
  const healthChecked = booleanValue(health.checked);
  const healthBlockers = stringArray(health.blocking_conditions);
  const healthEndpoint = compactPreview([
    stringValue(health.endpoint_origin),
    stringValue(health.endpoint_path),
  ]);
  const launchHint = objectRecord(record.launch_hint);
  const launchCommand = stringArray(launchHint.command);
  const launchEnv = objectRecord(launchHint.env);
  const controlledProvider = objectRecord(launchHint.controlled_provider);
  const controlledCommand = stringArray(controlledProvider.command);
  const controlledSmokeCommand = stringArray(controlledProvider.smoke_command);
  const controlledEnv = objectRecord(controlledProvider.env);
  const controlledProviderId = stringValue(controlledProvider.provider_id);
  const controlledEnvUrl = stringValue(controlledEnv.OHA_YACHIYO_DESKTOP_PROVIDER_URL);
  const launchProviderId = stringValue(launchHint.provider_id) || providerId;
  const launchEnvUrl = stringValue(launchEnv.OHA_YACHIYO_DESKTOP_PROVIDER_URL);
  const foregroundMutationSupported = booleanValue(record.foreground_mutation_supported)
    ?? booleanValue(launchHint.foreground_mutation_supported);
  const keyboardMouseCaptureSupported = booleanValue(record.keyboard_mouse_capture_supported);
  const requiresRealSandboxFor = uniqueStrings([
    ...stringArray(record.requires_real_sandbox_for),
    ...stringArray(launchHint.requires_real_sandbox_for),
  ]);
  return {
    available,
    blockers,
    controlledCommand,
    controlledEnvUrl,
    controlledLabel: sandboxProviderLaunchLabel({
      command: controlledCommand,
      foregroundMutationSupported: booleanValue(controlledProvider.foreground_mutation_supported),
      providerId: controlledProviderId,
      requiresRealSandboxFor: [],
    }),
    controlledProviderId,
    controlledSmokeCommand,
    foregroundMutationSupported,
    keyboardMouseCaptureSupported,
    healthBlockers,
    healthChecked,
    healthEndpoint,
    healthLabel: sandboxProviderHealthLabel({
      blockers: healthBlockers,
      checked: healthChecked,
      ok: healthOk,
      status: healthStatus,
    }),
    healthOk,
    healthStatus,
    launchCommand,
    launchEnvUrl,
    launchLabel: sandboxProviderLaunchLabel({
      command: launchCommand,
      foregroundMutationSupported,
      providerId: launchProviderId,
      requiresRealSandboxFor,
    }),
    launchProviderId,
    label: sandboxProviderLabel({ available, blockers, providerId, providerKind, status }),
    providerId,
    providerKind,
    reason,
    requiresRealSandboxFor,
    status,
  };
}

function sandboxProviderLabel(provider: {
  available: boolean;
  blockers: string[];
  providerId: string;
  providerKind: string;
  status: string;
}): string {
  if (!provider.status && !provider.providerId && !provider.providerKind && !provider.blockers.length) return '';
  if (provider.available) {
    return compactPreview([
      provider.status || 'available',
      provider.providerId || provider.providerKind,
    ]);
  }
  return compactPreview([
    provider.status || 'blocked',
    provider.blockers[0],
    provider.providerKind,
  ]);
}

function sandboxProviderHealthLabel(health: {
  blockers: string[];
  checked: boolean | null;
  ok: boolean | null;
  status: string;
}): string {
  if (!health.status && !health.blockers.length) return '';
  return compactPreview([
    health.status || (health.ok ? 'healthy' : 'not checked'),
    health.checked === false ? 'unchecked' : '',
    health.ok === false ? health.blockers[0] : '',
  ]);
}

function sandboxProviderLaunchLabel(launch: {
  command: string[];
  foregroundMutationSupported: boolean | null;
  providerId: string;
  requiresRealSandboxFor: string[];
}): string {
  if (!launch.command.length && !launch.providerId) return '';
  return compactPreview([
    launch.providerId,
    launch.command.slice(0, 2).join(' '),
    launch.foregroundMutationSupported === false ? 'read-only' : '',
    launch.requiresRealSandboxFor.length ? `needs sandbox for ${launch.requiresRealSandboxFor.slice(0, 2).join('/')}` : '',
  ]);
}

function executionPolicyLabel(policy: {
  allowLiveForeground: boolean | null;
  allowMediaControl: boolean | null;
  avoidUserForegroundTakeover: boolean | null;
  mode: string;
  preferIsolatedDesktop: boolean | null;
  requireSandboxForKeyboardMouse: boolean | null;
  source: string;
}): string {
  if (!policy.mode) return '';
  const parts = [policy.mode.replace(/_/g, ' ')];
  if (policy.allowLiveForeground === true) parts.push('live foreground');
  if (policy.preferIsolatedDesktop === true) parts.push('isolated preferred');
  if (policy.avoidUserForegroundTakeover === true) parts.push('no takeover');
  if (policy.requireSandboxForKeyboardMouse === true) parts.push('keyboard/mouse sandbox');
  if (policy.allowMediaControl === true) parts.push('media ok');
  if (policy.allowMediaControl === false) parts.push('media blocked');
  if (policy.source) parts.push(policy.source);
  return compactPreview(parts);
}

function runtimeExecutionRetrySummaries(
  requests: RuntimeExecutionRequestSnapshot[],
): RuntimeExecutionRetrySummary[] {
  const summaries: RuntimeExecutionRetrySummary[] = [];
  requests.forEach((request) => {
    const retry = objectRecord(request.observation_retry);
    if (!Object.keys(retry).length) return;
    const retryInput = objectRecord(retry.input);
    const tool = stringValue(retry.tool) || stringValue(retry.from_tool) || stringValue(request.tool_name);
    if (!tool) return;
    summaries.push({
      reason: stringValue(retry.reason),
      target: (
        stringValue(retry.target)
        || stringValue(retry.label)
        || stringValue(retryInput.app_name)
        || stringValue(retryInput.query)
      ),
      tool,
    });
  });
  return summaries;
}

function runtimeExecutionBlockers(requests: RuntimeExecutionRequestSnapshot[]): string[] {
  const values: string[] = [];
  requests.forEach((request) => {
    const evidence = objectRecord(request.observation_evidence);
    addUniqueString(values, stringValue(evidence.blocking_condition));
    addUniqueString(values, runtimeRecoveryEvidenceBlocker(evidence));
    const conditions = evidence.blocking_conditions;
    if (Array.isArray(conditions)) {
      conditions.forEach((condition) => addUniqueString(values, condition));
    }
  });
  return values;
}

function runtimeExecutionRiskCounts(
  requests: RuntimeExecutionRequestSnapshot[],
): Array<[string, number]> {
  const counts = new Map<string, number>();
  requests.forEach((request) => {
    const risk = stringValue(request.risk_level);
    if (!risk) return;
    counts.set(risk, (counts.get(risk) || 0) + 1);
  });
  return ['high', 'medium', 'low']
    .map((risk): [string, number] => [risk, counts.get(risk) || 0])
    .filter(([, count]) => count > 0);
}

function retryPreviewLabel(retry: RuntimeExecutionRetrySummary): string {
  return compactPreview([
    retry.tool,
    retry.reason,
    retry.target,
  ]);
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function booleanValue(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function stringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return uniqueStrings(value.map((item) => String(item || '').trim()));
}

function addUniqueString(values: string[], value: unknown): void {
  const text = stringValue(value);
  if (text && !values.includes(text)) values.push(text);
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => (
    Boolean(item) && typeof item === 'object' && !Array.isArray(item)
  ));
}

function mergeRecordLists(
  ...lists: Array<Array<Record<string, unknown>> | undefined>
): Array<Record<string, unknown>> {
  const records: Array<Record<string, unknown>> = [];
  const seen = new Set<string>();
  lists.forEach((list) => {
    (list || []).forEach((record) => {
      const key = JSON.stringify(record);
      if (seen.has(key)) return;
      seen.add(key);
      records.push(record);
    });
  });
  return records;
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const result: string[] = [];
  values.forEach((value) => {
    const text = String(value || '').trim();
    if (text && !result.includes(text)) result.push(text);
  });
  return result;
}
