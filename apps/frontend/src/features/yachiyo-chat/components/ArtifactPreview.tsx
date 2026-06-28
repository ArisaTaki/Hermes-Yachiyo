import {
  RuntimeReadableArtifactPreview,
  type RuntimeImageArtifactPointSelection,
  type RuntimeImageArtifactSelectedPoint,
} from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import { readYachiyoChatRunArtifact, readYachiyoTaskArtifact } from '../api';
import { yachiyoTaskArtifactReadTarget } from '../taskSnapshots';
import type { ArtifactSnapshot } from '../types';

export function ArtifactPreview({
  artifact,
  enableImagePointSelection = false,
  onSelectImagePoint,
  selectedImagePoint,
  taskId = '',
}: {
  artifact: ArtifactSnapshot;
  enableImagePointSelection?: boolean;
  onSelectImagePoint?: (selection: RuntimeImageArtifactPointSelection) => void;
  selectedImagePoint?: RuntimeImageArtifactSelectedPoint | null;
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
      imagePointLabel="点击截图补齐坐标"
      onSelectImagePoint={enableImagePointSelection ? onSelectImagePoint : undefined}
      readArtifact={
        canReadRunArtifact
          ? (artifactPath) => readYachiyoChatRunArtifact(artifactTarget.runId, artifactPath)
          : canReadTaskArtifact
            ? (artifactPath) => readYachiyoTaskArtifact(artifactTarget.taskId, artifactPath)
            : undefined
      }
      selectedImagePoint={enableImagePointSelection ? selectedImagePoint : null}
      shellTestId="yachiyo-task-artifact-shell"
      statusClassName="yachiyo-task-artifact-status"
      statusTestId="yachiyo-task-artifact-loading"
      triggerClassName="yachiyo-task-artifact-button"
    />
  );
}
