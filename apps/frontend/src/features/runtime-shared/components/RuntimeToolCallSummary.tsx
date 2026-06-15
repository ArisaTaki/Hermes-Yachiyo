import type { PublicRunEvent } from '../types';

export type RuntimeToolCallSummaryItem = {
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
  'skill.selected',
  'skill.dispatch.read',
  'memory.retrieved',
  'memory.write.add',
  'memory.write.replace',
  'memory.write.remove',
]);

export function RuntimeToolCallSummary({
  className = 'runtime-tool-call-summary',
  events,
  itemClassName = 'runtime-tool-call-summary-item',
  itemTestId = 'runtime-tool-call-summary-item',
  label = '工具',
  limit = 4,
  testId = 'runtime-tool-call-summary',
}: {
  className?: string;
  events: PublicRunEvent[];
  itemClassName?: string;
  itemTestId?: string;
  label?: string;
  limit?: number;
  testId?: string;
}) {
  const tools = summarizeRuntimeToolCalls(events, limit);
  if (!tools.length) return null;

  return (
    <div className={className} data-testid={testId}>
      <span>{label}</span>
      <div>
        {tools.map((tool) => (
          <span
            className={`${itemClassName} status-${tool.status}`}
            data-testid={itemTestId}
            data-tool-name={tool.name}
            data-tool-status={tool.status}
            key={tool.name}
          >
            <strong>{tool.name}</strong>
            {tool.count > 1 ? <em>x{tool.count}</em> : null}
            <small>{runtimeToolStatusLabel(tool.status)}</small>
          </span>
        ))}
      </div>
    </div>
  );
}

export function summarizeRuntimeToolCalls(
  events: PublicRunEvent[],
  limit: number,
): RuntimeToolCallSummaryItem[] {
  const byName = new Map<string, RuntimeToolCallSummaryItem>();
  for (const event of events || []) {
    const eventType = String(event.event_type || '').trim();
    if (!TOOL_EVENT_TYPES.has(eventType)) continue;

    const name = runtimeToolNameFromEvent(event);
    const sequence = Number.isFinite(event.sequence) ? Number(event.sequence) : 0;
    const status = runtimeToolStatusFromEvent(event);
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

function runtimeToolNameFromEvent(event: PublicRunEvent): string {
  const eventType = String(event.event_type || '').trim();
  if (eventType === 'memory.retrieved') return 'Memory 检索';
  if (eventType.startsWith('memory.write.')) {
    return (
      stringPayload(objectPayload(event.payload, 'result'), 'action') ||
      stringPayload(event.payload, 'tool') ||
      'Memory 写入'
    );
  }
  if (eventType === 'skill.selected' || eventType.startsWith('skill.dispatch.')) {
    return (
      stringPayload(objectPayload(event.payload, 'result'), 'name') ||
      stringPayload(event.payload, 'skill_name') ||
      stringPayload(objectPayload(event.payload, 'result'), 'skill_id') ||
      stringPayload(event.payload, 'skill_id') ||
      stringPayload(event.payload, 'tool') ||
      'Skill'
    );
  }
  const fallbackName = String(event.detail || event.title || 'tool').trim();
  return (
    stringPayload(event.payload, 'tool_name') ||
    stringPayload(event.payload, 'tool') ||
    stringPayload(event.payload, 'name') ||
    fallbackName ||
    'tool'
  );
}

function runtimeToolStatusFromEvent(event: PublicRunEvent): string {
  const payloadStatus = normalizeRuntimeToolStatus(stringPayload(event.payload, 'status'));
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
    eventType === 'tool.completed' ||
    eventType === 'skill.selected' ||
    eventType === 'memory.retrieved'
  ) {
    return 'completed';
  }
  if (eventType.startsWith('skill.dispatch.') || eventType.startsWith('memory.write.')) {
    return 'completed';
  }
  if (eventType === 'tool.started') return 'running';
  if (eventType === 'tool.requested') return 'queued';
  return 'running';
}

function normalizeRuntimeToolStatus(status: string): string {
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

function objectPayload(payload: Record<string, unknown> | undefined, key: string): Record<string, unknown> | undefined {
  const value = payload?.[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function runtimeToolStatusLabel(status: string): string {
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
