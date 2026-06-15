import { useMemo } from 'react';
import type { Edge, Node } from '@xyflow/react';

import type { AgentSpec, SkillSpec, WorkflowSpec } from '../types';
import type { ModelProfile, ModelProfileDefaults } from '../../../lib/modelProfiles';
import { agentRunReadinessIssue } from '../utils/agents';
import {
  workflowAgentRunReadinessIssue,
  workflowHasRunnableSteps,
  workflowRequestEdges,
  workflowRequestNodes,
  workflowRunnableStepRequiredMessage,
  workflowSpecStepRefs,
} from '../utils/workflow';

type UseWorkflowRunReadinessOptions = {
  agents: AgentSpec[];
  busy: boolean;
  chatModelProfiles: ModelProfile[];
  edges: Edge[];
  modelDefaults: ModelProfileDefaults;
  nodes: Node[];
  selectedWorkflow: WorkflowSpec | null;
  skills: SkillSpec[];
  workflowDescription: string;
  workflowEnabled: boolean;
  workflowErrors: string[];
  workflowName: string;
  workflowNameError: string;
  workflowRunGoal: string;
};

export function useWorkflowRunReadiness({
  agents,
  busy,
  chatModelProfiles,
  edges,
  modelDefaults,
  nodes,
  selectedWorkflow,
  skills,
  workflowDescription,
  workflowEnabled,
  workflowErrors,
  workflowName,
  workflowNameError,
  workflowRunGoal,
}: UseWorkflowRunReadinessOptions) {
  const workflowRunPreviewSteps = useMemo(
    () => workflowSpecStepRefs({
      workflow_id: selectedWorkflow?.workflow_id || 'draft',
      name: workflowName.trim() || 'New Workflow',
      description: workflowDescription.trim(),
      nodes: workflowRequestNodes(nodes),
      edges: workflowRequestEdges(edges),
      enabled: true,
    }),
    [edges, nodes, selectedWorkflow?.workflow_id, workflowDescription, workflowName],
  );
  const workflowHasErrors = workflowErrors.length > 0;
  const workflowPrimaryError = workflowErrors[0] || '';
  const agentRunIssueById = useMemo(() => {
    const next = new Map<string, string>();
    agents.forEach((agent) => {
      const issue = agentRunReadinessIssue(agent, chatModelProfiles, modelDefaults, skills);
      if (issue) next.set(agent.agent_id, issue);
    });
    return next;
  }, [agents, chatModelProfiles, modelDefaults, skills]);
  const workflowRunAgentIssue = useMemo(
    () => workflowAgentRunReadinessIssue(nodes, agentRunIssueById),
    [agentRunIssueById, nodes],
  );
  const workflowRunDisabledReason = useMemo(() => {
    if (!workflowEnabled) return '当前 Workflow 已停用，无法运行。';
    if (workflowNameError) return workflowNameError;
    if (workflowHasErrors) return workflowPrimaryError || '当前 Workflow 存在校验错误。';
    if (!workflowRunGoal.trim()) return '请输入运行目标。';
    if (!workflowHasRunnableSteps(nodes)) return workflowRunnableStepRequiredMessage;
    if (workflowRunAgentIssue) return workflowRunAgentIssue;
    return '';
  }, [nodes, workflowEnabled, workflowHasErrors, workflowNameError, workflowPrimaryError, workflowRunAgentIssue, workflowRunGoal]);

  return {
    agentRunIssueById,
    workflowHasErrors,
    workflowPrimaryError,
    workflowRunDisabled: busy || Boolean(workflowRunDisabledReason),
    workflowRunDisabledReason,
    workflowRunPreviewSteps,
  };
}
