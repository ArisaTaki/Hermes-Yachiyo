import { readYachiyoRunArtifact } from '../../yachiyo-studio/api';
import type { RunArtifactPreview } from '../components/runDetailTypes';

type UseRunArtifactActionsOptions = {
  setArtifactPreview: (preview: RunArtifactPreview | null) => void;
  setError: (message: string) => void;
  setStatus: (message: string) => void;
};

export function useRunArtifactActions({
  setArtifactPreview,
  setError,
  setStatus,
}: UseRunArtifactActionsOptions) {
  async function openArtifact(run: { run_id?: string } | string, path: string) {
    const runId = typeof run === 'string' ? run : run.run_id;
    if (!runId) {
      setError('请选择要读取 Artifact 的 Run');
      return;
    }
    setStatus('读取 artifact...');
    setError('');
    try {
      const payload = await readYachiyoRunArtifact(runId, path);
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
