type RuntimeRecoveryEvidencePanelProps = {
  actionTarget?: Record<string, unknown> | null;
  approvalRequired?: boolean;
  className?: string;
  input?: Record<string, unknown> | null;
  observationEvidence?: Record<string, unknown> | null;
  observationRetry?: Record<string, unknown> | null;
  permissionTarget?: string | null;
  planningReason?: string | null;
  riskLevel?: string | null;
  status?: string | null;
  testId?: string;
  tool?: string | null;
  verificationTargets?: Array<Record<string, unknown>> | null;
};

export function RuntimeRecoveryEvidencePanel({
  actionTarget,
  approvalRequired = false,
  className = '',
  input,
  observationEvidence,
  observationRetry,
  permissionTarget,
  planningReason,
  riskLevel,
  status,
  testId = 'runtime-recovery-evidence-panel',
  tool,
  verificationTargets,
}: RuntimeRecoveryEvidencePanelProps) {
  const target = objectRecord(actionTarget);
  const evidence = objectRecord(observationEvidence);
  const retry = objectRecord(observationRetry);
  const inputRecord = objectRecord(input);
  const targets = Array.isArray(verificationTargets) ? verificationTargets : [];
  const targetPreview = runtimeRecoveryActionTargetPreview(target);
  const evidencePreview = runtimeRecoveryObservationEvidencePreview(evidence);
  const retryPreview = runtimeRecoveryObservationRetryPreview(retry);
  const verificationPreview = runtimeRecoveryVerificationTargetsPreview(targets);
  const inputPreview = runtimeRecoveryValuePreview(inputRecord);
  const blocker = runtimeRecoveryEvidenceBlocker(evidence);
  const cleanPermission = stringValue(permissionTarget);
  const cleanRisk = stringValue(riskLevel);
  const cleanTool = stringValue(tool);
  const cleanStatus = stringValue(status);
  const cleanReason = stringValue(planningReason);
  const hasEvidence = Boolean(
    cleanTool
    || cleanStatus
    || cleanReason
    || cleanPermission
    || cleanRisk
    || approvalRequired
    || inputPreview
    || targetPreview
    || evidencePreview
    || retryPreview
    || verificationPreview
    || blocker
  );
  if (!hasEvidence) return null;

  const classes = [
    'runtime-recovery-evidence-panel',
    className,
  ].filter(Boolean).join(' ');
  return (
    <div
      className={classes}
      data-runtime-recovery-action-target={targetPreview}
      data-runtime-recovery-approval-required={String(approvalRequired)}
      data-runtime-recovery-blocker={blocker}
      data-runtime-recovery-input={inputPreview}
      data-runtime-recovery-observation-evidence={evidencePreview}
      data-runtime-recovery-observation-retry={retryPreview}
      data-runtime-recovery-permission-target={cleanPermission}
      data-runtime-recovery-planning-reason={cleanReason}
      data-runtime-recovery-risk={cleanRisk}
      data-runtime-recovery-status={cleanStatus}
      data-runtime-recovery-tool={cleanTool}
      data-runtime-recovery-verification-targets={verificationPreview}
      data-testid={testId}
    >
      {cleanTool ? <span data-runtime-recovery-evidence-kind="tool">tool · {cleanTool}</span> : null}
      {cleanStatus ? <span data-runtime-recovery-evidence-kind="status">status · {cleanStatus}</span> : null}
      {cleanReason ? <span data-runtime-recovery-evidence-kind="reason">reason · {cleanReason}</span> : null}
      {cleanPermission ? <span data-runtime-recovery-evidence-kind="permission">permission · {cleanPermission}</span> : null}
      {cleanRisk || approvalRequired ? (
        <span data-runtime-recovery-evidence-kind="risk">
          risk · {[cleanRisk, approvalRequired ? 'approval' : ''].filter(Boolean).join(' / ')}
        </span>
      ) : null}
      {blocker ? <span className="missing" data-runtime-recovery-evidence-kind="blocker">blocker · {blocker}</span> : null}
      {inputPreview ? <span data-runtime-recovery-evidence-kind="input">input · {inputPreview}</span> : null}
      {targetPreview ? <span data-runtime-recovery-evidence-kind="target">target · {targetPreview}</span> : null}
      {evidencePreview ? <span data-runtime-recovery-evidence-kind="evidence">evidence · {evidencePreview}</span> : null}
      {retryPreview ? <span data-runtime-recovery-evidence-kind="retry">retry · {retryPreview}</span> : null}
      {verificationPreview ? (
        <span data-runtime-recovery-evidence-kind="verification">verifies · {verificationPreview}</span>
      ) : null}
    </div>
  );
}

export function runtimeRecoveryActionTargetPreview(target: Record<string, unknown>): string {
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
  const preview = compactPreview([
    stringValue(target.action),
    label,
    app,
    query && query !== app ? `query ${query}` : '',
  ]);
  return preview || runtimeRecoveryValuePreview(target);
}

export function runtimeRecoveryObservationEvidencePreview(evidence: Record<string, unknown>): string {
  if (!Object.keys(evidence).length) return '';
  const center = runtimeRecoveryObservedCenterPreview(evidence);
  const app = (
    stringValue(evidence.app_name)
    || stringValue(evidence.resolved_app_name)
    || stringValue(evidence.app)
  );
  const query = stringValue(evidence.query) || stringValue(evidence.app_query);
  const foreground = evidence.foreground_required === true
    ? `foreground ${evidence.foreground_ready === false ? 'not ready' : 'required'}`
    : '';
  const preview = compactPreview([
    stringValue(evidence.source_tool) || stringValue(evidence.source),
    stringValue(evidence.strategy),
    stringValue(evidence.reason),
    runtimeRecoveryEvidenceBlocker(evidence),
    app,
    query && query !== app ? `query ${query}` : '',
    evidence.verification_failed === true ? 'verification failed' : '',
    foreground,
    center ? `center ${center}` : '',
  ]);
  return preview || runtimeRecoveryValuePreview(evidence);
}

export function runtimeRecoveryObservationRetryPreview(retry: Record<string, unknown>): string {
  if (!Object.keys(retry).length) return '';
  const retryInput = objectRecord(retry.input);
  const retryTarget = (
    stringValue(retry.target)
    || stringValue(retry.label)
    || stringValue(retry.target_label)
    || stringValue(retryInput.app_name)
    || stringValue(retryInput.query)
  );
  const preview = compactPreview([
    stringValue(retry.tool) || stringValue(retry.from_tool) || stringValue(retry.source_tool),
    stringValue(retry.reason),
    retryTarget,
  ]);
  return preview || runtimeRecoveryValuePreview(retry);
}

export function runtimeRecoveryObservedCenterPreview(evidence: Record<string, unknown>): string {
  const center = objectRecord(evidence.observed_center);
  const fallbackPoint = objectRecord(evidence.point);
  const x = coordinateValue(center.x ?? fallbackPoint.x);
  const y = coordinateValue(center.y ?? fallbackPoint.y);
  return x && y ? `${x},${y}` : '';
}

export function runtimeRecoveryVerificationTargetsPreview(targets: Array<Record<string, unknown>>): string {
  const parts = targets.slice(0, 3).map((target) => {
    const label = (
      stringValue(target.todo_title)
      || stringValue(target.title)
      || stringValue(target.step_id)
      || stringValue(target.todo_id)
      || stringValue(target.tool_name)
    );
    const checkpoints = Array.isArray(target.checkpoint_titles)
      ? uniqueStrings(target.checkpoint_titles).slice(0, 2).join(', ')
      : '';
    const workspace = runtimeRecoveryVerificationTargetWorkspacePreview(target);
    return [
      label,
      checkpoints,
      workspace ? `workspace: ${workspace}` : '',
    ].filter(Boolean).join(' -> ');
  }).filter(Boolean);
  if (!parts.length) return '';
  const suffix = targets.length > parts.length ? ` +${targets.length - parts.length}` : '';
  return truncatePreview(`${parts.join(' | ')}${suffix}`, 160);
}

export function runtimeRecoveryEvidenceBlocker(evidence: Record<string, unknown>): string {
  const blocker = stringValue(evidence.blocking_condition);
  if (blocker) return blocker;
  const conditions = evidence.blocking_conditions;
  if (!Array.isArray(conditions)) return '';
  return uniqueStrings(conditions)[0] || '';
}

export function runtimeRecoveryValuePreview(value: unknown): string {
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
  return truncatePreview(preview, 160);
}

function runtimeRecoveryVerificationTargetWorkspacePreview(target: Record<string, unknown>): string {
  const items = [
    ...arrayRecords(target.workspace_items),
    ...arrayRecords(target.task_workspace_items),
  ];
  const labels = items
    .slice(0, 2)
    .map((item) => (
      stringValue(item.title)
      || stringValue(item.path)
      || stringValue(item.item_id)
    ))
    .filter(Boolean);
  return labels.join(', ');
}

function compactPreview(parts: string[]): string {
  return truncatePreview(
    parts
      .map((part) => part.trim())
      .filter(Boolean)
      .join(' · '),
    120,
  );
}

function truncatePreview(value: string, limit: number): string {
  const clean = value.replace(/\s+/g, ' ').trim();
  return clean.length > limit ? `${clean.slice(0, limit - 3)}...` : clean;
}

function arrayRecords(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => (
    Boolean(item) && typeof item === 'object' && !Array.isArray(item)
  ));
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function coordinateValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) {
    return Number.isInteger(value) ? String(value) : value.toFixed(2);
  }
  if (typeof value !== 'string') return '';
  const parsed = Number.parseFloat(value);
  if (!Number.isFinite(parsed)) return '';
  return Number.isInteger(parsed) ? String(parsed) : parsed.toFixed(2);
}

function uniqueStrings(values: unknown[]): string[] {
  const result: string[] = [];
  values.forEach((value) => {
    const text = String(value || '').trim();
    if (text && !result.includes(text)) result.push(text);
  });
  return result;
}
