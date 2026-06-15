import type { SkillFolderSpec, SkillSpec } from '../types';
import {
  skillPathLabel,
  skillSourceLabel,
  skillSourceTypeLabel,
} from '../utils/skills';

type SkillCardProps = {
  busy: boolean;
  folders: SkillFolderSpec[];
  managing: boolean;
  onDelete: () => Promise<void> | void;
  onMoveFolder: (folderId: string) => Promise<void> | void;
  onOpenLocation: () => Promise<void> | void;
  onSelectionChange: () => void;
  onToggleEnabled: () => Promise<void> | void;
  selected: boolean;
  skill: SkillSpec;
};

export function SkillCard({
  busy,
  folders,
  managing,
  onDelete,
  onMoveFolder,
  onOpenLocation,
  onSelectionChange,
  onToggleEnabled,
  selected,
  skill,
}: SkillCardProps) {
  const enabled = skill.enabled !== false;
  const cardClassName = [
    'skill-card',
    enabled ? '' : 'disabled',
    managing ? 'managing' : '',
  ].filter(Boolean).join(' ');
  return (
    <article
      className={cardClassName}
      data-skill-enabled={enabled ? 'true' : 'false'}
      data-skill-folder-id={skill.folder_id || ''}
      data-skill-id={skill.skill_id}
      data-testid="skill-card"
    >
      <div className="section-heading-row skill-card-head">
        <div className="skill-card-title">
          <label className="skill-card-select" aria-label={`选择 Skill ${skill.name}`}>
            <input
              type="checkbox"
              data-testid="skill-card-select"
              checked={selected}
              disabled={busy || !managing}
              onChange={onSelectionChange}
            />
          </label>
          <div>
            <h3>{skill.name}</h3>
            <span className="skill-source-tag">{skillSourceTypeLabel(skill.source_type)}</span>
          </div>
        </div>
        <label className={enabled ? 'skill-enable-switch active' : 'skill-enable-switch'}>
          <input
            type="checkbox"
            data-testid="skill-card-enabled-toggle"
            checked={enabled}
            disabled={busy}
            onChange={() => void onToggleEnabled()}
          />
          <span aria-hidden="true" />
        </label>
      </div>
      <p>{skill.description || skill.content_summary}</p>
      <label className="skill-card-folder">
        <span>文件夹</span>
        <select
          className="hy-select"
          data-testid="skill-card-folder-select"
          value={skill.folder_id || ''}
          disabled={busy}
          onChange={(event) => void onMoveFolder(event.target.value)}
        >
          <option value="">无需分组</option>
          {folders.map((folder) => (
            <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
          ))}
        </select>
      </label>
      <div className="skill-card-path">
        <span>路径</span>
        <code>{skillPathLabel(skill)}</code>
      </div>
      {skillSourceLabel(skill) ? (
        <div className="skill-card-path">
          <span>来源</span>
          <code>{skillSourceLabel(skill)}</code>
        </div>
      ) : null}
      {skill.asset_paths?.length ? <small>{skill.asset_paths.length} assets/templates</small> : null}
      <div className="skill-card-actions">
        <button
          type="button"
          data-testid="skill-card-open-location"
          disabled={busy || !skill.local_path}
          onClick={() => void onOpenLocation()}
        >
          打开路径
        </button>
        <button
          type="button"
          className="danger-action"
          data-testid="skill-card-delete"
          disabled={busy}
          onClick={() => void onDelete()}
        >
          删除
        </button>
      </div>
      <pre>{(skill.skill_markdown || '').slice(0, 1200)}</pre>
    </article>
  );
}
