import { useEffect, useState } from 'react';

import { currentParam } from '../../../lib/view';
import { normalizeStudioTab, type StudioTab } from '../studioTabs';

export function useAgentStudioRouteState() {
  const routeRunId = currentParam('run').trim();
  const routeRunTarget = currentParam('target').trim();
  const routeRunGoal = currentParam('goal').trim();
  const routeTab = normalizeStudioTab(currentParam('tab'));
  const [tab, setTab] = useState<StudioTab>(() => routeRunId || routeRunTarget ? 'runs' : routeTab);
  const [runTarget, setRunTarget] = useState(() => routeRunTarget);
  const [runGoal, setRunGoal] = useState(() => routeRunGoal);
  const [selectedRunId, setSelectedRunId] = useState(() => routeRunId);

  useEffect(() => {
    const nextTab = routeRunId || routeRunTarget ? 'runs' : routeTab;
    setTab((current) => current === nextTab ? current : nextTab);
    if (routeRunId) {
      setSelectedRunId((current) => current === routeRunId ? current : routeRunId);
    } else if (routeRunTarget) {
      setSelectedRunId('');
    } else if (routeTab === 'runs') {
      setSelectedRunId('');
    }
    if (routeRunTarget) {
      setRunTarget((current) => current === routeRunTarget ? current : routeRunTarget);
      setRunGoal((current) => current === routeRunGoal ? current : routeRunGoal);
    } else if (routeRunGoal) {
      setRunGoal((current) => current === routeRunGoal ? current : routeRunGoal);
    }
  }, [routeRunGoal, routeRunId, routeRunTarget, routeTab]);

  return {
    runGoal,
    runTarget,
    selectedRunId,
    setRunGoal,
    setRunTarget,
    setSelectedRunId,
    setTab,
    tab,
  };
}
