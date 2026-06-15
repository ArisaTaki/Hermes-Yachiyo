import { RuntimeArtifactPreview } from '../../runtime-shared/components/RuntimeArtifactPreview';
import type { ArtifactSnapshot } from '../types';

export function ArtifactPreview({ artifact }: { artifact: ArtifactSnapshot }) {
  return (
    <RuntimeArtifactPreview
      artifact={artifact}
      className="yachiyo-task-artifact"
      testId="yachiyo-task-artifact-preview"
      variant="compact"
    />
  );
}
