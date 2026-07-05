import { useState, type ReactNode } from 'react';

import type { RunGroupSpec, RunSpec, WorkflowSpec } from '../types';
import type {
  GroupRunSnapshot,
  PublicRunEvent,
  RerunRunRequest,
  RecoveryRunProvenanceSnapshot,
  ToolCallSnapshot,
  YachiyoRunTimelineSnapshot,
} from '../../yachiyo-studio/types';
import type { RuntimeImageArtifactPointSelection } from '../../runtime-shared/components/RuntimeReadableArtifactPreview';
import { ExpandableRuntimeContent as RunExpandableContent } from '../../runtime-shared/components/ExpandableRuntimeContent';
import { RuntimeDebugSummary } from '../../runtime-shared/components/RuntimeDebugSummary';
import { RuntimeExecutionEnvelopeSummary } from '../../runtime-shared/components/RuntimeExecutionEnvelopeSummary';
import {
  runtimeToolRecoveryActionsFromRecords,
  runtimeToolRecoveryRetryAction,
  type RuntimeToolRecoveryAction,
} from '../../runtime-shared/toolRecoveryActions';
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
import {
  PlannerTraceInspector,
  TaskCoreInspector,
  TaskProgressInspector,
} from './PlannerTraceInspector';
import { RunTimeline } from './RunTimeline';
import { ToolCallInspector } from './ToolCallInspector';
import { WorkflowChildApprovalBridge } from './WorkflowChildApprovalBridge';
import { WorkflowRunDetailPanel } from './WorkflowRunDetailPanel';
import { WorkflowStepResults } from './WorkflowStepResults';
import type {
  RunArtifactPreview,
  RunDetailWorkflowStepRef,
  RunRecoveryCoordinate,
  RunRecoveryScreenPointContract,
} from './runDetailTypes';
import {
  mergeToolCallSnapshots,
  toolCallsFromRunEventReplay,
} from '../utils/runTimeline';
import {
  runRecoveryActionNeedsRetryField,
  runRecoveryInputPatchForAction,
} from '../utils/recoveryInput';

export function RunDetailPanel({
  artifactPreview,
  busy,
  formatRunDate,
  isActiveRunStatus,
  normalizeRunStatus,
  onApproveRunById,
  onCancelRunById,
  onLoadMoreSelectedGroupRunEvents,
  onLoadMoreSelectedRunEvents,
  onOpenArtifact,
  onOpenRunDetail,
  onOpenWorkflowDesign,
  onPrepareSelectedRunRerun,
  onRejectRunById,
  onRequestCancelSelectedRun,
  onRunGroupReplanRecoveryAction,
  onRunReplanRecoveryAction,
  onRunToolRecoveryAction,
  onRerunSelectedRun,
  onRerunWorkflowScope,
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
  artifactPreview: RunArtifactPreview | null;
  busy: boolean;
  formatRunDate: (value?: string) => string;
  isActiveRunStatus: (status: string) => boolean;
  normalizeRunStatus: (status: string) => string;
  onApproveRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onCancelRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onLoadMoreSelectedGroupRunEvents: () => Promise<void> | void;
  onLoadMoreSelectedRunEvents: () => Promise<void> | void;
  onOpenArtifact: (run: RunSpec | string, path: string) => Promise<void> | void;
  onOpenRunDetail: (runId: string) => void;
  onOpenWorkflowDesign: (workflowId: string) => void;
  onPrepareSelectedRunRerun: () => void;
  onRejectRunById: (runId: string, nextSelectedRunId?: string) => Promise<unknown>;
  onRequestCancelSelectedRun: () => void;
  onRunGroupReplanRecoveryAction?: (
    groupRunId: string,
    requestId: string,
    action: RuntimeToolRecoveryAction,
  ) => Promise<unknown> | unknown;
  onRunReplanRecoveryAction?: (
    runId: string,
    requestId: string,
    action: RuntimeToolRecoveryAction,
  ) => Promise<unknown> | unknown;
  onRunToolRecoveryAction?: (
    toolCall: ToolCallSnapshot,
    action: RuntimeToolRecoveryAction,
  ) => Promise<unknown> | unknown;
  onRerunSelectedRun: () => Promise<unknown>;
  onRerunWorkflowScope: (request: RerunRunRequest) => Promise<unknown>;
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
  const [recoveryCoordinate, setRecoveryCoordinate] = useState<RunRecoveryCoordinate | null>(null);
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
  const selectedRunRecoveryCoordinate = selectedRun && recoveryCoordinate?.run_id === selectedRun.run_id
    ? recoveryCoordinate
    : null;
  const recoveryScreenPointContract = runRecoveryScreenPointContractFromToolCalls(selectedRunToolCalls);
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
  const selectedRunPlannerEvents = selectedRunReplayEvents.length
    ? selectedRunReplayEvents
    : selectedPublicRunTimeline?.events || [];
  const plannerTraceSource = selectedRunReplayEvents.length
    ? 'RunEvent replay planner facts · Intent / Capability / Plan / Selection'
    : 'RunTimelineSnapshot planner facts · Intent / Capability / Plan / Selection';
  const rerunSourceRunId = selectedPublicRunTimeline?.rerun_of_run_id || selectedRun?.rerun_of_run_id || '';
  const rerunSourceLabel = selectedPublicRunTimeline?.rerun_of_runnable_name
    || selectedRun?.rerun_of_runnable_name
    || rerunSourceRunId;
  const showRunDetailRerunSource = Boolean(
    selectedRun
    && selectedRun.kind !== 'workflow_run'
    && rerunSourceRunId,
  );
  const recoverySource = selectedPublicRunTimeline?.recovery_source || selectedRun?.recovery_source || null;
  const recoverySourceRunId = String(recoverySource?.source_run_id || '').trim();
  const recoverySourceLabel = recoveryRunSourceLabel(recoverySource);
  const recoverySourceMeta = recoveryRunSourceMeta(recoverySource);
  const showRunDetailRecoverySource = Boolean(selectedRun && recoverySource);
  const selectedRunIdForReplanRecovery = selectedRun
    ? selectedPublicRunTimeline?.run_id || selectedRun.run_id
    : '';
  const handleRunReplanRecoveryAction = selectedRunIdForReplanRecovery
    ? (requestId: string, action: RuntimeToolRecoveryAction) => {
      void onRunReplanRecoveryAction?.(
        selectedRunIdForReplanRecovery,
        requestId,
        action,
      );
    }
    : undefined;
  const showTaskWorkspace = Boolean(
    selectedPublicRunTimeline?.task_core
    || selectedPublicRunTimeline?.task_progress
    || selectedPublicRunTimeline?.replan_recoveries?.length,
  );
  const selectedRunScopedWorkflowRerunDisabledReason = selectedRun?.kind === 'workflow_run'
    ? isActiveRunStatus(selectedRun.status)
      ? '当前 Workflow Run 还在进行中，请完成、失败或取消后再重跑。'
      : !selectedRun.user_goal?.trim()
        ? '原 Workflow Run 没有记录任务目标，无法重跑。'
        : ''
    : selectedRunRerunDisabledReason;
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
            {showRunDetailRerunSource ? (
              <button
                type="button"
                className="run-rerun-source-link"
                data-rerun-of-run-id={rerunSourceRunId}
                data-testid="agent-run-detail-rerun-source"
                onClick={() => onOpenRunDetail(rerunSourceRunId)}
              >
                rerun of {rerunSourceLabel}
              </button>
            ) : null}
            {showRunDetailRecoverySource ? (
              recoverySourceRunId ? (
                <button
                  type="button"
                  className="run-recovery-source-link"
                  data-recovery-action-id={recoverySource?.recovery_action_id || ''}
                  data-recovery-kind={recoverySource?.kind || ''}
                  data-recovery-source-run-id={recoverySourceRunId}
                  data-recovery-tool={recoverySource?.recovery_tool || ''}
                  data-testid="agent-run-detail-recovery-source"
                  onClick={() => onOpenRunDetail(recoverySourceRunId)}
                >
                  recovery of {recoverySourceLabel}
                </button>
              ) : (
                <span
                  className="run-recovery-source-link"
                  data-recovery-action-id={recoverySource?.recovery_action_id || ''}
                  data-recovery-kind={recoverySource?.kind || ''}
                  data-recovery-tool={recoverySource?.recovery_tool || ''}
                  data-testid="agent-run-detail-recovery-source"
                >
                  recovery of {recoverySourceLabel}
                </span>
              )
            ) : null}
            {recoverySourceMeta ? (
              <span
                className="run-recovery-source-tool"
                data-recovery-action-kind={recoverySource?.recovery_action_kind || ''}
                data-recovery-permission-target={recoverySource?.recovery_permission_target || ''}
                data-recovery-risk={recoverySource?.recovery_risk_level || ''}
                data-testid="agent-run-detail-recovery-source-meta"
              >
                {recoverySourceMeta}
              </span>
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
            onOpenArtifact={onOpenArtifact}
            onOpenRunDetail={onOpenRunDetail}
            onRunGroupReplanRecoveryAction={onRunGroupReplanRecoveryAction}
            onRunToolRecoveryAction={onRunToolRecoveryAction}
            recoveryActionDisabled={busy}
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
          <RuntimeDebugSummary
            className="run-detail-block run-runtime-debug-block"
            sourceLabel="RunTimelineSnapshot"
            summary={selectedPublicRunTimeline?.runtime_debug}
            testId="agent-run-detail-runtime-debug"
          />
          <RuntimeExecutionEnvelopeSummary
            className="run-detail-block run-runtime-execution-envelope-block"
            debugPillsTestId="agent-run-detail-runtime-execution-debug-pills"
            envelope={selectedPublicRunTimeline?.runtime_execution_envelope}
            requestListTestId="agent-run-detail-runtime-execution-requests"
            requestTestId="agent-run-detail-runtime-execution-request"
            showRequests
            sourceLabel="RunTimelineSnapshot runtime execution envelope"
            testId="agent-run-detail-runtime-execution-envelope"
            title="Runtime Execution"
            variant="studio"
          />
          {showTaskWorkspace ? (
            <details
              className="run-detail-block run-detail-fold run-task-workspace"
              data-core-id={selectedPublicRunTimeline?.task_core?.core_id || ''}
              data-task-progress-status={selectedPublicRunTimeline?.task_progress?.status || ''}
              data-testid="agent-run-detail-task-workspace"
              data-workspace-id={selectedPublicRunTimeline?.task_core?.workspace?.workspace_id || selectedPublicRunTimeline?.task_progress?.workspace_id || ''}
              open
            >
              <summary className="run-detail-section-head">
                <div>
                  <h4>Task Workspace</h4>
                  <span>{selectedPublicRunTimeline?.task_progress?.progress_text || selectedPublicRunTimeline?.task_core?.workspace?.title || 'workspace / todos / checkpoints / replan'}</span>
                </div>
              </summary>
              <div className="run-detail-fold-body studio-task-workspace">
                {selectedPublicRunTimeline?.task_core ? (
                  <TaskCoreInspector taskCore={selectedPublicRunTimeline.task_core} />
                ) : null}
                {selectedPublicRunTimeline?.task_progress || selectedPublicRunTimeline?.replan_recoveries?.length ? (
                  <TaskProgressInspector
                    onRunReplanRecoveryAction={handleRunReplanRecoveryAction}
                    recoveryActionDisabled={busy || !onRunReplanRecoveryAction}
                    replanRecoveries={selectedPublicRunTimeline?.replan_recoveries || []}
                    taskProgress={selectedPublicRunTimeline?.task_progress || null}
                  />
                ) : null}
              </div>
            </details>
          ) : null}
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
            onApproveRunById={onApproveRunById}
            onRejectRunById={onRejectRunById}
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
          <PlannerTraceInspector
            events={selectedRunPlannerEvents}
            onRunReplanRecoveryAction={handleRunReplanRecoveryAction}
            plannerSummary={selectedPublicRunTimeline?.planner_summary}
            recoveryActionDisabled={busy || !onRunReplanRecoveryAction}
            replanRecoveries={selectedPublicRunTimeline?.replan_recoveries || []}
            showTaskWorkspace={!showTaskWorkspace}
            sourceLabel={plannerTraceSource}
            taskCore={selectedPublicRunTimeline?.task_core}
            taskProgress={selectedPublicRunTimeline?.task_progress || null}
          />
          {selectedPublicRunTimeline || selectedRunToolCalls.length ? (
            <ToolCallInspector
              sourceLabel={toolCallSource}
              toolCalls={selectedRunToolCalls}
              onRunRecoveryAction={onRunToolRecoveryAction}
              recoveryActionInputPatch={(toolCall, action) => runRecoveryInputPatchForAction(
                action,
                selectedRunRecoveryCoordinate,
                toolCall,
              )}
              recoveryActionDisabled={busy}
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
          <WorkflowStepResults
            busy={busy}
            onOpenArtifact={onOpenArtifact}
            onOpenRunDetail={onOpenRunDetail}
            onRerunWorkflowScope={onRerunWorkflowScope}
            onRunAction={onRunAction}
            runById={runById}
            runStatusLabel={runStatusLabel}
            runStatusTone={runStatusTone}
            selectedRun={selectedRun}
            selectedRunRerunDisabledReason={selectedRunScopedWorkflowRerunDisabledReason}
            selectedWorkflowSteps={selectedWorkflowSteps}
            skippedWorkflowArtifactLabel={skippedWorkflowArtifactLabel}
            workflowRunArtifactForStep={workflowRunArtifactForStep}
            workflowStepArtifacts={workflowStepArtifacts}
            workflowStepKindLabel={workflowStepKindLabel}
            workflowStepSummary={workflowStepSummary}
          />
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
            onSelectImagePoint={(selection) => {
              setRecoveryCoordinate(runRecoveryCoordinateFromSelection(selectedRun.run_id, selection));
            }}
            recoveryScreenPointContract={recoveryScreenPointContract}
            selectedRun={selectedRun}
            selectedRunArtifacts={selectedRunArtifactFacts}
            selectedImagePoint={selectedRunRecoveryCoordinate}
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

function recoveryRunSourceLabel(source: RecoveryRunProvenanceSnapshot | null | undefined): string {
  if (!source) return 'source run';
  return source.source_task_title
    || source.source_tool_name
    || source.replan_request_id
    || source.source_run_id
    || source.source_group_run_id
    || source.source_workflow_run_id
    || 'source run';
}

function recoveryRunSourceMeta(source: RecoveryRunProvenanceSnapshot | null | undefined): string {
  if (!source) return '';
  const parts = [
    source.kind ? `kind ${source.kind}` : '',
    source.recovery_tool ? `tool ${source.recovery_tool}` : '',
    source.recovery_action_kind ? `action ${source.recovery_action_kind}` : '',
    source.recovery_permission_target ? `permission ${source.recovery_permission_target}` : '',
    source.recovery_risk_level ? `risk ${source.recovery_risk_level}` : '',
  ].filter(Boolean);
  return parts.join(' · ');
}

function runRecoveryScreenPointContractFromToolCalls(
  toolCalls: ToolCallSnapshot[],
): RunRecoveryScreenPointContract | null {
  for (const toolCall of toolCalls) {
    const inputPreview = objectValue(toolCall.input_preview);
    const outputPreview = objectValue(toolCall.output_preview);
    const actions = runtimeToolRecoveryActionsFromRecords(
      [outputPreview, inputPreview],
      {
        retry_input: inputPreview,
        retry_source_tool_call_id: toolCall.tool_call_id,
        retry_tool: String(toolCall.tool_name || '').trim(),
      },
    );
    const retryAction = actions
      .map((action) => runtimeToolRecoveryRetryAction(action))
      .find((action): action is RuntimeToolRecoveryAction => {
        if (!action || action.retry_input_source !== 'screen_capture_artifact') return false;
        return runRecoveryActionNeedsRetryField(action, 'x')
          || runRecoveryActionNeedsRetryField(action, 'y');
      });
    if (retryAction) {
      return {
        artifactKind: retryAction.retry_artifact_kind || 'image',
        artifactTool: retryAction.retry_artifact_tool || 'screen.capture',
      };
    }
  }
  return null;
}

function runRecoveryCoordinateFromSelection(
  runId: string,
  selection: RuntimeImageArtifactPointSelection,
): RunRecoveryCoordinate {
  return {
    artifact_id: selection.artifact.artifact_id,
    artifact_path: selection.artifact_path,
    kind: selection.artifact.kind,
    natural_height: selection.natural_height,
    natural_width: selection.natural_width,
    run_id: selection.artifact.run_id || selection.artifact.source_run_id || runId,
    source_tool: selection.artifact.source_tool,
    x: selection.x,
    y: selection.y,
  };
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
