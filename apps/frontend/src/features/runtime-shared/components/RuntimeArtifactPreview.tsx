import type { ArtifactSnapshot } from '../types';

export type RuntimeArtifactSnapshot = Pick<
  ArtifactSnapshot,
  'artifact_id' | 'kind' | 'path' | 'title'
>;

export type RuntimeArtifactVariant = 'compact' | 'full';

export function RuntimeArtifactPreview({
  artifact,
  className = 'yachiyo-task-artifact',
  testId = 'runtime-artifact-preview',
  variant = 'compact',
}: {
  artifact: RuntimeArtifactSnapshot;
  className?: string;
  testId?: string;
  variant?: RuntimeArtifactVariant;
}) {
  const label = artifact.title || artifact.path || artifact.kind || 'Artifact';
  return (
    <div
      className={className}
      data-artifact-id={artifact.artifact_id}
      data-artifact-kind={artifact.kind}
      data-artifact-path={artifact.path || ''}
      data-artifact-variant={variant}
      data-testid={testId}
      title={artifact.path || label}
    >
      <span>{artifact.kind || 'artifact'}</span>
      <strong>{label}</strong>
    </div>
  );
}
