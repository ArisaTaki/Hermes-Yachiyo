import type { PublicRunEvent } from '../../yachiyo-studio/types';
import { publicRunEventIsSecret } from '../../runtime-shared/runEvents';
import { runtimeToolDisplayLabelOrName } from '../../runtime-shared/approval';
import {
  runtimeEventIsDesktopIntent,
  runtimeEventIsDesktopPermissionRecovery,
  runtimeEventIsDesktopReadinessRecovered,
} from '../../runtime-shared/desktopEvents';
export {
  approvalsFromRunEventReplay,
  artifactsFromRunEventReplay,
  mergeApprovalSnapshots,
  mergeArtifactSnapshots,
  mergeToolCallSnapshots,
  toolCallsFromRunEventReplay,
} from '../../runtime-shared/runEventFacts';

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
  if (name === 'task.created') return '任务已创建';
  if (name === 'task.started') return '任务已启动';
  if (name === 'task.linked') return 'Task 已关联';
  if (name === 'task.completed') return '任务已完成';
  if (name === 'task.failed') return '任务失败';
  if (name === 'task.cancelled') return '任务已取消';
  if (name === 'model.request.started' || name === 'model.requested') return detail ? `模型请求 · ${detail}` : '模型请求已开始';
  if (name === 'model.request.failed') return '模型请求失败';
  if (name === 'model.output.ready') return '模型输出已就绪';
  if (name === 'model.output.completed' || name === 'model.completed') return '模型输出完成';
  if (name === 'agent.model.followup_context') return detail ? `模型后续上下文 · ${detail}` : '模型后续上下文';
  if (name === 'agent.run.started') return 'Agent 已启动';
  if (name === 'agent.runtime.compiled') return '运行环境已准备';
  if (name === 'agent.artifact.write') return '上下文/产物已写入';
  if (name === 'agent.model.response') return '模型响应';
  if (
    name === 'agent.intent.selected'
    || name === 'group.run.intent.selected'
    || name === 'workflow.intent.selected'
    || name === 'workflow.run.intent.selected'
  ) return detail ? `Intent 识别 · ${detail}` : 'Intent 识别';
  if (
    name === 'agent.replan.requested'
    || name === 'group.run.replan.requested'
    || name === 'workflow.replan.requested'
    || name === 'workflow.run.replan.requested'
  ) return detail ? `Planner 重规划 · ${detail}` : 'Planner 重规划';
  if (
    name === 'agent.plan.created'
    || name === 'group.run.plan.created'
    || name === 'workflow.plan.created'
    || name === 'workflow.run.plan.created'
  ) return detail ? `Planner 计划 · ${detail}` : 'Planner 计划';
  if (
    name === 'agent.plan.step'
    || name === 'group.run.plan.step'
    || name === 'workflow.plan.step'
    || name === 'workflow.run.plan.step'
  ) return detail ? `计划步骤 · ${detail}` : '计划步骤';
  if (
    name === 'agent.task_core.created'
    || name === 'group.run.task_core.created'
    || name === 'workflow.task_core.created'
    || name === 'workflow.run.task_core.created'
  ) return detail ? `Task Core · ${detail}` : 'Task Core';
  if (
    name === 'agent.task.todo.updated'
    || name === 'group.run.task.todo.updated'
    || name === 'workflow.task.todo.updated'
    || name === 'workflow.run.task.todo.updated'
  ) return detail ? `Task Todo · ${detail}` : 'Task Todo';
  if (
    name === 'agent.task.workspace_item.updated'
    || name === 'group.run.task.workspace_item.updated'
    || name === 'workflow.task.workspace_item.updated'
    || name === 'workflow.run.task.workspace_item.updated'
  ) return detail ? `Task Workspace · ${detail}` : 'Task Workspace';
  if (
    name === 'agent.task.checkpoint.updated'
    || name === 'group.run.task.checkpoint.updated'
    || name === 'workflow.task.checkpoint.updated'
    || name === 'workflow.run.task.checkpoint.updated'
  ) return detail ? `Task Checkpoint · ${detail}` : 'Task Checkpoint';
  if (
    name === 'agent.plan.selection'
    || name === 'group.run.plan.selection'
    || name === 'workflow.plan.selection'
    || name === 'workflow.run.plan.selection'
  ) {
    const selectionDetail = plannerSelectionTimelineDetail(event, detail);
    return selectionDetail ? `Planner 选择 · ${selectionDetail}` : 'Planner 选择';
  }
  if (runtimeEventIsDesktopIntent(name, 'planned')) {
    const toolLabel = plannedDesktopToolLabel(event, detail);
    return toolLabel ? `准备执行 · ${toolLabel}` : '准备执行桌面动作';
  }
  if (runtimeEventIsDesktopIntent(name, 'approval_required')) {
    const toolLabel = plannedDesktopToolLabel(event, detail);
    return toolLabel ? `等待审批 · ${toolLabel}` : '等待审批桌面动作';
  }
  if (runtimeEventIsDesktopIntent(name, 'completed')) {
    const toolLabel = plannedDesktopToolLabel(event, detail);
    return toolLabel ? `已执行 · ${toolLabel}` : '已执行桌面动作';
  }
  if (runtimeEventIsDesktopPermissionRecovery(name)) {
    const toolLabel = plannedDesktopToolLabel(event, detail);
    return toolLabel ? `权限恢复 · ${toolLabel}` : '桌面权限恢复';
  }
  if (runtimeEventIsDesktopReadinessRecovered(name)) {
    const toolLabel = plannedDesktopToolLabel(event, detail);
    return toolLabel ? `桌面就绪已恢复 · ${toolLabel}` : '桌面就绪已恢复';
  }
  if (runtimeEventIsDesktopIntent(name, 'unavailable')) {
    const toolLabel = plannedDesktopToolLabel(event, detail);
    return toolLabel ? `无法执行 · ${toolLabel}` : '无法执行桌面动作';
  }
  if (name === 'agent.tool.policy_decision' || name === 'tool.policy_decision') {
    return policyDecisionTitle(event, detail);
  }
  if (name === 'agent.tool.input_resolved') return detail ? `工具输入解析 · ${detail}` : '工具输入解析';
  if (name === 'agent.tool.call') return detail ? `工具调用 · ${detail}` : '工具调用';
  if (name === 'agent.tool.started') return detail ? `工具执行中 · ${detail}` : '工具执行中';
  if (name === 'agent.tool.skipped' || name === 'tool.skipped') return detail ? `工具已跳过 · ${detail}` : '工具已跳过';
  if (name === 'agent.tool.denied' || name === 'tool.denied') return detail ? `工具已拒绝 · ${detail}` : '工具已拒绝';
  if (name === 'agent.tool.failed') return detail ? `工具调用失败 · ${detail}` : '工具调用失败';
  if (name === 'approval.required' || name === 'agent.tool.approval_required') return detail ? `请求审批 · ${detail}` : '请求审批';
  if (name === 'tool.approved') return detail ? `工具审批通过 · ${detail}` : '工具审批通过';
  if (name === 'tool.rejected') return detail ? `工具审批拒绝 · ${detail}` : '工具审批拒绝';
  if (name === 'agent.tool.approval_approved' || name === 'tool.approval_approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';
  if (name === 'agent.tool.approval_rejected' || name === 'tool.approval_rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';
  if (name === 'agent.tool.approval_cancelled' || name === 'tool.approval_cancelled') return detail ? `审批已取消 · ${detail}` : '审批已取消';
  if (name === 'tool.cancelled') return detail ? `工具已取消 · ${detail}` : '工具已取消';
  if (name === 'approval.approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';
  if (name === 'approval.rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';
  if (name === 'approval.cancelled') return detail ? `审批已取消 · ${detail}` : '审批已取消';
  if (name === 'skill.selected') return detail ? `Skill 已选择 · ${detail}` : 'Skill 已选择';
  if (name.startsWith('skill.dispatch.')) return detail ? `Skill 调度 · ${detail}` : 'Skill 调度';
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
  if (name === 'group.run.started') return detail ? `群组运行启动 · ${detail}` : '群组运行启动';
  if (name === 'group.run.plan') return detail ? `群组调度计划 · ${detail}` : '群组调度计划';
  if (name === 'group.run.completed') return detail ? `群组运行完成 · ${detail}` : '群组运行完成';
  if (name === 'group.run.failed') return detail ? `群组运行失败 · ${detail}` : '群组运行失败';
  if (name === 'group.run.cancelled') return detail ? `群组运行已取消 · ${detail}` : '群组运行已取消';
  if (name === 'group.member.started') return detail ? `群组成员启动 · ${detail}` : '群组成员启动';
  if (name === 'group.member.completed') return detail ? `群组成员完成 · ${detail}` : '群组成员完成';
  if (name === 'group.member.failed') return detail ? `群组成员失败 · ${detail}` : '群组成员失败';
  if (name === 'group.member.cancelled') return detail ? `群组成员已取消 · ${detail}` : '群组成员已取消';
  if (name === 'group.approval_required') return detail ? `群组审批 · ${detail}` : '群组审批';
  if (name === 'group.member.approval_required') return detail ? `成员审批 · ${detail}` : '成员审批';
  if (name === 'group.artifact.created') return detail ? `群组产物 · ${detail}` : '群组产物';
  if (name === 'group.shared_artifact.created') return detail ? `群组共享产物 · ${detail}` : '群组共享产物';
  if (name === 'workflow.run.started' || name === 'workflow.started') return 'Workflow 已启动';
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
  if (name === 'workflow.node.approval_cancelled') return detail ? `审批已取消 · ${detail}` : '审批已取消';
  if (name === 'workflow.edge.followed') return detail ? `Workflow 路由 · ${detail}` : 'Workflow 路由';
  if (name === 'workflow.run.approval_required' || name === 'workflow.paused_for_approval') return 'Workflow 等待审批';
  if (name === 'workflow.run.child_resumed') return '子 Agent 已继续执行';
  if (name === 'workflow.run.resumed' || name === 'workflow.resumed') return 'Workflow 已继续执行';
  if (name === 'workflow.run.completed' || name === 'workflow.completed') return 'Workflow 已完成';
  if (name === 'workflow.run.failed' || name === 'workflow.failed') return 'Workflow 执行失败';
  if (name === 'workflow.run.cancelled' || name === 'workflow.cancelled') return 'Workflow 已取消';
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
    || name.includes('rejected')
  ) return 'danger';
  if (status === 'completed' || name.includes('completed')) return 'ready';
  if (status === 'approval_required' || name.includes('approval')) return 'approval';
  if (status === 'running' || status === 'processing' || name.includes('resumed')) return 'running';
  if (name === 'group.artifact.created' || name === 'group.shared_artifact.created') return 'ready';
  if (name === 'group.run.started') return 'running';
  if (name === 'group.run.plan') return 'running';
  if (name === 'group.run.completed') return 'ready';
  if (name === 'group.run.failed' || name === 'group.run.cancelled') return 'danger';
  if (name.startsWith('group.member.')) return name.includes('started') ? 'running' : 'ready';
  if (runtimeEventIsDesktopIntent(name, 'planned')) return 'tool';
  if (runtimeEventIsDesktopIntent(name, 'approval_required')) return 'approval';
  if (runtimeEventIsDesktopPermissionRecovery(name)) return 'approval';
  if (runtimeEventIsDesktopReadinessRecovered(name)) return 'ready';
  if (runtimeEventIsDesktopIntent(name, 'completed')) return 'ready';
  if (runtimeEventIsDesktopIntent(name, 'unavailable')) return 'danger';
  if (name === 'agent.model.followup_context') return 'model';
  if (name === 'agent.tool.policy_decision' || name === 'tool.policy_decision') {
    const payload = event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
      ? event.payload as Record<string, unknown>
      : {};
    const decision = String(payload.decision || payload.status || '').trim();
    return decision === 'deny' || decision === 'denied' || decision === 'blocked' ? 'danger' : 'tool';
  }
  if (name.startsWith('skill.') || name.startsWith('memory.')) return 'tool';
  if (
    name === 'agent.intent.selected'
    || name === 'agent.plan.created'
    || name === 'agent.plan.step'
    || name === 'agent.plan.selection'
    || name === 'agent.replan.requested'
    || name === 'agent.task_core.created'
    || name === 'agent.task.workspace_item.updated'
    || name === 'agent.task.todo.updated'
    || name === 'agent.task.checkpoint.updated'
    || name === 'group.run.intent.selected'
    || name === 'group.run.replan.requested'
    || name === 'group.run.plan.created'
    || name === 'group.run.plan.step'
    || name === 'group.run.plan.selection'
    || name === 'group.run.task_core.created'
    || name === 'group.run.task.workspace_item.updated'
    || name === 'group.run.task.todo.updated'
    || name === 'group.run.task.checkpoint.updated'
    || name === 'workflow.intent.selected'
    || name === 'workflow.run.intent.selected'
    || name === 'workflow.replan.requested'
    || name === 'workflow.run.replan.requested'
    || name === 'workflow.plan.created'
    || name === 'workflow.run.plan.created'
    || name === 'workflow.plan.step'
    || name === 'workflow.run.plan.step'
    || name === 'workflow.plan.selection'
    || name === 'workflow.run.plan.selection'
    || name === 'workflow.task_core.created'
    || name === 'workflow.run.task_core.created'
    || name === 'workflow.task.workspace_item.updated'
    || name === 'workflow.run.task.workspace_item.updated'
    || name === 'workflow.task.todo.updated'
    || name === 'workflow.run.task.todo.updated'
    || name === 'workflow.task.checkpoint.updated'
    || name === 'workflow.run.task.checkpoint.updated'
  ) return 'tool';
  if (name.includes('tool')) return 'tool';
  if (name.startsWith('model.') || name.includes('model.response')) return 'model';
  return 'neutral';
}

export function timelineEventCode(event: Record<string, unknown>): string {
  const name = timelineEventName(event);
  return name.includes('.') ? name.split('.').slice(-2).join('.') : name || 'event';
}

function plannedDesktopToolLabel(event: Record<string, unknown>, detail: string): string {
  const payload = event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
    ? event.payload as Record<string, unknown>
    : {};
  const tool = String(event.tool || event.tool_name || payload.tool || payload.tool_name || detail || '').trim();
  return tool ? runtimeToolDisplayLabelOrName(tool) : '';
}

function policyDecisionTitle(event: Record<string, unknown>, detail: string): string {
  const payload = event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
    ? event.payload as Record<string, unknown>
    : {};
  const toolLabel = plannedDesktopToolLabel(event, detail);
  const decision = String(payload.decision || payload.status || '').trim();
  const prefix = decision === 'deny' || decision === 'denied' || decision === 'blocked'
    ? '策略拦截'
    : '策略放行';
  return toolLabel ? `${prefix} · ${toolLabel}` : prefix;
}

function plannerSelectionTimelineDetail(event: Record<string, unknown>, fallback: string): string {
  const payload = event.payload && typeof event.payload === 'object' && !Array.isArray(event.payload)
    ? event.payload as Record<string, unknown>
    : {};
  const role = String(event.selection_role || payload.selection_role || '').trim();
  const source = String(event.selection_source || payload.selection_source || '').trim();
  const entrypoint = String(event.planner_entrypoint || payload.planner_entrypoint || '').trim();
  const entrypointSource = String(event.entrypoint_source || payload.entrypoint_source || '').trim();
  const surface = String(event.launcher_surface || payload.launcher_surface || '').trim();
  const parts = [
    role || source,
    entrypoint || entrypointSource,
    surface,
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : fallback;
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

export function timelineEventIsSecret(event: Record<string, unknown>): boolean {
  return publicRunEventIsSecret(event);
}

export function timelineEventPayload(event: Record<string, unknown>): string {
  if (timelineEventIsSecret(event)) return '';
  const observedEvidence = timelineObservedEvidencePayload(event);
  const inputPreview = event.input_preview;
  const result = event.result;
  const sections: string[] = [];
  if (observedEvidence) sections.push(observedEvidence);
  if (inputPreview && result) {
    sections.push(
      `请求内容：\n${formatTimelinePayload(inputPreview)}`,
      `执行结果：\n${formatTimelinePayload(result)}`,
    );
    return sections.join('\n\n');
  }
  if (inputPreview) {
    sections.push(`请求内容：\n${formatTimelinePayload(inputPreview)}`);
    return sections.join('\n\n');
  }
  if (result) {
    sections.push(formatTimelinePayload(result));
    return sections.join('\n\n');
  }
  const pendingApproval = event.pending_approval;
  if (pendingApproval) {
    sections.push(formatTimelinePayload(pendingApproval));
    return sections.join('\n\n');
  }
  const payload = event.payload;
  if (payload && typeof payload === 'object') {
    sections.push(`事件内容：\n${formatTimelinePayload(payload)}`);
    return sections.join('\n\n');
  }
  return sections.join('\n\n');
}

function timelineObservedEvidencePayload(event: Record<string, unknown>): string {
  const actionTarget = timelineContextNestedRecord(event, 'action_target');
  const observationEvidence = timelineContextNestedRecord(event, 'observation_evidence');
  const targetSummary = timelineObservedActionTargetSummary(actionTarget);
  const evidenceSummary = timelineObservedEvidenceSummary(observationEvidence);
  const centerSummary = timelineObservedCenterSummary(observationEvidence);
  const lines = [
    targetSummary ? `目标：${targetSummary}` : '',
    evidenceSummary ? `观测：${evidenceSummary}` : '',
    centerSummary ? `坐标：${centerSummary}` : '',
  ].filter(Boolean);
  return lines.length ? `执行证据：\n${lines.join('\n')}` : '';
}

function timelineContextNestedRecord(event: Record<string, unknown>, key: string): Record<string, unknown> {
  for (const record of timelineContextRecords(event)) {
    const value = record[key];
    if (value && typeof value === 'object' && !Array.isArray(value)) return value as Record<string, unknown>;
  }
  return {};
}

function timelineContextRecords(event: Record<string, unknown>): Record<string, unknown>[] {
  const records: Record<string, unknown>[] = [event];
  const seen = new Set<Record<string, unknown>>(records);
  const payload = event.payload;
  if (payload && typeof payload === 'object' && !Array.isArray(payload)) {
    const payloadRecord = payload as Record<string, unknown>;
    records.push(payloadRecord);
    seen.add(payloadRecord);
  }
  for (let index = 0; index < records.length; index += 1) {
    const record = records[index];
    for (const key of ['pending_approval', 'approval', 'tool_request', 'planned_request', 'request', 'result', 'metadata']) {
      const value = record[key];
      if (!value || typeof value !== 'object' || Array.isArray(value)) continue;
      const nested = value as Record<string, unknown>;
      if (seen.has(nested)) continue;
      records.push(nested);
      seen.add(nested);
    }
  }
  return records;
}

function timelineObservedActionTargetSummary(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  const action = timelineString(value.action);
  const target = (
    timelineString(value.target)
    || timelineString(value.label)
    || timelineString(value.name)
    || timelineString(value.title)
    || timelineString(value.text)
    || timelineString(value.role)
  );
  const roleFilter = timelineString(value.role_filter);
  const app = timelineString(value.app_name) || timelineString(value.app) || timelineString(value.bundle_id);
  return [action, target, roleFilter ? `role ${roleFilter}` : '', app].filter(Boolean).join(' · ');
}

function timelineObservedEvidenceSummary(value: Record<string, unknown>): string {
  if (!Object.keys(value).length) return '';
  const source = timelineString(value.source_tool) || timelineString(value.source);
  const strategy = timelineString(value.strategy);
  const reason = timelineString(value.reason);
  const center = timelineObservedCenterSummary(value);
  return [source, strategy, reason, center ? `center ${center}` : ''].filter(Boolean).join(' · ');
}

function timelineObservedCenterSummary(value: Record<string, unknown>): string {
  const center = timelineRecord(value.observed_center);
  const legacyCenter = timelineRecord(value.center);
  const point = timelineRecord(value.point);
  const x = timelineCoordinate(center.x ?? legacyCenter.x ?? point.x);
  const y = timelineCoordinate(center.y ?? legacyCenter.y ?? point.y);
  return x && y ? `${x},${y}` : '';
}

function timelineRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function timelineString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function timelineCoordinate(value: unknown): string {
  if (typeof value === 'number' && Number.isFinite(value)) return String(Math.round(value));
  return timelineString(value);
}

export function publicRunEventPayloadDetail(event: PublicRunEvent): string {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  if (publicRunEventIsSecret(event)) return event.detail || event.title || '';
  if (event.event_type === 'agent.model.followup_context') {
    const contentSnapshotSummary = publicRunEventContentSnapshotSummary(payload);
    if (contentSnapshotSummary) return contentSnapshotSummary;
  }
  if (runtimeEventIsDesktopIntent(event.event_type, 'completed')) {
    const toolChainSummary = publicRunEventDesktopToolChainSummary(payload);
    if (toolChainSummary) return toolChainSummary;
  }
  if (event.event_type === 'agent.tool.skipped' || event.event_type === 'tool.skipped') {
    const skipSummary = publicRunEventToolSkipSummary(payload);
    if (skipSummary) return skipSummary;
  }
  if (runtimeEventIsDesktopReadinessRecovered(event.event_type)) {
    const recoveredSummary = publicRunEventReadinessRecoveredSummary(payload);
    if (recoveredSummary) return recoveredSummary;
  }
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
    || publicRunEventPlannerSummary(event.event_type, payload)
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
    || publicRunEventContentSnapshotSummary(payload)
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
    target_app_name: payload.target_app_name,
    target_app_query: payload.target_app_query,
    target_search_text: payload.target_search_text,
    ...publicRunEventWorkflowStepPayload(payload),
    payload,
  };
}

function publicRunEventPayloadString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === 'string' ? value.trim() : '';
}

function publicRunEventPayloadRecord(payload: Record<string, unknown>, key: string): Record<string, unknown> {
  const value = payload[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function publicRunEventWorkflowStepPayload(payload: Record<string, unknown>): Record<string, unknown> {
  const artifactPath = publicRunEventPayloadString(payload, 'artifact_path') || publicRunEventPayloadString(payload, 'path');
  return {
    artifact: payload.artifact || (artifactPath ? { path: artifactPath } : null),
    artifact_count: payload.artifact_count,
    child_workflow_id: payload.child_workflow_id,
    child_workflow_name: payload.child_workflow_name,
    criteria: payload.criteria,
    step_task: payload.step_task,
    workflow_node_approval_criteria: payload.workflow_node_approval_criteria,
    workflow_node_branch_count: payload.workflow_node_branch_count,
    workflow_node_completed_branch_count: payload.workflow_node_completed_branch_count,
    workflow_node_condition: payload.workflow_node_condition,
    workflow_node_condition_matched: payload.workflow_node_condition_matched,
    workflow_node_join_target: payload.workflow_node_join_target,
    workflow_node_loop_iteration: payload.workflow_node_loop_iteration,
    workflow_node_loop_limit_reached: payload.workflow_node_loop_limit_reached,
    workflow_node_loop_max_iterations: payload.workflow_node_loop_max_iterations,
    workflow_node_selected_branch: payload.workflow_node_selected_branch,
    workflow_node_selected_target: payload.workflow_node_selected_target,
    workflow_node_task: payload.workflow_node_task,
  };
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

function publicRunEventPlannerSummary(eventType: string, payload: Record<string, unknown>): string {
  if (eventType === 'agent.intent.selected') {
    const intent = publicRunEventPayloadRecord(payload, 'intent');
    return (
      publicRunEventPayloadString(intent, 'title')
      || publicRunEventPayloadString(intent, 'kind')
      || publicRunEventPayloadString(payload, 'intent_kind')
    );
  }
  if (eventType === 'agent.plan.created') {
    const plan = publicRunEventPayloadRecord(payload, 'plan');
    const toolPlan = publicRunEventPayloadRecord(plan, 'tool_plan');
    return (
      publicRunEventPayloadString(plan, 'title')
      || publicRunEventPayloadString(toolPlan, 'title')
      || publicRunEventPayloadString(plan, 'plan_id')
      || publicRunEventPayloadString(payload, 'plan_id')
    );
  }
  if (eventType === 'agent.plan.step') {
    const step = publicRunEventPayloadRecord(payload, 'step');
    return (
      publicRunEventPayloadString(step, 'title')
      || publicRunEventPayloadString(step, 'tool_name')
      || publicRunEventPayloadString(step, 'capability_id')
      || publicRunEventPayloadString(payload, 'tool_name')
    );
  }
  if (eventType === 'agent.plan.selection') {
    return publicRunEventPlannerSelectionSummary(payload);
  }
  return '';
}

function publicRunEventPlannerSelectionSummary(payload: Record<string, unknown>): string {
  const reason = publicRunEventPayloadString(payload, 'selection_reason');
  if (reason) return reason;
  const role = publicRunEventPayloadString(payload, 'selection_role')
    || publicRunEventPayloadString(payload, 'selection_source');
  const entrypoint = publicRunEventPayloadString(payload, 'planner_entrypoint')
    || publicRunEventPayloadString(payload, 'entrypoint_source');
  const surface = publicRunEventPayloadString(payload, 'launcher_surface');
  return [role, entrypoint, surface].filter(Boolean).join(' · ');
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

function publicRunEventDesktopToolChainSummary(payload: Record<string, unknown>): string {
  const tools = publicRunEventDesktopToolChain(payload);
  if (tools.length < 2) return '';
  return `工具链 · ${tools.map(runtimeToolDisplayLabelOrName).join(' -> ')}`;
}

function publicRunEventDesktopToolChain(payload: Record<string, unknown>): string[] {
  const directTools = [
    publicRunEventPayloadStringList(payload, 'tools'),
    publicRunEventPayloadStringList(payload, 'tool_chain'),
  ].find((items) => items.length > 0) || [];
  if (directTools.length) return publicRunEventUniqueStrings(directTools);
  const steps = Array.isArray(payload.steps) ? payload.steps : [];
  return publicRunEventUniqueStrings(
    steps
      .filter((step): step is Record<string, unknown> => (
        Boolean(step && typeof step === 'object' && !Array.isArray(step))
      ))
      .map((step) => publicRunEventPayloadString(step, 'tool') || publicRunEventPayloadString(step, 'tool_name')),
  );
}

function publicRunEventPayloadStringList(payload: Record<string, unknown>, key: string): string[] {
  const value = payload[key];
  if (!Array.isArray(value)) return [];
  return value.map((item) => typeof item === 'string' ? item.trim() : '').filter(Boolean);
}

function publicRunEventPayloadStringValues(payload: Record<string, unknown>, ...keys: string[]): string[] {
  return keys.flatMap((key) => {
    const value = payload[key];
    if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean);
    const text = typeof value === 'string' ? value.trim() : '';
    return text ? [text] : [];
  });
}

function publicRunEventUniqueStrings(values: string[]): string[] {
  const seen = new Set<string>();
  const next: string[] = [];
  for (const value of values) {
    const item = String(value || '').trim();
    if (!item || seen.has(item)) continue;
    seen.add(item);
    next.push(item);
  }
  return next;
}

function publicRunEventToolSkipSummary(payload: Record<string, unknown>): string {
  const result = publicRunEventPayloadRecord(payload, 'result');
  const data = publicRunEventPayloadRecord(result, 'data');
  const reason = publicRunEventSkipReason(payload, result, data);
  const conditions = publicRunEventUniqueStrings([
    ...publicRunEventPayloadStringValues(payload, 'blocking_condition', 'blocking_conditions'),
    ...publicRunEventPayloadStringValues(result, 'blocking_condition', 'blocking_conditions'),
    ...publicRunEventPayloadStringValues(data, 'blocking_condition', 'blocking_conditions'),
  ]);
  const recommendedTools = publicRunEventUniqueStrings([
    ...publicRunEventPayloadStringValues(payload, 'recommended_tools'),
    ...publicRunEventPayloadStringValues(result, 'recommended_tools'),
    ...publicRunEventPayloadStringValues(data, 'recommended_tools'),
  ]);
  const recoveryTool = publicRunEventRecoveryActionTool(payload, result, data);
  return [
    reason,
    conditions.slice(0, 3).join(', '),
    recommendedTools.length ? `建议 ${recommendedTools.map(runtimeToolDisplayLabelOrName).join(' -> ')}` : '',
    recoveryTool ? `恢复 ${runtimeToolDisplayLabelOrName(recoveryTool)}` : '',
  ].filter(Boolean).join(' · ');
}

function publicRunEventReadinessRecoveredSummary(payload: Record<string, unknown>): string {
  const tool = (
    publicRunEventPayloadString(payload, 'recovery_tool')
    || publicRunEventPayloadString(payload, 'tool')
    || publicRunEventPayloadString(payload, 'tool_name')
  );
  const appName = (
    publicRunEventPayloadString(payload, 'app_name')
    || publicRunEventPayloadString(payload, 'requested_app_name')
    || publicRunEventPayloadString(payload, 'target_app_name')
  );
  const conditions = publicRunEventUniqueStrings(
    publicRunEventPayloadStringValues(payload, 'blocking_condition', 'blocking_conditions'),
  );
  return [
    tool ? `恢复工具 · ${runtimeToolDisplayLabelOrName(tool)}` : '',
    appName,
    conditions.slice(0, 3).join(', '),
  ].filter(Boolean).join(' · ');
}

function publicRunEventSkipReason(...records: Array<Record<string, unknown>>): string {
  if (records.some((record) => record.blocked_by_runtime_readiness === true)) return '前台未就绪';
  if (records.some((record) => record.blocked_by_app_resolution === true)) return '应用未解析';
  if (records.some((record) => record.blocked_by_user_goal === true)) return '用户约束';
  return publicRunEventFirstPayloadString(
    ['error', 'blocking_condition', 'source_summary'],
    ...records,
  );
}

function publicRunEventRecoveryActionTool(...records: Array<Record<string, unknown>>): string {
  for (const record of records) {
    const actions = record.recovery_actions;
    if (!Array.isArray(actions)) continue;
    for (const action of actions) {
      if (!action || typeof action !== 'object' || Array.isArray(action)) continue;
      const tool = publicRunEventPayloadString(action as Record<string, unknown>, 'tool');
      if (tool) return tool;
    }
  }
  return '';
}

function publicRunEventFirstPayloadString(
  keys: string[],
  ...records: Array<Record<string, unknown>>
): string {
  for (const record of records) {
    for (const key of keys) {
      const value = publicRunEventPayloadString(record, key);
      if (value) return value;
    }
  }
  return '';
}

function publicRunEventContentSnapshotSummary(payload: Record<string, unknown>): string {
  const snapshots = publicRunEventContentSnapshotRecords(payload);
  return snapshots.map(publicRunEventContentSnapshotRecordSummary).filter(Boolean).join(' / ');
}

function publicRunEventContentSnapshotRecords(payload: Record<string, unknown>): Array<Record<string, unknown>> {
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

function publicRunEventContentSnapshotRecordSummary(record: Record<string, unknown>): string {
  const textItemCount = publicRunEventPayloadNumberString(record, 'text_item_count');
  const elementCount = publicRunEventPayloadNumberString(record, 'element_count');
  const rows = publicRunEventPayloadNumberString(record, 'rows');
  const columns = publicRunEventPayloadArrayLength(record, 'columns');
  const artifactCount = publicRunEventPayloadNumberString(record, 'artifact_count');
  return [
    publicRunEventPayloadString(record, 'source_tool'),
    publicRunEventPayloadString(record, 'app_name'),
    publicRunEventPayloadString(record, 'title'),
    publicRunEventPayloadString(record, 'url'),
    publicRunEventPayloadString(record, 'source_kind'),
    rows ? `${rows} 行` : '',
    columns ? `${columns} 列` : '',
    textItemCount ? `${textItemCount} 条文本` : '',
    elementCount ? `${elementCount} 个元素` : '',
    artifactCount ? `${artifactCount} 个产物` : '',
    publicRunEventPayloadString(record, 'path'),
  ].filter(Boolean).join(' · ');
}

function publicRunEventPayloadNumberString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return publicRunEventPayloadString(payload, key);
}

function publicRunEventPayloadArrayLength(payload: Record<string, unknown>, key: string): number {
  const value = payload[key];
  return Array.isArray(value) ? value.length : 0;
}
