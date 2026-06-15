import { routePath } from '../../lib/view';

export function studioRunUrl(runId?: string | null): string | null {
  const cleanRunId = String(runId || '').trim();
  if (!cleanRunId) return null;
  return routePath('agents', { run: cleanRunId });
}

export function runIdFromStudioUrl(value?: string | null): string {
  const url = String(value || '').trim();
  const queryMatch = url.match(/[?&](?:run|run_id)=([^&#]+)/);
  if (queryMatch) return decodeURIComponent(queryMatch[1]);
  const pathMatch = url.match(/^#\/agents\/([^?&#]+)/);
  return pathMatch ? decodeURIComponent(pathMatch[1]) : '';
}
