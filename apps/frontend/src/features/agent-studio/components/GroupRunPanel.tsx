import { useCallback, useEffect, useState } from 'react';

import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import { RuntimeArtifactList } from '../../runtime-shared/components/RuntimeArtifactList';
import { RuntimeDebugSummary } from '../../runtime-shared/components/RuntimeDebugSummary';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import { listYachiyoGroupRunEvents } from '../../yachiyo-studio/api';
import type { GroupRunSnapshot, RunEventPageSnapshot } from '../../yachiyo-studio/types';
import { runStatusLabel, runStatusTone } from '../utils/runs';

type GroupRunPanelProps = {
  agentGroupRunGoal: string;
  busy: boolean;
  latestAgentGroupRun: GroupRunSnapshot | null;
  selectedAgentGroupId: string;
  onAgentGroupRunGoalChange: (value: string) => void;
  onOpenArtifact?: (runId: string, path: string) => Promise<void> | void;
  onOpenAgentGroupRunTimeline: (groupRun: GroupRunSnapshot) => void;
  onRunAgentGroup: () => void;
};

export function GroupRunPanel({
  agentGroupRunGoal,
  busy,
  latestAgentGroupRun,
  selectedAgentGroupId,
  onAgentGroupRunGoalChange,
  onOpenArtifact,
  onOpenAgentGroupRunTimeline,
  onRunAgentGroup,
}: GroupRunPanelProps) {
  const [groupRunEventPage, setGroupRunEventPage] = useState<RunEventPageSnapshot | null>(null);
  const [groupRunEventError, setGroupRunEventError] = useState('');
  const [groupRunEventLoading, setGroupRunEventLoading] = useState(false);
  const latestGroupRunId = latestAgentGroupRun?.group_run_id || '';
  const latestGroupRunUpdatedAt = latestAgentGroupRun?.updated_at || '';
  useEffect(() => {
    if (!latestGroupRunId) {
      setGroupRunEventPage(null);
      setGroupRunEventError('');
      setGroupRunEventLoading(false);
      return;
    }
    let disposed = false;
    setGroupRunEventError('');
    listYachiyoGroupRunEvents(latestGroupRunId, 0, 25)
      .then((page) => {
        if (!disposed) setGroupRunEventPage(page);
      })
      .catch(() => {
        if (!disposed) {
          setGroupRunEventPage(null);
          setGroupRunEventError('GroupRun events 暂时不可用。');
        }
      });
    return () => {
      disposed = true;
    };
  }, [latestGroupRunId, latestGroupRunUpdatedAt]);

  const loadMoreGroupRunEvents = useCallback(async () => {
    if (!latestGroupRunId || !groupRunEventPage?.has_more || groupRunEventLoading) return;
    setGroupRunEventLoading(true);
    setGroupRunEventError('');
    try {
      const page = await listYachiyoGroupRunEvents(
        latestGroupRunId,
        groupRunEventPage.next_after_sequence,
        25,
      );
      setGroupRunEventPage((current) => (
        current && current.run_id === latestGroupRunId
          ? mergeGroupRunEventPages(current, page)
          : page
      ));
    } catch {
      setGroupRunEventError('加载更多 GroupRun events 失败。');
    } finally {
      setGroupRunEventLoading(false);
    }
  }, [groupRunEventLoading, groupRunEventPage, latestGroupRunId]);

  const latestEvents = groupRunEventPage?.events ?? latestAgentGroupRun?.events ?? [];
  const groupRunEventDisplayLimit = groupRunEventPage
    ? Math.max(4, groupRunEventPage.events.length)
    : 4;
  const latestStatus = latestAgentGroupRun?.status || 'unknown';
  const pendingApprovals = latestAgentGroupRun?.pending_approvals || [];
  const sharedArtifacts = latestAgentGroupRun?.shared_artifacts || [];
  return (
    <section className="group-run-panel" data-testid="agent-group-run-panel">
      <label>
        <span>Run 目标</span>
        <textarea
          className="hy-input"
          rows={4}
          value={agentGroupRunGoal}
          onChange={(event) => onAgentGroupRunGoalChange(event.target.value)}
        />
      </label>
      <div className="studio-heading-actions">
        <button type="button" className="primary-action" data-testid="agent-group-run" disabled={busy || !selectedAgentGroupId || !agentGroupRunGoal.trim()} onClick={onRunAgentGroup}>启动 Run</button>
        {latestAgentGroupRun ? (
          <button type="button" data-testid="agent-group-open-run" disabled={busy} onClick={() => onOpenAgentGroupRunTimeline(latestAgentGroupRun)}>打开 Run Timeline</button>
        ) : null}
      </div>
      {latestAgentGroupRun ? (
        <div
          className="group-run-latest"
          data-runtime-capability-id={latestAgentGroupRun.runtime_debug?.current_capability_id || ''}
          data-runtime-deferred-tool={latestAgentGroupRun.runtime_debug?.latest_deferred_tool || ''}
          data-runtime-doctrine={latestAgentGroupRun.runtime_debug?.runtime_doctrine || ''}
          data-runtime-replan-request-id={latestAgentGroupRun.runtime_debug?.latest_replan_request_id || ''}
          data-runtime-role={latestAgentGroupRun.runtime_debug?.runtime_role || ''}
          data-runtime-stage={latestAgentGroupRun.runtime_debug?.runtime_stage || ''}
          data-testid="agent-group-run-latest"
        >
          <div className="group-run-latest-head">
            <strong>{latestAgentGroupRun.title || latestAgentGroupRun.objective || 'Group Run'}</strong>
            <span className={`run-status-pill ${runStatusTone(latestStatus)}`}>
              {runStatusLabel(latestStatus)}
            </span>
          </div>
          <RuntimeDebugSummary
            className="group-run-latest-runtime-debug"
            compact
            sourceLabel="GroupRun latest"
            summary={latestAgentGroupRun.runtime_debug}
            testId="agent-group-run-runtime-debug"
          />
          {latestEvents.length ? (
            <RuntimeTimelineSummary
              className="group-run-event-summary"
              events={latestEvents}
              limit={groupRunEventDisplayLimit}
              testId="agent-group-run-event-summary"
            />
          ) : null}
          {groupRunEventPage ? (
            <div
              className="group-run-event-page-meta"
              data-testid="agent-group-run-event-page-meta"
            >
              <span>events {groupRunEventPage.events.length}</span>
              <span>cursor {groupRunEventPage.next_after_sequence}</span>
              {groupRunEventPage.has_more ? <span>more</span> : null}
            </div>
          ) : null}
          {groupRunEventError ? (
            <div className="group-run-event-page-error" data-testid="agent-group-run-event-page-error">
              {groupRunEventError}
            </div>
          ) : null}
          {groupRunEventPage?.has_more ? (
            <div className="group-run-event-page-actions">
              <button
                type="button"
                data-testid="agent-group-run-load-more-events"
                disabled={busy || groupRunEventLoading}
                onClick={() => void loadMoreGroupRunEvents()}
              >
                {groupRunEventLoading ? '加载中...' : '加载更多事件'}
              </button>
            </div>
          ) : null}
          {pendingApprovals.length ? (
            <section
              className="group-run-runtime-section"
              data-testid="agent-group-run-approvals"
            >
              <div className="group-run-runtime-section-head">
                <strong>Pending Approvals</strong>
                <span>{pendingApprovals.length}</span>
              </div>
              <div className="group-run-approval-list">
                {pendingApprovals.map((approval) => (
                  <RuntimeApprovalCard
                    approval={approval}
                    className="studio-runtime-approval group-run-approval-card"
                    key={approval.approval_id}
                    testId="agent-group-run-approval-card"
                    variant="inspector"
                  />
                ))}
              </div>
            </section>
          ) : null}
          {sharedArtifacts.length ? (
            <section
              className="group-run-runtime-section"
              data-testid="agent-group-run-artifacts"
            >
              <div className="group-run-runtime-section-head">
                <strong>Shared Artifacts</strong>
                <span>{sharedArtifacts.length}</span>
              </div>
              <RuntimeArtifactList
                artifacts={sharedArtifacts}
                className="group-run-artifact-list"
                fallbackRunId={latestGroupRunId}
                itemTestId="agent-group-run-artifact-item"
                onOpenArtifact={onOpenArtifact}
                previewClassName="studio-runtime-artifact group-run-artifact-card"
                previewTestId="agent-group-run-artifact-preview"
                previewVariant="full"
                testId="agent-group-run-artifact-list"
              />
            </section>
          ) : null}
        </div>
      ) : null}
    </section>
  );
}

function mergeGroupRunEventPages(
  current: RunEventPageSnapshot,
  next: RunEventPageSnapshot,
): RunEventPageSnapshot {
  const eventsByKey = new Map<string, RunEventPageSnapshot['events'][number]>();
  [...current.events, ...next.events].forEach((event) => {
    const key = [
      event.event_id || '',
      event.run_id || '',
      event.sequence,
      event.event_type,
    ].join(':');
    if (!eventsByKey.has(key)) eventsByKey.set(key, event);
  });
  return {
    ...next,
    after_sequence: current.after_sequence,
    events: Array.from(eventsByKey.values()),
  };
}
