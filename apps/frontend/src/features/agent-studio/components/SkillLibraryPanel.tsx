import type { SkillFolderSpec, SkillSpec } from '../types';
import type { SkillFolderFilter, SkillSourceFilter } from '../utils/skills';
import { SkillCard } from './SkillCard';

type SkillLibraryPanelProps = {
  allLibrarySkillsSelected: boolean;
  busy: boolean;
  filteredLibrarySkillIds: string[];
  filteredLibrarySkills: SkillSpec[];
  installedSkillCount: number;
  nativeSkillCount: number;
  selectedLibrarySkills: SkillSpec[];
  selectedSkillIdSet: Set<string>;
  skillFolders: SkillFolderSpec[];
  skillLibraryFilter: SkillSourceFilter;
  skillLibraryFolderFilter: SkillFolderFilter;
  skillLibrarySearch: string;
  skillManagementMode: boolean;
  onDeleteSkill: (skill: SkillSpec) => void;
  onDeleteSelectedSkills: () => void;
  onFinishSkillManagement: () => void;
  onMoveSkillFolder: (skill: SkillSpec, folderId: string) => void;
  onOpenSkillLocation: (skill: SkillSpec) => void;
  onSetSelectedSkillIds: (skillIds: string[]) => void;
  onSetSkillLibraryFilter: (filter: SkillSourceFilter) => void;
  onSetSkillLibraryFolderFilter: (folderId: SkillFolderFilter) => void;
  onSetSkillLibrarySearch: (query: string) => void;
  onSetSkillManagementMode: (managing: boolean) => void;
  onToggleSkillEnabled: (skill: SkillSpec) => void;
  onToggleSkillSelected: (skillId: string) => void;
};

export function SkillLibraryPanel({
  allLibrarySkillsSelected,
  busy,
  filteredLibrarySkillIds,
  filteredLibrarySkills,
  installedSkillCount,
  nativeSkillCount,
  selectedLibrarySkills,
  selectedSkillIdSet,
  skillFolders,
  skillLibraryFilter,
  skillLibraryFolderFilter,
  skillLibrarySearch,
  skillManagementMode,
  onDeleteSkill,
  onDeleteSelectedSkills,
  onFinishSkillManagement,
  onMoveSkillFolder,
  onOpenSkillLocation,
  onSetSelectedSkillIds,
  onSetSkillLibraryFilter,
  onSetSkillLibraryFolderFilter,
  onSetSkillLibrarySearch,
  onSetSkillManagementMode,
  onToggleSkillEnabled,
  onToggleSkillSelected,
}: SkillLibraryPanelProps) {
  return (
    <div className="agent-studio-panel" data-testid="skill-library-panel">
      <div className="section-heading-row">
        <h2>{skillLibraryFilter === 'native' ? 'Native Skill Library' : 'Installed Skill Library'}</h2>
        <div className="studio-heading-actions">
          <span className="agent-section-count">{installedSkillCount} Installed / {nativeSkillCount} Native</span>
          {filteredLibrarySkills.length && !skillManagementMode ? (
            <button type="button" disabled={busy} onClick={() => onSetSkillManagementMode(true)}>管理</button>
          ) : null}
        </div>
      </div>
      <div className="skill-filter-bar">
        <div className="skill-filter-tabs">
          <button
            type="button"
            data-testid="skill-filter-installed"
            className={skillLibraryFilter === 'installed' ? 'active' : ''}
            onClick={() => onSetSkillLibraryFilter('installed')}
          >
            Installed
          </button>
          <button
            type="button"
            data-testid="skill-filter-native"
            className={skillLibraryFilter === 'native' ? 'active' : ''}
            onClick={() => onSetSkillLibraryFilter('native')}
          >
            Native
          </button>
        </div>
        <select
          className="hy-select"
          data-testid="skill-library-folder-filter"
          value={skillLibraryFolderFilter}
          onChange={(event) => onSetSkillLibraryFolderFilter(event.target.value)}
        >
          <option value="all">全部文件夹</option>
          <option value="uncategorized">无需分组</option>
          {skillFolders.map((folder) => (
            <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
          ))}
        </select>
        <input
          className="hy-input"
          data-testid="skill-library-search"
          value={skillLibrarySearch}
          onChange={(event) => onSetSkillLibrarySearch(event.target.value)}
          placeholder="搜索 Skill 名称、路径或摘要"
        />
      </div>
      {filteredLibrarySkills.length && skillManagementMode ? (
        <div className="studio-bulk-actions" aria-label="Skill 批量操作">
          <span>
            {selectedLibrarySkills.length
              ? `已选择 ${selectedLibrarySkills.length} / ${filteredLibrarySkills.length}`
              : `${filteredLibrarySkills.length} skills`}
          </span>
          <button
            type="button"
            disabled={busy}
            onClick={() => onSetSelectedSkillIds(
              allLibrarySkillsSelected ? [] : filteredLibrarySkillIds,
            )}
          >
            {allLibrarySkillsSelected ? '取消全选' : '全选当前列表'}
          </button>
          <button
            type="button"
            disabled={busy || !selectedLibrarySkills.length}
            onClick={() => onSetSelectedSkillIds([])}
          >
            清空
          </button>
          <button
            type="button"
            className="danger-action"
            disabled={busy || !selectedLibrarySkills.length}
            onClick={onDeleteSelectedSkills}
          >
            删除所选
          </button>
          <button type="button" disabled={busy} onClick={onFinishSkillManagement}>完成</button>
        </div>
      ) : null}
      <div className="skill-list" data-testid="skill-list">
        {filteredLibrarySkills.map((skill) => (
          <SkillCard
            busy={busy}
            folders={skillFolders}
            key={skill.skill_id}
            onDelete={() => onDeleteSkill(skill)}
            onMoveFolder={(folderId) => onMoveSkillFolder(skill, folderId)}
            onOpenLocation={() => onOpenSkillLocation(skill)}
            onSelectionChange={() => onToggleSkillSelected(skill.skill_id)}
            onToggleEnabled={() => onToggleSkillEnabled(skill)}
            managing={skillManagementMode}
            selected={selectedSkillIdSet.has(skill.skill_id)}
            skill={skill}
          />
        ))}
        {!filteredLibrarySkills.length ? <div className="empty-state inline-empty">当前分类或搜索下没有 Skill。</div> : null}
      </div>
    </div>
  );
}
