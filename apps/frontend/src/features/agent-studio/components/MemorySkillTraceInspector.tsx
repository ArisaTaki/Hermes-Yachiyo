import { ExpandableRuntimeContent } from '../../runtime-shared/components/ExpandableRuntimeContent';
import type { PublicRunEvent } from '../../yachiyo-studio/types';

type MemorySkillTrace = {
  count: string;
  detail: string;
  eventType: string;
  id: string;
  key: string;
  kind: 'memory' | 'skill';
  payload: string;
  sequence: string;
  status: string;
  title: string;
  tool: string;
};

type MemorySkillTraceInspectorProps = {
  events?: PublicRunEvent[];
  sourceLabel?: string;
};

export function MemorySkillTraceInspector({
  events = [],
  sourceLabel = 'Memory 检索、写入和 Skill 调度的 Runtime 事实',
}: MemorySkillTraceInspectorProps) {
  const traces = events.map(memorySkillTraceFromEvent).filter((trace): trace is MemorySkillTrace => Boolean(trace));
  return (
    <details
      className="run-detail-block run-detail-fold run-memory-skill-traces"
      data-testid="agent-run-detail-memory-skill-traces"
      open={traces.length > 0}
    >
      <summary className="run-detail-section-head">
        <div>
          <h4>Memory / Skill Trace · {traces.length}</h4>
          <span>{sourceLabel}</span>
        </div>
      </summary>
      <div className="run-detail-fold-body run-memory-skill-trace-list" data-testid="agent-run-detail-memory-skill-trace-list">
        {traces.map((trace) => (
          <article
            className={`run-memory-skill-trace ${trace.kind} ${traceStatusTone(trace.status)}`}
            data-run-event={trace.eventType}
            data-run-event-sequence={trace.sequence}
            data-runtime-trace-kind={trace.kind}
            data-testid="agent-run-detail-memory-skill-trace"
            key={trace.key}
          >
            <div>
              <span>{trace.kind === 'memory' ? 'Memory' : 'Skill'}</span>
              <strong>{trace.title}</strong>
              {trace.detail ? <p>{trace.detail}</p> : null}
            </div>
            <div className="run-memory-skill-trace-meta">
              {trace.status ? <em>{traceStatusLabel(trace.status)}</em> : null}
              {trace.tool ? <code>{trace.tool}</code> : null}
              {trace.id ? <code>{trace.id}</code> : null}
              {trace.count ? <span>{trace.count}</span> : null}
              {trace.sequence ? <span>#{trace.sequence}</span> : null}
            </div>
            {trace.payload ? (
              <ExpandableRuntimeContent
                content={trace.payload}
                label="展开完整 Trace payload"
                defaultOpen={trace.status === 'failed'}
              />
            ) : null}
          </article>
        ))}
        {!traces.length ? <span>No memory or skill trace events</span> : null}
      </div>
    </details>
  );
}

function memorySkillTraceFromEvent(event: PublicRunEvent): MemorySkillTrace | null {
  const eventType = String(event.event_type || '').trim();
  const kind = eventType.startsWith('memory.') ? 'memory' : eventType.startsWith('skill.') ? 'skill' : null;
  if (!kind) return null;

  const payload = objectRecord(event.payload);
  const result = objectRecord(payload.result);
  const memories = Array.isArray(payload.memories) ? payload.memories.map(objectRecord) : [];
  const sequence = Number.isFinite(event.sequence) ? String(event.sequence) : '';
  const status = normalizeTraceStatus(stringValue(payload.status) || stringValue((event as Record<string, unknown>).status));
  const id = kind === 'memory'
    ? stringValue(result.memory_id) || stringValue(memories[0]?.memory_id)
    : stringValue(result.skill_id) || stringValue(payload.skill_id);
  const title = traceTitle(eventType, payload, result, memories);
  const detail = stringValue(event.detail) || traceDetail(eventType, payload, result, memories);
  const count = eventType === 'memory.retrieved' ? traceMemoryCount(payload, memories) : '';
  return {
    count,
    detail,
    eventType,
    id,
    key: stringValue(event.event_id) || `${eventType}-${sequence || title}-${id}`,
    kind,
    payload: JSON.stringify(payload, null, 2),
    sequence,
    status,
    title,
    tool: stringValue(payload.tool),
  };
}

function traceTitle(
  eventType: string,
  payload: Record<string, unknown>,
  result: Record<string, unknown>,
  memories: Array<Record<string, unknown>>,
): string {
  if (eventType === 'memory.retrieved') return 'Memory 检索';
  if (eventType === 'memory.write.add') return 'Memory 新增';
  if (eventType === 'memory.write.replace') return 'Memory 更新';
  if (eventType === 'memory.write.remove') return 'Memory 删除';
  if (eventType === 'skill.selected') {
    return stringValue(result.name) || stringValue(payload.skill_name) || stringValue(result.skill_id) || 'Skill 已选择';
  }
  if (eventType === 'skill.dispatch.read') {
    return stringValue(result.name) || stringValue(result.skill_id) || 'Skill 调度';
  }
  return stringValue(result.name) || stringValue(memories[0]?.kind) || eventType;
}

function traceDetail(
  eventType: string,
  payload: Record<string, unknown>,
  result: Record<string, unknown>,
  memories: Array<Record<string, unknown>>,
): string {
  if (eventType === 'memory.retrieved') {
    const scopes = new Set(memories.map((memory) => stringValue(memory.scope)).filter(Boolean));
    const kinds = new Set(memories.map((memory) => stringValue(memory.kind)).filter(Boolean));
    return [traceMemoryCount(payload, memories), Array.from(kinds).join(', '), Array.from(scopes).join(', ')]
      .filter(Boolean)
      .join(' · ');
  }
  if (eventType.startsWith('memory.write.')) {
    return [stringValue(result.action), stringValue(result.kind), stringValue(result.scope)]
      .filter(Boolean)
      .join(' · ');
  }
  if (eventType.startsWith('skill.')) {
    return [
      stringValue(result.description),
      stringValue(result.source_ref),
      stringValue(result.source_type),
    ].filter(Boolean).join(' · ');
  }
  return '';
}

function traceMemoryCount(payload: Record<string, unknown>, memories: Array<Record<string, unknown>>): string {
  const count = typeof payload.count === 'number' && Number.isFinite(payload.count)
    ? payload.count
    : memories.length;
  return count ? `${count} memories` : '';
}

function traceStatusTone(status: string): string {
  if (status === 'failed') return 'danger';
  if (status === 'completed') return 'ready';
  if (status === 'running' || status === 'queued') return 'running';
  return 'neutral';
}

function traceStatusLabel(status: string): string {
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'running') return '执行中';
  if (status === 'queued') return '已请求';
  return status;
}

function normalizeTraceStatus(status: string): string {
  if (status === 'ok') return 'completed';
  return status;
}

function objectRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
