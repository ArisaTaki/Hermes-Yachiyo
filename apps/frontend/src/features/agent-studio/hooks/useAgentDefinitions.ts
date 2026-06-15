import { useCallback, useEffect, useMemo, useState } from 'react';

import type { AgentSpec } from '../types';

type ApplyAgentOptions = {
  selectedAgentId?: string;
  selectFirstAgent?: boolean;
};

function pruneSelectedIds(current: string[], validIds: string[]): string[] {
  const valid = new Set(validIds);
  return current.filter((id) => valid.has(id));
}

function toggleSelectedId(current: string[], id: string): string[] {
  if (current.includes(id)) return current.filter((item) => item !== id);
  return [...current, id];
}

export function useAgentDefinitions() {
  const [agents, setAgents] = useState<AgentSpec[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [agentManagementMode, setAgentManagementMode] = useState(false);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === selectedAgentId) || null,
    [agents, selectedAgentId],
  );
  const selectedAgentReadOnly = Boolean(selectedAgent && (selectedAgent.system || selectedAgent.editable === false));
  const selectedAgentDeletable = Boolean(selectedAgent && !selectedAgent.system && selectedAgent.deletable !== false);
  const deletableAgentIds = useMemo(
    () => agents.filter((agent) => !agent.system && agent.deletable !== false).map((agent) => agent.agent_id).filter(Boolean),
    [agents],
  );
  const selectedAgentIdSet = useMemo(() => new Set(selectedAgentIds), [selectedAgentIds]);
  const selectedAgents = useMemo(
    () => agents.filter((agent) => selectedAgentIdSet.has(agent.agent_id)),
    [agents, selectedAgentIdSet],
  );
  const selectedDeletableAgents = useMemo(
    () => selectedAgents.filter((agent) => !agent.system && agent.deletable !== false),
    [selectedAgents],
  );
  const allAgentsSelected = deletableAgentIds.length > 0 && selectedDeletableAgents.length === deletableAgentIds.length;

  useEffect(() => {
    setSelectedAgentIds((current) => pruneSelectedIds(current, deletableAgentIds));
  }, [deletableAgentIds]);

  const applyAgents = useCallback((nextAgents: AgentSpec[], options: ApplyAgentOptions = {}) => {
    setAgents(nextAgents);
    setSelectedAgentId((current) => {
      const desired = options.selectedAgentId !== undefined ? options.selectedAgentId : current;
      if (desired && nextAgents.some((agent) => agent.agent_id === desired)) return desired;
      return options.selectFirstAgent && nextAgents.length ? nextAgents[0].agent_id : '';
    });
  }, []);

  const toggleAgentSelected = useCallback((agentId: string) => {
    if (!deletableAgentIds.includes(agentId)) return;
    setSelectedAgentIds((current) => toggleSelectedId(current, agentId));
  }, [deletableAgentIds]);

  const finishAgentManagement = useCallback(() => {
    setAgentManagementMode(false);
    setSelectedAgentIds([]);
  }, []);

  return {
    agentManagementMode,
    agents,
    allAgentsSelected,
    applyAgents,
    deletableAgentIds,
    finishAgentManagement,
    selectedAgent,
    selectedAgentDeletable,
    selectedAgentId,
    selectedAgentIds,
    selectedAgentIdSet,
    selectedAgentReadOnly,
    selectedAgents,
    selectedDeletableAgents,
    setAgentManagementMode,
    setSelectedAgentId,
    setSelectedAgentIds,
    toggleAgentSelected,
  };
}
