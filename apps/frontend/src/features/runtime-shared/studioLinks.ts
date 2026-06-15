import { routePath } from '../../lib/view';

export type StudioRunLinkOptions = {
  groupRunId?: string | null;
};

export function studioRunUrl(runId?: string | null, options: StudioRunLinkOptions = {}): string | null {
  const cleanRunId = String(runId || '').trim();
  if (!cleanRunId) return null;
  const cleanGroupRunId = String(options.groupRunId || '').trim();
  return routePath('agents', {
    run: cleanRunId,
    ...(cleanGroupRunId ? { group_run: cleanGroupRunId } : {}),
  });
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
