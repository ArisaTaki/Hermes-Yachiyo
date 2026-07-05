import type { RuntimeExecutionRequestSnapshot } from '../types';
import { runtimeAnchorId, runtimeAnchorSelector, type RuntimeAnchorKind } from '../runtimeAnchors';

export type RuntimeRequestReplayEvidenceSnapshot = {
  eventIds: string[];
  toolCallIds: string[];
  approvalIds: string[];
  artifactIds: string[];
  artifactPaths: string[];
  verificationEventIds: string[];
  verificationArtifactPaths: string[];
  eventPreview: string;
  toolCallPreview: string;
  approvalPreview: string;
  artifactIdPreview: string;
  artifactPathPreview: string;
  verificationEventPreview: string;
  verificationArtifactPreview: string;
  verificationStatus: string;
  verificationStepId: string;
};

type RuntimeRequestReplayEvidencePanelProps = {
  className?: string;
  evidence: RuntimeRequestReplayEvidenceSnapshot;
  testId?: string;
};

export function RuntimeRequestReplayEvidencePanel({
  className = '',
  evidence,
  testId = 'runtime-request-replay-evidence-panel',
}: RuntimeRequestReplayEvidencePanelProps) {
  const hasEvidence = Boolean(
    evidence.toolCallPreview
    || evidence.approvalPreview
    || evidence.eventPreview
    || evidence.artifactPathPreview
    || evidence.artifactIdPreview
    || evidence.verificationStatus
    || evidence.verificationStepId
    || evidence.verificationEventPreview
    || evidence.verificationArtifactPreview
  );
  if (!hasEvidence) return null;

  const classes = [
    'runtime-recovery-evidence-panel',
    'runtime-request-replay-evidence-panel',
    className,
  ].filter(Boolean).join(' ');
  return (
    <div
      className={classes}
      data-request-approval-ids={evidence.approvalPreview}
      data-request-artifact-ids={evidence.artifactIdPreview}
      data-request-artifact-paths={evidence.artifactPathPreview}
      data-request-event-ids={evidence.eventPreview}
      data-request-tool-call-ids={evidence.toolCallPreview}
      data-verification-artifact-paths={evidence.verificationArtifactPreview}
      data-verification-event-ids={evidence.verificationEventPreview}
      data-verification-status={evidence.verificationStatus}
      data-verification-step-id={evidence.verificationStepId}
      data-testid={testId}
    >
      <RuntimeRequestEvidenceTarget kind="tool-call" label="tool calls" values={evidence.toolCallIds} />
      <RuntimeRequestEvidenceTarget kind="approval" label="approvals" values={evidence.approvalIds} />
      <RuntimeRequestEvidenceTarget kind="event" label="events" values={evidence.eventIds} />
      <RuntimeRequestEvidenceTarget kind="artifact-path" label="artifacts" values={evidence.artifactPaths} />
      {!evidence.artifactPaths.length ? (
        <RuntimeRequestEvidenceTarget kind="artifact" label="artifact ids" values={evidence.artifactIds} />
      ) : null}
      {evidence.verificationStatus ? (
        <span data-runtime-request-evidence-kind="verification-status">
          verification · {evidence.verificationStatus}
        </span>
      ) : null}
      {evidence.verificationStepId ? (
        <span data-runtime-request-evidence-kind="verification-step">verified by · {evidence.verificationStepId}</span>
      ) : null}
      <RuntimeRequestEvidenceTarget
        evidenceKind="verification-event"
        kind="event"
        label="verification events"
        values={evidence.verificationEventIds}
      />
      <RuntimeRequestEvidenceTarget
        evidenceKind="verification-artifact"
        kind="artifact-path"
        label="verification artifacts"
        values={evidence.verificationArtifactPaths}
      />
    </div>
  );
}

function RuntimeRequestEvidenceTarget({
  evidenceKind,
  kind,
  label,
  values,
}: {
  evidenceKind?: string;
  kind: RuntimeAnchorKind;
  label: string;
  values: string[];
}) {
  const preview = previewIds(values);
  const primary = values[0] || '';
  if (!preview) return null;
  const targetAnchor = runtimeAnchorId(kind, primary);
  const targetSelector = runtimeAnchorSelector(kind, primary);
  return (
    <button
      type="button"
      data-runtime-request-evidence-kind={evidenceKind || kind}
      data-runtime-target-anchor={targetAnchor}
      data-runtime-target-kind={kind}
      data-runtime-target-selector={targetSelector}
      data-runtime-target-value={primary}
      onClick={() => runtimeRequestReplayNavigateToTarget(targetSelector, targetAnchor)}
      title={`Locate ${primary}`}
    >
      {label} · {preview}
    </button>
  );
}

function runtimeRequestReplayNavigateToTarget(selector: string, anchorId: string): void {
  if (typeof document === 'undefined') return;
  const target = runtimeRequestReplayTargetElement(selector, anchorId);
  if (!target) return;
  runtimeRequestReplayOpenDetails(target);
  target.setAttribute('data-runtime-anchor-active', 'true');
  target.scrollIntoView({ behavior: 'smooth', block: 'center', inline: 'nearest' });
  if (target instanceof HTMLElement) {
    if (!target.hasAttribute('tabindex')) target.setAttribute('tabindex', '-1');
    target.focus({ preventScroll: true });
  }
  window.setTimeout(() => {
    target.removeAttribute('data-runtime-anchor-active');
  }, 1600);
}

function runtimeRequestReplayTargetElement(selector: string, anchorId: string): Element | null {
  if (selector) {
    const selected = document.querySelector(selector);
    if (selected) return selected;
  }
  if (!anchorId) return null;
  return document.getElementById(anchorId);
}

function runtimeRequestReplayOpenDetails(target: Element): void {
  let current: Element | null = target;
  while (current) {
    if (current instanceof HTMLDetailsElement) current.open = true;
    current = current.parentElement;
  }
}

export function runtimeRequestReplayEvidenceFromRequest(
  request: RuntimeExecutionRequestSnapshot,
): RuntimeRequestReplayEvidenceSnapshot {
  const eventIds = uniqueStrings(request.event_ids || []);
  const toolCallIds = uniqueStrings(request.tool_call_ids || []);
  const approvalIds = uniqueStrings(request.approval_ids || []);
  const artifactIds = uniqueStrings(request.artifact_ids || []);
  const artifactPaths = uniqueStrings(request.artifact_paths || []);
  const verificationEventIds = uniqueStrings(request.verification_event_ids || []);
  const verificationArtifactPaths = uniqueStrings(request.verification_artifact_paths || []);
  return {
    eventIds,
    toolCallIds,
    approvalIds,
    artifactIds,
    artifactPaths,
    verificationEventIds,
    verificationArtifactPaths,
    eventPreview: previewIds(eventIds),
    toolCallPreview: previewIds(toolCallIds),
    approvalPreview: previewIds(approvalIds),
    artifactIdPreview: previewIds(artifactIds),
    artifactPathPreview: previewIds(artifactPaths),
    verificationEventPreview: previewIds(verificationEventIds),
    verificationArtifactPreview: previewIds(verificationArtifactPaths),
    verificationStatus: stringValue(request.verification_status),
    verificationStepId: stringValue(request.verification_step_id),
  };
}

function previewIds(values: string[]): string {
  return values.slice(0, 3).join(',');
}

function uniqueStrings(values: unknown[]): string[] {
  const result: string[] = [];
  values.forEach((value) => {
    const text = stringValue(value);
    if (text && !result.includes(text)) result.push(text);
  });
  return result;
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
