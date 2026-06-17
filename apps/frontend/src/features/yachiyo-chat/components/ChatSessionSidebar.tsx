import {
  contextFromSession,
  sessionDisplayName,
  sessionKindLabel,
  sessionPreview,
} from '../sessionState';
import type { ChatRunnableSummary as RunnableSummary } from '../runnables';
import type {
  AssistantProfilePayload,
  SessionItem,
} from '../types';
import { SessionAvatar } from './ChatAvatars';
import { UiIcon } from '../../../components/UiIcon';

export type ChatSessionAgentGroup = {
  agent_id: string;
  agent_name: string;
  sessions: SessionItem[];
};

type ChatSessionSidebarProps = {
  agentGroups: ChatSessionAgentGroup[];
  assistantProfile: AssistantProfilePayload | null;
  assistantProfileLoading: boolean;
  currentSessionId: string;
  expandedAgentIds: Set<string>;
  groupSessions: SessionItem[];
  normalizedSessionQuery: string;
  runnables: RunnableSummary[];
  sessionItemsCount: number;
  sessionsLoaded: boolean;
  sessionQuery: string;
  sessionTab: 'agents' | 'groups';
  unassignedSessions: SessionItem[];
  visibleSessions: SessionItem[];
  formatSessionSideLabel: (session: SessionItem) => string;
  formatTokenCount: (value?: number) => string;
  onCreate: () => void;
  onSearchChange: (value: string) => void;
  onSwitchSession: (sessionId: string, anchorMessageId?: string) => void | Promise<void>;
  onTabChange: (tab: 'agents' | 'groups') => void;
  onToggleAgentGroup: (agentId: string) => void;
};

export function ChatSessionSidebar({
  agentGroups,
  assistantProfile,
  assistantProfileLoading,
  currentSessionId,
  expandedAgentIds,
  groupSessions,
  normalizedSessionQuery,
  runnables,
  sessionItemsCount,
  sessionsLoaded,
  sessionQuery,
  sessionTab,
  unassignedSessions,
  visibleSessions,
  formatSessionSideLabel,
  formatTokenCount,
  onCreate,
  onSearchChange,
  onSwitchSession,
  onTabChange,
  onToggleAgentGroup,
}: ChatSessionSidebarProps) {
  return (
    <aside className="chat-sidebar hy-chat-sessions" aria-label="会话列表">
      <div className="chat-sidebar-header hy-chat-sessions-head">
        <div className="chat-sidebar-title">会话列表</div>
        <input
          type="search"
          className="chat-search"
          value={sessionQuery}
          onChange={(event) => onSearchChange(event.target.value)}
          placeholder="搜索会话..."
          aria-label="搜索会话"
        />
        {normalizedSessionQuery ? (
          <div className="chat-search-meta">
            {sessionsLoaded ? `找到 ${visibleSessions.length} 个相关会话` : '正在搜索...'}
          </div>
        ) : null}
      </div>

      <div className="session-tabs">
        <button
          type="button"
          className={`session-tab ${sessionTab === 'agents' ? 'active' : ''}`}
          data-testid="chat-session-tab-agents"
          onClick={() => onTabChange('agents')}
        >
          Agent
        </button>
        <button
          type="button"
          className={`session-tab ${sessionTab === 'groups' ? 'active' : ''}`}
          data-testid="chat-session-tab-groups"
          onClick={() => onTabChange('groups')}
        >
          群组
        </button>
        <button
          type="button"
          className="session-tab-create"
          data-testid="chat-session-tab-create"
          title={sessionTab === 'groups' ? '创建群组' : '新建对话'}
          aria-label={sessionTab === 'groups' ? '创建群组' : '新建对话'}
          onClick={onCreate}
        >
          <UiIcon name="plus" />
        </button>
      </div>

      <div className="chat-list hy-chat-session-list">
        {normalizedSessionQuery ? (
          visibleSessions.length > 0 ? (
            visibleSessions.map((session) => (
              <ChatSessionListItem
                assistantProfile={assistantProfile}
                assistantProfileLoading={assistantProfileLoading}
                currentSessionId={currentSessionId}
                formatSessionSideLabel={formatSessionSideLabel}
                formatTokenCount={formatTokenCount}
                key={session.session_id}
                normalizedSessionQuery={normalizedSessionQuery}
                onSwitchSession={onSwitchSession}
                runnables={runnables}
                session={session}
                showKind={session.conversation_kind === 'agent' || session.conversation_kind === 'workflow' || session.conversation_kind === 'group'}
              />
            ))
          ) : (
            <div className="empty-state inline-empty">
              无匹配会话
            </div>
          )
        ) : sessionTab === 'agents' ? (
          unassignedSessions.length > 0 || agentGroups.length > 0 ? (
            <>
              {unassignedSessions.map((session) => (
                <ChatSessionListItem
                  assistantProfile={assistantProfile}
                  assistantProfileLoading={assistantProfileLoading}
                  className="unassigned-chat-item"
                  currentSessionId={currentSessionId}
                  formatSessionSideLabel={formatSessionSideLabel}
                  formatTokenCount={formatTokenCount}
                  key={session.session_id}
                  normalizedSessionQuery={normalizedSessionQuery}
                  onSwitchSession={onSwitchSession}
                  runnables={runnables}
                  session={session}
                  sessionContextOverride={{ ...contextFromSession(session), conversation_kind: 'unassigned' }}
                />
              ))}
              {agentGroups.map((group) => {
                const isExpanded = expandedAgentIds.has(group.agent_id);
                return (
                  <div key={group.agent_id} className="agent-group">
                    <button
                      type="button"
                      className="agent-group-header"
                      onClick={() => onToggleAgentGroup(group.agent_id)}
                    >
                      <span className={`agent-group-toggle ${isExpanded ? 'expanded' : ''}`}>
                        {'>'}
                      </span>
                      <span className="agent-group-name">{group.agent_name}</span>
                      <span className="agent-group-count">{group.sessions.length}</span>
                    </button>
                    <div className={`agent-group-sessions ${isExpanded ? 'expanded' : ''}`}>
                      <div className="agent-group-sessions-inner">
                        {group.sessions.map((session) => (
                          <ChatSessionListItem
                            assistantProfile={assistantProfile}
                            assistantProfileLoading={assistantProfileLoading}
                            currentSessionId={currentSessionId}
                            formatSessionSideLabel={formatSessionSideLabel}
                            formatTokenCount={formatTokenCount}
                            key={session.session_id}
                            normalizedSessionQuery={normalizedSessionQuery}
                            onSwitchSession={onSwitchSession}
                            runnables={runnables}
                            session={session}
                          />
                        ))}
                      </div>
                    </div>
                  </div>
                );
              })}
            </>
          ) : (
            <div className="empty-state inline-empty">
              {sessionItemsCount ? '无匹配会话' : '暂无对话'}
            </div>
          )
        ) : (
          groupSessions.length > 0 ? (
            groupSessions.map((session) => (
              <ChatSessionListItem
                assistantProfile={assistantProfile}
                assistantProfileLoading={assistantProfileLoading}
                currentSessionId={currentSessionId}
                formatSessionSideLabel={formatSessionSideLabel}
                formatTokenCount={formatTokenCount}
                key={session.session_id}
                normalizedSessionQuery={normalizedSessionQuery}
                onSwitchSession={onSwitchSession}
                runnables={runnables}
                session={session}
                showKind
              />
            ))
          ) : (
            <div className="empty-state inline-empty">
              {sessionItemsCount ? '无群组会话' : '暂无对话'}
            </div>
          )
        )}
      </div>
    </aside>
  );
}

function ChatSessionListItem({
  assistantProfile,
  assistantProfileLoading,
  className = '',
  currentSessionId,
  formatSessionSideLabel,
  formatTokenCount,
  normalizedSessionQuery,
  onSwitchSession,
  runnables,
  session,
  sessionContextOverride,
  showKind = false,
}: {
  assistantProfile: AssistantProfilePayload | null;
  assistantProfileLoading: boolean;
  className?: string;
  currentSessionId: string;
  formatSessionSideLabel: (session: SessionItem) => string;
  formatTokenCount: (value?: number) => string;
  normalizedSessionQuery: string;
  onSwitchSession: (sessionId: string, anchorMessageId?: string) => void | Promise<void>;
  runnables: RunnableSummary[];
  session: SessionItem;
  sessionContextOverride?: ReturnType<typeof contextFromSession>;
  showKind?: boolean;
}) {
  const active = session.session_id === currentSessionId;
  const itemClassName = ['chat-item', className, active ? 'active' : ''].filter(Boolean).join(' ');
  return (
    <button
      type="button"
      className={itemClassName}
      onClick={() => void onSwitchSession(session.session_id, session.search_match?.message_id || '')}
    >
      <SessionAvatar
        assistantProfile={assistantProfile}
        context={sessionContextOverride || contextFromSession(session)}
        loading={assistantProfileLoading}
        size="small"
        runnables={runnables}
      />
      <span className="chat-item-info">
        <strong className="chat-item-name">{sessionDisplayName(session, assistantProfile)}</strong>
        {showKind ? <span className="chat-item-kind">{sessionKindLabel(session)}</span> : null}
        <span className={session.search_match ? 'chat-item-preview search-hit' : 'chat-item-preview'}>
          <HighlightedText text={sessionPreview(session)} query={normalizedSessionQuery} />
        </span>
      </span>
      <span className="chat-item-side">
        <span className="chat-item-time">
          {formatSessionSideLabel(session)}
        </span>
        <span className="chat-item-token">{formatTokenCount(session.token_count)}</span>
      </span>
    </button>
  );
}

function HighlightedText({ text, query }: { text: string; query: string }) {
  const needle = query.trim();
  if (!needle) return <>{text}</>;
  const lowerText = text.toLowerCase();
  const lowerNeedle = needle.toLowerCase();
  const index = lowerText.indexOf(lowerNeedle);
  if (index < 0) return <>{text}</>;
  const before = text.slice(0, index);
  const match = text.slice(index, index + needle.length);
  const after = text.slice(index + needle.length);
  return (
    <>
      {before}
      <mark>{match}</mark>
      {after}
    </>
  );
}
