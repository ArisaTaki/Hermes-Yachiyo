import type { PublicRunEvent } from '../types';

type ToolCallSummaryItem = {
  count: number;
  name: string;
  sequence: number;
  status: string;
};

const TOOL_EVENT_TYPES = new Set([
  'agent.tool.call',
  'agent.tool.denied',
  'agent.tool.failed',
  'agent.tool.skipped',
  'agent.tool.approval_required',
  'agent.tool.approval_approved',
  'agent.tool.approval_rejected',
  'tool.requested',
  'tool.started',
  'tool.approval_required',
  'tool.completed',
  'agent.tool.completed',
  'tool.failed',
]);

export function ToolCallSummary({
  events,
  limit = 4,
}: {
  events: PublicRunEvent[];
  limit?: number;
}) {
  const tools = summarizeToolCalls(events, limit);
  if (!tools.length) return null;

  return (
    <div className="yachiyo-agent-task-tools" data-testid="yachiyo-agent-task-tool-summary">
      <span>工具</span>
      <div>
        {tools.map((tool) => (
          <span
            className={`yachiyo-agent-task-tool status-${tool.status}`}
            data-testid="yachiyo-agent-task-tool-summary-item"
            data-tool-name={tool.name}
            data-tool-status={tool.status}
            key={tool.name}
          >
            <strong>{tool.name}</strong>
            {tool.count > 1 ? <em>x{tool.count}</em> : null}
            <small>{toolStatusLabel(tool.status)}</small>
          </span>
        ))}
      </div>
    </div>
  );
}

function summarizeToolCalls(events: PublicRunEvent[], limit: number): ToolCallSummaryItem[] {
  const byName = new Map<string, ToolCallSummaryItem>();
  for (const event of events || []) {
    const eventType = String(event.event_type || '').trim();
    if (!TOOL_EVENT_TYPES.has(eventType)) continue;

    const name = toolNameFromEvent(event);
    const sequence = Number.isFinite(event.sequence) ? Number(event.sequence) : 0;
    const status = toolStatusFromEvent(event);
    const previous = byName.get(name);
    if (previous) {
      previous.count += 1;
      if (sequence >= previous.sequence) {
        previous.sequence = sequence;
        previous.status = status;
      }
      continue;
    }

    byName.set(name, { count: 1, name, sequence, status });
  }

  return Array.from(byName.values())
    .sort((left, right) => right.sequence - left.sequence)
    .slice(0, Math.max(1, limit));
}

function toolNameFromEvent(event: PublicRunEvent): string {
  const fallbackName = String(event.detail || event.title || 'tool').trim();
  return (
    stringPayload(event.payload, 'tool_name') ||
    stringPayload(event.payload, 'tool') ||
    stringPayload(event.payload, 'name') ||
    fallbackName ||
    'tool'
  );
}

function toolStatusFromEvent(event: PublicRunEvent): string {
  const payloadStatus = normalizeToolStatus(stringPayload(event.payload, 'status'));
  if (payloadStatus) return payloadStatus;

  const eventType = String(event.event_type || '').trim();
  if (eventType === 'agent.tool.denied') return 'denied';
  if (eventType === 'agent.tool.failed' || eventType === 'tool.failed') return 'failed';
  if (eventType === 'agent.tool.skipped') return 'skipped';
  if (eventType === 'agent.tool.approval_required' || eventType === 'tool.approval_required') {
    return 'waiting_approval';
  }
  if (eventType === 'agent.tool.approval_approved') return 'approved';
  if (eventType === 'agent.tool.approval_rejected') return 'denied';
  if (
    eventType === 'agent.tool.call' ||
    eventType === 'agent.tool.completed' ||
    eventType === 'tool.completed'
  ) {
    return 'completed';
  }
  if (eventType === 'tool.started') return 'running';
  if (eventType === 'tool.requested') return 'queued';
  return 'running';
}

function normalizeToolStatus(status: string): string {
  if (!status) return '';
  if (status === 'approval_required') return 'waiting_approval';
  if (status === 'cancelled') return 'failed';
  const knownStatuses = [
    'queued',
    'running',
    'waiting_approval',
    'approved',
    'completed',
    'failed',
    'denied',
    'skipped',
  ];
  if (knownStatuses.includes(status)) {
    return status;
  }
  return 'running';
}

function stringPayload(payload: Record<string, unknown> | undefined, key: string): string {
  const value = payload?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

function toolStatusLabel(status: string): string {
  if (status === 'queued') return '已请求';
  if (status === 'running') return '执行中';
  if (status === 'waiting_approval') return '待审批';
  if (status === 'approved') return '已批准';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'denied') return '已拒绝';
  if (status === 'skipped') return '已跳过';
  return status || '工具';
}
