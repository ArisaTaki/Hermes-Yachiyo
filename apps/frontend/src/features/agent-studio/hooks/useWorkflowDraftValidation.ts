import { useMemo } from 'react';
import type { Edge, Node } from '@xyflow/react';

import type { AgentSpec, WorkflowSpec } from '../types';
import { validateWorkflowDraft } from '../utils/workflow';

type UseWorkflowDraftValidationOptions = {
  agents: AgentSpec[];
  edges: Edge[];
  nodes: Node[];
  selectedWorkflowId?: string;
  workflowName: string;
  workflows: WorkflowSpec[];
};

export function useWorkflowDraftValidation({
  agents,
  edges,
  nodes,
  selectedWorkflowId = '',
  workflowName,
  workflows,
}: UseWorkflowDraftValidationOptions) {
  const workflowValidation = useMemo(
    () => validateWorkflowDraft(nodes, edges, agents, workflows, selectedWorkflowId),
    [agents, edges, nodes, selectedWorkflowId, workflows],
  );
  const workflowNameError = workflowName.trim() ? '' : 'Workflow 名称不能为空';
  const workflowErrors = workflowNameError
    ? [workflowNameError, ...workflowValidation.errors]
    : workflowValidation.errors;
  return {
    workflowErrors,
    workflowNameError,
    workflowValidation,
  };
}
