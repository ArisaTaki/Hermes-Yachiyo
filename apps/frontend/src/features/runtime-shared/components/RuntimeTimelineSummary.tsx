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
  if (type === 'tool.approval_required' || type === 'agent.tool.approval_required') return '等待审批';
  if (type === 'tool.completed' || type === 'agent.tool.completed') return '工具完成';
  if (type === 'skill.selected') return 'Skill 已选择';
  if (type === 'skill.dispatch.read') return 'Skill 调度';
  if (type === 'memory.retrieved') return 'Memory 检索';
  if (type === 'memory.write.add') return 'Memory 新增';
  if (type === 'memory.write.replace') return 'Memory 更新';
  if (type === 'memory.write.remove') return 'Memory 删除';
  if (type === 'artifact.created') return '产物已生成';
  if (type === 'group.approval_required' || type === 'group.member.approval_required') return '群组等待审批';
  if (type === 'group.artifact.created' || type === 'group.shared_artifact.created') return '群组产物已生成';
  if (type === 'run.completed' || type === 'task.completed') return '任务完成';
  if (type === 'run.failed' || type === 'task.failed') return '任务失败';
  return type || '运行事件';
}

function runtimeTimelineStatusLabel(status: string): string {
  if (status === 'queued') return '排队中';
  if (status === 'running') return '执行中';
  if (status === 'approval_required' || status === 'waiting_approval') return '待审批';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  return status;
}
