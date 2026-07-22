import type { RunSpec } from '../types';
import {
  RuntimeArtifactList,
  runtimeArtifactListItem,
  type RuntimeArtifactListItem,
} from '../../runtime-shared/components/RuntimeArtifactList';
import {
  RuntimeReadableArtifactContentPreview,
  type RuntimeImageArtifactPointSelection,
} from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import type {
  RunArtifactPreview,
  RunRecoveryCoordinate,
  RunRecoveryScreenPointContract,
} from './runDetailTypes';

type ArtifactInspectorProps = {
  artifactPreview: RunArtifactPreview | null;
  onOpenArtifact: (run: RunSpec | string, path: string) => Promise<void> | void;
  onSelectImagePoint?: (selection: RuntimeImageArtifactPointSelection) => void;
  recoveryScreenPointContract?: RunRecoveryScreenPointContract | null;
  selectedRun: RunSpec;
  selectedRunArtifacts: Array<Record<string, unknown>>;
  selectedImagePoint?: RunRecoveryCoordinate | null;
  sourceLabel?: string;
};

export function ArtifactInspector({
  artifactPreview,
  onOpenArtifact,
  onSelectImagePoint,
  recoveryScreenPointContract = null,
  selectedRun,
  selectedRunArtifacts,
  selectedImagePoint = null,
  sourceLabel = '上下文、工具产物和可预览文件',
}: ArtifactInspectorProps) {
  const previewArtifact = artifactPreview
    ? artifactForPreview(artifactPreview, selectedRunArtifacts, selectedRun.run_id)
    : null;
  const enableImagePointSelection = Boolean(
    previewArtifact
    && artifactMatchesRecoveryScreenPoint(previewArtifact, recoveryScreenPointContract),
  );
  return (
    <details className="run-detail-block run-detail-fold" data-testid="agent-run-detail-artifacts" open>
      <summary className="run-detail-section-head">
        <div>
          <h4>Artifacts · {selectedRunArtifacts.length}</h4>
          <span>{sourceLabel}</span>
        </div>
      </summary>
      <RuntimeArtifactList
        artifacts={selectedRunArtifacts}
        className="run-detail-fold-body run-artifacts"
        emptyLabel="暂无 Artifacts"
        fallbackRunId={selectedRun.run_id}
        itemTestId="agent-run-detail-artifact"
        onOpenArtifact={onOpenArtifact}
        previewClassName="studio-runtime-artifact"
        previewTestId="agent-run-detail-artifact-preview-card"
        previewVariant="full"
        testId="agent-run-detail-artifact-list"
      />
      {artifactPreview ? (
        <div
          className="run-detail-fold-body artifact-preview"
          data-coordinate-pick-enabled={enableImagePointSelection ? 'true' : 'false'}
          data-testid="agent-run-detail-artifact-preview"
        >
          <strong>{artifactPreview.path}{artifactPreview.truncated ? ' · truncated' : ''}</strong>
          {previewArtifact ? (
            <RuntimeReadableArtifactContentPreview
              artifact={previewArtifact}
              className="agent-run-detail-artifact-preview-content"
              contentTestId="agent-run-detail-artifact-preview-content"
              imagePointLabel="点击截图补齐重试坐标"
              onSelectImagePoint={enableImagePointSelection ? onSelectImagePoint : undefined}
              preview={{
                content: artifactPreview.content,
                mime_type: artifactPreview.mime_type,
                truncated: artifactPreview.truncated,
              }}
              selectedImagePoint={enableImagePointSelection ? selectedImagePoint : null}
            />
          ) : (
            <pre>{artifactPreview.content}</pre>
          )}
        </div>
      ) : null}
    </details>
  );
}

function artifactForPreview(
  preview: RunArtifactPreview,
  artifacts: Array<Record<string, unknown>>,
  fallbackRunId: string,
): RuntimeArtifactListItem | null {
  const runId = String(preview.run_id || fallbackRunId || '').trim();
  const path = String(preview.path || '').trim();
  if (!path) return null;
  const items = artifacts.map((artifact, index) => runtimeArtifactListItem(artifact, index, fallbackRunId));
  const matched = items.find((item) => (
    item.path === path
    && (!runId || item.source_run_id === runId || item.run_id === runId)
  )) || items.find((item) => item.path === path);
  if (matched) return matched;
  return runtimeArtifactListItem({
    artifact_id: `${runId}:${path}`,
    kind: preview.mime_type?.startsWith('image/') ? 'image' : 'artifact',
    mime_type: preview.mime_type,
    path,
    run_id: runId,
    source_run_id: runId,
    title: path,
  }, 0, fallbackRunId);
}

function artifactMatchesRecoveryScreenPoint(
  artifact: RuntimeArtifactListItem,
  contract: RunRecoveryScreenPointContract | null,
): boolean {
  if (!contract) return false;
  const kind = String(artifact.kind || '').trim();
  const mimeType = String(artifact.mime_type || '').trim();
  const path = String(artifact.path || '').trim();
  const sourceTool = String(artifact.source_tool || '').trim();
  if (sourceTool && contract.artifactTool && sourceTool !== contract.artifactTool) return false;
  if (kind && contract.artifactKind && kind !== contract.artifactKind) return false;
  return kind === 'image'
    || mimeType.startsWith('image/')
    || /\.(?:png|jpe?g|webp|gif)$/i.test(path);
}
