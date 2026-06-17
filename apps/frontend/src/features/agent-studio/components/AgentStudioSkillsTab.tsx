import type { ComponentProps } from 'react';

import { SkillLibraryTab } from './SkillLibraryTab';

type SkillLibraryTabProps = ComponentProps<typeof SkillLibraryTab>;

export function AgentStudioSkillsTab(props: SkillLibraryTabProps) {
  return <SkillLibraryTab {...props} />;
}
