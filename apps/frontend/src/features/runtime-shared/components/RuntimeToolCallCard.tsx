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
  replan_request_id?: string | null;
  replan_trigger?: string | null;
  replan_triggers?: string[];
  replan_signal_ids?: string[];
  runtime_doctrine?: string | null;
  runtime_stage?: string | null;
  runtime_role?: string | null;
  requires_observation?: boolean | null;
  requires_post_action_verification?: boolean | null;
  tool_name: string;
  status: string;
  risk_level?: string | null;
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
  const metadata = toolCallMetadataItems(toolCall);
  return (
    <div
      className={className}
      data-approval-id={toolCall.approval_id || ''}
      data-blocking-conditions={blockingConditions.join(',')}
      data-group-id={toolCall.group_id || ''}
      data-group-run-id={toolCall.group_run_id || ''}
      data-risk-level={toolCall.risk_level || ''}
      data-run-id={toolCall.run_id || ''}
      data-runtime-capability-id={runtimeToolTraceString(toolCall, 'capability_id')}
      data-runtime-doctrine={runtimeToolTraceString(toolCall, 'runtime_doctrine')}
      data-runtime-replan-request-id={runtimeToolTraceString(toolCall, 'replan_request_id')}
      data-runtime-replan-signal-ids={runtimeToolTraceStringList(toolCall, 'replan_signal_ids').join(',')}
      data-runtime-replan-trigger={runtimeToolTraceString(toolCall, 'replan_trigger') || runtimeToolTraceStringList(toolCall, 'replan_triggers')[0] || ''}
      data-runtime-role={runtimeToolTraceString(toolCall, 'runtime_role')}
      data-runtime-stage={runtimeToolTraceString(toolCall, 'runtime_stage')}
      data-runtime-step-id={runtimeToolTraceString(toolCall, 'step_id', 'planner_step_id')}
      data-source-runnable-id={toolCall.source_runnable_id || ''}
      data-source-run-id={toolCall.source_run_id || ''}
      data-testid={testId}
      data-tool-call-id={toolCall.tool_call_id}
      data-tool-family={runtimeToolFamily(toolCall.tool_name)}
      data-tool-name={toolCall.tool_name}
      data-tool-status={toolCall.status}
      data-workflow-id={toolCall.workflow_id || ''}
      data-workflow-node-id={toolCall.workflow_node_id || ''}
      data-workflow-run-id={toolCall.workflow_run_id || ''}
    >
      <span>{toolCall.status || 'tool'}</span>
      <strong>{displayName}</strong>
      {rawToolName && rawToolName !== displayName ? <small>{rawToolName}</small> : null}
      {toolCall.risk_level ? <em>{toolCall.risk_level}</em> : null}
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
            return [
              <button
                type="button"
                data-permission-target={action.permission_target}
                data-recovery-kind="permission_recovery"
                data-recovery-tool={action.tool}
                data-testid={`${testId}-run-recovery-action`}
                disabled={recoveryActionDisabled || !onRunRecoveryAction}
                key={`${action.tool}:${action.prompt}:${action.permission_target}:recovery`}
                onClick={() => void onRunRecoveryAction?.(toolCall, action)}
                title={action.prompt}
              >
                {action.label}
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
                  data-retry-input-schema={JSON.stringify(retryAction.retry_input_schema || {})}
                  data-testid={`${testId}-run-retry-action`}
                  disabled={recoveryActionDisabled || !onRunRecoveryAction || missingRetryFields.length > 0}
                  key={`${retryAction.tool}:${retryAction.prompt}:${retryAction.permission_target}:retry`}
                  onClick={() => void onRunRecoveryAction?.(toolCall, retryAction)}
                  title={retryAction.prompt}
                >
                  {retryAction.label}
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
  const metadata = approvalPreviewRecord(toolCall.metadata);
  const actionTarget = approvalPreviewRecord(metadata.action_target);
  const observationEvidence = approvalPreviewRecord(metadata.observation_evidence);
  const replanTrigger = runtimeToolTraceString(toolCall, 'replan_trigger');
  const replanTriggers = runtimeToolTraceStringList(toolCall, 'replan_triggers');
  return [
    { label: 'run', value: toolCall.run_id || '' },
    { label: 'source', value: toolCall.source_run_id || '' },
    { label: 'agent', value: toolCall.source_runnable_name || toolCall.source_runnable_id || '' },
    { label: 'workflow', value: toolCall.workflow_node_label || toolCall.workflow_node_id || toolCall.workflow_run_id || toolCall.workflow_id || '' },
    { label: 'group', value: toolCall.group_run_id || toolCall.group_id || '' },
    { label: 'intent', value: toolCall.intent_kind || '' },
    { label: 'capability', value: runtimeToolTraceString(toolCall, 'capability_id') },
    { label: 'step', value: runtimeToolTraceString(toolCall, 'step_id', 'planner_step_id') },
    { label: 'stage', value: runtimeToolTraceString(toolCall, 'runtime_stage') },
    { label: 'role', value: runtimeToolTraceString(toolCall, 'runtime_role') },
    { label: 'doctrine', value: runtimeToolTraceString(toolCall, 'runtime_doctrine') },
    { label: 'observe', value: runtimeToolTraceBoolLabel(toolCall, 'requires_observation') },
    { label: 'verify', value: runtimeToolTraceBoolLabel(toolCall, 'requires_post_action_verification') },
    { label: 'replan', value: runtimeToolTraceString(toolCall, 'replan_request_id') || replanTrigger || replanTriggers.join(', ') },
    { label: 'signals', value: runtimeToolTraceStringList(toolCall, 'replan_signal_ids').join(', ') },
    { label: 'action', value: observedActionTargetSummary(actionTarget) },
    { label: 'observed', value: observedActionEvidenceSummary(observationEvidence) },
  ].filter((item) => item.value);
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
  ].filter((record) => Object.keys(record).length);
}

function observedActionTargetSummary(value: Record<string, unknown>): string {
  const action = stringValue(value.action);
  const target = stringValue(value.target);
  const roleFilter = stringValue(value.role_filter);
  if (!action && !target) return '';
  return [action, target, roleFilter ? `role ${roleFilter}` : '']
    .filter(Boolean)
    .join(' · ');
}

function observedActionEvidenceSummary(value: Record<string, unknown>): string {
  const sourceTool = stringValue(value.source_tool);
  const strategy = stringValue(value.strategy);
  const center = approvalPreviewRecord(value.center);
  const x = stringValue(center.x);
  const y = stringValue(center.y);
  const centerText = x && y ? `center ${x},${y}` : '';
  return [sourceTool, strategy, centerText].filter(Boolean).join(' · ');
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
