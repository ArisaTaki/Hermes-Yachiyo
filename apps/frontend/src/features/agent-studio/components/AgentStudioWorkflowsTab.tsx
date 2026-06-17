import type { ComponentProps } from 'react';

import { agentCapabilityLine } from '../utils/agents';
import { WorkflowEditorPanel } from './WorkflowEditorPanel';

type WorkflowEditorPanelProps = ComponentProps<typeof WorkflowEditorPanel>;

type AgentStudioWorkflowsTabProps = Omit<WorkflowEditorPanelProps, 'agentCapabilityLine'>;

export function AgentStudioWorkflowsTab(props: AgentStudioWorkflowsTabProps) {
  return (
    <WorkflowEditorPanel
      {...props}
      agentCapabilityLine={agentCapabilityLine}
    />
  );
}
