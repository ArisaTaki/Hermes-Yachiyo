import { useEffect, useRef, useState } from 'react';

import { apiPost } from '../../../lib/bridge';
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
}: UseChatRouteHandoffOptions) {
  const { routeSessionId, routeTaskId } = useChatRouteHandoffParams();
  const actionsRef = useRef({
    loadSessions,
    refreshAssistantProfile,
    refreshExecutor,
    refreshMessages,
    revealMessage,
    setStatus,
  });

  useEffect(() => {
    actionsRef.current = {
      loadSessions,
      refreshAssistantProfile,
      refreshExecutor,
      refreshMessages,
      revealMessage,
      setStatus,
    };
  }, [
    loadSessions,
    refreshAssistantProfile,
    refreshExecutor,
    refreshMessages,
    revealMessage,
    setStatus,
  ]);

  useEffect(() => {
    const requestedSessionId = routeSessionId;
    const requestedTaskId = routeTaskId;
    void (async () => {
      const actions = actionsRef.current;
      await Promise.all([actions.refreshAssistantProfile(), actions.refreshExecutor()]);
      if (requestedSessionId) {
        try {
          const result = await apiPost<{ ok?: boolean; error?: string }>('/ui/chat/sessions/load', {
            session_id: requestedSessionId,
          });
          if (result.ok === false) throw new Error(result.error || '切换会话失败');
        } catch (error) {
          actions.setStatus(error instanceof Error ? error.message : '切换会话失败');
        }
      }
      const [messagePayload] = await Promise.all([actions.refreshMessages(), actions.loadSessions()]);
      if (requestedTaskId && messagePayload?.messages) {
        const messageId = taskHandoffMessageId(messagePayload.messages, requestedTaskId);
        if (messageId) {
          actions.revealMessage(messageId);
          actions.setStatus('已定位到关联任务消息');
        }
      }
    })();
  }, [routeSessionId, routeTaskId]);
}
