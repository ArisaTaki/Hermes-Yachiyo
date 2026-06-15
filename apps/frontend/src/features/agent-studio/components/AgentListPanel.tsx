import type { AgentSpec } from '../types';

type AgentListPanelProps = {
  agents: AgentSpec[];
  agentManagementMode: boolean;
  allAgentsSelected: boolean;
  busy: boolean;
  deletableAgentIds: string[];
  selectedAgentId: string;
  selectedAgentIdSet: Set<string>;
  selectedAgentCount: number;
  selectedDeletableAgentCount: number;
  onClearSelection: () => void;
  onFinishManagement: () => void;
  onRequestDeleteSelectedAgents: () => void;
  onSelectAgent: (agentId: string) => void;
  onSetAgentManagementMode: (enabled: boolean) => void;
  onSetSelectedAgentIds: (agentIds: string[]) => void;
  onStartNewAgent: () => void;
  onToggleAgentSelected: (agentId: string) => void;
};

export function AgentListPanel({
  agents,
  agentManagementMode,
  allAgentsSelected,
  busy,
  deletableAgentIds,
  selectedAgentId,
  selectedAgentIdSet,
  selectedAgentCount,
  selectedDeletableAgentCount,
  onClearSelection,
  onFinishManagement,
  onRequestDeleteSelectedAgents,
  onSelectAgent,
  onSetAgentManagementMode,
  onSetSelectedAgentIds,
  onStartNewAgent,
  onToggleAgentSelected,
}: AgentListPanelProps) {
  return (
    <aside className="agent-studio-panel">
      <div className="section-heading-row">
        <h2>Agents</h2>
        <div className="studio-heading-actions">
          {agents.length && !agentManagementMode ? (
            <button type="button" data-testid="agent-management-toggle" disabled={busy} onClick={() => onSetAgentManagementMode(true)}>管理</button>
          ) : null}
          <button type="button" data-testid="agent-new" disabled={busy} onClick={onStartNewAgent}>新建</button>
        </div>
      </div>
      {agents.length && agentManagementMode ? (
        <div className="studio-bulk-actions" aria-label="Agent 批量操作">
          <span>{selectedAgentCount ? `已选择 ${selectedAgentCount} / ${agents.length}` : `${agents.length} agents`}</span>
          <button type="button" data-testid="agent-select-all" disabled={busy || !deletableAgentIds.length} onClick={() => onSetSelectedAgentIds(allAgentsSelected ? [] : deletableAgentIds)}>
            {allAgentsSelected ? '取消全选' : '全选当前列表'}
          </button>
          <button type="button" data-testid="agent-clear-selection" disabled={busy || !selectedAgentCount} onClick={onClearSelection}>清空</button>
          <button type="button" className="danger-action" data-testid="agent-delete-selected" disabled={busy || !selectedDeletableAgentCount} onClick={onRequestDeleteSelectedAgents}>删除所选</button>
          <button type="button" data-testid="agent-management-done" disabled={busy} onClick={onFinishManagement}>完成</button>
        </div>
      ) : null}
      <div className={agentManagementMode ? 'agent-list managing' : 'agent-list'} data-testid="agent-list">
        {agents.map((agent) => (
          <div
            className={agent.agent_id === selectedAgentId ? 'agent-list-item active' : 'agent-list-item'}
            data-agent-id={agent.agent_id}
            data-agent-deletable={!agent.system && agent.deletable !== false ? 'true' : 'false'}
            data-testid="agent-list-item"
            key={agent.agent_id}
          >
            <label className="agent-list-select" aria-label={`选择 Agent ${agent.nickname || agent.name}`}>
              <input
                type="checkbox"
                data-testid="agent-list-select-checkbox"
                checked={selectedAgentIdSet.has(agent.agent_id)}
                disabled={busy || !agentManagementMode || agent.system || agent.deletable === false}
                onChange={() => onToggleAgentSelected(agent.agent_id)}
              />
            </label>
            <button
              type="button"
              className="agent-list-main"
              data-testid="agent-list-open"
              onClick={() => onSelectAgent(agent.agent_id)}
            >
              <span className="agent-list-profile">
                <AgentAvatar avatarUrl={agent.avatar_url} name={agent.nickname || agent.name} />
                <span>
                  <strong className="agent-list-name">{agent.nickname || agent.name}</strong>
                  <small className="agent-list-base-name">{agent.name}</small>
                </span>
              </span>
              <span className="agent-list-meta">
                <span className="agent-list-category">{agent.category || 'custom'}</span>
                <span className="agent-list-separator">·</span>
                <span className="agent-list-profile-type">{agent.model_mode === 'custom_api' ? 'Custom API' : 'Chat Profile'}</span>
              </span>
            </button>
          </div>
        ))}
        {!agents.length ? <span className="agent-empty-inline">暂无 Agent。点击“新建”创建一个 Agent。</span> : null}
      </div>
    </aside>
  );
}

function AgentAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }) {
  return (
    <span className="agent-avatar">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : (name || 'A').slice(0, 1)}
    </span>
  );
}
