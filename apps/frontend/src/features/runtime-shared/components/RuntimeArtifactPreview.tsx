export type RuntimeArtifactSnapshot = {
  artifact_id: string;
  title?: string | null;
  kind: string;
  path?: string | null;
};

export function RuntimeArtifactPreview({
  artifact,
  className = 'yachiyo-task-artifact',
  testId = 'runtime-artifact-preview',
}: {
  artifact: RuntimeArtifactSnapshot;
  className?: string;
  testId?: string;
}) {
  const label = artifact.title || artifact.path || artifact.kind || 'Artifact';
  return (
    <div
      className={className}
      data-artifact-id={artifact.artifact_id}
      data-artifact-kind={artifact.kind}
      data-artifact-path={artifact.path || ''}
      data-testid={testId}
      title={artifact.path || label}
    >
      <span>{artifact.kind || 'artifact'}</span>
      <strong>{label}</strong>
    </div>
  );
}
