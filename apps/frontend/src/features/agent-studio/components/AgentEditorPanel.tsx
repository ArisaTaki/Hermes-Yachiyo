import type { ModelProfile } from '../../../lib/modelProfiles';
import type { SkillFolderSpec, SkillSpec } from '../types';
import type { AgentDraft } from '../types';
import type { ToolCatalogSnapshot } from '../../yachiyo-studio/types';
import { SettingsDisclosure } from '../../../components/SettingsDisclosure';
import {
  agentToolCapabilitySummaries,
  type AgentToolCapabilitySummary,
} from '../utils/toolCatalog';
import { AgentDeskPanel } from './AgentDeskPanel';
import { AgentSkillMountsPanel } from './AgentSkillMountsPanel';

type AgentReadinessNotice = {
  tone: 'danger' | 'warn' | 'info';
  text: string;
};

type SkillSourceFilter = 'installed' | 'native';
type SkillFolderFilter = 'all' | 'uncategorized' | string;
type AgentCapabilityToggle = {
  draftKey: keyof Pick<
    AgentDraft,
    | 'allow_screen_context'
    | 'allow_app_control'
    | 'allow_media_control'
    | 'allow_foreground_input'
    | 'allow_browser_control'
    | 'allow_terminal'
    | 'allow_workspace_read'
    | 'allow_workspace_write'
    | 'allow_artifacts'
  >;
  id: string;
  label: string;
  testId: string;
};

const agentCapabilityToggles: AgentCapabilityToggle[] = [
  {
    draftKey: 'allow_screen_context',
    id: 'screen_context',
    label: 'Screen',
    testId: 'agent-capability-screen',
  },
  {
    draftKey: 'allow_app_control',
    id: 'app_control',
    label: 'App Control',
    testId: 'agent-capability-app-control',
  },
  {
    draftKey: 'allow_media_control',
    id: 'media_control',
    label: 'Media',
    testId: 'agent-capability-media',
  },
  {
    draftKey: 'allow_foreground_input',
    id: 'foreground_input',
    label: 'Foreground Input',
    testId: 'agent-capability-foreground-input',
  },
  {
    draftKey: 'allow_browser_control',
    id: 'browser_control',
    label: 'Browser',
    testId: 'agent-capability-browser',
  },
  {
    draftKey: 'allow_terminal',
    id: 'terminal',
    label: 'Terminal',
    testId: 'agent-capability-terminal',
  },
  {
    draftKey: 'allow_workspace_read',
    id: 'workspace_read',
    label: 'Read workspace',
    testId: 'agent-capability-workspace-read',
  },
  {
    draftKey: 'allow_workspace_write',
    id: 'workspace_write',
    label: 'Write files',
    testId: 'agent-capability-workspace-write',
  },
  {
    draftKey: 'allow_artifacts',
    id: 'artifacts',
    label: 'Write artifacts',
    testId: 'agent-capability-artifacts',
  },
];

type AgentEditorPanelProps = {
  agentQuickRunDisabled: boolean;
  agentQuickRunDisabledReason: string;
  agentReadinessNotices: AgentReadinessNotice[];
  agentRunGoal: string;
  busy: boolean;
  chatModelProfiles: ModelProfile[];
  customApiKeyConfigured: boolean;
  disabledMountedSkills: SkillSpec[];
  draft: AgentDraft;
  filteredMountSkills: SkillSpec[];
  mountedSkillCount: number;
  selectedAgentDeletable: boolean;
  selectedAgentReadOnly: boolean;
  selectedSkillIds: string[];
  skillFolders: SkillFolderSpec[];
  skillMountFilter: SkillSourceFilter;
  skillMountFolderFilter: SkillFolderFilter;
  skillMountSearch: string;
  toolCatalog: ToolCatalogSnapshot | null;
  toolCatalogError: string;
  toolCatalogLoading: boolean;
  visibleMountedCount: number;
  visionModelProfiles: ModelProfile[];
  onAgentRunGoalChange: (value: string) => void;
  onDraftChange: (draft: AgentDraft) => void;
  onMountVisibleSkills: () => void;
  onOpenModelProfiles: () => void;
  onPickAgentAvatar: () => void;
  onRequestDeleteAgent: () => void;
  onRunAgent: () => void;
  onSaveAgent: () => void;
  onSetSkillMountFilter: (filter: SkillSourceFilter) => void;
  onSetSkillMountFolderFilter: (filter: SkillFolderFilter) => void;
  onSetSkillMountSearch: (query: string) => void;
  onReloadToolCatalog: () => void;
  onTestAgentModel: () => void;
  onToggleSkillMount: (skill: SkillSpec, mounted: boolean) => void;
  onUnmountVisibleSkills: () => void;
};

export function AgentEditorPanel({
  agentQuickRunDisabled,
  agentQuickRunDisabledReason,
  agentReadinessNotices,
  agentRunGoal,
  busy,
  chatModelProfiles,
  customApiKeyConfigured,
  disabledMountedSkills,
  draft,
  filteredMountSkills,
  mountedSkillCount,
  selectedAgentDeletable,
  selectedAgentReadOnly,
  selectedSkillIds,
  skillFolders,
  skillMountFilter,
  skillMountFolderFilter,
  skillMountSearch,
  toolCatalog,
  toolCatalogError,
  toolCatalogLoading,
  visibleMountedCount,
  visionModelProfiles,
  onAgentRunGoalChange,
  onDraftChange,
  onMountVisibleSkills,
  onOpenModelProfiles,
  onPickAgentAvatar,
  onRequestDeleteAgent,
  onRunAgent,
  onSaveAgent,
  onSetSkillMountFilter,
  onSetSkillMountFolderFilter,
  onSetSkillMountSearch,
  onReloadToolCatalog,
  onTestAgentModel,
  onToggleSkillMount,
  onUnmountVisibleSkills,
}: AgentEditorPanelProps) {
  const updateDraft = (patch: Partial<AgentDraft>) => onDraftChange({ ...draft, ...patch });
  const dailyDesktopToolsIncomplete = !draft.allow_screen_context
    || !draft.allow_app_control
    || !draft.allow_media_control
    || !draft.allow_browser_control;
  const enableDailyDesktopTools = () => updateDraft({
    allow_screen_context: true,
    allow_app_control: true,
    allow_media_control: true,
    allow_browser_control: true,
  });
  const toolCapabilitySummaries = agentToolCapabilitySummaries(draft, toolCatalog);
  const toolCapabilityById = new Map(
    toolCapabilitySummaries.map((summary) => [summary.id, summary]),
  );
  return (
    <form className="agent-studio-panel agent-editor" data-testid="agent-editor" onSubmit={(event) => { event.preventDefault(); onSaveAgent(); }}>
      <div className="section-heading-row">
        <h2>{draft.agent_id ? '编辑助手' : '新建助手'}</h2>
        {draft.agent_id && selectedAgentDeletable ? <button type="button" className="danger-action" data-testid="agent-delete" disabled={busy} onClick={onRequestDeleteAgent}>删除</button> : null}
      </div>
      {selectedAgentReadOnly ? <div className="agent-inline-note">系统 Agent 由 oha-yachiyo 管理，可查看但不能编辑、删除或直接挂载 Skill。</div> : null}
      <div className="agent-profile-editor">
        <AgentAvatar avatarUrl={draft.avatar_url} name={draft.nickname || draft.name || 'Agent'} />
        <div className="agent-profile-fields">
          <div className="agent-form-row">
            <label><span>名称</span><input className="hy-input" data-testid="agent-name-input" value={draft.name} onChange={(event) => updateDraft({ name: event.target.value })} readOnly={selectedAgentReadOnly} required /></label>
            <label><span>昵称</span><input className="hy-input" data-testid="agent-nickname-input" value={draft.nickname} onChange={(event) => updateDraft({ nickname: event.target.value })} readOnly={selectedAgentReadOnly} placeholder="对话框里显示的称呼" /></label>
          </div>
          <div className="agent-avatar-picker-row">
            <div>
              <span>头像</span>
              <strong>{draft.avatar_url ? '已选择自定义头像' : '使用首字母头像'}</strong>
            </div>
            <div className="agent-avatar-picker-actions">
              <button type="button" className="hy-btn hy-btn-ghost" data-testid="agent-avatar-select" disabled={busy || selectedAgentReadOnly} onClick={onPickAgentAvatar}>选择头像</button>
              {draft.avatar_url ? (
                <button type="button" className="hy-btn hy-btn-ghost" data-testid="agent-avatar-clear" disabled={busy || selectedAgentReadOnly} onClick={() => updateDraft({ avatar_url: '' })}>清除</button>
              ) : null}
            </div>
          </div>
          <label><span>用途介绍</span><input className="hy-input" data-testid="agent-description-input" value={draft.description} onChange={(event) => updateDraft({ description: event.target.value })} readOnly={selectedAgentReadOnly} /></label>
        </div>
      </div>
      <div className="agent-form-row">
        <label><span>分类</span><input className="hy-input" data-testid="agent-category-input" value={draft.category} onChange={(event) => updateDraft({ category: event.target.value })} readOnly={selectedAgentReadOnly} /></label>
      </div>
      <label>
        <span>任务说明</span>
        <textarea className="hy-input agent-textarea" data-testid="agent-instructions-input" value={draft.instructions} onChange={(event) => updateDraft({ instructions: event.target.value })} readOnly={selectedAgentReadOnly} />
        <small className="agent-field-help">写任务边界、工作方法、必须遵守的功能要求。</small>
      </label>
      <label>
        <span>说话风格</span>
        <textarea className="hy-input agent-textarea compact" data-testid="agent-persona-input" value={draft.persona_prompt} onChange={(event) => updateDraft({ persona_prompt: event.target.value })} readOnly={selectedAgentReadOnly} />
        <small className="agent-field-help">写人设、口吻、角色偏好；运行时会和功能要求分段放进 Agent context。</small>
      </label>
      <section className="agent-backend-section" aria-label="Model">
        <div className="section-heading-row compact">
          <h3>默认 AI</h3>
        </div>
        <div className="agent-backend-fields">
          <label>
            <span>对话 AI</span>
            <select
              className="hy-select"
              disabled={selectedAgentReadOnly || draft.model_mode === 'custom_api'}
              value={draft.model_profile_id}
              onChange={(event) => updateDraft({ model_profile_id: event.target.value })}
            >
              <option value="">选择已保存模型组</option>
              {chatModelProfiles.map((profile) => (
                <option key={profile.profile_id} value={profile.profile_id}>
                  {profile.name} · {profile.model || profile.provider}
                </option>
              ))}
            </select>
          </label>
        </div>
      </section>
      {!chatModelProfiles.length ? (
        <div className="notice">还没有可用的文本模型组。请先在模型配置页面新建并测试。</div>
      ) : null}
      <div className="agent-form-row">
        <label>
          <span>图片识别模型</span>
          <select className="hy-select" value={draft.vision_model_profile_id} disabled={selectedAgentReadOnly} onChange={(event) => updateDraft({ vision_model_profile_id: event.target.value })}>
            <option value="">跟随全局图片识别</option>
            {visionModelProfiles.map((profile) => (
              <option key={profile.profile_id} value={profile.profile_id}>
                {profile.name} · {profile.model || profile.provider}
              </option>
            ))}
          </select>
        </label>
        <label><span>AI 服务</span><button type="button" className="hy-btn hy-btn-ghost" onClick={onOpenModelProfiles}>管理 AI 服务</button></label>
      </div>
      {!visionModelProfiles.length ? (
        <div className="notice">还没有可用的图片识别模型组。需要图片能力时，请先在模型配置页面创建。</div>
      ) : null}
      <section className="agent-capability-box" aria-label="Capabilities">
        <div className="section-heading-row compact">
          <h3>可用能力</h3>
        </div>
        <p className="agent-section-help">开启常用桌面能力；写文件和运行命令即使开启，也仍然需要 Run 审批。</p>
        {dailyDesktopToolsIncomplete ? (
          <div className="agent-desktop-execution-notice" data-testid="agent-desktop-execution-notice">
            <div>
              <strong>日常桌面执行能力未完整开启</strong>
              <span>打开 App、播放音乐、搜索网页和读取屏幕上下文需要这些低风险能力；前台输入、点击和快捷键仍单独控制。</span>
            </div>
            <button
              type="button"
              className="hy-btn hy-btn-ghost"
              data-testid="agent-enable-daily-desktop-tools"
              disabled={busy || selectedAgentReadOnly}
              onClick={enableDailyDesktopTools}
            >
              开启日常桌面能力
            </button>
          </div>
        ) : (
          <div className="agent-desktop-execution-notice">
            <div>
              <strong>日常助手能力已开启</strong>
              <span>涉及输入、点击、文件修改或命令运行时，仍会按原有安全策略请求确认。</span>
            </div>
          </div>
        )}
      </section>
      <SettingsDisclosure
        summary="高级模型与输出"
        description="用于自定义模型连接和专业交付格式；日常使用通常不需要调整。"
        testId="agent-advanced-model-output"
      >
        <label>
          <span>Output Contract</span>
          <select className="hy-select" data-testid="agent-output-contract-select" value={draft.output_contract} disabled={selectedAgentReadOnly} onChange={(event) => updateDraft({ output_contract: event.target.value })}>
            <option value="chat">chat</option>
            <option value="markdown">markdown</option>
            <option value="diff">diff</option>
            <option value="report">report</option>
            <option value="artifacts">artifacts</option>
          </select>
          <small className="agent-field-help">约束最终交付形态；diff 不会自动写工作区，artifacts 会优先提示可保存产物。</small>
        </label>
        <div className="agent-form-row">
          <label className="agent-checkbox-row">
            <input
              type="checkbox"
              checked={draft.model_mode === 'custom_api'}
              disabled={selectedAgentReadOnly}
              onChange={(event) => updateDraft({ model_mode: event.target.checked ? 'custom_api' : 'profile' })}
            />
            <span>Custom API</span>
          </label>
        </div>
        {draft.model_mode === 'custom_api' ? (
          <div className="agent-config-box">
            <label><span>Model</span><input className="hy-input" value={draft.model} onChange={(event) => updateDraft({ model: event.target.value })} readOnly={selectedAgentReadOnly} placeholder="gpt-4.1-mini" /></label>
            <label><span>Base URL</span><input className="hy-input" value={draft.base_url} onChange={(event) => updateDraft({ base_url: event.target.value })} readOnly={selectedAgentReadOnly} placeholder="https://api.example.com/v1" /></label>
            <label><span>API Key</span><input className="hy-input" type="password" value={draft.api_key} onChange={(event) => updateDraft({ api_key: event.target.value })} readOnly={selectedAgentReadOnly} placeholder={customApiKeyConfigured ? '已配置，留空不覆盖' : '保存到后端'} /></label>
          </div>
        ) : null}
      </SettingsDisclosure>
      <SettingsDisclosure
        summary="精细能力与安全策略"
        description="逐项控制工具、审批和权限映射，适合需要严格边界的专业助手。"
        testId="agent-advanced-capabilities"
      >
        <div className="agent-capability-grid">
          {agentCapabilityToggles.map((capability) => {
            const summary = toolCapabilityById.get(capability.id);
            const checked = Boolean(draft[capability.draftKey]);
            const nextPatch = (enabled: boolean): Partial<AgentDraft> => {
              if (capability.draftKey === 'allow_workspace_write') {
                return {
                  allow_workspace_read: enabled ? true : draft.allow_workspace_read,
                  allow_workspace_write: enabled,
                };
              }
              return { [capability.draftKey]: enabled } as Partial<AgentDraft>;
            };
            return (
              <label
                className={checked ? 'agent-capability-toggle enabled' : 'agent-capability-toggle'}
                data-capability-id={capability.id}
                data-testid={capability.testId}
                key={capability.id}
              >
                <span className="agent-capability-toggle-head">
                  <input
                    type="checkbox"
                    checked={checked}
                    disabled={selectedAgentReadOnly}
                    onChange={(event) => updateDraft(nextPatch(event.target.checked))}
                  />
                  <strong>{summary?.label || capability.label}</strong>
                </span>
                <span className="agent-capability-toggle-tools">
                  {(summary?.tools || []).join(', ') || '暂无工具'}
                </span>
                <span className="agent-capability-toggle-meta">
                  <span className={`studio-tool-risk ${summary?.riskLevel || 'unknown'}`}>
                    {summary?.riskLevel || 'unknown'}
                  </span>
                  {summary?.approvalRequired ? <span className="agent-policy-pill warn">approval</span> : null}
                  <span className={checked ? 'agent-policy-pill on' : 'agent-policy-pill'}>{checked ? 'on' : 'off'}</span>
                </span>
                {summary?.missingPermissions.length ? (
                  <em>Missing: {summary.missingPermissions.join(', ')}</em>
                ) : null}
              </label>
            );
          })}
        </div>
        {agentReadinessNotices.length ? (
          <div className="agent-readiness-list" aria-label="Agent 运行状态">
            {agentReadinessNotices.map((notice) => (
              <span className={notice.tone} key={notice.text}>{notice.text}</span>
            ))}
          </div>
        ) : null}
        <AgentToolPolicyPreview
          error={toolCatalogError}
          loading={toolCatalogLoading}
          summaries={toolCapabilitySummaries}
          onReload={onReloadToolCatalog}
        />
      </SettingsDisclosure>
      <SettingsDisclosure
        summary="工作区访问范围"
        description="限定助手可以读取和写入的本地目录；保留默认值即可获得隔离工作区。"
        testId="agent-advanced-workspace"
      >
        <div className="agent-form-row">
          <label>
            <span>Default Workdir</span>
            <input className="hy-input" value={draft.default_workdir} onChange={(event) => updateDraft({ default_workdir: event.target.value })} readOnly={selectedAgentReadOnly} placeholder="保存后自动分配独立目录" />
            <small className="agent-field-help">工具相对路径的基准目录；留空时保存后自动分配到 Yachiyo 的 Agent 工作区。</small>
          </label>
          <label>
            <span>Writable Scopes</span>
            <input className="hy-input" value={draft.writable_scopes} onChange={(event) => updateDraft({ writable_scopes: event.target.value })} readOnly={selectedAgentReadOnly} placeholder="src, tests" />
            <small className="agent-field-help">允许 `workspace.write_patch` 写入的相对目录，逗号分隔。</small>
          </label>
        </div>
        <label>
          <span>Readable Scopes</span>
          <input className="hy-input" value={draft.readable_scopes} onChange={(event) => updateDraft({ readable_scopes: event.target.value })} readOnly={selectedAgentReadOnly} />
          <small className="agent-field-help">允许 `workspace.list/read` 访问的相对目录，默认 `.` 表示工作区内可读。</small>
        </label>
      </SettingsDisclosure>
      {draft.agent_id ? (
        <AgentDeskPanel
          agentId={draft.agent_id}
          busy={busy}
          selectedAgentReadOnly={selectedAgentReadOnly}
        />
      ) : null}
      <div className="agent-inline-note">保存后可先测试 AI 连接，再用“试运行”检查实际效果。权限与工作区范围仍会在运行时强制校验。</div>
      <div className="agent-editor-actions">
        <button type="submit" className="primary-action" data-testid="agent-save" disabled={busy || selectedAgentReadOnly}>保存 Agent</button>
        {draft.agent_id ? <button type="button" disabled={busy || selectedAgentReadOnly} onClick={onTestAgentModel}>测试模型</button> : null}
      </div>
      {draft.agent_id ? (
        <section className="agent-quick-run">
          <div>
            <h3>试运行</h3>
            <p>让当前助手立即完成一个小任务，结束后自动打开详情。</p>
          </div>
          <label>
            <span>要做的事</span>
            <textarea
              className="hy-input agent-run-textarea"
              value={agentRunGoal}
              disabled={selectedAgentReadOnly}
              onChange={(event) => onAgentRunGoalChange(event.target.value)}
              placeholder="例如：检查这个页面还有哪些交互缺口"
            />
          </label>
          {agentQuickRunDisabledReason && agentRunGoal.trim() ? (
            <div className="agent-inline-note warn">{agentQuickRunDisabledReason}</div>
          ) : null}
          <button
            type="button"
            className="primary-action"
            disabled={agentQuickRunDisabled}
            title={agentQuickRunDisabledReason || undefined}
            onClick={onRunAgent}
          >
            运行当前助手
          </button>
        </section>
      ) : (
        <div className="agent-inline-note">保存 Agent 后即可在这里直接运行，并在 Runs 中查看结果和 artifacts。</div>
      )}
      {draft.agent_id ? (
        <AgentSkillMountsPanel
          busy={busy}
          disabledMountedSkills={disabledMountedSkills}
          filteredMountSkills={filteredMountSkills}
          mountedSkillCount={mountedSkillCount}
          selectedAgentReadOnly={selectedAgentReadOnly}
          selectedSkillIds={selectedSkillIds}
          skillFolders={skillFolders}
          skillMountFilter={skillMountFilter}
          skillMountFolderFilter={skillMountFolderFilter}
          skillMountSearch={skillMountSearch}
          visibleMountedCount={visibleMountedCount}
          onMountVisibleSkills={onMountVisibleSkills}
          onSetSkillMountFilter={onSetSkillMountFilter}
          onSetSkillMountFolderFilter={onSetSkillMountFolderFilter}
          onSetSkillMountSearch={onSetSkillMountSearch}
          onToggleSkillMount={onToggleSkillMount}
          onUnmountVisibleSkills={onUnmountVisibleSkills}
        />
      ) : null}
    </form>
  );
}

function AgentToolPolicyPreview({
  error,
  loading,
  summaries,
  onReload,
}: {
  error: string;
  loading: boolean;
  summaries: AgentToolCapabilitySummary[];
  onReload: () => void;
}) {
  return (
    <div className="agent-tool-policy-preview" data-testid="agent-tool-policy-preview">
      <div className="section-heading-row compact">
        <div>
          <h3>Tool Policy Preview</h3>
          <span>{loading ? '同步工具目录中' : `${summaries.filter((summary) => summary.enabled).length} 个能力已启用`}</span>
        </div>
        <button type="button" className="hy-btn hy-btn-ghost" disabled={loading} onClick={onReload}>刷新</button>
      </div>
      {error ? <div className="agent-inline-note warn">{error}</div> : null}
      <div className="agent-tool-policy-list">
        {summaries.map((summary) => (
          <div
            className={summary.enabled ? 'agent-tool-policy-row enabled' : 'agent-tool-policy-row'}
            key={summary.id}
          >
            <div className="agent-tool-policy-main">
              <strong>{summary.label}</strong>
              <span>{summary.tools.join(', ')}</span>
              {summary.missingPermissions.length ? (
                <em>Missing: {summary.missingPermissions.join(', ')}</em>
              ) : null}
            </div>
            <div className="agent-tool-policy-meta">
              <span className={`studio-tool-risk ${summary.riskLevel}`}>{summary.riskLevel}</span>
              {summary.approvalRequired ? <span className="agent-policy-pill warn">approval</span> : null}
              <span className={summary.enabled ? 'agent-policy-pill on' : 'agent-policy-pill'}>{summary.enabled ? 'on' : 'off'}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}

function AgentAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }) {
  const clean = name.trim();
  return (
    <span className={avatarUrl ? 'agent-avatar has-image' : 'agent-avatar'} aria-hidden="true">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : clean ? clean.slice(0, 1).toUpperCase() : 'A'}
    </span>
  );
}
