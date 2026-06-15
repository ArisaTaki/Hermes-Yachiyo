import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  listYachiyoAgentGroups,
  saveYachiyoAgentGroup,
  startYachiyoGroupRun,
} from '../../yachiyo-studio/api';
import type { AgentGroupSnapshot, GroupRunSnapshot } from '../../yachiyo-studio/types';
import { getStudioGroupForView } from '../utils/studioData';
import {
  agentGroupMemberIds as memberIdsForAgentGroup,
  buildAgentGroupSaveRequest,
  groupRunTimelineRunId,
  nextSelectedAgentGroupId,
  toggleAgentGroupMemberId,
} from '../utils/groups';

export type AgentGroupRunResult = {
  groupRun: GroupRunSnapshot;
  runId: string;
  statusMessage: string;
};

function mergeAgentGroupById(
  current: AgentGroupSnapshot[],
  nextGroup: AgentGroupSnapshot,
): AgentGroupSnapshot[] {
  if (!nextGroup.group_id) return current;
  const index = current.findIndex((group) => group.group_id === nextGroup.group_id);
  if (index < 0) return [...current, nextGroup];
  const next = [...current];
  next[index] = nextGroup;
  return next;
}

export function useAgentGroups() {
  const [agentGroups, setAgentGroups] = useState<AgentGroupSnapshot[]>([]);
  const [selectedAgentGroupId, setSelectedAgentGroupId] = useState('');
  const [agentGroupName, setAgentGroupName] = useState('New Group');
  const [agentGroupDescription, setAgentGroupDescription] = useState('');
  const [agentGroupMemberIds, setAgentGroupMemberIds] = useState<string[]>([]);
  const [agentGroupMode, setAgentGroupMode] = useState<AgentGroupSnapshot['mode']>('moderated');
  const [agentGroupMemoryScope, setAgentGroupMemoryScope] = useState<AgentGroupSnapshot['memory_scope']>('shared');
  const [agentGroupModeratorId, setAgentGroupModeratorId] = useState('');
  const [agentGroupDefaultModel, setAgentGroupDefaultModel] = useState('');
  const [agentGroupToolPolicyId, setAgentGroupToolPolicyId] = useState('');
  const [agentGroupEnabled, setAgentGroupEnabled] = useState(true);
  const [agentGroupRunGoal, setAgentGroupRunGoal] = useState('');
  const [latestAgentGroupRun, setLatestAgentGroupRun] = useState<GroupRunSnapshot | null>(null);

  const selectedAgentGroup = useMemo(
    () => agentGroups.find((group) => group.group_id === selectedAgentGroupId) || null,
    [agentGroups, selectedAgentGroupId],
  );

  const applyAgentGroups = useCallback((nextAgentGroups: AgentGroupSnapshot[]) => {
    setAgentGroups(nextAgentGroups);
    setSelectedAgentGroupId((current) => nextSelectedAgentGroupId(current, nextAgentGroups));
  }, []);

  const loadAgentGroups = useCallback(async () => {
    const nextAgentGroups = await listYachiyoAgentGroups().catch(() => []);
    applyAgentGroups(nextAgentGroups);
    return nextAgentGroups;
  }, [applyAgentGroups]);

  useEffect(() => {
    if (!selectedAgentGroup) return;
    setAgentGroupName(selectedAgentGroup.name || 'Agent Group');
    setAgentGroupDescription(selectedAgentGroup.description || '');
    setAgentGroupMemberIds(memberIdsForAgentGroup(selectedAgentGroup));
    setAgentGroupMode(selectedAgentGroup.mode || 'moderated');
    setAgentGroupMemoryScope(selectedAgentGroup.memory_scope || 'shared');
    setAgentGroupModeratorId(selectedAgentGroup.moderator_agent_id || '');
    setAgentGroupDefaultModel(selectedAgentGroup.default_model || '');
    setAgentGroupToolPolicyId(selectedAgentGroup.tool_policy_id || '');
    setAgentGroupEnabled(selectedAgentGroup.enabled !== false);
  }, [selectedAgentGroup]);

  const startNewAgentGroup = useCallback(() => {
    setSelectedAgentGroupId('');
    setAgentGroupName('New Group');
    setAgentGroupDescription('');
    setAgentGroupMemberIds([]);
    setAgentGroupMode('moderated');
    setAgentGroupMemoryScope('shared');
    setAgentGroupModeratorId('');
    setAgentGroupDefaultModel('');
    setAgentGroupToolPolicyId('');
    setAgentGroupEnabled(true);
    setAgentGroupRunGoal('');
    setLatestAgentGroupRun(null);
  }, []);

  const selectAgentGroup = useCallback((groupId: string) => {
    setSelectedAgentGroupId(groupId);
    setLatestAgentGroupRun(null);
    void getStudioGroupForView(groupId)
      .then((group) => {
        setAgentGroups((current) => mergeAgentGroupById(current, group));
      })
      .catch(() => undefined);
  }, []);

  const toggleAgentGroupMember = useCallback((agentId: string) => {
    setAgentGroupMemberIds((current) => toggleAgentGroupMemberId(current, agentId));
  }, []);

  const saveAgentGroupDraft = useCallback(async () => {
    const name = agentGroupName.trim();
    const memberIds = agentGroupMemberIds.filter(Boolean);
    if (!name) throw new Error('Group 名称不能为空');
    if (!memberIds.length) throw new Error('Group 至少需要一个 Agent 成员');
    const saved = await saveYachiyoAgentGroup(
      buildAgentGroupSaveRequest(
        selectedAgentGroupId,
        name,
        memberIds,
        selectedAgentGroup,
        agentGroupMode,
        agentGroupMemoryScope,
        agentGroupDescription,
        agentGroupModeratorId,
        agentGroupDefaultModel,
        agentGroupToolPolicyId,
        agentGroupEnabled,
      ),
    );
    setSelectedAgentGroupId(saved.group_id);
    setAgentGroupName(saved.name);
    setAgentGroupDescription(saved.description || '');
    setAgentGroupMemberIds(memberIdsForAgentGroup(saved));
    setAgentGroupMode(saved.mode || 'moderated');
    setAgentGroupMemoryScope(saved.memory_scope || 'shared');
    setAgentGroupModeratorId(saved.moderator_agent_id || '');
    setAgentGroupDefaultModel(saved.default_model || '');
    setAgentGroupToolPolicyId(saved.tool_policy_id || '');
    setAgentGroupEnabled(saved.enabled !== false);
    setAgentGroups((current) => {
      const nextById = new Map(current.map((group) => [group.group_id, group]));
      nextById.set(saved.group_id, saved);
      return Array.from(nextById.values());
    });
    return {
      saved,
      statusMessage: `已保存 Agent Group：${saved.name}`,
    };
  }, [
    agentGroupDefaultModel,
    agentGroupDescription,
    agentGroupEnabled,
    agentGroupMemberIds,
    agentGroupMemoryScope,
    agentGroupMode,
    agentGroupModeratorId,
    agentGroupName,
    agentGroupToolPolicyId,
    selectedAgentGroup,
    selectedAgentGroupId,
  ]);

  const runAgentGroup = useCallback(async (): Promise<AgentGroupRunResult> => {
    const groupId = selectedAgentGroupId.trim();
    const objective = agentGroupRunGoal.trim();
    if (!groupId) throw new Error('请先保存 Agent Group');
    if (!objective) throw new Error('Group Run 目标不能为空');
    const groupRun = await startYachiyoGroupRun(groupId, objective, agentGroupName.trim());
    setLatestAgentGroupRun(groupRun);
    setAgentGroupRunGoal('');
    const runId = groupRunTimelineRunId(groupRun);
    return {
      groupRun,
      runId,
      statusMessage: `已启动 Group Run：${groupRun.title || groupRun.group_run_id}`,
    };
  }, [agentGroupName, agentGroupRunGoal, selectedAgentGroupId]);

  return {
    agentGroups,
    agentGroupDefaultModel,
    agentGroupDescription,
    agentGroupEnabled,
    agentGroupMemberIds,
    agentGroupMemoryScope,
    agentGroupMode,
    agentGroupModeratorId,
    agentGroupName,
    agentGroupRunGoal,
    agentGroupToolPolicyId,
    applyAgentGroups,
    latestAgentGroupRun,
    loadAgentGroups,
    runAgentGroup,
    saveAgentGroupDraft,
    selectAgentGroup,
    selectedAgentGroup,
    selectedAgentGroupId,
    setAgentGroupDefaultModel,
    setAgentGroupDescription,
    setAgentGroupEnabled,
    setAgentGroupMemoryScope,
    setAgentGroupMode,
    setAgentGroupModeratorId,
    setAgentGroupName,
    setAgentGroupRunGoal,
    setAgentGroupToolPolicyId,
    startNewAgentGroup,
    toggleAgentGroupMember,
  };
}
