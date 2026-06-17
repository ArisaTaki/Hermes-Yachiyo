import { useEffect, useState } from 'react';

import { listYachiyoChatRunnables, type ChatRunnableSummary } from '../runnables';

const CHAT_RUNNABLE_REFRESH_MS = 10_000;

export function useChatRunnables(enabled = true): ChatRunnableSummary[] {
  const [runnables, setRunnables] = useState<ChatRunnableSummary[]>([]);

  useEffect(() => {
    if (!enabled) return;
    let disposed = false;

    async function refreshRunnables() {
      try {
        const payload = await listYachiyoChatRunnables();
        if (disposed) return;
        setRunnables(payload.filter((item) => item.enabled !== false));
      } catch {
        if (!disposed) setRunnables([]);
      }
    }

    void refreshRunnables();
    const timer = window.setInterval(refreshRunnables, CHAT_RUNNABLE_REFRESH_MS);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [enabled]);

  return runnables;
}
