import type { RunGroupSpec, RunSpec } from '../types';
import type { GroupRunSnapshot } from '../../yachiyo-studio/types';
import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import { RuntimeArtifactList } from '../../runtime-shared/components/RuntimeArtifactList';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';

type GroupRunDetailPanelProps = {
  formatRunDate: (value?: string) => string;
  onOpenRunDetail: (runId: string) => void;
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
  onOpenRunDetail,
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
    || 'No GroupRun summary recorded.';
  const groupRunParticipants = selectedGroupRunSnapshot?.participants || [];
  const groupRunEvents = selectedGroupRunSnapshot?.events || [];
  const groupRunApprovals = selectedGroupRunSnapshot?.pending_approvals || [];
  const groupRunArtifacts = selectedGroupRunSnapshot?.shared_artifacts || [];

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
        {selectedGroupRunSnapshot?.objective ? <span>Objective {selectedGroupRunSnapshot.objective}</span> : null}
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
      {groupRunEvents.length ? (
        <RuntimeTimelineSummary
          className="group-run-event-summary run-group-overview-events"
          events={groupRunEvents}
          limit={6}
          testId="agent-run-detail-group-run-events"
        />
      ) : null}
      {groupRunApprovals.length ? (
        <section className="group-run-runtime-section" data-testid="agent-run-detail-group-run-approvals">
          <div className="group-run-runtime-section-head">
            <strong>Pending Approvals</strong>
            <span>{groupRunApprovals.length}</span>
          </div>
          <div className="group-run-approval-list">
            {groupRunApprovals.map((approval) => (
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
      {groupRunArtifacts.length ? (
        <section className="group-run-runtime-section" data-testid="agent-run-detail-group-run-artifacts">
          <div className="group-run-runtime-section-head">
            <strong>Shared Artifacts</strong>
            <span>{groupRunArtifacts.length}</span>
          </div>
          <RuntimeArtifactList
            artifacts={groupRunArtifacts}
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
      {selectedGroupRunSnapshot?.final_answer ? (
        <pre data-testid="agent-run-detail-group-run-final-answer">{selectedGroupRunSnapshot.final_answer}</pre>
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
