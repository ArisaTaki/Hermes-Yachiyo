import { approvalPreviewRecord, approvalPreviewValue } from '../approval';

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
    </div>
  );
}
