import { approvalPreviewRecord, approvalPreviewValue } from '../approval';
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
  testId = 'runtime-tool-call-card',
}: {
  toolCall: RuntimeToolCallCardSnapshot;
  className?: string;
  testId?: string;
}) {
  const inputPreview = approvalPreviewRecord(toolCall.input_preview);
  const outputPreview = approvalPreviewRecord(toolCall.output_preview);
  const target = approvalPreviewValue(inputPreview, ['command', 'cmd', 'path', 'file', 'target']);
  const output = approvalPreviewValue(outputPreview, ['summary', 'result', 'output', 'stdout', 'path']);
  const inputPreviewContent = formatToolPreview(inputPreview);
  const outputPreviewContent = formatToolPreview(outputPreview);
  const metadata = toolCallMetadataItems(toolCall);
  return (
    <div
      className={className}
      data-approval-id={toolCall.approval_id || ''}
      data-group-run-id={toolCall.group_run_id || ''}
      data-risk-level={toolCall.risk_level || ''}
      data-source-runnable-id={toolCall.source_runnable_id || ''}
      data-source-run-id={toolCall.source_run_id || ''}
      data-testid={testId}
      data-tool-call-id={toolCall.tool_call_id}
      data-tool-name={toolCall.tool_name}
      data-tool-status={toolCall.status}
      data-workflow-node-id={toolCall.workflow_node_id || ''}
    >
      <span>{toolCall.status || 'tool'}</span>
      <strong>{toolCall.tool_name || 'tool'}</strong>
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
    { label: 'workflow', value: toolCall.workflow_node_label || toolCall.workflow_node_id || '' },
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
