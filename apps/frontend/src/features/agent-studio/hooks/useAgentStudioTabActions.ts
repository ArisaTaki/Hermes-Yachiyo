import { useCallback } from 'react';

import { navigateTo } from '../../../lib/view';
import type { StudioTab } from '../studioTabs';
import type { StudioRefreshOptions } from './useAgentStudioRefresh';

type UseAgentStudioTabActionsOptions = {
  refresh: (options?: StudioRefreshOptions) => Promise<void>;
  setError: (message: string) => void;
  setStatus: (message: string) => void;
  setTab: (tab: StudioTab) => void;
};

export function useAgentStudioTabActions({
  refresh,
  setError,
  setStatus,
  setTab,
}: UseAgentStudioTabActionsOptions) {
  const activateTab = useCallback((nextTab: StudioTab) => {
    setTab(nextTab);
    setStatus('');
    setError('');
    navigateTo('agents', nextTab === 'agents' ? {} : { tab: nextTab }, ['run', 'tab', 'target', 'goal']);
    if (nextTab === 'agents') {
      void refresh().catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '刷新 Agent 列表失败');
      });
    }
  }, [refresh, setError, setStatus, setTab]);

  return {
    activateTab,
  };
}
