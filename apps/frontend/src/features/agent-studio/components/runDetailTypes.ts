import type { RuntimeImageArtifactSelectedPoint } from '../../runtime-shared/components/RuntimeReadableArtifactPreview';

export type RunDetailWorkflowStepRef = {
  key: string;
  kind: 'start' | 'agent' | 'approval' | 'artifact' | 'condition' | 'parallel' | 'workflow' | 'loop' | 'unknown';
  nodeId?: string;
  label: string;
  status: string;
  childRunId?: string;
  payload?: string;
  artifactPath?: string;
  artifactCount?: number;
  task?: string;
  selectedBranch?: string;
  selectedTargetNodeId?: string;
};

export type RunArtifactPreview = {
  path: string;
  content: string;
  mime_type?: string | null;
  run_id?: string | null;
  truncated?: boolean;
};

export type RunRecoveryCoordinate = RuntimeImageArtifactSelectedPoint & {
  artifact_id: string;
  kind?: string | null;
  run_id: string;
  source_tool?: string | null;
};

export type RunRecoveryScreenPointContract = {
  artifactKind: string;
  artifactTool: string;
};
