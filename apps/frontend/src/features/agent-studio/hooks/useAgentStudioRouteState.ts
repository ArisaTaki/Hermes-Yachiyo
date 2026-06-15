import { useEffect, useState } from 'react';

import { currentParam } from '../../../lib/view';
import { normalizeStudioTab, type StudioTab } from '../studioTabs';

export function useAgentStudioRouteState() {
  const routeRunId = (currentParam('run') || currentParam('run_id')).trim();
  const routeGroupRunId = (currentParam('group_run') || currentParam('group_run_id') || currentParam('run_group_id')).trim();
  const routeRunTarget = currentParam('target').trim();
  const routeRunGoal = currentParam('goal').trim();
  const routeTab = normalizeStudioTab(currentParam('tab'));
  const [tab, setTab] = useState<StudioTab>(() => routeRunId || routeRunTarget ? 'runs' : routeTab);
  const [runTarget, setRunTarget] = useState(() => routeRunTarget);
  const [runGoal, setRunGoal] = useState(() => routeRunGoal);
  const [selectedRunId, setSelectedRunId] = useState(() => routeRunId);
  const [selectedRouteGroupRunId, setSelectedRouteGroupRunId] = useState(() => routeGroupRunId);

  useEffect(() => {
    const nextTab = routeRunId || routeRunTarget ? 'runs' : routeTab;
    setTab((current) => current === nextTab ? current : nextTab);
    setSelectedRouteGroupRunId((current) => current === routeGroupRunId ? current : routeGroupRunId);
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
  }, [routeGroupRunId, routeRunGoal, routeRunId, routeRunTarget, routeTab]);

  return {
    runGoal,
    runTarget,
    selectedRouteGroupRunId,
    selectedRunId,
    setRunGoal,
    setRunTarget,
    setSelectedRunId,
    setTab,
    tab,
  };
}
