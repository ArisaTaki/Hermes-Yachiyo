import type { RunTimelineChildSnapshot, YachiyoRunTimelineSnapshot } from '../../yachiyo-studio/types';
import type { RunSpec } from '../types';

type WorkflowRunDetailPanelProps = {
  onOpenRunDetail: (runId: string) => void;
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedPublicRunTimeline: YachiyoRunTimelineSnapshot | null;
  selectedRun: RunSpec;
};

export function WorkflowRunDetailPanel({
  onOpenRunDetail,
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
  const childSnapshots = selectedPublicRunTimeline.children || [];

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
        {selectedPublicRunTimeline.rerun_of_run_id ? (
          <button
            type="button"
            data-rerun-of-run-id={selectedPublicRunTimeline.rerun_of_run_id}
            data-testid="agent-run-detail-public-rerun-source"
            onClick={() => onOpenRunDetail(selectedPublicRunTimeline.rerun_of_run_id || '')}
          >
            rerun of {selectedPublicRunTimeline.rerun_of_runnable_name || selectedPublicRunTimeline.rerun_of_run_id}
          </button>
        ) : null}
        <span>events {selectedPublicRunTimeline.events?.length || 0}</span>
        <span>approvals {selectedPublicRunTimeline.approvals?.length || 0}</span>
        <span>artifacts {selectedPublicRunTimeline.artifacts?.length || 0}</span>
        <span>children {selectedPublicRunTimeline.children?.length || 0}</span>
      </div>
      {childSnapshots.length ? (
        <div className="run-group-overview-children run-public-child-list" data-testid="agent-run-detail-public-children">
          {childSnapshots.map((child) => (
            <button
              type="button"
              data-group-run-id={child.group_run_id || child.run_group_id || ''}
              data-run-id={child.run_id}
              data-testid="agent-run-detail-public-child-run"
              data-workflow-node-id={child.workflow_node_id || ''}
              key={child.run_id}
              onClick={() => onOpenRunDetail(child.run_id)}
            >
              <span>{publicChildRunTitle(child)}</span>
              <small>{publicChildRunMeta(child, runStatusLabel(child.status || 'unknown'))}</small>
            </button>
          ))}
        </div>
      ) : null}
    </section>
  );
}

function publicChildRunTitle(child: RunTimelineChildSnapshot): string {
  return child.title || child.agent_id || child.workflow_id || child.run_id;
}

function publicChildRunMeta(child: RunTimelineChildSnapshot, statusLabel: string): string {
  const groupRunId = child.group_run_id || child.run_group_id || '';
  return [
    statusLabel,
    child.kind,
    child.agent_id ? `agent ${child.agent_id}` : '',
    child.workflow_id ? `workflow ${child.workflow_id}` : '',
    child.workflow_run_id ? `workflow run ${child.workflow_run_id}` : '',
    child.workflow_node_label || child.workflow_node_id ? `node ${child.workflow_node_label || child.workflow_node_id}` : '',
    groupRunId ? `group run ${groupRunId}` : '',
    child.parent_run_id ? `parent ${child.parent_run_id}` : '',
  ].filter(Boolean).join(' · ');
}
