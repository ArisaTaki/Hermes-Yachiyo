import type { Dispatch, SetStateAction } from 'react';

import {
  deleteSkill,
  type SkillSpec,
} from '../../../lib/agents';
import { isInstalledSkill, isNativeSkill } from '../utils/skills';

type SkillDeletionRefreshOptions = {
  statusMessage?: string;
};

type ConfirmDialogRequest = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

type UseSkillDeletionActionsOptions = {
  runAction: (action: () => Promise<SkillDeletionRefreshOptions | void>, label: string) => void;
  selectedLibrarySkills: SkillSpec[];
  setSelectedSkillIds: Dispatch<SetStateAction<string[]>>;
  showConfirmDialog: (dialog: ConfirmDialogRequest) => void;
};

export function useSkillDeletionActions({
  runAction,
  selectedLibrarySkills,
  setSelectedSkillIds,
  showConfirmDialog,
}: UseSkillDeletionActionsOptions) {
  function requestDeleteSkill(skill: SkillSpec) {
    showConfirmDialog({
      title: `删除 Skill「${skill.name}」？`,
      description: isNativeSkill(skill)
        ? '这只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除 Native Skill Library 原始文件。'
        : 'Installed Skill 管理区里的本地 Skill 副本会被删除，已挂载它的 Agent 会失去这个 Skill。',
      confirmLabel: '删除 Skill',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteSkill(skill.skill_id);
        setSelectedSkillIds((current) => current.filter((id) => id !== skill.skill_id));
      }, '删除 Skill'),
    });
  }

  function requestDeleteSelectedSkills() {
    const targets = selectedLibrarySkills.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((skill) => skill.skill_id));
    const hasNativeSkills = targets.some(isNativeSkill);
    const hasInstalledSkills = targets.some(isInstalledSkill);
    const description = hasNativeSkills && hasInstalledSkills
      ? 'Installed Skill 管理区里的本地 Skill 副本会被删除；Native Skill 只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除原始文件。'
      : hasNativeSkills
        ? '这些 Native Skill 只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除原始文件。'
        : 'Installed Skill 管理区里的本地 Skill 副本会被删除，已挂载它们的 Agent 会失去这些 Skill。';
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Skill？`,
      description,
      confirmLabel: `删除 ${targets.length} 个 Skill`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const skill of targets) {
          await deleteSkill(skill.skill_id);
        }
        setSelectedSkillIds((current) => current.filter((id) => !targetIds.has(id)));
      }, '批量删除 Skill'),
    });
  }

  return {
    requestDeleteSelectedSkills,
    requestDeleteSkill,
  };
}
