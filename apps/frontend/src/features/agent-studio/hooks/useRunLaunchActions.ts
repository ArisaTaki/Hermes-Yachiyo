import { useCallback } from 'react';

import {
  type RunnableSummary,
  type RunSpec,
  type WorkflowSpec,
} from '../../../lib/agents';
import {
  rerunYachiyoRun,
  startYachiyoAgentRun,
  startYachiyoWorkflowRun,
} from '../../yachiyo-studio/api';
import { publicRunTimelineToRunSpec } from '../utils/runs';

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
    const run = publicRunTimelineToRunSpec(
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
    const run = publicRunTimelineToRunSpec(
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
      ? publicRunTimelineToRunSpec(
        await startYachiyoAgentRun(target.id, goal),
        { kind: 'agent_run', runnableId: target.id, runnableName: target.name, userGoal: goal },
      )
      : publicRunTimelineToRunSpec(
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
    const run = publicRunTimelineToRunSpec(
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

  return {
    createRunFromTarget,
    prepareSelectedRunRerun,
    rerunSelectedRun,
    runCurrentAgent,
    runCurrentWorkflow,
  };
}
