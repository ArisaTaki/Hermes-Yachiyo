import { UiIcon } from '../../../components/UiIcon';
import { navigateTo } from '../../../lib/view';
import { studioRunUrl } from '../../runtime-shared/studioLinks';

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
    run_group_id?: string;
    group_dispatch_run_group_id?: string;
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
  onOpenRunDetails: (runId: string, studioUrl?: string) => void;
  progressLabel?: string;
}) {
  const rows = events.slice(0, 4);
  const fallback = progressLabel && !rows.length
    ? [{ title: progressLabel, status: messageStatus || 'running' } as MessageActivityEvent]
    : [];
  const visibleRows = rows.length ? rows : fallback;
  if (!visibleRows.length) return null;

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
        const groupRunId = activityGroupRunId(event);
        const studioUrl = runId ? studioRunUrl(runId, { groupRunId }) || '' : '';
        const eventKey = activityEventKey(event, index);
        return (
          <div
            className={`message-activity-row ${activityStatusClass(displayStatus)}${runId ? ' has-detail' : ''}`}
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
              </div>
              {event.detail ? <small>{event.detail}</small> : null}
            </div>
            <time>{formatTime(event.created_at)}</time>
            {runId ? (
              <button
                type="button"
                className="message-activity-detail-button"
                data-run-id={runId}
                data-run-status={displayStatus || ''}
                data-studio-url={studioUrl}
                data-testid="chat-message-activity-open-run-detail"
                onClick={() => onOpenRunDetails(runId, studioUrl)}
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

function activityRunId(event?: MessageActivityEvent | null) {
  return String(event?.metadata?.run_id || event?.metadata?.workflow_run_id || '').trim();
}

function activityGroupRunId(event?: MessageActivityEvent | null) {
  return String(event?.metadata?.run_group_id || event?.metadata?.group_dispatch_run_group_id || '').trim();
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
