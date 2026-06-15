import { useEffect, type Dispatch, type SetStateAction } from 'react';
import type { Edge, Node } from '@xyflow/react';

import type { AgentDraft, AgentSpec, WorkflowSpec } from '../types';
import { agentToDraft } from '../utils/agents';
import { workflowEdges, workflowNodes } from '../utils/workflow';

type UseAgentStudioSelectionSynchronizationOptions = {
  filteredLibrarySkillIds: string[];
  filteredRunIds: string[];
  selectedAgent: AgentSpec | null;
  selectedWorkflow: WorkflowSpec | null;
  setDraft: Dispatch<SetStateAction<AgentDraft>>;
  setEdges: Dispatch<SetStateAction<Edge[]>>;
  setNodes: Dispatch<SetStateAction<Node[]>>;
  setSelectedRunIds: Dispatch<SetStateAction<string[]>>;
  setSelectedSkillIds: Dispatch<SetStateAction<string[]>>;
  setWorkflowDescription: (description: string) => void;
  setWorkflowEnabled: (enabled: boolean) => void;
  setWorkflowName: (name: string) => void;
};

function pruneSelectedIds(current: string[], availableIds: string[]): string[] {
  const available = new Set(availableIds);
  const next = current.filter((id) => available.has(id));
  if (next.length === current.length) return current;
  return next;
}

export function useAgentStudioSelectionSynchronization({
  filteredLibrarySkillIds,
  filteredRunIds,
  selectedAgent,
  selectedWorkflow,
  setDraft,
  setEdges,
  setNodes,
  setSelectedRunIds,
  setSelectedSkillIds,
  setWorkflowDescription,
  setWorkflowEnabled,
  setWorkflowName,
}: UseAgentStudioSelectionSynchronizationOptions) {
  useEffect(() => {
    setSelectedSkillIds((current) => pruneSelectedIds(current, filteredLibrarySkillIds));
  }, [filteredLibrarySkillIds, setSelectedSkillIds]);

  useEffect(() => {
    setSelectedRunIds((current) => pruneSelectedIds(current, filteredRunIds));
  }, [filteredRunIds, setSelectedRunIds]);

  useEffect(() => {
    if (selectedAgent) setDraft(agentToDraft(selectedAgent));
  }, [selectedAgent, setDraft]);

  useEffect(() => {
    setNodes(workflowNodes(selectedWorkflow));
    setEdges(workflowEdges(selectedWorkflow));
    setWorkflowName(selectedWorkflow?.name || 'New Workflow');
    setWorkflowDescription(selectedWorkflow?.description || '');
    setWorkflowEnabled(selectedWorkflow?.enabled !== false);
  }, [
    selectedWorkflow,
    setEdges,
    setNodes,
    setWorkflowDescription,
    setWorkflowEnabled,
    setWorkflowName,
  ]);
}
