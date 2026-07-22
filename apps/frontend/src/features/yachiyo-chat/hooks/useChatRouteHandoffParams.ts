import { useEffect, useRef, useState } from 'react';

import { ROUTE_CHANGE_EVENT, currentParam } from '../../../lib/view';
import { taskHandoffMessageId } from '../messageTaskHandoff';
import type { ChatMessage } from '../types';

type ChatRouteHandoffMessagesPayload = {
  messages?: ChatMessage[];
} | undefined;

type UseChatRouteHandoffOptions = {
  loadSessions: () => Promise<void>;
  refreshAssistantProfile: () => Promise<unknown>;
  refreshExecutor: () => Promise<unknown>;
  refreshMessages: () => Promise<ChatRouteHandoffMessagesPayload>;
  revealMessage: (messageId: string) => void;
  setStatus: (value: string) => void;
  switchConversation: (sessionId: string) => Promise<ChatRouteHandoffMessagesPayload>;
};

function readChatRouteHandoffParams() {
  return {
    routeSessionId: currentParam('session_id').trim(),
    routeTaskId: currentParam('task_id').trim(),
  };
}

export function useChatRouteHandoffParams() {
  const [{ routeSessionId, routeTaskId }, setRouteParams] = useState(readChatRouteHandoffParams);

  useEffect(() => {
    const syncRouteChatHandoffParams = () => {
      setRouteParams(readChatRouteHandoffParams());
    };
    window.addEventListener('hashchange', syncRouteChatHandoffParams);
    window.addEventListener('popstate', syncRouteChatHandoffParams);
    window.addEventListener(ROUTE_CHANGE_EVENT, syncRouteChatHandoffParams);
    syncRouteChatHandoffParams();
    return () => {
      window.removeEventListener('hashchange', syncRouteChatHandoffParams);
      window.removeEventListener('popstate', syncRouteChatHandoffParams);
      window.removeEventListener(ROUTE_CHANGE_EVENT, syncRouteChatHandoffParams);
    };
  }, []);

  return {
    routeSessionId,
    routeTaskId,
  };
}

export function useChatRouteHandoff({
  loadSessions,
  refreshAssistantProfile,
  refreshExecutor,
  refreshMessages,
  revealMessage,
  setStatus,
  switchConversation,
}: UseChatRouteHandoffOptions) {
  const { routeSessionId, routeTaskId } = useChatRouteHandoffParams();
  const actionsRef = useRef({
    loadSessions,
    refreshAssistantProfile,
    refreshExecutor,
    refreshMessages,
    revealMessage,
    setStatus,
    switchConversation,
  });

  useEffect(() => {
    actionsRef.current = {
      loadSessions,
      refreshAssistantProfile,
      refreshExecutor,
      refreshMessages,
      revealMessage,
      setStatus,
      switchConversation,
    };
  }, [
    loadSessions,
    refreshAssistantProfile,
    refreshExecutor,
    refreshMessages,
    revealMessage,
    setStatus,
    switchConversation,
  ]);

  useEffect(() => {
    const requestedSessionId = routeSessionId;
    const requestedTaskId = routeTaskId;
    let cancelled = false;
    void (async () => {
      const actions = actionsRef.current;
      await Promise.all([actions.refreshAssistantProfile(), actions.refreshExecutor()]);
      if (cancelled) return;
      const messagePayload = requestedSessionId
        ? await actions.switchConversation(requestedSessionId)
        : (await Promise.all([actions.refreshMessages(), actions.loadSessions()]))[0];
      if (cancelled) return;
      if (requestedTaskId && messagePayload?.messages) {
        const messageId = taskHandoffMessageId(messagePayload.messages, requestedTaskId);
        if (messageId) {
          actions.revealMessage(messageId);
          actions.setStatus('已定位到关联任务消息');
        }
      }
    })().catch((error) => {
      if (!cancelled) {
        actionsRef.current.setStatus(error instanceof Error ? error.message : '会话定位失败');
      }
    });
    return () => {
      cancelled = true;
    };
  }, [routeSessionId, routeTaskId]);
}
