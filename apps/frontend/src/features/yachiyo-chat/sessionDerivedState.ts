import {
  contextFromSession,
  conversationDisplayName,
  deleteTargetLabel,
  groupDefaultName,
  isUnassignedSession,
  normalizeSessionContext,
} from './sessionState';
import type { ChatRunnableSummary as RunnableSummary } from './runnables';
import type {
  AssistantProfilePayload,
  ChatMessage,
  ChatSessionContext,
  SessionItem,
  SessionsPayload,
} from './types';

export type ChatSessionAgentGroup = {
  agent_id: string;
  agent_name: string;
  sessions: SessionItem[];
};

export type ChatSessionDerivedStateInput = {
  assistantProfile: AssistantProfilePayload | null;
  debouncedSessionQuery: string;
  messages: ChatMessage[];
  runnables: RunnableSummary[];
  selectedGroupAgentIds: string[];
  sessionContext: ChatSessionContext | null;
  sessions: SessionsPayload | null;
};

export type ChatSessionDerivedState = {
  activeSessionContext: ChatSessionContext;
  agentGroups: ChatSessionAgentGroup[];
  agentRunnables: RunnableSummary[];
  currentIsUnassigned: boolean;
  currentSession?: SessionItem;
  currentSessionId: string;
  currentTitle: string;
  defaultGroupName: string;
  deleteTarget: string;
  groupSessions: SessionItem[];
  normalizedSessionQuery: string;
  sessionItems: SessionItem[];
  unassignedSessions: SessionItem[];
  visibleSessions: SessionItem[];
};

export function deriveChatSessionState({
  assistantProfile,
  debouncedSessionQuery,
  messages,
  runnables,
  selectedGroupAgentIds,
  sessionContext,
  sessions,
}: ChatSessionDerivedStateInput): ChatSessionDerivedState {
  const sessionItems = sessions?.sessions || [];
  const normalizedSessionQuery = debouncedSessionQuery.trim();
  const visibleSessions = sessionItems;
  const agentRunnables = runnables.filter((item) => item.kind === 'agent' && item.enabled !== false);
  const defaultGroupName = groupDefaultName(agentRunnables, selectedGroupAgentIds, assistantProfile);
  const unassignedSessions = sessionItems.filter((session) => isUnassignedSession(session));
  const agentGroups = deriveAgentGroups(sessionItems, runnables, assistantProfile);
  const groupSessions = sessionItems.filter((session) => (
    session.conversation_kind === 'workflow' || session.conversation_kind === 'group'
  ));
  const currentSessionId = sessions?.current_session_id || '';
  const currentSession = sessionItems.find((session) => session.session_id === currentSessionId);
  const currentIsUnassigned = currentSession
    ? isUnassignedSession(currentSession)
    : messages.length === 0 && normalizeSessionContext(sessionContext).conversation_kind === 'main';
  const activeSessionContext = currentIsUnassigned
    ? {
      ...normalizeSessionContext(currentSession ? contextFromSession(currentSession) : sessionContext),
      conversation_kind: 'unassigned',
    }
    : currentSession ? contextFromSession(currentSession) : normalizeSessionContext(sessionContext);
  const currentTitle = conversationDisplayName(
    currentSession,
    activeSessionContext,
    assistantProfile,
    messages,
  );
  const deleteTarget = deleteTargetLabel(activeSessionContext);

  return {
    activeSessionContext,
    agentGroups,
    agentRunnables,
    currentIsUnassigned,
    currentSession,
    currentSessionId,
    currentTitle,
    defaultGroupName,
    deleteTarget,
    groupSessions,
    normalizedSessionQuery,
    sessionItems,
    unassignedSessions,
    visibleSessions,
  };
}

function deriveAgentGroups(
  sessionItems: SessionItem[],
  runnables: RunnableSummary[],
  assistantProfile: AssistantProfilePayload | null,
): ChatSessionAgentGroup[] {
  const groups = new Map<string, ChatSessionAgentGroup>();

  sessionItems
    .filter((session) => (
      !isUnassignedSession(session)
      && (session.conversation_kind === 'main' || session.conversation_kind === 'agent')
    ))
    .forEach((session) => {
      const agentId = session.runnable_id || 'main';
      const runnable = runnables.find((item) => item.id === agentId);
      const agentName = agentId === 'main'
        ? (assistantProfile?.agent_nickname || assistantProfile?.agent_name || '主模型')
        : runnable?.nickname || runnable?.name || session.runnable_name || 'Agent';

      if (!groups.has(agentId)) {
        groups.set(agentId, {
          agent_id: agentId,
          agent_name: agentName,
          sessions: [],
        });
      }
      groups.get(agentId)!.sessions.push(session);
    });

  return Array.from(groups.values());
}
