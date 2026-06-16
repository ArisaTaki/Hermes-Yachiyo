import {
  RuntimeArtifactPreview,
  type RuntimeArtifactSnapshot,
  type RuntimeArtifactVariant,
} from './RuntimeArtifactPreview';

export type RuntimeArtifactSource = RuntimeArtifactSnapshot | Record<string, unknown>;

export type RuntimeArtifactListItem = RuntimeArtifactSnapshot & {
  group_id?: string | null;
  group_run_id?: string | null;
  run_id?: string | null;
  source_label?: string | null;
  source_runnable_id?: string | null;
  source_runnable_name?: string | null;
  source_run_id?: string | null;
  source_tool?: string | null;
  workflow_id?: string | null;
  workflow_node_id?: string | null;
  workflow_node_label?: string | null;
  workflow_run_id?: string | null;
};

type RuntimeArtifactListProps = {
  artifacts: RuntimeArtifactSource[];
  className: string;
  emptyLabel?: string;
  fallbackRunId?: string;
  itemTestId?: string;
  limit?: number;
  onOpenArtifact?: (runId: string, path: string) => Promise<void> | void;
  previewClassName?: string;
  previewTestId?: string;
  previewVariant?: RuntimeArtifactVariant;
  testId?: string;
};

export function RuntimeArtifactList({
  artifacts,
  className,
  emptyLabel,
  fallbackRunId = '',
  itemTestId,
  limit,
  onOpenArtifact,
  previewClassName,
  previewTestId,
  previewVariant = 'compact',
  testId,
}: RuntimeArtifactListProps) {
  const visibleArtifacts = artifacts.slice(0, limit ? Math.max(0, limit) : artifacts.length);
  return (
    <div className={className} data-testid={testId}>
      {visibleArtifacts.map((artifact, index) => {
        const item = runtimeArtifactListItem(artifact, index, fallbackRunId);
        const preview = (
          <RuntimeArtifactPreview
            artifact={item}
            className={previewClassName}
            testId={previewTestId}
            variant={previewVariant}
          />
        );
        if (!onOpenArtifact) {
          return <div data-artifact-source-run-id={item.source_run_id || ''} key={`${item.artifact_id}-${index}`}>{preview}</div>;
        }
        return (
          <button
            type="button"
            data-artifact-kind={item.kind}
            data-artifact-path={item.path || ''}
            data-artifact-source-label={item.source_label || ''}
            data-artifact-source-run-id={item.source_run_id || ''}
            data-testid={itemTestId}
            disabled={!item.path}
            key={`${item.artifact_id}-${index}`}
            onClick={() => item.path ? void onOpenArtifact(item.source_run_id || fallbackRunId, item.path) : undefined}
          >
            {preview}
          </button>
        );
      })}
      {!visibleArtifacts.length && emptyLabel ? <span>{emptyLabel}</span> : null}
    </div>
  );
}

export function runtimeArtifactListItem(
  artifact: RuntimeArtifactSource,
  index: number,
  fallbackRunId = '',
): RuntimeArtifactListItem {
  const path = artifactStringValue(artifact, 'path');
  const kind = artifactStringValue(artifact, 'kind') || artifactStringValue(artifact, 'artifact_kind') || 'artifact';
  const runId = artifactStringValue(artifact, 'run_id');
  const sourceRunId = artifactStringValue(artifact, 'source_run_id') || runId || fallbackRunId;
  const sourceRunnableId = artifactStringValue(artifact, 'source_runnable_id');
  const sourceRunnableName = artifactStringValue(artifact, 'source_runnable_name');
  const sourceTool = artifactStringValue(artifact, 'source_tool');
  const groupId = artifactStringValue(artifact, 'group_id');
  const groupRunId = artifactStringValue(artifact, 'group_run_id');
  const workflowId = artifactStringValue(artifact, 'workflow_id');
  const workflowRunId = artifactStringValue(artifact, 'workflow_run_id');
  const workflowNodeId = artifactStringValue(artifact, 'workflow_node_id');
  const workflowNodeLabel = artifactStringValue(artifact, 'workflow_node_label') || artifactStringValue(artifact, 'workflow_step_label');
  const sourceLabel = sourceRunnableName || workflowNodeLabel || sourceTool;
  const mimeType = artifactStringValue(artifact, 'mime_type');
  const previewText = artifactStringValue(artifact, 'preview_text');
  const url = artifactStringValue(artifact, 'url');
  const createdAt = artifactStringValue(artifact, 'created_at');
  const sizeBytes = artifactNumberValue(artifact, 'size_bytes');
  const artifactId = artifactStringValue(artifact, 'artifact_id') || `${sourceRunId}:${path || kind}:${index}`;
  const title = artifactStringValue(artifact, 'title')
    || (sourceLabel ? `${sourceLabel} / ${path || 'artifact'}` : path || kind || 'Artifact');
  return {
    artifact_id: artifactId,
    created_at: createdAt,
    group_id: groupId,
    group_run_id: groupRunId,
    kind,
    mime_type: mimeType,
    path,
    preview_text: previewText,
    run_id: runId,
    size_bytes: sizeBytes,
    source_label: sourceLabel,
    source_runnable_id: sourceRunnableId,
    source_runnable_name: sourceRunnableName,
    source_run_id: sourceRunId,
    source_tool: sourceTool,
    title,
    url,
    workflow_id: workflowId,
    workflow_node_id: workflowNodeId,
    workflow_node_label: workflowNodeLabel,
    workflow_run_id: workflowRunId,
  };
}

function artifactStringValue(artifact: RuntimeArtifactSource, key: string) {
  const value = (artifact as Record<string, unknown>)[key];
  return typeof value === 'string' ? value.trim() : '';
}

function artifactNumberValue(artifact: RuntimeArtifactSource, key: string) {
  const value = (artifact as Record<string, unknown>)[key];
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  if (typeof value !== 'string' || !value.trim()) return null;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : null;
}
