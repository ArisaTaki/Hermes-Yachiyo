import { navigateTo } from '../../lib/view';
import { groupRunIdFromStudioUrl, runIdFromStudioUrl } from '../runtime-shared/studioLinks';

export function openYachiyoStudioRun(runId: string | undefined, studioUrl = '') {
  const clean = runIdFromStudioUrl(studioUrl) || String(runId || '').trim();
  if (!clean) return false;
  const groupRunId = groupRunIdFromStudioUrl(studioUrl);
  navigateTo('agents', {
    run: clean,
    ...(groupRunId ? { group_run: groupRunId } : {}),
  }, ['tab', 'target', 'goal', 'group_run', 'group_run_id', 'run_group_id']);
  return true;
}

export function openYachiyoWorkflowStudio(runnableId = '', suggestedGoal = '') {
  const cleanRunnableId = String(runnableId || '').trim();
  if (cleanRunnableId) {
    navigateTo('agents', {
      tab: 'runs',
      target: cleanRunnableId,
      goal: String(suggestedGoal || '').trim(),
    }, ['run']);
    return;
  }
  navigateTo('agents', { tab: 'workflows' }, ['run', 'target', 'goal']);
}
