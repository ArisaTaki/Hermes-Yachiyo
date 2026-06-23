import type { RunGroupSpec, RunSpec } from '../types';
import type {
  GroupRunSnapshot,
  PublicRunEvent,
  RunTimelineSnapshot,
  ToolCallSnapshot,
} from '../../yachiyo-studio/types';
import { MemorySkillTraceInspector } from './MemorySkillTraceInspector';
import { RuntimeApprovalCard } from '../../runtime-shared/components/RuntimeApprovalCard';
import { RuntimeArtifactList } from '../../runtime-shared/components/RuntimeArtifactList';
import { RuntimeTimelineSummary } from '../../runtime-shared/components/RuntimeTimelineSummary';
import type { RuntimeToolRecoveryAction } from '../../runtime-shared/toolRecoveryActions';
import { ToolCallInspector } from './ToolCallInspector';
import {
  approvalsFromRunEventReplay,
  artifactsFromRunEventReplay,
  mergeApprovalSnapshots,
  mergeArtifactSnapshots,
  mergeToolCallSnapshots,
  toolCallsFromRunEventReplay,
} from '../../runtime-shared/runEventFacts';

type GroupRunDetailPanelProps = {
  formatRunDate: (value?: string) => string;
  onLoadMoreGroupRunEvents: () => Promise<unknown> | unknown;
  onOpenArtifact: (run: RunSpec | string, path: string) => Promise<void> | void;
  onOpenRunDetail: (runId: string) => void;
  onRunToolRecoveryAction?: (
    toolCall: ToolCallSnapshot,
    action: RuntimeToolRecoveryAction,
  ) => Promise<unknown> | unknown;
  recoveryActionDisabled?: boolean;
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

type GroupRunChildRunRef = {
  loadedRun: RunSpec | null;
  publicRun: RunTimelineSnapshot | null;
  runId: string;
};

export function GroupRunDetailPanel({
  formatRunDate,
  onLoadMoreGroupRunEvents,
  onOpenArtifact,
  onOpenRunDetail,
  onRunToolRecoveryAction,
  recoveryActionDisabled = false,
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
  const legacyGroupChildRunIds = selectedRunGroup?.child_run_ids?.length
    ? selectedRunGroup.child_run_ids
    : selectedGroupRunSnapshot?.child_run_ids || [];
  const groupOverviewChildRuns = groupRunChildRunRefs(
    selectedGroupRunSnapshot?.runs || [],
    legacyGroupChildRunIds,
    runById,
  );
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
  const replayToolCalls = replayEvents.length ? toolCallsFromRunEventReplay(replayEvents) : [];
  const groupRunApprovalFacts = mergeApprovalSnapshots(groupRunApprovals, replayApprovals);
  const groupRunArtifactFacts = mergeArtifactSnapshots(groupRunArtifacts, replayArtifacts);
  const snapshotToolCalls = selectedGroupRunSnapshot?.tool_calls?.length
    ? selectedGroupRunSnapshot.tool_calls
    : groupRunChildToolCalls(selectedGroupRunSnapshot?.runs || []);
  const groupRunToolCalls = snapshotToolCalls.length
    ? mergeToolCallSnapshots(snapshotToolCalls, [])
    : replayToolCalls;
  const groupRunMemoryTraces = selectedGroupRunSnapshot?.memory_traces?.length
    ? selectedGroupRunSnapshot.memory_traces
    : groupRunChildMemoryTraces(selectedGroupRunSnapshot?.runs || []);
  const groupRunSkillTraces = selectedGroupRunSnapshot?.skill_traces?.length
    ? selectedGroupRunSnapshot.skill_traces
    : groupRunChildSkillTraces(selectedGroupRunSnapshot?.runs || []);
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
            {selectedRunGroup?.source || selectedGroupRunSnapshot?.group_id || 'group'} · {groupOverviewChildRuns.length} child runs
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
      {groupRunToolCalls.length ? (
        <section className="group-run-runtime-section" data-testid="agent-run-detail-group-run-tool-calls">
          <ToolCallInspector
            cardTestId="agent-run-detail-group-run-tool-call-card"
            listTestId="agent-run-detail-group-run-tool-call-list"
            sourceLabel="GroupRunSnapshot + RunEvent replay tool facts"
            testId="agent-run-detail-group-run-tool-call-inspector"
            toolCalls={groupRunToolCalls}
            onRunRecoveryAction={onRunToolRecoveryAction}
            recoveryActionDisabled={recoveryActionDisabled}
          />
        </section>
      ) : null}
      {groupRunMemoryTraces.length || groupRunSkillTraces.length || groupRunReplayEvents.some(groupRunEventIsMemorySkillTrace) ? (
        <section className="group-run-runtime-section" data-testid="agent-run-detail-group-run-memory-skill-traces">
          <MemorySkillTraceInspector
            contextTestId="agent-run-detail-group-run-memory-skill-trace-context"
            events={groupRunReplayEvents}
            itemTestId="agent-run-detail-group-run-memory-skill-trace"
            listTestId="agent-run-detail-group-run-memory-skill-trace-list"
            memoryTraces={groupRunMemoryTraces}
            skillTraces={groupRunSkillTraces}
            sourceLabel="GroupRunSnapshot + RunEvent replay trace facts"
            testId="agent-run-detail-group-run-memory-skill-trace-inspector"
          />
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
            onOpenArtifact={onOpenArtifact}
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
      {groupOverviewChildRuns.length ? (
        <div className="run-group-overview-children" data-testid="agent-run-detail-group-run-children">
          {groupOverviewChildRuns.map(({ loadedRun: childRun, publicRun, runId: childRunId }) => {
            const selected = childRunId === selectedRun.run_id;
            const childStatus = publicRun?.status || childRun?.status || '';
            const childKind = groupRunChildKind(publicRun, childRun);
            return (
              <button
                key={childRunId}
                type="button"
                className={selected ? 'selected' : ''}
                data-agent-id={publicRun?.agent_id || childRun?.runnable_id || ''}
                data-run-id={childRunId}
                data-run-status={childStatus}
                data-testid="agent-run-detail-group-run-child"
                data-workflow-run-id={publicRun?.workflow_run_id || childRun?.workflow_run_id || ''}
                onClick={() => onOpenRunDetail(childRunId)}
              >
                <span>{publicRun?.title || childRun?.runnable_name || childRun?.runnable_id || childRunId}</span>
                <small>
                  {selected ? '当前 Run · ' : ''}
                  {groupRunChildMeta(publicRun, childRun, runKindLabel(childKind), runStatusLabel(childStatus))}
                </small>
              </button>
            );
          })}
        </div>
      ) : null}
    </section>
  );
}

function groupRunChildRunRefs(
  publicRuns: RunTimelineSnapshot[],
  childRunIds: string[],
  runById: Map<string, RunSpec>,
): GroupRunChildRunRef[] {
  const refs: GroupRunChildRunRef[] = [];
  const seen = new Set<string>();
  for (const publicRun of publicRuns) {
    const runId = publicRun.run_id;
    if (!runId || seen.has(runId)) continue;
    seen.add(runId);
    refs.push({ loadedRun: runById.get(runId) || null, publicRun, runId });
  }
  for (const runId of childRunIds) {
    if (!runId || seen.has(runId)) continue;
    seen.add(runId);
    refs.push({ loadedRun: runById.get(runId) || null, publicRun: null, runId });
  }
  return refs;
}

function groupRunChildToolCalls(publicRuns: RunTimelineSnapshot[]) {
  return publicRuns.flatMap((run) => run.tool_calls || []);
}

function groupRunChildMemoryTraces(publicRuns: RunTimelineSnapshot[]) {
  return publicRuns.flatMap((run) => run.memory_traces || []);
}

function groupRunChildSkillTraces(publicRuns: RunTimelineSnapshot[]) {
  return publicRuns.flatMap((run) => run.skill_traces || []);
}

function groupRunEventIsMemorySkillTrace(event: PublicRunEvent): boolean {
  const eventType = String(event.event_type || '').trim();
  return eventType.startsWith('memory.') || eventType.startsWith('skill.');
}

function groupRunChildKind(publicRun: RunTimelineSnapshot | null, childRun: RunSpec | null): string {
  if (childRun?.kind) return childRun.kind;
  if (publicRun?.workflow_run_id) return 'workflow_run';
  if (publicRun?.agent_id) return 'agent_run';
  return 'run';
}

function groupRunChildMeta(
  publicRun: RunTimelineSnapshot | null,
  childRun: RunSpec | null,
  kindLabel: string,
  statusLabel: string,
): string {
  return [
    publicRun || childRun ? `${kindLabel} · ${statusLabel}` : '未加载',
    publicRun?.agent_id ? `agent ${publicRun.agent_id}` : '',
    publicRun?.workflow_run_id ? `workflow run ${publicRun.workflow_run_id}` : '',
    publicRun?.task_id ? `task ${publicRun.task_id}` : '',
    publicRun?.session_id ? `session ${publicRun.session_id}` : '',
    publicRun?.events?.length ? `events ${publicRun.events.length}` : '',
    publicRun?.tool_calls?.length ? `tools ${publicRun.tool_calls.length}` : '',
    publicRun?.approvals?.length ? `approvals ${publicRun.approvals.length}` : '',
    publicRun?.artifacts?.length ? `artifacts ${publicRun.artifacts.length}` : '',
  ].filter(Boolean).join(' · ');
}
