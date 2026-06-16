import { ExpandableRuntimeContent as RunExpandableContent } from '../../runtime-shared/components/ExpandableRuntimeContent';
import type { RunSpec } from '../types';
import type { RunDetailWorkflowStepRef } from './runDetailTypes';

type WorkflowStepResultsProps = {
  onOpenArtifact: (run: RunSpec | string, path: string) => Promise<void> | void;
  onOpenRunDetail: (runId: string) => void;
  runById: Map<string, RunSpec>;
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedRun: RunSpec;
  selectedWorkflowSteps: RunDetailWorkflowStepRef[];
  skippedWorkflowArtifactLabel: (run: RunSpec | null, step: RunDetailWorkflowStepRef) => string;
  workflowRunArtifactForStep: (run: RunSpec | null, step: RunDetailWorkflowStepRef) => Record<string, unknown> | null | undefined;
  workflowStepArtifacts: (childRun: RunSpec | null) => Array<Record<string, unknown>>;
  workflowStepKindLabel: (kind: RunDetailWorkflowStepRef['kind']) => string;
  workflowStepSummary: (step: RunDetailWorkflowStepRef, childRun: RunSpec | null) => string;
};

export function WorkflowStepResults({
  onOpenArtifact,
  onOpenRunDetail,
  runById,
  runStatusLabel,
  runStatusTone,
  selectedRun,
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
          return (
            <article
              className={`workflow-child-result workflow-step-result ${step.kind}`}
              data-testid="agent-run-detail-workflow-step"
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
                </div>
              </div>
              {step.task ? (
                <p className="workflow-step-task">
                  <strong>{step.kind === 'approval' ? '审批说明' : 'Step Task'}</strong>
                  {step.task}
                </p>
              ) : null}
              <RunExpandableContent
                content={step.childRunId && !childRun ? 'Loading child run...' : summary}
                label="展开完整节点结果"
                defaultOpen={childStatus === 'failed' || childStatus === 'cancelled' || childStatus === 'approval_required'}
              />
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
