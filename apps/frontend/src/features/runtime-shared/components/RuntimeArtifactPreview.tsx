import type { ReactNode } from 'react';

import type { ArtifactSnapshot } from '../types';
import {
  runtimeArtifactPresentation,
  type RuntimeArtifactPresentationMode,
} from '../artifactPresentation';
import { runtimeAnchorId } from '../runtimeAnchors';

export type RuntimeArtifactSnapshot = Pick<
  ArtifactSnapshot,
  | 'artifact_id'
  | 'created_at'
  | 'capability_id'
  | 'decision_id'
  | 'intent_kind'
  | 'kind'
  | 'mime_type'
  | 'path'
  | 'plan_id'
  | 'planner_step_id'
  | 'planning_reason'
  | 'capability_title'
  | 'capability_status'
  | 'capability_reason'
  | 'capability_selected_tools'
  | 'capability_planned_step_ids'
  | 'preview_text'
  | 'replan_request_id'
  | 'replan_signal_ids'
  | 'replan_trigger'
  | 'replan_triggers'
  | 'requires_observation'
  | 'requires_post_action_verification'
  | 'run_id'
  | 'runtime_doctrine'
  | 'runtime_role'
  | 'runtime_stage'
  | 'size_bytes'
  | 'source'
  | 'source_runnable_id'
  | 'source_runnable_name'
  | 'source_run_id'
  | 'source_tool'
  | 'step_id'
  | 'title'
  | 'tool_plan_id'
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
  presentationMode = 'diagnostic',
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
  presentationMode?: RuntimeArtifactPresentationMode;
  testId?: string;
  variant?: RuntimeArtifactVariant;
}) {
  const presentation = runtimeArtifactPresentation(artifact, presentationMode);
  const label = presentation.label;
  const metadata = variant === 'full' ? artifactMetadataItems(artifact) : [];
  const anchorValue = artifact.artifact_id || artifact.path || '';
  const anchorKind = artifact.artifact_id ? 'artifact' : 'artifact-path';
  const anchorId = runtimeAnchorId(anchorKind, anchorValue);
  return (
    <Component
      className={className}
      id={anchorId || undefined}
      data-artifact-id={artifact.artifact_id}
      data-artifact-group-id={artifact.group_id || ''}
      data-artifact-group-run-id={artifact.group_run_id || ''}
      data-artifact-kind={artifact.kind}
      data-artifact-mime-type={artifact.mime_type || ''}
      data-artifact-path={artifact.path || ''}
      data-artifact-run-id={artifact.run_id || ''}
      data-artifact-runtime-capability-id={artifact.capability_id || ''}
      data-artifact-runtime-capability-title={artifact.capability_title || ''}
      data-artifact-runtime-doctrine={artifact.runtime_doctrine || ''}
      data-artifact-runtime-role={artifact.runtime_role || ''}
      data-artifact-runtime-stage={artifact.runtime_stage || ''}
      data-artifact-runtime-step-id={artifact.step_id || artifact.planner_step_id || ''}
      data-artifact-size-bytes={artifact.size_bytes ?? ''}
      data-artifact-source-runnable-id={artifact.source_runnable_id || ''}
      data-artifact-source-tool={artifact.source_tool || ''}
      data-artifact-source-run-id={artifact.source_run_id || ''}
      data-artifact-replan-request-id={artifact.replan_request_id || ''}
      data-artifact-replan-signal-ids={(artifact.replan_signal_ids || []).join(',')}
      data-artifact-replan-trigger={artifact.replan_trigger || artifact.replan_triggers?.[0] || ''}
      data-artifact-variant={variant}
      data-artifact-workflow-id={artifact.workflow_id || ''}
      data-artifact-workflow-node-id={artifact.workflow_node_id || ''}
      data-artifact-workflow-run-id={artifact.workflow_run_id || ''}
      data-runtime-anchor={anchorId}
      data-runtime-anchor-kind={anchorKind}
      data-runtime-anchor-value={anchorValue}
      data-testid={testId}
      title={presentation.tooltip || undefined}
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
  const capabilityTitle = artifact.capability_title || '';
  const items = [
    { label: 'artifact', value: artifact.artifact_id },
    { label: 'run', value: artifact.run_id || '' },
    { label: 'source', value: artifact.source_run_id || '' },
    { label: 'tool', value: artifact.source_tool || '' },
    { label: 'agent', value: artifact.source_runnable_name || artifact.source_runnable_id || '' },
    { label: 'workflow', value: artifact.workflow_node_label || artifact.workflow_node_id || artifact.workflow_run_id || artifact.workflow_id || '' },
    { label: 'group', value: artifact.group_run_id || artifact.group_id || '' },
    { label: 'step', value: artifact.step_id || artifact.planner_step_id || '' },
    { label: 'capability', value: capabilityTitle || artifact.capability_id || '' },
    { label: 'capability id', value: capabilityTitle ? artifact.capability_id || '' : '' },
    { label: 'capability status', value: artifact.capability_status || '' },
    { label: 'capability reason', value: artifact.capability_reason || '' },
    { label: 'capability tools', value: artifact.capability_selected_tools?.join(', ') || '' },
    { label: 'capability steps', value: artifact.capability_planned_step_ids?.join(', ') || '' },
    { label: 'stage', value: artifact.runtime_stage || '' },
    { label: 'role', value: artifact.runtime_role || '' },
    { label: 'doctrine', value: artifact.runtime_doctrine || '' },
    { label: 'observe', value: artifact.requires_observation ? 'required' : '' },
    { label: 'verify', value: artifact.requires_post_action_verification ? 'required' : '' },
    { label: 'plan', value: artifact.tool_plan_id || artifact.plan_id || '' },
    { label: 'decision', value: artifact.decision_id || '' },
    { label: 'intent', value: artifact.intent_kind || '' },
    { label: 'replan', value: artifact.replan_request_id || artifact.replan_trigger || artifact.replan_triggers?.join(', ') || '' },
    { label: 'signals', value: artifact.replan_signal_ids?.join(', ') || '' },
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
