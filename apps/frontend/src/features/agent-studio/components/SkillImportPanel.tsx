import type { DragEvent } from 'react';

import type { SkillFolderSpec, SkillSourceRoot } from '../../../lib/agents';
import {
  skillResultStatusLabel,
  skillSourceTypeLabel,
  type SkillImportResult,
} from '../utils/skills';

type SkillImportPanelProps = {
  busy: boolean;
  installingSkill: boolean;
  skillFolders: SkillFolderSpec[];
  skillImportResults: SkillImportResult[];
  skillInstallCommand: string;
  skillSources: SkillSourceRoot[];
  skillTargetFolderId: string;
  onDropSkillSources: (event: DragEvent<HTMLElement>) => void;
  onInstallSkill: () => void;
  onPickSkillSources: () => void;
  onSetSkillInstallCommand: (command: string) => void;
  onSetSkillTargetFolderId: (folderId: string) => void;
  onSyncNativeSkillLibrary: () => void;
};

export function SkillImportPanel({
  busy,
  installingSkill,
  skillFolders,
  skillImportResults,
  skillInstallCommand,
  skillSources,
  skillTargetFolderId,
  onDropSkillSources,
  onInstallSkill,
  onPickSkillSources,
  onSetSkillInstallCommand,
  onSetSkillTargetFolderId,
  onSyncNativeSkillLibrary,
}: SkillImportPanelProps) {
  return (
    <div className="agent-studio-panel skill-import-panel" data-testid="skill-import-panel">
      <div className="section-heading-row">
        <h2>Installed Skills</h2>
      </div>
      <p className="agent-section-help">
        从安装命令或上传入口导入的 Skills 会进入 Installed Skill 管理区；
        它们和 Native Skill Library 分开展示和挂载。
      </p>
      <div className="skill-import-target">
        <label>
          <span>导入到文件夹</span>
          <select
            className="hy-select"
            data-testid="skill-import-folder-select"
            value={skillTargetFolderId}
            onChange={(event) => onSetSkillTargetFolderId(event.target.value)}
          >
            <option value="">无需分组</option>
            {skillFolders.map((folder) => (
              <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
            ))}
          </select>
        </label>
        <small>需要新增、重命名或删除文件夹时，进入上方“分组管理”。</small>
      </div>
      <div className="skill-install-box">
        <label>
          <span>Skill 来源或安装命令</span>
          <input
            className="hy-input"
            data-testid="skill-install-command-input"
            value={skillInstallCommand}
            onChange={(event) => onSetSkillInstallCommand(event.target.value)}
            placeholder="owner/repo --skill skill-name 或 skills@latest add owner/repo"
          />
        </label>
        {installingSkill ? (
          <div className="skill-install-progress" role="progressbar" aria-label="Skill 安装进度">
            <span />
          </div>
        ) : null}
        <button
          type="button"
          data-testid="skill-install-command-submit"
          disabled={busy || !skillInstallCommand.trim()}
          onClick={onInstallSkill}
        >
          {installingSkill ? '安装中...' : '安装并同步'}
        </button>
        <small>
          可以直接输入 Skill 来源，也可以输入 <code>skills@latest add ...</code>
          {' '}或 <code>npx skills add ...</code>。
          Oha-Yachiyo 会固定使用 <code>oha-yachiyo</code> 目标并补上 <code>--copy -y</code>，
          在 Installed Skill 工作区执行，不写入 Native 全局库。
        </small>
      </div>
      <div className="section-heading-row"><h2>上传 Skills</h2></div>
      <p className="agent-section-help">
        支持批量上传 zip 技能包，也支持选择本地 Skill 目录；
        导入后会复制到 Installed Skill 管理区。
      </p>
      <div className="skill-import-hints">
        <span>一次上传多个 zip</span>
        <span>自动校验 SKILL.md</span>
        <span>跳过重复选择</span>
      </div>
      <div
        className="skill-drop-zone"
        onDragOver={(event) => event.preventDefault()}
        onDrop={onDropSkillSources}
      >
        <strong>拖拽 Skill 目录或 zip 到这里</strong>
        <span>也可以点击选择文件，选择后会立即校验并导入</span>
        <button
          type="button"
          data-testid="skill-source-picker"
          disabled={busy}
          onClick={onPickSkillSources}
        >
          上传 Skills
        </button>
      </div>
      <div className="section-heading-row">
        <h2>Native Skill Library</h2>
        <button
          type="button"
          data-testid="skill-native-sync"
          disabled={busy}
          onClick={onSyncNativeSkillLibrary}
        >
          从 Native Library 同步
        </button>
      </div>
      <p className="agent-section-help">
        Native Skill Library 的 `~/.oha-yachiyo/skill-library/skills` 只登记引用，
        不复制到 Installed Skill 管理区；项目级 Skills 暂不纳入本页管理。
      </p>
      <div className="skill-source-roots">
        {skillSources.map((source) => (
          <div
            className={source.exists ? 'skill-source-root' : 'skill-source-root missing'}
            data-testid="skill-source-root"
            key={`${source.source_type}-${source.path}`}
          >
            <strong>{skillSourceTypeLabel(source.source_type)}</strong>
            <span>{source.skill_count || 0} skills</span>
            <code>{source.path}</code>
          </div>
        ))}
        {!skillSources.length ? (
          <div className="empty-state inline-empty">暂未检测到 Native skills root。</div>
        ) : null}
      </div>
      {skillImportResults.length ? (
        <div className="skill-import-results" aria-label="Skill import results" data-testid="skill-import-results">
          {skillImportResults.map((result) => (
            <div
              className={`skill-import-result ${result.status}`}
              data-testid="skill-import-result"
              key={`${result.source}-${result.status}`}
            >
              <strong>{skillResultStatusLabel(result.status)}</strong>
              <span>{result.source}</span>
              <small>{result.message}</small>
            </div>
          ))}
        </div>
      ) : null}
    </div>
  );
}
