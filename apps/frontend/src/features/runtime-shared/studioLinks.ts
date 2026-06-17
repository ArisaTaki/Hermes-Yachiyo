import { routePath } from '../../lib/view';

export type StudioRunLinkOptions = {
  groupRunId?: string | null;
  studioUrl?: string | null;
};

export const studioRunClearParams = ['tab', 'target', 'goal', 'group_run', 'group_run_id', 'run_group_id'];

export const workflowStudioClearParams = ['run', 'target', 'goal'];

export const studioTabClearParams = ['run', 'tab', 'target', 'goal'];

export function studioRunUrl(runId?: string | null, options: StudioRunLinkOptions = {}): string | null {
  const params = studioRunRouteParams(runId, options);
  return params ? routePath('agents', params) : null;
}

export function studioRunRouteParams(
  runId?: string | null,
  options: StudioRunLinkOptions = {},
): Record<string, string> | null {
  const cleanRunId = runIdFromStudioUrl(options.studioUrl) || String(runId || '').trim();
  if (!cleanRunId) return null;
  const cleanGroupRunId = groupRunIdFromStudioUrl(options.studioUrl) || String(options.groupRunId || '').trim();
  return {
    run: cleanRunId,
    ...(cleanGroupRunId ? { group_run: cleanGroupRunId } : {}),
  };
}

export function workflowStudioRouteParams(runnableId = '', suggestedGoal = ''): Record<string, string> {
  const cleanRunnableId = String(runnableId || '').trim();
  if (!cleanRunnableId) return { tab: 'workflows' };
  return {
    tab: 'runs',
    target: cleanRunnableId,
    goal: String(suggestedGoal || '').trim(),
  };
}

export function studioTabRouteParams(tab = 'agents'): Record<string, string> {
  const cleanTab = String(tab || '').trim();
  return !cleanTab || cleanTab === 'agents' ? {} : { tab: cleanTab };
}

export function runIdFromStudioUrl(value?: string | null): string {
  const url = String(value || '').trim();
  const queryMatch = url.match(/[?&](?:run|run_id)=([^&#]+)/);
  if (queryMatch) return decodeURIComponent(queryMatch[1]);
  const pathMatch = url.match(/^#\/agents\/([^?&#]+)/);
  return pathMatch ? decodeURIComponent(pathMatch[1]) : '';
}

export function groupRunIdFromStudioUrl(value?: string | null): string {
  const url = String(value || '').trim();
  const queryMatch = url.match(/[?&](?:group_run|group_run_id|run_group_id)=([^&#]+)/);
  return queryMatch ? decodeURIComponent(queryMatch[1]) : '';
}
