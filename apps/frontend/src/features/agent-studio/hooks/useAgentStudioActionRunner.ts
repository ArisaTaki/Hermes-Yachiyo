import { useCallback } from 'react';

import type { StudioRefreshOptions } from './useAgentStudioRefresh';

export type AgentStudioRunnableAction = () => Promise<unknown> | unknown;

type UseAgentStudioActionRunnerOptions = {
  refresh: (options?: StudioRefreshOptions) => Promise<void>;
  setBusyAction: (label: string) => void;
  setError: (message: string) => void;
  setStatus: (message: string) => void;
};

function isStudioRefreshOptions(value: unknown): value is StudioRefreshOptions {
  if (!value || typeof value !== 'object') return false;
  const keys = [
    'selectedAgentId',
    'selectFirstAgent',
    'selectedWorkflowId',
    'selectFirstWorkflow',
    'runTarget',
    'selectedRunId',
    'statusMessage',
    'skipRefresh',
  ];
  return keys.some((key) => key in value);
}

export function useAgentStudioActionRunner({
  refresh,
  setBusyAction,
  setError,
  setStatus,
}: UseAgentStudioActionRunnerOptions) {
  const runAction = useCallback(async (action: AgentStudioRunnableAction, label: string) => {
    setBusyAction(label);
    setStatus(`${label}...`);
    setError('');
    try {
      const result = await action();
      const refreshOptions = isStudioRefreshOptions(result) ? result : {};
      if (!refreshOptions.skipRefresh) {
        await refresh(refreshOptions);
      }
      setStatus(refreshOptions.statusMessage || `${label} 完成`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} 失败`);
    } finally {
      setBusyAction('');
    }
  }, [refresh, setBusyAction, setError, setStatus]);

  return {
    runAction,
  };
}
