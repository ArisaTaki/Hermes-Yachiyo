import { useState } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { navigateTo } from '../../../lib/view';

export type MessageActivityEvent = {
  event_id?: string;
  task_id?: string;
  tool_name?: string;
  title?: string;
  detail?: string;
  status?: string;
  created_at?: string;
  metadata?: {
    run_id?: string;
    workflow_run_id?: string;
  } & Record<string, unknown>;
};

export function MessageActivityList({
  events,
  formatTime,
  messageStatus,
  onOpenRunDetails,
  progressLabel,
}: {
  events: MessageActivityEvent[];
  formatTime: (value?: string) => string;
  messageStatus?: string;
  onOpenRunDetails: (runId: string) => void;
  progressLabel?: string;
}) {
  const [expandedEventIds, setExpandedEventIds] = useState<Set<string>>(() => new Set());
  const rows = events.slice(0, 4);
  const fallback = progressLabel && !rows.length
    ? [{ title: progressLabel, status: messageStatus || 'running' } as MessageActivityEvent]
    : [];
  const visibleRows = rows.length ? rows : fallback;
  if (!visibleRows.length) return null;

  function toggleExpanded(eventKey: string) {
    setExpandedEventIds((current) => {
      const next = new Set(current);
      if (next.has(eventKey)) next.delete(eventKey);
      else next.add(eventKey);
      return next;
    });
  }

  function openActivity(event: MessageActivityEvent) {
    if (event.event_id) {
      navigateTo('activity-detail', { event_id: event.event_id });
      return;
    }
    navigateTo('activity-all');
  }

  return (
    <div className="message-activity-list" data-testid="chat-message-activity-list" aria-label="执行活动">
      {visibleRows.map((event, index) => {
        const displayStatus = activityDisplayStatus(event.status, messageStatus);
        const runId = activityRunId(event);
        const eventKey = activityEventKey(event, index);
        const metadataText = formatActivityMetadata(event.metadata);
        const canExpand = Boolean(event.detail || metadataText);
        const expanded = expandedEventIds.has(eventKey);
        return (
          <div
            className={`message-activity-row ${activityStatusClass(displayStatus)}${runId ? ' has-detail' : ''}${expanded ? ' expanded' : ''}`}
            data-activity-status={displayStatus || ''}
            data-activity-tool={event.tool_name || ''}
            data-run-id={runId || ''}
            data-run-status={displayStatus || ''}
            data-testid="chat-message-activity-row"
            key={eventKey}
          >
            <span className="message-activity-icon" aria-hidden="true">{activityStatusIcon(displayStatus)}</span>
            <div className="message-activity-text">
              <div className="message-activity-heading">
                <strong>{event.title || event.tool_name || 'Native 活动'}</strong>
                {event.event_id ? (
                  <button
                    type="button"
                    className="message-activity-link"
                    data-testid="chat-message-activity-open"
                    title="打开活动详情"
                    aria-label="打开活动详情"
                    onClick={() => openActivity(event)}
                  >
                    <UiIcon name="activity" />
                    <span>详情</span>
                  </button>
                ) : null}
                {canExpand ? (
                  <button
                    type="button"
                    className="message-activity-link"
                    data-testid="chat-message-activity-toggle"
                    title={expanded ? '收起调用记录' : '展开调用记录'}
                    aria-label={expanded ? '收起调用记录' : '展开调用记录'}
                    onClick={() => toggleExpanded(eventKey)}
                  >
                    <UiIcon name={expanded ? 'close' : 'plus'} />
                    <span>{expanded ? '收起' : '展开'}</span>
                  </button>
                ) : null}
              </div>
              {event.detail ? <small>{event.detail}</small> : null}
              {expanded ? (
                <div className="message-activity-expanded">
                  {event.detail ? <span>{event.detail}</span> : null}
                  {metadataText ? <pre>{metadataText}</pre> : null}
                </div>
              ) : null}
            </div>
            <time>{formatTime(event.created_at)}</time>
            {runId ? (
              <button
                type="button"
                className="message-activity-detail-button"
                data-run-id={runId}
                data-run-status={displayStatus || ''}
                data-testid="chat-message-activity-open-run-detail"
                onClick={() => onOpenRunDetails(runId)}
              >
                详情
              </button>
            ) : null}
          </div>
        );
      })}
    </div>
  );
}

function activityEventKey(event: MessageActivityEvent, index: number) {
  return event.event_id || `${event.created_at || 'activity'}-${event.task_id || event.title || index}-${index}`;
}

function formatActivityMetadata(metadata?: Record<string, unknown>) {
  if (!metadata || !Object.keys(metadata).length) return '';
  try {
    return JSON.stringify(metadata, null, 2);
  } catch {
    return '';
  }
}

function activityRunId(event?: MessageActivityEvent | null) {
  return String(event?.metadata?.run_id || event?.metadata?.workflow_run_id || '').trim();
}

function activityStatusClass(status?: string) {
  if (status === 'completed' || status === 'success') return 'completed';
  if (status === 'failed' || status === 'error') return 'failed';
  if (status === 'approval_required') return 'approval';
  if (status === 'progress' || status === 'running') return 'running';
  return 'status';
}

function activityStatusIcon(status?: string) {
  if (status === 'completed' || status === 'success') return '✓';
  if (status === 'failed' || status === 'error') return '!';
  if (status === 'approval_required') return '!';
  return '';
}

function activityDisplayStatus(eventStatus?: string, messageStatus?: string) {
  if (
    (messageStatus === 'completed' || messageStatus === 'failed')
    && (!eventStatus || eventStatus === 'running' || eventStatus === 'progress' || eventStatus === 'status')
  ) {
    return messageStatus;
  }
  return eventStatus;
}
