import { RuntimeToolCallCard } from '../../runtime-shared/components/RuntimeToolCallCard';
import type { RuntimeToolRecoveryAction } from '../../runtime-shared/toolRecoveryActions';
import type { ToolCallSnapshot } from '../../yachiyo-studio/types';

type ToolCallInspectorProps = {
  cardTestId?: string;
  listTestId?: string;
  onRunRecoveryAction?: (
    toolCall: ToolCallSnapshot,
    action: RuntimeToolRecoveryAction,
  ) => unknown | Promise<unknown>;
  recoveryActionInputPatch?: (
    toolCall: ToolCallSnapshot,
    action: RuntimeToolRecoveryAction,
  ) => Record<string, unknown> | null | undefined;
  recoveryActionDisabled?: boolean;
  sourceLabel?: string;
  testId?: string;
  toolCalls?: ToolCallSnapshot[];
};

export function ToolCallInspector({
  cardTestId = 'agent-run-detail-tool-call-card',
  listTestId = 'agent-run-detail-tool-call-list',
  onRunRecoveryAction,
  recoveryActionInputPatch,
  recoveryActionDisabled = false,
  sourceLabel = '工具调用、审批关联和输入输出预览',
  testId = 'agent-run-detail-tool-calls',
  toolCalls = [],
}: ToolCallInspectorProps) {
  return (
    <details className="run-detail-block run-detail-fold run-tool-calls" data-testid={testId} open={toolCalls.length > 0}>
      <summary className="run-detail-section-head">
        <div>
          <h4>Tool Calls · {toolCalls.length}</h4>
          <span>{sourceLabel}</span>
        </div>
      </summary>
      <div className="run-detail-fold-body run-tool-call-list" data-testid={listTestId}>
        {toolCalls.map((toolCall) => (
          <RuntimeToolCallCard
            key={toolCall.tool_call_id}
            toolCall={toolCall}
            className="studio-runtime-tool-call"
            onRunRecoveryAction={onRunRecoveryAction}
            recoveryActionInputPatch={recoveryActionInputPatch}
            recoveryActionDisabled={recoveryActionDisabled}
            testId={cardTestId}
          />
        ))}
        {!toolCalls.length ? <span>No tool calls</span> : null}
      </div>
    </details>
  );
}
