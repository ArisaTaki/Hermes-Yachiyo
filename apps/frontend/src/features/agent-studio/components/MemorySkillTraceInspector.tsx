import { ExpandableRuntimeContent } from '../../runtime-shared/components/ExpandableRuntimeContent';
import { publicRunEventIsSecret } from '../../runtime-shared/runEvents';
import type { MemoryTraceSnapshot, PublicRunEvent, SkillTraceSnapshot } from '../../yachiyo-studio/types';

type MemorySkillTrace = {
  count: string;
  detail: string;
  eventType: string;
  groupRunId: string;
  id: string;
  key: string;
  kind: 'memory' | 'skill';
  memberAgentId: string;
  metadata: MemorySkillTraceMetadataItem[];
  memoryId: string;
  payload: string;
  sequence: string;
  skillId: string;
  status: string;
  title: string;
  tool: string;
  workflowNodeId: string;
};

type MemorySkillTraceMetadataItem = {
  key: string;
  label: string;
  value: string;
};

type MemorySkillTraceInspectorProps = {
  events?: PublicRunEvent[];
  memoryTraces?: MemoryTraceSnapshot[];
  skillTraces?: SkillTraceSnapshot[];
  sourceLabel?: string;
};

export function MemorySkillTraceInspector({
  events = [],
  memoryTraces = [],
  skillTraces = [],
  sourceLabel = 'Memory 检索、写入和 Skill 调度的 Runtime 事实',
}: MemorySkillTraceInspectorProps) {
  const traces = mergeMemorySkillTraces(
    [
      ...memoryTraces.map(memorySkillTraceFromMemorySnapshot),
      ...skillTraces.map(memorySkillTraceFromSkillSnapshot),
    ],
    events.map(memorySkillTraceFromEvent).filter((trace): trace is MemorySkillTrace => Boolean(trace)),
  );
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
            data-group-run-id={trace.groupRunId}
            data-member-agent-id={trace.memberAgentId}
            data-memory-id={trace.memoryId}
            data-runtime-trace-kind={trace.kind}
            data-skill-id={trace.skillId}
            data-testid="agent-run-detail-memory-skill-trace"
            data-workflow-node-id={trace.workflowNodeId}
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
            {trace.metadata.length ? (
              <div
                className="run-memory-skill-trace-context"
                data-testid="agent-run-detail-memory-skill-trace-context"
              >
                {trace.metadata.map((item) => (
                  <span data-trace-context={item.key} key={item.key}>
                    <small>{item.label}</small>
                    <code>{item.value}</code>
                  </span>
                ))}
              </div>
            ) : null}
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

function mergeMemorySkillTraces(
  snapshotTraces: MemorySkillTrace[],
  eventTraces: MemorySkillTrace[],
): MemorySkillTrace[] {
  const byKey = new Map<string, MemorySkillTrace>();
  snapshotTraces.forEach((trace) => byKey.set(trace.key, trace));
  eventTraces.forEach((trace) => {
    if (!byKey.has(trace.key)) byKey.set(trace.key, trace);
  });
  return Array.from(byKey.values());
}

function memorySkillTraceFromMemorySnapshot(trace: MemoryTraceSnapshot): MemorySkillTrace {
  const sequence = Number.isFinite(trace.sequence) ? String(trace.sequence) : '';
  return {
    count: trace.count ? `${trace.count} memories` : '',
    detail: trace.detail || '',
    eventType: trace.event_type,
    groupRunId: trace.group_run_id || '',
    id: trace.memory_id || '',
    key: trace.trace_id,
    kind: 'memory',
    memberAgentId: trace.source_runnable_id || '',
    metadata: memorySkillTraceMetadataFromMemorySnapshot(trace),
    memoryId: trace.memory_id || '',
    payload: formatTracePayload(trace.payload_preview),
    sequence,
    skillId: '',
    status: normalizeTraceStatus(trace.status || ''),
    title: trace.title,
    tool: '',
    workflowNodeId: trace.workflow_node_id || '',
  };
}

function memorySkillTraceFromSkillSnapshot(trace: SkillTraceSnapshot): MemorySkillTrace {
  const sequence = Number.isFinite(trace.sequence) ? String(trace.sequence) : '';
  return {
    count: '',
    detail: trace.detail || '',
    eventType: trace.event_type,
    groupRunId: trace.group_run_id || '',
    id: trace.skill_id || '',
    key: trace.trace_id,
    kind: 'skill',
    memberAgentId: trace.source_runnable_id || '',
    metadata: memorySkillTraceMetadataFromSkillSnapshot(trace),
    memoryId: '',
    payload: formatTracePayload(trace.payload_preview),
    sequence,
    skillId: trace.skill_id || '',
    status: normalizeTraceStatus(trace.status || ''),
    title: trace.title,
    tool: trace.tool_name || '',
    workflowNodeId: trace.workflow_node_id || '',
  };
}

function memorySkillTraceFromEvent(event: PublicRunEvent): MemorySkillTrace | null {
  const eventType = String(event.event_type || '').trim();
  const kind = eventType.startsWith('memory.') ? 'memory' : eventType.startsWith('skill.') ? 'skill' : null;
  if (!kind) return null;

  const payload = objectRecord(event.payload);
  const eventIsSecret = publicRunEventIsSecret(event);
  const visiblePayload = eventIsSecret ? {} : payload;
  const result = objectRecord(visiblePayload.result);
  const skill = objectRecord(visiblePayload.skill || result.skill);
  const traceResult = Object.keys(skill).length ? { ...skill, ...result } : result;
  const payloadMemories = Array.isArray(visiblePayload.memories) ? visiblePayload.memories.map(objectRecord) : [];
  const resultMemories = Array.isArray(result.memories) ? result.memories.map(objectRecord) : [];
  const memories = payloadMemories.length ? payloadMemories : resultMemories;
  const sequence = Number.isFinite(event.sequence) ? String(event.sequence) : '';
  const status = normalizeTraceStatus(
    stringValue(visiblePayload.status) || stringValue((event as Record<string, unknown>).status),
  );
  const memoryId = stringValue(traceResult.memory_id) || stringValue(visiblePayload.memory_id) || stringValue(memories[0]?.memory_id);
  const skillId = stringValue(traceResult.skill_id) || stringValue(visiblePayload.skill_id);
  const id = kind === 'memory' ? memoryId : skillId;
  const title = traceTitle(eventType, visiblePayload, traceResult, memories);
  const detail = eventIsSecret
    ? ''
    : stringValue(event.detail) || traceDetail(eventType, visiblePayload, traceResult, memories);
  const count = eventType === 'memory.retrieved' ? traceMemoryCount(visiblePayload, memories) : '';
  const groupRunId = stringValue(visiblePayload.group_run_id) || stringValue(visiblePayload.run_group_id);
  const memberAgentId = stringValue(visiblePayload.member_agent_id);
  const workflowNodeId = stringValue(visiblePayload.workflow_node_id);
  return {
    count,
    detail,
    eventType,
    groupRunId,
    id,
    key: runtimeTraceKeyFromEvent(event, eventType, sequence, title, id),
    kind,
    memberAgentId,
    metadata: eventIsSecret ? [] : memorySkillTraceMetadata(kind, visiblePayload, traceResult, memories),
    memoryId,
    payload: eventIsSecret ? '' : JSON.stringify(payload, null, 2),
    sequence,
    skillId,
    status,
    title,
    tool: stringValue(visiblePayload.tool),
    workflowNodeId,
  };
}

function runtimeTraceKeyFromEvent(
  event: PublicRunEvent,
  eventType: string,
  sequence: string,
  title: string,
  id: string,
): string {
  const eventId = stringValue(event.event_id);
  if (eventId) return eventId;
  const runId = stringValue(event.run_id);
  if (runId && eventType && sequence) return `${runId}:${eventType}:${sequence}`;
  return `${eventType}-${sequence || title}-${id}`;
}

function memorySkillTraceMetadataFromMemorySnapshot(trace: MemoryTraceSnapshot): MemorySkillTraceMetadataItem[] {
  return traceMetadataItems([
    ['memory', trace.memory_id || ''],
    ['kind', trace.memory_kind || ''],
    ['scope', trace.memory_scope || ''],
    ['workflow', trace.workflow_node_label || trace.workflow_node_id || ''],
    ['member', trace.source_runnable_name || trace.source_runnable_id || ''],
    ['group', trace.group_run_id || trace.group_id || ''],
  ]);
}

function memorySkillTraceMetadataFromSkillSnapshot(trace: SkillTraceSnapshot): MemorySkillTraceMetadataItem[] {
  return traceMetadataItems([
    ['skill', trace.skill_name || trace.skill_id || ''],
    ['source', trace.source_ref || trace.source_type || ''],
    ['workflow', trace.workflow_node_label || trace.workflow_node_id || ''],
    ['member', trace.source_runnable_name || trace.source_runnable_id || ''],
    ['group', trace.group_run_id || trace.group_id || ''],
  ]);
}

function memorySkillTraceMetadata(
  kind: MemorySkillTrace['kind'],
  payload: Record<string, unknown>,
  result: Record<string, unknown>,
  memories: Array<Record<string, unknown>>,
): MemorySkillTraceMetadataItem[] {
  const firstMemory = memories[0] || {};
  const candidates = kind === 'memory'
    ? [
      ['memory', stringValue(result.memory_id) || stringValue(payload.memory_id) || stringValue(firstMemory.memory_id)],
      ['kind', stringValue(result.kind) || stringValue(payload.memory_kind) || stringValue(firstMemory.kind)],
      ['scope', stringValue(result.scope) || stringValue(payload.scope) || stringValue(firstMemory.scope)],
      ['workflow', stringValue(payload.workflow_node_label) || stringValue(payload.workflow_node_id)],
      ['member', stringValue(payload.member_agent_name) || stringValue(payload.member_agent_id)],
      ['group', stringValue(payload.group_run_id) || stringValue(payload.run_group_id) || stringValue(payload.group_id)],
    ]
    : [
      ['skill', stringValue(result.name) || stringValue(payload.skill_name) || stringValue(result.skill_id) || stringValue(payload.skill_id)],
      ['source', stringValue(result.source_ref) || stringValue(result.source_type)],
      ['workflow', stringValue(payload.workflow_node_label) || stringValue(payload.workflow_node_id)],
      ['member', stringValue(payload.member_agent_name) || stringValue(payload.member_agent_id)],
      ['group', stringValue(payload.group_run_id) || stringValue(payload.run_group_id) || stringValue(payload.group_id)],
    ];
  return traceMetadataItems(candidates);
}

function traceMetadataItems(candidates: string[][]): MemorySkillTraceMetadataItem[] {
  return candidates
    .map(([label, value]) => ({ key: `${label}:${value}`, label, value }))
    .filter((item) => Boolean(item.value));
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

function formatTracePayload(value: Record<string, unknown> | undefined): string {
  if (!value || !Object.keys(value).length) return '';
  return JSON.stringify(value, null, 2);
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
