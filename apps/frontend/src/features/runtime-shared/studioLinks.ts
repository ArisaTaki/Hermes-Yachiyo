export function studioRunUrl(runId?: string | null): string | null {
  const cleanRunId = String(runId || '').trim();
  if (!cleanRunId) return null;
  return `#/agents?run_id=${encodeURIComponent(cleanRunId)}`;
}

export function runIdFromStudioUrl(value?: string | null): string {
  const match = String(value || '').match(/[?&](?:run|run_id)=([^&#]+)/);
  return match ? decodeURIComponent(match[1]) : '';
}
