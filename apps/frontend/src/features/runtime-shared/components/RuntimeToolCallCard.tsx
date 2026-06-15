import { approvalPreviewRecord, approvalPreviewValue } from '../approval';
import { ExpandableRuntimeContent } from './ExpandableRuntimeContent';

export type RuntimeToolCallCardSnapshot = {
  tool_call_id: string;
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
  return (
    <div
      className={className}
      data-approval-id={toolCall.approval_id || ''}
      data-risk-level={toolCall.risk_level || ''}
      data-testid={testId}
      data-tool-call-id={toolCall.tool_call_id}
      data-tool-name={toolCall.tool_name}
      data-tool-status={toolCall.status}
    >
      <span>{toolCall.status || 'tool'}</span>
      <strong>{toolCall.tool_name || 'tool'}</strong>
      {toolCall.risk_level ? <em>{toolCall.risk_level}</em> : null}
      {target ? <code>{target}</code> : null}
      {output ? <p>{output}</p> : null}
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

function formatToolPreview(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value);
  }
}
