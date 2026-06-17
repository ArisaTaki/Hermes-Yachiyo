import { UiIcon } from '../../../components/UiIcon';
import type { ChatRunnableSummary as RunnableSummary } from '../runnables';
import type {
  AssistantProfilePayload,
  ChatSessionContext,
} from '../types';
import { SessionAvatar } from './ChatAvatars';

type ChatHeaderProps = {
  assistantProfile: AssistantProfilePayload | null;
  assistantProfileLoading: boolean;
  attachmentHelpText: string;
  currentSessionId: string;
  currentTitle: string;
  deleteTarget: string;
  hasSessions: boolean;
  imageAttachDisabled: boolean;
  isProcessing: boolean;
  copiedSessionId: string;
  runnables: RunnableSummary[];
  sessionContext: ChatSessionContext;
  statusText: string;
  onCancelProcessing: () => void;
  onClearSession: () => void;
  onOpenGroupSettings: () => void;
  onOpenImageAttachmentPicker: () => void;
  onOpenSessionIdDialog: () => void;
  onRequestDeleteSession: () => void;
};

export function ChatHeader({
  assistantProfile,
  assistantProfileLoading,
  attachmentHelpText,
  currentSessionId,
  currentTitle,
  deleteTarget,
  hasSessions,
  imageAttachDisabled,
  isProcessing,
  copiedSessionId,
  runnables,
  sessionContext,
  statusText,
  onCancelProcessing,
  onClearSession,
  onOpenGroupSettings,
  onOpenImageAttachmentPicker,
  onOpenSessionIdDialog,
  onRequestDeleteSession,
}: ChatHeaderProps) {
  const sessionIdCopied = copiedSessionId === currentSessionId;
  return (
    <header className="chat-header">
      <div className="chat-header-info">
        <SessionAvatar
          assistantProfile={assistantProfile}
          context={sessionContext}
          loading={assistantProfileLoading}
          size="header"
          runnables={runnables}
        />
        <div>
          <div className="chat-header-name">{currentTitle}</div>
          <div className="chat-header-status">
            <div className={`status-dot ${isProcessing ? 'processing' : 'completed'}`} />
            <span>{statusText}</span>
          </div>
        </div>
      </div>
      <div className="chat-header-actions">
        {sessionContext.conversation_kind === 'group' ? (
          <button
            type="button"
            className="chat-action-btn"
            data-testid="chat-group-settings"
            title="群组设置"
            aria-label="群组设置"
            disabled={!currentSessionId}
            onClick={onOpenGroupSettings}
          >
            <UiIcon name="settings" />
          </button>
        ) : null}
        <button
          type="button"
          className={`chat-action-btn ${sessionIdCopied ? 'copied' : ''}`}
          title={currentSessionId ? `查看/复制会话 ID：${currentSessionId}` : '查看/复制会话 ID'}
          aria-label="查看/复制会话 ID，不复制聊天记录"
          disabled={!currentSessionId}
          onClick={onOpenSessionIdDialog}
        >
          <UiIcon name={sessionIdCopied ? 'check' : 'copy'} />
        </button>
        <button
          type="button"
          className="chat-action-btn"
          title={attachmentHelpText}
          aria-label="附加图片"
          data-testid="chat-header-image-attach-button"
          disabled={imageAttachDisabled}
          onClick={onOpenImageAttachmentPicker}
        >
          <UiIcon name="image" />
        </button>
        <button
          type="button"
          className="chat-action-btn"
          title="停止生成"
          aria-label="停止生成"
          data-testid="chat-header-stop-button"
          onClick={onCancelProcessing}
          disabled={!isProcessing}
        >
          <UiIcon name="stop" />
        </button>
        <button type="button" className="chat-action-btn" title="新对话" aria-label="新对话" onClick={onClearSession}>
          <UiIcon name="plus" />
        </button>
        <button
          type="button"
          className="chat-action-btn danger-action"
          title={`删除${deleteTarget}`}
          aria-label={`删除${deleteTarget}`}
          onClick={onRequestDeleteSession}
          disabled={!hasSessions}
        >
          <UiIcon name="trash" />
        </button>
      </div>
    </header>
  );
}
