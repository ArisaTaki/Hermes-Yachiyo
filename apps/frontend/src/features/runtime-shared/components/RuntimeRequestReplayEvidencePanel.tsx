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
      {evidence.verificationEventPreview ? (
        <span data-runtime-request-evidence-kind="verification-event">
          verification events · {evidence.verificationEventPreview}
        </span>
      ) : null}
      {evidence.verificationArtifactPreview ? (
        <span data-runtime-request-evidence-kind="verification-artifact">
          verification artifacts · {evidence.verificationArtifactPreview}
        </span>
      ) : null}
    </div>
  );
}

function RuntimeRequestEvidenceTarget({
  kind,
  label,
  values,
}: {
  kind: RuntimeAnchorKind;
  label: string;
  values: string[];
}) {
  const preview = previewIds(values);
  const primary = values[0] || '';
  if (!preview) return null;
  return (
    <span
      data-runtime-request-evidence-kind={kind}
      data-runtime-target-anchor={runtimeAnchorId(kind, primary)}
      data-runtime-target-kind={kind}
      data-runtime-target-selector={runtimeAnchorSelector(kind, primary)}
      data-runtime-target-value={primary}
    >
      {label} · {preview}
    </span>
  );
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
