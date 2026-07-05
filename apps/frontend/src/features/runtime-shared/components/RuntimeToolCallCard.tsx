import {
  approvalPreviewRecord,
  approvalPreviewTarget,
  approvalPreviewValue,
  runtimeToolDisplayLabelOrName,
  runtimeToolFamily,
} from '../approval';
import {
  runtimeToolRecoveryActionWithInputPatch,
  runtimeToolRecoveryActionsFromRecords,
  runtimeToolRecoveryMissingRequiredFields,
  runtimeToolRecoveryRetryAction,
  type RuntimeToolRecoveryAction,
} from '../toolRecoveryActions';
import { runtimeToolRecoveryHintsFromRecords } from '../toolRecoveryHints';
import { runtimeAnchorId } from '../runtimeAnchors';
import { ExpandableRuntimeContent } from './ExpandableRuntimeContent';

export type RuntimeToolCallCardSnapshot = {
  tool_call_id: string;
  run_id?: string | null;
  source_run_id?: string | null;
  source_runnable_id?: string | null;
  source_runnable_name?: string | null;
  workflow_id?: string | null;
  workflow_run_id?: string | null;
  workflow_node_id?: string | null;
  workflow_node_label?: string | null;
  group_id?: string | null;
  group_run_id?: string | null;
  source?: string | null;
  planning_reason?: string | null;
  decision_id?: string | null;
  plan_id?: string | null;
  tool_plan_id?: string | null;
  intent_kind?: string | null;
  step_id?: string | null;
  planner_step_id?: string | null;
  capability_id?: string | null;
  capability_title?: string | null;
  capability_status?: string | null;
  capability_reason?: string | null;
  capability_selected_tools?: string[];
  capability_planned_step_ids?: string[];
  replan_request_id?: string | null;
  replan_trigger?: string | null;
  task_workspace_items?: Array<Record<string, unknown>>;
  verification_targets?: Array<Record<string, unknown>>;
  task_verification_targets?: Array<Record<string, unknown>>;
  checkpoint_policy?: Record<string, unknown>;
  desktop_loop?: Record<string, unknown>;
  replan_triggers?: string[];
  replan_signal_ids?: string[];
  runtime_doctrine?: string | null;
  runtime_stage?: string | null;
  runtime_role?: string | null;
  requires_observation?: boolean | null;
  requires_post_action_verification?: boolean | null;
  deferred_tool?: string | null;
  deferred_input?: Record<string, unknown>;
  deferred_context?: Record<string, unknown>;
  deferred_continuation?: Array<Record<string, unknown>>;
  tool_name: string;
  status: string;
  risk_level?: string | null;
  policy_reason?: string | null;
  input_preview?: Record<string, unknown>;
  output_preview?: Record<string, unknown>;
  metadata?: Record<string, unknown>;
  approval_id?: string | null;
};

export function RuntimeToolCallCard({
  toolCall,
  className = 'runtime-tool-call',
  onRunRecoveryAction,
  recoveryActionDisabled = false,
  recoveryActionInputPatch,
  testId = 'runtime-tool-call-card',
}: {
  toolCall: RuntimeToolCallCardSnapshot;
  className?: string;
  onRunRecoveryAction?: (
    toolCall: RuntimeToolCallCardSnapshot,
    action: RuntimeToolRecoveryAction,
  ) => unknown | Promise<unknown>;
  recoveryActionDisabled?: boolean;
  recoveryActionInputPatch?: (
    toolCall: RuntimeToolCallCardSnapshot,
    action: RuntimeToolRecoveryAction,
  ) => Record<string, unknown> | null | undefined;
  testId?: string;
}) {
  const inputPreview = approvalPreviewRecord(toolCall.input_preview);
  const outputPreview = approvalPreviewRecord(toolCall.output_preview);
  const displayName = runtimeToolDisplayLabelOrName(toolCall.tool_name);
  const rawToolName = String(toolCall.tool_name || '').trim();
  const target = approvalPreviewTarget(inputPreview, toolCall.tool_name);
  const output = approvalPreviewValue(outputPreview, ['summary', 'result', 'output', 'stdout', 'path']);
  const inputPreviewContent = formatToolPreview(inputPreview);
  const outputPreviewContent = formatToolPreview(outputPreview);
  const recoveryHints = runtimeToolRecoveryHintsFromRecords([outputPreview, inputPreview]);
  const blockingConditions = runtimeToolBlockingConditionsFromRecords([outputPreview, inputPreview]);
  const recoveryActions = runtimeToolRecoveryActionsFromRecords(
    [outputPreview, inputPreview],
    {
      retry_input: inputPreview,
      retry_source_tool_call_id: toolCall.tool_call_id,
      retry_tool: rawToolName,
    },
  );
  const observedMetadata = runtimeToolObservedMetadata(toolCall);
  const observedActionTarget = observedActionTargetSummary(observedMetadata.actionTarget);
  const observedActionEvidence = observedActionEvidenceSummary(observedMetadata.observationEvidence);
  const observedActionRetry = observedActionRetrySummary(observedMetadata.observationRetry);
  const observedCenter = observedActionCenterSummary(observedMetadata.observationEvidence);
  const taskWorkspaceItems = runtimeToolTaskWorkspaceItems(toolCall);
  const taskVerificationTargets = runtimeToolTaskVerificationTargets(toolCall);
  const checkpointPolicy = runtimeToolTraceRecord(toolCall, 'checkpoint_policy');
  const desktopLoop = runtimeToolTraceRecord(toolCall, 'desktop_loop');
  const deferredContinuation = runtimeToolTraceRecordList(toolCall, 'deferred_continuation');
  const metadata = toolCallMetadataItems(toolCall);
  const anchorId = runtimeAnchorId('tool-call', toolCall.tool_call_id);
  return (
    <div
      className={className}
      id={anchorId || undefined}
      data-approval-id={toolCall.approval_id || ''}
      data-blocking-conditions={blockingConditions.join(',')}
      data-deferred-continuation-count={deferredContinuation.length}
      data-deferred-tool={runtimeToolTraceString(toolCall, 'deferred_tool')}
      data-group-id={toolCall.group_id || ''}
      data-group-run-id={toolCall.group_run_id || ''}
      data-observed-action-evidence={observedActionEvidence}
      data-observed-action-retry={observedActionRetry}
      data-observed-action-target={observedActionTarget}
      data-observed-center={observedCenter}
      data-risk-level={toolCall.risk_level || ''}
      data-run-id={toolCall.run_id || ''}
      data-runtime-capability-id={runtimeToolTraceString(toolCall, 'capability_id')}
      data-runtime-capability-title={runtimeToolTraceString(toolCall, 'capability_title')}
      data-runtime-deferred-tool={runtimeToolTraceString(toolCall, 'deferred_tool')}
      data-runtime-desktop-loop={runtimeToolDesktopLoopSummary(desktopLoop)}
      data-runtime-doctrine={runtimeToolTraceString(toolCall, 'runtime_doctrine')}
      data-runtime-replan-request-id={runtimeToolTraceString(toolCall, 'replan_request_id')}
      data-runtime-replan-signal-ids={runtimeToolTraceStringList(toolCall, 'replan_signal_ids').join(',')}
      data-runtime-replan-trigger={runtimeToolTraceString(toolCall, 'replan_trigger') || runtimeToolTraceStringList(toolCall, 'replan_triggers')[0] || ''}
      data-runtime-role={runtimeToolTraceString(toolCall, 'runtime_role')}
      data-runtime-stage={runtimeToolTraceString(toolCall, 'runtime_stage')}
      data-runtime-step-id={runtimeToolTraceString(toolCall, 'step_id', 'planner_step_id')}
      data-runtime-checkpoint-policy={runtimeToolCheckpointPolicySummary(checkpointPolicy)}
      data-runtime-app-resolution-match-capability={runtimeToolTraceString(toolCall, 'app_resolution_matched_capability')}
      data-runtime-app-resolution-match-name={runtimeToolTraceString(toolCall, 'app_resolution_matched_name')}
      data-runtime-app-resolution-match-source={runtimeToolTraceString(toolCall, 'app_resolution_matched_name_source')}
      data-source-runnable-id={toolCall.source_runnable_id || ''}
      data-source-run-id={toolCall.source_run_id || ''}
      data-runtime-anchor={anchorId}
      data-runtime-anchor-kind="tool-call"
      data-runtime-anchor-value={toolCall.tool_call_id}
      data-task-verification-target-count={taskVerificationTargets.length}
      data-task-workspace-item-count={taskWorkspaceItems.length}
      data-testid={testId}
      data-tool-call-id={toolCall.tool_call_id}
      data-tool-family={runtimeToolFamily(toolCall.tool_name)}
      data-tool-name={toolCall.tool_name}
      data-tool-policy-reason={toolCall.policy_reason || ''}
      data-tool-status={toolCall.status}
      data-workflow-id={toolCall.workflow_id || ''}
      data-workflow-node-id={toolCall.workflow_node_id || ''}
      data-workflow-run-id={toolCall.workflow_run_id || ''}
    >
      <span>{toolCall.status || 'tool'}</span>
      <strong>{displayName}</strong>
      {rawToolName && rawToolName !== displayName ? <small>{rawToolName}</small> : null}
      {toolCall.risk_level ? (
        <em title={toolCall.policy_reason || undefined}>{toolCall.risk_level}</em>
      ) : null}
      {target ? <code>{target}</code> : null}
      {output ? <p>{output}</p> : null}
      {metadata.length ? (
        <dl className="runtime-tool-call-metadata">
          {metadata.map((item) => (
            <div key={item.label}>
              <dt>{item.label}</dt>
              <dd>{item.value}</dd>
            </div>
          ))}
        </dl>
      ) : null}
      {blockingConditions.length ? (
        <div className="runtime-tool-call-blockers" data-testid={`${testId}-runtime-blockers`}>
          {blockingConditions.map((condition) => (
            <span data-runtime-blocker={condition} key={condition}>
              {runtimeToolBlockingConditionLabel(condition)}
            </span>
          ))}
        </div>
      ) : null}
      {recoveryHints.length ? (
        <ul className="runtime-tool-call-recovery-hints" data-testid={`${testId}-recovery-hints`}>
          {recoveryHints.map((hint) => (
            <li key={hint}>{hint}</li>
          ))}
        </ul>
      ) : null}
      {recoveryActions.length ? (
        <div className="runtime-tool-call-recovery-actions" data-testid={`${testId}-recovery-actions`}>
          {recoveryActions.slice(0, 3).flatMap((action) => {
            const baseRetryAction = runtimeToolRecoveryRetryAction(action);
            const retryInputPatch = baseRetryAction
              ? recoveryActionInputPatch?.(toolCall, baseRetryAction)
              : null;
            const retryAction = baseRetryAction && retryInputPatch
              ? runtimeToolRecoveryActionWithInputPatch(baseRetryAction, retryInputPatch)
              : baseRetryAction;
            const retryFields = retryAction?.required_retry_fields || [];
            const missingRetryFields = retryAction ? runtimeToolRecoveryMissingRequiredFields(retryAction) : [];
            const retryInputSource = retryAction?.retry_input_source === 'screen_capture_artifact'
              ? '截图定位'
              : '';
            const retryInput = retryAction?.input || {};
            const verificationTargetsPreview = runtimeToolRecoveryVerificationTargetsSummary(action.verification_targets);
            const retryVerificationTargetsPreview = retryAction
              ? runtimeToolRecoveryVerificationTargetsSummary(retryAction.verification_targets)
              : '';
            return [
              <button
                type="button"
                data-permission-target={action.permission_target}
                data-recovery-kind="permission_recovery"
                data-recovery-tool={action.tool}
                data-recovery-verification-targets={verificationTargetsPreview}
                data-testid={`${testId}-run-recovery-action`}
                disabled={recoveryActionDisabled || !onRunRecoveryAction}
                key={`${action.tool}:${action.prompt}:${action.permission_target}:recovery`}
                onClick={() => void onRunRecoveryAction?.(toolCall, action)}
                title={[
                  action.prompt,
                  verificationTargetsPreview ? `verification: ${verificationTargetsPreview}` : '',
                ].filter(Boolean).join(' · ')}
              >
                {action.label}
                {verificationTargetsPreview ? (
                  <small className="runtime-tool-call-recovery-verification">
                    verifies: {verificationTargetsPreview}
                  </small>
                ) : null}
              </button>,
              retryAction ? (
                <button
                  type="button"
                  className={retryFields.length ? 'has-retry-contract' : undefined}
                  data-required-retry-fields={retryFields.join(',')}
                  data-missing-retry-fields={missingRetryFields.join(',')}
                  data-permission-target={retryAction.permission_target}
                  data-retry-input-source={retryAction.retry_input_source || ''}
                  data-selected-retry-x={retryInput.x ?? ''}
                  data-selected-retry-y={retryInput.y ?? ''}
                  data-recovery-kind="retry_original"
                  data-recovery-tool={retryAction.tool}
                  data-recovery-verification-targets={retryVerificationTargetsPreview}
                  data-retry-input-schema={JSON.stringify(retryAction.retry_input_schema || {})}
                  data-testid={`${testId}-run-retry-action`}
                  disabled={recoveryActionDisabled || !onRunRecoveryAction || missingRetryFields.length > 0}
                  key={`${retryAction.tool}:${retryAction.prompt}:${retryAction.permission_target}:retry`}
                  onClick={() => void onRunRecoveryAction?.(toolCall, retryAction)}
                  title={[
                    retryAction.prompt,
                    retryVerificationTargetsPreview ? `verification: ${retryVerificationTargetsPreview}` : '',
                  ].filter(Boolean).join(' · ')}
                >
                  {retryAction.label}
                  {retryVerificationTargetsPreview ? (
                    <small className="runtime-tool-call-recovery-verification">
                      verifies: {retryVerificationTargetsPreview}
                    </small>
                  ) : null}
                  {missingRetryFields.length ? (
                    <small className="runtime-tool-call-retry-contract">
                      待补参数：{missingRetryFields.join('、')}
                      {retryInputSource ? ` · ${retryInputSource}` : ''}
                    </small>
                  ) : null}
                </button>
              ) : null,
            ];
          })}
        </div>
      ) : null}
      {inputPreviewContent || outputPreviewContent ? (
        <div className="runtime-tool-call-previews">
          {inputPreviewContent ? (
            <ExpandableRuntimeContent
              content={inputPreviewContent}
              label="展开输入预览"
            />
          ) : null}
          {outputPreviewContent ? (
            <ExpandableRuntimeContent
              content={outputPreviewContent}
              label="展开输出预览"
            />
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function toolCallMetadataItems(toolCall: RuntimeToolCallCardSnapshot): Array<{ label: string; value: string }> {
  const observedMetadata = runtimeToolObservedMetadata(toolCall);
  const replanTrigger = runtimeToolTraceString(toolCall, 'replan_trigger');
  const replanTriggers = runtimeToolTraceStringList(toolCall, 'replan_triggers');
  const taskWorkspaceItems = runtimeToolTaskWorkspaceItems(toolCall);
  const taskVerificationTargets = runtimeToolTaskVerificationTargets(toolCall);
  const checkpointPolicy = runtimeToolTraceRecord(toolCall, 'checkpoint_policy');
  const desktopLoop = runtimeToolTraceRecord(toolCall, 'desktop_loop');
  const deferredInput = runtimeToolTraceRecord(toolCall, 'deferred_input');
  const deferredContext = runtimeToolTraceRecord(toolCall, 'deferred_context');
  const deferredContinuation = runtimeToolTraceRecordList(toolCall, 'deferred_continuation');
  const capabilityTitle = runtimeToolTraceString(toolCall, 'capability_title');
  const appResolution = runtimeToolAppResolutionSummary(toolCall);
  return [
    { label: 'run', value: toolCall.run_id || '' },
    { label: 'source', value: toolCall.source_run_id || '' },
    { label: 'agent', value: toolCall.source_runnable_name || toolCall.source_runnable_id || '' },
    { label: 'workflow', value: toolCall.workflow_node_label || toolCall.workflow_node_id || toolCall.workflow_run_id || toolCall.workflow_id || '' },
    { label: 'group', value: toolCall.group_run_id || toolCall.group_id || '' },
    { label: 'intent', value: toolCall.intent_kind || '' },
    { label: 'capability', value: capabilityTitle || runtimeToolTraceString(toolCall, 'capability_id') },
    { label: 'capability id', value: capabilityTitle ? runtimeToolTraceString(toolCall, 'capability_id') : '' },
    { label: 'capability status', value: runtimeToolTraceString(toolCall, 'capability_status') },
    { label: 'capability reason', value: runtimeToolTraceString(toolCall, 'capability_reason') },
    { label: 'capability tools', value: runtimeToolTraceStringList(toolCall, 'capability_selected_tools').join(', ') },
    { label: 'capability steps', value: runtimeToolTraceStringList(toolCall, 'capability_planned_step_ids').join(', ') },
    { label: 'step', value: runtimeToolTraceString(toolCall, 'step_id', 'planner_step_id') },
    { label: 'stage', value: runtimeToolTraceString(toolCall, 'runtime_stage') },
    { label: 'role', value: runtimeToolTraceString(toolCall, 'runtime_role') },
    { label: 'doctrine', value: runtimeToolTraceString(toolCall, 'runtime_doctrine') },
    { label: 'observe', value: runtimeToolTraceBoolLabel(toolCall, 'requires_observation') },
    { label: 'verify', value: runtimeToolTraceBoolLabel(toolCall, 'requires_post_action_verification') },
    { label: 'workspace', value: runtimeToolTaskWorkspaceSummary(taskWorkspaceItems) },
    { label: 'targets', value: runtimeToolRecoveryVerificationTargetsSummary(taskVerificationTargets) },
    { label: 'checkpoint policy', value: runtimeToolCheckpointPolicySummary(checkpointPolicy) },
    { label: 'desktop loop', value: runtimeToolDesktopLoopSummary(desktopLoop) },
    { label: 'app resolution', value: appResolution },
    { label: 'replan', value: runtimeToolTraceString(toolCall, 'replan_request_id') || replanTrigger || replanTriggers.join(', ') },
    { label: 'signals', value: runtimeToolTraceStringList(toolCall, 'replan_signal_ids').join(', ') },
    { label: 'deferred', value: runtimeToolTraceString(toolCall, 'deferred_tool') },
    { label: 'deferred input', value: runtimeToolObjectSummary(deferredInput) },
    { label: 'deferred context', value: runtimeToolObjectSummary(deferredContext) },
    { label: 'continuation', value: runtimeToolDeferredContinuationSummary(deferredContinuation) },
    { label: 'action', value: observedActionTargetSummary(observedMetadata.actionTarget) },
    { label: 'observed', value: observedActionEvidenceSummary(observedMetadata.observationEvidence) },
    { label: 'retry', value: observedActionRetrySummary(observedMetadata.observationRetry) },
  ].filter((item) => item.value);
}

function runtimeToolAppResolutionSummary(toolCall: RuntimeToolCallCardSnapshot): string {
  const requested = runtimeToolTraceString(toolCall, 'requested_app_name');
  const resolved = runtimeToolTraceString(toolCall, 'resolved_app_name', 'app_name');
  const matchedName = runtimeToolTraceString(toolCall, 'app_resolution_matched_name');
  const matchedSource = runtimeToolTraceString(toolCall, 'app_resolution_matched_name_source');
  const matchedCapability = runtimeToolTraceString(toolCall, 'app_resolution_matched_capability');
  const source = runtimeToolTraceString(toolCall, 'app_resolution_source');
  const confidence = runtimeToolTraceString(toolCall, 'app_resolution_confidence');
  const score = runtimeToolTraceString(toolCall, 'app_resolution_score');
  const reason = runtimeToolTraceString(toolCall, 'app_resolution_reason');
  return [
    requested && requested !== resolved ? `requested ${requested}` : '',
    resolved ? `resolved ${resolved}` : '',
    matchedName ? `matched ${matchedName}` : '',
    matchedSource ? `name source ${matchedSource}` : '',
    matchedCapability ? `capability ${matchedCapability}` : '',
    source ? `via ${source}` : '',
    confidence || score ? [confidence, score].filter(Boolean).join('/') : '',
    reason,
  ].filter(Boolean).join(' · ');
}

function runtimeToolObservedMetadata(toolCall: RuntimeToolCallCardSnapshot): {
  actionTarget: Record<string, unknown>;
  observationEvidence: Record<string, unknown>;
  observationRetry: Record<string, unknown>;
} {
  const metadata = approvalPreviewRecord(toolCall.metadata);
  return {
    actionTarget: approvalPreviewRecord(metadata.action_target),
    observationEvidence: approvalPreviewRecord(metadata.observation_evidence),
    observationRetry: approvalPreviewRecord(metadata.observation_retry),
  };
}

function runtimeToolTraceString(
  toolCall: RuntimeToolCallCardSnapshot,
  ...keys: string[]
): string {
  for (const key of keys) {
    for (const record of runtimeToolTraceRecords(toolCall)) {
      const value = stringValue(record[key]);
      if (value) return value;
    }
  }
  return '';
}

function runtimeToolTraceStringList(
  toolCall: RuntimeToolCallCardSnapshot,
  ...keys: string[]
): string[] {
  const values: string[] = [];
  for (const key of keys) {
    for (const record of runtimeToolTraceRecords(toolCall)) {
      for (const value of stringList(record[key])) {
        if (!values.includes(value)) values.push(value);
      }
    }
  }
  return values;
}

function runtimeToolTraceBoolLabel(
  toolCall: RuntimeToolCallCardSnapshot,
  key: string,
): string {
  for (const record of runtimeToolTraceRecords(toolCall)) {
    if (record[key] === true) return 'required';
    if (record[key] === false) continue;
    const value = stringValue(record[key]).toLowerCase();
    if (value === 'true' || value === 'required') return 'required';
  }
  return '';
}

function runtimeToolTraceRecord(
  toolCall: RuntimeToolCallCardSnapshot,
  key: string,
): Record<string, unknown> {
  for (const record of runtimeToolTraceRecords(toolCall)) {
    const value = approvalPreviewRecord(record[key]);
    if (Object.keys(value).length) return value;
  }
  return {};
}

function runtimeToolTraceRecordList(
  toolCall: RuntimeToolCallCardSnapshot,
  key: string,
): Array<Record<string, unknown>> {
  return uniqueRecords(
    runtimeToolTraceRecords(toolCall).flatMap((record) => recordList(record[key])),
  );
}

function runtimeToolTraceRecords(toolCall: RuntimeToolCallCardSnapshot): Record<string, unknown>[] {
  const metadata = approvalPreviewRecord(toolCall.metadata);
  return [
    toolCall as Record<string, unknown>,
    metadata,
    approvalPreviewRecord(metadata.tool_request),
    approvalPreviewRecord(metadata.planned_request),
    approvalPreviewRecord(metadata.request),
    approvalPreviewRecord(metadata.result),
    approvalPreviewRecord(metadata.metadata),
    approvalPreviewRecord(toolCall.input_preview),
    approvalPreviewRecord(toolCall.output_preview),
  ].filter((record) => Object.keys(record).length);
}

function observedActionTargetSummary(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  const action = stringValue(value.action);
  const target = (
    stringValue(value.target)
    || stringValue(value.label)
    || stringValue(value.name)
    || stringValue(value.title)
    || stringValue(value.text)
    || stringValue(value.role)
  );
  const roleFilter = stringValue(value.role_filter);
  const app = stringValue(value.app_name) || stringValue(value.app) || stringValue(value.bundle_id);
  if (!action && !target && !app) return '';
  return [action, target, roleFilter ? `role ${roleFilter}` : '', app]
    .filter(Boolean)
    .join(' · ');
}

function observedActionEvidenceSummary(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  const sourceTool = stringValue(value.source_tool);
  const source = stringValue(value.source);
  const strategy = stringValue(value.strategy);
  const reason = stringValue(value.reason);
  const center = observedActionCenterSummary(value);
  return [sourceTool || source, strategy, reason, center ? `center ${center}` : ''].filter(Boolean).join(' · ');
}

function observedActionRetrySummary(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  const sourceTool = stringValue(value.from_tool) || stringValue(value.source_tool);
  const reason = stringValue(value.reason);
  const target = stringValue(value.target) || stringValue(value.label) || stringValue(value.target_label);
  return [sourceTool, reason, target ? `target ${target}` : ''].filter(Boolean).join(' · ');
}

function observedActionCenterSummary(value: Record<string, unknown>): string {
  const center = approvalPreviewRecord(value.observed_center);
  const legacyCenter = approvalPreviewRecord(value.center);
  const point = approvalPreviewRecord(value.point);
  const x = coordinateValue(center.x ?? legacyCenter.x ?? point.x);
  const y = coordinateValue(center.y ?? legacyCenter.y ?? point.y);
  return x && y ? `${x},${y}` : '';
}

function runtimeToolRecoveryVerificationTargetsSummary(
  targets: Array<Record<string, unknown>> | undefined,
): string {
  if (!targets?.length) return '';
  const parts = targets.slice(0, 3).map((target) => {
    const label = (
      stringValue(target.todo_title)
      || stringValue(target.title)
      || stringValue(target.step_id)
      || stringValue(target.todo_id)
      || stringValue(target.tool_name)
    );
    const workspaceItems = [
      ...recordList(target.workspace_items),
      ...recordList(target.task_workspace_items),
    ];
    const workspace = workspaceItems
      .slice(0, 2)
      .map((item) => (
        stringValue(item.title)
        || stringValue(item.path)
        || stringValue(item.item_id)
        || stringValue(item.source_step_id)
      ))
      .filter(Boolean)
      .join(', ');
    return [label, workspace ? `workspace: ${workspace}` : ''].filter(Boolean).join(' -> ');
  }).filter(Boolean);
  if (!parts.length) return '';
  const suffix = targets.length > parts.length ? ` +${targets.length - parts.length}` : '';
  return `${parts.join(' | ')}${suffix}`;
}

function runtimeToolCheckpointPolicySummary(record: Record<string, unknown>): string {
  if (!Object.keys(record).length) return '';
  const checkpointIds = stringList(record.checkpoint_ids);
  const titles = stringList(record.checkpoint_titles);
  const triggers = stringList(record.replan_triggers);
  const fallbacks = stringList(record.fallback_tools);
  const targetSteps = stringList(record.verification_target_step_ids);
  const flags = [
    record.replan_on_failure === true ? 'replan' : '',
    record.requires_approval === true ? 'approval' : '',
    record.requires_observation === true ? 'observe' : '',
    record.requires_post_action_verification === true ? 'verify' : '',
  ].filter(Boolean);
  const primary = titles[0] || checkpointIds[0] || targetSteps[0] || '';
  return [
    primary,
    triggers.length ? `triggers ${triggers.join(', ')}` : '',
    fallbacks.length ? `fallbacks ${fallbacks.join(', ')}` : '',
    targetSteps.length ? `targets ${targetSteps.join(', ')}` : '',
    flags.length ? flags.join(', ') : '',
  ].filter(Boolean).join(' · ');
}

function runtimeToolDesktopLoopSummary(record: Record<string, unknown>): string {
  if (!Object.keys(record).length) return '';
  const stage = stringValue(record.stage);
  const action = stringValue(record.action);
  const app = stringValue(record.app_name) || stringValue(record.query);
  const retryTool = stringValue(record.retry_tool);
  const retryReason = stringValue(record.retry_reason);
  const targetSteps = stringList(record.verification_target_step_ids);
  return [
    [stage, action].filter(Boolean).join(':'),
    app,
    retryTool ? `retry ${retryTool}` : '',
    retryReason,
    targetSteps.length ? `verifies ${targetSteps.join(', ')}` : '',
    record.can_auto_retry === true ? 'auto retry' : '',
  ].filter(Boolean).join(' · ');
}

function runtimeToolObjectSummary(record: Record<string, unknown>): string {
  if (!Object.keys(record).length) return '';
  const primary = (
    stringValue(record.tool)
    || stringValue(record.target)
    || stringValue(record.label)
    || stringValue(record.query)
    || stringValue(record.step_id)
  );
  const keys = Object.keys(record).filter((key) => (
    record[key] !== undefined && record[key] !== null
  ));
  return primary ? `${primary} (${keys.length} fields)` : `${keys.length} fields`;
}

function runtimeToolDeferredContinuationSummary(records: Array<Record<string, unknown>>): string {
  if (!records.length) return '';
  const labels = records
    .slice(0, 3)
    .map((record) => (
      stringValue(record.tool)
      || stringValue(record.step_id)
      || stringValue(record.label)
      || stringValue(record.target)
    ))
    .filter(Boolean);
  const suffix = records.length > labels.length ? ` +${records.length - labels.length}` : '';
  return labels.length ? `${labels.join(', ')}${suffix}` : `${records.length} steps`;
}

function runtimeToolTaskWorkspaceItems(toolCall: RuntimeToolCallCardSnapshot): Array<Record<string, unknown>> {
  return uniqueRecords(runtimeToolTraceRecords(toolCall).flatMap((record) => [
    ...recordList(record.task_workspace_items),
    ...recordList(record.workspace_items),
  ]));
}

function runtimeToolTaskVerificationTargets(toolCall: RuntimeToolCallCardSnapshot): Array<Record<string, unknown>> {
  return uniqueRecords(runtimeToolTraceRecords(toolCall).flatMap((record) => [
    ...recordList(record.task_verification_targets),
    ...recordList(record.verification_targets),
  ]));
}

function runtimeToolTaskWorkspaceSummary(items: Array<Record<string, unknown>>): string {
  return items
    .slice(0, 3)
    .map((item) => (
      stringValue(item.title)
      || stringValue(item.path)
      || stringValue(item.item_id)
      || stringValue(item.source_step_id)
    ))
    .filter(Boolean)
    .join(', ');
}

function uniqueRecords(items: Array<Record<string, unknown>>): Array<Record<string, unknown>> {
  const seen = new Set<string>();
  return items.filter((item) => {
    const key = JSON.stringify(item);
    if (seen.has(key)) return false;
    seen.add(key);
    return true;
  });
}

function recordList(value: unknown): Array<Record<string, unknown>> {
  if (!Array.isArray(value)) return [];
  return value.filter((item): item is Record<string, unknown> => (
    Boolean(item) && typeof item === 'object' && !Array.isArray(item)
  ));
}

function coordinateValue(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) return String(Math.round(value));
  if (typeof value === 'string' && value.trim()) return value.trim();
  return '';
}

function stringValue(value: unknown): string {
  return String(value || '').trim();
}

function formatToolPreview(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}

function runtimeToolBlockingConditionsFromRecords(records: Record<string, unknown>[]): string[] {
  return uniqueStrings(records.flatMap((record) => [
    ...stringList(record.blocking_condition),
    ...stringList(record.blocking_conditions),
    ...stringList(approvalPreviewRecord(record.data).blocking_condition),
    ...stringList(approvalPreviewRecord(record.data).blocking_conditions),
  ]));
}

function runtimeToolBlockingConditionLabel(condition: string): string {
  if (condition === 'desktop_session_locked') return 'desktop session locked';
  if (condition === 'screen_capture_blank') return 'screen capture blank';
  return condition.replace(/_/g, ' ');
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return value.flatMap((item) => stringList(item));
  }
  const clean = String(value || '').trim();
  return clean ? [clean] : [];
}

function uniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => value.trim()).filter(Boolean)));
}
