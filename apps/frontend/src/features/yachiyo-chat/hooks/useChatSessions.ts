import { useCallback, useEffect, useState } from 'react';

import { apiGet } from '../../../lib/bridge';
import type { SessionsPayload } from '../types';

type UseChatSessionsOptions = {
  refreshYachiyoTasksForSession: (sessionId: string) => void | Promise<void>;
};

export function useChatSessions({
  refreshYachiyoTasksForSession,
}: UseChatSessionsOptions) {
  const [sessions, setSessions] = useState<SessionsPayload | null>(null);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [sessionQuery, setSessionQuery] = useState('');
  const [debouncedSessionQuery, setDebouncedSessionQuery] = useState('');

  const loadSessions = useCallback(async () => {
    try {
      const query = new URLSearchParams();
      query.set('limit', '0');
      if (debouncedSessionQuery) query.set('query', debouncedSessionQuery);
      const payload = await apiGet<SessionsPayload>(`/ui/chat/sessions?${query.toString()}`);
      if (payload.ok === false) throw new Error('读取会话失败');
      setSessions(payload);
      if (payload.current_session_id) void refreshYachiyoTasksForSession(payload.current_session_id);
    } catch {
      setSessions(null);
    } finally {
      setSessionsLoaded(true);
    }
  }, [debouncedSessionQuery, refreshYachiyoTasksForSession]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSessionQuery(sessionQuery.trim());
    }, 180);
    return () => window.clearTimeout(timer);
  }, [sessionQuery]);

  return {
    debouncedSessionQuery,
    loadSessions,
    sessions,
    sessionsLoaded,
    sessionQuery,
    setSessionQuery,
  };
}
