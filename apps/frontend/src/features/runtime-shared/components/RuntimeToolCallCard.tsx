import {
  approvalPreviewRecord,
  approvalPreviewTarget,
  approvalPreviewValue,
  runtimeToolDisplayLabelOrName,
  runtimeToolFamily,
} from '../approval';
import {
  runtimeToolRecoveryActionsFromRecords,
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
  tool_name: string;
  status: string;
  risk_level?: string | null;
  input_preview?: Record<string, unknown>;
  output_preview?: Record<string, unknown>;
  approval_id?: string | null;
};

export function RuntimeToolCallCard({
  toolCall,
  className = 'runtime-tool-call',
  onRunRecoveryAction,
  recoveryActionDisabled = false,
  testId = 'runtime-tool-call-card',
}: {
  toolCall: RuntimeToolCallCardSnapshot;
  className?: string;
  onRunRecoveryAction?: (
    toolCall: RuntimeToolCallCardSnapshot,
    action: RuntimeToolRecoveryAction,
  ) => unknown | Promise<unknown>;
  recoveryActionDisabled?: boolean;
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
      data-group-id={toolCall.group_id || ''}
      data-group-run-id={toolCall.group_run_id || ''}
      data-risk-level={toolCall.risk_level || ''}
      data-run-id={toolCall.run_id || ''}
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
            const retryAction = runtimeToolRecoveryRetryAction(action);
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
                  data-permission-target={retryAction.permission_target}
                  data-recovery-kind="retry_original"
                  data-recovery-tool={retryAction.tool}
                  data-testid={`${testId}-run-retry-action`}
                  disabled={recoveryActionDisabled || !onRunRecoveryAction}
                  key={`${retryAction.tool}:${retryAction.prompt}:${retryAction.permission_target}:retry`}
                  onClick={() => void onRunRecoveryAction?.(toolCall, retryAction)}
                  title={retryAction.prompt}
                >
                  {retryAction.label}
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
  return [
    { label: 'run', value: toolCall.run_id || '' },
    { label: 'source', value: toolCall.source_run_id || '' },
    { label: 'agent', value: toolCall.source_runnable_name || toolCall.source_runnable_id || '' },
    { label: 'workflow', value: toolCall.workflow_node_label || toolCall.workflow_node_id || toolCall.workflow_run_id || toolCall.workflow_id || '' },
    { label: 'group', value: toolCall.group_run_id || toolCall.group_id || '' },
  ].filter((item) => item.value);
}

function formatToolPreview(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
