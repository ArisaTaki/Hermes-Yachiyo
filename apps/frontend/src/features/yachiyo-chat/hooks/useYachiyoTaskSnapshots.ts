import { useCallback, useEffect, useRef, useState } from 'react';

import { getYachiyoTask, listYachiyoTasks } from '../api';
import { yachiyoTaskCacheKeys } from '../taskSnapshots';
import type { AgentTaskSnapshot } from '../types';

const TASK_SNAPSHOT_REQUEST_TIMEOUT_MS = 15_000;

export function useYachiyoTaskSnapshots() {
  const [agentTaskSnapshotsById, setAgentTaskSnapshotsById] = useState<Record<string, AgentTaskSnapshot>>({});
  const agentTaskSnapshotsRef = useRef<Record<string, AgentTaskSnapshot>>({});
  const agentTaskFetchInFlightRef = useRef<Map<string, Promise<void>>>(new Map());
  const agentTaskFetchAbortControllerRef = useRef<Map<string, AbortController>>(new Map());
  const taskListAbortControllersRef = useRef<Set<AbortController>>(new Set());
  const mountedRef = useRef(true);

  useEffect(() => {
    mountedRef.current = true;
    return () => {
      mountedRef.current = false;
      taskListAbortControllersRef.current.forEach((controller) => controller.abort());
      agentTaskFetchAbortControllerRef.current.forEach((controller) => controller.abort());
    };
  }, []);

  const rememberYachiyoTasks = useCallback((tasks: Array<AgentTaskSnapshot | null | undefined>) => {
    if (!mountedRef.current) return;
    const snapshots = tasks.filter((task): task is AgentTaskSnapshot => Boolean(task?.task_id));
    if (!snapshots.length) return;
    const next = { ...agentTaskSnapshotsRef.current };
    let changed = false;
    snapshots.forEach((task) => {
      const keys = yachiyoTaskCacheKeys(task).filter(Boolean);
      const existing = newestTaskSnapshot(
        keys
          .map((key) => next[key])
          .filter((candidate) => candidate?.task_id === task.task_id),
      );
      if (existing && !shouldRememberTaskSnapshot(task, existing)) {
        keys.forEach((key) => {
          if (next[key]) return;
          next[key] = existing;
          changed = true;
        });
        return;
      }
      keys.forEach((key) => {
        if (!key) return;
        if (next[key] === task) return;
        next[key] = task;
        changed = true;
      });
    });
    if (!changed) return;
    agentTaskSnapshotsRef.current = next;
    setAgentTaskSnapshotsById(next);
  }, []);

  const refreshYachiyoTasksForSession = useCallback(async (sessionId: string) => {
    const cleanSessionId = sessionId.trim();
    if (!cleanSessionId) return;
    const requestController = new AbortController();
    taskListAbortControllersRef.current.add(requestController);
    try {
      const tasks = await listYachiyoTasks(cleanSessionId, {
        signal: requestController.signal,
        timeoutMs: TASK_SNAPSHOT_REQUEST_TIMEOUT_MS,
      });
      rememberYachiyoTasks(tasks);
    } catch {
      // The Chat surface keeps using legacy messages if the new facade is unavailable.
    } finally {
      taskListAbortControllersRef.current.delete(requestController);
    }
  }, [rememberYachiyoTasks]);

  const refreshYachiyoTaskById = useCallback(async (taskId: string) => {
    const cleanTaskId = taskId.trim();
    if (!cleanTaskId) return;
    const current = agentTaskFetchInFlightRef.current.get(cleanTaskId);
    if (current) return current;
    const requestController = new AbortController();
    agentTaskFetchAbortControllerRef.current.set(cleanTaskId, requestController);
    const request = (async () => {
      try {
        const task = await getYachiyoTask(cleanTaskId, {
          signal: requestController.signal,
          timeoutMs: TASK_SNAPSHOT_REQUEST_TIMEOUT_MS,
        });
        rememberYachiyoTasks([task]);
      } catch {
        // Message metadata still provides a fallback task card for legacy runs.
      }
    })();
    const tracked = request.finally(() => {
      if (agentTaskFetchInFlightRef.current.get(cleanTaskId) === tracked) {
        agentTaskFetchInFlightRef.current.delete(cleanTaskId);
        agentTaskFetchAbortControllerRef.current.delete(cleanTaskId);
      }
    });
    agentTaskFetchInFlightRef.current.set(cleanTaskId, tracked);
    return tracked;
  }, [rememberYachiyoTasks]);

  const refreshYachiyoTaskSnapshotsForRunIds = useCallback((runIds: unknown[]) => {
    uniqueStrings(runIds)
      .filter((runId) => !agentTaskSnapshotsRef.current[runId])
      .slice(-8)
      .forEach((runId) => {
        void refreshYachiyoTaskById(runId);
      });
  }, [refreshYachiyoTaskById]);

  return {
    agentTaskSnapshotsById,
    rememberYachiyoTasks,
    refreshYachiyoTaskById,
    refreshYachiyoTasksForSession,
    refreshYachiyoTaskSnapshotsForRunIds,
  };
}

function uniqueStrings(values: unknown[]): string[] {
  const seen = new Set<string>();
  const result: string[] = [];
  values.forEach((value) => {
    const text = String(value || '').trim();
    if (!text || seen.has(text)) return;
    seen.add(text);
    result.push(text);
  });
  return result;
}

function newestTaskSnapshot(
  snapshots: Array<AgentTaskSnapshot | undefined>,
): AgentTaskSnapshot | undefined {
  return snapshots.reduce<AgentTaskSnapshot | undefined>((newest, candidate) => {
    if (!candidate) return newest;
    if (!newest || shouldRememberTaskSnapshot(candidate, newest)) return candidate;
    return newest;
  }, undefined);
}

function shouldRememberTaskSnapshot(
  incoming: AgentTaskSnapshot,
  existing: AgentTaskSnapshot,
): boolean {
  if (incoming === existing) return false;
  const incomingUpdatedAt = taskSnapshotUpdatedAt(incoming);
  const existingUpdatedAt = taskSnapshotUpdatedAt(existing);
  if (incomingUpdatedAt !== null && existingUpdatedAt !== null) {
    if (incomingUpdatedAt < existingUpdatedAt) return false;
    if (incomingUpdatedAt > existingUpdatedAt) return true;
  } else if (incomingUpdatedAt === null && existingUpdatedAt !== null) {
    return false;
  } else if (incomingUpdatedAt !== null) {
    return true;
  }
  if (isTerminalTaskStatus(existing.status) && !isTerminalTaskStatus(incoming.status)) return false;
  return true;
}

function taskSnapshotUpdatedAt(task: AgentTaskSnapshot): number | null {
  const timestamp = Date.parse(String(task.updated_at || task.created_at || ''));
  return Number.isFinite(timestamp) ? timestamp : null;
}

function isTerminalTaskStatus(status: unknown): boolean {
  return ['cancelled', 'completed', 'failed', 'rejected'].includes(
    String(status || '').trim().toLowerCase(),
  );
}
