import type { RunGroupSpec, RunSpec } from '../types';
import type { GroupRunSnapshot, PublicRunEvent } from '../../yachiyo-studio/types';
import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import { RuntimeArtifactList } from '../../runtime-shared/components/RuntimeArtifactList';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import {
  approvalsFromRunEventReplay,
  artifactsFromRunEventReplay,
  mergeApprovalSnapshots,
  mergeArtifactSnapshots,
} from '../utils/runTimeline';

type GroupRunDetailPanelProps = {
  formatRunDate: (value?: string) => string;
  onLoadMoreGroupRunEvents: () => Promise<unknown> | unknown;
  onOpenRunDetail: (runId: string) => void;
  replayError: string;
  replayEvents: PublicRunEvent[];
  replayHasMore: boolean;
  replayLoading: boolean;
  replayNextAfterSequence: number;
  runById: Map<string, RunSpec>;
  runKindLabel: (kind: string) => string;
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedGroupRunSnapshot: GroupRunSnapshot | null;
  selectedRouteGroupRunId: string;
  selectedRun: RunSpec;
  selectedRunGroup: RunGroupSpec | null;
};

export function GroupRunDetailPanel({
  formatRunDate,
  onLoadMoreGroupRunEvents,
  onOpenRunDetail,
  replayError,
  replayEvents,
  replayHasMore,
  replayLoading,
  replayNextAfterSequence,
  runById,
  runKindLabel,
  runStatusLabel,
  runStatusTone,
  selectedGroupRunSnapshot,
  selectedRouteGroupRunId,
  selectedRun,
  selectedRunGroup,
}: GroupRunDetailPanelProps) {
  if (!selectedRunGroup && !selectedGroupRunSnapshot) return null;

  const groupOverviewId = selectedRunGroup?.run_group_id
    || selectedGroupRunSnapshot?.run_group_id
    || selectedGroupRunSnapshot?.group_run_id
    || '';
  const groupOverviewChildRunIds = selectedRunGroup?.child_run_ids?.length
    ? selectedRunGroup.child_run_ids
    : selectedGroupRunSnapshot?.child_run_ids || [];
  const groupOverviewStatus = selectedGroupRunSnapshot?.status || selectedRunGroup?.status || 'unknown';
  const groupOverviewTitle = selectedRunGroup?.summary
    || selectedGroupRunSnapshot?.title
    || selectedGroupRunSnapshot?.objective
    || selectedRunGroup?.title
    || selectedRunGroup?.objective
    || 'No GroupRun summary recorded.';
  const groupRunObjective = selectedGroupRunSnapshot?.objective || selectedRunGroup?.objective || '';
  const groupRunParticipants = selectedGroupRunSnapshot?.participants?.length
    ? selectedGroupRunSnapshot.participants
    : selectedRunGroup?.participants || [];
  const groupRunEvents = selectedGroupRunSnapshot?.events?.length
    ? selectedGroupRunSnapshot.events
    : selectedRunGroup?.events || [];
  const groupRunReplayEvents = replayEvents.length ? replayEvents : groupRunEvents;
  const groupRunReplaySource = replayEvents.length ? 'RunEvent replay facts' : 'GroupRunSnapshot events';
  const groupRunApprovals = selectedGroupRunSnapshot?.pending_approvals?.length
    ? selectedGroupRunSnapshot.pending_approvals
    : selectedRunGroup?.pending_approvals || [];
  const groupRunArtifacts = selectedGroupRunSnapshot?.shared_artifacts?.length
    ? selectedGroupRunSnapshot.shared_artifacts
    : selectedRunGroup?.shared_artifacts || [];
  const replayApprovals = replayEvents.length ? approvalsFromRunEventReplay(replayEvents) : [];
  const replayArtifacts = replayEvents.length ? artifactsFromRunEventReplay(replayEvents) : [];
  const groupRunApprovalFacts = mergeApprovalSnapshots(groupRunApprovals, replayApprovals);
  const groupRunArtifactFacts = mergeArtifactSnapshots(groupRunArtifacts, replayArtifacts);
  const groupRunFinalAnswer = selectedGroupRunSnapshot?.final_answer || selectedRunGroup?.final_answer || '';

  return (
    <section
      className="run-detail-block run-group-overview"
      data-group-run-id={selectedGroupRunSnapshot?.group_run_id || ''}
      data-run-group-id={groupOverviewId}
      data-route-group-run-id={selectedRouteGroupRunId}
      data-testid="agent-run-detail-group-run-overview"
    >
      <div className="run-detail-section-head">
        <div>
          <h4>GroupRun Overview</h4>
          <span>
            {selectedRunGroup?.source || selectedGroupRunSnapshot?.group_id || 'group'} · {groupOverviewChildRunIds.length} child runs
          </span>
        </div>
        <span className={`run-status-pill ${runStatusTone(groupOverviewStatus)}`}>
          {runStatusLabel(groupOverviewStatus)}
        </span>
      </div>
      <p>{groupOverviewTitle}</p>
      <div className="run-group-overview-meta" data-testid="agent-run-detail-group-run-meta">
        {groupOverviewId ? <code>{groupOverviewId}</code> : null}
        {selectedRouteGroupRunId ? (
          <span data-testid="agent-run-detail-group-run-route">Deep link {selectedRouteGroupRunId}</span>
        ) : null}
        {selectedGroupRunSnapshot?.group_run_id ? <code>GroupRun {selectedGroupRunSnapshot.group_run_id}</code> : null}
        {groupRunObjective ? <span>Objective {groupRunObjective}</span> : null}
        {selectedGroupRunSnapshot?.updated_at || selectedGroupRunSnapshot?.created_at || selectedRunGroup?.updated_at || selectedRunGroup?.created_at ? (
          <span>Updated {formatRunDate(
            selectedGroupRunSnapshot?.updated_at
            || selectedGroupRunSnapshot?.created_at
            || selectedRunGroup?.updated_at
            || selectedRunGroup?.created_at,
          )}</span>
        ) : null}
        {selectedRunGroup?.workspace_dir ? <span>{selectedRunGroup.workspace_dir}</span> : null}
      </div>
      {groupRunParticipants.length ? (
        <div className="run-group-overview-participants" data-testid="agent-run-detail-group-run-participants">
          {groupRunParticipants.map((participant) => (
            <span
              data-agent-id={participant.agent_id}
              data-testid="agent-run-detail-group-run-participant"
              key={participant.agent_id}
            >
              {participant.name || participant.agent_id}
            </span>
          ))}
        </div>
      ) : null}
      {groupRunReplayEvents.length || replayLoading || replayError ? (
        <section className="group-run-runtime-section" data-testid="agent-run-detail-group-run-replay">
          <div className="group-run-runtime-section-head">
            <strong>GroupRun Events</strong>
            <span>
              {groupRunReplaySource}
              {replayNextAfterSequence ? ` · cursor ${replayNextAfterSequence}` : ''}
            </span>
          </div>
          {groupRunReplayEvents.length ? (
            <RuntimeTimelineSummary
              className="group-run-event-summary run-group-overview-events"
              events={groupRunReplayEvents}
              limit={6}
              testId="agent-run-detail-group-run-events"
            />
          ) : null}
          <div className="run-timeline-replay-controls" data-testid="agent-run-detail-group-run-replay-controls">
            {replayError ? <span className="run-replay-error">{replayError}</span> : null}
            <button
              type="button"
              disabled={replayLoading || (!replayHasMore && !replayError)}
              data-testid="agent-run-detail-group-run-load-more-events"
              onClick={() => void onLoadMoreGroupRunEvents()}
            >
              {replayLoading ? 'Loading GroupRun Events...' : replayHasMore ? 'Load more GroupRun Events' : 'GroupRun replay complete'}
            </button>
          </div>
        </section>
      ) : null}
      {groupRunApprovalFacts.length ? (
        <section className="group-run-runtime-section" data-testid="agent-run-detail-group-run-approvals">
          <div className="group-run-runtime-section-head">
            <strong>Approvals</strong>
            <span>{groupRunApprovalFacts.length}</span>
          </div>
          <div className="group-run-approval-list">
            {groupRunApprovalFacts.map((approval) => (
              <RuntimeApprovalCard
                approval={approval}
                className="studio-runtime-approval group-run-approval-card"
                key={approval.approval_id}
                testId="agent-run-detail-group-run-approval-card"
                variant="inspector"
              />
            ))}
          </div>
        </section>
      ) : null}
      {groupRunArtifactFacts.length ? (
        <section className="group-run-runtime-section" data-testid="agent-run-detail-group-run-artifacts">
          <div className="group-run-runtime-section-head">
            <strong>Shared Artifacts</strong>
            <span>{groupRunArtifactFacts.length}</span>
          </div>
          <RuntimeArtifactList
            artifacts={groupRunArtifactFacts}
            className="group-run-artifact-list run-group-overview-artifact-list"
            fallbackRunId={selectedGroupRunSnapshot?.group_run_id || groupOverviewId}
            itemTestId="agent-run-detail-group-run-artifact-item"
            previewClassName="studio-runtime-artifact group-run-artifact-card"
            previewTestId="agent-run-detail-group-run-artifact-preview"
            previewVariant="full"
            testId="agent-run-detail-group-run-artifact-list"
          />
        </section>
      ) : null}
      {groupRunFinalAnswer ? (
        <pre data-testid="agent-run-detail-group-run-final-answer">{groupRunFinalAnswer}</pre>
      ) : null}
      {groupOverviewChildRunIds.length ? (
        <div className="run-group-overview-children" data-testid="agent-run-detail-group-run-children">
          {groupOverviewChildRunIds.map((childRunId) => {
            const childRun = runById.get(childRunId) || null;
            const selected = childRunId === selectedRun.run_id;
            return (
              <button
                key={childRunId}
                type="button"
                className={selected ? 'selected' : ''}
                data-run-id={childRunId}
                data-run-status={childRun?.status || ''}
                data-testid="agent-run-detail-group-run-child"
                onClick={() => onOpenRunDetail(childRunId)}
              >
                <span>{childRun?.runnable_name || childRun?.runnable_id || childRunId}</span>
                <small>
                  {selected ? '当前 Run · ' : ''}
                  {childRun ? `${runKindLabel(childRun.kind)} · ${runStatusLabel(childRun.status)}` : '未加载'}
                </small>
              </button>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}
