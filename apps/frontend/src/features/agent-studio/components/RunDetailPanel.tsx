import type { ReactNode } from 'react';

import type { RunGroupSpec, RunSpec, WorkflowSpec } from '../types';
import type { GroupRunSnapshot, PublicRunEvent, YachiyoRunTimelineSnapshot } from '../../yachiyo-studio/types';
import { ExpandableRuntimeContent as RunExpandableContent } from '../../runtime-shared/components/ExpandableRuntimeContent';
import {
  approvalsFromRunEventReplay,
  artifactsFromRunEventReplay,
  mergeApprovalSnapshots,
  mergeArtifactSnapshots,
} from '../../runtime-shared/runEventFacts';
import { ApprovalInspector, type RunPendingApproval } from './ApprovalInspector';
import { ArtifactInspector } from './ArtifactInspector';
import { GroupRunDetailPanel } from './GroupRunDetailPanel';
import { MemorySkillTraceInspector } from './MemorySkillTraceInspector';
import { RunTimeline } from './RunTimeline';
import { ToolCallInspector } from './ToolCallInspector';
import { WorkflowChildApprovalBridge, type RunDetailWorkflowStepRef } from './WorkflowChildApprovalBridge';
import { WorkflowRunDetailPanel } from './WorkflowRunDetailPanel';
import {
  mergeToolCallSnapshots,
  toolCallsFromRunEventReplay,
} from '../utils/runTimeline';

type ArtifactPreview = {
  path: string;
  content: string;
  truncated?: boolean;
};

export function RunDetailPanel({
  artifactPreview,
  busy,
  formatRunDate,
  isActiveRunStatus,
  normalizeRunStatus,
  onApproveRunById,
  onApproveSelectedRun,
  onCancelRunById,
  onLoadMoreSelectedGroupRunEvents,
  onLoadMoreSelectedRunEvents,
  onOpenArtifact,
  onOpenRunDetail,
  onOpenWorkflowDesign,
  onPrepareSelectedRunRerun,
  onRejectRunById,
  onRejectSelectedRun,
  onRequestCancelSelectedRun,
  onRerunSelectedRun,
  onRunAction,
  runById,
  runKindLabel,
  runStatusLabel,
  runStatusTone,
  selectedGroupRunSnapshot,
  selectedGroupRunReplayError,
  selectedGroupRunReplayEvents,
  selectedGroupRunReplayHasMore,
  selectedGroupRunReplayLoading,
  selectedGroupRunReplayNextAfterSequence,
  selectedPublicRunTimeline,
  selectedRouteGroupRunId,
  selectedRun,
  selectedRunApproval,
  selectedRunArtifacts,
  selectedRunAvatarUrl,
  selectedRunExecutionEvents,
  selectedRunGroup,
  selectedRunIsLive,
  selectedRunReplayError,
  selectedRunReplayEvents,
  selectedRunReplayHasMore,
  selectedRunReplayLoading,
  selectedRunReplayNextAfterSequence,
  selectedRunRerunDisabledReason,
  selectedRunRerunTarget,
  selectedRunWorkflow,
  selectedWorkflowApprovalChildRun,
  selectedWorkflowApprovalChildRunId,
  selectedWorkflowApprovalStep,
  selectedWorkflowParentRun,
  selectedWorkflowParentRunId,
  selectedWorkflowSteps,
  skippedWorkflowArtifactLabel,
  workflowRunArtifactForStep,
  workflowStepArtifacts,
  workflowStepKindLabel,
  workflowStepSummary,
}: {
  artifactPreview: ArtifactPreview | null;
  busy: boolean;
  formatRunDate: (value?: string) => string;
  isActiveRunStatus: (status: string) => boolean;
  normalizeRunStatus: (status: string) => string;
  onApproveRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onApproveSelectedRun: () => Promise<unknown>;
  onCancelRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onLoadMoreSelectedGroupRunEvents: () => Promise<void> | void;
  onLoadMoreSelectedRunEvents: () => Promise<void> | void;
  onOpenArtifact: (run: RunSpec | string, path: string) => Promise<void> | void;
  onOpenRunDetail: (runId: string) => void;
  onOpenWorkflowDesign: (workflowId: string) => void;
  onPrepareSelectedRunRerun: () => void;
  onRejectRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onRejectSelectedRun: () => Promise<unknown>;
  onRequestCancelSelectedRun: () => void;
  onRerunSelectedRun: () => Promise<unknown>;
  onRunAction: (action: () => Promise<unknown> | unknown, label: string) => void;
  runById: Map<string, RunSpec>;
  runKindLabel: (kind: string) => string;
  runStatusLabel: (status: string) => string;
  runStatusTone: (status: string) => string;
  selectedGroupRunSnapshot: GroupRunSnapshot | null;
  selectedGroupRunReplayError: string;
  selectedGroupRunReplayEvents: PublicRunEvent[];
  selectedGroupRunReplayHasMore: boolean;
  selectedGroupRunReplayLoading: boolean;
  selectedGroupRunReplayNextAfterSequence: number;
  selectedPublicRunTimeline: YachiyoRunTimelineSnapshot | null;
  selectedRouteGroupRunId: string;
  selectedRun: RunSpec | null;
  selectedRunApproval: RunPendingApproval | null;
  selectedRunArtifacts: Array<Record<string, unknown>>;
  selectedRunAvatarUrl: string;
  selectedRunExecutionEvents: Array<Record<string, unknown>>;
  selectedRunGroup: RunGroupSpec | null;
  selectedRunIsLive: boolean;
  selectedRunReplayError: string;
  selectedRunReplayEvents: PublicRunEvent[];
  selectedRunReplayHasMore: boolean;
  selectedRunReplayLoading: boolean;
  selectedRunReplayNextAfterSequence: number;
  selectedRunRerunDisabledReason: string;
  selectedRunRerunTarget: { id: string } | null;
  selectedRunWorkflow: WorkflowSpec | null;
  selectedWorkflowApprovalChildRun: RunSpec | null;
  selectedWorkflowApprovalChildRunId: string;
  selectedWorkflowApprovalStep: RunDetailWorkflowStepRef | null | undefined;
  selectedWorkflowParentRun: RunSpec | null;
  selectedWorkflowParentRunId: string;
  selectedWorkflowSteps: RunDetailWorkflowStepRef[];
  skippedWorkflowArtifactLabel: (run: RunSpec | null, step: RunDetailWorkflowStepRef) => string;
  workflowRunArtifactForStep: (run: RunSpec | null, step: RunDetailWorkflowStepRef) => Record<string, unknown> | null | undefined;
  workflowStepArtifacts: (childRun: RunSpec | null) => Array<Record<string, unknown>>;
  workflowStepKindLabel: (kind: RunDetailWorkflowStepRef['kind']) => string;
  workflowStepSummary: (step: RunDetailWorkflowStepRef, childRun: RunSpec | null) => string;
}) {
  const timelineMemoryTraces = selectedPublicRunTimeline?.memory_traces || [];
  const timelineSkillTraces = selectedPublicRunTimeline?.skill_traces || [];
  const hasTimelineMemorySkillTraces = Boolean(timelineMemoryTraces.length || timelineSkillTraces.length);
  const memorySkillTraceEvents = selectedRunReplayEvents.length
    ? selectedRunReplayEvents
    : hasTimelineMemorySkillTraces
      ? []
    : selectedPublicRunTimeline?.events || [];
  const memorySkillTraceSource = selectedRunReplayEvents.length
    ? hasTimelineMemorySkillTraces
      ? 'RunTimelineSnapshot + RunEvent replay trace facts · Memory / Skill'
      : 'RunEvent replay trace facts · Memory / Skill'
    : 'RunTimelineSnapshot trace facts · Memory / Skill';
  const replayToolCalls = selectedRunReplayEvents.length
    ? toolCallsFromRunEventReplay(selectedRunReplayEvents)
    : [];
  const selectedRunToolCalls = mergeToolCallSnapshots(
    selectedPublicRunTimeline?.tool_calls || [],
    replayToolCalls,
  );
  const toolCallSource = replayToolCalls.length
    ? 'RunTimelineSnapshot + RunEvent replay tool facts'
    : 'RunTimelineSnapshot tool calls';
  const replayArtifacts = selectedRunReplayEvents.length
    ? artifactsFromRunEventReplay(selectedRunReplayEvents)
    : [];
  const selectedRunArtifactFacts = mergeArtifactSnapshots(selectedRunArtifacts, replayArtifacts);
  const artifactSource = replayArtifacts.length
    ? 'RunTimelineSnapshot + RunEvent replay artifact facts'
    : 'RunTimelineSnapshot artifacts';
  const replayApprovals = selectedRunReplayEvents.length
    ? approvalsFromRunEventReplay(selectedRunReplayEvents)
    : [];
  const selectedRunApprovalHistory = mergeApprovalSnapshots(
    selectedPublicRunTimeline?.approvals || [],
    replayApprovals,
  );
  const approvalHistorySource = replayApprovals.length
    ? 'RunTimelineSnapshot + RunEvent replay approval facts'
    : 'RunTimelineSnapshot approval facts';
  return (
    <div className="agent-studio-panel">
      <div className="section-heading-row"><h2>Run Detail</h2></div>
      {selectedRun ? (
        <article
          className="run-detail"
          data-run-group-id={selectedRun.run_group_id || ''}
          data-run-id={selectedRun.run_id}
          data-run-kind={selectedRun.kind}
          data-run-status={selectedRun.status}
          data-session-id={selectedRun.session_id || ''}
          data-task-id={selectedRun.task_id || ''}
          data-testid="agent-run-detail"
        >
          <header className="run-detail-hero" data-testid="agent-run-detail-hero">
            <AgentAvatar avatarUrl={selectedRunAvatarUrl} name={selectedRun.runnable_name || selectedRun.runnable_id || 'Run'} />
            <div className="run-detail-title">
              <span>{runKindLabel(selectedRun.kind)} · {formatRunDate(selectedRun.created_at)}</span>
              <h3>{selectedRun.runnable_name || selectedRun.runnable_id}</h3>
              <p>{selectedRun.user_goal || 'No task goal recorded.'}</p>
            </div>
            <span className={`run-status-pill ${runStatusTone(selectedRun.status)}`}>{runStatusLabel(selectedRun.status)}</span>
          </header>
          <div className="run-detail-meta" data-testid="agent-run-detail-meta">
            <span>{runKindLabel(selectedRun.kind)}</span>
            <span>Updated {formatRunDate(selectedRun.updated_at || selectedRun.created_at)}</span>
            {selectedRunIsLive ? <span className="run-live-pill">实时更新</span> : null}
            {selectedRun.run_group_id ? <span>Group {selectedRun.run_group_id}</span> : null}
            {selectedRun.task_id ? <code>Task {selectedRun.task_id}</code> : null}
            {selectedRun.session_id ? <code>Session {selectedRun.session_id}</code> : null}
            {selectedRun.task_run_link_run_status ? <span>Task link {runStatusLabel(selectedRun.task_run_link_run_status)}</span> : null}
            {selectedRun.task_run_link_last_event_sequence !== undefined && selectedRun.task_run_link_last_event_sequence !== null ? (
              <span>Replay #{selectedRun.task_run_link_last_event_sequence}</span>
            ) : null}
            {selectedRun.task_run_link_updated_at || selectedRun.task_run_link_created_at ? (
              <span>Task link updated {formatRunDate(selectedRun.task_run_link_updated_at || selectedRun.task_run_link_created_at)}</span>
            ) : null}
            <code>{selectedRun.run_id}</code>
            <button
              type="button"
              className="run-rerun-prepare"
              data-testid="agent-run-detail-prepare-rerun"
              disabled={busy || !selectedRunRerunTarget}
              title={!selectedRunRerunTarget ? '找不到原目标，无法准备重跑。' : undefined}
              onClick={onPrepareSelectedRunRerun}
            >
              准备重跑
            </button>
            <button
              type="button"
              className="run-rerun-action"
              data-testid="agent-run-detail-rerun"
              disabled={busy || Boolean(selectedRunRerunDisabledReason)}
              title={selectedRunRerunDisabledReason || undefined}
              onClick={() => onRunAction(onRerunSelectedRun, '重新运行')}
            >
              重新运行
            </button>
            {selectedWorkflowParentRunId ? (
              <button
                type="button"
                className="run-parent-link"
                data-run-id={selectedWorkflowParentRunId}
                data-run-status={selectedWorkflowParentRun?.status || ''}
                data-testid="agent-run-detail-open-parent-run"
                onClick={() => onOpenRunDetail(selectedWorkflowParentRunId)}
              >
                返回 Workflow：{selectedWorkflowParentRun?.runnable_name || selectedWorkflowParentRun?.runnable_id || '父 Workflow'}
              </button>
            ) : null}
            {selectedRun.kind === 'workflow_run' && selectedRunWorkflow ? (
              <button type="button" className="run-workflow-link" data-testid="agent-run-detail-open-workflow-studio" onClick={() => onOpenWorkflowDesign(selectedRunWorkflow.workflow_id)}>
                打开 Workflow Studio
              </button>
            ) : null}
            {isActiveRunStatus(selectedRun.status) ? (
              <button
                type="button"
                className="run-cancel-action danger-action"
                data-testid="agent-run-detail-cancel"
                disabled={busy}
                onClick={onRequestCancelSelectedRun}
              >
                取消 Run
              </button>
            ) : null}
          </div>
          <GroupRunDetailPanel
            formatRunDate={formatRunDate}
            onOpenRunDetail={onOpenRunDetail}
            runById={runById}
            runKindLabel={runKindLabel}
            runStatusLabel={runStatusLabel}
            runStatusTone={runStatusTone}
            onLoadMoreGroupRunEvents={onLoadMoreSelectedGroupRunEvents}
            replayError={selectedGroupRunReplayError}
            replayEvents={selectedGroupRunReplayEvents}
            replayHasMore={selectedGroupRunReplayHasMore}
            replayLoading={selectedGroupRunReplayLoading}
            replayNextAfterSequence={selectedGroupRunReplayNextAfterSequence}
            selectedGroupRunSnapshot={selectedGroupRunSnapshot}
            selectedRouteGroupRunId={selectedRouteGroupRunId}
            selectedRun={selectedRun}
            selectedRunGroup={selectedRunGroup}
          />
          {selectedWorkflowApprovalChildRunId ? (
            <WorkflowChildApprovalBridge
              busy={busy}
              onApproveRunById={onApproveRunById}
              onCancelRunById={onCancelRunById}
              onOpenRunDetail={onOpenRunDetail}
              onRejectRunById={onRejectRunById}
              onRunAction={onRunAction}
              runStatusLabel={runStatusLabel}
              runStatusTone={runStatusTone}
              selectedRun={selectedRun}
              selectedWorkflowApprovalChildRun={selectedWorkflowApprovalChildRun}
              selectedWorkflowApprovalChildRunId={selectedWorkflowApprovalChildRunId}
              selectedWorkflowApprovalStep={selectedWorkflowApprovalStep}
            />
          ) : null}
          <ApprovalInspector
            approvalHistory={selectedRunApprovalHistory}
            approvalHistorySource={approvalHistorySource}
            busy={busy}
            onApproveSelectedRun={onApproveSelectedRun}
            onRejectSelectedRun={onRejectSelectedRun}
            onRunAction={onRunAction}
            runKindLabel={runKindLabel}
            selectedPublicRunTimeline={selectedPublicRunTimeline}
            selectedRun={selectedRun}
            selectedRunApproval={selectedRunApproval}
          />
          <WorkflowRunDetailPanel
            onOpenRunDetail={onOpenRunDetail}
            runStatusLabel={runStatusLabel}
            runStatusTone={runStatusTone}
            selectedPublicRunTimeline={selectedPublicRunTimeline}
            selectedRun={selectedRun}
          />
          {selectedPublicRunTimeline || selectedRunToolCalls.length ? (
            <ToolCallInspector
              sourceLabel={toolCallSource}
              toolCalls={selectedRunToolCalls}
            />
          ) : null}
          {selectedPublicRunTimeline || selectedRunReplayEvents.length ? (
            <MemorySkillTraceInspector
              events={memorySkillTraceEvents}
              memoryTraces={timelineMemoryTraces}
              skillTraces={timelineSkillTraces}
              sourceLabel={memorySkillTraceSource}
            />
          ) : null}
          <section className="run-detail-block run-task-block" data-testid="agent-run-detail-task">
            <div className="run-detail-section-head">
              <div>
                <h4>Task</h4>
                <span>Agent 收到的完整任务目标</span>
              </div>
            </div>
            <p>{selectedRun.user_goal || 'No task goal recorded.'}</p>
          </section>
          <section className={`run-detail-block run-result-block ${runStatusTone(selectedRun.status)}`} data-testid="agent-run-detail-result">
            <div className="run-detail-section-head">
              <div>
                <h4>{selectedRun.kind === 'workflow_run' ? 'Final Result' : 'Result'}</h4>
                <span>{selectedRun.status === 'completed' ? '最终交付内容' : selectedRun.status === 'failed' ? '失败原因或最后输出' : '当前最新输出'}</span>
              </div>
              <span className={`run-status-pill ${runStatusTone(selectedRun.status)}`}>{runStatusLabel(selectedRun.status)}</span>
            </div>
            <RunExpandableContent
              content={selectedRun.result || 'No result yet.'}
              label="展开完整结果"
              defaultOpen
            />
          </section>
          {selectedRun.kind === 'workflow_run' ? (
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
          ) : null}
          <RunTimeline
            events={selectedRunExecutionEvents}
            replayError={selectedRunReplayError}
            replayEventCount={selectedRunReplayEvents.length}
            replayHasMore={selectedRunReplayHasMore}
            replayLoading={selectedRunReplayLoading}
            replayNextAfterSequence={selectedRunReplayNextAfterSequence}
            formatRunDate={formatRunDate}
            getChildRunStatus={(childRunId, eventStatus) => {
              const childRun = runById.get(childRunId);
              return normalizeRunStatus(childRun?.status || eventStatus);
            }}
            onLoadMoreEvents={onLoadMoreSelectedRunEvents}
            onOpenRunDetail={(runId) => onOpenRunDetail(runId)}
            runStatusLabel={runStatusLabel}
            runStatusTone={runStatusTone}
          />
          <ArtifactInspector
            artifactPreview={artifactPreview}
            onOpenArtifact={onOpenArtifact}
            selectedRun={selectedRun}
            selectedRunArtifacts={selectedRunArtifactFacts}
            sourceLabel={artifactSource}
          />
        </article>
      ) : (
        <div className="empty-state inline-empty">从左侧选择一个 Run，或运行新的 Agent / Workflow 后查看 Result、Timeline 和 Artifacts。</div>
      )}
    </div>
  );
}

function AgentAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }): ReactNode {
  return (
    <span className={avatarUrl ? 'agent-avatar has-image' : 'agent-avatar'} aria-hidden="true">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : agentInitial(name)}
    </span>
  );
}

function agentInitial(name: string): string {
  const clean = name.trim();
  return clean ? clean.slice(0, 1).toUpperCase() : 'A';
}
