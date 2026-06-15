import type { ComponentProps } from 'react';

import { RunDetailPanel } from './RunDetailPanel';
import { RunLauncherPanel } from './RunLauncherPanel';

type RunManagementTabProps =
  ComponentProps<typeof RunLauncherPanel>
  & ComponentProps<typeof RunDetailPanel>;

export function RunManagementTab(props: RunManagementTabProps) {
  return (
    <section className="agent-studio-grid" data-testid="agent-studio-runs">
      <RunLauncherPanel {...props} />
      <RunDetailPanel {...props} />
    </section>
  );
}
