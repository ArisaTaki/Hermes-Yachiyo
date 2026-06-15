import type { Dispatch, SetStateAction } from 'react';

import type { SkillFolderSpec, SkillSpec } from '../types';
import { navigateTo } from '../../../lib/view';
import {
  createYachiyoSkillFolder,
  deleteYachiyoSkillFolder,
  updateYachiyoSkillFolder,
} from '../../yachiyo-studio/api';
import {
  publicSkillFolderToSkillFolderSpec,
  skillFolderNameError,
  type SkillFolderFilter,
} from '../utils/skills';

type SkillFolderRefreshOptions = {
  statusMessage?: string;
};

type SkillFolderDeleteMode = 'folder' | 'skills';

type ConfirmDialogRequest = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

type UseSkillFolderManagementOptions = {
  editingSkillFolderId: string;
  editingSkillFolderName: string;
  newSkillFolderName: string;
  runAction: (action: () => Promise<SkillFolderRefreshOptions | void>, label: string) => void;
  setEditingSkillFolderId: (folderId: string) => void;
  setEditingSkillFolderName: (name: string) => void;
  setError: (message: string) => void;
  setNewSkillFolderName: (name: string) => void;
  setSkillFolderDeleteModes: Dispatch<SetStateAction<Record<string, SkillFolderDeleteMode>>>;
  setSkillLibraryFolderFilter: (filter: SkillFolderFilter) => void;
  setSkillMountFolderFilter: (filter: SkillFolderFilter) => void;
  setSkillTargetFolderId: (folderId: string) => void;
  setStatus: (message: string) => void;
  setTab: (tab: 'skills') => void;
  showConfirmDialog: (dialog: ConfirmDialogRequest) => void;
  skillFolders: SkillFolderSpec[];
  skillLibraryFolderFilter: SkillFolderFilter;
  skillMountFolderFilter: SkillFolderFilter;
  skills: SkillSpec[];
  skillTargetFolderId: string;
};

export function useSkillFolderManagement({
  editingSkillFolderId,
  editingSkillFolderName,
  newSkillFolderName,
  runAction,
  setEditingSkillFolderId,
  setEditingSkillFolderName,
  setError,
  setNewSkillFolderName,
  setSkillFolderDeleteModes,
  setSkillLibraryFolderFilter,
  setSkillMountFolderFilter,
  setSkillTargetFolderId,
  setStatus,
  setTab,
  showConfirmDialog,
  skillFolders,
  skillLibraryFolderFilter,
  skillMountFolderFilter,
  skills,
  skillTargetFolderId,
}: UseSkillFolderManagementOptions) {
  async function createSkillFolderFromDraft(): Promise<SkillFolderRefreshOptions | void> {
    const name = newSkillFolderName.trim();
    if (!name) throw new Error('请输入 Skill 文件夹名称');
    const validation = skillFolderNameError(name, skillFolders);
    if (validation) throw new Error(validation);
    const folder = publicSkillFolderToSkillFolderSpec(await createYachiyoSkillFolder({ name }));
    setNewSkillFolderName('');
    setSkillTargetFolderId(folder.folder_id);
    setSkillLibraryFolderFilter(folder.folder_id);
    setSkillMountFolderFilter(folder.folder_id);
  }

  function startEditingSkillFolder(folder: SkillFolderSpec) {
    setEditingSkillFolderId(folder.folder_id);
    setEditingSkillFolderName(folder.name);
    setStatus('');
    setError('');
  }

  function cancelEditingSkillFolder() {
    setEditingSkillFolderId('');
    setEditingSkillFolderName('');
  }

  async function updateSkillFolderFromDraft(folderId: string): Promise<SkillFolderRefreshOptions | void> {
    const name = editingSkillFolderName.trim();
    if (!name) throw new Error('请输入 Skill 文件夹名称');
    const validation = skillFolderNameError(name, skillFolders, folderId);
    if (validation) throw new Error(validation);
    await updateYachiyoSkillFolder(folderId, { name });
    cancelEditingSkillFolder();
  }

  async function deleteSkillFolderById(folderId: string, deleteSkills = false): Promise<SkillFolderRefreshOptions | void> {
    await deleteYachiyoSkillFolder(folderId, { deleteSkills });
    if (skillTargetFolderId === folderId) setSkillTargetFolderId('');
    if (skillLibraryFolderFilter === folderId) setSkillLibraryFolderFilter('all');
    if (skillMountFolderFilter === folderId) setSkillMountFolderFilter('all');
    if (editingSkillFolderId === folderId) cancelEditingSkillFolder();
    setSkillFolderDeleteMode(folderId, null);
  }

  function setSkillFolderDeleteMode(folderId: string, mode: SkillFolderDeleteMode | null) {
    setSkillFolderDeleteModes((current) => {
      const next = { ...current };
      if (mode) next[folderId] = mode;
      else delete next[folderId];
      return next;
    });
  }

  function requestDeleteSkillFolder(folder: SkillFolderSpec, deleteSkills: boolean) {
    const count = folder.skill_count || skills.filter((skill) => skill.folder_id === folder.folder_id).length;
    if (deleteSkills) {
      showConfirmDialog({
        title: `删除「${folder.name}」和其中 ${count} 个 Skill？`,
        description: 'Installed Skill 本地副本会被删除；Native Skill 只会删除 Oha-Yachiyo 的登记，不会删除原始文件。',
        confirmLabel: '连带删除',
        variant: 'danger',
        onConfirm: () => void runAction(
          async () => deleteSkillFolderById(folder.folder_id, true),
          '删除 Skill 文件夹和 Skills',
        ),
      });
      return;
    }
    showConfirmDialog({
      title: `删除文件夹「${folder.name}」？`,
      description: `${count} 个 Skill 会回到“无需分组”。`,
      confirmLabel: '删除文件夹',
      variant: 'danger',
      onConfirm: () => void runAction(
        async () => deleteSkillFolderById(folder.folder_id, false),
        '删除 Skill 文件夹',
      ),
    });
  }

  function openSkillLibraryFolder(folder: SkillFolderSpec) {
    setSkillTargetFolderId(folder.folder_id);
    setSkillLibraryFolderFilter(folder.folder_id);
    setTab('skills');
    navigateTo('agents', { tab: 'skills' }, ['run', 'tab']);
  }

  return {
    cancelEditingSkillFolder,
    createSkillFolderFromDraft,
    deleteSkillFolderById,
    openSkillLibraryFolder,
    requestDeleteSkillFolder,
    setSkillFolderDeleteMode,
    startEditingSkillFolder,
    updateSkillFolderFromDraft,
  };
}
