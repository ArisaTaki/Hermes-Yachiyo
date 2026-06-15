import { useEffect, useRef } from 'react';

import { UiIcon } from '../../../components/UiIcon';

export function SessionIdDialog({ copied, error, sessionId, onClose, onCopy }: {
  copied: boolean;
  error: string;
  sessionId: string;
  onClose: () => void;
  onCopy: () => void;
}) {
  const inputRef = useRef<HTMLInputElement>(null);

  useEffect(() => {
    window.setTimeout(() => {
      inputRef.current?.focus({ preventScroll: true });
      inputRef.current?.select();
    }, 30);
  }, []);

  useEffect(() => {
    function handleEscape(event: KeyboardEvent) {
      if (event.key === 'Escape') onClose();
    }
    window.addEventListener('keydown', handleEscape);
    return () => window.removeEventListener('keydown', handleEscape);
  }, [onClose]);

  return (
    <div className="chat-modal-backdrop" role="presentation" onMouseDown={(event) => {
      if (event.target === event.currentTarget) onClose();
    }}>
      <div className="chat-session-id-dialog" role="dialog" aria-modal="true" aria-label="会话 ID">
        <header className="chat-group-dialog-header">
          <div>
            <strong>会话 ID</strong>
            <span>{error ? '复制失败时可手动选择' : '用于调试，不会复制聊天记录'}</span>
          </div>
          <button type="button" className="chat-action-btn" aria-label="关闭" title="关闭" onClick={onClose}>
            <UiIcon name="close" />
          </button>
        </header>
        <input
          ref={inputRef}
          className="chat-session-id-input"
          value={sessionId}
          readOnly
          onFocus={(event) => event.currentTarget.select()}
        />
        {error ? <div className="chat-session-id-error">剪贴板不可用：{error}</div> : null}
        <footer className="chat-group-dialog-actions">
          <button type="button" className="chat-group-secondary-btn" onClick={onClose}>关闭</button>
          <button type="button" className="chat-group-primary-btn" onClick={onCopy}>
            {copied ? '已复制' : '复制 ID'}
          </button>
        </footer>
      </div>
    </div>
  );
}
