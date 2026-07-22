import {
  AgentStudioLoadingState,
  isStudioTopTabActive,
  studioTabLabel,
  studioTabTestId,
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
  onPreloadTab: (tab: StudioTab) => void;
};

export function AgentStudioChrome({
  error,
  loading,
  status,
  tab,
  onActivateTab,
  onBack,
  onPreloadTab,
}: AgentStudioChromeProps) {
  const isSkillLibraryTab = tab === 'skills' || tab === 'skill-groups';
  return (
    <>
      <header className="agent-studio-hero">
        <div className="agent-studio-hero-copy">
          <span className="section-eyebrow">Oha-Yachiyo Runtime</span>
          <h1>代理工作台</h1>
          <p>管理代理、技能、工作流、工具与运行记录。</p>
        </div>
        <button type="button" className="page-back-link" onClick={onBack}>返回主控台</button>
      </header>

      <div className="agent-studio-tabs" role="tablist" aria-label="Agent Studio">
        {studioTabs.map((item) => (
          <button
            type="button"
            className={isStudioTopTabActive(tab, item) ? 'active' : ''}
            data-testid={studioTabTestId(item)}
            key={item}
            onClick={() => onActivateTab(item)}
            onFocus={() => onPreloadTab(item)}
            onMouseEnter={() => onPreloadTab(item)}
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
            data-testid={studioTabTestId('skill-groups')}
            onClick={() => onActivateTab('skill-groups')}
          >
            分组管理
          </button>
        </div>
      ) : null}
    </>
  );
}
