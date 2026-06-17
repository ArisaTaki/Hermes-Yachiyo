import { ImageAttachmentViewer } from '../../../components/ImageAttachmentViewer';
import { UiIcon } from '../../../components/UiIcon';
import {
  approvalRequestDetails,
  hasActionableApproval,
  isWorkflowApprovalDetails,
  messageApprovalId,
  messageApprovalSignature,
} from '../approvalItems';
import { fencedCode, renderMarkdown } from '../markdown';
import {
  messageHasRunContext,
  messageRoleLabel,
  messageRunId,
  messageRunProgressDetail,
  messageRunProgressRunGroupId,
  messageRunProgressRunnableId,
  messageRunProgressRunnableKind,
  messageRunProgressTitle,
  messageRunStatus,
  messageSender,
} from '../messageState';
import { messageArtifactCount, messageArtifactTitle } from '../messageArtifacts';
import { messageWorkflowStudioAction } from '../messageWorkflowGuidance';
import {
  groupAgentSummaryNotice,
  groupAgentSummaryRunGroupId,
  groupAgentSummaryStatus,
  groupAgentSummaryTaskId,
  groupFollowupAgentMessageIdsAttribute,
  groupFollowupNotice,
  groupFollowupTaskIdsAttribute,
} from '../messageGroups';
import { participantDisplayName } from '../sessionState';
import type {
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  AssistantProfilePayload,
  ChatMessage,
} from '../types';
import type { ChatRunnableSummary as RunnableSummary } from '../runnables';
import { AgentRunProgressCard } from './AgentRunProgressCard';
import { messageAvatar } from './ChatAvatars';
import { MessageActivityList } from './MessageActivityList';
import { MessageAgentTaskCard } from './MessageAgentTaskCard';
import { MessageApprovalRequestCard } from './MessageApprovalRequestCard';

type MessageBubbleProps = {
  approvalBusy: boolean;
  assistantProfile: AssistantProfilePayload | null;
  assistantProfileLoading: boolean;
  copied: boolean;
  copiedCodeBlockKey: string;
  displayContent: string;
  formatTime: (value?: string) => string;
  highlighted: boolean;
  message: ChatMessage;
  publicTaskSnapshot?: AgentTaskSnapshot | null;
  retryDisabled: boolean;
  retrying: boolean;
  showRetry: boolean;
  onApprove: () => void;
  onApproveTaskApproval: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void;
  onCancelTask: (task: AgentTaskSnapshot) => void;
  onCopy: () => void;
  onOpenRunDetails: (runId: string | undefined, studioUrl?: string) => void;
  onOpenWorkflowStudio: (runnableId?: string, suggestedGoal?: string) => void;
  onReject: () => void;
  onRejectTaskApproval: (task: AgentTaskSnapshot, approval: ApprovalCardSnapshot) => void;
  onRetry: () => void;
  registerMessageNode: (messageId: string | undefined, node: HTMLElement | null) => void;
  runnables: RunnableSummary[];
};

export function MessageBubble({
  approvalBusy,
  assistantProfile,
  assistantProfileLoading,
  copied,
  copiedCodeBlockKey,
  displayContent,
  formatTime,
  highlighted,
  message,
  publicTaskSnapshot = null,
  retryDisabled,
  retrying,
  showRetry,
  onApprove,
  onApproveTaskApproval,
  onCancelTask,
  onCopy,
  onOpenRunDetails,
  onOpenWorkflowStudio,
  onReject,
  onRejectTaskApproval,
  onRetry,
  registerMessageNode,
  runnables,
}: MessageBubbleProps) {
  const role = message.role || 'system';
  const statusClass = message.status === 'failed'
    ? 'error'
    : message.status === 'processing'
      ? 'processing'
      : message.status === 'pending'
        ? 'pending'
        : '';
  const isProcessingEmpty = role === 'assistant' && message.status === 'processing' && !displayContent;
  const runId = messageRunId(message);
  const runStatus = messageRunStatus(message);
  const showApprovalActions = hasActionableApproval(message) && Boolean(runId);
  const approvalDetails = showApprovalActions ? approvalRequestDetails(message) : null;
  const approvalId = approvalDetails ? messageApprovalId(message) : '';
  const approvalSignature = approvalDetails ? messageApprovalSignature(message) : '';
  const showAgentProgress = isProcessingEmpty && messageHasRunContext(message);
  const progressSender = messageSender(message);
  const progressName = participantDisplayName(progressSender) || messageRoleLabel(message);
  const progressTitle = messageRunProgressTitle(message);
  const progressDetail = messageRunProgressDetail(message, progressName);
  const progressRunnableKind = messageRunProgressRunnableKind(message);
  const progressRunnableId = messageRunProgressRunnableId(message);
  const progressRunGroupId = messageRunProgressRunGroupId(message);
  const showInlineRunDetails = role === 'assistant' && Boolean(runId) && !approvalDetails && !showAgentProgress;
  const showPublicTaskCard = Boolean(publicTaskSnapshot);
  const showLegacyApprovalDetails = Boolean(approvalDetails && !showPublicTaskCard);
  const showLegacyAgentProgress = Boolean(showAgentProgress && !showPublicTaskCard);
  const artifactCount = messageArtifactCount(message);
  const duplicateError = Boolean(message.error && displayContent.trim() && message.error.trim() === displayContent.trim());
  const summaryNotice = groupAgentSummaryNotice(message);
  const followupNotice = groupFollowupNotice(message);
  const summaryTaskId = groupAgentSummaryTaskId(message);
  const summaryStatus = groupAgentSummaryStatus(message);
  const summaryRunGroupId = groupAgentSummaryRunGroupId(message);
  const followupTaskIds = groupFollowupTaskIdsAttribute(message);
  const followupAgentMessageIds = groupFollowupAgentMessageIdsAttribute(message);
  const workflowStudioAction = messageWorkflowStudioAction(message);

  return (
    <article
      className={`message message--${messageVisualRole(role)} refined-message ${role} ${statusClass}${highlighted ? ' search-highlighted' : ''}`}
      data-message-id={message.id || ''}
      ref={(node) => registerMessageNode(message.id, node)}
    >
      <div className="message-avatar">{messageAvatar(message, assistantProfile, assistantProfileLoading, runnables)}</div>
      <div className="message-stack">
        <div className="message-bubble">
          {showLegacyApprovalDetails && approvalDetails ? (
            <MessageApprovalRequestCard
              approvalId={approvalId}
              approvalSignature={approvalSignature}
              details={approvalDetails}
              onOpenDetails={() => onOpenRunDetails(runId)}
              renderCodePreview={(codeText, codeLanguage) => (
                renderMarkdown(fencedCode(codeText, codeLanguage), message.id || '', copiedCodeBlockKey)
              )}
              runId={runId}
              runStatus={runStatus}
            />
          ) : showLegacyAgentProgress ? (
            <AgentRunProgressCard
              detail={progressDetail}
              onOpenDetails={() => onOpenRunDetails(runId)}
              runGroupId={progressRunGroupId}
              runId={runId}
              runStatus={runStatus}
              runnableId={progressRunnableId}
              runnableKind={progressRunnableKind}
              title={progressTitle}
            />
          ) : isProcessingEmpty && !showPublicTaskCard ? (
            <TypingIndicator />
          ) : (
            <div className="message-content markdown" dangerouslySetInnerHTML={{ __html: renderMarkdown(displayContent, message.id || '', copiedCodeBlockKey) }} />
          )}
          {message.attachments?.length ? (
            <div className="message-attachments" data-testid="chat-message-attachments">
              {message.attachments.map((attachment) => (
                <ImageAttachmentViewer
                  attachment={attachment}
                  key={attachment.id || attachment.name}
                  testId="chat-message-attachment-item"
                />
              ))}
            </div>
          ) : null}
          {message.error && !duplicateError ? <div className="message-error">{message.error}</div> : null}
          {summaryNotice ? (
            <div
              className={`message-summary-status ${summaryNotice.tone}`}
              data-run-group-id={summaryRunGroupId}
              data-summary-status={summaryStatus}
              data-summary-task-id={summaryTaskId}
              data-testid="chat-message-summary-status"
              data-summary-tone={summaryNotice.tone}
            >
              {summaryNotice.text}
            </div>
          ) : null}
        </div>
        <MessageActivityList
          events={message.activity_events || []}
          formatTime={formatTime}
          messageStatus={message.status}
          onOpenRunDetails={onOpenRunDetails}
          progressLabel={message.progress_label}
        />
        <MessageAgentTaskCard
          busy={approvalBusy}
          displayContent={displayContent}
          hidden={Boolean(showLegacyApprovalDetails || showLegacyAgentProgress)}
          message={message}
          onApproveApproval={onApproveTaskApproval}
          onCancelTask={onCancelTask}
          onOpenStudio={onOpenRunDetails}
          onRejectApproval={onRejectTaskApproval}
          publicTaskSnapshot={publicTaskSnapshot}
        />
        {followupNotice ? (
          <div
            className="message-followup-status"
            data-followup-agent-message-ids={followupAgentMessageIds}
            data-followup-task-ids={followupTaskIds}
            data-testid="chat-message-followup-status"
          >
            {followupNotice}
          </div>
        ) : null}
        {showApprovalActions ? (
          <div
            className="message-approval-actions"
            data-approval-id={approvalId}
            data-approval-kind={approvalDetails && isWorkflowApprovalDetails(approvalDetails) ? 'workflow' : 'tool'}
            data-approval-requester={approvalDetails?.requester || ''}
            data-approval-signature={approvalSignature}
            data-approval-source="message"
            data-approval-tool={approvalDetails?.tool || ''}
            data-run-id={runId}
            data-testid="chat-message-approval-actions"
          >
            <button type="button" className="message-approval-approve" data-testid="chat-message-approval-approve" disabled={approvalBusy} onClick={onApprove}>
              {approvalBusy ? '处理中...' : '批准'}
            </button>
            <button type="button" className="message-approval-reject" data-testid="chat-message-approval-reject" disabled={approvalBusy} onClick={onReject}>
              拒绝
            </button>
          </div>
        ) : null}
        <div className="message-time">
          <span>{messageMetaText(message, formatTime, message.status, message.created_at)}</span>
          {artifactCount > 0 && runId ? (
            <button
              className="message-artifact-detail-button"
              type="button"
              title={messageArtifactTitle(message)}
              onClick={() => onOpenRunDetails(runId)}
            >
              产物 {artifactCount}
            </button>
          ) : null}
          {showInlineRunDetails ? (
            <button
              className="message-run-detail-button"
              type="button"
              data-run-id={runId}
              data-run-status={runStatus}
              data-testid="chat-message-open-run-detail"
              onClick={() => onOpenRunDetails(runId)}
            >
              Agent Studio
            </button>
          ) : null}
          {workflowStudioAction ? (
            <button
              className="message-run-detail-button"
              type="button"
              onClick={() => onOpenWorkflowStudio(
                workflowStudioAction.runnableId,
                workflowStudioAction.suggestedGoal,
              )}
            >
              {workflowStudioAction.label}
            </button>
          ) : null}
          {showRetry ? (
            <button
              className={`message-retry-button ${retrying ? 'retrying' : ''}`}
              type="button"
              data-testid="chat-message-retry"
              title={retrying ? '重试中' : '重试这条失败消息'}
              aria-label={retrying ? '重试中' : '重试这条失败消息'}
              disabled={retryDisabled}
              onClick={onRetry}
            >
              <UiIcon name="retry" />
            </button>
          ) : null}
          <button
            className={`message-copy-button ${copied ? 'copied' : ''}`}
            type="button"
            data-testid="chat-message-copy"
            title={copied ? '已复制' : '复制内容'}
            aria-label={copied ? '已复制' : '复制内容'}
            onClick={onCopy}
          >
            <UiIcon name={copied ? 'check' : 'copy'} />
          </button>
        </div>
      </div>
    </article>
  );
}

function TypingIndicator() {
  return (
    <span className="typing-indicator loading-dots" aria-label="处理中">
      <span className="loading-dot" /><span className="loading-dot" /><span className="loading-dot" />
    </span>
  );
}

function messageVisualRole(role: string) {
  if (role === 'user') return 'user';
  if (role === 'assistant') return 'agent';
  return 'system';
}

function messageMetaText(message: ChatMessage, formatTime: (value?: string) => string, status?: string, createdAt?: string) {
  const runStatus = messageRunStatus(message);
  const hasRunContext = messageHasRunContext(message);
  const statusText = status === 'pending'
    ? ' · 等待中'
    : runStatus === 'approval_required'
      ? ' · 等待审批'
      : status === 'processing'
        ? hasRunContext ? ' · 处理中' : ' · 输入中'
        : status === 'failed'
          ? ' · 失败'
          : '';
  const timeText = formatTime(createdAt);
  return `${messageRoleLabel(message)}${timeText !== '—' ? ` · ${timeText}` : ''}${statusText}`;
}
