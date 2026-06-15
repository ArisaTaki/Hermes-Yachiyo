export type StudioTab = 'agents' | 'groups' | 'skills' | 'skill-groups' | 'workflows' | 'runs' | 'memory';

export const studioRouteTabs: StudioTab[] = [
  'agents',
  'groups',
  'skills',
  'skill-groups',
  'workflows',
  'runs',
  'memory',
];

export const studioTabs: StudioTab[] = [
  'agents',
  'groups',
  'skills',
  'workflows',
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
  if (item === 'agents') return 'Agents';
  if (item === 'groups') return 'Groups';
  if (item === 'skills') return 'Skill Library';
  if (item === 'workflows') return 'Workflow Studio';
  if (item === 'runs') return 'Runs';
  if (item === 'memory') return 'Memory';
  return item;
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
