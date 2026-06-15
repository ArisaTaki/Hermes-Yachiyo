import { useCallback, useRef } from 'react';

import type { RunSpec } from '../types';
import {
  normalizeRunStatus,
  runApprovalSignature,
} from '../utils/runs';

type ApprovedApprovalGuard = {
  signature: string;
  staleUntil: number;
};

const approvedApprovalStaleWindowMs = 6000;

export function useApprovedRunGuard() {
  const approvedApprovalGuardsRef = useRef<Map<string, ApprovedApprovalGuard>>(new Map());

  const rememberApprovedRun = useCallback((run: RunSpec | null | undefined) => {
    if (!run) return;
    approvedApprovalGuardsRef.current.set(run.run_id, {
      signature: runApprovalSignature(run),
      staleUntil: Date.now() + approvedApprovalStaleWindowMs,
    });
  }, []);

  const shouldAcceptRunUpdate = useCallback((run: RunSpec): boolean => {
    const guard = approvedApprovalGuardsRef.current.get(run.run_id);
    if (!guard) return true;
    if (normalizeRunStatus(run.status) !== 'approval_required') {
      approvedApprovalGuardsRef.current.delete(run.run_id);
      return true;
    }
    const signature = runApprovalSignature(run);
    if (guard.signature && signature === guard.signature) return false;
    if (!guard.signature && Date.now() < guard.staleUntil) return false;
    approvedApprovalGuardsRef.current.delete(run.run_id);
    return true;
  }, []);

  const acceptedRunUpdates = useCallback(
    (nextRuns: RunSpec[]): RunSpec[] => nextRuns.filter((run) => shouldAcceptRunUpdate(run)),
    [shouldAcceptRunUpdate],
  );

  return {
    acceptedRunUpdates,
    rememberApprovedRun,
  };
}
