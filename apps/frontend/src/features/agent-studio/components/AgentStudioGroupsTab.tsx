import type { ComponentProps } from 'react';

import { AgentGroupPanel } from './AgentGroupPanel';

type AgentGroupPanelProps = ComponentProps<typeof AgentGroupPanel>;
type AgentStudioGroupsTabProps = Omit<AgentGroupPanelProps, 'agentGroupMemoryScope' | 'agentGroupMode'> & {
  agentGroupMemoryScope?: string;
  agentGroupMode?: string;
};

export function AgentStudioGroupsTab({
  agentGroupMemoryScope,
  agentGroupMode,
  ...props
}: AgentStudioGroupsTabProps) {
  return (
    <AgentGroupPanel
      {...props}
      agentGroupMemoryScope={agentGroupMemoryScope || 'shared'}
      agentGroupMode={agentGroupMode || 'moderated'}
    />
  );
}
