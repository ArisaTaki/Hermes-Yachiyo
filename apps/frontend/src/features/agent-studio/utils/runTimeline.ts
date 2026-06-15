import type { ApprovalCardSnapshot, PublicRunEvent, ToolCallSnapshot } from '../../yachiyo-studio/types';

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
  if (name === 'skill.selected') return detail ? `Skill 已选择 · ${detail}` : 'Skill 已选择';
  if (name === 'skill.dispatch.read') return detail ? `Skill 调度 · ${detail}` : 'Skill 调度';
  if (name === 'memory.retrieved') return detail ? `Memory 检索 · ${detail}` : 'Memory 检索';
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
  if (name === 'group.approval_required') return detail ? `群组审批 · ${detail}` : '群组审批';
  if (name === 'group.member.approval_required') return detail ? `成员审批 · ${detail}` : '成员审批';
  if (name === 'group.artifact.created') return detail ? `群组产物 · ${detail}` : '群组产物';
  if (name === 'group.shared_artifact.created') return detail ? `群组共享产物 · ${detail}` : '群组共享产物';
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
  if (name === 'group.artifact.created' || name === 'group.shared_artifact.created') return 'ready';
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
  const payload = event.payload;
  if (payload && typeof payload === 'object') {
    return `事件内容：\n${formatTimelinePayload(payload)}`;
  }
  return '';
}

export function publicRunEventPayloadDetail(event: PublicRunEvent): string {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  return (
    event.detail
    || event.title
    || publicRunEventPayloadString(payload, 'tool_name')
    || publicRunEventPayloadString(payload, 'tool')
    || publicRunEventPayloadString(payload, 'model')
    || publicRunEventPayloadString(payload, 'workflow_node_label')
    || publicRunEventPayloadString(payload, 'workflow_node_id')
    || publicRunEventPayloadString(payload, 'skill_name')
    || publicRunEventPayloadString(payload, 'skill_id')
    || publicRunEventMemorySummary(payload)
    || publicRunEventPayloadString(payload, 'memory_id')
    || publicRunEventPayloadString(payload, 'memory_kind')
    || publicRunEventPayloadString(payload, 'member_agent_name')
    || publicRunEventPayloadString(payload, 'agent_name')
    || publicRunEventPayloadString(payload, 'agent_id')
    || publicRunEventPayloadString(payload, 'group_name')
    || publicRunEventPayloadString(payload, 'member_agent_id')
    || publicRunEventPayloadString(payload, 'group_id')
    || publicRunEventArtifactSummary(payload)
    || publicRunEventPayloadString(payload, 'artifact_path')
    || publicRunEventPayloadString(payload, 'path')
    || publicRunEventPayloadString(payload, 'child_run_id')
    || publicRunEventPayloadString(payload, 'result')
    || publicRunEventPayloadString(payload, 'error')
  );
}

export function runEventReplayToTimelineEvent(event: PublicRunEvent): Record<string, unknown> {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const detail = publicRunEventPayloadDetail(event);
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
    pending_approval: payload.pending_approval || payload.approval || null,
    child_run_id: payload.child_run_id,
    workflow_node_id: payload.workflow_node_id,
    workflow_node_kind: payload.workflow_node_kind,
    workflow_node_label: payload.workflow_node_label,
    payload,
  };
}

export function toolCallsFromRunEventReplay(events: PublicRunEvent[]): ToolCallSnapshot[] {
  return events
    .map(toolCallFromRunEvent)
    .filter((toolCall): toolCall is ToolCallSnapshot => Boolean(toolCall));
}

export function mergeToolCallSnapshots(
  timelineToolCalls: ToolCallSnapshot[],
  replayToolCalls: ToolCallSnapshot[],
): ToolCallSnapshot[] {
  const byId = new Map<string, ToolCallSnapshot>();
  timelineToolCalls.forEach((toolCall) => byId.set(toolCall.tool_call_id, toolCall));
  replayToolCalls.forEach((toolCall) => {
    if (!byId.has(toolCall.tool_call_id)) byId.set(toolCall.tool_call_id, toolCall);
  });
  return Array.from(byId.values());
}

export function artifactsFromRunEventReplay(events: PublicRunEvent[]): Array<Record<string, unknown>> {
  return events
    .map(artifactFromRunEvent)
    .filter((artifact): artifact is Record<string, unknown> => Boolean(artifact));
}

export function mergeArtifactSnapshots(
  timelineArtifacts: Array<Record<string, unknown>>,
  replayArtifacts: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const byKey = new Map<string, Record<string, unknown>>();
  timelineArtifacts.forEach((artifact, index) => {
    byKey.set(artifactRecordKey(artifact, index), artifact);
  });
  replayArtifacts.forEach((artifact, index) => {
    const key = artifactRecordKey(artifact, index);
    if (!byKey.has(key)) byKey.set(key, artifact);
  });
  return Array.from(byKey.values());
}

export function approvalsFromRunEventReplay(events: PublicRunEvent[]): ApprovalCardSnapshot[] {
  return events
    .map(approvalFromRunEvent)
    .filter((approval): approval is ApprovalCardSnapshot => Boolean(approval));
}

export function mergeApprovalSnapshots(
  timelineApprovals: ApprovalCardSnapshot[],
  replayApprovals: ApprovalCardSnapshot[],
): ApprovalCardSnapshot[] {
  const byKey = new Map<string, ApprovalCardSnapshot>();
  timelineApprovals.forEach((approval, index) => {
    byKey.set(approvalRecordKey(approval, index), approval);
  });
  replayApprovals.forEach((approval, index) => {
    const key = approvalRecordKey(approval, index);
    if (!byKey.has(key)) byKey.set(key, approval);
  });
  return Array.from(byKey.values());
}

export function mergeRunEventReplayPages(
  current: PublicRunEvent[],
  incoming: PublicRunEvent[],
): PublicRunEvent[] {
  const bySequence = new Map<number, PublicRunEvent>();
  current.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  incoming.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  return Array.from(bySequence.values()).sort(
    (left, right) => (Number(left.sequence) || 0) - (Number(right.sequence) || 0),
  );
}

function toolCallFromRunEvent(event: PublicRunEvent): ToolCallSnapshot | null {
  if (!isToolRunEvent(event.event_type)) return null;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const outputPreview = objectPreview(payload.output_preview)
    || objectPreview(payload.result)
    || (payload.error !== undefined ? { error: payload.error } : {});
  const toolName = publicRunEventPayloadString(payload, 'tool_name')
    || publicRunEventPayloadString(payload, 'tool')
    || event.detail
    || 'tool';
  return {
    tool_call_id: event.event_id
      || publicRunEventPayloadString(payload, 'tool_call_id')
      || publicRunEventPayloadString(payload, 'id')
      || `${event.run_id}:${event.event_type}:${event.sequence}`,
    run_id: event.run_id,
    tool_name: toolName,
    status: publicRunEventPayloadString(payload, 'status') || toolStatusFromRunEvent(event.event_type),
    risk_level: publicRunEventPayloadString(payload, 'risk_level')
      || publicRunEventPayloadString(payload, 'risk')
      || null,
    input_preview: objectPreview(payload.input_preview) || objectPreview(payload.input) || {},
    output_preview: outputPreview,
    approval_id: publicRunEventPayloadString(payload, 'approval_id') || null,
    started_at: event.created_at || '',
    completed_at: publicRunEventPayloadString(payload, 'completed_at') || null,
  };
}

function approvalFromRunEvent(event: PublicRunEvent): ApprovalCardSnapshot | null {
  if (!isApprovalRunEvent(event.event_type)) return null;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const source = objectPreview(payload.pending_approval)
    || objectPreview(payload.approval)
    || payload;
  const toolName = publicRunEventPayloadString(source, 'tool_name')
    || publicRunEventPayloadString(source, 'tool')
    || approvalToolFromRunEvent(event.event_type)
    || event.detail
    || 'approval';
  const approvalId = publicRunEventPayloadString(source, 'approval_id')
    || `${event.run_id}:${event.event_type}:${event.sequence}`;
  const status = publicRunEventPayloadString(source, 'status') || approvalStatusFromRunEvent(event.event_type);
  return {
    approval_id: approvalId,
    description: publicRunEventPayloadString(source, 'description') || null,
    input_preview: objectPreview(source.input_preview) || objectPreview(source.input) || {},
    policy_reason: publicRunEventPayloadString(source, 'policy_reason') || null,
    requested_at: publicRunEventPayloadString(source, 'requested_at') || event.created_at || '',
    resolved_at: publicRunEventPayloadString(source, 'resolved_at')
      || (status !== 'pending' ? event.created_at || '' : null),
    risk_level: publicRunEventPayloadString(source, 'risk_level')
      || publicRunEventPayloadString(source, 'risk')
      || null,
    run_id: publicRunEventPayloadString(source, 'run_id') || event.run_id,
    status,
    title: publicRunEventPayloadString(source, 'title') || `Approval · ${toolName}`,
    tool_name: toolName,
  };
}

function isApprovalRunEvent(eventType: string): boolean {
  return eventType.includes('approval_required')
    || eventType.includes('approval_approved')
    || eventType.includes('approval_rejected')
    || eventType === 'approval.timeout';
}

function approvalStatusFromRunEvent(eventType: string): ApprovalCardSnapshot['status'] {
  if (eventType.includes('approval_approved')) return 'approved';
  if (eventType.includes('approval_rejected')) return 'rejected';
  if (eventType === 'approval.timeout') return 'expired';
  return 'pending';
}

function approvalToolFromRunEvent(eventType: string): string {
  if (eventType.startsWith('workflow.')) return 'workflow.approval';
  if (eventType.startsWith('group.')) return 'group.approval';
  if (eventType.startsWith('agent.tool.') || eventType.startsWith('tool.')) return 'tool.approval';
  return '';
}

function artifactFromRunEvent(event: PublicRunEvent): Record<string, unknown> | null {
  if (!isArtifactRunEvent(event.event_type)) return null;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  let artifactPayload: Record<string, unknown> | null = null;
  if (event.event_type === 'artifact.created' || event.event_type === 'agent.artifact.write') {
    artifactPayload = { ...payload };
  } else if (event.event_type === 'group.artifact.created' || event.event_type === 'group.shared_artifact.created') {
    artifactPayload = { ...(objectPreview(payload.artifact) || payload) };
    artifactPayload.kind = artifactPayload.kind || 'group_artifact';
    artifactPayload.source_runnable_name = artifactPayload.source_runnable_name || payload.member_agent_name;
    artifactPayload.source_runnable_id = artifactPayload.source_runnable_id || payload.member_agent_id;
  } else if (event.event_type === 'workflow.node.artifact') {
    artifactPayload = {
      kind: 'workflow_artifact',
      title: payload.workflow_node_label || 'Workflow Artifact',
      workflow_node_id: payload.workflow_node_id,
      workflow_node_label: payload.workflow_node_label,
      workflow_step_label: payload.workflow_node_label,
      ...(objectPreview(payload.artifact) || payload),
    };
  }
  if (!artifactPayload) return null;
  const path = publicRunEventPayloadString(artifactPayload, 'path')
    || publicRunEventPayloadString(artifactPayload, 'artifact_path');
  const artifactId = publicRunEventPayloadString(artifactPayload, 'artifact_id')
    || publicRunEventPayloadString(artifactPayload, 'id');
  if (!artifactId && !path) return null;
  return {
    ...artifactPayload,
    artifact_id: artifactId || `${event.run_id}:${path || event.event_type}:${event.sequence}`,
    created_at: publicRunEventPayloadString(artifactPayload, 'created_at') || event.created_at || '',
    kind: publicRunEventPayloadString(artifactPayload, 'kind') || 'artifact',
    path,
    run_id: publicRunEventPayloadString(artifactPayload, 'run_id') || event.run_id,
    source_run_id: publicRunEventPayloadString(artifactPayload, 'source_run_id') || event.run_id,
    title: publicRunEventPayloadString(artifactPayload, 'title') || path || 'Artifact',
  };
}

function isArtifactRunEvent(eventType: string): boolean {
  return [
    'artifact.created',
    'agent.artifact.write',
    'group.artifact.created',
    'group.shared_artifact.created',
    'workflow.node.artifact',
  ].includes(eventType);
}

function artifactRecordKey(artifact: Record<string, unknown>, index: number): string {
  return publicRunEventPayloadString(artifact, 'artifact_id')
    || [
      publicRunEventPayloadString(artifact, 'source_run_id') || publicRunEventPayloadString(artifact, 'run_id'),
      publicRunEventPayloadString(artifact, 'path') || publicRunEventPayloadString(artifact, 'artifact_path'),
      publicRunEventPayloadString(artifact, 'title'),
      publicRunEventPayloadString(artifact, 'kind'),
    ].filter(Boolean).join(':')
    || `artifact:${index}`;
}

function approvalRecordKey(approval: ApprovalCardSnapshot, index: number): string {
  return approval.approval_id
    || [approval.run_id || '', approval.tool_name || '', approval.title || ''].filter(Boolean).join(':')
    || `approval:${index}`;
}

function isToolRunEvent(eventType: string): boolean {
  return [
    'agent.tool.call',
    'agent.tool.denied',
    'agent.tool.failed',
    'agent.tool.skipped',
    'agent.tool.approval_required',
    'agent.tool.approval_approved',
    'agent.tool.approval_rejected',
    'agent.tool.completed',
    'tool.requested',
    'tool.started',
    'tool.approval_required',
    'tool.completed',
    'tool.failed',
  ].includes(eventType);
}

function toolStatusFromRunEvent(eventType: string): string {
  if (eventType === 'tool.requested') return 'requested';
  if (eventType === 'tool.started') return 'running';
  if (eventType === 'tool.approval_required' || eventType === 'agent.tool.approval_required') return 'waiting_approval';
  if (eventType === 'agent.tool.approval_approved') return 'approved';
  if (eventType === 'agent.tool.approval_rejected' || eventType === 'agent.tool.denied') return 'denied';
  if (eventType === 'tool.failed' || eventType === 'agent.tool.failed') return 'failed';
  if (eventType === 'agent.tool.skipped') return 'skipped';
  return 'completed';
}

function objectPreview(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function publicRunEventPayloadString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === 'string' ? value.trim() : '';
}

function publicRunEventMemorySummary(payload: Record<string, unknown>): string {
  const memories = payload.memories;
  const countValue = payload.count;
  const count = typeof countValue === 'number' && Number.isFinite(countValue)
    ? countValue
    : Array.isArray(memories) ? memories.length : 0;
  if (!Array.isArray(memories) || !memories.length) {
    return count ? `Memory × ${count}` : '';
  }
  const labels = memories
    .filter((item): item is Record<string, unknown> => Boolean(item && typeof item === 'object'))
    .slice(0, 3)
    .map((item) => [
      publicRunEventPayloadString(item, 'kind'),
      publicRunEventPayloadString(item, 'memory_id'),
    ].filter(Boolean).join(':'))
    .filter(Boolean)
    .join('、');
  return labels ? `Memory × ${count || memories.length} · ${labels}` : `Memory × ${count || memories.length}`;
}

function publicRunEventArtifactSummary(payload: Record<string, unknown>): string {
  const artifact = payload.artifact;
  if (!artifact || typeof artifact !== 'object' || Array.isArray(artifact)) return '';
  const artifactPayload = artifact as Record<string, unknown>;
  return (
    publicRunEventPayloadString(artifactPayload, 'title')
    || publicRunEventPayloadString(artifactPayload, 'path')
    || publicRunEventPayloadString(artifactPayload, 'artifact_path')
  );
}
