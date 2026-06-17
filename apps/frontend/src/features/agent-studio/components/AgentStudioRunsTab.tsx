import type { Node } from '@xyflow/react';
import type { ComponentProps } from 'react';

import {
  agentCapabilityLine,
  runnableCapabilityLine,
  runnableOptionLabel,
} from '../utils/agents';
import {
  formatRunDate,
  isActiveRunStatus,
  normalizeRunStatus,
  runHistoryGroupSummary,
  runKindLabel,
  runStatusLabel,
  runStatusTone,
} from '../utils/runs';
import {
  skippedWorkflowArtifactLabel,
  workflowRunArtifactForStep,
  workflowStepArtifacts,
  workflowStepKindLabel,
  workflowStepSummary,
} from '../utils/workflow';
import type { AgentSpec } from '../types';
import { RunManagementTab } from './RunManagementTab';
import { WorkflowRunPreview, type WorkflowPreviewStep } from './WorkflowRunPreview';

type RunManagementTabProps = ComponentProps<typeof RunManagementTab>;

type AgentStudioRunsTabProps = Omit<
  RunManagementTabProps,
  | 'formatRunDate'
  | 'isActiveRunStatus'
  | 'normalizeRunStatus'
  | 'runHistoryGroupSummary'
  | 'runKindLabel'
  | 'runStatusLabel'
  | 'runStatusTone'
  | 'runnableCapabilityLine'
  | 'runnableOptionLabel'
  | 'skippedWorkflowArtifactLabel'
  | 'workflowPreview'
  | 'workflowRunArtifactForStep'
  | 'workflowStepArtifacts'
  | 'workflowStepKindLabel'
  | 'workflowStepSummary'
> & {
  agents: AgentSpec[];
  agentIssueById: Map<string, string>;
  selectedRunTargetWorkflowNodes: Node[];
  selectedRunTargetWorkflowPreviewSteps: WorkflowPreviewStep[];
};

export function AgentStudioRunsTab({
  agents,
  agentIssueById,
  selectedRunTargetWorkflowNodes,
  selectedRunTargetWorkflowPreviewSteps,
  ...props
}: AgentStudioRunsTabProps) {
  const workflowPreview = props.selectedRunTarget?.kind === 'workflow' ? (
    <WorkflowRunPreview
      agents={agents}
      agentCapabilityLine={agentCapabilityLine}
      agentIssueById={agentIssueById}
      sourceNodes={selectedRunTargetWorkflowNodes}
      steps={selectedRunTargetWorkflowPreviewSteps}
    />
  ) : null;

  return (
    <RunManagementTab
      {...props}
      formatRunDate={formatRunDate}
      isActiveRunStatus={isActiveRunStatus}
      normalizeRunStatus={normalizeRunStatus}
      runHistoryGroupSummary={runHistoryGroupSummary}
      runKindLabel={runKindLabel}
      runStatusLabel={runStatusLabel}
      runStatusTone={runStatusTone}
      runnableCapabilityLine={runnableCapabilityLine}
      runnableOptionLabel={runnableOptionLabel}
      skippedWorkflowArtifactLabel={skippedWorkflowArtifactLabel}
      workflowPreview={workflowPreview}
      workflowRunArtifactForStep={workflowRunArtifactForStep}
      workflowStepArtifacts={workflowStepArtifacts}
      workflowStepKindLabel={workflowStepKindLabel}
      workflowStepSummary={workflowStepSummary}
    />
  );
}
