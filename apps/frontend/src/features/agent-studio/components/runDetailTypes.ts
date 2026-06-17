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
  truncated?: boolean;
};
