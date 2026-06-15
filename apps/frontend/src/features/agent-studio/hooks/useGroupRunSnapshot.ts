import { useEffect, useMemo, useState } from 'react';

import { getYachiyoGroupRun } from '../../yachiyo-studio/api';
import type { GroupRunSnapshot } from '../../yachiyo-studio/types';

export function useGroupRunSnapshot(groupRunId: string, refreshKey = '') {
  const [groupRunById, setGroupRunById] = useState<Record<string, GroupRunSnapshot>>({});
  const selectedGroupRunSnapshot = useMemo(
    () => groupRunId ? groupRunById[groupRunId] || null : null,
    [groupRunById, groupRunId],
  );

  useEffect(() => {
    if (!groupRunId) return;
    let disposed = false;
    getYachiyoGroupRun(groupRunId)
      .then((snapshot) => {
        if (disposed) return;
        setGroupRunById((current) => ({
          ...current,
          [groupRunId]: snapshot,
        }));
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [groupRunId, refreshKey]);

  return {
    groupRunById,
    selectedGroupRunSnapshot,
  };
}
