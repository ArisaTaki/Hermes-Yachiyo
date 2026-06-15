import { useEffect } from 'react';

import type { StudioTab } from '../studioTabs';
import type { StudioRefreshOptions } from './useAgentStudioRefresh';

type UseAgentStudioLoadLifecycleOptions = {
  agentCount: number;
  busyAction: string;
  draftAgentId: string;
  loading: boolean;
  refresh: (options?: StudioRefreshOptions) => Promise<void>;
  selectedAgentId: string;
  setError: (message: string) => void;
  setLoading: (loading: boolean) => void;
  tab: StudioTab;
};

export function useAgentStudioLoadLifecycle({
  agentCount,
  busyAction,
  draftAgentId,
  loading,
  refresh,
  selectedAgentId,
  setError,
  setLoading,
  tab,
}: UseAgentStudioLoadLifecycleOptions) {
  useEffect(() => {
    setLoading(true);
    refresh()
      .then(() => setError(''))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '读取 Agent Studio 失败'))
      .finally(() => setLoading(false));
  }, [refresh, setError, setLoading]);

  useEffect(() => {
    if (tab !== 'agents' || loading || busyAction || agentCount) return;
    if (!selectedAgentId && !draftAgentId) return;
    let disposed = false;
    refresh()
      .then(() => {
        if (!disposed) setError('');
      })
      .catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : '刷新 Agent 列表失败');
      });
    return () => {
      disposed = true;
    };
  }, [agentCount, busyAction, draftAgentId, loading, refresh, selectedAgentId, setError, tab]);
}
