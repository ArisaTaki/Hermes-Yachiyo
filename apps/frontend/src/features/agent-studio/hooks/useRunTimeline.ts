import { useEffect, useMemo, useState } from 'react';

import { getYachiyoRunTimeline } from '../../yachiyo-studio/api';
import type { RunTimelineSnapshot } from '../../yachiyo-studio/types';

export function useRunTimeline(runId: string, refreshKey: string) {
  const [publicRunTimelineById, setPublicRunTimelineById] = useState<Record<string, RunTimelineSnapshot>>({});
  const selectedPublicRunTimeline = useMemo(
    () => runId ? publicRunTimelineById[runId] || null : null,
    [publicRunTimelineById, runId],
  );

  useEffect(() => {
    if (!runId) return;
    let disposed = false;
    getYachiyoRunTimeline(runId)
      .then((timeline) => {
        if (disposed) return;
        setPublicRunTimelineById((current) => ({
          ...current,
          [runId]: timeline,
        }));
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [runId, refreshKey]);

  return {
    publicRunTimelineById,
    selectedPublicRunTimeline,
  };
}
