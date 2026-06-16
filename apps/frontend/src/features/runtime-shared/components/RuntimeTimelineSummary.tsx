import { RuntimeTimelineEventList, type RuntimeTimelineEventRecord } from './RuntimeTimelineEventList';

export type RuntimeTimelineEventSnapshot = {
  event_id?: string | null;
  run_id?: string | null;
  sequence?: number | null;
  event_type?: string | null;
  title?: string | null;
  detail?: string | null;
  actor?: string | null;
  status?: string | null;
  created_at?: string | null;
};

export function RuntimeTimelineSummary({
  className = 'runtime-timeline-summary',
  events,
  limit = 3,
  testId = 'runtime-timeline-summary',
}: {
  className?: string;
  events: RuntimeTimelineEventSnapshot[];
  limit?: number;
  testId?: string;
}) {
  const visibleEvents = (events || []).slice(0, Math.max(1, limit));
  if (!visibleEvents.length) return null;
  return (
    <RuntimeTimelineEventList
      className={className}
      eventTestId={`${testId}-event`}
      events={visibleEvents as RuntimeTimelineEventRecord[]}
      getEventName={(event) => String(event.event_type || event.title || 'event').trim()}
      getEventStatus={(event) => String(event.status || '').trim()}
      getEventTitle={(event) => runtimeTimelineEventLabel(event as RuntimeTimelineEventSnapshot)}
      runStatusLabel={runtimeTimelineStatusLabel}
      testId={testId}
      variant="compact"
    />
  );
}

function runtimeTimelineEventLabel(event: RuntimeTimelineEventSnapshot): string {
  const title = String(event.title || '').trim();
  if (title) return title;
  const type = String(event.event_type || '').trim();
  if (type === 'run.started' || type === 'task.started') return '任务已启动';
  if (type === 'task.linked') return 'Task 已关联';
  if (type === 'tool.requested') return '工具请求';
  if (type === 'tool.started') return '工具执行中';
  if (type === 'agent.tool.call') return '工具调用';
  if (type === 'agent.tool.skipped') return '工具已跳过';
  if (type === 'agent.tool.denied') return '工具已拒绝';
  if (type === 'tool.approval_required' || type === 'agent.tool.approval_required') return '等待审批';
  if (type === 'tool.approved') return '工具审批通过';
  if (type === 'tool.rejected') return '工具审批拒绝';
  if (type === 'agent.tool.approval_approved') return '审批已通过';
  if (type === 'agent.tool.approval_rejected') return '审批已拒绝';
  if (type === 'agent.tool.approval_timeout') return '审批已超时';
  if (type === 'approval.approved') return '审批已通过';
  if (type === 'approval.rejected') return '审批已拒绝';
  if (type === 'tool.completed' || type === 'agent.tool.completed') return '工具完成';
  if (type === 'tool.failed' || type === 'agent.tool.failed') return '工具失败';
  if (type === 'skill.selected') return 'Skill 已选择';
  if (type === 'skill.dispatch.read') return 'Skill 调度';
  if (type === 'memory.retrieved') return 'Memory 检索';
  if (type === 'memory.write.add') return 'Memory 新增';
  if (type === 'memory.write.replace') return 'Memory 更新';
  if (type === 'memory.write.remove') return 'Memory 删除';
  if (type === 'artifact.created') return '产物已生成';
  if (type === 'group.member.started') return '群组成员启动';
  if (type === 'group.member.completed') return '群组成员完成';
  if (type === 'group.member.failed') return '群组成员失败';
  if (type === 'group.approval_required' || type === 'group.member.approval_required') return '群组等待审批';
  if (type === 'group.artifact.created' || type === 'group.shared_artifact.created') return '群组产物已生成';
  if (type === 'workflow.run.started') return 'Workflow 已启动';
  if (type === 'workflow.node.start') return 'Workflow 起点';
  if (type === 'workflow.node.agent') return 'Agent 节点';
  if (type === 'workflow.node.workflow') return '子 Workflow';
  if (type === 'workflow.node.condition') return '条件节点';
  if (type === 'workflow.node.parallel') return '并行节点';
  if (type === 'workflow.node.loop') return '循环节点';
  if (type === 'workflow.node.artifact') return '产物节点';
  if (type === 'workflow.node.approval_required' || type === 'workflow.run.approval_required') return 'Workflow 等待审批';
  if (type === 'workflow.node.approval_approved') return 'Workflow 审批通过';
  if (type === 'workflow.node.approval_rejected') return 'Workflow 审批拒绝';
  if (type === 'workflow.node.approval_timeout') return 'Workflow 审批超时';
  if (type === 'workflow.edge.followed') return 'Workflow 路由';
  if (type === 'workflow.run.child_resumed') return '子 Run 已继续';
  if (type === 'workflow.run.resumed') return 'Workflow 已继续';
  if (type === 'workflow.node.started') return 'Workflow 节点已启动';
  if (type === 'workflow.node.completed') return 'Workflow 节点完成';
  if (type === 'workflow.node.failed') return 'Workflow 节点失败';
  if (type === 'workflow.run.completed') return 'Workflow 完成';
  if (type === 'workflow.run.failed') return 'Workflow 失败';
  if (type === 'workflow.run.cancelled') return 'Workflow 已取消';
  if (type === 'run.completed' || type === 'task.completed') return '任务完成';
  if (type === 'run.failed' || type === 'task.failed') return '任务失败';
  if (type === 'run.cancelled' || type === 'task.cancelled') return '任务已取消';
  return type || '运行事件';
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
