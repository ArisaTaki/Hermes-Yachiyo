import { RuntimeReadableArtifactPreview } from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import { readYachiyoChatRunArtifact, readYachiyoTaskArtifact } from '../api';
import { yachiyoTaskArtifactReadTarget } from '../taskSnapshots';
import type { ArtifactSnapshot } from '../types';

export function ArtifactPreview({
  artifact,
  taskId = '',
}: {
  artifact: ArtifactSnapshot;
  taskId?: string;
}) {
  const artifactTarget = yachiyoTaskArtifactReadTarget(artifact, taskId);
  const canReadRunArtifact = Boolean(artifactTarget.runId && artifactTarget.path);
  const canReadTaskArtifact = Boolean(artifactTarget.taskId && artifactTarget.path);
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
          ? (artifactPath) => readYachiyoChatRunArtifact(artifactTarget.runId, artifactPath)
          : canReadTaskArtifact
            ? (artifactPath) => readYachiyoTaskArtifact(artifactTarget.taskId, artifactPath)
            : undefined
      }
      shellTestId="yachiyo-task-artifact-shell"
      statusClassName="yachiyo-task-artifact-status"
      statusTestId="yachiyo-task-artifact-loading"
      triggerClassName="yachiyo-task-artifact-button"
    />
  );
}
