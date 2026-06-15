import type { Edge, Node } from '@xyflow/react';

import type { WorkflowSpec } from '../types';
import { saveYachiyoWorkflow } from '../../yachiyo-studio/api';
import {
  publicWorkflowToWorkflowSpec,
  workflowRequestEdges,
  workflowRequestNodes,
} from '../utils/workflow';

type WorkflowSaveRefreshOptions = {
  selectedWorkflowId?: string;
};

type UseWorkflowSaveActionsOptions = {
  edges: Edge[];
  nodes: Node[];
  selectedWorkflow: WorkflowSpec | null;
  setSelectedWorkflowId: (workflowId: string) => void;
  workflowDescription: string;
  workflowEnabled: boolean;
  workflowErrors: string[];
  workflowName: string;
};

export function useWorkflowSaveActions({
  edges,
  nodes,
  selectedWorkflow,
  setSelectedWorkflowId,
  workflowDescription,
  workflowEnabled,
  workflowErrors,
  workflowName,
}: UseWorkflowSaveActionsOptions) {
  function workflowDraftRequest(): Partial<WorkflowSpec> {
    return {
      name: workflowName.trim(),
      description: workflowDescription.trim(),
      nodes: workflowRequestNodes(nodes),
      edges: workflowRequestEdges(edges),
      enabled: workflowEnabled,
    };
  }

  async function saveWorkflowDraft(): Promise<WorkflowSpec> {
    if (workflowErrors.length) {
      throw new Error(workflowErrors[0]);
    }
    const request = workflowDraftRequest();
    const saved = publicWorkflowToWorkflowSpec(await saveYachiyoWorkflow(
      selectedWorkflow ? { ...request, workflow_id: selectedWorkflow.workflow_id } : request,
    ));
    setSelectedWorkflowId(saved.workflow_id);
    return saved;
  }

  async function saveWorkflow(): Promise<WorkflowSaveRefreshOptions> {
    const saved = await saveWorkflowDraft();
    return { selectedWorkflowId: saved.workflow_id };
  }

  return {
    saveWorkflow,
    saveWorkflowDraft,
    workflowDraftRequest,
  };
}
