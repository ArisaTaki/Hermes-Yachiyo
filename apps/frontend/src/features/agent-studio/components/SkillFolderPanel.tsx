import type { SkillFolderSpec } from '../types';
import { skillFolderNameMaxLength } from '../utils/skills';

type SkillFolderDeleteMode = 'folder' | 'skills';

type SkillFolderStats = {
  installed: number;
  native: number;
  total: number;
};

type SkillFolderPanelProps = {
  busy: boolean;
  editingSkillFolderError: string;
  editingSkillFolderId: string;
  editingSkillFolderName: string;
  newSkillFolderError: string;
  newSkillFolderName: string;
  skillFolderDeleteModes: Record<string, SkillFolderDeleteMode>;
  skillFolders: SkillFolderSpec[];
  ungroupedSkillStats: SkillFolderStats;
  onCancelEditingSkillFolder: () => void;
  onCreateSkillFolder: () => void;
  onDeleteSkillFolder: (folder: SkillFolderSpec, deleteWithSkills: boolean) => void;
  onEditingSkillFolderNameChange: (name: string) => void;
  onNewSkillFolderNameChange: (name: string) => void;
  onOpenSkillLibraryFolder: (folder: SkillFolderSpec) => void;
  onSetSkillFolderDeleteMode: (folderId: string, mode: SkillFolderDeleteMode) => void;
  onStartEditingSkillFolder: (folder: SkillFolderSpec) => void;
  onUpdateSkillFolder: (folderId: string) => void;
};

export function SkillFolderPanel({
  busy,
  editingSkillFolderError,
  editingSkillFolderId,
  editingSkillFolderName,
  newSkillFolderError,
  newSkillFolderName,
  skillFolderDeleteModes,
  skillFolders,
  ungroupedSkillStats,
  onCancelEditingSkillFolder,
  onCreateSkillFolder,
  onDeleteSkillFolder,
  onEditingSkillFolderNameChange,
  onNewSkillFolderNameChange,
  onOpenSkillLibraryFolder,
  onSetSkillFolderDeleteMode,
  onStartEditingSkillFolder,
  onUpdateSkillFolder,
}: SkillFolderPanelProps) {
  return (
    <section className="agent-studio-grid skill-group-page" data-testid="skill-folder-page">
      <aside className="agent-studio-panel">
        <div className="section-heading-row">
          <h2>Skill 分组</h2>
        </div>
        <p className="agent-section-help">
          文件夹只用于筛选、导入目标和 Agent 挂载选择，不会移动 Native Skill Library 原始路径。
        </p>
        <div className="skill-folder-box">
          <div className="section-heading-row compact">
            <h3>新建文件夹</h3>
          </div>
          <div className="skill-folder-create">
            <input
              className="hy-input"
              data-testid="skill-folder-name-input"
              maxLength={skillFolderNameMaxLength + 1}
              value={newSkillFolderName}
              onChange={(event) => onNewSkillFolderNameChange(event.target.value)}
              placeholder="例如 Laravel / Design"
            />
            <button
              type="button"
              data-testid="skill-folder-create"
              disabled={busy || !newSkillFolderName.trim() || Boolean(newSkillFolderError)}
              onClick={onCreateSkillFolder}
            >
              新建
            </button>
          </div>
          {newSkillFolderError ? <small className="skill-folder-validation">{newSkillFolderError}</small> : null}
        </div>
        <div className="skill-folder-system-row">
          <strong>无需分组</strong>
          <div className="skill-folder-meta">
            <span>{ungroupedSkillStats.total} skills</span>
            <span>{ungroupedSkillStats.installed} Installed</span>
            <span>{ungroupedSkillStats.native} Native</span>
          </div>
          <small>默认分组，不能删除；删除其他文件夹后 Skill 会回到这里。</small>
        </div>
      </aside>
      <div className="agent-studio-panel">
        <div className="section-heading-row">
          <h2>文件夹管理</h2>
          <span className="agent-section-count">{skillFolders.length} folders</span>
        </div>
        <div className="skill-folder-manager-list" data-testid="skill-folder-list">
          {skillFolders.map((folder) => {
            const editing = editingSkillFolderId === folder.folder_id;
            const deleteMode = skillFolderDeleteModes[folder.folder_id] || 'folder';
            const deleteWithSkills = deleteMode === 'skills' && Boolean(folder.skill_count || 0);
            return (
              <article
                className="skill-folder-manager-row"
                data-folder-id={folder.folder_id}
                data-folder-name={folder.name}
                data-testid="skill-folder-row"
                key={folder.folder_id}
              >
                <div className="skill-folder-manager-main">
                  {editing ? (
                    <input
                      className="hy-input"
                      data-testid="skill-folder-edit-name-input"
                      maxLength={skillFolderNameMaxLength + 1}
                      value={editingSkillFolderName}
                      onChange={(event) => onEditingSkillFolderNameChange(event.target.value)}
                      autoFocus
                    />
                  ) : (
                    <>
                      <h3>{folder.name}</h3>
                      <div className="skill-folder-meta">
                        <span>{folder.skill_count || 0} skills</span>
                        <span>{folder.installed_count || 0} Installed</span>
                        <span>{folder.native_count || 0} Native</span>
                      </div>
                    </>
                  )}
                </div>
                <div className="skill-folder-actions">
                  {editing ? (
                    <>
                      <button
                        type="button"
                        data-testid="skill-folder-save-rename"
                        disabled={busy || !editingSkillFolderName.trim() || Boolean(editingSkillFolderError)}
                        onClick={() => onUpdateSkillFolder(folder.folder_id)}
                      >
                        保存
                      </button>
                      <button
                        type="button"
                        data-testid="skill-folder-cancel-rename"
                        disabled={busy}
                        onClick={onCancelEditingSkillFolder}
                      >
                        取消
                      </button>
                    </>
                  ) : (
                    <>
                      <button
                        type="button"
                        data-testid="skill-folder-rename"
                        disabled={busy}
                        onClick={() => onStartEditingSkillFolder(folder)}
                      >
                        重命名
                      </button>
                      <button
                        type="button"
                        data-testid="skill-folder-open"
                        disabled={busy}
                        onClick={() => onOpenSkillLibraryFolder(folder)}
                      >
                        查看
                      </button>
                      <div className="skill-folder-delete-control" aria-label={`${folder.name} 删除设置`}>
                        <label
                          className="skill-folder-delete-switch"
                          title="开启后删除文件夹时会连带删除其中 Skills"
                        >
                          <input
                            type="checkbox"
                            data-testid="skill-folder-delete-with-skills"
                            role="switch"
                            checked={deleteWithSkills}
                            disabled={busy || !(folder.skill_count || 0)}
                            aria-label={`${folder.name} 删除时连带删除 Skills`}
                            onChange={(event) => (
                              onSetSkillFolderDeleteMode(
                                folder.folder_id,
                                event.currentTarget.checked ? 'skills' : 'folder',
                              )
                            )}
                          />
                          <span className="skill-folder-delete-toggle" aria-hidden="true" />
                          <span>连带 Skills</span>
                        </label>
                        <button
                          type="button"
                          className="danger-action"
                          data-testid="skill-folder-delete"
                          disabled={busy}
                          onClick={() => onDeleteSkillFolder(folder, deleteWithSkills)}
                        >
                          删除
                        </button>
                      </div>
                    </>
                  )}
                </div>
                {editing && editingSkillFolderError ? (
                  <small className="skill-folder-validation">{editingSkillFolderError}</small>
                ) : null}
              </article>
            );
          })}
          {!skillFolders.length ? (
            <div className="empty-state inline-empty skill-folder-empty-state">
              <strong>暂无自定义文件夹</strong>
              <span>现有 Skill 会继续显示在“无需分组”里。</span>
            </div>
          ) : null}
        </div>
      </div>
    </section>
  );
}
