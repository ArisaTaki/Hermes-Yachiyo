import { useMemo } from 'react';

import type {
  AgentSpec,
  RunnableSummary,
  RunGroupSpec,
  RunSpec,
  WorkflowSpec,
} from '../types';
import type { PublicRunEvent, RunTimelineSnapshot } from '../../yachiyo-studio/types';
import {
  isActiveRunStatus,
  isPotentialWorkflowChildAgentRun,
  isWorkflowChildAgentRun,
  publicApprovalToRunPendingApproval,
  publicArtifactsOrLegacy,
  publicRunEventToTimelineEvent,
} from '../utils/runs';
import { runEventReplayToTimelineEvent } from '../utils/runTimeline';
import {
  validateWorkflowDraft,
  workflowAgentRunReadinessIssue,
  workflowChildRunRefs,
  workflowEdges,
  workflowHasRunnableSteps,
  workflowNodes,
  workflowPendingApprovalChildRunId,
  workflowRunHasChildRun,
  workflowRunnableStepRequiredMessage,
  workflowStepRefs,
} from '../utils/workflow';

type UseSelectedRunDetailStateOptions = {
  agentRunIssueById: Map<string, string>;
  agents: AgentSpec[];
  runById: Map<string, RunSpec>;
  runGroups: RunGroupSpec[];
  runnables: RunnableSummary[];
  selectedPublicRunTimeline: RunTimelineSnapshot | null;
  selectedRun: RunSpec | null;
  selectedRunId: string;
  selectedRunReplayEvents: PublicRunEvent[];
  workflows: WorkflowSpec[];
};

export function useSelectedRunDetailState({
  agentRunIssueById,
  agents,
  runById,
  runGroups,
  runnables,
  selectedPublicRunTimeline,
  selectedRun,
  selectedRunId,
  selectedRunReplayEvents,
  workflows,
}: UseSelectedRunDetailStateOptions) {
  const selectedRunExecutionEvents = useMemo(
    () => selectedRunReplayEvents.length
      ? selectedRunReplayEvents.map(runEventReplayToTimelineEvent)
      : selectedPublicRunTimeline?.events?.length
        ? selectedPublicRunTimeline.events.map(publicRunEventToTimelineEvent)
      : selectedRun?.timeline || [],
    [selectedPublicRunTimeline, selectedRun, selectedRunReplayEvents],
  );
  const selectedPublicRunApproval = useMemo(
    () => (
      selectedPublicRunTimeline?.pending_approval
      || selectedPublicRunTimeline?.approvals?.find((approval) => approval.status === 'pending')
      || null
    ),
    [selectedPublicRunTimeline],
  );
  const selectedRunApproval = useMemo(
    () => (
      publicApprovalToRunPendingApproval(selectedPublicRunApproval)
      || selectedRun?.pending_approval
      || null
    ),
    [selectedPublicRunApproval, selectedRun],
  );
  const selectedRunArtifacts = useMemo(
    () => publicArtifactsOrLegacy(
      selectedPublicRunTimeline?.artifacts,
      selectedRun?.artifacts as Array<Record<string, unknown>> | undefined,
    ),
    [selectedPublicRunTimeline, selectedRun],
  );
  const selectedRunWorkflow = useMemo(
    () => (
      selectedRun?.kind === 'workflow_run'
        ? workflows.find((workflow) => workflow.workflow_id === selectedRun.runnable_id) || null
        : null
    ),
    [selectedRun, workflows],
  );
  const selectedWorkflowSteps = useMemo(
    () => workflowStepRefs(selectedRun, selectedRunWorkflow),
    [selectedRun, selectedRunWorkflow],
  );
  const selectedWorkflowChildRefs = useMemo(
    () => workflowChildRunRefs(selectedRun),
    [selectedRun],
  );
  const selectedWorkflowApprovalChildRunId = useMemo(
    () => workflowPendingApprovalChildRunId(selectedRun),
    [selectedRun],
  );
  const selectedWorkflowApprovalChildRun = selectedWorkflowApprovalChildRunId
    ? runById.get(selectedWorkflowApprovalChildRunId) || null
    : null;
  const selectedWorkflowApprovalStep = selectedWorkflowApprovalChildRunId
    ? selectedWorkflowSteps.find((step) => step.childRunId === selectedWorkflowApprovalChildRunId) || null
    : null;
  const selectedWorkflowParentRun = useMemo(() => {
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return null;
    const timelineParent = Array.from(runById.values()).find((run) => (
      run.kind === 'workflow_run'
      && run.run_group_id === selectedRun.run_group_id
      && workflowRunHasChildRun(run, selectedRun.run_id)
    ));
    if (timelineParent) return timelineParent;
    if (!isWorkflowChildAgentRun(selectedRun)) return null;
    return Array.from(runById.values()).find((run) => (
      run.kind === 'workflow_run'
      && run.run_group_id === selectedRun.run_group_id
    )) || null;
  }, [runById, selectedRun]);
  const selectedWorkflowParentRunId = useMemo(() => {
    if (selectedWorkflowParentRun) return selectedWorkflowParentRun.run_id;
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return '';
    const group = runGroups.find((item) => item.run_group_id === selectedRun.run_group_id);
    const childRunIds = group?.child_run_ids || [];
    return childRunIds.find((runId) => {
      const run = runById.get(runId);
      return run?.kind === 'workflow_run' && workflowRunHasChildRun(run, selectedRun.run_id);
    }) || childRunIds.find((runId) => runId.startsWith('workflow_run_')) || '';
  }, [runById, runGroups, selectedRun, selectedWorkflowParentRun]);
  const activeRunPollKey = useMemo(() => {
    const nextIds = new Set<string>();
    const maybeAdd = (runId: string) => {
      if (!runId) return;
      const run = runById.get(runId);
      if (!run || isActiveRunStatus(run.status)) nextIds.add(runId);
    };
    maybeAdd(selectedRunId);
    selectedWorkflowChildRefs.forEach((ref) => maybeAdd(ref.childRunId));
    maybeAdd(selectedWorkflowApprovalChildRunId);
    return Array.from(nextIds).sort().join('|');
  }, [runById, selectedRunId, selectedWorkflowApprovalChildRunId, selectedWorkflowChildRefs]);
  const selectedRunIsLive = Boolean(selectedRunId && activeRunPollKey.split('|').includes(selectedRunId));
  const selectedRunAvatarUrl = useMemo(() => {
    if (!selectedRun) return '';
    const runnable = runnables.find((item) => item.id === selectedRun.runnable_id);
    const agent = agents.find((item) => item.agent_id === selectedRun.runnable_id);
    return runnable?.avatar_url || agent?.avatar_url || '';
  }, [agents, runnables, selectedRun]);
  const selectedRunRerunTarget = useMemo(() => {
    if (!selectedRun) return null;
    const expectedKind = selectedRun.kind === 'workflow_run' ? 'workflow' : 'agent';
    return runnables.find((item) => item.id === selectedRun.runnable_id && item.kind === expectedKind) || null;
  }, [runnables, selectedRun]);
  const selectedRunRerunDisabledReason = useMemo(() => {
    if (!selectedRun) return '';
    if (isActiveRunStatus(selectedRun.status)) return '当前 Run 还在进行中，请完成、失败或取消后再重跑。';
    if (!selectedRun.user_goal?.trim()) return '原 Run 没有记录任务目标，无法直接重跑。';
    if (!selectedRunRerunTarget) return '找不到原 Run 对应的 Agent 或 Workflow，无法重跑。';
    if (selectedRunRerunTarget.enabled === false) return '原目标已停用，无法重跑。';
    if (selectedRunRerunTarget.kind === 'agent') {
      const agent = agents.find((item) => item.agent_id === selectedRunRerunTarget.id);
      if (!agent) return '找不到 Agent 定义，无法重跑。';
      return agentRunIssueById.get(agent.agent_id) || '';
    }
    const workflow = workflows.find((item) => item.workflow_id === selectedRunRerunTarget.id);
    if (!workflow) return '找不到 Workflow 定义，无法重跑。';
    const validation = validateWorkflowDraft(
      workflowNodes(workflow),
      workflowEdges(workflow),
      agents,
      workflows,
      workflow.workflow_id,
    );
    if (validation.errors.length) return validation.errors[0] || '当前 Workflow 存在校验错误。';
    if (!workflowHasRunnableSteps(workflowNodes(workflow))) return workflowRunnableStepRequiredMessage;
    return workflowAgentRunReadinessIssue(workflowNodes(workflow), agentRunIssueById);
  }, [agentRunIssueById, agents, selectedRun, selectedRunRerunTarget, workflows]);

  return {
    activeRunPollKey,
    selectedRunApproval,
    selectedRunArtifacts,
    selectedRunAvatarUrl,
    selectedRunExecutionEvents,
    selectedRunIsLive,
    selectedRunRerunDisabledReason,
    selectedRunRerunTarget,
    selectedRunWorkflow,
    selectedWorkflowApprovalChildRun,
    selectedWorkflowApprovalChildRunId,
    selectedWorkflowApprovalStep,
    selectedWorkflowChildRefs,
    selectedWorkflowParentRun,
    selectedWorkflowParentRunId,
    selectedWorkflowSteps,
  };
}
