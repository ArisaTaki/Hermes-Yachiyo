import { useCallback, useRef, useState } from 'react';

import { getYachiyoTask, listYachiyoTasks } from '../api';
import { yachiyoTaskCacheKeys } from '../taskSnapshots';
import type { AgentTaskSnapshot } from '../types';

export function useYachiyoTaskSnapshots() {
  const [agentTaskSnapshotsById, setAgentTaskSnapshotsById] = useState<Record<string, AgentTaskSnapshot>>({});
  const agentTaskSnapshotsRef = useRef<Record<string, AgentTaskSnapshot>>({});
  const agentTaskFetchInFlightRef = useRef<Set<string>>(new Set());

  const rememberYachiyoTasks = useCallback((tasks: Array<AgentTaskSnapshot | null | undefined>) => {
    const snapshots = tasks.filter((task): task is AgentTaskSnapshot => Boolean(task?.task_id));
    if (!snapshots.length) return;
    const next = { ...agentTaskSnapshotsRef.current };
    let changed = false;
    snapshots.forEach((task) => {
      yachiyoTaskCacheKeys(task).forEach((key) => {
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
    try {
      rememberYachiyoTasks(await listYachiyoTasks(cleanSessionId));
    } catch {
      // The Chat surface keeps using legacy messages if the new facade is unavailable.
    }
  }, [rememberYachiyoTasks]);

  const refreshYachiyoTaskById = useCallback(async (taskId: string) => {
    const cleanTaskId = taskId.trim();
    if (!cleanTaskId || agentTaskSnapshotsRef.current[cleanTaskId]) return;
    if (agentTaskFetchInFlightRef.current.has(cleanTaskId)) return;
    agentTaskFetchInFlightRef.current.add(cleanTaskId);
    try {
      rememberYachiyoTasks([await getYachiyoTask(cleanTaskId)]);
    } catch {
      // Message metadata still provides a fallback task card for legacy runs.
    } finally {
      agentTaskFetchInFlightRef.current.delete(cleanTaskId);
    }
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
