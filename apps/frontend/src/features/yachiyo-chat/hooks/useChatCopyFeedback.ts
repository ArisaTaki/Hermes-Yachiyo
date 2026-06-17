import { useCallback, useEffect, useRef, useState } from 'react';

const COPY_FEEDBACK_MS = 1500;
const CODE_COPY_FEEDBACK_MS = 2600;

export function useChatCopyFeedback() {
  const [copiedMessageId, setCopiedMessageId] = useState('');
  const [copiedCodeBlockKey, setCopiedCodeBlockKey] = useState('');
  const [copiedSessionId, setCopiedSessionId] = useState('');
  const messageCopyTimerRef = useRef<number | null>(null);
  const codeCopyTimerRef = useRef<number | null>(null);
  const sessionCopyTimerRef = useRef<number | null>(null);

  const markMessageCopied = useCallback((messageId: string) => {
    if (messageCopyTimerRef.current !== null) window.clearTimeout(messageCopyTimerRef.current);
    setCopiedMessageId(messageId);
    messageCopyTimerRef.current = window.setTimeout(() => {
      setCopiedMessageId((current) => (current === messageId ? '' : current));
      messageCopyTimerRef.current = null;
    }, COPY_FEEDBACK_MS);
  }, []);

  const markCodeBlockCopied = useCallback((codeBlockKey: string) => {
    if (codeCopyTimerRef.current !== null) window.clearTimeout(codeCopyTimerRef.current);
    setCopiedCodeBlockKey(codeBlockKey);
    codeCopyTimerRef.current = window.setTimeout(() => {
      setCopiedCodeBlockKey((current) => (current === codeBlockKey ? '' : current));
      codeCopyTimerRef.current = null;
    }, CODE_COPY_FEEDBACK_MS);
  }, []);

  const markSessionCopied = useCallback((sessionId: string) => {
    if (sessionCopyTimerRef.current !== null) window.clearTimeout(sessionCopyTimerRef.current);
    setCopiedSessionId(sessionId);
    sessionCopyTimerRef.current = window.setTimeout(() => {
      setCopiedSessionId((current) => (current === sessionId ? '' : current));
      sessionCopyTimerRef.current = null;
    }, COPY_FEEDBACK_MS);
  }, []);

  useEffect(() => () => {
    if (messageCopyTimerRef.current !== null) window.clearTimeout(messageCopyTimerRef.current);
    if (codeCopyTimerRef.current !== null) window.clearTimeout(codeCopyTimerRef.current);
    if (sessionCopyTimerRef.current !== null) window.clearTimeout(sessionCopyTimerRef.current);
  }, []);

  return {
    copiedCodeBlockKey,
    copiedMessageId,
    copiedSessionId,
    markCodeBlockCopied,
    markMessageCopied,
    markSessionCopied,
  };
}
