import type { Ref } from 'react';

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
  conversationTransitionLocked: boolean;
  runnables: RunnableSummary[];
  sessionContext: ChatSessionContext;
  statusText: string;
  onCancelProcessing: () => void;
  onClearSession: () => void;
  onOpenGroupSettings: () => void;
  onOpenImageAttachmentPicker: () => void;
  onRequestDeleteSession: () => void;
  onToggleSessions: () => void;
  sessionsPanelOpen: boolean;
  sessionsToggleRef: Ref<HTMLButtonElement>;
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
  conversationTransitionLocked,
  runnables,
  sessionContext,
  statusText,
  onCancelProcessing,
  onClearSession,
  onOpenGroupSettings,
  onOpenImageAttachmentPicker,
  onRequestDeleteSession,
  onToggleSessions,
  sessionsPanelOpen,
  sessionsToggleRef,
}: ChatHeaderProps) {
  return (
    <header className="chat-header">
      <div className="chat-header-info">
        <button
          type="button"
          className="chat-action-btn chat-session-toggle-btn"
          aria-controls="chat-session-sidebar"
          aria-expanded={sessionsPanelOpen}
          aria-label={sessionsPanelOpen ? '收起会话列表' : '展开会话列表'}
          title={sessionsPanelOpen ? '收起会话列表' : '展开会话列表'}
          onClick={onToggleSessions}
          ref={sessionsToggleRef}
        >
          <UiIcon name="sidebar" />
        </button>
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
            disabled={!currentSessionId || conversationTransitionLocked}
            onClick={onOpenGroupSettings}
          >
            <UiIcon name="settings" />
          </button>
        ) : null}
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
        <button
          type="button"
          className="chat-action-btn"
          title="新对话"
          aria-label="新对话"
          onClick={onClearSession}
          disabled={conversationTransitionLocked}
        >
          <UiIcon name="plus" />
        </button>
        <button
          type="button"
          className="chat-action-btn danger-action"
          title={`删除${deleteTarget}`}
          aria-label={`删除${deleteTarget}`}
          onClick={onRequestDeleteSession}
          disabled={!hasSessions || conversationTransitionLocked}
        >
          <UiIcon name="trash" />
        </button>
      </div>
    </header>
  );
}
