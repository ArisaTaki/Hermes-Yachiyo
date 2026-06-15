import type { Dispatch, SetStateAction } from 'react';

import {
  deleteWorkflow,
  type WorkflowSpec,
} from '../../../lib/agents';

type WorkflowDeletionRefreshOptions = {
  selectedWorkflowId?: string;
};

type ConfirmDialogRequest = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

type UseWorkflowDeletionActionsOptions = {
  resetWorkflowDraft: () => void;
  runAction: (action: () => Promise<WorkflowDeletionRefreshOptions | void>, label: string) => void;
  selectedWorkflow: WorkflowSpec | null;
  selectedWorkflowId: string;
  selectedWorkflows: WorkflowSpec[];
  setSelectedWorkflowIds: Dispatch<SetStateAction<string[]>>;
  showConfirmDialog: (dialog: ConfirmDialogRequest) => void;
};

export function useWorkflowDeletionActions({
  resetWorkflowDraft,
  runAction,
  selectedWorkflow,
  selectedWorkflowId,
  selectedWorkflows,
  setSelectedWorkflowIds,
  showConfirmDialog,
}: UseWorkflowDeletionActionsOptions) {
  function requestDeleteWorkflow() {
    if (!selectedWorkflow) return;
    const workflowId = selectedWorkflow.workflow_id;
    const workflowName = selectedWorkflow.name || 'Workflow';
    showConfirmDialog({
      title: `删除「${workflowName}」？`,
      description: '这个 Workflow 定义会从 Workflow Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: '删除 Workflow',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteWorkflow(workflowId);
        setSelectedWorkflowIds((current) => current.filter((id) => id !== workflowId));
        resetWorkflowDraft();
        return { selectedWorkflowId: '' };
      }, '删除 Workflow'),
    });
  }

  function requestDeleteSelectedWorkflows() {
    const targets = selectedWorkflows.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((workflow) => workflow.workflow_id));
    const deletingCurrent = Boolean(selectedWorkflowId && targetIds.has(selectedWorkflowId));
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Workflow？`,
      description: '这些 Workflow 定义会从 Workflow Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: `删除 ${targets.length} 个 Workflow`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const workflow of targets) {
          await deleteWorkflow(workflow.workflow_id);
        }
        setSelectedWorkflowIds((current) => current.filter((id) => !targetIds.has(id)));
        if (deletingCurrent) {
          resetWorkflowDraft();
          return { selectedWorkflowId: '' };
        }
        return undefined;
      }, '批量删除 Workflow'),
    });
  }

  return {
    requestDeleteSelectedWorkflows,
    requestDeleteWorkflow,
  };
}
