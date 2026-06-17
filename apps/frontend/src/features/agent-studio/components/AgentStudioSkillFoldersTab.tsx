import type { ComponentProps } from 'react';

import { SkillFolderPanel } from './SkillFolderPanel';

type SkillFolderPanelProps = ComponentProps<typeof SkillFolderPanel>;

export function AgentStudioSkillFoldersTab(props: SkillFolderPanelProps) {
  return <SkillFolderPanel {...props} />;
}
