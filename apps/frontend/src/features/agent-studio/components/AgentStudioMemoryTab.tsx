import type { ComponentProps } from 'react';

import { formatRunDate } from '../utils/runs';
import { RuntimeMemoryPanel } from './RuntimeMemoryPanel';

type RuntimeMemoryPanelProps = ComponentProps<typeof RuntimeMemoryPanel>;

type AgentStudioMemoryTabProps = Omit<RuntimeMemoryPanelProps, 'formatRunDate'>;

export function AgentStudioMemoryTab(props: AgentStudioMemoryTabProps) {
  return (
    <RuntimeMemoryPanel
      {...props}
      formatRunDate={formatRunDate}
    />
  );
}
