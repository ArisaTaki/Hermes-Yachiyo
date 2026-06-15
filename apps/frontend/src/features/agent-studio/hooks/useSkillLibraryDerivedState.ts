import { useMemo } from 'react';

import type {
  AgentSpec,
  SkillFolderSpec,
  SkillSpec,
} from '../../../lib/agents';
import {
  isInstalledSkill,
  isNativeSkill,
  skillFolderNameError,
  skillMatchesFolderFilter,
  skillMatchesQuery,
  skillMatchesSourceFilter,
  type SkillFolderFilter,
  type SkillSourceFilter,
} from '../utils/skills';

type UseSkillLibraryDerivedStateOptions = {
  editingSkillFolderId: string;
  editingSkillFolderName: string;
  newSkillFolderName: string;
  selectedAgent: AgentSpec | null;
  selectedSkillIds: string[];
  skillFolders: SkillFolderSpec[];
  skillLibraryFilter: SkillSourceFilter;
  skillLibraryFolderFilter: SkillFolderFilter;
  skillLibrarySearch: string;
  skillMountFilter: SkillSourceFilter;
  skillMountFolderFilter: SkillFolderFilter;
  skillMountSearch: string;
  skills: SkillSpec[];
};

export function useSkillLibraryDerivedState({
  editingSkillFolderId,
  editingSkillFolderName,
  newSkillFolderName,
  selectedAgent,
  selectedSkillIds,
  skillFolders,
  skillLibraryFilter,
  skillLibraryFolderFilter,
  skillLibrarySearch,
  skillMountFilter,
  skillMountFolderFilter,
  skillMountSearch,
  skills,
}: UseSkillLibraryDerivedStateOptions) {
  const mountedSkillCount = useMemo(
    () => skills.filter((skill) => (
      skill.enabled !== false && selectedAgent?.skill_ids?.includes(skill.skill_id)
    )).length,
    [selectedAgent, skills],
  );
  const enabledSkills = useMemo(
    () => skills.filter((skill) => skill.enabled !== false),
    [skills],
  );
  const installedSkillCount = useMemo(
    () => skills.filter(isInstalledSkill).length,
    [skills],
  );
  const nativeSkillCount = useMemo(
    () => skills.filter(isNativeSkill).length,
    [skills],
  );
  const filteredLibrarySkills = useMemo(
    () => skills.filter((skill) => (
      skillMatchesSourceFilter(skill, skillLibraryFilter)
      && skillMatchesFolderFilter(skill, skillLibraryFolderFilter)
      && skillMatchesQuery(skill, skillLibrarySearch)
    )),
    [skills, skillLibraryFilter, skillLibraryFolderFilter, skillLibrarySearch],
  );
  const filteredLibrarySkillIds = useMemo(
    () => filteredLibrarySkills.map((skill) => skill.skill_id).filter(Boolean),
    [filteredLibrarySkills],
  );
  const selectedSkillIdSet = useMemo(
    () => new Set(selectedSkillIds),
    [selectedSkillIds],
  );
  const selectedLibrarySkills = useMemo(
    () => filteredLibrarySkills.filter((skill) => selectedSkillIdSet.has(skill.skill_id)),
    [filteredLibrarySkills, selectedSkillIdSet],
  );
  const allLibrarySkillsSelected = (
    filteredLibrarySkillIds.length > 0
    && selectedLibrarySkills.length === filteredLibrarySkillIds.length
  );
  const filteredMountSkills = useMemo(
    () => enabledSkills.filter((skill) => (
      skillMatchesSourceFilter(skill, skillMountFilter)
      && skillMatchesFolderFilter(skill, skillMountFolderFilter)
      && skillMatchesQuery(skill, skillMountSearch)
    )),
    [enabledSkills, skillMountFilter, skillMountFolderFilter, skillMountSearch],
  );
  const disabledMountedSkills = useMemo(
    () => skills.filter((skill) => (
      skill.enabled === false && selectedAgent?.skill_ids?.includes(skill.skill_id)
    )),
    [selectedAgent, skills],
  );
  const visibleMountSkillIds = useMemo(
    () => filteredMountSkills.map((skill) => skill.skill_id),
    [filteredMountSkills],
  );
  const visibleMountedCount = useMemo(
    () => visibleMountSkillIds.filter((skillId) => selectedAgent?.skill_ids?.includes(skillId)).length,
    [selectedAgent, visibleMountSkillIds],
  );
  const ungroupedSkillStats = useMemo(() => {
    const ungrouped = skills.filter((skill) => !skill.folder_id);
    return {
      total: ungrouped.length,
      installed: ungrouped.filter(isInstalledSkill).length,
      native: ungrouped.filter(isNativeSkill).length,
    };
  }, [skills]);
  const newSkillFolderError = useMemo(
    () => skillFolderNameError(newSkillFolderName, skillFolders),
    [newSkillFolderName, skillFolders],
  );
  const editingSkillFolderError = useMemo(
    () => skillFolderNameError(editingSkillFolderName, skillFolders, editingSkillFolderId),
    [editingSkillFolderId, editingSkillFolderName, skillFolders],
  );

  return {
    allLibrarySkillsSelected,
    disabledMountedSkills,
    filteredLibrarySkillIds,
    filteredLibrarySkills,
    filteredMountSkills,
    installedSkillCount,
    mountedSkillCount,
    nativeSkillCount,
    editingSkillFolderError,
    newSkillFolderError,
    selectedLibrarySkills,
    selectedSkillIdSet,
    ungroupedSkillStats,
    visibleMountedCount,
    visibleMountSkillIds,
  };
}
