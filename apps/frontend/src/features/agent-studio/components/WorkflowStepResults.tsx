import { ExpandableRuntimeContent as RunExpandableContent } from '../../runtime-shared/components/ExpandableRuntimeContent';
import { RuntimeDebugSummary } from '../../runtime-shared/components/RuntimeDebugSummary';
import { RuntimeExecutionEnvelopeSummary } from '../../runtime-shared/components/RuntimeExecutionEnvelopeSummary';
import type { RecoveryRunProvenanceSnapshot, RerunRunRequest } from '../../yachiyo-studio/types';
import type { RunSpec } from '../types';
import { TaskCoreInspector, TaskProgressInspector } from './PlannerTraceInspector';
import type { RunDetailWorkflowStepRef } from './runDetailTypes';

type WorkflowStepResultsProps = {
  busy: boolean;
  onOpenArtifact: (run: RunSpec | string, path: string) => Promise<void> | void;
  onOpenRunDetail: (runId: string) => void;
  onRerunWorkflowScope: (request: RerunRunRequest) => Promise<unknown>;
  onRunAction: (action: () => Promise<unknown> | unknown, label: string) => void;
  runById: Map<string, RunSpec>;
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedRun: RunSpec;
  selectedRunRerunDisabledReason: string;
  selectedWorkflowSteps: RunDetailWorkflowStepRef[];
  skippedWorkflowArtifactLabel: (run: RunSpec | null, step: RunDetailWorkflowStepRef) => string;
  workflowRunArtifactForStep: (run: RunSpec | null, step: RunDetailWorkflowStepRef) => Record<string, unknown> | null | undefined;
  workflowStepArtifacts: (childRun: RunSpec | null) => Array<Record<string, unknown>>;
  workflowStepKindLabel: (kind: RunDetailWorkflowStepRef['kind']) => string;
  workflowStepSummary: (step: RunDetailWorkflowStepRef, childRun: RunSpec | null) => string;
};

export function WorkflowStepResults({
  busy,
  onOpenArtifact,
  onOpenRunDetail,
  onRerunWorkflowScope,
  onRunAction,
  runById,
  runStatusLabel,
  runStatusTone,
  selectedRun,
  selectedRunRerunDisabledReason,
  selectedWorkflowSteps,
  skippedWorkflowArtifactLabel,
  workflowRunArtifactForStep,
  workflowStepArtifacts,
  workflowStepKindLabel,
  workflowStepSummary,
}: WorkflowStepResultsProps) {
  if (selectedRun.kind !== 'workflow_run') return null;
  return (
    <details className="run-detail-block run-detail-fold" data-testid="agent-run-detail-workflow-steps" open>
      <summary className="run-detail-section-head">
        <div>
          <h4>Workflow Steps · {selectedWorkflowSteps.length}</h4>
          <span>Workflow 中每个节点的执行状态、审批和产物</span>
        </div>
      </summary>
      <div className="run-detail-fold-body workflow-child-results">
        {selectedWorkflowSteps.map((step, index) => {
          const childRun = step.childRunId ? runById.get(step.childRunId) || null : null;
          const childStatus = childRun?.status || step.status || 'loading';
          const summary = workflowStepSummary(step, childRun);
          const childArtifacts = workflowStepArtifacts(childRun);
          const workflowArtifact = workflowRunArtifactForStep(selectedRun, step);
          const rerunDisabled = Boolean(busy || selectedRunRerunDisabledReason || !step.nodeId);
          const stepLabel = step.label || step.nodeId || 'Workflow node';
          const canRerunBranch = Boolean(step.nodeId && step.selectedTargetNodeId);
          const recoverySource = childRun?.recovery_source || null;
          const recoverySourceSummary = workflowStepRecoverySourceSummary(recoverySource);
          const childRuntimeEnvelope = childRun?.runtime_execution_envelope || null;
          const childTaskCore = childRun?.task_core || null;
          const childTaskProgress = childRun?.task_progress || null;
          const childReplanRecoveries = childRun?.replan_recoveries || [];
          const childHasTaskWorkspace = Boolean(
            childTaskCore
            || childTaskProgress
            || childReplanRecoveries.length,
          );
          return (
            <article
              className={`workflow-child-result workflow-step-result ${step.kind}`}
              data-recovery-action-id={recoverySource?.recovery_action_id || ''}
              data-recovery-kind={recoverySource?.kind || ''}
              data-recovery-source-run-id={recoverySource?.source_run_id || ''}
              data-recovery-tool={recoverySource?.recovery_tool || ''}
              data-testid="agent-run-detail-workflow-step"
              data-task-progress-status={childTaskProgress?.status || ''}
              data-workflow-step-key={step.key}
              data-workflow-step-kind={step.kind}
              data-workflow-step-node-id={step.nodeId || ''}
              data-workflow-step-status={childStatus}
              data-child-run-id={step.childRunId || ''}
              key={step.key}
            >
              <div className="workflow-child-result-head">
                <div>
                  <strong>{index + 1}. {step.label}</strong>
                  <span>{workflowStepKindLabel(step.kind)}{childRun?.runnable_name ? ` · ${childRun.runnable_name}` : ''}</span>
                </div>
                <div>
                  <em className={`run-status-pill ${runStatusTone(childStatus)}`}>{runStatusLabel(childStatus)}</em>
                  {step.childRunId ? (
                    <button
                      type="button"
                      className="run-timeline-child"
                      data-run-id={step.childRunId}
                      data-run-status={childStatus}
                      data-testid="agent-run-detail-workflow-step-open-run"
                      onClick={() => onOpenRunDetail(step.childRunId || '')}
                    >
                      Open Run
                    </button>
                  ) : null}
                  {recoverySourceSummary ? (
                    <button
                      type="button"
                      className="run-timeline-child workflow-step-recovery-source"
                      data-recovery-action-id={recoverySource?.recovery_action_id || ''}
                      data-recovery-kind={recoverySource?.kind || ''}
                      data-recovery-source-run-id={recoverySource?.source_run_id || ''}
                      data-testid="agent-run-detail-workflow-step-recovery-source"
                      disabled={!recoverySource?.source_run_id}
                      onClick={() => {
                        if (recoverySource?.source_run_id) onOpenRunDetail(recoverySource.source_run_id);
                      }}
                    >
                      Recovery
                    </button>
                  ) : null}
                  <button
                    type="button"
                    className="run-timeline-child workflow-step-rerun"
                    data-testid="agent-run-detail-workflow-step-rerun-node"
                    data-workflow-node-id={step.nodeId || ''}
                    disabled={rerunDisabled}
                    title={selectedRunRerunDisabledReason || undefined}
                    onClick={() => onRunAction(
                      () => onRerunWorkflowScope({
                        scope: 'workflow_node',
                        workflow_node_id: step.nodeId || '',
                        workflow_node_label: stepLabel,
                        reason: `Rerun workflow node ${stepLabel}`,
                      }),
                      '重跑 Workflow 节点',
                    )}
                  >
                    重跑节点
                  </button>
                  {canRerunBranch ? (
                    <button
                      type="button"
                      className="run-timeline-child workflow-step-rerun"
                      data-testid="agent-run-detail-workflow-step-rerun-branch"
                      data-workflow-edge-branch={step.selectedBranch || ''}
                      data-workflow-node-id={step.nodeId || ''}
                      data-workflow-node-selected-target={step.selectedTargetNodeId || ''}
                      disabled={rerunDisabled}
                      title={selectedRunRerunDisabledReason || undefined}
                      onClick={() => onRunAction(
                        () => onRerunWorkflowScope({
                          scope: 'workflow_branch',
                          workflow_node_id: step.nodeId || '',
                          workflow_node_label: stepLabel,
                          workflow_edge_branch: step.selectedBranch || '',
                          workflow_node_selected_target: step.selectedTargetNodeId || '',
                          reason: `Rerun workflow branch ${step.selectedBranch || 'selected'}`,
                        }),
                        '重跑 Workflow 分支',
                      )}
                    >
                      重跑分支
                    </button>
                  ) : null}
                </div>
              </div>
              {step.task ? (
                <p className="workflow-step-task">
                  <strong>{step.kind === 'approval' ? '审批说明' : 'Step Task'}</strong>
                  {step.task}
                </p>
              ) : null}
              {recoverySourceSummary ? (
                <p
                  className="workflow-step-recovery-source-summary"
                  data-testid="agent-run-detail-workflow-step-recovery-source-summary"
                >
                  {recoverySourceSummary}
                </p>
              ) : null}
              <RunExpandableContent
                content={step.childRunId && !childRun ? 'Loading child run...' : summary}
                label="展开完整节点结果"
                defaultOpen={childStatus === 'failed' || childStatus === 'cancelled' || childStatus === 'approval_required'}
              />
              <RuntimeDebugSummary
                className="workflow-step-runtime-debug"
                compact
                sourceLabel={step.childRunId ? `Child run ${step.childRunId}` : 'Workflow step'}
                summary={childRun?.runtime_debug}
                testId="agent-run-detail-workflow-step-runtime-debug"
              />
              <RuntimeExecutionEnvelopeSummary
                className="workflow-step-runtime-execution"
                debugPillsTestId="agent-run-detail-workflow-step-runtime-execution-debug-pills"
                envelope={childRuntimeEnvelope}
                requestLimit={4}
                requestListTestId="agent-run-detail-workflow-step-runtime-execution-requests"
                requestTestId="agent-run-detail-workflow-step-runtime-execution-request"
                showRequests
                sourceLabel={step.childRunId ? `Child run ${step.childRunId} runtime execution` : 'Workflow step runtime execution'}
                testId="agent-run-detail-workflow-step-runtime-execution-envelope"
                title="Step Runtime Execution"
                variant="studio"
              />
              {childHasTaskWorkspace ? (
                <section
                  className="group-run-runtime-section workflow-step-task-workspace"
                  data-core-id={childTaskCore?.core_id || ''}
                  data-task-progress-status={childTaskProgress?.status || ''}
                  data-testid="agent-run-detail-workflow-step-task-workspace"
                  data-workspace-id={childTaskCore?.workspace?.workspace_id || childTaskProgress?.workspace_id || ''}
                >
                  <div className="group-run-runtime-section-head">
                    <strong>Task Workspace</strong>
                    <span>{childTaskProgress?.progress_text || childTaskCore?.workspace?.title || 'workspace / todos / checkpoints / replan'}</span>
                  </div>
                  <div className="studio-task-workspace">
                    {childTaskCore ? <TaskCoreInspector taskCore={childTaskCore} /> : null}
                    {childTaskProgress || childReplanRecoveries.length ? (
                      <TaskProgressInspector
                        replanRecoveries={childReplanRecoveries}
                        taskProgress={childTaskProgress}
                      />
                    ) : null}
                  </div>
                </section>
              ) : null}
              {childRun && childArtifacts.length ? (
                <div className="run-artifacts compact">
                  {childArtifacts.map((artifact, artifactIndex) => {
                    const path = String(artifact.path || '');
                    return (
                      <button
                        type="button"
                        disabled={!path}
                        key={`${step.childRunId}-${path}-${artifactIndex}`}
                        onClick={() => path ? void onOpenArtifact(childRun, path) : undefined}
                      >
                        {path || 'artifact'}
                      </button>
                    );
                  })}
                </div>
              ) : null}
              {step.kind === 'artifact' && step.artifactPath ? (
                <div className="run-artifacts compact">
                  {workflowArtifact ? (
                    <button type="button" onClick={() => void onOpenArtifact(selectedRun, step.artifactPath || '')}>
                      {step.artifactPath}
                    </button>
                  ) : (
                    <span className="workflow-artifact-plan">
                      {skippedWorkflowArtifactLabel(selectedRun, step)} · {step.artifactPath}
                    </span>
                  )}
                </div>
              ) : null}
            </article>
          );
        })}
        {!selectedWorkflowSteps.length ? <span>No workflow steps</span> : null}
      </div>
    </details>
  );
}

function workflowStepRecoverySourceSummary(
  source: RecoveryRunProvenanceSnapshot | null | undefined,
): string {
  if (!source) return '';
  const sourceLabel = source.source_task_title
    || source.source_tool_name
    || source.replan_request_id
    || source.source_run_id
    || source.source_group_run_id
    || source.source_workflow_run_id
    || 'source run';
  return [
    `Recovery from ${sourceLabel}`,
    source.kind ? `kind ${source.kind}` : '',
    source.recovery_tool ? `tool ${source.recovery_tool}` : '',
    source.recovery_action_kind ? `action ${source.recovery_action_kind}` : '',
  ].filter(Boolean).join(' · ');
}
