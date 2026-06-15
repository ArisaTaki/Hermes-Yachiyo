import { useCallback, useEffect, useMemo, useState } from 'react';

import type { WorkflowSpec } from '../types';

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

function mergeWorkflowById(current: WorkflowSpec[], nextWorkflow: WorkflowSpec): WorkflowSpec[] {
  if (!nextWorkflow.workflow_id) return current;
  const index = current.findIndex((workflow) => workflow.workflow_id === nextWorkflow.workflow_id);
  if (index < 0) return [...current, nextWorkflow];
  const next = [...current];
  next[index] = nextWorkflow;
  return next;
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

  const mergeWorkflow = useCallback((nextWorkflow: WorkflowSpec) => {
    setWorkflows((current) => mergeWorkflowById(current, nextWorkflow));
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
    mergeWorkflow,
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
