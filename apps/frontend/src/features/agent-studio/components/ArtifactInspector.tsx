import type { RunSpec } from '../types';
import { RuntimeArtifactPreview } from '../../runtime-shared/components/RuntimeArtifactPreview';

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
      <div className="run-detail-fold-body run-artifacts" data-testid="agent-run-detail-artifact-list">
        {selectedRunArtifacts.map((artifact, index) => {
          const path = String(artifact.path || '');
          const artifactKind = String(artifact.kind || artifact.artifact_kind || 'artifact').trim();
          const sourceRunId = String(artifact.source_run_id || artifact.run_id || selectedRun.run_id);
          const sourceLabel = String(artifact.source_runnable_name || artifact.workflow_step_label || '').trim();
          const artifactId = String(artifact.artifact_id || `${sourceRunId}:${path || artifactKind}:${index}`);
          const artifactTitle = sourceLabel ? `${sourceLabel} / ${path || 'artifact'}` : path || 'artifact';
          return (
            <button
              type="button"
              data-artifact-kind={artifactKind}
              data-artifact-path={path}
              data-artifact-source-label={sourceLabel}
              data-artifact-source-run-id={sourceRunId}
              data-testid="agent-run-detail-artifact"
              disabled={!path}
              key={`${path}-${index}`}
              onClick={() => path ? void onOpenArtifact(sourceRunId, path) : undefined}
            >
              <RuntimeArtifactPreview
                artifact={{
                  artifact_id: artifactId,
                  kind: artifactKind,
                  path,
                  title: artifactTitle,
                }}
                className="studio-runtime-artifact"
                testId="agent-run-detail-artifact-preview-card"
              />
            </button>
          );
        })}
        {!selectedRunArtifacts.length ? <span>No artifacts</span> : null}
      </div>
      {artifactPreview ? (
        <div className="run-detail-fold-body artifact-preview" data-testid="agent-run-detail-artifact-preview">
          <strong>{artifactPreview.path}{artifactPreview.truncated ? ' · truncated' : ''}</strong>
          <pre>{artifactPreview.content}</pre>
        </div>
      ) : null}
    </details>
  );
}
