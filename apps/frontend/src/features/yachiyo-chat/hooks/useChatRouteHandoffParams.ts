import { useEffect, useState } from 'react';

import { ROUTE_CHANGE_EVENT, currentParam } from '../../../lib/view';

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
