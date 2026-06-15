import type { YachiyoRunTimelineSnapshot } from '../../yachiyo-studio/types';
import type { RunSpec } from '../types';

type WorkflowRunDetailPanelProps = {
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedPublicRunTimeline: YachiyoRunTimelineSnapshot | null;
  selectedRun: RunSpec;
};

export function WorkflowRunDetailPanel({
  runStatusLabel,
  runStatusTone,
  selectedPublicRunTimeline,
  selectedRun,
}: WorkflowRunDetailPanelProps) {
  if (!selectedPublicRunTimeline) return null;
  const workflowRunSnapshotActive = Boolean(
    selectedRun.kind === 'workflow_run'
    && (
      selectedPublicRunTimeline.workflow_id
      || selectedPublicRunTimeline.objective
      || selectedPublicRunTimeline.current_node_id
      || selectedPublicRunTimeline.current_node_label
      || selectedPublicRunTimeline.final_answer
    ),
  );
  const publicSnapshotName = workflowRunSnapshotActive ? 'WorkflowRunSnapshot' : 'RunTimelineSnapshot';

  return (
    <section
      className="run-detail-block run-public-contract-block"
      data-public-snapshot-kind={publicSnapshotName}
      data-workflow-id={selectedPublicRunTimeline.workflow_id || ''}
      data-testid="agent-run-detail-public-timeline"
    >
      <div className="run-detail-section-head">
        <div>
          <h4>Public Runtime Snapshot</h4>
          <span>{publicSnapshotName} · Approval · Artifact · Events</span>
        </div>
        <span className={`run-status-pill ${runStatusTone(selectedPublicRunTimeline.status)}`}>
          {runStatusLabel(selectedPublicRunTimeline.status)}
        </span>
      </div>
      <div className="run-public-contract-grid">
        {selectedPublicRunTimeline.workflow_id ? <code>Workflow {selectedPublicRunTimeline.workflow_id}</code> : null}
        {selectedPublicRunTimeline.objective ? <span>objective {selectedPublicRunTimeline.objective}</span> : null}
        {selectedPublicRunTimeline.current_node_label || selectedPublicRunTimeline.current_node_id ? (
          <span>node {selectedPublicRunTimeline.current_node_label || selectedPublicRunTimeline.current_node_id}</span>
        ) : null}
        {selectedPublicRunTimeline.final_answer ? <span>final answer recorded</span> : null}
        <span>events {selectedPublicRunTimeline.events?.length || 0}</span>
        <span>approvals {selectedPublicRunTimeline.approvals?.length || 0}</span>
        <span>artifacts {selectedPublicRunTimeline.artifacts?.length || 0}</span>
        <span>children {selectedPublicRunTimeline.children?.length || 0}</span>
      </div>
    </section>
  );
}
