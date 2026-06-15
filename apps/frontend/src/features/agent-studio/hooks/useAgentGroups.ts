import { useCallback, useEffect, useMemo, useState } from 'react';

import {
  listYachiyoAgentGroups,
  saveYachiyoAgentGroup,
  startYachiyoGroupRun,
} from '../../yachiyo-studio/api';
import type { AgentGroupSnapshot, GroupRunSnapshot } from '../../yachiyo-studio/types';
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

export function useAgentGroups() {
  const [agentGroups, setAgentGroups] = useState<AgentGroupSnapshot[]>([]);
  const [selectedAgentGroupId, setSelectedAgentGroupId] = useState('');
  const [agentGroupName, setAgentGroupName] = useState('New Group');
  const [agentGroupMemberIds, setAgentGroupMemberIds] = useState<string[]>([]);
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
    setAgentGroupMemberIds(memberIdsForAgentGroup(selectedAgentGroup));
  }, [selectedAgentGroup]);

  const startNewAgentGroup = useCallback(() => {
    setSelectedAgentGroupId('');
    setAgentGroupName('New Group');
    setAgentGroupMemberIds([]);
    setAgentGroupRunGoal('');
    setLatestAgentGroupRun(null);
  }, []);

  const selectAgentGroup = useCallback((groupId: string) => {
    setSelectedAgentGroupId(groupId);
    setLatestAgentGroupRun(null);
  }, []);

  const toggleAgentGroupMember = useCallback((agentId: string) => {
    setAgentGroupMemberIds((current) => toggleAgentGroupMemberId(current, agentId));
  }, []);

  const saveAgentGroupDraft = useCallback(async () => {
    const name = agentGroupName.trim();
    const memberIds = agentGroupMemberIds.filter(Boolean);
    if (!name) throw new Error('Group 名称不能为空');
    if (!memberIds.length) throw new Error('Group 至少需要一个 Agent 成员');
    const saved = await saveYachiyoAgentGroup(buildAgentGroupSaveRequest(selectedAgentGroupId, name, memberIds));
    setSelectedAgentGroupId(saved.group_id);
    setAgentGroupName(saved.name);
    setAgentGroupMemberIds(memberIdsForAgentGroup(saved));
    setAgentGroups((current) => {
      const nextById = new Map(current.map((group) => [group.group_id, group]));
      nextById.set(saved.group_id, saved);
      return Array.from(nextById.values());
    });
    return {
      saved,
      statusMessage: `已保存 Agent Group：${saved.name}`,
    };
  }, [agentGroupMemberIds, agentGroupName, selectedAgentGroupId]);

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
    agentGroupMemberIds,
    agentGroupName,
    agentGroupRunGoal,
    applyAgentGroups,
    latestAgentGroupRun,
    loadAgentGroups,
    runAgentGroup,
    saveAgentGroupDraft,
    selectAgentGroup,
    selectedAgentGroup,
    selectedAgentGroupId,
    setAgentGroupName,
    setAgentGroupRunGoal,
    startNewAgentGroup,
    toggleAgentGroupMember,
  };
}
