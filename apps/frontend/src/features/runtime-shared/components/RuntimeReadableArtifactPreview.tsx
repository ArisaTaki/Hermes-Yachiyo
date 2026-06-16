import { useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import {
  RuntimeArtifactPreview,
  type RuntimeArtifactSnapshot,
  type RuntimeArtifactVariant,
} from './RuntimeArtifactPreview';

export type RuntimeReadableArtifactContent = {
  content?: string;
  mime_type?: string | null;
  truncated?: boolean;
};

type RuntimeReadableArtifactPreviewProps = {
  artifact: RuntimeArtifactSnapshot;
  busyLabel?: string;
  className?: string;
  contentClassName?: string;
  contentTestId?: string;
  emptyContentLabel?: string;
  errorClassName?: string;
  errorFallback?: string;
  errorTestId?: string;
  previewActionClassName?: string;
  previewActionTestId?: string;
  previewClassName?: string;
  previewTestId?: string;
  previewVariant?: RuntimeArtifactVariant;
  readArtifact?: (
    path: string,
    artifact: RuntimeArtifactSnapshot,
  ) => Promise<RuntimeReadableArtifactContent>;
  shellTestId?: string;
  statusClassName?: string;
  statusTestId?: string;
  triggerClassName?: string;
};

export function RuntimeReadableArtifactPreview({
  artifact,
  busyLabel = '读取 artifact...',
  className = 'runtime-readable-artifact',
  contentClassName = 'runtime-readable-artifact-content',
  contentTestId = 'runtime-readable-artifact-content',
  emptyContentLabel = '(empty artifact)',
  errorClassName = 'runtime-readable-artifact-status error',
  errorFallback = '读取 artifact 失败',
  errorTestId = 'runtime-readable-artifact-error',
  previewActionClassName = 'runtime-readable-artifact-action',
  previewActionTestId = 'runtime-readable-artifact-action',
  previewClassName = 'runtime-artifact-preview',
  previewTestId = 'runtime-artifact-preview',
  previewVariant = 'compact',
  readArtifact,
  shellTestId = 'runtime-readable-artifact-shell',
  statusClassName = 'runtime-readable-artifact-status',
  statusTestId = 'runtime-readable-artifact-loading',
  triggerClassName = 'runtime-readable-artifact-button',
}: RuntimeReadableArtifactPreviewProps) {
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState('');
  const [preview, setPreview] = useState<RuntimeReadableArtifactContent | null>(null);
  const path = String(artifact.path || '').trim();
  const canReadArtifact = Boolean(readArtifact && path);

  if (!canReadArtifact) {
    return (
      <RuntimeArtifactPreview
        artifact={artifact}
        className={previewClassName}
        testId={previewTestId}
        variant={previewVariant}
      />
    );
  }

  async function togglePreview() {
    if (!readArtifact || !path) return;
    if (preview) {
      setPreview(null);
      setError('');
      return;
    }
    setBusy(true);
    setError('');
    try {
      setPreview(await readArtifact(path, artifact));
    } catch (err) {
      setError(err instanceof Error ? err.message : errorFallback);
    } finally {
      setBusy(false);
    }
  }

  const label = artifact.title || path || artifact.kind || 'Artifact';
  return (
    <div
      className={className}
      data-artifact-id={artifact.artifact_id}
      data-artifact-path={path}
      data-testid={shellTestId}
    >
      <button
        type="button"
        aria-expanded={Boolean(preview)}
        className={triggerClassName}
        disabled={busy}
        onClick={() => void togglePreview()}
        title={path || label}
      >
        <RuntimeArtifactPreview
          actions={<UiIcon name={preview ? 'close' : 'paperclip'} />}
          actionsClassName={previewActionClassName}
          actionsElement="span"
          actionsTestId={previewActionTestId}
          artifact={artifact}
          as="span"
          className={previewClassName}
          testId={previewTestId}
          variant={previewVariant}
        />
      </button>
      {busy ? (
        <p className={statusClassName} data-testid={statusTestId}>
          {busyLabel}
        </p>
      ) : null}
      {error ? (
        <p className={errorClassName} data-testid={errorTestId}>
          {error}
        </p>
      ) : null}
      {preview ? (
        <pre className={contentClassName} data-testid={contentTestId}>
          {preview.content || emptyContentLabel}
        </pre>
      ) : null}
    </div>
  );
}
