import { useCallback, type Dispatch, type SetStateAction } from 'react';

import { openPath } from '../../../lib/bridge';
import { updateYachiyoSkill } from '../../yachiyo-studio/api';
import type { StudioRefreshOptions } from './useAgentStudioRefresh';
import type { SkillSpec } from '../types';

type UseSkillLibraryActionsOptions = {
  runAction: (action: () => Promise<StudioRefreshOptions | void>, label: string) => void;
  setSelectedSkillIds: Dispatch<SetStateAction<string[]>>;
  setSkillManagementMode: (managing: boolean) => void;
};

function toggleSkillSelection(current: string[], skillId: string): string[] {
  if (!skillId) return current;
  if (current.includes(skillId)) return current.filter((item) => item !== skillId);
  return [...current, skillId];
}

export function useSkillLibraryActions({
  runAction,
  setSelectedSkillIds,
  setSkillManagementMode,
}: UseSkillLibraryActionsOptions) {
  const toggleSkillSelected = useCallback((skillId: string) => {
    setSelectedSkillIds((current) => toggleSkillSelection(current, skillId));
  }, [setSelectedSkillIds]);

  const finishSkillManagement = useCallback(() => {
    setSkillManagementMode(false);
    setSelectedSkillIds([]);
  }, [setSelectedSkillIds, setSkillManagementMode]);

  const moveSkillFolder = useCallback((skill: SkillSpec, folderId: string) => {
    void runAction(async () => {
      await updateYachiyoSkill(skill.skill_id, { folder_id: folderId });
    }, '移动 Skill');
  }, [runAction]);

  const openSkillLocation = useCallback((skill: SkillSpec) => {
    void runAction(async () => {
      await openPath(skill.local_path || '');
    }, '打开 Skill 路径');
  }, [runAction]);

  const toggleSkillEnabled = useCallback((skill: SkillSpec) => {
    void runAction(async () => {
      await updateYachiyoSkill(skill.skill_id, { enabled: skill.enabled === false });
    }, skill.enabled === false ? '启用 Skill' : '停用 Skill');
  }, [runAction]);

  return {
    finishSkillManagement,
    moveSkillFolder,
    openSkillLocation,
    toggleSkillEnabled,
    toggleSkillSelected,
  };
}
