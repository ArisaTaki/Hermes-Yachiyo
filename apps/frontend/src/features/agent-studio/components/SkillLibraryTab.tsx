import type { DragEvent } from 'react';

import type { SkillFolderSpec, SkillSourceRoot, SkillSpec } from '../types';
import type { SkillFolderFilter, SkillImportResult, SkillSourceFilter } from '../utils/skills';
import { SkillImportPanel } from './SkillImportPanel';
import { SkillLibraryPanel } from './SkillLibraryPanel';

type SkillLibraryTabProps = {
  allLibrarySkillsSelected: boolean;
  busy: boolean;
  filteredLibrarySkillIds: string[];
  filteredLibrarySkills: SkillSpec[];
  installedSkillCount: number;
  installingSkill: boolean;
  nativeSkillCount: number;
  selectedLibrarySkills: SkillSpec[];
  selectedSkillIdSet: Set<string>;
  skillFolders: SkillFolderSpec[];
  skillImportResults: SkillImportResult[];
  skillInstallCommand: string;
  skillLibraryFilter: SkillSourceFilter;
  skillLibraryFolderFilter: SkillFolderFilter;
  skillLibrarySearch: string;
  skillManagementMode: boolean;
  skillSources: SkillSourceRoot[];
  skillTargetFolderId: string;
  onDeleteSkill: (skill: SkillSpec) => void;
  onDeleteSelectedSkills: () => void;
  onDropSkillSources: (event: DragEvent<HTMLElement>) => void;
  onFinishSkillManagement: () => void;
  onInstallSkill: () => void;
  onMoveSkillFolder: (skill: SkillSpec, folderId: string) => void;
  onOpenSkillLocation: (skill: SkillSpec) => void;
  onPickSkillSources: () => void;
  onSetSelectedSkillIds: (skillIds: string[]) => void;
  onSetSkillInstallCommand: (command: string) => void;
  onSetSkillLibraryFilter: (filter: SkillSourceFilter) => void;
  onSetSkillLibraryFolderFilter: (folderId: SkillFolderFilter) => void;
  onSetSkillLibrarySearch: (query: string) => void;
  onSetSkillManagementMode: (managing: boolean) => void;
  onSetSkillTargetFolderId: (folderId: string) => void;
  onSyncNativeSkillLibrary: () => void;
  onToggleSkillEnabled: (skill: SkillSpec) => void;
  onToggleSkillSelected: (skillId: string) => void;
};

export function SkillLibraryTab({
  allLibrarySkillsSelected,
  busy,
  filteredLibrarySkillIds,
  filteredLibrarySkills,
  installedSkillCount,
  installingSkill,
  nativeSkillCount,
  selectedLibrarySkills,
  selectedSkillIdSet,
  skillFolders,
  skillImportResults,
  skillInstallCommand,
  skillLibraryFilter,
  skillLibraryFolderFilter,
  skillLibrarySearch,
  skillManagementMode,
  skillSources,
  skillTargetFolderId,
  onDeleteSkill,
  onDeleteSelectedSkills,
  onDropSkillSources,
  onFinishSkillManagement,
  onInstallSkill,
  onMoveSkillFolder,
  onOpenSkillLocation,
  onPickSkillSources,
  onSetSelectedSkillIds,
  onSetSkillInstallCommand,
  onSetSkillLibraryFilter,
  onSetSkillLibraryFolderFilter,
  onSetSkillLibrarySearch,
  onSetSkillManagementMode,
  onSetSkillTargetFolderId,
  onSyncNativeSkillLibrary,
  onToggleSkillEnabled,
  onToggleSkillSelected,
}: SkillLibraryTabProps) {
  return (
    <section className="agent-studio-grid" data-testid="skill-library">
      <SkillImportPanel
        busy={busy}
        installingSkill={installingSkill}
        skillFolders={skillFolders}
        skillImportResults={skillImportResults}
        skillInstallCommand={skillInstallCommand}
        skillSources={skillSources}
        skillTargetFolderId={skillTargetFolderId}
        onDropSkillSources={onDropSkillSources}
        onInstallSkill={onInstallSkill}
        onPickSkillSources={onPickSkillSources}
        onSetSkillInstallCommand={onSetSkillInstallCommand}
        onSetSkillTargetFolderId={onSetSkillTargetFolderId}
        onSyncNativeSkillLibrary={onSyncNativeSkillLibrary}
      />
      <SkillLibraryPanel
        allLibrarySkillsSelected={allLibrarySkillsSelected}
        busy={busy}
        filteredLibrarySkillIds={filteredLibrarySkillIds}
        filteredLibrarySkills={filteredLibrarySkills}
        installedSkillCount={installedSkillCount}
        nativeSkillCount={nativeSkillCount}
        selectedLibrarySkills={selectedLibrarySkills}
        selectedSkillIdSet={selectedSkillIdSet}
        skillFolders={skillFolders}
        skillLibraryFilter={skillLibraryFilter}
        skillLibraryFolderFilter={skillLibraryFolderFilter}
        skillLibrarySearch={skillLibrarySearch}
        skillManagementMode={skillManagementMode}
        onDeleteSkill={onDeleteSkill}
        onDeleteSelectedSkills={onDeleteSelectedSkills}
        onFinishSkillManagement={onFinishSkillManagement}
        onMoveSkillFolder={onMoveSkillFolder}
        onOpenSkillLocation={onOpenSkillLocation}
        onSetSelectedSkillIds={onSetSelectedSkillIds}
        onSetSkillLibraryFilter={onSetSkillLibraryFilter}
        onSetSkillLibraryFolderFilter={onSetSkillLibraryFolderFilter}
        onSetSkillLibrarySearch={onSetSkillLibrarySearch}
        onSetSkillManagementMode={onSetSkillManagementMode}
        onToggleSkillEnabled={onToggleSkillEnabled}
        onToggleSkillSelected={onToggleSkillSelected}
      />
    </section>
  );
}
