import { useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { RuntimeArtifactPreview } from '../../runtime-shared/components/RuntimeArtifactPreview';
import { readYachiyoTaskArtifact } from '../api';
import type { ArtifactContentSnapshot, ArtifactSnapshot } from '../types';

export function ArtifactPreview({
  artifact,
  taskId = '',
}: {
  artifact: ArtifactSnapshot;
  taskId?: string;
}) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<ArtifactContentSnapshot | null>(null);
  const path = String(artifact.path || '').trim();
  const canReadArtifact = Boolean(taskId && path);

  if (!canReadArtifact) {
    return (
      <RuntimeArtifactPreview
        artifact={artifact}
        className="yachiyo-task-artifact"
        testId="yachiyo-task-artifact-preview"
        variant="compact"
      />
    );
  }

  async function togglePreview() {
    if (preview) {
      setPreview(null);
      setError('');
      return;
    }
    setBusy(true);
    setError('');
    try {
      setPreview(await readYachiyoTaskArtifact(taskId, path));
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 artifact 失败');
    } finally {
      setBusy(false);
    }
  }

  const label = artifact.title || path || artifact.kind || 'Artifact';
  return (
    <div
      className="yachiyo-task-artifact-shell"
      data-artifact-id={artifact.artifact_id}
      data-artifact-path={path}
      data-testid="yachiyo-task-artifact-shell"
    >
      <button
        type="button"
        aria-expanded={Boolean(preview)}
        className="yachiyo-task-artifact-button"
        disabled={busy}
        onClick={() => void togglePreview()}
        title={path || label}
      >
        <RuntimeArtifactPreview
          actions={<UiIcon name={preview ? 'close' : 'paperclip'} />}
          actionsClassName="yachiyo-task-artifact-action"
          actionsElement="span"
          actionsTestId="yachiyo-task-artifact-action"
          artifact={artifact}
          as="span"
          className="yachiyo-task-artifact"
          testId="yachiyo-task-artifact-preview"
          variant="compact"
        />
      </button>
      {busy ? (
        <p className="yachiyo-task-artifact-status" data-testid="yachiyo-task-artifact-loading">
          读取 artifact...
        </p>
      ) : null}
      {error ? (
        <p className="yachiyo-task-artifact-status error" data-testid="yachiyo-task-artifact-error">
          {error}
        </p>
      ) : null}
      {preview ? (
        <pre className="yachiyo-task-artifact-content" data-testid="yachiyo-task-artifact-content">
          {preview.content || '(empty artifact)'}
        </pre>
      ) : null}
    </div>
  );
}
