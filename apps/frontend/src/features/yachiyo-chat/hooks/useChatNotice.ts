import { useCallback, useEffect, useRef, useState } from 'react';

import type { ChatNotice } from '../types';

type ChatNoticeAction = Pick<ChatNotice, 'action_label' | 'action_view' | 'action_params'>;

export function useChatNotice() {
  const [notice, setNotice] = useState<ChatNotice | null>(null);
  const noticeTimerRef = useRef<number | null>(null);

  const dismissNotice = useCallback(() => {
    if (noticeTimerRef.current !== null) {
      window.clearTimeout(noticeTimerRef.current);
      noticeTimerRef.current = null;
    }
    setNotice(null);
  }, []);

  const showNotice = useCallback((
    title: string,
    detail: string,
    kind: ChatNotice['kind'] = 'warn',
    action: ChatNoticeAction = {},
  ) => {
    if (noticeTimerRef.current !== null) window.clearTimeout(noticeTimerRef.current);
    setNotice({ id: Date.now(), kind, title, detail, ...action });
    noticeTimerRef.current = window.setTimeout(() => {
      noticeTimerRef.current = null;
      setNotice(null);
    }, 5200);
  }, []);

  useEffect(() => dismissNotice, [dismissNotice]);

  return {
    dismissNotice,
    notice,
    showNotice,
  };
}
