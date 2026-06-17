import { navigateTo } from '../../lib/view';
import {
  studioRunClearParams,
  studioRunRouteParams,
  workflowStudioClearParams,
  workflowStudioRouteParams,
} from '../runtime-shared/studioLinks';

export function openYachiyoStudioRun(runId: string | undefined, studioUrl = '') {
  const params = studioRunRouteParams(runId, { studioUrl });
  if (!params) return false;
  navigateTo('agents', params, studioRunClearParams);
  return true;
}

export function openYachiyoWorkflowStudio(runnableId = '', suggestedGoal = '') {
  navigateTo('agents', workflowStudioRouteParams(runnableId, suggestedGoal), workflowStudioClearParams);
}
