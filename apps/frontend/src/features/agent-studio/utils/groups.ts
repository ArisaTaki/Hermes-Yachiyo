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
  mode: AgentGroupSnapshot['mode'] = currentGroup?.mode || 'moderated',
  memoryScope: AgentGroupSnapshot['memory_scope'] = currentGroup?.memory_scope || 'shared',
  description = currentGroup?.description || '',
  moderatorAgentId = currentGroup?.moderator_agent_id || '',
  defaultModel = currentGroup?.default_model || '',
  toolPolicyId = currentGroup?.tool_policy_id || '',
  enabled = currentGroup?.enabled ?? true,
): SaveAgentGroupRequest {
  const selectedModeratorId = moderatorAgentId && memberIds.includes(moderatorAgentId)
    ? moderatorAgentId
    : memberIds[0];
  return {
    group_id: groupId || undefined,
    name,
    description: description.trim() || undefined,
    members: memberIds.map((agentId, index) => ({
      agent_id: agentId,
      role: agentId === selectedModeratorId ? 'moderator' : 'member',
      sort_order: index,
      enabled: true,
    })),
    mode,
    moderator_agent_id: selectedModeratorId || null,
    default_model: defaultModel.trim() || null,
    memory_scope: memoryScope,
    tool_policy_id: toolPolicyId.trim() || null,
    enabled,
  };
}

export function agentGroupSaveDisabled(busy: boolean, name: string, memberIds: string[]): boolean {
  return busy || !name.trim() || !memberIds.length;
}

export function groupRunTimelineRunId(groupRun: GroupRunSnapshot | null): string {
  return groupRun?.runs?.[0]?.run_id || groupRun?.child_run_ids?.[0] || '';
}
