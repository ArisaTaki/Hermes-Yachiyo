import { RuntimeTimelineEventList, type RuntimeTimelineEventRecord } from './RuntimeTimelineEventList';
import { runtimeToolDisplayLabelOrName } from '../approval';
import {
  runtimeEventIsDesktopIntent,
  runtimeEventIsDesktopPermissionRecovery,
  runtimeEventIsDesktopReadinessRecovered,
} from '../desktopEvents';

export type RuntimeTimelineEventSnapshot = {
  event_id?: string | null;
  run_id?: string | null;
  sequence?: number | null;
  event_type?: string | null;
  title?: string | null;
  detail?: string | null;
  actor?: string | null;
  status?: string | null;
  payload?: Record<string, unknown> | null;
  created_at?: string | null;
};

export function RuntimeTimelineSummary({
  className = 'runtime-timeline-summary',
  eventTestId,
  events,
  limit = 3,
  testId = 'runtime-timeline-summary',
}: {
  className?: string;
  eventTestId?: string;
  events: RuntimeTimelineEventSnapshot[];
  limit?: number;
  testId?: string;
}) {
  const visibleEvents = runtimeTimelineSummaryEvents(events || [], limit);
  if (!visibleEvents.length) return null;
  return (
    <RuntimeTimelineEventList
      className={className}
      eventTestId={eventTestId || `${testId}-event`}
      events={visibleEvents as RuntimeTimelineEventRecord[]}
      getEventDetail={(event) => runtimeTimelineEventDetail(event as RuntimeTimelineEventSnapshot)}
      getEventName={(event) => String(event.event_type || event.title || 'event').trim()}
      getEventStatus={(event) => String(event.status || '').trim()}
      getEventTitle={(event) => runtimeTimelineEventLabel(event as RuntimeTimelineEventSnapshot)}
      runStatusLabel={runtimeTimelineStatusLabel}
      testId={testId}
      variant="compact"
    />
  );
}

export function runtimeTimelineSummaryEvents(
  events: RuntimeTimelineEventSnapshot[],
  limit = 3,
): RuntimeTimelineEventSnapshot[] {
  return (events || []).slice(-Math.max(1, limit));
}

export function runtimeTimelineEventLabel(event: RuntimeTimelineEventSnapshot): string {
  const title = String(event.title || '').trim();
  const type = String(event.event_type || '').trim();
  if (runtimeEventIsDesktopIntent(type, 'planned')) {
    const toolLabel = runtimeTimelinePlannedDesktopToolLabel(event);
    return toolLabel ? `准备执行 · ${toolLabel}` : '准备执行桌面动作';
  }
  if (runtimeEventIsDesktopIntent(type, 'approval_required')) {
    const toolLabel = runtimeTimelinePlannedDesktopToolLabel(event);
    return toolLabel ? `等待审批 · ${toolLabel}` : '等待审批桌面动作';
  }
  if (runtimeEventIsDesktopIntent(type, 'completed')) {
    const toolLabel = runtimeTimelinePlannedDesktopToolLabel(event);
    return toolLabel ? `已执行 · ${toolLabel}` : '已执行桌面动作';
  }
  if (runtimeEventIsDesktopPermissionRecovery(type)) {
    const toolLabel = runtimeTimelinePlannedDesktopToolLabel(event);
    return toolLabel ? `权限恢复 · ${toolLabel}` : '桌面权限恢复';
  }
  if (runtimeEventIsDesktopReadinessRecovered(type)) {
    const toolLabel = runtimeTimelinePlannedDesktopToolLabel(event);
    return toolLabel ? `桌面就绪已恢复 · ${toolLabel}` : '桌面就绪已恢复';
  }
  if (runtimeEventIsDesktopIntent(type, 'unavailable')) {
    const toolLabel = runtimeTimelinePlannedDesktopToolLabel(event);
    return toolLabel ? `无法执行 · ${toolLabel}` : '无法执行桌面动作';
  }
  if (type === 'agent.tool.policy_decision' || type === 'tool.policy_decision') {
    return runtimeTimelinePolicyDecisionLabel(event);
  }
  if (
    type === 'agent.plan.selection'
    || type === 'group.run.plan.selection'
    || type === 'workflow.plan.selection'
    || type === 'workflow.run.plan.selection'
  ) {
    const selectionDetail = runtimeTimelinePlannerSelectionDetail(event);
    return selectionDetail ? `Planner 选择 · ${selectionDetail}` : 'Planner 选择';
  }
  const typeLabel = runtimeTimelineEventTypeLabel(type || title);
  if (typeLabel) return typeLabel;
  if (title && !runtimeTimelineLooksInternalLabel(title)) return title;
  if (type && !runtimeTimelineLooksInternalLabel(type)) return type;
  return '运行事件';
}

function runtimeTimelineEventDetail(event: RuntimeTimelineEventSnapshot): string {
  const type = String(event.event_type || '').trim();
  const recoveryTargetDetail = runtimeTimelineRecoveryTargetDetail(event);
  if (recoveryTargetDetail && (
    runtimeEventIsDesktopIntent(type, 'planned')
    || type === 'agent.replan.requested'
    || type === 'group.run.replan.requested'
    || type === 'workflow.replan.requested'
    || type === 'workflow.run.replan.requested'
  )) {
    return recoveryTargetDetail;
  }
  if (type === 'agent.model.followup_context') {
    const contentSnapshotDetail = runtimeTimelineContentSnapshotDetail(event);
    if (contentSnapshotDetail) return contentSnapshotDetail;
    if (recoveryTargetDetail) return recoveryTargetDetail;
  }
  if (runtimeEventIsDesktopIntent(type, 'completed')) {
    const toolChainDetail = runtimeTimelineDesktopToolChainDetail(event);
    if (toolChainDetail) return toolChainDetail;
  }
  const detail = String(event.detail || '').trim();
  if (!detail) return '';
  if (detail === String(event.title || '').trim()) return '';
  if (runtimeTimelineLooksInternalLabel(detail)) return '';
  if (runtimeTimelineLooksRuntimeId(detail)) return '';
  return detail;
}

function runtimeTimelineRecoveryTargetDetail(event: RuntimeTimelineEventSnapshot): string {
  const record = event as RuntimeTimelineEventSnapshot & Record<string, unknown>;
  const payload = record.payload && typeof record.payload === 'object' && !Array.isArray(record.payload)
    ? record.payload as Record<string, unknown>
    : {};
  const metadata = payload.metadata && typeof payload.metadata === 'object' && !Array.isArray(payload.metadata)
    ? payload.metadata as Record<string, unknown>
    : {};
  const inputPreview = payload.input_preview && typeof payload.input_preview === 'object' && !Array.isArray(payload.input_preview)
    ? payload.input_preview as Record<string, unknown>
    : {};
  const appName = runtimeTimelineFirstRecordString(
    ['target_app_name', 'expected_app_name', 'resolved_app_name', 'discovered_app_name', 'requested_app_name', 'app_name'],
    record,
    payload,
    metadata,
    inputPreview,
  );
  const appQuery = runtimeTimelineFirstRecordString(
    ['target_app_query', 'app_query', 'query'],
    record,
    payload,
    metadata,
    inputPreview,
  );
  const searchText = runtimeTimelineFirstRecordString(
    ['target_search_text', 'search_text', 'text', 'value'],
    record,
    payload,
    metadata,
    inputPreview,
  );
  const parts = [appName, appQuery && appQuery !== appName ? appQuery : '', searchText].filter(Boolean);
  return parts.length ? `恢复目标 · ${parts.join(' · ')}` : '';
}

function runtimeTimelinePolicyDecisionLabel(event: RuntimeTimelineEventSnapshot): string {
  const payload = event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
    ? event.payload as Record<string, unknown>
    : {};
  const toolLabel = runtimeTimelinePlannedDesktopToolLabel(event);
  const decision = String(payload.decision || payload.status || '').trim();
  const prefix = decision === 'deny' || decision === 'denied' || decision === 'blocked'
    ? '策略拦截'
    : '策略放行';
  return toolLabel ? `${prefix} · ${toolLabel}` : prefix;
}

function runtimeTimelinePlannerSelectionDetail(event: RuntimeTimelineEventSnapshot): string {
  const record = event as RuntimeTimelineEventSnapshot & Record<string, unknown>;
  const payload = record.payload && typeof record.payload === 'object' && !Array.isArray(record.payload)
    ? record.payload as Record<string, unknown>
    : {};
  const role = String(record.selection_role || payload.selection_role || '').trim();
  const source = String(record.selection_source || payload.selection_source || '').trim();
  const entrypoint = String(record.planner_entrypoint || payload.planner_entrypoint || '').trim();
  const entrypointSource = String(record.entrypoint_source || payload.entrypoint_source || '').trim();
  const surface = String(record.launcher_surface || payload.launcher_surface || '').trim();
  return [
    role || source,
    entrypoint || entrypointSource,
    surface,
  ].filter(Boolean).join(' · ');
}

function runtimeTimelineEventTypeLabel(type: string): string {
  if (type === 'task.created') return '任务已创建';
  if (type === 'run.started' || type === 'task.started') return '任务已启动';
  if (type === 'task.linked') return 'Task 已关联';
  if (type === 'model.request.started' || type === 'model.requested') return '模型请求';
  if (type === 'model.request.failed') return '模型请求失败';
  if (type === 'model.output.ready') return '模型输出就绪';
  if (type === 'model.output.completed' || type === 'model.completed') return '模型完成';
  if (type === 'agent.model.followup_context') return '模型后续上下文';
  if (
    type === 'agent.intent.selected'
    || type === 'group.run.intent.selected'
    || type === 'workflow.intent.selected'
    || type === 'workflow.run.intent.selected'
  ) return 'Intent 识别';
  if (
    type === 'agent.replan.requested'
    || type === 'group.run.replan.requested'
    || type === 'workflow.replan.requested'
    || type === 'workflow.run.replan.requested'
  ) return 'Planner 重规划';
  if (
    type === 'agent.plan.created'
    || type === 'group.run.plan.created'
    || type === 'workflow.plan.created'
    || type === 'workflow.run.plan.created'
  ) return 'Planner 计划';
  if (
    type === 'agent.plan.step'
    || type === 'group.run.plan.step'
    || type === 'workflow.plan.step'
    || type === 'workflow.run.plan.step'
  ) return '计划步骤';
  if (
    type === 'agent.task_core.created'
    || type === 'group.run.task_core.created'
    || type === 'workflow.task_core.created'
    || type === 'workflow.run.task_core.created'
  ) return 'Task Core';
  if (
    type === 'agent.task.todo.updated'
    || type === 'group.run.task.todo.updated'
    || type === 'workflow.task.todo.updated'
    || type === 'workflow.run.task.todo.updated'
  ) return 'Task Todo';
  if (
    type === 'agent.task.workspace_item.updated'
    || type === 'group.run.task.workspace_item.updated'
    || type === 'workflow.task.workspace_item.updated'
    || type === 'workflow.run.task.workspace_item.updated'
  ) return 'Task Workspace';
  if (
    type === 'agent.task.checkpoint.updated'
    || type === 'group.run.task.checkpoint.updated'
    || type === 'workflow.task.checkpoint.updated'
    || type === 'workflow.run.task.checkpoint.updated'
  ) return 'Task Checkpoint';
  if (type === 'tool.requested') return '工具请求';
  if (type === 'agent.tool.policy_decision' || type === 'tool.policy_decision') return '工具策略决策';
  if (type === 'agent.tool.input_resolved') return '工具输入解析';
  if (type === 'tool.started' || type === 'agent.tool.started') return '工具执行中';
  if (type === 'agent.tool.call') return '工具调用';
  if (type === 'agent.tool.skipped' || type === 'tool.skipped') return '工具已跳过';
  if (type === 'agent.tool.denied' || type === 'tool.denied') return '工具已拒绝';
  if (type === 'approval.required' || type === 'tool.approval_required' || type === 'agent.tool.approval_required') return '等待审批';
  if (type === 'tool.approved') return '工具审批通过';
  if (type === 'tool.rejected') return '工具审批拒绝';
  if (type === 'agent.tool.approval_approved' || type === 'tool.approval_approved') return '审批已通过';
  if (type === 'agent.tool.approval_rejected' || type === 'tool.approval_rejected') return '审批已拒绝';
  if (type === 'agent.tool.approval_cancelled' || type === 'tool.approval_cancelled') return '审批已取消';
  if (type === 'agent.tool.approval_timeout') return '审批已超时';
  if (type === 'approval.approved') return '审批已通过';
  if (type === 'approval.rejected') return '审批已拒绝';
  if (type === 'approval.cancelled') return '审批已取消';
  if (type === 'tool.completed' || type === 'agent.tool.completed') return '工具完成';
  if (type === 'tool.failed' || type === 'agent.tool.failed') return '工具失败';
  if (type === 'tool.cancelled') return '工具已取消';
  if (type === 'skill.selected') return 'Skill 已选择';
  if (type.startsWith('skill.dispatch.')) return 'Skill 调度';
  if (type === 'memory.retrieved') return 'Memory 检索';
  if (type === 'memory.write.add') return 'Memory 新增';
  if (type === 'memory.write.replace') return 'Memory 更新';
  if (type === 'memory.write.remove') return 'Memory 删除';
  if (type === 'artifact.created') return '产物已生成';
  if (type === 'group.run.started') return '群组运行启动';
  if (type === 'group.run.plan') return '群组调度计划';
  if (type === 'group.run.completed') return '群组运行完成';
  if (type === 'group.run.failed') return '群组运行失败';
  if (type === 'group.run.cancelled') return '群组运行已取消';
  if (type === 'group.member.started') return '群组成员启动';
  if (type === 'group.member.completed') return '群组成员完成';
  if (type === 'group.member.failed') return '群组成员失败';
  if (type === 'group.member.cancelled') return '群组成员已取消';
  if (type === 'group.approval_required' || type === 'group.member.approval_required') return '群组等待审批';
  if (type === 'group.artifact.created' || type === 'group.shared_artifact.created') return '群组产物已生成';
  if (type === 'workflow.run.started' || type === 'workflow.started') return 'Workflow 已启动';
  if (type === 'workflow.node.start') return 'Workflow 起点';
  if (type === 'workflow.node.agent') return 'Agent 节点';
  if (type === 'workflow.node.workflow') return '子 Workflow';
  if (type === 'workflow.node.condition') return '条件节点';
  if (type === 'workflow.node.parallel') return '并行节点';
  if (type === 'workflow.node.loop') return '循环节点';
  if (type === 'workflow.node.artifact') return '产物节点';
  if (type === 'workflow.node.approval_required' || type === 'workflow.run.approval_required' || type === 'workflow.paused_for_approval') return 'Workflow 等待审批';
  if (type === 'workflow.node.approval_approved') return 'Workflow 审批通过';
  if (type === 'workflow.node.approval_rejected') return 'Workflow 审批拒绝';
  if (type === 'workflow.node.approval_cancelled') return 'Workflow 审批取消';
  if (type === 'workflow.node.approval_timeout') return 'Workflow 审批超时';
  if (type === 'workflow.edge.followed') return 'Workflow 路由';
  if (type === 'workflow.run.child_resumed') return '子任务已继续';
  if (type === 'workflow.run.resumed' || type === 'workflow.resumed') return 'Workflow 已继续';
  if (type === 'workflow.node.started') return 'Workflow 节点已启动';
  if (type === 'workflow.node.completed') return 'Workflow 节点完成';
  if (type === 'workflow.node.failed') return 'Workflow 节点失败';
  if (type === 'workflow.run.completed' || type === 'workflow.completed') return 'Workflow 完成';
  if (type === 'workflow.run.failed' || type === 'workflow.failed') return 'Workflow 失败';
  if (type === 'workflow.run.cancelled' || type === 'workflow.cancelled') return 'Workflow 已取消';
  if (type === 'run.completed' || type === 'task.completed') return '任务完成';
  if (type === 'run.failed' || type === 'task.failed') return '任务失败';
  if (type === 'run.cancelled' || type === 'task.cancelled') return '任务已取消';
  return '';
}

function runtimeTimelinePlannedDesktopToolLabel(event: RuntimeTimelineEventSnapshot): string {
  const record = event as RuntimeTimelineEventSnapshot & Record<string, unknown>;
  const payload = record.payload && typeof record.payload === 'object' && !Array.isArray(record.payload)
    ? record.payload as Record<string, unknown>
    : {};
  const tool = String(
    record.tool
      || record.tool_name
      || payload.tool
      || payload.tool_name
      || event.detail
      || '',
  ).trim();
  if (!tool || runtimeTimelineLooksRuntimeId(tool)) return '';
  return runtimeToolDisplayLabelOrName(tool);
}

function runtimeTimelineDesktopToolChainDetail(event: RuntimeTimelineEventSnapshot): string {
  const record = event as RuntimeTimelineEventSnapshot & Record<string, unknown>;
  const payload = record.payload && typeof record.payload === 'object' && !Array.isArray(record.payload)
    ? record.payload as Record<string, unknown>
    : {};
  const tools = runtimeTimelineDesktopToolChain(record, payload);
  if (tools.length < 2) return '';
  return `工具链 · ${tools.map(runtimeToolDisplayLabelOrName).join(' -> ')}`;
}

function runtimeTimelineDesktopToolChain(
  record: Record<string, unknown>,
  payload: Record<string, unknown>,
): string[] {
  const directTools = [
    runtimeTimelineRecordStringList(record, 'tools'),
    runtimeTimelineRecordStringList(payload, 'tools'),
    runtimeTimelineRecordStringList(record, 'tool_chain'),
    runtimeTimelineRecordStringList(payload, 'tool_chain'),
  ].find((items) => items.length > 0) || [];
  if (directTools.length) return runtimeTimelineUniqueToolNames(directTools);
  const steps = Array.isArray(payload.steps) ? payload.steps : Array.isArray(record.steps) ? record.steps : [];
  return runtimeTimelineUniqueToolNames(
    steps
      .filter((step): step is Record<string, unknown> => (
        Boolean(step && typeof step === 'object' && !Array.isArray(step))
      ))
      .map((step) => runtimeTimelineRecordString(step, 'tool') || runtimeTimelineRecordString(step, 'tool_name')),
  );
}

function runtimeTimelineRecordStringList(record: Record<string, unknown>, key: string): string[] {
  const value = record[key];
  if (!Array.isArray(value)) return [];
  return value.map((item) => typeof item === 'string' ? item.trim() : '').filter(Boolean);
}

function runtimeTimelineUniqueToolNames(values: string[]): string[] {
  const seen = new Set<string>();
  const tools: string[] = [];
  for (const value of values) {
    const tool = String(value || '').trim();
    if (!tool || seen.has(tool)) continue;
    seen.add(tool);
    tools.push(tool);
  }
  return tools;
}

function runtimeTimelineContentSnapshotDetail(event: RuntimeTimelineEventSnapshot): string {
  const payload = event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
    ? event.payload as Record<string, unknown>
    : {};
  const snapshots = runtimeTimelineContentSnapshotRecords(payload);
  if (snapshots.length) {
    return snapshots.map(runtimeTimelineContentSnapshotRecordDetail).filter(Boolean).join(' / ');
  }
  return '';
}

function runtimeTimelineContentSnapshotRecords(payload: Record<string, unknown>): Array<Record<string, unknown>> {
  const snapshots = payload.content_snapshots;
  if (Array.isArray(snapshots)) {
    return snapshots.filter((snapshot): snapshot is Record<string, unknown> => (
      Boolean(snapshot)
      && typeof snapshot === 'object'
      && !Array.isArray(snapshot)
      && Object.keys(snapshot).length > 0
    ));
  }
  const snapshot = payload.content_snapshot;
  if (!snapshot || typeof snapshot !== 'object' || Array.isArray(snapshot)) return [];
  return [snapshot as Record<string, unknown>];
}

function runtimeTimelineContentSnapshotRecordDetail(record: Record<string, unknown>): string {
  const textItemCount = runtimeTimelineRecordNumberString(record, 'text_item_count');
  const elementCount = runtimeTimelineRecordNumberString(record, 'element_count');
  const rows = runtimeTimelineRecordNumberString(record, 'rows');
  const columns = runtimeTimelineRecordArrayLength(record, 'columns');
  const artifactCount = runtimeTimelineRecordNumberString(record, 'artifact_count');
  return [
    runtimeTimelineRecordString(record, 'source_tool'),
    runtimeTimelineRecordString(record, 'app_name'),
    runtimeTimelineRecordString(record, 'title'),
    runtimeTimelineRecordString(record, 'url'),
    runtimeTimelineRecordString(record, 'source_kind'),
    rows ? `${rows} 行` : '',
    columns ? `${columns} 列` : '',
    textItemCount ? `${textItemCount} 条文本` : '',
    elementCount ? `${elementCount} 个元素` : '',
    artifactCount ? `${artifactCount} 个产物` : '',
    runtimeTimelineRecordString(record, 'path'),
  ].filter(Boolean).join(' · ');
}

function runtimeTimelineRecordString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  return typeof value === 'string' ? value.trim() : '';
}

function runtimeTimelineFirstRecordString(
  keys: string[],
  ...records: Array<Record<string, unknown>>
): string {
  for (const record of records) {
    for (const key of keys) {
      const value = runtimeTimelineRecordString(record, key);
      if (value) return value;
    }
  }
  return '';
}

function runtimeTimelineRecordNumberString(record: Record<string, unknown>, key: string): string {
  const value = record[key];
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return runtimeTimelineRecordString(record, key);
}

function runtimeTimelineRecordArrayLength(record: Record<string, unknown>, key: string): number {
  const value = record[key];
  return Array.isArray(value) ? value.length : 0;
}

function runtimeTimelineLooksInternalLabel(value: string): boolean {
  return /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/i.test(value);
}

function runtimeTimelineLooksRuntimeId(value: string): boolean {
  return /^(run|task|workflow|group|agent|approval|artifact)[-_][A-Za-z0-9_.:-]+$/i.test(value);
}

function runtimeTimelineStatusLabel(status: string): string {
  if (status === 'queued') return '排队中';
  if (status === 'pending') return '等待中';
  if (status === 'processing') return '执行中';
  if (status === 'running') return '执行中';
  if (status === 'approval_required' || status === 'waiting_approval') return '待审批';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  return status;
}
