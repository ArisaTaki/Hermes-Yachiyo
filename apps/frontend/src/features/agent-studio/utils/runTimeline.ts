import type { RunEventSpec } from '../../../lib/agents';

export function timelineChildRunId(event: Record<string, unknown>): string {
  const value = event.child_run_id;
  return typeof value === 'string' ? value.trim() : '';
}

export function timelineStatus(event: Record<string, unknown>): string {
  const value = event.status;
  return typeof value === 'string' ? value.trim() : '';
}

export function timelineEventTitle(event: Record<string, unknown>): string {
  const name = String(event.event || 'event');
  const detail = String(event.detail || '').trim();
  if (name === 'run.started') return 'Run 已启动';
  if (name === 'task.linked') return 'Task 已关联';
  if (name === 'model.request.started') return detail ? `模型请求 · ${detail}` : '模型请求已开始';
  if (name === 'model.request.failed') return '模型请求失败';
  if (name === 'model.output.ready') return '模型输出已就绪';
  if (name === 'model.output.completed') return '模型输出完成';
  if (name === 'agent.run.started') return 'Agent 已启动';
  if (name === 'agent.runtime.compiled') return '运行环境已准备';
  if (name === 'agent.artifact.write') return '上下文/产物已写入';
  if (name === 'agent.model.response') return '模型响应';
  if (name === 'agent.tool.call') return detail ? `工具调用 · ${detail}` : '工具调用';
  if (name === 'agent.tool.skipped') return detail ? `工具已跳过 · ${detail}` : '工具已跳过';
  if (name === 'agent.tool.denied') return detail ? `工具已拒绝 · ${detail}` : '工具已拒绝';
  if (name === 'agent.tool.failed') return detail ? `工具调用失败 · ${detail}` : '工具调用失败';
  if (name === 'agent.tool.approval_required') return detail ? `请求审批 · ${detail}` : '请求审批';
  if (name === 'agent.tool.approval_approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';
  if (name === 'agent.tool.approval_rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';
  if (name === 'skill.dispatch.read') return detail ? `Skill 调度 · ${detail}` : 'Skill 调度';
  if (name === 'memory.write.add') return detail ? `Memory 新增 · ${detail}` : 'Memory 新增';
  if (name === 'memory.write.replace') return detail ? `Memory 更新 · ${detail}` : 'Memory 更新';
  if (name === 'memory.write.remove') return detail ? `Memory 删除 · ${detail}` : 'Memory 删除';
  if (name === 'approval.timeout') return '审批已超时';
  if (name === 'agent.run.resumed') return 'Agent 已继续执行';
  if (name === 'agent.run.completed') return 'Run 已完成';
  if (name === 'agent.run.cancelled') return 'Agent 已取消';
  if (name === 'agent.run.failed') return 'Run 执行失败';
  if (name === 'run.cancelled') return 'Run 已取消';
  if (name === 'run.completed') return 'Run 已完成';
  if (name === 'run.failed') return 'Run 执行失败';
  if (name === 'run.rerun.started') return '从原 Run 重跑';
  if (name === 'group.member.started') return detail ? `群组成员启动 · ${detail}` : '群组成员启动';
  if (name === 'group.member.completed') return detail ? `群组成员完成 · ${detail}` : '群组成员完成';
  if (name === 'workflow.run.started') return 'Workflow 已启动';
  if (name === 'workflow.node.start') return 'Workflow 起点';
  if (name === 'workflow.node.agent') return detail ? `Agent 节点 · ${detail}` : 'Agent 节点';
  if (name === 'workflow.node.workflow') return detail ? `子 Workflow · ${detail}` : '子 Workflow';
  if (name === 'workflow.node.condition') return detail ? `条件节点 · ${detail}` : '条件节点';
  if (name === 'workflow.node.parallel') return detail ? `并行节点 · ${detail}` : '并行节点';
  if (name === 'workflow.node.loop') return detail ? `循环节点 · ${detail}` : '循环节点';
  if (name === 'workflow.node.artifact') return detail ? `产物节点 · ${detail}` : '产物节点';
  if (name === 'workflow.node.approval_required') return detail ? `人工审批 · ${detail}` : '人工审批';
  if (name === 'workflow.node.approval_approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';
  if (name === 'workflow.node.approval_rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';
  if (name === 'workflow.edge.followed') return detail ? `Workflow 路由 · ${detail}` : 'Workflow 路由';
  if (name === 'workflow.run.approval_required') return 'Workflow 等待审批';
  if (name === 'workflow.run.child_resumed') return '子 Agent 已继续执行';
  if (name === 'workflow.run.resumed') return 'Workflow 已继续执行';
  if (name === 'workflow.run.completed') return 'Workflow 已完成';
  if (name === 'workflow.run.failed') return 'Workflow 执行失败';
  if (name === 'workflow.run.cancelled') return 'Workflow 已取消';
  return name;
}

export function timelineEventTone(event: Record<string, unknown>): string {
  const name = String(event.event || '');
  const status = timelineStatus(event);
  if (
    status === 'failed'
    || status === 'cancelled'
    || name.includes('failed')
    || name.includes('cancelled')
    || name.includes('timeout')
    || name.includes('denied')
  ) return 'danger';
  if (status === 'completed' || name.includes('completed')) return 'ready';
  if (status === 'approval_required' || name.includes('approval')) return 'approval';
  if (status === 'running' || status === 'processing' || name.includes('resumed')) return 'running';
  if (name.startsWith('group.member.')) return name.includes('started') ? 'running' : 'ready';
  if (name.startsWith('skill.') || name.startsWith('memory.')) return 'tool';
  if (name.includes('tool')) return 'tool';
  if (name.startsWith('model.') || name.includes('model.response')) return 'model';
  return 'neutral';
}

export function timelineEventCode(event: Record<string, unknown>): string {
  const name = timelineEventName(event);
  return name.includes('.') ? name.split('.').slice(-2).join('.') : name || 'event';
}

export function timelineEventName(event: Record<string, unknown>): string {
  return String(event.event || '').trim();
}

export function timelineEventSequence(event: Record<string, unknown>): string {
  const value = event.sequence;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return typeof value === 'string' ? value.trim() : '';
}

export function timelineEventTime(event: Record<string, unknown>): string {
  return typeof event.time === 'string' ? event.time : '';
}

function formatTimelinePayload(value: unknown): string {
  if (!value) return '';
  if (typeof value === 'string') return String(value).trim();
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value).trim();
  }
}

export function timelineEventPayload(event: Record<string, unknown>): string {
  const inputPreview = event.input_preview;
  const result = event.result;
  if (inputPreview && result) {
    return [
      `请求内容：\n${formatTimelinePayload(inputPreview)}`,
      `执行结果：\n${formatTimelinePayload(result)}`,
    ].join('\n\n');
  }
  if (inputPreview) return `请求内容：\n${formatTimelinePayload(inputPreview)}`;
  if (result) return formatTimelinePayload(result);
  const pendingApproval = event.pending_approval;
  if (pendingApproval) return formatTimelinePayload(pendingApproval);
  return '';
}

export function runEventReplayToTimelineEvent(event: RunEventSpec): Record<string, unknown> {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const detail = typeof payload.tool === 'string'
    ? payload.tool
    : typeof payload.model === 'string'
      ? payload.model
      : typeof payload.result === 'string'
        ? payload.result
        : typeof payload.error === 'string'
          ? payload.error
          : typeof payload.workflow_node_label === 'string'
            ? payload.workflow_node_label
            : '';
  return {
    event_id: event.event_id || '',
    run_id: event.run_id,
    schema_version: event.schema_version || '',
    event: event.event_type,
    actor: event.actor || '',
    visibility: event.visibility || '',
    sensitivity: event.sensitivity || '',
    detail,
    status: typeof payload.status === 'string' ? payload.status : '',
    time: event.created_at || '',
    sequence: event.sequence,
    input_preview: payload.input_preview,
    result: payload.result || payload.content || payload.error || '',
    pending_approval: payload.pending_approval || payload,
    child_run_id: payload.child_run_id,
    workflow_node_id: payload.workflow_node_id,
    workflow_node_kind: payload.workflow_node_kind,
    workflow_node_label: payload.workflow_node_label,
    payload,
  };
}

export function mergeRunEventReplayPages(
  current: RunEventSpec[],
  incoming: RunEventSpec[],
): RunEventSpec[] {
  const bySequence = new Map<number, RunEventSpec>();
  current.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  incoming.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  return Array.from(bySequence.values()).sort(
    (left, right) => (Number(left.sequence) || 0) - (Number(right.sequence) || 0),
  );
}
