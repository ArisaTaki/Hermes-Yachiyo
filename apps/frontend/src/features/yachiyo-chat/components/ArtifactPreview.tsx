import { RuntimeReadableArtifactPreview } from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import { readYachiyoRunArtifact } from '../../yachiyo-studio/api';
import { readYachiyoTaskArtifact } from '../api';
import type { ArtifactSnapshot } from '../types';

export function ArtifactPreview({
  artifact,
  taskId = '',
}: {
  artifact: ArtifactSnapshot;
  taskId?: string;
}) {
  const path = String(artifact.path || '').trim();
  const sourceRunId = String(artifact.source_run_id || artifact.run_id || '').trim();
  const canReadRunArtifact = Boolean(sourceRunId && path);
  const canReadTaskArtifact = Boolean(taskId && path);
  return (
    <RuntimeReadableArtifactPreview
      artifact={artifact}
      className="yachiyo-task-artifact-shell"
      contentClassName="yachiyo-task-artifact-content"
      contentTestId="yachiyo-task-artifact-content"
      errorClassName="yachiyo-task-artifact-status error"
      errorTestId="yachiyo-task-artifact-error"
      previewActionClassName="yachiyo-task-artifact-action"
      previewActionTestId="yachiyo-task-artifact-action"
      previewClassName="yachiyo-task-artifact"
      previewTestId="yachiyo-task-artifact-preview"
      previewVariant="compact"
      readArtifact={
        canReadRunArtifact
          ? (artifactPath) => readYachiyoRunArtifact(sourceRunId, artifactPath)
          : canReadTaskArtifact
            ? (artifactPath) => readYachiyoTaskArtifact(taskId, artifactPath)
            : undefined
      }
      shellTestId="yachiyo-task-artifact-shell"
      statusClassName="yachiyo-task-artifact-status"
      statusTestId="yachiyo-task-artifact-loading"
      triggerClassName="yachiyo-task-artifact-button"
    />
  );
}
