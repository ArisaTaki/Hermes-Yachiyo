import type { ReactNode } from 'react';

import type { RuntimeExecutionEnvelopeSnapshot, RuntimeExecutionRequestSnapshot } from '../types';

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
      data-request-count={requests.length}
      data-route-to-studio={envelope.route_to_studio === undefined ? '' : String(envelope.route_to_studio)}
      data-runtime-doctrine={envelope.runtime_doctrine || ''}
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
            debugPillsTestId={debugPillsTestId}
            openQuestions={openQuestions}
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
            debugPillsTestId={debugPillsTestId}
            openQuestions={openQuestions}
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
  debugPillsTestId,
  openQuestions,
  stageCounts,
  tools,
  variant,
}: {
  approvals: string[];
  artifacts: string[];
  debugPillsTestId?: string;
  openQuestions: string[];
  stageCounts: Array<[string, number]>;
  tools: string[];
  variant: RuntimeExecutionEnvelopeSummaryVariant;
}) {
  const isChat = variant === 'chat';
  if (!stageCounts.length && !tools.length && !approvals.length && !artifacts.length && !openQuestions.length) {
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
  return (
    <div
      className="studio-planner-step"
      data-approval-required={String(request.approval_required === true)}
      data-execution-request-id={request.request_id}
      data-execution-tool={request.tool_name}
      data-observation-retry={observationRetryPreview}
      data-request-action-target={actionTargetPreview}
      data-request-observation-evidence={observationEvidencePreview}
      data-runtime-stage={request.runtime_stage || ''}
      data-testid={testId}
    >
      <div>
        <strong>{index + 1}. {request.tool_name || request.capability_id || 'runtime request'}</strong>
        <span>{request.step_id || request.capability_id || request.request_id}</span>
        {actionTargetPreview ? <span>target: {actionTargetPreview}</span> : null}
        {observationEvidencePreview ? <span>evidence: {observationEvidencePreview}</span> : null}
        {observationRetryPreview ? <span>retry: {observationRetryPreview}</span> : null}
      </div>
      <small>{stage || 'operate'}{request.approval_required ? ' / approval' : ''}</small>
    </div>
  );
}

function requestActionTargetPreview(target: Record<string, unknown>): string {
  if (!Object.keys(target).length) return '';
  const label = (
    stringValue(target.target)
    || stringValue(target.label)
    || stringValue(target.name)
    || stringValue(target.title)
    || stringValue(target.text)
    || stringValue(target.role)
  );
  const app = (
    stringValue(target.app_name)
    || stringValue(target.resolved_app_name)
    || stringValue(target.app)
    || stringValue(target.bundle_id)
  );
  const query = stringValue(target.query) || stringValue(target.app_query);
  return compactPreview([
    stringValue(target.action),
    label,
    app,
    query && query !== app ? `query ${query}` : '',
  ]);
}

function requestObservationEvidencePreview(evidence: Record<string, unknown>): string {
  if (!Object.keys(evidence).length) return '';
  const source = (
    stringValue(evidence.source_tool)
    || stringValue(evidence.source)
  );
  const app = (
    stringValue(evidence.app_name)
    || stringValue(evidence.resolved_app_name)
    || stringValue(evidence.app)
  );
  const query = stringValue(evidence.query) || stringValue(evidence.app_query);
  return compactPreview([
    source,
    stringValue(evidence.strategy),
    stringValue(evidence.reason),
    app,
    query && query !== app ? `query ${query}` : '',
  ]);
}

function requestObservationRetryPreview(retry: Record<string, unknown>): string {
  if (!Object.keys(retry).length) return '';
  const retryInput = objectRecord(retry.input);
  const retryTarget = (
    stringValue(retry.target)
    || stringValue(retry.label)
    || stringValue(retry.target_label)
    || stringValue(retryInput.app_name)
    || stringValue(retryInput.query)
  );
  return compactPreview([
    stringValue(retry.from_tool) || stringValue(retry.tool) || stringValue(retry.source_tool),
    stringValue(retry.reason),
    retryTarget,
  ]);
}

function compactPreview(parts: string[]): string {
  const text = parts
    .map((part) => part.trim())
    .filter(Boolean)
    .join(' · ');
  return text.length > 120 ? `${text.slice(0, 117)}...` : text;
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function uniqueStrings(values: Array<string | null | undefined>): string[] {
  const result: string[] = [];
  values.forEach((value) => {
    const text = String(value || '').trim();
    if (text && !result.includes(text)) result.push(text);
  });
  return result;
}
