import type { AgentSpec } from '../types';
import type {
  AgentGroupSnapshot,
  GroupRunSnapshot,
} from '../../yachiyo-studio/types';
import {
  agentGroupListMeta,
  agentGroupMemberSummary,
  agentGroupSaveDisabled,
  agentInitial,
} from '../utils/groups';
import { GroupRunPanel } from './GroupRunPanel';

type AgentGroupPanelProps = {
  agents: AgentSpec[];
  agentGroups: AgentGroupSnapshot[];
  agentGroupMemoryScope: string;
  agentGroupMemberIds: string[];
  agentGroupMode: string;
  agentGroupName: string;
  agentGroupRunGoal: string;
  busy: boolean;
  latestAgentGroupRun: GroupRunSnapshot | null;
  selectedAgentGroup: AgentGroupSnapshot | null;
  selectedAgentGroupId: string;
  onAgentGroupMemoryScopeChange: (value: string) => void;
  onAgentGroupModeChange: (value: string) => void;
  onAgentGroupNameChange: (value: string) => void;
  onAgentGroupRunGoalChange: (value: string) => void;
  onOpenAgentGroupRunTimeline: (groupRun: GroupRunSnapshot) => void;
  onRunAgentGroup: () => void;
  onSaveAgentGroup: () => void;
  onSelectAgentGroup: (groupId: string) => void;
  onStartNewAgentGroup: () => void;
  onToggleAgentGroupMember: (agentId: string) => void;
};

const groupModeOptions = [
  ['moderated', 'Moderated'],
  ['round_robin', 'Round robin'],
  ['debate', 'Debate'],
  ['pipeline', 'Pipeline'],
  ['parallel', 'Parallel'],
  ['custom', 'Custom'],
];

const memoryScopeOptions = [
  ['shared', 'Shared'],
  ['per_agent', 'Per agent'],
  ['hybrid', 'Hybrid'],
];

function AgentGroupAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }) {
  return (
    <span className={avatarUrl ? 'agent-avatar has-image' : 'agent-avatar'} aria-hidden="true">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : agentInitial(name)}
    </span>
  );
}

export function AgentGroupPanel({
  agents,
  agentGroups,
  agentGroupMemoryScope,
  agentGroupMemberIds,
  agentGroupMode,
  agentGroupName,
  agentGroupRunGoal,
  busy,
  latestAgentGroupRun,
  selectedAgentGroup,
  selectedAgentGroupId,
  onAgentGroupMemoryScopeChange,
  onAgentGroupModeChange,
  onAgentGroupNameChange,
  onAgentGroupRunGoalChange,
  onOpenAgentGroupRunTimeline,
  onRunAgentGroup,
  onSaveAgentGroup,
  onSelectAgentGroup,
  onStartNewAgentGroup,
  onToggleAgentGroupMember,
}: AgentGroupPanelProps) {
  const agentGroupMemberIdSet = new Set(agentGroupMemberIds);
  return (
    <section className="agent-studio-grid" data-testid="agent-studio-groups">
      <aside className="agent-studio-panel">
        <div className="section-heading-row">
          <h2>Agent Groups</h2>
          <div className="studio-heading-actions">
            <button type="button" data-testid="agent-group-new" disabled={busy} onClick={onStartNewAgentGroup}>新建</button>
          </div>
        </div>
        <div className="agent-list" data-testid="agent-group-list">
          {agentGroups.map((group) => (
            <button
              type="button"
              className={group.group_id === selectedAgentGroupId ? 'active' : ''}
              data-agent-group-id={group.group_id}
              data-testid="agent-group-list-item"
              key={group.group_id}
              onClick={() => onSelectAgentGroup(group.group_id)}
            >
              <strong>{group.name}</strong>
              <span>{agentGroupListMeta(group)}</span>
            </button>
          ))}
          {!agentGroups.length ? <div className="agent-empty-inline">No Agent Groups</div> : null}
        </div>
      </aside>

      <section className="agent-studio-panel" data-testid="agent-group-editor">
        <div className="section-heading-row">
          <h2>{selectedAgentGroupId ? 'Group Definition' : 'New Group'}</h2>
          <div className="studio-heading-actions">
            <button type="button" data-testid="agent-group-save" disabled={agentGroupSaveDisabled(busy, agentGroupName, agentGroupMemberIds)} onClick={onSaveAgentGroup}>保存</button>
          </div>
        </div>

        <label>
          <span>名称</span>
          <input
            className="hy-input"
            value={agentGroupName}
            maxLength={160}
            onChange={(event) => onAgentGroupNameChange(event.target.value)}
          />
        </label>

        <div className="agent-group-settings-grid">
          <label>
            <span>运行模式</span>
            <select
              className="hy-select"
              value={agentGroupMode || 'moderated'}
              onChange={(event) => onAgentGroupModeChange(event.target.value)}
            >
              {groupModeOptions.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
          <label>
            <span>记忆范围</span>
            <select
              className="hy-select"
              value={agentGroupMemoryScope || 'shared'}
              onChange={(event) => onAgentGroupMemoryScopeChange(event.target.value)}
            >
              {memoryScopeOptions.map(([value, label]) => (
                <option key={value} value={value}>{label}</option>
              ))}
            </select>
          </label>
        </div>

        <div className="section-heading-row compact">
          <h3>Members</h3>
          <span>{agentGroupMemberIds.length} selected</span>
        </div>
        <div className="agent-list managing" data-testid="agent-group-member-picker">
          {agents.map((agent) => (
            <label
              className="agent-list-item"
              data-agent-id={agent.agent_id}
              key={agent.agent_id}
            >
              <span className="agent-list-select" aria-hidden="true">
                <input
                  type="checkbox"
                  checked={agentGroupMemberIdSet.has(agent.agent_id)}
                  disabled={busy || agent.enabled === false}
                  onChange={() => onToggleAgentGroupMember(agent.agent_id)}
                />
              </span>
              <span className="agent-list-main">
                <span className="agent-list-profile">
                  <AgentGroupAvatar avatarUrl={agent.avatar_url} name={agent.nickname || agent.name || agent.agent_id} />
                  <span>
                    <span className="agent-list-name">{agent.nickname || agent.name || agent.agent_id}</span>
                    <small>{agent.description || agent.category || agent.agent_id}</small>
                  </span>
                </span>
              </span>
            </label>
          ))}
          {!agents.length ? <div className="agent-empty-inline">No Agents</div> : null}
        </div>

        <GroupRunPanel
          agentGroupRunGoal={agentGroupRunGoal}
          busy={busy}
          latestAgentGroupRun={latestAgentGroupRun}
          selectedAgentGroupId={selectedAgentGroupId}
          onAgentGroupRunGoalChange={onAgentGroupRunGoalChange}
          onOpenAgentGroupRunTimeline={onOpenAgentGroupRunTimeline}
          onRunAgentGroup={onRunAgentGroup}
        />

        {selectedAgentGroup ? (
          <div className="runtime-management-row">
            <div className="runtime-management-main">
              <div className="runtime-management-title">
                <strong>{selectedAgentGroup.name}</strong>
                <span>{selectedAgentGroup.mode}</span>
                <span>{selectedAgentGroup.memory_scope || 'shared'}</span>
                {selectedAgentGroup.moderator_agent_id ? (
                  <span>moderator {selectedAgentGroup.moderator_agent_id}</span>
                ) : null}
                {selectedAgentGroup.default_model ? (
                  <span>model {selectedAgentGroup.default_model}</span>
                ) : null}
                {selectedAgentGroup.tool_policy_id ? (
                  <span>policy {selectedAgentGroup.tool_policy_id}</span>
                ) : null}
              </div>
              <span>{agentGroupMemberSummary(selectedAgentGroup)}</span>
            </div>
          </div>
        ) : null}
      </section>
    </section>
  );
}
