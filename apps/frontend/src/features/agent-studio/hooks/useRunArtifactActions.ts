import type { RunSpec } from '../../../lib/agents';
import { getRunArtifact } from '../../../lib/agents';

type ArtifactPreview = {
  path: string;
  content: string;
  truncated?: boolean;
};

type UseRunArtifactActionsOptions = {
  setArtifactPreview: (preview: ArtifactPreview | null) => void;
  setError: (message: string) => void;
  setStatus: (message: string) => void;
};

export function useRunArtifactActions({
  setArtifactPreview,
  setError,
  setStatus,
}: UseRunArtifactActionsOptions) {
  async function openArtifact(run: RunSpec | string, path: string) {
    const runId = typeof run === 'string' ? run : run.run_id;
    setStatus('读取 artifact...');
    setError('');
    try {
      const payload = await getRunArtifact(runId, path);
      setArtifactPreview({
        path: payload.path || path,
        content: payload.content || '',
        truncated: payload.truncated,
      });
      setStatus('Artifact 已读取');
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 artifact 失败');
    }
  }

  return {
    openArtifact,
  };
}
