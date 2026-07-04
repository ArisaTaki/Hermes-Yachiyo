import type {
  PlannerTraceSummarySnapshot,
  RecoveryRunProvenanceSnapshot,
  RunTimelineChildSnapshot,
  YachiyoRunTimelineSnapshot,
} from '../../yachiyo-studio/types';
import { RuntimeDebugSummary } from '../../runtime-shared/components/RuntimeDebugSummary';
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
  const recoverySource = selectedPublicRunTimeline.recovery_source || null;

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
        {recoverySource ? (
          <button
            type="button"
            data-recovery-action-id={recoverySource.recovery_action_id || ''}
            data-recovery-kind={recoverySource.kind || ''}
            data-recovery-source-run-id={recoverySource.source_run_id || ''}
            data-recovery-tool={recoverySource.recovery_tool || ''}
            data-testid="agent-run-detail-public-recovery-source"
            disabled={!recoverySource.source_run_id}
            onClick={() => {
              if (recoverySource.source_run_id) onOpenRunDetail(recoverySource.source_run_id);
            }}
          >
            recovery of {publicRecoverySourceLabel(recoverySource)}
          </button>
        ) : null}
        {recoverySource?.recovery_tool ? <span>recovery tool {recoverySource.recovery_tool}</span> : null}
        {recoverySource?.source_tool_call_id ? <code>tool call {recoverySource.source_tool_call_id}</code> : null}
        <span>events {selectedPublicRunTimeline.events?.length || 0}</span>
        <span>approvals {selectedPublicRunTimeline.approvals?.length || 0}</span>
        <span>artifacts {selectedPublicRunTimeline.artifacts?.length || 0}</span>
        <span>children {selectedPublicRunTimeline.children?.length || 0}</span>
      </div>
      <RuntimeDebugSummary
        className="run-public-runtime-debug"
        sourceLabel={publicSnapshotName}
        summary={selectedPublicRunTimeline.runtime_debug}
        testId="agent-run-detail-public-runtime-debug"
      />
      {childSnapshots.length ? (
        <div className="run-group-overview-children run-public-child-list" data-testid="agent-run-detail-public-children">
          {childSnapshots.map((child) => {
            const plannerSummary = publicChildPlannerSummary(child);
            const rawPlannerSummary = child.planner_summary;
            const taskProgressSummary = publicChildTaskProgressSummary(child);
            return (
              <button
                type="button"
                data-group-run-id={child.group_run_id || child.run_group_id || ''}
                data-has-planner-summary={String(Boolean(plannerSummary))}
                data-has-task-progress={String(Boolean(taskProgressSummary))}
                data-planner-approvals-required={plannerSummaryValues(rawPlannerSummary?.approvals_required)}
                data-planner-artifacts-expected={plannerSummaryValues(rawPlannerSummary?.artifacts_expected)}
                data-planner-capabilities={plannerSummaryValues(rawPlannerSummary?.plan_capabilities)}
                data-planner-entrypoint={rawPlannerSummary?.planner_entrypoint || ''}
                data-planner-entrypoint-source={rawPlannerSummary?.entrypoint_source || ''}
                data-planner-intent-kind={rawPlannerSummary?.intent_kind || ''}
                data-planner-open-questions={plannerSummaryValues(rawPlannerSummary?.open_questions)}
                data-planner-plan-id={rawPlannerSummary?.plan_id || ''}
                data-planner-selection-role={rawPlannerSummary?.selection_role || rawPlannerSummary?.selection_source || ''}
                data-planner-summary={plannerSummary}
                data-planner-tools={plannerSummaryValues(rawPlannerSummary?.plan_tools)}
                data-run-id={child.run_id}
                data-selected-tools={plannerSummaryValues(rawPlannerSummary?.selected_tools)}
                data-task-progress-status={child.task_progress?.status || ''}
                data-testid="agent-run-detail-public-child-run"
                data-workflow-node-id={child.workflow_node_id || ''}
                key={child.run_id}
                onClick={() => onOpenRunDetail(child.run_id)}
              >
                <span>{publicChildRunTitle(child)}</span>
                <small>{publicChildRunMeta(child, runStatusLabel(child.status || 'unknown'))}</small>
                {plannerSummary ? (
                  <small
                    className="group-run-child-planner-trace"
                    data-testid="agent-run-detail-public-child-planner-summary"
                  >
                    Planner trace · {plannerSummary}
                  </small>
                ) : null}
                {taskProgressSummary ? (
                  <small
                    className="group-run-child-task-progress"
                    data-testid="agent-run-detail-public-child-task-progress"
                  >
                    Task progress · {taskProgressSummary}
                  </small>
                ) : null}
              </button>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function publicChildRunTitle(child: RunTimelineChildSnapshot): string {
  return child.title || child.agent_id || child.workflow_id || child.run_id;
}

function publicRecoverySourceLabel(source: RecoveryRunProvenanceSnapshot): string {
  return source.source_task_title
    || source.source_tool_name
    || source.replan_request_id
    || source.source_run_id
    || source.source_group_run_id
    || source.source_workflow_run_id
    || 'source run';
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

function publicChildPlannerSummary(child: RunTimelineChildSnapshot): string {
  const summary = child.planner_summary;
  if (!summary) return '';
  const parts = [
    summary.intent_kind,
    summary.plan_capabilities?.length ? `${summary.plan_capabilities.length} capabilities` : '',
    summary.step_count ? `${summary.step_count} steps` : '',
    publicChildPlannerToolSummary(summary),
    summary.approvals_required?.length ? `${summary.approvals_required.length} approvals` : '',
    summary.artifacts_expected?.length ? `${summary.artifacts_expected.length} artifacts` : '',
    summary.open_questions?.length ? `${summary.open_questions.length} questions` : '',
    summary.selection_role || summary.selection_source || summary.selected_tools?.length ? 'selection' : '',
    summary.planner_entrypoint ? `entrypoint ${summary.planner_entrypoint}` : '',
    summary.launcher_surface ? `surface ${summary.launcher_surface}` : '',
  ].filter(Boolean);
  return parts.join(' · ');
}

function publicChildPlannerToolSummary(summary: PlannerTraceSummarySnapshot | null | undefined): string {
  const selectedTools = plannerSummaryValues(summary?.selected_tools, ', ');
  if (selectedTools) return `selected ${selectedTools}`;
  const planTools = plannerSummaryValues(summary?.plan_tools, ', ');
  return planTools ? `tools ${planTools}` : '';
}

function publicChildTaskProgressSummary(child: RunTimelineChildSnapshot): string {
  const progress = child.task_progress || null;
  if (!progress) return '';
  return [
    progress.progress_text || progress.status || '',
    typeof progress.completed_todos === 'number' || typeof progress.total_todos === 'number'
      ? `todo ${progress.completed_todos ?? 0}/${progress.total_todos ?? 0}`
      : '',
    progress.needs_replan ? 'replan' : '',
    progress.failed_verification_count ? `verify failed ${progress.failed_verification_count}` : '',
    progress.pending_verification_count ? `verify pending ${progress.pending_verification_count}` : '',
    progress.needs_user_action ? 'user action' : '',
  ].filter(Boolean).join(' · ');
}

function plannerSummaryValues(values: string[] | null | undefined, separator = ','): string {
  return Array.isArray(values) ? values.filter(Boolean).join(separator) : '';
}
