import type { ReactNode } from 'react';

import type { ArtifactSnapshot } from '../types';

export type RuntimeArtifactSnapshot = Pick<
  ArtifactSnapshot,
  | 'artifact_id'
  | 'created_at'
  | 'kind'
  | 'mime_type'
  | 'path'
  | 'preview_text'
  | 'run_id'
  | 'size_bytes'
  | 'source_runnable_id'
  | 'source_runnable_name'
  | 'source_run_id'
  | 'source_tool'
  | 'title'
  | 'url'
  | 'workflow_id'
  | 'workflow_node_id'
  | 'workflow_node_label'
  | 'workflow_run_id'
  | 'group_id'
  | 'group_run_id'
>;

export type RuntimeArtifactVariant = 'compact' | 'full';

export function RuntimeArtifactPreview({
  actions,
  actionsClassName = 'runtime-artifact-actions',
  actionsElement: ActionsElement = 'div',
  actionsTestId,
  artifact,
  as: Component = 'div',
  className = 'yachiyo-task-artifact',
  testId = 'runtime-artifact-preview',
  variant = 'compact',
}: {
  actions?: ReactNode;
  actionsClassName?: string;
  actionsElement?: 'div' | 'span';
  actionsTestId?: string;
  artifact: RuntimeArtifactSnapshot;
  as?: 'div' | 'span';
  className?: string;
  testId?: string;
  variant?: RuntimeArtifactVariant;
}) {
  const label = artifact.title || artifact.path || artifact.kind || 'Artifact';
  const metadata = variant === 'full' ? artifactMetadataItems(artifact) : [];
  return (
    <Component
      className={className}
      data-artifact-id={artifact.artifact_id}
      data-artifact-kind={artifact.kind}
      data-artifact-mime-type={artifact.mime_type || ''}
      data-artifact-path={artifact.path || ''}
      data-artifact-run-id={artifact.run_id || ''}
      data-artifact-size-bytes={artifact.size_bytes ?? ''}
      data-artifact-source-runnable-id={artifact.source_runnable_id || ''}
      data-artifact-source-tool={artifact.source_tool || ''}
      data-artifact-source-run-id={artifact.source_run_id || ''}
      data-artifact-variant={variant}
      data-artifact-workflow-node-id={artifact.workflow_node_id || ''}
      data-testid={testId}
      title={artifact.path || label}
    >
      <span>{artifact.kind || 'artifact'}</span>
      <strong>{label}</strong>
      {artifact.preview_text && variant === 'full' ? (
        <p className="runtime-artifact-preview-text">{artifact.preview_text}</p>
      ) : null}
      {actions ? (
        <ActionsElement className={actionsClassName} data-testid={actionsTestId}>
          {actions}
        </ActionsElement>
      ) : null}
      {metadata.length ? (
        <div className="runtime-artifact-meta" data-testid={`${testId}-metadata`}>
          {metadata.map(({ label: itemLabel, value }) => (
            <span key={`${itemLabel}:${value}`}>{itemLabel} {value}</span>
          ))}
        </div>
      ) : null}
    </Component>
  );
}

function artifactMetadataItems(artifact: RuntimeArtifactSnapshot) {
  const items = [
    { label: 'artifact', value: artifact.artifact_id },
    { label: 'run', value: artifact.run_id || '' },
    { label: 'source', value: artifact.source_run_id || '' },
    { label: 'tool', value: artifact.source_tool || '' },
    { label: 'agent', value: artifact.source_runnable_name || artifact.source_runnable_id || '' },
    { label: 'workflow', value: artifact.workflow_node_label || artifact.workflow_node_id || '' },
    { label: 'group', value: artifact.group_run_id || artifact.group_id || '' },
    { label: 'mime', value: artifact.mime_type || '' },
    { label: 'size', value: artifactDisplaySize(artifact.size_bytes) },
    { label: 'path', value: artifact.path || '' },
    { label: 'created', value: artifact.created_at || '' },
    { label: 'url', value: artifact.url || '' },
  ];
  return items.filter((item) => String(item.value || '').trim());
}

function artifactDisplaySize(value?: number | null) {
  if (typeof value !== 'number' || !Number.isFinite(value)) return '';
  if (value < 1024) return `${value} B`;
  if (value < 1024 * 1024) return `${(value / 1024).toFixed(1)} KB`;
  return `${(value / (1024 * 1024)).toFixed(1)} MB`;
}
