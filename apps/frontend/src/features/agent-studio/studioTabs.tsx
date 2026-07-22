export type StudioTab = 'agents' | 'groups' | 'skills' | 'skill-groups' | 'workflows' | 'tools' | 'runs' | 'memory';

export const studioRouteTabs: StudioTab[] = [
  'agents',
  'groups',
  'skills',
  'skill-groups',
  'workflows',
  'tools',
  'runs',
  'memory',
];

export const studioTabs: StudioTab[] = [
  'agents',
  'groups',
  'skills',
  'workflows',
  'tools',
  'runs',
  'memory',
];

export function normalizeStudioTab(value: string): StudioTab {
  return studioRouteTabs.includes(value as StudioTab) ? value as StudioTab : 'agents';
}

export function isStudioTopTabActive(currentTab: StudioTab, item: StudioTab): boolean {
  if (item === 'skills') return currentTab === 'skills' || currentTab === 'skill-groups';
  return currentTab === item;
}

export function studioTabLabel(item: StudioTab): string {
  if (item === 'agents') return '代理';
  if (item === 'groups') return '群组';
  if (item === 'skills') return '技能库';
  if (item === 'workflows') return '工作流';
  if (item === 'tools') return '工具';
  if (item === 'runs') return '运行';
  if (item === 'memory') return '记忆';
  return item;
}

export function studioTabTestId(item: StudioTab): string {
  if (item === 'agents') return 'agent-studio-tab-agents';
  if (item === 'groups') return 'agent-studio-tab-groups';
  if (item === 'skills') return 'agent-studio-tab-skills';
  if (item === 'skill-groups') return 'agent-studio-tab-skill-groups';
  if (item === 'workflows') return 'agent-studio-tab-workflows';
  if (item === 'tools') return 'agent-studio-tab-tools';
  if (item === 'runs') return 'agent-studio-tab-runs';
  return 'agent-studio-tab-memory';
}

export function AgentStudioLoadingState() {
  return (
    <section className="agent-studio-grid agent-studio-loading" aria-label="正在读取 Agent Studio">
      <aside className="agent-studio-panel">
        <div className="section-heading-row">
          <span className="agent-studio-skeleton-line title" />
          <span className="agent-studio-skeleton-button" />
        </div>
        <div className="agent-studio-skeleton-list">
          {Array.from({ length: 5 }).map((_, index) => (
            <div className="agent-studio-skeleton-card" key={index}>
              <span className="agent-studio-skeleton-avatar" />
              <span className="agent-studio-skeleton-stack">
                <span className="agent-studio-skeleton-line name" />
                <span className="agent-studio-skeleton-line meta" />
              </span>
            </div>
          ))}
        </div>
      </aside>
      <div className="agent-studio-panel">
        <div className="section-heading-row">
          <span className="agent-studio-skeleton-line title wide" />
        </div>
        <div className="agent-studio-skeleton-form">
          <span className="agent-studio-skeleton-avatar large" />
          <span className="agent-studio-skeleton-line field" />
          <span className="agent-studio-skeleton-line field" />
          <span className="agent-studio-skeleton-line field wide" />
          <span className="agent-studio-skeleton-block" />
          <span className="agent-studio-skeleton-block short" />
        </div>
      </div>
    </section>
  );
}
