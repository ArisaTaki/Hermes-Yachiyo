import { useCallback } from 'react';

import {
  type RunnableSummary,
  type RunSpec,
  type WorkflowSpec,
} from '../types';
import {
  rerunYachiyoRun,
  startYachiyoAgentRun,
  startYachiyoWorkflowRun,
} from '../../yachiyo-studio/api';
import type { RerunRunRequest } from '../../yachiyo-studio/types';
import { publicRunTimelineToStudioRunSpec } from '../utils/runs';

export type RunLaunchActionRefreshOptions = {
  selectedAgentId?: string;
  selectedWorkflowId?: string;
  runTarget?: string;
  selectedRunId?: string;
  statusMessage?: string;
};

type UseRunLaunchActionsOptions = {
  agentQuickRunDisabledReason: string;
  agentRunGoal: string;
  draftAgentId: string;
  openRunDetail: (runId: string, options?: { revealInHistory?: boolean }) => void;
  refreshRunGroupsForRuns: (runs: RunSpec[]) => Promise<void>;
  runGoal: string;
  runnables: RunnableSummary[];
  runTarget: string;
  saveWorkflowDraft: () => Promise<WorkflowSpec>;
  selectedRun: RunSpec | null;
  selectedRunRerunDisabledReason: string;
  selectedRunRerunTarget: RunnableSummary | null;
  setAgentRunGoal: (goal: string) => void;
  setError: (message: string) => void;
  setRunGoal: (goal: string) => void;
  setRunTarget: (target: string) => void;
  setStatus: (message: string) => void;
  setWorkflowRunGoal: (goal: string) => void;
  upsertRunDetailCache: (runs: RunSpec[]) => void;
  workflowRunDisabledReason: string;
  workflowRunGoal: string;
};

export function useRunLaunchActions({
  agentQuickRunDisabledReason,
  agentRunGoal,
  draftAgentId,
  openRunDetail,
  refreshRunGroupsForRuns,
  runGoal,
  runnables,
  runTarget,
  saveWorkflowDraft,
  selectedRun,
  selectedRunRerunDisabledReason,
  selectedRunRerunTarget,
  setAgentRunGoal,
  setError,
  setRunGoal,
  setRunTarget,
  setStatus,
  setWorkflowRunGoal,
  upsertRunDetailCache,
  workflowRunDisabledReason,
  workflowRunGoal,
}: UseRunLaunchActionsOptions) {
  const runCurrentAgent = useCallback(async (): Promise<RunLaunchActionRefreshOptions> => {
    if (agentQuickRunDisabledReason) throw new Error(agentQuickRunDisabledReason);
    const agentId = draftAgentId || '';
    const goal = agentRunGoal.trim();
    const run = publicRunTimelineToStudioRunSpec(
      await startYachiyoAgentRun(agentId, goal),
      { kind: 'agent_run', runnableId: agentId, userGoal: goal },
    );
    setAgentRunGoal('');
    setRunTarget(agentId);
    openRunDetail(run.run_id, { revealInHistory: true });
    return { selectedAgentId: agentId, runTarget: agentId, selectedRunId: run.run_id };
  }, [agentQuickRunDisabledReason, agentRunGoal, draftAgentId, openRunDetail, setAgentRunGoal, setRunTarget]);

  const runCurrentWorkflow = useCallback(async (): Promise<RunLaunchActionRefreshOptions> => {
    if (workflowRunDisabledReason) throw new Error(workflowRunDisabledReason);
    const goal = workflowRunGoal.trim();
    const saved = await saveWorkflowDraft();
    const run = publicRunTimelineToStudioRunSpec(
      await startYachiyoWorkflowRun(saved.workflow_id, goal),
      { kind: 'workflow_run', runnableId: saved.workflow_id, userGoal: goal },
    );
    setWorkflowRunGoal('');
    setRunTarget(saved.workflow_id);
    openRunDetail(run.run_id, { revealInHistory: true });
    return { selectedWorkflowId: saved.workflow_id, runTarget: saved.workflow_id, selectedRunId: run.run_id };
  }, [openRunDetail, saveWorkflowDraft, setRunTarget, setWorkflowRunGoal, workflowRunDisabledReason, workflowRunGoal]);

  const createRunFromTarget = useCallback(async (): Promise<RunLaunchActionRefreshOptions | void> => {
    const target = runnables.find((item) => item.id === runTarget);
    if (!target) return;
    const goal = runGoal.trim();
    const run = target.kind === 'agent'
      ? publicRunTimelineToStudioRunSpec(
        await startYachiyoAgentRun(target.id, goal),
        { kind: 'agent_run', runnableId: target.id, runnableName: target.name, userGoal: goal },
      )
      : publicRunTimelineToStudioRunSpec(
        await startYachiyoWorkflowRun(target.id, goal),
        { kind: 'workflow_run', runnableId: target.id, runnableName: target.name, userGoal: goal },
      );
    openRunDetail(run.run_id, { revealInHistory: true });
    setRunGoal('');
    return { selectedRunId: run.run_id, runTarget: target.id };
  }, [openRunDetail, runGoal, runTarget, runnables, setRunGoal]);

  const prepareSelectedRunRerun = useCallback(() => {
    if (!selectedRun) return;
    if (!selectedRunRerunTarget) {
      setError('找不到原 Run 对应的 Agent 或 Workflow，无法准备重跑。');
      return;
    }
    setRunTarget(selectedRunRerunTarget.id);
    setRunGoal(selectedRun.user_goal || '');
    setStatus(`已把「${selectedRunRerunTarget.name || selectedRun.runnable_name || selectedRun.runnable_id}」和原任务填回 Run 面板。`);
    setError('');
  }, [selectedRun, selectedRunRerunTarget, setError, setRunGoal, setRunTarget, setStatus]);

  const rerunSelectedRun = useCallback(async (): Promise<RunLaunchActionRefreshOptions> => {
    if (!selectedRun) throw new Error('请选择要重跑的 Run');
    if (selectedRunRerunDisabledReason) throw new Error(selectedRunRerunDisabledReason);
    if (!selectedRunRerunTarget) throw new Error('找不到原 Run 对应的 Agent 或 Workflow，无法重跑。');
    const run = publicRunTimelineToStudioRunSpec(
      await rerunYachiyoRun(selectedRun.run_id),
      {
        kind: selectedRun.kind,
        runnableId: selectedRun.runnable_id,
        runnableName: selectedRun.runnable_name,
        userGoal: selectedRun.user_goal,
      },
    );
    upsertRunDetailCache([run]);
    await refreshRunGroupsForRuns([run]);
    openRunDetail(run.run_id, { revealInHistory: true });
    if (selectedRunRerunTarget.kind === 'agent') {
      return {
        selectedAgentId: selectedRunRerunTarget.id,
        selectedRunId: run.run_id,
        runTarget: selectedRunRerunTarget.id,
        statusMessage: '已按原任务重新运行 Agent。',
      };
    }
    return {
      selectedWorkflowId: selectedRunRerunTarget.id,
      selectedRunId: run.run_id,
      runTarget: selectedRunRerunTarget.id,
      statusMessage: '已按原任务重新运行 Workflow。',
    };
  }, [
    openRunDetail,
    refreshRunGroupsForRuns,
    selectedRun,
    selectedRunRerunDisabledReason,
    selectedRunRerunTarget,
    upsertRunDetailCache,
  ]);

  const rerunWorkflowScope = useCallback(async (
    request: RerunRunRequest,
  ): Promise<RunLaunchActionRefreshOptions> => {
    if (!selectedRun) throw new Error('请选择要重跑的 Workflow Run');
    if (selectedRun.kind !== 'workflow_run') throw new Error('只能重跑 Workflow 节点或分支。');
    if (!['completed', 'failed', 'cancelled'].includes(selectedRun.status)) {
      throw new Error('当前 Workflow Run 还在进行中，请完成、失败或取消后再重跑。');
    }
    if (!selectedRun.user_goal?.trim()) throw new Error('原 Workflow Run 没有记录任务目标，无法重跑。');
    const workflowTargetId = selectedRunRerunTarget?.id || selectedRun.runnable_id;
    if (!workflowTargetId) throw new Error('找不到原 Workflow，无法重跑。');
    const run = publicRunTimelineToStudioRunSpec(
      await rerunYachiyoRun(selectedRun.run_id, request),
      {
        kind: 'workflow_run',
        runnableId: selectedRun.runnable_id,
        runnableName: selectedRun.runnable_name,
        userGoal: selectedRun.user_goal,
      },
    );
    upsertRunDetailCache([run]);
    await refreshRunGroupsForRuns([run]);
    openRunDetail(run.run_id, { revealInHistory: true });
    return {
      selectedWorkflowId: workflowTargetId,
      selectedRunId: run.run_id,
      runTarget: workflowTargetId,
      statusMessage: request.scope === 'workflow_branch'
        ? '已从 Workflow 分支重新运行。'
        : '已从 Workflow 节点重新运行。',
    };
  }, [
    openRunDetail,
    refreshRunGroupsForRuns,
    selectedRun,
    selectedRunRerunTarget,
    upsertRunDetailCache,
  ]);

  return {
    createRunFromTarget,
    prepareSelectedRunRerun,
    rerunWorkflowScope,
    rerunSelectedRun,
    runCurrentAgent,
    runCurrentWorkflow,
  };
}
