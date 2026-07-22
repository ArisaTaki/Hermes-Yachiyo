import { useMemo } from 'react';

import { ImageAttachmentViewer } from '../../../components/ImageAttachmentViewer';
import { UiIcon } from '../../../components/UiIcon';
import {
  approvalRequestDetails,
  hasActionableApproval,
  hasPendingApproval,
  isWorkflowApprovalDetails,
  messageApprovalId,
  messageApprovalSignature,
  type ComposerApprovalItem,
} from '../approvalItems';
import {
  consumerFailureText,
  consumerMessageFailurePresentation,
} from '../consumerFailure';
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
import {
  agentTaskHasVisibleExecution,
  agentTaskSnapshotFromMessage,
} from '../taskSnapshots';
import type {
  AgentTaskSnapshot,
  ApprovalCardSnapshot,
  AssistantProfilePayload,
  ChatMessage,
} from '../types';
import type { ChatRunnableSummary as RunnableSummary } from '../runnables';
import type { TaskPermissionRecoveryAction } from '../taskPermissionRecovery';
import { AgentRunProgressCard } from './AgentRunProgressCard';
import { chatTaskHasRunnableRecoveryAction } from './AgentTaskCard';
import { messageAvatar } from './ChatAvatars';
import { MessageActivityList } from './MessageActivityList';
import { MessageAgentTaskCard } from './MessageAgentTaskCard';
import { MessageApprovalRequestCard } from './MessageApprovalRequestCard';

const CHAT_TECHNICAL_EXECUTION_VISIBLE = false;

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
  fallbackApprovalItem?: ComposerApprovalItem | null;
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
  onRunTaskRecoveryAction?: (task: AgentTaskSnapshot, action: TaskPermissionRecoveryAction) => void;
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
  fallbackApprovalItem = null,
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
  onRunTaskRecoveryAction,
  registerMessageNode,
  runnables,
}: MessageBubbleProps) {
  const role = message.role || 'system';
  const runStatus = messageRunStatus(message);
  const messageCancelledByRunStatus = ['cancelled', 'canceled'].includes(runStatus);
  const hasConsumerFailure = (
    !messageCancelledByRunStatus
    && (
      ['failed', 'cancelled', 'canceled'].includes(String(message.status || '').toLowerCase())
      || Boolean(message.error)
    )
  );
  const failurePresentation = hasConsumerFailure
    ? consumerMessageFailurePresentation(message, displayContent)
    : null;
  const visibleDisplayContent = failurePresentation && role !== 'user'
    ? consumerFailureText(failurePresentation)
    : displayContent;
  const visibleMessageError = failurePresentation && role === 'user'
    ? failurePresentation.detail
    : '';
  const retryActionLabel = message.metadata?.client_optimistic === true
    ? '确认/重试投递'
    : '重试这条失败消息';
  const effectiveMessageStatus = messageCancelledByRunStatus ? 'cancelled' : String(message.status || '');
  const statusClass = effectiveMessageStatus === 'failed'
    ? 'error'
    : effectiveMessageStatus === 'processing'
      ? 'processing'
      : effectiveMessageStatus === 'pending'
        ? 'pending'
        : '';
  const isProcessingEmpty = role === 'assistant' && effectiveMessageStatus === 'processing' && !visibleDisplayContent;
  const runId = messageRunId(message);
  const showMessageApprovalDetails = hasPendingApproval(message) && Boolean(runId);
  const fallbackApproval = showMessageApprovalDetails ? null : fallbackApprovalItem;
  const approvalRunId = fallbackApproval?.runId || runId;
  const approvalRunStatus = fallbackApproval?.runStatus || runStatus;
  const approvalDetails = showMessageApprovalDetails
    ? approvalRequestDetails(message)
    : fallbackApproval?.details || null;
  const approvalId = showMessageApprovalDetails
    ? messageApprovalId(message)
    : String(fallbackApproval?.approvalId || '').trim();
  const approvalSignature = showMessageApprovalDetails
    ? messageApprovalSignature(message)
    : fallbackApproval?.id || '';
  const messageTaskSnapshot = agentTaskSnapshotFromMessage(message, displayContent);
  const publicTaskHasVisibleExecution = agentTaskHasVisibleExecution(publicTaskSnapshot);
  const messageTaskHasVisibleExecution = agentTaskHasVisibleExecution(messageTaskSnapshot, message);
  const visibleAgentTaskSnapshot = publicTaskHasVisibleExecution
    ? publicTaskSnapshot
    : messageTaskHasVisibleExecution ? messageTaskSnapshot : null;
  const hasVisibleAgentExecution = publicTaskHasVisibleExecution || messageTaskHasVisibleExecution;
  const showAgentProgress = isProcessingEmpty && messageHasRunContext(message) && hasVisibleAgentExecution;
  const progressSender = messageSender(message);
  const progressName = participantDisplayName(progressSender) || messageRoleLabel(message);
  const progressTitle = messageRunProgressTitle(message);
  const progressDetail = messageRunProgressDetail(message, progressName);
  const progressRunnableKind = messageRunProgressRunnableKind(message);
  const progressRunnableId = messageRunProgressRunnableId(message);
  const progressRunGroupId = messageRunProgressRunGroupId(message);
  const showInlineRunDetails = CHAT_TECHNICAL_EXECUTION_VISIBLE
    && role === 'assistant'
    && Boolean(runId)
    && !approvalDetails
    && !showAgentProgress
    && hasVisibleAgentExecution;
  const showPublicTaskCard = Boolean(
    publicTaskSnapshot && publicTaskHasVisibleExecution,
  );
  const showCanonicalTaskApproval = Boolean(
    publicTaskSnapshot?.pending_approvals?.some((approval) => {
      if ((approval.status || 'pending') !== 'pending') return false;
      const taskApprovalId = String(approval.approval_id || '').trim();
      return approvalId ? taskApprovalId === approvalId : Boolean(taskApprovalId);
    }),
  );
  const showApprovalActions = (hasActionableApproval(message) || Boolean(fallbackApproval && approvalId))
    && Boolean(approvalRunId)
    && !showCanonicalTaskApproval;
  const showLegacyApprovalDetails = Boolean(approvalDetails && !showCanonicalTaskApproval);
  const showLegacyAgentProgress = Boolean(showAgentProgress && !showPublicTaskCard);
  const showAgentTaskCard = Boolean(
    role === 'assistant'
    && visibleAgentTaskSnapshot
    && !showLegacyApprovalDetails
    && !showLegacyAgentProgress
  );
  const taskRecoveryReplacesMessageRetry = Boolean(
    showAgentTaskCard
    && onRunTaskRecoveryAction
    && visibleAgentTaskSnapshot
    && chatTaskHasRunnableRecoveryAction(visibleAgentTaskSnapshot)
  );
  const showMessageRetry = showRetry && !taskRecoveryReplacesMessageRetry;
  const artifactCount = messageArtifactCount(message);
  const summaryNotice = groupAgentSummaryNotice(message);
  const summaryFailurePresentation = summaryNotice?.tone === 'failed'
    ? consumerMessageFailurePresentation(
      { ...message, status: 'failed', error: summaryNotice.text },
      summaryNotice.text,
    )
    : null;
  const visibleSummaryNoticeText = summaryFailurePresentation
    ? consumerFailureText(summaryFailurePresentation)
    : summaryNotice?.text || '';
  const followupNotice = groupFollowupNotice(message);
  const summaryTaskId = groupAgentSummaryTaskId(message);
  const summaryStatus = groupAgentSummaryStatus(message);
  const summaryRunGroupId = groupAgentSummaryRunGroupId(message);
  const followupTaskIds = groupFollowupTaskIdsAttribute(message);
  const followupAgentMessageIds = groupFollowupAgentMessageIdsAttribute(message);
  const workflowStudioAction = messageWorkflowStudioAction(message);
  const renderedMessageContent = useMemo(
    () => renderMarkdown(visibleDisplayContent, message.id || '', copiedCodeBlockKey),
    [copiedCodeBlockKey, message.id, visibleDisplayContent],
  );

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
              onOpenDetails={() => onOpenRunDetails(approvalRunId)}
              renderCodePreview={(codeText, codeLanguage) => (
                renderMarkdown(fencedCode(codeText, codeLanguage), message.id || '', copiedCodeBlockKey)
              )}
              runId={approvalRunId}
              runStatus={approvalRunStatus}
              showTechnicalDetails={CHAT_TECHNICAL_EXECUTION_VISIBLE}
            />
          ) : showLegacyAgentProgress ? (
            <AgentRunProgressCard
              detail={CHAT_TECHNICAL_EXECUTION_VISIBLE ? progressDetail : '正在处理你的请求'}
              onOpenDetails={() => onOpenRunDetails(runId)}
              runGroupId={progressRunGroupId}
              runId={runId}
              runStatus={runStatus}
              runnableId={progressRunnableId}
              runnableKind={progressRunnableKind}
              showTechnicalDetails={CHAT_TECHNICAL_EXECUTION_VISIBLE}
              title={CHAT_TECHNICAL_EXECUTION_VISIBLE ? progressTitle : '正在处理'}
            />
          ) : isProcessingEmpty ? (
            <TypingIndicator />
          ) : failurePresentation && role !== 'user' ? (
            <div
              className="message-content markdown"
              data-testid="chat-message-failure-detail"
              dangerouslySetInnerHTML={{ __html: renderedMessageContent }}
            />
          ) : (
            <div className="message-content markdown" dangerouslySetInnerHTML={{ __html: renderedMessageContent }} />
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
          {visibleMessageError ? <div className="message-error">{visibleMessageError}</div> : null}
          {summaryNotice ? (
            <div
              className={`message-summary-status ${summaryNotice.tone}`}
              data-run-group-id={summaryRunGroupId}
              data-summary-status={summaryStatus}
              data-summary-task-id={summaryTaskId}
              data-testid="chat-message-summary-status"
              data-summary-tone={summaryNotice.tone}
            >
              {visibleSummaryNoticeText}
            </div>
          ) : null}
        </div>
        {CHAT_TECHNICAL_EXECUTION_VISIBLE && hasVisibleAgentExecution
        && !showAgentTaskCard && !showLegacyAgentProgress
        && !showLegacyApprovalDetails ? (
          <MessageActivityList
            events={message.activity_events || []}
            formatTime={formatTime}
            messageStatus={message.status}
            onOpenRunDetails={onOpenRunDetails}
            progressLabel={message.progress_label}
          />
        ) : null}
        <MessageAgentTaskCard
          busy={approvalBusy}
          displayContent={displayContent}
          hidden={Boolean(showLegacyApprovalDetails || showLegacyAgentProgress)}
          message={message}
          onApproveApproval={onApproveTaskApproval}
          onCancelTask={onCancelTask}
          onOpenStudio={onOpenRunDetails}
          onRejectApproval={onRejectTaskApproval}
          onRunRecoveryAction={onRunTaskRecoveryAction}
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
            data-approval-source={fallbackApproval?.source || 'message'}
            data-approval-tool={approvalDetails?.tool || ''}
            data-run-id={approvalRunId}
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
          <span>{messageMetaText(message, formatTime, effectiveMessageStatus, message.created_at)}</span>
          {artifactCount > 0 && runId ? (
            <button
              className="message-artifact-detail-button"
              type="button"
              data-testid="chat-message-open-artifacts"
              title={messageArtifactTitle(message)}
              onClick={() => onOpenRunDetails(runId)}
            >
              查看全部结果（{artifactCount}）
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
          {failurePresentation?.kind === 'unknown' && runId ? (
            <button
              className="message-run-detail-button"
              type="button"
              data-testid="chat-message-failure-open-detail"
              onClick={() => onOpenRunDetails(runId)}
            >
              查看详情
            </button>
          ) : null}
          {CHAT_TECHNICAL_EXECUTION_VISIBLE && workflowStudioAction ? (
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
          {showMessageRetry ? (
            <button
              className={`message-retry-button ${retrying ? 'retrying' : ''}`}
              type="button"
              data-testid="chat-message-retry"
              title={retrying ? '重试中' : retryActionLabel}
              aria-label={retrying ? '重试中' : retryActionLabel}
              disabled={retryDisabled}
              onClick={onRetry}
            >
              <UiIcon name="retry" />
            </button>
          ) : null}
          {failurePresentation && role !== 'user' ? null : (
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
          )}
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
      : status === 'cancelled' || status === 'canceled'
        ? ' · 已取消'
      : status === 'processing'
        ? hasRunContext ? ' · 处理中' : ' · 输入中'
        : status === 'failed'
          ? ' · 失败'
          : '';
  const timeText = formatTime(createdAt);
  return `${messageRoleLabel(message)}${timeText !== '—' ? ` · ${timeText}` : ''}${statusText}`;
}
