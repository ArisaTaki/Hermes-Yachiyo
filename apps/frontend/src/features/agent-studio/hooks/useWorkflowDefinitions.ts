import { useCallback, useEffect, useMemo, useState } from 'react';

import type { WorkflowSpec } from '../../../lib/agents';

type ApplyWorkflowOptions = {
  selectedWorkflowId?: string;
  selectFirstWorkflow?: boolean;
};

function pruneSelectedIds(current: string[], validIds: string[]): string[] {
  const valid = new Set(validIds);
  return current.filter((id) => valid.has(id));
}

function toggleSelectedId(current: string[], id: string): string[] {
  if (current.includes(id)) return current.filter((item) => item !== id);
  return [...current, id];
}

export function useWorkflowDefinitions() {
  const [workflows, setWorkflows] = useState<WorkflowSpec[]>([]);
  const [selectedWorkflowId, setSelectedWorkflowId] = useState('');
  const [selectedWorkflowIds, setSelectedWorkflowIds] = useState<string[]>([]);
  const [workflowManagementMode, setWorkflowManagementMode] = useState(false);

  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.workflow_id === selectedWorkflowId) || null,
    [workflows, selectedWorkflowId],
  );
  const workflowIds = useMemo(
    () => workflows.map((workflow) => workflow.workflow_id).filter(Boolean),
    [workflows],
  );
  const selectedWorkflowIdSet = useMemo(() => new Set(selectedWorkflowIds), [selectedWorkflowIds]);
  const selectedWorkflows = useMemo(
    () => workflows.filter((workflow) => selectedWorkflowIdSet.has(workflow.workflow_id)),
    [workflows, selectedWorkflowIdSet],
  );
  const allWorkflowsSelected = workflowIds.length > 0 && selectedWorkflows.length === workflowIds.length;

  useEffect(() => {
    setSelectedWorkflowIds((current) => pruneSelectedIds(current, workflowIds));
  }, [workflowIds]);

  const applyWorkflows = useCallback((nextWorkflows: WorkflowSpec[], options: ApplyWorkflowOptions = {}) => {
    setWorkflows(nextWorkflows);
    setSelectedWorkflowId((current) => {
      const desired = options.selectedWorkflowId !== undefined ? options.selectedWorkflowId : current;
      if (desired && nextWorkflows.some((workflow) => workflow.workflow_id === desired)) return desired;
      return options.selectFirstWorkflow && nextWorkflows.length ? nextWorkflows[0].workflow_id : '';
    });
  }, []);

  const toggleWorkflowSelected = useCallback((workflowId: string) => {
    setSelectedWorkflowIds((current) => toggleSelectedId(current, workflowId));
  }, []);

  const finishWorkflowManagement = useCallback(() => {
    setWorkflowManagementMode(false);
    setSelectedWorkflowIds([]);
  }, []);

  return {
    allWorkflowsSelected,
    applyWorkflows,
    finishWorkflowManagement,
    selectedWorkflow,
    selectedWorkflowId,
    selectedWorkflowIds,
    selectedWorkflowIdSet,
    selectedWorkflows,
    setSelectedWorkflowId,
    setSelectedWorkflowIds,
    setWorkflowManagementMode,
    toggleWorkflowSelected,
    workflowIds,
    workflowManagementMode,
    workflows,
  };
}
