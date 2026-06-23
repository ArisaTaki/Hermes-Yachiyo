import { RuntimeToolCallSummary } from '../../runtime-shared/components/RuntimeToolCallSummary';
import type { PublicRunEvent, ToolCallSnapshot } from '../types';

export function ToolCallSummary({
  events,
  limit = 4,
  toolCalls = [],
}: {
  events: PublicRunEvent[];
  limit?: number;
  toolCalls?: ToolCallSnapshot[];
}) {
  return (
    <RuntimeToolCallSummary
      className="yachiyo-agent-task-tools"
      events={events}
      itemClassName="yachiyo-agent-task-tool"
      itemTestId="yachiyo-agent-task-tool-summary-item"
      label="能力"
      limit={limit}
      testId="yachiyo-agent-task-tool-summary"
      toolCalls={toolCalls}
    />
  );
}
