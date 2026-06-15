import { useMemo } from 'react';

import type {
  AgentSpec,
  RunnableSummary,
  WorkflowSpec,
} from '../types';
import {
  validateWorkflowDraft,
  workflowAgentRunReadinessIssue,
  workflowEdges,
  workflowHasRunnableSteps,
  workflowNodes,
  workflowRunnableStepRequiredMessage,
  workflowSpecStepRefs,
} from '../utils/workflow';

type UseRunTargetReadinessOptions = {
  agentRunIssueById: Map<string, string>;
  agents: AgentSpec[];
  runTarget: string;
  runnables: RunnableSummary[];
  workflows: WorkflowSpec[];
};

export function useRunTargetReadiness({
  agentRunIssueById,
  agents,
  runTarget,
  runnables,
  workflows,
}: UseRunTargetReadinessOptions) {
  const selectedRunTarget = useMemo(
    () => runTarget ? runnables.find((item) => item.id === runTarget) || null : null,
    [runTarget, runnables],
  );
  const selectedRunTargetWorkflow = useMemo(
    () => selectedRunTarget?.kind === 'workflow'
      ? workflows.find((workflow) => workflow.workflow_id === selectedRunTarget.id) || null
      : null,
    [selectedRunTarget, workflows],
  );
  const selectedRunTargetWorkflowNodes = useMemo(
    () => selectedRunTargetWorkflow ? workflowNodes(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowEdges = useMemo(
    () => selectedRunTargetWorkflow ? workflowEdges(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowPreviewSteps = useMemo(
    () => selectedRunTargetWorkflow ? workflowSpecStepRefs(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowValidation = useMemo(
    () => selectedRunTargetWorkflow
      ? validateWorkflowDraft(
        selectedRunTargetWorkflowNodes,
        selectedRunTargetWorkflowEdges,
        agents,
        workflows,
        selectedRunTargetWorkflow.workflow_id,
      )
      : { errors: [], warnings: [] },
    [agents, selectedRunTargetWorkflow, selectedRunTargetWorkflowEdges, selectedRunTargetWorkflowNodes, workflows],
  );
  const selectedRunTargetWorkflowAgentIssue = useMemo(
    () => selectedRunTargetWorkflow
      ? workflowAgentRunReadinessIssue(selectedRunTargetWorkflowNodes, agentRunIssueById)
      : '',
    [agentRunIssueById, selectedRunTargetWorkflow, selectedRunTargetWorkflowNodes],
  );
  const selectedRunTargetDisabled = selectedRunTarget?.enabled === false;
  const runTargetDisabledReason = useMemo(() => {
    if (!selectedRunTarget) return '';
    if (selectedRunTargetDisabled) return '目标已停用，无法运行。';
    if (selectedRunTarget.kind === 'agent') {
      const agent = agents.find((item) => item.agent_id === selectedRunTarget.id);
      if (!agent) return '找不到 Agent 定义，无法运行。';
      return agentRunIssueById.get(agent.agent_id) || '';
    }
    if (selectedRunTarget.kind === 'workflow') {
      if (!selectedRunTargetWorkflow) return '找不到 Workflow 定义，无法运行。';
      if (selectedRunTargetWorkflowValidation.errors.length) {
        return selectedRunTargetWorkflowValidation.errors[0] || '当前 Workflow 存在校验错误。';
      }
      if (!workflowHasRunnableSteps(selectedRunTargetWorkflowNodes)) {
        return workflowRunnableStepRequiredMessage;
      }
      if (selectedRunTargetWorkflowAgentIssue) return selectedRunTargetWorkflowAgentIssue;
    }
    return '';
  }, [agentRunIssueById, agents, selectedRunTarget, selectedRunTargetDisabled, selectedRunTargetWorkflow, selectedRunTargetWorkflowAgentIssue, selectedRunTargetWorkflowNodes, selectedRunTargetWorkflowValidation.errors]);

  return {
    runTargetDisabledReason,
    selectedRunTarget,
    selectedRunTargetWorkflowEdges,
    selectedRunTargetWorkflowNodes,
    selectedRunTargetWorkflowPreviewSteps,
    selectedRunTargetWorkflowValidation,
  };
}
