import {
  AgentStudioLoadingState,
  isStudioTopTabActive,
  studioTabLabel,
  studioTabs,
  type StudioTab,
} from '../studioTabs';

type AgentStudioChromeProps = {
  error: string;
  loading: boolean;
  status: string;
  tab: StudioTab;
  onActivateTab: (tab: StudioTab) => void;
  onBack: () => void;
};

export function AgentStudioChrome({
  error,
  loading,
  status,
  tab,
  onActivateTab,
  onBack,
}: AgentStudioChromeProps) {
  const isSkillLibraryTab = tab === 'skills' || tab === 'skill-groups';
  return (
    <>
      <header className="agent-studio-hero">
        <button type="button" className="page-back-link" onClick={onBack}>← 返回主控台</button>
        <div>
          <span className="section-eyebrow">Agent Runtime</span>
          <h1>Agent Studio</h1>
          <p>创建可配置 Agent，导入本地 Skills，并用线性 Workflow 把多个 Agent 编排成可运行链路。</p>
        </div>
      </header>

      <div className="agent-studio-tabs" role="tablist" aria-label="Agent Studio">
        {studioTabs.map((item) => (
          <button
            type="button"
            className={isStudioTopTabActive(tab, item) ? 'active' : ''}
            key={item}
            onClick={() => onActivateTab(item)}
          >
            {studioTabLabel(item)}
          </button>
        ))}
      </div>

      {loading ? <AgentStudioLoadingState /> : null}
      {status ? <div className="notice">{status}</div> : null}
      {error ? <div className="notice danger">{error}</div> : null}

      {!loading && isSkillLibraryTab ? (
        <div className="skill-library-subnav" role="tablist" aria-label="Skill Library">
          <button
            type="button"
            className={tab === 'skills' ? 'active' : ''}
            onClick={() => onActivateTab('skills')}
          >
            Skills 列表
          </button>
          <button
            type="button"
            className={tab === 'skill-groups' ? 'active' : ''}
            onClick={() => onActivateTab('skill-groups')}
          >
            分组管理
          </button>
        </div>
      ) : null}
    </>
  );
}
