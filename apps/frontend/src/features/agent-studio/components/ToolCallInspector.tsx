import { RuntimeToolCallCard } from '../../runtime-shared/components/RuntimeToolCallCard';
import type { ToolCallSnapshot } from '../../yachiyo-studio/types';

type ToolCallInspectorProps = {
  sourceLabel?: string;
  toolCalls?: ToolCallSnapshot[];
};

export function ToolCallInspector({
  sourceLabel = '工具调用、审批关联和输入输出预览',
  toolCalls = [],
}: ToolCallInspectorProps) {
  return (
    <details className="run-detail-block run-detail-fold run-tool-calls" data-testid="agent-run-detail-tool-calls" open={toolCalls.length > 0}>
      <summary className="run-detail-section-head">
        <div>
          <h4>Tool Calls · {toolCalls.length}</h4>
          <span>{sourceLabel}</span>
        </div>
      </summary>
      <div className="run-detail-fold-body run-tool-call-list" data-testid="agent-run-detail-tool-call-list">
        {toolCalls.map((toolCall) => (
          <RuntimeToolCallCard
            key={toolCall.tool_call_id}
            toolCall={toolCall}
            className="studio-runtime-tool-call"
            testId="agent-run-detail-tool-call-card"
          />
        ))}
        {!toolCalls.length ? <span>No tool calls</span> : null}
      </div>
    </details>
  );
}
