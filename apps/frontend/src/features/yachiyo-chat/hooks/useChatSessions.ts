import { useCallback, useEffect, useRef, useState } from 'react';

import { apiGet } from '../../../lib/bridge';
import type { SessionsPayload } from '../types';

type UseChatSessionsOptions = {
  activePollIntervalMs: number;
  idlePollIntervalMs: number;
  isProcessing: boolean;
  refreshYachiyoTasksForSession: (sessionId: string) => void | Promise<void>;
};

type LoadSessionsOptions = {
  poll?: boolean;
};

const ACTIVE_TASKS_REFRESH_INTERVAL_MS = 2000;
const IDLE_TASKS_REFRESH_INTERVAL_MS = 10_000;
const CHAT_SESSIONS_REQUEST_TIMEOUT_MS = 15_000;

export function useChatSessions({
  activePollIntervalMs,
  idlePollIntervalMs,
  isProcessing,
  refreshYachiyoTasksForSession,
}: UseChatSessionsOptions) {
  const [sessions, setSessions] = useState<SessionsPayload | null>(null);
  const [sessionsLoaded, setSessionsLoaded] = useState(false);
  const [sessionQuery, setSessionQuery] = useState('');
  const [debouncedSessionQuery, setDebouncedSessionQuery] = useState('');
  const latestDebouncedSessionQueryRef = useRef(debouncedSessionQuery);
  const sessionsExplicitLoadEpochRef = useRef(0);
  const sessionsInFlightRef = useRef<Promise<SessionsPayload | undefined> | null>(null);
  const sessionsRequestAbortControllerRef = useRef<AbortController | null>(null);
  const sessionsRequestIsPollRef = useRef(false);
  const refreshedTasksSessionIdRef = useRef('');
  const tasksRefreshStartedAtRef = useRef(0);
  const tasksRefreshInFlightRef = useRef<Promise<void> | null>(null);
  const forceTasksRefreshRef = useRef(false);
  const previousProcessingRef = useRef(isProcessing);
  const mountedRef = useRef(true);
  latestDebouncedSessionQueryRef.current = debouncedSessionQuery;
  if (previousProcessingRef.current && !isProcessing) forceTasksRefreshRef.current = true;
  previousProcessingRef.current = isProcessing;

  const refreshTasksIfDue = useCallback((sessionId: string, force = false): Promise<void> => {
    if (!sessionId) {
      refreshedTasksSessionIdRef.current = '';
      tasksRefreshStartedAtRef.current = 0;
      return Promise.resolve();
    }
    const sessionChanged = sessionId !== refreshedTasksSessionIdRef.current;
    const refreshInterval = isProcessing
      ? ACTIVE_TASKS_REFRESH_INTERVAL_MS
      : IDLE_TASKS_REFRESH_INTERVAL_MS;
    const forceRefresh = force || forceTasksRefreshRef.current;
    const refreshDue = forceRefresh
      || Date.now() - tasksRefreshStartedAtRef.current >= refreshInterval;
    if (!sessionChanged && tasksRefreshInFlightRef.current && !forceRefresh) {
      return tasksRefreshInFlightRef.current;
    }
    if (!sessionChanged && !refreshDue) return Promise.resolve();

    forceTasksRefreshRef.current = false;
    refreshedTasksSessionIdRef.current = sessionId;
    tasksRefreshStartedAtRef.current = Date.now();
    const current = tasksRefreshInFlightRef.current;
    const execute = () => Promise.resolve().then(() => refreshYachiyoTasksForSession(sessionId));
    const pending = current
      ? current.catch(() => undefined).then(execute)
      : execute();
    let tracked: Promise<void>;
    tracked = pending
      .catch(() => {
        if (refreshedTasksSessionIdRef.current === sessionId) {
          refreshedTasksSessionIdRef.current = '';
          tasksRefreshStartedAtRef.current = 0;
        }
      })
      .finally(() => {
        if (tasksRefreshInFlightRef.current === tracked) tasksRefreshInFlightRef.current = null;
      });
    tasksRefreshInFlightRef.current = tracked;
    return tracked;
  }, [isProcessing, refreshYachiyoTasksForSession]);

  const runSessionsLoad = useCallback(async (
    queryValue: string,
    poll: boolean,
    loadEpoch: number,
  ) => {
    const isCurrentRequest = () => (
      mountedRef.current
      && queryValue === latestDebouncedSessionQueryRef.current
      && (!poll || loadEpoch === sessionsExplicitLoadEpochRef.current)
    );
    if (!isCurrentRequest()) return;
    const requestController = new AbortController();
    sessionsRequestAbortControllerRef.current = requestController;
    sessionsRequestIsPollRef.current = poll;
    try {
      const query = new URLSearchParams();
      query.set('limit', '0');
      if (queryValue) query.set('query', queryValue);
      const payload = await apiGet<SessionsPayload>(`/ui/chat/sessions?${query.toString()}`, {
        signal: requestController.signal,
        timeoutMs: CHAT_SESSIONS_REQUEST_TIMEOUT_MS,
      });
      if (payload.ok === false) throw new Error('读取会话失败');
      if (!isCurrentRequest()) return;
      setSessions(payload);
      const currentSessionId = String(payload.current_session_id || '').trim();
      const taskRefresh = refreshTasksIfDue(currentSessionId, !poll);
      if (!poll) await taskRefresh;
      return isCurrentRequest() ? payload : undefined;
    } catch {
      if (isCurrentRequest()) setSessions(null);
      return undefined;
    } finally {
      if (isCurrentRequest()) setSessionsLoaded(true);
      if (sessionsRequestAbortControllerRef.current === requestController) {
        sessionsRequestAbortControllerRef.current = null;
        sessionsRequestIsPollRef.current = false;
      }
    }
  }, [refreshTasksIfDue]);

  const scheduleSessionsLoad = useCallback((options: LoadSessionsOptions = {}) => {
    const current = sessionsInFlightRef.current;
    if (options.poll && current) return current;

    const poll = Boolean(options.poll);
    const loadEpoch = poll
      ? sessionsExplicitLoadEpochRef.current
      : ++sessionsExplicitLoadEpochRef.current;
    if (!poll && sessionsRequestIsPollRef.current) {
      sessionsRequestAbortControllerRef.current?.abort();
    }
    const queryValue = latestDebouncedSessionQueryRef.current;
    const execute = () => runSessionsLoad(queryValue, poll, loadEpoch);
    const pending = current
      ? current.catch(() => undefined).then(execute)
      : execute();
    let tracked: Promise<SessionsPayload | undefined>;
    tracked = pending.finally(() => {
      if (sessionsInFlightRef.current === tracked) sessionsInFlightRef.current = null;
    });
    sessionsInFlightRef.current = tracked;
    return tracked;
  }, [runSessionsLoad]);

  const loadSessionsSnapshot = useCallback(
    () => scheduleSessionsLoad(),
    [scheduleSessionsLoad],
  );
  const loadSessions = useCallback(async () => {
    await loadSessionsSnapshot();
  }, [loadSessionsSnapshot]);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      sessionsExplicitLoadEpochRef.current += 1;
      sessionsRequestAbortControllerRef.current?.abort();
    };
  }, []);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setDebouncedSessionQuery(sessionQuery.trim());
    }, 180);
    return () => window.clearTimeout(timer);
  }, [sessionQuery]);

  useEffect(() => {
    void loadSessions();
  }, [debouncedSessionQuery, loadSessions]);

  useEffect(() => {
    const interval = isProcessing ? activePollIntervalMs : idlePollIntervalMs;
    let timer: number | null = null;
    let disposed = false;

    const clearTimer = () => {
      if (timer === null) return;
      window.clearTimeout(timer);
      timer = null;
    };
    const scheduleNextPoll = () => {
      clearTimer();
      if (disposed || document.hidden) return;
      timer = window.setTimeout(() => {
        timer = null;
        void scheduleSessionsLoad({ poll: true })
          .catch(() => undefined)
          .finally(scheduleNextPoll);
      }, interval);
    };
    const handleVisibilityChange = () => {
      clearTimer();
      if (disposed || document.hidden) return;
      void loadSessions()
        .catch(() => undefined)
        .finally(scheduleNextPoll);
    };

    document.addEventListener('visibilitychange', handleVisibilityChange);
    scheduleNextPoll();
    return () => {
      disposed = true;
      clearTimer();
      document.removeEventListener('visibilitychange', handleVisibilityChange);
    };
  }, [activePollIntervalMs, idlePollIntervalMs, isProcessing, loadSessions, scheduleSessionsLoad]);

  return {
    debouncedSessionQuery,
    loadSessions,
    loadSessionsSnapshot,
    sessions,
    sessionsLoaded,
    sessionQuery,
    setSessionQuery,
  };
}
