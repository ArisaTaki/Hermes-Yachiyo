import type {
  AgentGroupSnapshot,
  GroupRunSnapshot,
  SaveAgentGroupRequest,
} from '../../yachiyo-studio/types';

export function agentInitial(name: string): string {
  const clean = name.trim();
  return clean ? clean.slice(0, 1).toUpperCase() : 'A';
}

export function agentGroupMemberIds(group: AgentGroupSnapshot | null): string[] {
  return (group?.members || [])
    .map((member) => member.agent_id)
    .filter(Boolean);
}

export function agentGroupListMeta(group: AgentGroupSnapshot): string {
  return `${group.members.length} members · ${group.mode || 'moderated'} · ${group.memory_scope || 'shared'}`;
}

export function agentGroupMemberSummary(group: AgentGroupSnapshot): string {
  return group.members.map((member) => member.name || member.agent_id).join('、') || 'No members';
}

export function nextSelectedAgentGroupId(current: string, nextAgentGroups: AgentGroupSnapshot[]): string {
  if (current && nextAgentGroups.some((group) => group.group_id === current)) return current;
  return nextAgentGroups.length ? nextAgentGroups[0].group_id : '';
}

export function toggleAgentGroupMemberId(current: string[], agentId: string): string[] {
  if (!agentId) return current;
  return current.includes(agentId)
    ? current.filter((item) => item !== agentId)
    : [...current, agentId];
}

export function buildAgentGroupSaveRequest(
  groupId: string,
  name: string,
  memberIds: string[],
  currentGroup: AgentGroupSnapshot | null = null,
): SaveAgentGroupRequest {
  const currentModeratorId = currentGroup?.moderator_agent_id;
  const moderatorAgentId = currentModeratorId && memberIds.includes(currentModeratorId)
    ? currentModeratorId
    : memberIds[0];
  return {
    group_id: groupId || undefined,
    name,
    description: currentGroup?.description || undefined,
    members: memberIds.map((agentId, index) => ({
      agent_id: agentId,
      role: agentId === moderatorAgentId ? 'moderator' : 'member',
      sort_order: index,
      enabled: true,
    })),
    mode: currentGroup?.mode || 'moderated',
    moderator_agent_id: moderatorAgentId || null,
    default_model: currentGroup?.default_model || null,
    memory_scope: currentGroup?.memory_scope || 'shared',
    tool_policy_id: currentGroup?.tool_policy_id || null,
    enabled: currentGroup?.enabled ?? true,
  };
}

export function agentGroupSaveDisabled(busy: boolean, name: string, memberIds: string[]): boolean {
  return busy || !name.trim() || !memberIds.length;
}

export function groupRunTimelineRunId(groupRun: GroupRunSnapshot | null): string {
  return groupRun?.runs?.[0]?.run_id || groupRun?.child_run_ids?.[0] || '';
}
