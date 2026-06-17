import { useCallback, useEffect, useState } from 'react';

import { apiGet } from '../../../lib/bridge';
import type { ExecutorPayload } from '../types';

export function useChatExecutor(pollIntervalMs: number) {
  const [executor, setExecutor] = useState<ExecutorPayload | null>(null);

  const refreshExecutor = useCallback(async () => {
    try {
      setExecutor(await apiGet<ExecutorPayload>('/ui/chat/executor'));
    } catch {
      setExecutor({ executor: 'none', available: false });
    }
  }, []);

  useEffect(() => {
    const timer = window.setInterval(() => {
      void refreshExecutor();
    }, pollIntervalMs);
    return () => window.clearInterval(timer);
  }, [pollIntervalMs, refreshExecutor]);

  return {
    executor,
    refreshExecutor,
  };
}
