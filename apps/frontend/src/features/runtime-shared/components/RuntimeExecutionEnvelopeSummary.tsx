import type { ReactNode } from 'react';

import type { RuntimeExecutionEnvelopeSnapshot, RuntimeExecutionRequestSnapshot } from '../types';
import {
  RuntimeRecoveryEvidencePanel,
  runtimeRecoveryActionTargetPreview,
  runtimeRecoveryEvidenceBlocker,
  runtimeRecoveryObservationEvidencePreview,
  runtimeRecoveryObservationRetryPreview,
} from './RuntimeRecoveryEvidencePanel';

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
            openQuestions={openQuestions}
            retrySummaries={retrySummaries}
            riskCounts={riskCounts}
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
          </div>
          <RuntimeExecutionEnvelopePills
            approvals={approvals}
            artifacts={artifacts}
            blockers={blockers}
            debugPillsTestId={debugPillsTestId}
            openQuestions={openQuestions}
            retrySummaries={retrySummaries}
            riskCounts={riskCounts}
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
  openQuestions,
  retrySummaries,
  riskCounts,
  stageCounts,
  tools,
  variant,
}: {
  approvals: string[];
  artifacts: string[];
  blockers: string[];
  debugPillsTestId?: string;
  openQuestions: string[];
  retrySummaries: RuntimeExecutionRetrySummary[];
  riskCounts: Array<[string, number]>;
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
  ) {
    return null;
  }
  const rowClassName = isChat ? 'yachiyo-agent-task-planner-chips' : 'studio-tool-pill-row';
  const pillClassName = isChat ? 'yachiyo-agent-task-planner-chip' : 'studio-tool-permission';
  const missingClassName = isChat ? `${pillClassName} approval` : `${pillClassName} missing`;
  return (
    <div className={rowClassName} data-testid={debugPillsTestId}>
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
  const eventIds = uniqueStrings(request.event_ids || []);
  const toolCallIds = uniqueStrings(request.tool_call_ids || []);
  const approvalIds = uniqueStrings(request.approval_ids || []);
  const artifactIds = uniqueStrings(request.artifact_ids || []);
  const artifactPaths = uniqueStrings(request.artifact_paths || []);
  const verificationEventIds = uniqueStrings(request.verification_event_ids || []);
  const verificationArtifactPaths = uniqueStrings(request.verification_artifact_paths || []);
  const eventPreview = eventIds.slice(0, 3).join(',');
  const toolCallPreview = toolCallIds.slice(0, 3).join(',');
  const approvalPreview = approvalIds.slice(0, 3).join(',');
  const artifactIdPreview = artifactIds.slice(0, 3).join(',');
  const artifactPathPreview = artifactPaths.slice(0, 3).join(',');
  const verificationEventPreview = verificationEventIds.slice(0, 3).join(',');
  const verificationArtifactPreview = verificationArtifactPaths.slice(0, 3).join(',');
  return (
    <div
      className="studio-planner-step"
      data-approval-required={String(request.approval_required === true)}
      data-execution-request-id={request.request_id}
      data-execution-tool={request.tool_name}
      data-observation-retry={observationRetryPreview}
      data-policy-reason={request.policy_reason || ''}
      data-request-approval-ids={approvalPreview}
      data-request-artifact-ids={artifactIdPreview}
      data-request-artifact-paths={artifactPathPreview}
      data-request-action-target={actionTargetPreview}
      data-request-event-ids={eventPreview}
      data-request-observation-evidence={observationEvidencePreview}
      data-request-tool-call-ids={toolCallPreview}
      data-risk-level={request.risk_level || ''}
      data-runtime-stage={request.runtime_stage || ''}
      data-verification-artifact-paths={verificationArtifactPreview}
      data-verification-event-ids={verificationEventPreview}
      data-verification-status={request.verification_status || ''}
      data-verification-step-id={request.verification_step_id || ''}
      data-testid={testId}
    >
      <div>
        <strong>{index + 1}. {request.tool_name || request.capability_id || 'runtime request'}</strong>
        <span>{request.step_id || request.capability_id || request.request_id}</span>
        {request.risk_level ? (
          <span title={request.policy_reason || undefined}>risk: {request.risk_level}</span>
        ) : null}
        {toolCallPreview ? <span>tool calls: {toolCallPreview}</span> : null}
        {approvalPreview ? <span>approvals: {approvalPreview}</span> : null}
        {eventPreview ? <span>events: {eventPreview}</span> : null}
        {artifactPathPreview ? <span>artifacts: {artifactPathPreview}</span> : null}
        {artifactIdPreview && !artifactPathPreview ? <span>artifact ids: {artifactIdPreview}</span> : null}
        {actionTargetPreview ? <span>target: {actionTargetPreview}</span> : null}
        {observationEvidencePreview ? <span>evidence: {observationEvidencePreview}</span> : null}
        {observationRetryPreview ? <span>retry: {observationRetryPreview}</span> : null}
        {request.verification_status ? (
          <span>verification: {request.verification_status}</span>
        ) : null}
        {verificationArtifactPreview ? (
          <span>artifacts: {verificationArtifactPreview}</span>
        ) : null}
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
          verificationTargets={recordList(request.task_verification_targets)}
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

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const result: string[] = [];
  values.forEach((value) => {
    const text = String(value || '').trim();
    if (text && !result.includes(text)) result.push(text);
  });
  return result;
}
