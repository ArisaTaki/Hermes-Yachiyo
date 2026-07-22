import type {
  ChangeEvent,
  ClipboardEvent as ReactClipboardEvent,
  CSSProperties,
  FormEvent,
  KeyboardEvent as ReactKeyboardEvent,
  PointerEvent as ReactPointerEvent,
  RefObject,
} from 'react';

import { UiIcon } from '../../../components/UiIcon';
import type { ComposerApprovalItem } from '../approvalItems';
import { mentionKindLabel, type MentionOption } from '../mentions';
import type { PendingAttachment } from '../types';
import { AvatarStack, participantAvatarContent } from './ChatAvatars';
import { ComposerApprovalNotice } from './ComposerApprovalNotice';
import type { ApprovalRequestDetails } from './MessageApprovalRequestCard';

type ChatComposerProps = {
  activeMentionChips: MentionOption[];
  activeMentionOptionId?: string;
  attachmentHelpText: string;
  attachments: PendingAttachment[];
  composerApprovalBusy: boolean;
  composerApprovalCount: number;
  composerApprovalDetails: ApprovalRequestDetails | null;
  composerApprovalIndex: number;
  composerApprovalItem: ComposerApprovalItem | null;
  composerHeight: number;
  composerMaxHeight: number;
  composerMinHeight: number;
  conversationTransitionLocked: boolean;
  fileInputRef: RefObject<HTMLInputElement | null>;
  imageAttachDisabled: boolean;
  input: string;
  inputRef: RefObject<HTMLTextAreaElement | null>;
  isProcessing: boolean;
  isSending: boolean;
  mentionActiveIndex: number;
  mentionSuggestions: MentionOption[];
  processingCount: number;
  onCancelProcessing: () => void;
  onComposerCompositionEnd: () => void;
  onComposerCompositionStart: () => void;
  onComposerKeyDown: (event: ReactKeyboardEvent<HTMLTextAreaElement>) => void;
  onComposerPaste: (event: ReactClipboardEvent<HTMLTextAreaElement>) => void;
  onComposerResizeKeyDown: (event: ReactKeyboardEvent<HTMLDivElement>) => void;
  onComposerResizePointerDown: (event: ReactPointerEvent<HTMLDivElement>) => void;
  onFileInputChange: (event: ChangeEvent<HTMLInputElement>) => void;
  onInputChange: (value: string) => void;
  onMentionHover: (index: number) => void;
  onMentionSelect: (option: MentionOption) => void;
  onOpenComposerApprovalDetails: () => void;
  onOpenImageAttachmentPicker: () => void;
  onPreviousComposerApproval: () => void;
  onRemoveAttachment: (attachmentId: string) => void;
  onRevealComposerApproval: () => void;
  onNextComposerApproval: () => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
};

export function ChatComposer({
  activeMentionChips,
  activeMentionOptionId,
  attachmentHelpText,
  attachments,
  composerApprovalBusy,
  composerApprovalCount,
  composerApprovalDetails,
  composerApprovalIndex,
  composerApprovalItem,
  composerHeight,
  composerMaxHeight,
  composerMinHeight,
  conversationTransitionLocked,
  fileInputRef,
  imageAttachDisabled,
  input,
  inputRef,
  isProcessing,
  isSending,
  mentionActiveIndex,
  mentionSuggestions,
  processingCount,
  onCancelProcessing,
  onComposerCompositionEnd,
  onComposerCompositionStart,
  onComposerKeyDown,
  onComposerPaste,
  onComposerResizeKeyDown,
  onComposerResizePointerDown,
  onFileInputChange,
  onInputChange,
  onMentionHover,
  onMentionSelect,
  onOpenComposerApprovalDetails,
  onOpenImageAttachmentPicker,
  onPreviousComposerApproval,
  onRemoveAttachment,
  onRevealComposerApproval,
  onNextComposerApproval,
  onSubmit,
}: ChatComposerProps) {
  const composerInputStyle = { height: `${composerHeight}px` } as CSSProperties;
  const sendDisabled = conversationTransitionLocked
    || isSending
    || (!input.trim() && attachments.length === 0);

  return (
    <form
      className="chat-input-area composer refined-composer"
      data-conversation-transition-locked={String(conversationTransitionLocked)}
      onSubmit={onSubmit}
    >
      {composerApprovalItem && composerApprovalDetails ? (
        <ComposerApprovalNotice
          approvalId={composerApprovalItem.approvalId}
          busy={composerApprovalBusy}
          currentIndex={composerApprovalIndex}
          details={composerApprovalDetails}
          itemId={composerApprovalItem.id}
          onOpenDetails={onOpenComposerApprovalDetails}
          onPrevious={onPreviousComposerApproval}
          onReveal={onRevealComposerApproval}
          onNext={onNextComposerApproval}
          runId={composerApprovalItem.runId}
          runStatus={composerApprovalItem.runStatus}
          source={composerApprovalItem.source}
          total={composerApprovalCount}
        />
      ) : null}
      <div className={`chat-input-wrapper${isProcessing ? ' is-processing' : ''}`}>
        <div className="composer-body">
          {attachments.length ? (
            <div className="composer-attachments" aria-label="已添加图片附件">
              {attachments.map((attachment) => (
                <figure
                  className="composer-attachment"
                  data-testid="chat-composer-attachment-preview"
                  data-attachment-id={attachment.id}
                  data-attachment-mime={attachment.mime_type}
                  data-attachment-name={attachment.name}
                  data-attachment-size={attachment.size}
                  data-attachment-width={attachment.width || ''}
                  data-attachment-height={attachment.height || ''}
                  key={attachment.id}
                >
                  <img src={attachment.data_url} alt={attachment.name} />
                  <figcaption>{attachment.name}</figcaption>
                  <button
                    type="button"
                    disabled={conversationTransitionLocked}
                    aria-label={`移除 ${attachment.name}`}
                    data-testid="chat-composer-attachment-remove"
                    onClick={() => onRemoveAttachment(attachment.id)}
                  >
                    ×
                  </button>
                </figure>
              ))}
            </div>
          ) : null}
          {activeMentionChips.length ? (
            <div className="composer-mention-chips" aria-label="当前提及">
              {activeMentionChips.map((mention) => (
                <span className={`composer-mention-chip ${mention.kind}`} key={`${mention.kind}-${mention.id}`}>
                  @{mention.nickname || mention.name}
                </span>
              ))}
            </div>
          ) : null}
          {mentionSuggestions.length ? (
            <div className="composer-mention-menu" id="composer-mention-menu" role="listbox" aria-label="选择提及对象">
              {mentionSuggestions.map((option, index) => (
                <button
                  type="button"
                  disabled={conversationTransitionLocked}
                  className={`composer-mention-option ${option.kind}${index === mentionActiveIndex ? ' active' : ''}`}
                  id={`composer-mention-option-${index}`}
                  key={`${option.kind}-${option.id}`}
                  role="option"
                  aria-selected={index === mentionActiveIndex}
                  onClick={() => onMentionSelect(option)}
                  onMouseEnter={() => onMentionHover(index)}
                >
                  <span className="composer-mention-avatar">
                    {option.kind === 'workflow' || option.kind === 'group' ? (
                      <AvatarStack participants={option.participants || []} />
                    ) : (
                      participantAvatarContent(option, option.kind === 'main' ? '月' : 'A')
                    )}
                  </span>
                  <span className="composer-mention-text">
                    <strong>{option.nickname || option.name}</strong>
                    <small>{mentionKindLabel(option)}</small>
                  </span>
                </button>
              ))}
            </div>
          ) : null}
          <textarea
            className="chat-input"
            data-testid="chat-composer-input"
            ref={inputRef}
            value={input}
            onChange={(event) => onInputChange(event.target.value)}
            onCompositionEnd={onComposerCompositionEnd}
            onCompositionStart={onComposerCompositionStart}
            onKeyDown={onComposerKeyDown}
            onPaste={onComposerPaste}
            placeholder="输入消息..."
            aria-activedescendant={activeMentionOptionId}
            aria-disabled={isSending || conversationTransitionLocked}
            aria-controls={mentionSuggestions.length ? 'composer-mention-menu' : undefined}
            aria-expanded={mentionSuggestions.length > 0}
            aria-haspopup="listbox"
            disabled={conversationTransitionLocked}
            readOnly={isSending || conversationTransitionLocked}
            rows={1}
            style={composerInputStyle}
          />
        </div>
        <div
          className="composer-resize-handle"
          role="separator"
          aria-label="调整输入框高度"
          aria-orientation="horizontal"
          aria-valuemin={composerMinHeight}
          aria-valuemax={composerMaxHeight}
          aria-valuenow={composerHeight}
          tabIndex={0}
          title="拖动或用方向键调整输入框高度"
          onKeyDown={onComposerResizeKeyDown}
          onPointerDown={onComposerResizePointerDown}
        />
        <button
          type="button"
          className="chat-attach-btn"
          disabled={imageAttachDisabled}
          title={attachmentHelpText}
          aria-label="添加附件，当前仅支持图片"
          data-testid="chat-composer-image-attach-button"
          onClick={onOpenImageAttachmentPicker}
        >
          <UiIcon name="paperclip" />
        </button>
        {isProcessing ? (
          <button
            type="button"
            className="chat-stop-btn"
            aria-label={processingCount > 1 ? `停止当前 ${processingCount} 项任务` : '停止当前任务'}
            title={processingCount > 1 ? `停止当前 ${processingCount} 项任务` : '停止当前任务'}
            data-testid="chat-composer-stop-button"
            onClick={onCancelProcessing}
          >
            <UiIcon name="stop" />
          </button>
        ) : null}
        <button
          type="submit"
          className="chat-send-btn neon-glow"
          data-testid="chat-composer-send"
          disabled={sendDisabled}
          aria-label="发送消息"
          title={isProcessing ? '继续发送消息' : '发送消息'}
        >
          <UiIcon name="send" />
        </button>
      </div>
      <input
        ref={fileInputRef}
        type="file"
        accept="image/*"
        multiple
        hidden
        disabled={imageAttachDisabled}
        data-testid="chat-image-file-input"
        onChange={onFileInputChange}
      />
    </form>
  );
}
