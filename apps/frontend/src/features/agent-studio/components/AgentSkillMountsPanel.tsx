import type { SkillFolderSpec, SkillSpec } from '../types';

type SkillSourceFilter = 'installed' | 'native';
type SkillFolderFilter = 'all' | 'uncategorized' | string;

type AgentSkillMountsPanelProps = {
  busy: boolean;
  disabledMountedSkills: SkillSpec[];
  filteredMountSkills: SkillSpec[];
  mountedSkillCount: number;
  selectedAgentReadOnly: boolean;
  selectedSkillIds?: string[];
  skillFolders: SkillFolderSpec[];
  skillMountFilter: SkillSourceFilter;
  skillMountFolderFilter: SkillFolderFilter;
  skillMountSearch: string;
  visibleMountedCount: number;
  onMountVisibleSkills: () => void;
  onSetSkillMountFilter: (filter: SkillSourceFilter) => void;
  onSetSkillMountFolderFilter: (filter: SkillFolderFilter) => void;
  onSetSkillMountSearch: (query: string) => void;
  onToggleSkillMount: (skill: SkillSpec, mounted: boolean) => void;
  onUnmountVisibleSkills: () => void;
};

export function AgentSkillMountsPanel({
  busy,
  disabledMountedSkills,
  filteredMountSkills,
  mountedSkillCount,
  selectedAgentReadOnly,
  selectedSkillIds = [],
  skillFolders,
  skillMountFilter,
  skillMountFolderFilter,
  skillMountSearch,
  visibleMountedCount,
  onMountVisibleSkills,
  onSetSkillMountFilter,
  onSetSkillMountFolderFilter,
  onSetSkillMountSearch,
  onToggleSkillMount,
  onUnmountVisibleSkills,
}: AgentSkillMountsPanelProps) {
  const selectedSkillIdSet = new Set(selectedSkillIds);
  return (
    <div className="agent-skill-mounts" data-testid="agent-skill-mounts">
      <div className="agent-skill-mounts-head">
        <h3>Mounted Skills</h3>
        <span data-testid="agent-skill-mount-summary">{mountedSkillCount} mounted / {filteredMountSkills.length} visible skills</span>
      </div>
      {disabledMountedSkills.length ? (
        <div className="agent-inline-note warn">
          有 {disabledMountedSkills.length} 个已挂载 Skill 当前已停用，运行时不会通过校验。
        </div>
      ) : null}
      <div className="skill-filter-bar">
        <div className="skill-filter-tabs">
          <button type="button" data-testid="agent-skill-mount-filter-installed" className={skillMountFilter === 'installed' ? 'active' : ''} onClick={() => onSetSkillMountFilter('installed')}>Installed</button>
          <button type="button" data-testid="agent-skill-mount-filter-native" className={skillMountFilter === 'native' ? 'active' : ''} onClick={() => onSetSkillMountFilter('native')}>Native</button>
        </div>
        <select
          className="hy-select"
          data-testid="agent-skill-mount-folder-filter"
          value={skillMountFolderFilter}
          onChange={(event) => onSetSkillMountFolderFilter(event.target.value)}
        >
          <option value="all">全部文件夹</option>
          <option value="uncategorized">无需分组</option>
          {skillFolders.map((folder) => (
            <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
          ))}
        </select>
        <input
          className="hy-input"
          data-testid="agent-skill-mount-search"
          value={skillMountSearch}
          onChange={(event) => onSetSkillMountSearch(event.target.value)}
          placeholder="搜索可挂载 Skills"
        />
      </div>
      <div className="agent-skill-bulk-actions">
        <span data-testid="agent-skill-mount-visible-count">{visibleMountedCount} / {filteredMountSkills.length} 当前筛选已挂载</span>
        <button
          type="button"
          data-testid="agent-skill-mount-all-visible"
          disabled={busy || selectedAgentReadOnly || !filteredMountSkills.length || visibleMountedCount === filteredMountSkills.length}
          onClick={onMountVisibleSkills}
        >
          全选当前筛选
        </button>
        <button
          type="button"
          data-testid="agent-skill-unmount-all-visible"
          disabled={busy || selectedAgentReadOnly || !visibleMountedCount}
          onClick={onUnmountVisibleSkills}
        >
          清空当前筛选
        </button>
      </div>
      <div className="agent-skill-grid" data-testid="agent-skill-mount-grid">
        {filteredMountSkills.map((skill) => {
          const mounted = selectedSkillIdSet.has(skill.skill_id);
          return (
            <button
              type="button"
              className={mounted ? 'active' : ''}
              data-skill-id={skill.skill_id}
              data-skill-mounted={mounted ? 'true' : 'false'}
              data-testid="agent-skill-mount-item"
              disabled={busy || selectedAgentReadOnly}
              key={skill.skill_id}
              onClick={() => onToggleSkillMount(skill, mounted)}
            >
              {skill.name}
            </button>
          );
        })}
        {!filteredMountSkills.length ? <span className="agent-empty-inline">当前筛选下没有可挂载 Skill。</span> : null}
      </div>
    </div>
  );
}
