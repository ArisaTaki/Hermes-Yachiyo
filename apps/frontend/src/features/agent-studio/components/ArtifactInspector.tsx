import type { RunSpec } from '../types';
import { RuntimeArtifactList } from '../../runtime-shared/components/RuntimeArtifactList';

type ArtifactPreview = {
  path: string;
  content: string;
  truncated?: boolean;
};

type ArtifactInspectorProps = {
  artifactPreview: ArtifactPreview | null;
  onOpenArtifact: (run: RunSpec | string, path: string) => Promise<void> | void;
  selectedRun: RunSpec;
  selectedRunArtifacts: Array<Record<string, unknown>>;
};

export function ArtifactInspector({
  artifactPreview,
  onOpenArtifact,
  selectedRun,
  selectedRunArtifacts,
}: ArtifactInspectorProps) {
  return (
    <details className="run-detail-block run-detail-fold" data-testid="agent-run-detail-artifacts" open>
      <summary className="run-detail-section-head">
        <div>
          <h4>Artifacts · {selectedRunArtifacts.length}</h4>
          <span>上下文、工具产物和可预览文件</span>
        </div>
      </summary>
      <RuntimeArtifactList
        artifacts={selectedRunArtifacts}
        className="run-detail-fold-body run-artifacts"
        emptyLabel="No artifacts"
        fallbackRunId={selectedRun.run_id}
        itemTestId="agent-run-detail-artifact"
        onOpenArtifact={onOpenArtifact}
        previewClassName="studio-runtime-artifact"
        previewTestId="agent-run-detail-artifact-preview-card"
        previewVariant="full"
        testId="agent-run-detail-artifact-list"
      />
      {artifactPreview ? (
        <div className="run-detail-fold-body artifact-preview" data-testid="agent-run-detail-artifact-preview">
          <strong>{artifactPreview.path}{artifactPreview.truncated ? ' · truncated' : ''}</strong>
          <pre>{artifactPreview.content}</pre>
        </div>
      ) : null}
    </details>
  );
}
