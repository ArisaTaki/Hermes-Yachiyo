import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import type { Connection, Edge, Node } from '@xyflow/react';
import {
  addEdge,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { AgentEditorPanel, type AgentDraft } from '../features/agent-studio/components/AgentEditorPanel';
import { AgentGroupPanel } from '../features/agent-studio/components/AgentGroupPanel';
import { AgentListPanel } from '../features/agent-studio/components/AgentListPanel';
import { RuntimeMemoryPanel } from '../features/agent-studio/components/RuntimeMemoryPanel';
import { RunDetailPanel } from '../features/agent-studio/components/RunDetailPanel';
import { RunLauncherPanel } from '../features/agent-studio/components/RunLauncherPanel';
import { WorkflowEditorPanel, WorkflowRunPreview } from '../features/agent-studio/components/WorkflowEditorPanel';
import { useAgentDefinitions } from '../features/agent-studio/hooks/useAgentDefinitions';
import { useAgentGroups } from '../features/agent-studio/hooks/useAgentGroups';
import { useApprovedRunGuard } from '../features/agent-studio/hooks/useApprovedRunGuard';
import { useRunEventReplay } from '../features/agent-studio/hooks/useRunEventReplay';
import { useRunTimeline } from '../features/agent-studio/hooks/useRunTimeline';
import { useWorkflowDefinitions } from '../features/agent-studio/hooks/useWorkflowDefinitions';
import {
  agentCapabilityLine,
  agentRunReadinessIssue,
  agentToDraft,
  draftToolPolicy,
  runnableCapabilityLine,
  runnableOptionLabel,
  textToScopes,
} from '../features/agent-studio/utils/agents';
import {
  approvedRunStatusMessage,
  formatRunDate,
  isActiveRunStatus,
  isPotentialWorkflowChildAgentRun,
  isWorkflowChildAgentRun,
  makeRunContinuingAfterApproval,
  normalizeRunStatus,
  publicApprovalToRunPendingApproval,
  publicArtifactsOrLegacy,
  publicRunEventToTimelineEvent,
  runHistoryGroupKey,
  runHistoryGroupsFor,
  runHistoryGroupSummary,
  runKindLabel,
  runMatchesFilter,
  runMatchesSearch,
  runMatchesStatusFilter,
  runSearchTextByRunnableIdFor,
  runStatusLabel,
  runStatusTone,
  type RunHistoryGroup,
  type RunKindFilter,
  type RunStatusFilter,
} from '../features/agent-studio/utils/runs';
import {
  runEventReplayToTimelineEvent,
} from '../features/agent-studio/utils/runTimeline';
import {
  isInstalledSkill,
  isNativeSkill,
  localSourceAlias,
  normalizeSkillSources,
  skillFolderNameError,
  skillFolderNameMaxLength,
  skillMatchesFolderFilter,
  skillMatchesQuery,
  skillMatchesSourceFilter,
  skillPathLabel,
  skillResultStatusLabel,
  skillSourceLabel,
  skillSourceTypeLabel,
  syncResultsToImportResults,
  type SkillFolderFilter,
  type SkillImportResult,
  type SkillSourceFilter,
} from '../features/agent-studio/utils/skills';
import { groupRunTimelineRunId } from '../features/agent-studio/utils/groups';
import {
  buildPhase4WorkflowNodes,
  linearEdgesForNodes,
  skippedWorkflowArtifactLabel,
  starterNodes,
  terminalNodeId,
  uniqueWorkflowNodeId,
  validateWorkflowDraft,
  workflowAgentRunReadinessIssue,
  workflowChildRunRefs,
  workflowEdges,
  workflowHasRunnableSteps,
  workflowNodes,
  workflowPendingApprovalChildRunId,
  workflowRequestEdges,
  workflowRequestNodes,
  workflowRunArtifactForStep,
  workflowRunHasChildRun,
  workflowRunnableStepRequiredMessage,
  workflowSpecStepRefs,
  workflowStepArtifacts,
  workflowStepKindLabel,
  workflowStepRefs,
  workflowStepSummary,
} from '../features/agent-studio/utils/workflow';
import type { GroupRunSnapshot } from '../features/yachiyo-studio/types';
import {
  attachSkill,
  approveRunApproval,
  cancelRun,
  cancelFutureTask,
  createSkillFolder,
  createAgent,
  createAgentRun,
  createWorkflow,
  createWorkflowRun,
  deleteAgent,
  deleteMemory,
  deleteRun,
  deleteSkillFolder,
  deleteSkill,
  deleteWorkflow,
  detachSkill,
  getRun,
  getRunArtifact,
  getRunGroup,
  importSkill,
  installSkillCommand,
  listAgents,
  listFutureTasks,
  listMemories,
  listRunGroups,
  listRunnables,
  listRuns,
  listSkillFolders,
  listSkillSources,
  listSkills,
  listWorkflows,
  rejectRunApproval,
  rerunRun,
  syncNativeSkills,
  testAgentModel,
  triggerDueFutureTasks,
  updateAgent,
  updateSkill,
  updateSkillFolder,
  updateWorkflow,
  type AgentSpec,
  type FutureTaskSpec,
  type MemorySpec,
  type RunnableSummary,
  type RunGroupSpec,
  type RunSpec,
  type SkillFolderSpec,
  type SkillSourceRoot,
  type SkillSpec,
  type WorkflowSpec,
} from '../lib/agents';
import { chooseAvatarImage, chooseSkillSources, openAppView, openPath } from '../lib/bridge';
import { listModelProfiles, type ModelProfile, type ModelProfileDefaults } from '../lib/modelProfiles';
import { currentParam, navigateTo } from '../lib/view';

type StudioTab = 'agents' | 'groups' | 'skills' | 'skill-groups' | 'workflows' | 'runs' | 'memory';

type StudioRefreshOptions = {
  selectedAgentId?: string;
  selectFirstAgent?: boolean;
  selectedWorkflowId?: string;
  selectFirstWorkflow?: boolean;
  runTarget?: string;
  selectedRunId?: string;
  statusMessage?: string;
  skipRefresh?: boolean;
};

const runApprovalPollAttempts = 100;
const runApprovalPollIntervalMs = 1200;

type ConfirmDialogState = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

const emptyAgentDraft: AgentDraft = {
  name: '',
  nickname: '',
  description: '',
  avatar_url: '',
  category: 'custom',
  instructions: '',
  persona_prompt: '',
  model_mode: 'profile',
  model_profile_id: '',
  vision_model_profile_id: '',
  base_url: '',
  model: '',
  api_key: '',
  output_contract: 'chat',
  allow_workspace_read: false,
  allow_workspace_write: false,
  allow_terminal: false,
  allow_artifacts: true,
  default_workdir: '',
  readable_scopes: '.',
  writable_scopes: '',
  enabled: true,
};

const studioRouteTabs: StudioTab[] = ['agents', 'groups', 'skills', 'skill-groups', 'workflows', 'runs', 'memory'];
const studioTabs: StudioTab[] = ['agents', 'groups', 'skills', 'workflows', 'runs', 'memory'];

function AgentStudioLoadingState() {
  return (
    <section className="agent-studio-grid agent-studio-loading" aria-label="正在读取 Agent Studio">
      <aside className="agent-studio-panel">
        <div className="section-heading-row">
          <span className="agent-studio-skeleton-line title" />
          <span className="agent-studio-skeleton-button" />
        </div>
        <div className="agent-studio-skeleton-list">
          {Array.from({ length: 5 }).map((_, index) => (
            <div className="agent-studio-skeleton-card" key={index}>
              <span className="agent-studio-skeleton-avatar" />
              <span className="agent-studio-skeleton-stack">
                <span className="agent-studio-skeleton-line name" />
                <span className="agent-studio-skeleton-line meta" />
              </span>
            </div>
          ))}
        </div>
      </aside>
      <div className="agent-studio-panel">
        <div className="section-heading-row">
          <span className="agent-studio-skeleton-line title wide" />
        </div>
        <div className="agent-studio-skeleton-form">
          <span className="agent-studio-skeleton-avatar large" />
          <span className="agent-studio-skeleton-line field" />
          <span className="agent-studio-skeleton-line field" />
          <span className="agent-studio-skeleton-line field wide" />
          <span className="agent-studio-skeleton-block" />
          <span className="agent-studio-skeleton-block short" />
        </div>
      </div>
    </section>
  );
}

function toggleSelectedId(current: string[], id: string): string[] {
  if (!id) return current;
  if (current.includes(id)) return current.filter((item) => item !== id);
  return [...current, id];
}

function pruneSelectedIds(current: string[], availableIds: string[]): string[] {
  const available = new Set(availableIds);
  const next = current.filter((id) => available.has(id));
  if (next.length === current.length) return current;
  return next;
}

function normalizeStudioTab(value: string): StudioTab {
  return studioRouteTabs.includes(value as StudioTab) ? value as StudioTab : 'agents';
}

export function AgentStudioView() {
  const routeRunId = currentParam('run').trim();
  const routeRunTarget = currentParam('target').trim();
  const routeRunGoal = currentParam('goal').trim();
  const routeTab = normalizeStudioTab(currentParam('tab'));
  const [tab, setTab] = useState<StudioTab>(() => routeRunId || routeRunTarget ? 'runs' : routeTab);
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [modelDefaults, setModelDefaults] = useState<ModelProfileDefaults>({});
  const [runnables, setRunnables] = useState<RunnableSummary[]>([]);
  const [runs, setRuns] = useState<RunSpec[]>([]);
  const [runGroups, setRunGroups] = useState<RunGroupSpec[]>([]);
  const [memories, setMemories] = useState<MemorySpec[]>([]);
  const [futureTasks, setFutureTasks] = useState<FutureTaskSpec[]>([]);
  const [runDetailCache, setRunDetailCache] = useState<RunSpec[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [skillManagementMode, setSkillManagementMode] = useState(false);
  const [runHistoryManagementMode, setRunHistoryManagementMode] = useState(false);
  const [draft, setDraft] = useState<AgentDraft>(emptyAgentDraft);
  const [skillSources, setSkillSources] = useState<SkillSourceRoot[]>([]);
  const [skillFolders, setSkillFolders] = useState<SkillFolderSpec[]>([]);
  const [newSkillFolderName, setNewSkillFolderName] = useState('');
  const [editingSkillFolderId, setEditingSkillFolderId] = useState('');
  const [editingSkillFolderName, setEditingSkillFolderName] = useState('');
  const [skillFolderDeleteModes, setSkillFolderDeleteModes] = useState<Record<string, 'folder' | 'skills'>>({});
  const [skillTargetFolderId, setSkillTargetFolderId] = useState('');
  const [skillInstallCommand, setSkillInstallCommand] = useState('');
  const [skillImportResults, setSkillImportResults] = useState<SkillImportResult[]>([]);
  const [skillLibraryFilter, setSkillLibraryFilter] = useState<SkillSourceFilter>('installed');
  const [skillLibraryFolderFilter, setSkillLibraryFolderFilter] = useState<SkillFolderFilter>('all');
  const [skillLibrarySearch, setSkillLibrarySearch] = useState('');
  const [skillMountFilter, setSkillMountFilter] = useState<SkillSourceFilter>('installed');
  const [skillMountFolderFilter, setSkillMountFolderFilter] = useState<SkillFolderFilter>('all');
  const [skillMountSearch, setSkillMountSearch] = useState('');
  const [workflowName, setWorkflowName] = useState('New Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [workflowEnabled, setWorkflowEnabled] = useState(true);
  const [agentRunGoal, setAgentRunGoal] = useState('');
  const [workflowRunGoal, setWorkflowRunGoal] = useState('');
  const [runTarget, setRunTarget] = useState(() => routeRunTarget);
  const [runGoal, setRunGoal] = useState(() => routeRunGoal);
  const [runKindFilter, setRunKindFilter] = useState<RunKindFilter>('all');
  const [runStatusFilter, setRunStatusFilter] = useState<RunStatusFilter>('all');
  const [runSearchQuery, setRunSearchQuery] = useState('');
  const [collapsedRunHistoryGroups, setCollapsedRunHistoryGroups] = useState<Set<string>>(new Set());
  const [selectedRunId, setSelectedRunId] = useState(() => routeRunId);
  const selectedRunIdRef = useRef(selectedRunId);
  const [artifactPreview, setArtifactPreview] = useState<{ path: string; content: string; truncated?: boolean } | null>(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(starterNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const busy = loading || Boolean(busyAction);
  const installingSkill = busyAction === '安装 Skill';
  const isSkillLibraryTab = tab === 'skills' || tab === 'skill-groups';
  const {
    agentGroups,
    agentGroupMemberIds,
    agentGroupName,
    agentGroupRunGoal,
    latestAgentGroupRun,
    loadAgentGroups,
    runAgentGroup,
    saveAgentGroupDraft,
    selectAgentGroup,
    selectedAgentGroup,
    selectedAgentGroupId,
    setAgentGroupName,
    setAgentGroupRunGoal,
    startNewAgentGroup,
    toggleAgentGroupMember,
  } = useAgentGroups();
  const {
    agentManagementMode,
    agents,
    allAgentsSelected,
    applyAgents,
    deletableAgentIds,
    finishAgentManagement,
    selectedAgent,
    selectedAgentDeletable,
    selectedAgentId,
    selectedAgentIdSet,
    selectedAgentReadOnly,
    selectedAgents,
    selectedDeletableAgents,
    setAgentManagementMode,
    setSelectedAgentId,
    setSelectedAgentIds,
    toggleAgentSelected,
  } = useAgentDefinitions();
  const {
    allWorkflowsSelected,
    applyWorkflows,
    finishWorkflowManagement,
    selectedWorkflow,
    selectedWorkflowId,
    selectedWorkflowIdSet,
    selectedWorkflows,
    setSelectedWorkflowId,
    setSelectedWorkflowIds,
    setWorkflowManagementMode,
    toggleWorkflowSelected,
    workflowIds,
    workflowManagementMode,
    workflows,
  } = useWorkflowDefinitions();

  const chatModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => profile.capability === 'chat' && profile.status === 'available' && profile.enabled !== false),
    [modelProfiles],
  );
  const visionModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => profile.capability === 'vision' && profile.status === 'available' && profile.enabled !== false),
    [modelProfiles],
  );
  const workflowValidation = useMemo(
    () => validateWorkflowDraft(nodes, edges, agents, workflows, selectedWorkflow?.workflow_id || ''),
    [agents, edges, nodes, selectedWorkflow?.workflow_id, workflows],
  );
  const workflowNameError = workflowName.trim() ? '' : 'Workflow 名称不能为空';
  const workflowErrors = workflowNameError ? [workflowNameError, ...workflowValidation.errors] : workflowValidation.errors;
  const workflowRunPreviewSteps = useMemo(
    () => workflowSpecStepRefs({
      workflow_id: selectedWorkflow?.workflow_id || 'draft',
      name: workflowName.trim() || 'New Workflow',
      description: workflowDescription.trim(),
      nodes: workflowRequestNodes(nodes),
      edges: workflowRequestEdges(edges),
      enabled: true,
    }),
    [edges, nodes, selectedWorkflow?.workflow_id, workflowDescription, workflowName],
  );
  const workflowHasErrors = workflowErrors.length > 0;
  const workflowPrimaryError = workflowErrors[0] || '';
  const agentRunIssueById = useMemo(() => {
    const next = new Map<string, string>();
    agents.forEach((agent) => {
      const issue = agentRunReadinessIssue(agent, chatModelProfiles, modelDefaults, skills);
      if (issue) next.set(agent.agent_id, issue);
    });
    return next;
  }, [agents, chatModelProfiles, modelDefaults, skills]);
  const workflowRunAgentIssue = useMemo(
    () => workflowAgentRunReadinessIssue(nodes, agentRunIssueById),
    [agentRunIssueById, nodes],
  );
  const runById = useMemo(
    () => {
      const next = new Map<string, RunSpec>();
      runDetailCache.forEach((run) => next.set(run.run_id, run));
      runs.forEach((run) => next.set(run.run_id, run));
      return next;
    },
    [runDetailCache, runs],
  );
  const selectedRun = useMemo(
    () => selectedRunId ? runById.get(selectedRunId) || null : null,
    [runById, selectedRunId],
  );
  const selectedRunReplayRefreshKey = useMemo(
    () => selectedRunId
      ? [
          selectedRunId,
          selectedRun?.updated_at || '',
          selectedRun?.status || '',
          selectedRun?.timeline?.length || 0,
        ].join('|')
      : '',
    [selectedRun, selectedRunId],
  );
  const { selectedPublicRunTimeline } = useRunTimeline(selectedRunId, selectedRunReplayRefreshKey);
  const {
    clearRunEventReplay,
    loadMoreSelectedRunEvents: loadMoreRunReplayEvents,
    selectedReplayError: selectedRunReplayError,
    selectedReplayEvents: selectedRunReplayEvents,
    selectedReplayHasMore: selectedRunReplayHasMore,
    selectedReplayLoading: selectedRunReplayLoading,
  } = useRunEventReplay(selectedRunId, selectedRunReplayRefreshKey);
  const {
    acceptedRunUpdates,
    rememberApprovedRun,
  } = useApprovedRunGuard();
  const selectedRunExecutionEvents = useMemo(
    () => selectedRunReplayEvents.length
      ? selectedRunReplayEvents.map(runEventReplayToTimelineEvent)
      : selectedPublicRunTimeline?.events?.length
        ? selectedPublicRunTimeline.events.map(publicRunEventToTimelineEvent)
      : selectedRun?.timeline || [],
    [selectedPublicRunTimeline, selectedRun, selectedRunReplayEvents],
  );
  const selectedPublicRunApproval = useMemo(
    () => (
      selectedPublicRunTimeline?.pending_approval
      || selectedPublicRunTimeline?.approvals?.find((approval) => approval.status === 'pending')
      || null
    ),
    [selectedPublicRunTimeline],
  );
  const selectedRunApproval = useMemo(
    () => (
      publicApprovalToRunPendingApproval(selectedPublicRunApproval)
      || selectedRun?.pending_approval
      || null
    ),
    [selectedPublicRunApproval, selectedRun],
  );
  const selectedRunArtifacts = useMemo(
    () => publicArtifactsOrLegacy(
      selectedPublicRunTimeline?.artifacts,
      selectedRun?.artifacts as Array<Record<string, unknown>> | undefined,
    ),
    [selectedPublicRunTimeline, selectedRun],
  );
  const selectedRunTarget = useMemo(
    () => runTarget ? runnables.find((item) => item.id === runTarget) || null : null,
    [runTarget, runnables],
  );
  const selectedRunTargetWorkflow = useMemo(
    () => selectedRunTarget?.kind === 'workflow'
      ? workflows.find((workflow) => workflow.workflow_id === selectedRunTarget.id) || null
      : null,
    [selectedRunTarget, workflows],
  );
  const selectedRunTargetWorkflowNodes = useMemo(
    () => selectedRunTargetWorkflow ? workflowNodes(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowEdges = useMemo(
    () => selectedRunTargetWorkflow ? workflowEdges(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowPreviewSteps = useMemo(
    () => selectedRunTargetWorkflow ? workflowSpecStepRefs(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowValidation = useMemo(
    () => selectedRunTargetWorkflow
      ? validateWorkflowDraft(
        selectedRunTargetWorkflowNodes,
        selectedRunTargetWorkflowEdges,
        agents,
        workflows,
        selectedRunTargetWorkflow.workflow_id,
      )
      : { errors: [], warnings: [] },
    [agents, selectedRunTargetWorkflow, selectedRunTargetWorkflowEdges, selectedRunTargetWorkflowNodes, workflows],
  );
  const selectedRunTargetWorkflowAgentIssue = useMemo(
    () => selectedRunTargetWorkflow
      ? workflowAgentRunReadinessIssue(selectedRunTargetWorkflowNodes, agentRunIssueById)
      : '',
    [agentRunIssueById, selectedRunTargetWorkflow, selectedRunTargetWorkflowNodes],
  );
  const selectedRunTargetDisabled = selectedRunTarget?.enabled === false;
  const runTargetDisabledReason = useMemo(() => {
    if (!selectedRunTarget) return '';
    if (selectedRunTargetDisabled) return '目标已停用，无法运行。';
    if (selectedRunTarget.kind === 'agent') {
      const agent = agents.find((item) => item.agent_id === selectedRunTarget.id);
      if (!agent) return '找不到 Agent 定义，无法运行。';
      return agentRunIssueById.get(agent.agent_id) || '';
    }
    if (selectedRunTarget.kind === 'workflow') {
      if (!selectedRunTargetWorkflow) return '找不到 Workflow 定义，无法运行。';
      if (selectedRunTargetWorkflowValidation.errors.length) {
        return selectedRunTargetWorkflowValidation.errors[0] || '当前 Workflow 存在校验错误。';
      }
      if (!workflowHasRunnableSteps(selectedRunTargetWorkflowNodes)) {
        return workflowRunnableStepRequiredMessage;
      }
      if (selectedRunTargetWorkflowAgentIssue) return selectedRunTargetWorkflowAgentIssue;
    }
    return '';
  }, [agentRunIssueById, agents, selectedRunTarget, selectedRunTargetDisabled, selectedRunTargetWorkflow, selectedRunTargetWorkflowAgentIssue, selectedRunTargetWorkflowNodes, selectedRunTargetWorkflowValidation.errors]);
  const workflowRunDisabledReason = useMemo(() => {
    if (!workflowEnabled) return '当前 Workflow 已停用，无法运行。';
    if (workflowNameError) return workflowNameError;
    if (workflowHasErrors) return workflowPrimaryError || '当前 Workflow 存在校验错误。';
    if (!workflowRunGoal.trim()) return '请输入运行目标。';
    if (!workflowHasRunnableSteps(nodes)) return workflowRunnableStepRequiredMessage;
    if (workflowRunAgentIssue) return workflowRunAgentIssue;
    return '';
  }, [nodes, workflowEnabled, workflowHasErrors, workflowNameError, workflowPrimaryError, workflowRunAgentIssue, workflowRunGoal]);
  const workflowRunDisabled = busy || Boolean(workflowRunDisabledReason);
  const runFilterCounts = useMemo(
    () => ({
      all: runs.filter((run) => runMatchesFilter(run, 'all')).length,
      workflow: runs.filter((run) => runMatchesFilter(run, 'workflow')).length,
      agent: runs.filter((run) => runMatchesFilter(run, 'agent')).length,
    }),
    [runs],
  );
  const runKindFilteredRuns = useMemo(
    () => runs.filter((run) => runMatchesFilter(run, runKindFilter)),
    [runs, runKindFilter],
  );
  const runStatusFilterCounts = useMemo(
    () => ({
      all: runKindFilteredRuns.length,
      completed: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'completed')).length,
      failed: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'failed')).length,
      active: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'active')).length,
    }),
    [runKindFilteredRuns],
  );
  const runStatusFilteredRuns = useMemo(
    () => runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, runStatusFilter)),
    [runKindFilteredRuns, runStatusFilter],
  );
  const runSearchActive = Boolean(runSearchQuery.trim());
  const runSearchTextByRunnableId = useMemo(
    () => runSearchTextByRunnableIdFor(runnables, agents, workflows),
    [agents, runnables, workflows],
  );
  const filteredRuns = useMemo(
    () => runStatusFilteredRuns.filter((run) => (
      runMatchesSearch(run, runSearchQuery, runSearchTextByRunnableId.get(run.runnable_id) || '')
    )),
    [runSearchQuery, runSearchTextByRunnableId, runStatusFilteredRuns],
  );
  const filteredRunIds = useMemo(
    () => filteredRuns.map((run) => run.run_id).filter(Boolean),
    [filteredRuns],
  );
  const selectedRunIdSet = useMemo(() => new Set(selectedRunIds), [selectedRunIds]);
  const selectedHistoryRuns = useMemo(
    () => filteredRuns.filter((run) => selectedRunIdSet.has(run.run_id)),
    [filteredRuns, selectedRunIdSet],
  );
  const selectedHistoryActiveRunCount = useMemo(
    () => selectedHistoryRuns.filter((run) => isActiveRunStatus(run.status)).length,
    [selectedHistoryRuns],
  );
  const runBulkDeleteDisabledReason = selectedHistoryActiveRunCount
    ? `有 ${selectedHistoryActiveRunCount} 个 Run 仍在进行中或待审批，请先取消或等待结束后再删除。`
    : '';
  const allHistoryRunsSelected = filteredRunIds.length > 0 && selectedHistoryRuns.length === filteredRunIds.length;
  const runHistoryGroups = useMemo(
    () => runHistoryGroupsFor(filteredRuns, runnables, agents),
    [agents, filteredRuns, runnables],
  );
  const selectedRunWorkflow = useMemo(
    () => (
      selectedRun?.kind === 'workflow_run'
        ? workflows.find((workflow) => workflow.workflow_id === selectedRun.runnable_id) || null
        : null
    ),
    [selectedRun, workflows],
  );
  const selectedWorkflowSteps = useMemo(
    () => workflowStepRefs(selectedRun, selectedRunWorkflow),
    [selectedRun, selectedRunWorkflow],
  );
  const selectedWorkflowChildRefs = useMemo(
    () => workflowChildRunRefs(selectedRun),
    [selectedRun],
  );
  const selectedWorkflowApprovalChildRunId = useMemo(
    () => workflowPendingApprovalChildRunId(selectedRun),
    [selectedRun],
  );
  const selectedWorkflowApprovalChildRun = selectedWorkflowApprovalChildRunId
    ? runById.get(selectedWorkflowApprovalChildRunId) || null
    : null;
  const selectedWorkflowApprovalStep = selectedWorkflowApprovalChildRunId
    ? selectedWorkflowSteps.find((step) => step.childRunId === selectedWorkflowApprovalChildRunId) || null
    : null;
  const selectedWorkflowParentRun = useMemo(() => {
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return null;
    const timelineParent = Array.from(runById.values()).find((run) => (
      run.kind === 'workflow_run'
      && run.run_group_id === selectedRun.run_group_id
      && workflowRunHasChildRun(run, selectedRun.run_id)
    ));
    if (timelineParent) return timelineParent;
    if (!isWorkflowChildAgentRun(selectedRun)) return null;
    return Array.from(runById.values()).find((run) => (
      run.kind === 'workflow_run'
      && run.run_group_id === selectedRun.run_group_id
    )) || null;
  }, [runById, selectedRun]);
  const selectedWorkflowParentRunId = useMemo(() => {
    if (selectedWorkflowParentRun) return selectedWorkflowParentRun.run_id;
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return '';
    const group = runGroups.find((item) => item.run_group_id === selectedRun.run_group_id);
    const childRunIds = group?.child_run_ids || [];
    return childRunIds.find((runId) => {
      const run = runById.get(runId);
      return run?.kind === 'workflow_run' && workflowRunHasChildRun(run, selectedRun.run_id);
    }) || childRunIds.find((runId) => runId.startsWith('workflow_run_')) || '';
  }, [runById, runGroups, selectedRun, selectedWorkflowParentRun]);
  const activeRunPollKey = useMemo(() => {
    const nextIds = new Set<string>();
    const maybeAdd = (runId: string) => {
      if (!runId) return;
      const run = runById.get(runId);
      if (!run || isActiveRunStatus(run.status)) nextIds.add(runId);
    };
    maybeAdd(selectedRunId);
    selectedWorkflowChildRefs.forEach((ref) => maybeAdd(ref.childRunId));
    maybeAdd(selectedWorkflowApprovalChildRunId);
    return Array.from(nextIds).sort().join('|');
  }, [runById, selectedRunId, selectedWorkflowApprovalChildRunId, selectedWorkflowChildRefs]);
  const selectedRunIsLive = Boolean(selectedRunId && activeRunPollKey.split('|').includes(selectedRunId));
  const selectedRunAvatarUrl = useMemo(() => {
    if (!selectedRun) return '';
    const runnable = runnables.find((item) => item.id === selectedRun.runnable_id);
    const agent = agents.find((item) => item.agent_id === selectedRun.runnable_id);
    return runnable?.avatar_url || agent?.avatar_url || '';
  }, [agents, runnables, selectedRun]);
  const selectedRunRerunTarget = useMemo(() => {
    if (!selectedRun) return null;
    const expectedKind = selectedRun.kind === 'workflow_run' ? 'workflow' : 'agent';
    return runnables.find((item) => item.id === selectedRun.runnable_id && item.kind === expectedKind) || null;
  }, [runnables, selectedRun]);
  const selectedRunRerunDisabledReason = useMemo(() => {
    if (!selectedRun) return '';
    if (isActiveRunStatus(selectedRun.status)) return '当前 Run 还在进行中，请完成、失败或取消后再重跑。';
    if (!selectedRun.user_goal?.trim()) return '原 Run 没有记录任务目标，无法直接重跑。';
    if (!selectedRunRerunTarget) return '找不到原 Run 对应的 Agent 或 Workflow，无法重跑。';
    if (selectedRunRerunTarget.enabled === false) return '原目标已停用，无法重跑。';
    if (selectedRunRerunTarget.kind === 'agent') {
      const agent = agents.find((item) => item.agent_id === selectedRunRerunTarget.id);
      if (!agent) return '找不到 Agent 定义，无法重跑。';
      return agentRunIssueById.get(agent.agent_id) || '';
    }
    const workflow = workflows.find((item) => item.workflow_id === selectedRunRerunTarget.id);
    if (!workflow) return '找不到 Workflow 定义，无法重跑。';
    const validation = validateWorkflowDraft(
      workflowNodes(workflow),
      workflowEdges(workflow),
      agents,
      workflows,
      workflow.workflow_id,
    );
    if (validation.errors.length) return validation.errors[0] || '当前 Workflow 存在校验错误。';
    if (!workflowHasRunnableSteps(workflowNodes(workflow))) return workflowRunnableStepRequiredMessage;
    return workflowAgentRunReadinessIssue(workflowNodes(workflow), agentRunIssueById);
  }, [agentRunIssueById, agents, selectedRun, selectedRunRerunTarget, workflows]);
  const mountedSkillCount = useMemo(
    () => skills.filter((skill) => skill.enabled !== false && selectedAgent?.skill_ids?.includes(skill.skill_id)).length,
    [selectedAgent, skills],
  );
  const enabledSkills = useMemo(() => skills.filter((skill) => skill.enabled !== false), [skills]);
  const installedSkillCount = useMemo(() => skills.filter(isInstalledSkill).length, [skills]);
  const nativeSkillCount = useMemo(() => skills.filter(isNativeSkill).length, [skills]);
  const filteredLibrarySkills = useMemo(
    () => skills.filter((skill) => (
      skillMatchesSourceFilter(skill, skillLibraryFilter)
      && skillMatchesFolderFilter(skill, skillLibraryFolderFilter)
      && skillMatchesQuery(skill, skillLibrarySearch)
    )),
    [skills, skillLibraryFilter, skillLibraryFolderFilter, skillLibrarySearch],
  );
  const filteredLibrarySkillIds = useMemo(
    () => filteredLibrarySkills.map((skill) => skill.skill_id).filter(Boolean),
    [filteredLibrarySkills],
  );
  const selectedSkillIdSet = useMemo(() => new Set(selectedSkillIds), [selectedSkillIds]);
  const selectedLibrarySkills = useMemo(
    () => filteredLibrarySkills.filter((skill) => selectedSkillIdSet.has(skill.skill_id)),
    [filteredLibrarySkills, selectedSkillIdSet],
  );
  const allLibrarySkillsSelected = filteredLibrarySkillIds.length > 0 && selectedLibrarySkills.length === filteredLibrarySkillIds.length;
  const filteredMountSkills = useMemo(
    () => enabledSkills.filter((skill) => (
      skillMatchesSourceFilter(skill, skillMountFilter)
      && skillMatchesFolderFilter(skill, skillMountFolderFilter)
      && skillMatchesQuery(skill, skillMountSearch)
    )),
    [enabledSkills, skillMountFilter, skillMountFolderFilter, skillMountSearch],
  );
  const disabledMountedSkills = useMemo(
    () => skills.filter((skill) => skill.enabled === false && selectedAgent?.skill_ids?.includes(skill.skill_id)),
    [selectedAgent, skills],
  );
  const agentReadinessNotices = useMemo(() => {
    const notices: Array<{ tone: 'danger' | 'warn' | 'info'; text: string }> = [];
    const selectedProfileAvailable = draft.model_profile_id
      ? chatModelProfiles.some((profile) => profile.profile_id === draft.model_profile_id)
      : false;
    if (draft.model_mode === 'profile') {
      if (!draft.model_profile_id) {
        notices.push({ tone: 'danger', text: '尚未选择 Chat Profile；Agent Run 和 Workflow 节点运行前需要一个可用文本模型。' });
      } else if (!selectedProfileAvailable) {
        notices.push({ tone: 'danger', text: '当前 Chat Profile 不可用或已停用；请重新选择可用 Profile。' });
      }
    } else {
      if (!draft.base_url.trim() || !draft.model.trim()) {
        notices.push({ tone: 'danger', text: 'Custom API 需要 Base URL 和 Model，配置不完整时无法运行。' });
      }
      if (!draft.api_key.trim() && !selectedAgent?.model_config?.api_key_configured) {
        notices.push({ tone: 'danger', text: 'Custom API 尚未保存 API Key；请填写后保存，或切回 Chat Profile。' });
      }
    }
    if (disabledMountedSkills.length) {
      notices.push({ tone: 'danger', text: `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用；运行会被拦截。` });
    }
    if (draft.allow_workspace_write) {
      notices.push({
        tone: 'warn',
        text: draft.writable_scopes.trim()
          ? '`workspace.write_patch` 已启用；每次写文件都会先进入审批。'
          : draft.default_workdir.trim()
            ? '`workspace.write_patch` 已启用但 Writable Scopes 为空；写入会被工作区策略拒绝。'
            : '`workspace.write_patch` 已启用；保存后会自动分配独立工作目录，并允许在该目录内写入。',
      });
    }
    if (draft.allow_terminal) {
      notices.push({ tone: 'warn', text: '`terminal.run` 已启用；每次运行命令都会先进入审批。' });
    }
    if (!draft.allow_workspace_read && !draft.allow_workspace_write && !draft.allow_terminal && !draft.allow_artifacts) {
      notices.push({ tone: 'info', text: '当前 Agent 只会调用模型，不会获得工作区、命令或 artifact 工具。' });
    }
    return notices;
  }, [
    chatModelProfiles,
    disabledMountedSkills.length,
    draft.allow_artifacts,
    draft.allow_terminal,
    draft.allow_workspace_read,
    draft.allow_workspace_write,
    draft.api_key,
    draft.base_url,
    draft.model,
    draft.model_mode,
    draft.model_profile_id,
    draft.writable_scopes,
    selectedAgent,
  ]);
  const agentQuickRunDisabledReason = useMemo(() => {
    if (!draft.agent_id) return '请先保存 Agent，再运行。';
    if (selectedAgentReadOnly) return '系统 Agent 只能查看，不能从 Agent Studio 直接运行。';
    if (draft.enabled === false || selectedAgent?.enabled === false) return '当前 Agent 已停用，无法运行。';
    if (draft.model_mode === 'profile') {
      if (!draft.model_profile_id) return '请选择可用 Chat Profile 后再运行。';
      if (!chatModelProfiles.some((profile) => profile.profile_id === draft.model_profile_id)) return '当前 Chat Profile 不可用或已停用。';
    } else {
      if (!draft.base_url.trim() || !draft.model.trim()) return 'Custom API 配置不完整，请填写 Base URL 和 Model。';
      if (!draft.api_key.trim() && !selectedAgent?.model_config?.api_key_configured) return 'Custom API 尚未保存 API Key。';
    }
    if (disabledMountedSkills.length) return `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用，请先启用或卸载后再运行。`;
    if (!agentRunGoal.trim()) return '请输入运行目标。';
    return '';
  }, [
    agentRunGoal,
    chatModelProfiles,
    disabledMountedSkills.length,
    draft.agent_id,
    draft.api_key,
    draft.base_url,
    draft.enabled,
    draft.model,
    draft.model_mode,
    draft.model_profile_id,
    selectedAgent,
    selectedAgentReadOnly,
  ]);
  const agentQuickRunDisabled = busy || Boolean(agentQuickRunDisabledReason);
  const visibleMountSkillIds = useMemo(
    () => filteredMountSkills.map((skill) => skill.skill_id),
    [filteredMountSkills],
  );
  const visibleMountedCount = useMemo(
    () => visibleMountSkillIds.filter((skillId) => selectedAgent?.skill_ids?.includes(skillId)).length,
    [selectedAgent, visibleMountSkillIds],
  );
  const ungroupedSkillStats = useMemo(() => {
    const ungrouped = skills.filter((skill) => !skill.folder_id);
    return {
      total: ungrouped.length,
      installed: ungrouped.filter(isInstalledSkill).length,
      native: ungrouped.filter(isNativeSkill).length,
    };
  }, [skills]);
  const newSkillFolderError = useMemo(
    () => skillFolderNameError(newSkillFolderName, skillFolders),
    [newSkillFolderName, skillFolders],
  );
  const editingSkillFolderError = useMemo(
    () => skillFolderNameError(editingSkillFolderName, skillFolders, editingSkillFolderId),
    [editingSkillFolderId, editingSkillFolderName, skillFolders],
  );

  function upsertRunDetailCache(nextRuns: RunSpec[]) {
    const visibleRuns = acceptedRunUpdates(nextRuns);
    if (!visibleRuns.length) return;
    setRunDetailCache((current) => {
      const nextById = new Map(current.map((run) => [run.run_id, run]));
      visibleRuns.forEach((run) => nextById.set(run.run_id, run));
      return Array.from(nextById.values());
    });
    setRuns((current) => {
      const nextById = new Map(visibleRuns.map((run) => [run.run_id, run]));
      let changed = false;
      const merged = current.map((run) => {
        const next = nextById.get(run.run_id);
        if (!next) return run;
        changed = true;
        return next;
      });
      return changed ? merged : current;
    });
  }

  async function refreshRunGroupsForRuns(nextRuns: RunSpec[]) {
    const groupIds = Array.from(new Set(nextRuns.map((run) => String(run.run_group_id || '')).filter(Boolean)));
    if (!groupIds.length) return;
    const loadedGroups = (await Promise.all(groupIds.map((groupId) => getRunGroup(groupId).catch(() => null))))
      .filter((group): group is RunGroupSpec => Boolean(group));
    if (!loadedGroups.length) return;
    setRunGroups((current) => {
      const nextById = new Map(current.map((group) => [group.run_group_id, group]));
      loadedGroups.forEach((group) => nextById.set(group.run_group_id, group));
      return Array.from(nextById.values());
    });
  }

  function pruneDeletedRunState(deletedRunIds: Set<string>) {
    if (!deletedRunIds.size) return;
    setRuns((current) => current.filter((run) => !deletedRunIds.has(run.run_id)));
    setRunDetailCache((current) => current.filter((run) => !deletedRunIds.has(run.run_id)));
    clearRunEventReplay(deletedRunIds);
    setRunGroups((current) => current.filter((group) => {
      const childRunIds = group.child_run_ids || [];
      return !childRunIds.length || childRunIds.some((runId) => !deletedRunIds.has(runId));
    }));
  }

  function isApprovalFollowupCurrent(selectedAfterAction: string): boolean {
    return selectedRunIdRef.current === selectedAfterAction;
  }

  function approvalFollowupRefreshOptions(selectedAfterAction: string): StudioRefreshOptions {
    return isApprovalFollowupCurrent(selectedAfterAction) ? { selectedRunId: selectedAfterAction } : {};
  }

  async function pollApprovedRunProgress(runId: string, selectedAfterAction: string) {
    const pollRunIds = Array.from(new Set([runId, selectedAfterAction].filter(Boolean)));
    if (!pollRunIds.length) return;
    for (let attempt = 0; attempt < runApprovalPollAttempts; attempt += 1) {
      await new Promise<void>((resolve) => {
        window.setTimeout(resolve, attempt === 0 ? 300 : runApprovalPollIntervalMs);
      });
      const loadedRuns = (await Promise.all(pollRunIds.map((id) => getRun(id).catch(() => null))))
        .filter((run): run is RunSpec => Boolean(run));
      const visibleRuns = acceptedRunUpdates(loadedRuns);
      if (!visibleRuns.length) continue;
      upsertRunDetailCache(visibleRuns);
      await refreshRunGroupsForRuns(visibleRuns);
      const approvedRun = visibleRuns.find((run) => run.run_id === runId) || null;
      const selectedRunUpdate = visibleRuns.find((run) => run.run_id === selectedAfterAction) || null;
      const watchedRun = selectedRunUpdate || approvedRun;
      if (!watchedRun) continue;
      const watchedStatus = normalizeRunStatus(watchedRun.status);
      if (watchedStatus === 'approval_required') {
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setStatus('Run 需要处理下一次审批。');
        }
        await refresh(approvalFollowupRefreshOptions(selectedAfterAction));
        return;
      }
      if (!isActiveRunStatus(watchedRun.status)) {
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setStatus(approvedRunStatusMessage(watchedRun));
        }
        await refresh(approvalFollowupRefreshOptions(selectedAfterAction));
        return;
      }
    }
    await refresh(approvalFollowupRefreshOptions(selectedAfterAction));
  }

  const refresh = useCallback(async (options: StudioRefreshOptions = {}) => {
    const [
      nextAgents,
      nextSkills,
      nextProfiles,
      nextWorkflows,
      ,
      nextRunnables,
      nextRuns,
      nextRunGroups,
      nextSkillSources,
      nextSkillFolders,
      nextMemories,
      nextFutureTasks,
    ] = await Promise.all([
      listAgents(),
      listSkills(),
      listModelProfiles(),
      listWorkflows(),
      loadAgentGroups(),
      listRunnables(),
      listRuns(),
      listRunGroups(),
      listSkillSources(),
      listSkillFolders(),
      listMemories(),
      listFutureTasks(),
    ]);
    applyAgents(nextAgents, options);
    setSkills(nextSkills);
    setSkillSources(nextSkillSources);
    setSkillFolders(nextSkillFolders);
    setModelProfiles(nextProfiles.profiles || []);
    setModelDefaults(nextProfiles.defaults || {});
    applyWorkflows(nextWorkflows, options);
    setRunnables(nextRunnables);
    setRuns(nextRuns);
    setRunGroups(nextRunGroups);
    setMemories(nextMemories);
    setFutureTasks(nextFutureTasks);
    setRunTarget((current) => {
      const desired = options.runTarget !== undefined ? options.runTarget : current;
      if (desired && nextRunnables.some((item) => item.id === desired)) return desired;
      return '';
    });
    setSelectedRunId((current) => {
      const desired = options.selectedRunId !== undefined ? options.selectedRunId : current;
      if (desired) return desired;
      return '';
    });
  }, [applyAgents, applyWorkflows, loadAgentGroups]);

  useEffect(() => {
    setLoading(true);
    refresh()
      .then(() => setError(''))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '读取 Agent Studio 失败'))
      .finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    selectedRunIdRef.current = selectedRunId;
  }, [selectedRunId]);

  useEffect(() => {
    const nextTab = routeRunId || routeRunTarget ? 'runs' : routeTab;
    setTab((current) => current === nextTab ? current : nextTab);
    if (routeRunId) {
      setSelectedRunId((current) => current === routeRunId ? current : routeRunId);
    } else if (routeRunTarget) {
      setSelectedRunId('');
    } else if (routeTab === 'runs') {
      setSelectedRunId('');
    }
    if (routeRunTarget) {
      setRunTarget((current) => current === routeRunTarget ? current : routeRunTarget);
      setRunGoal((current) => current === routeRunGoal ? current : routeRunGoal);
    } else if (routeRunGoal) {
      setRunGoal((current) => current === routeRunGoal ? current : routeRunGoal);
    }
  }, [routeRunGoal, routeRunId, routeRunTarget, routeTab]);

  useEffect(() => {
    setSelectedSkillIds((current) => pruneSelectedIds(current, filteredLibrarySkillIds));
  }, [filteredLibrarySkillIds]);

  useEffect(() => {
    setSelectedRunIds((current) => pruneSelectedIds(current, filteredRunIds));
  }, [filteredRunIds]);

  useEffect(() => {
    if (selectedAgent) setDraft(agentToDraft(selectedAgent));
  }, [selectedAgent]);

  useEffect(() => {
    if (tab !== 'agents' || loading || busyAction || agents.length) return;
    if (!selectedAgentId && !draft.agent_id) return;
    let disposed = false;
    refresh()
      .then(() => {
        if (!disposed) setError('');
      })
      .catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : '刷新 Agent 列表失败');
      });
    return () => {
      disposed = true;
    };
  }, [agents.length, busyAction, draft.agent_id, loading, refresh, selectedAgentId, tab]);

  useEffect(() => {
    if (!selectedRunId || selectedRun) return;
    let disposed = false;
    getRun(selectedRunId)
      .then((run) => {
        if (!disposed) upsertRunDetailCache([run]);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [selectedRun, selectedRunId]);

  useEffect(() => {
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return;
    const runGroupId = selectedRun.run_group_id || '';
    if (!runGroupId) return;
    if (runGroups.some((group) => group.run_group_id === runGroupId)) return;
    let disposed = false;
    getRunGroup(runGroupId)
      .then((group) => {
        if (disposed) return;
        setRunGroups((current) => {
          const nextById = new Map(current.map((item) => [item.run_group_id, item]));
          nextById.set(group.run_group_id, group);
          return Array.from(nextById.values());
        });
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [runGroups, selectedRun]);

  useEffect(() => {
    if (!selectedWorkflowParentRunId || runById.has(selectedWorkflowParentRunId)) return;
    let disposed = false;
    getRun(selectedWorkflowParentRunId)
      .then((run) => {
        if (!disposed) upsertRunDetailCache([run]);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [runById, selectedWorkflowParentRunId]);

  useEffect(() => {
    const childRunIds = [
      ...selectedWorkflowChildRefs.map((ref) => ref.childRunId),
      selectedWorkflowApprovalChildRunId,
    ].filter(Boolean);
    const uniqueChildRunIds = Array.from(new Set(childRunIds));
    if (!uniqueChildRunIds.length) return;
    let disposed = false;
    Promise.all(uniqueChildRunIds.map((runId) => getRun(runId).catch(() => null)))
      .then((childRuns) => {
        if (disposed) return;
        const loaded = childRuns.filter((run): run is RunSpec => Boolean(run));
        if (!loaded.length) return;
        upsertRunDetailCache(loaded);
      });
    return () => {
      disposed = true;
    };
  }, [selectedWorkflowApprovalChildRunId, selectedWorkflowChildRefs]);

  useEffect(() => {
    const pollRunIds = activeRunPollKey.split('|').filter(Boolean);
    if (!pollRunIds.length) return;
    let disposed = false;
    let inFlight = false;
    const pollRuns = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const loadedRuns = (await Promise.all(pollRunIds.map((runId) => getRun(runId).catch(() => null))))
          .filter((run): run is RunSpec => Boolean(run));
        if (disposed || !loadedRuns.length) return;
        upsertRunDetailCache(loadedRuns);
        const groupIds = Array.from(new Set(loadedRuns.map((run) => String(run.run_group_id || '')).filter(Boolean)));
        const loadedGroups = (await Promise.all(groupIds.map((groupId) => getRunGroup(groupId).catch(() => null))))
          .filter((group): group is RunGroupSpec => Boolean(group));
        if (disposed || !loadedGroups.length) return;
        setRunGroups((current) => {
          const nextById = new Map(current.map((group) => [group.run_group_id, group]));
          loadedGroups.forEach((group) => nextById.set(group.run_group_id, group));
          return Array.from(nextById.values());
        });
      } finally {
        inFlight = false;
      }
    };
    void pollRuns();
    const timer = window.setInterval(() => {
      void pollRuns();
    }, 2500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeRunPollKey]);

  useEffect(() => {
    setArtifactPreview(null);
  }, [selectedRunId]);

  useEffect(() => {
    setNodes(workflowNodes(selectedWorkflow));
    setEdges(workflowEdges(selectedWorkflow));
    setWorkflowName(selectedWorkflow?.name || 'New Workflow');
    setWorkflowDescription(selectedWorkflow?.description || '');
    setWorkflowEnabled(selectedWorkflow?.enabled !== false);
  }, [selectedWorkflow, setEdges, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((current) => addEdge({ ...connection, id: `edge-${connection.source}-${connection.target}` }, current));
    },
    [setEdges],
  );

  function toggleSkillSelected(skillId: string) {
    setSelectedSkillIds((current) => toggleSelectedId(current, skillId));
  }

  function toggleRunSelected(runId: string) {
    setSelectedRunIds((current) => toggleSelectedId(current, runId));
  }

  function finishSkillManagement() {
    setSkillManagementMode(false);
    setSelectedSkillIds([]);
  }

  function finishRunHistoryManagement() {
    setRunHistoryManagementMode(false);
    setSelectedRunIds([]);
  }

  function startNewAgent() {
    setSelectedAgentId('');
    setDraft({ ...emptyAgentDraft });
    setStatus('正在编辑新的 Agent 草稿');
    setError('');
  }

  function selectAgent(agentId: string) {
    setSelectedAgentId(agentId);
    setStatus('');
    setError('');
  }

  function startNewWorkflow() {
    setSelectedWorkflowId('');
    setNodes(starterNodes);
    setEdges([]);
    setWorkflowName('New Workflow');
    setWorkflowDescription('');
    setWorkflowEnabled(true);
    setStatus('正在编辑新的 Workflow 草稿');
    setError('');
  }

  function loadPhase4WorkflowTemplate() {
    const nextNodes = buildPhase4WorkflowNodes(agents);
    const agentNodeCount = nextNodes.filter((node) => node.data?.kind === 'agent').length;
    if (!agentNodeCount) {
      setError('当前没有可用 Agent，无法生成全线测试模板。');
      return;
    }
    setSelectedWorkflowId('');
    setWorkflowName('Phase 4 Agent 全线流通测试');
    setWorkflowDescription('依次调用 Orchestrator、Research、Design、Coding、Review、Office，并写出最终 Artifact。');
    setWorkflowEnabled(true);
    setNodes(nextNodes);
    setEdges(linearEdgesForNodes(nextNodes));
    setStatus(`已生成全线测试模板：${agentNodeCount} 个启用 Agent 节点`);
    setError('');
  }

  function selectWorkflow(workflowId: string) {
    setSelectedWorkflowId(workflowId);
    setStatus('');
    setError('');
  }

  function openWorkflowDesign(workflowId: string) {
    const workflow = workflows.find((item) => item.workflow_id === workflowId);
    if (!workflow) {
      setError('找不到对应的 Workflow 定义，可能已被删除。');
      return;
    }
    setSelectedWorkflowId(workflow.workflow_id);
    setTab('workflows');
    setStatus(`已打开 Workflow Studio：${workflow.name || workflow.workflow_id}`);
    setError('');
    navigateTo('agents', { tab: 'workflows' }, ['run', 'target', 'goal']);
  }

  function activateTab(nextTab: StudioTab) {
    setTab(nextTab);
    setStatus('');
    setError('');
    navigateTo('agents', nextTab === 'agents' ? {} : { tab: nextTab }, ['run', 'tab', 'target', 'goal']);
    if (nextTab === 'agents') {
      void refresh().catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '刷新 Agent 列表失败');
      });
    }
  }

  function isTopTabActive(item: StudioTab): boolean {
    if (item === 'skills') return isSkillLibraryTab;
    return tab === item;
  }

  async function runAction(action: () => Promise<StudioRefreshOptions | void>, label: string) {
    setBusyAction(label);
    setStatus(`${label}...`);
    setError('');
    try {
      const refreshOptions = await action();
      if (!refreshOptions?.skipRefresh) {
        await refresh(refreshOptions || {});
      }
      setStatus(refreshOptions?.statusMessage || `${label} 完成`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} 失败`);
    } finally {
      setBusyAction('');
    }
  }

  async function pickSkillSources() {
    setError('');
    try {
      const selected = await chooseSkillSources();
      if (selected.length) await runAction(() => importSkillSourceList(selected), '导入 Skills');
    } catch (err) {
      setError(err instanceof Error ? err.message : '选择 Skill 文件失败');
    }
  }

  async function pickAgentAvatar() {
    setBusyAction('选择 Agent 头像');
    setError('');
    try {
      const selection = await chooseAvatarImage();
      const avatar = typeof selection === 'string' ? selection : selection?.data_url || selection?.path || '';
      if (avatar) {
        setDraft((current) => ({ ...current, avatar_url: avatar }));
        setStatus('已选择 Agent 头像');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '选择 Agent 头像失败');
    } finally {
      setBusyAction('');
    }
  }

  function dropSkillSources(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    const filePaths = Array.from(event.dataTransfer.files)
      .map((file) => (file as File & { path?: string }).path || file.name)
      .filter(Boolean);
    if (filePaths.length) {
      void runAction(() => importSkillSourceList(filePaths), '导入 Skills');
    }
  }

  async function importSkillSourceList(rawSources: string[]): Promise<StudioRefreshOptions | void> {
    const sources = normalizeSkillSources(rawSources);
    if (!sources.length) throw new Error('请先选择或拖入 Skill 目录/ZIP');
    const existingPaths = new Set(skills.flatMap((skill) => [skill.local_path, skill.source_path]).filter(Boolean).map(String));
    const results: SkillImportResult[] = [];
    for (const source of sources) {
      if (existingPaths.has(source) || existingPaths.has(localSourceAlias(source))) {
        results.push({ source, status: 'skipped', message: '已存在，跳过' });
        continue;
      }
      try {
        const imported = await importSkill(source, skillTargetFolderId);
        results.push({ source, status: 'success', message: `已导入 ${imported.name}` });
      } catch (err) {
        results.push({ source, status: 'failed', message: err instanceof Error ? err.message : '导入失败' });
      }
    }
    setSkillImportResults(results);
  }

  async function syncNativeSkillLibrary(): Promise<StudioRefreshOptions | void> {
    const result = await syncNativeSkills();
    setSkillImportResults(syncResultsToImportResults(result.results || []));
    if (result.roots) setSkillSources(result.roots);
  }

  async function installSkillFromCommand(): Promise<StudioRefreshOptions | void> {
    const command = skillInstallCommand.trim();
    if (!command) throw new Error('请输入 Skill 来源或安装命令');
    const result = await installSkillCommand(command, skillTargetFolderId);
    if (result.sync?.results) {
      setSkillImportResults(syncResultsToImportResults(result.sync.results));
    }
    if (!result.ok) {
      throw new Error(result.stderr || result.stdout || `安装命令退出：${result.returncode ?? 'unknown'}`);
    }
  }

  async function createSkillFolderFromDraft(): Promise<StudioRefreshOptions | void> {
    const name = newSkillFolderName.trim();
    if (!name) throw new Error('请输入 Skill 文件夹名称');
    const validation = skillFolderNameError(name, skillFolders);
    if (validation) throw new Error(validation);
    const folder = await createSkillFolder({ name });
    setNewSkillFolderName('');
    setSkillTargetFolderId(folder.folder_id);
    setSkillLibraryFolderFilter(folder.folder_id);
    setSkillMountFolderFilter(folder.folder_id);
  }

  function startEditingSkillFolder(folder: SkillFolderSpec) {
    setEditingSkillFolderId(folder.folder_id);
    setEditingSkillFolderName(folder.name);
    setStatus('');
    setError('');
  }

  function cancelEditingSkillFolder() {
    setEditingSkillFolderId('');
    setEditingSkillFolderName('');
  }

  async function updateSkillFolderFromDraft(folderId: string): Promise<StudioRefreshOptions | void> {
    const name = editingSkillFolderName.trim();
    if (!name) throw new Error('请输入 Skill 文件夹名称');
    const validation = skillFolderNameError(name, skillFolders, folderId);
    if (validation) throw new Error(validation);
    await updateSkillFolder(folderId, { name });
    cancelEditingSkillFolder();
  }

  async function deleteSkillFolderById(folderId: string, deleteSkills = false): Promise<StudioRefreshOptions | void> {
    await deleteSkillFolder(folderId, { deleteSkills });
    if (skillTargetFolderId === folderId) setSkillTargetFolderId('');
    if (skillLibraryFolderFilter === folderId) setSkillLibraryFolderFilter('all');
    if (skillMountFolderFilter === folderId) setSkillMountFolderFilter('all');
    if (editingSkillFolderId === folderId) cancelEditingSkillFolder();
    setSkillFolderDeleteMode(folderId, null);
  }

  function setSkillFolderDeleteMode(folderId: string, mode: 'folder' | 'skills' | null) {
    setSkillFolderDeleteModes((current) => {
      const next = { ...current };
      if (mode) next[folderId] = mode;
      else delete next[folderId];
      return next;
    });
  }

  function showConfirmDialog(nextConfirm: ConfirmDialogState) {
    setConfirmDialog(nextConfirm);
  }

  function closeConfirmDialog() {
    setConfirmDialog(null);
  }

  function confirmCurrentDialog() {
    const action = confirmDialog?.onConfirm;
    setConfirmDialog(null);
    if (action) action();
  }

  function requestDeleteAgent() {
    if (!draft.agent_id) return;
    if (!selectedAgentDeletable) {
      setStatus('系统 Agent 只能查看，不能删除。');
      return;
    }
    const agentId = draft.agent_id;
    const agentName = draft.name || selectedAgent?.name || 'Agent';
    showConfirmDialog({
      title: `删除「${agentName}」？`,
      description: '这个 Agent 的定义会从 Agent Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: '删除 Agent',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteAgent(agentId);
        setSelectedAgentIds((current) => current.filter((id) => id !== agentId));
        setSelectedAgentId('');
        setDraft({ ...emptyAgentDraft });
        return { selectedAgentId: '' };
      }, '删除 Agent'),
    });
  }

  function requestDeleteSelectedAgents() {
    const targets = selectedDeletableAgents.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((agent) => agent.agent_id));
    const deletingCurrent = Boolean(selectedAgentId && targetIds.has(selectedAgentId));
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Agent？`,
      description: '这些 Agent 的定义会从 Agent Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: `删除 ${targets.length} 个 Agent`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const agent of targets) {
          await deleteAgent(agent.agent_id);
        }
        setSelectedAgentIds((current) => current.filter((id) => !targetIds.has(id)));
        if (deletingCurrent) {
          setSelectedAgentId('');
          setDraft({ ...emptyAgentDraft });
          return { selectedAgentId: '' };
        }
        return undefined;
      }, '批量删除 Agent'),
    });
  }

  function requestDeleteSkill(skill: SkillSpec) {
    showConfirmDialog({
      title: `删除 Skill「${skill.name}」？`,
      description: isNativeSkill(skill)
        ? '这只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除 Native Skill Library 原始文件。'
        : 'Installed Skill 管理区里的本地 Skill 副本会被删除，已挂载它的 Agent 会失去这个 Skill。',
      confirmLabel: '删除 Skill',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteSkill(skill.skill_id);
        setSelectedSkillIds((current) => current.filter((id) => id !== skill.skill_id));
      }, '删除 Skill'),
    });
  }

  function requestDeleteSelectedSkills() {
    const targets = selectedLibrarySkills.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((skill) => skill.skill_id));
    const hasNativeSkills = targets.some(isNativeSkill);
    const hasInstalledSkills = targets.some(isInstalledSkill);
    const description = hasNativeSkills && hasInstalledSkills
      ? 'Installed Skill 管理区里的本地 Skill 副本会被删除；Native Skill 只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除原始文件。'
      : hasNativeSkills
        ? '这些 Native Skill 只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除原始文件。'
        : 'Installed Skill 管理区里的本地 Skill 副本会被删除，已挂载它们的 Agent 会失去这些 Skill。';
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Skill？`,
      description,
      confirmLabel: `删除 ${targets.length} 个 Skill`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const skill of targets) {
          await deleteSkill(skill.skill_id);
        }
        setSelectedSkillIds((current) => current.filter((id) => !targetIds.has(id)));
      }, '批量删除 Skill'),
    });
  }

  function requestDeleteWorkflow() {
    if (!selectedWorkflow) return;
    const workflowId = selectedWorkflow.workflow_id;
    const workflowName = selectedWorkflow.name || 'Workflow';
    showConfirmDialog({
      title: `删除「${workflowName}」？`,
      description: '这个 Workflow 定义会从 Workflow Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: '删除 Workflow',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteWorkflow(workflowId);
        setSelectedWorkflowIds((current) => current.filter((id) => id !== workflowId));
        startNewWorkflow();
        return { selectedWorkflowId: '' };
      }, '删除 Workflow'),
    });
  }

  function requestDeleteSelectedWorkflows() {
    const targets = selectedWorkflows.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((workflow) => workflow.workflow_id));
    const deletingCurrent = Boolean(selectedWorkflowId && targetIds.has(selectedWorkflowId));
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Workflow？`,
      description: '这些 Workflow 定义会从 Workflow Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: `删除 ${targets.length} 个 Workflow`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const workflow of targets) {
          await deleteWorkflow(workflow.workflow_id);
        }
        setSelectedWorkflowIds((current) => current.filter((id) => !targetIds.has(id)));
        if (deletingCurrent) {
          startNewWorkflow();
          return { selectedWorkflowId: '' };
        }
        return undefined;
      }, '批量删除 Workflow'),
    });
  }

  function requestDeleteSelectedRuns() {
    const targets = selectedHistoryRuns.slice();
    if (!targets.length || selectedHistoryActiveRunCount) return;
    showConfirmDialog({
      title: `删除 ${targets.length} 条 Run History？`,
      description: '这些 Run 记录会从 Runs History 移除，对应 artifacts 也会删除；Workflow Run 会连带删除同一次 Workflow 的子 Agent Run。',
      confirmLabel: `删除 ${targets.length} 条记录`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        const deletedRunIds = new Set<string>();
        for (const run of targets) {
          const result = await deleteRun(run.run_id);
          const resultIds = Array.isArray(result.deleted_run_ids) ? result.deleted_run_ids : [run.run_id];
          resultIds.forEach((id) => {
            if (id) deletedRunIds.add(id);
          });
        }
        pruneDeletedRunState(deletedRunIds);
        setSelectedRunIds((current) => current.filter((id) => !deletedRunIds.has(id)));
        if (selectedRunId && deletedRunIds.has(selectedRunId)) {
          setSelectedRunId('');
          setArtifactPreview(null);
          navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
          return { selectedRunId: '' };
        }
        return undefined;
      }, '批量删除 Run History'),
    });
  }

  function requestDeleteMemory(memory: MemorySpec) {
    const memoryLabel = memory.content.trim() || memory.memory_id;
    showConfirmDialog({
      title: `删除 Memory「${memoryLabel.slice(0, 32)}」？`,
      description: '这条长期记忆会从 Agent Runtime 的主动回忆范围中移除；历史 Run 不会被删除。',
      confirmLabel: '删除 Memory',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteMemory(memory.memory_id, 'studio_user_delete');
        return { statusMessage: 'Memory 已删除。' };
      }, '删除 Memory'),
    });
  }

  function requestCancelFutureTask(futureTask: FutureTaskSpec) {
    const taskLabel = futureTask.title.trim() || futureTask.future_task_id;
    showConfirmDialog({
      title: `取消 FutureTask「${taskLabel.slice(0, 40)}」？`,
      description: '这个 FutureTask 不会再自动触发；已经生成的 Run 不会被删除。',
      confirmLabel: '取消 FutureTask',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await cancelFutureTask(futureTask.future_task_id, 'studio_user_cancel');
        return { statusMessage: 'FutureTask 已取消。' };
      }, '取消 FutureTask'),
    });
  }

  async function triggerDueFutureTaskRuns(): Promise<StudioRefreshOptions> {
    const result = await triggerDueFutureTasks();
    const triggered = result.triggered || [];
    const firstRunId = triggered.map((item) => item.run?.run_id || '').find(Boolean) || '';
    const failedCount = triggered.filter((item) => item.error || item.ok === false).length;
    const statusMessage = triggered.length
      ? `已触发 ${triggered.length} 个 FutureTask${failedCount ? `，${failedCount} 个失败` : ''}。`
      : '没有到期 FutureTask。';
    if (firstRunId) {
      openRunDetail(firstRunId, { revealInHistory: true });
      return { selectedRunId: firstRunId, statusMessage };
    }
    return { statusMessage };
  }

  function requestDeleteSkillFolder(folder: SkillFolderSpec, deleteSkills: boolean) {
    const count = folder.skill_count || skills.filter((skill) => skill.folder_id === folder.folder_id).length;
    if (deleteSkills) {
      showConfirmDialog({
        title: `删除「${folder.name}」和其中 ${count} 个 Skill？`,
        description: 'Installed Skill 本地副本会被删除；Native Skill 只会删除 Oha-Yachiyo 的登记，不会删除原始文件。',
        confirmLabel: '连带删除',
        variant: 'danger',
        onConfirm: () => void runAction(
          async () => deleteSkillFolderById(folder.folder_id, true),
          '删除 Skill 文件夹和 Skills',
        ),
      });
      return;
    }
    showConfirmDialog({
      title: `删除文件夹「${folder.name}」？`,
      description: `${count} 个 Skill 会回到“无需分组”。`,
      confirmLabel: '删除文件夹',
      variant: 'danger',
      onConfirm: () => void runAction(
        async () => deleteSkillFolderById(folder.folder_id, false),
        '删除 Skill 文件夹',
      ),
    });
  }

  function openSkillLibraryFolder(folder: SkillFolderSpec) {
    setSkillTargetFolderId(folder.folder_id);
    setSkillLibraryFolderFilter(folder.folder_id);
    setTab('skills');
    navigateTo('agents', { tab: 'skills' }, ['run', 'tab']);
  }

  async function mountVisibleSkills(): Promise<StudioRefreshOptions | void> {
    if (!draft.agent_id || !selectedAgent) return;
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
      return;
    }
    const nextSkillIds = Array.from(new Set([...(selectedAgent.skill_ids || []), ...visibleMountSkillIds]));
    await updateAgent(draft.agent_id, { skill_ids: nextSkillIds });
  }

  async function unmountVisibleSkills(): Promise<StudioRefreshOptions | void> {
    if (!draft.agent_id || !selectedAgent) return;
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
      return;
    }
    const visible = new Set(visibleMountSkillIds);
    const nextSkillIds = (selectedAgent.skill_ids || []).filter((skillId) => !visible.has(skillId));
    await updateAgent(draft.agent_id, { skill_ids: nextSkillIds });
  }

  function toggleAgentSkillMount(skill: SkillSpec, mounted: boolean) {
    void runAction(async () => {
      if (!draft.agent_id) return;
      if (selectedAgentReadOnly) {
        setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
        return;
      }
      if (mounted) await detachSkill(draft.agent_id, skill.skill_id);
      else await attachSkill(draft.agent_id, skill.skill_id);
    }, mounted ? '移除 Skill' : '挂载 Skill');
  }

  async function saveAgent(): Promise<StudioRefreshOptions> {
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改。');
      return { selectedAgentId };
    }
    const request: Partial<AgentSpec> = {
      name: draft.name,
      nickname: draft.nickname,
      description: draft.description,
      avatar_url: draft.avatar_url,
      category: draft.category,
      instructions: draft.instructions,
      persona_prompt: draft.persona_prompt,
      model_mode: draft.model_mode,
      model_profile_id: draft.model_mode === 'profile' ? draft.model_profile_id : '',
      vision_model_profile_id: draft.vision_model_profile_id,
      tool_policy: draftToolPolicy(draft),
      workspace_policy: {
        default_workdir: draft.default_workdir,
        readable_scopes: textToScopes(draft.readable_scopes),
        writable_scopes: textToScopes(draft.writable_scopes),
      },
      output_contract: draft.output_contract,
      enabled: draft.enabled,
    };
    if (draft.model_mode === 'custom_api') {
      request.model_config = {
        provider: 'openai_compatible',
        base_url: draft.base_url,
        model: draft.model,
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
      };
    }
    const saved = draft.agent_id ? await updateAgent(draft.agent_id, request) : await createAgent(request);
    setSelectedAgentId(saved.agent_id);
    setDraft(agentToDraft(saved));
    return { selectedAgentId: saved.agent_id };
  }

  async function saveAgentGroup(): Promise<StudioRefreshOptions> {
    const { statusMessage } = await saveAgentGroupDraft();
    return { statusMessage };
  }

  function workflowDraftRequest(): Partial<WorkflowSpec> {
    return {
      name: workflowName.trim(),
      description: workflowDescription.trim(),
      nodes: workflowRequestNodes(nodes),
      edges: workflowRequestEdges(edges),
      enabled: workflowEnabled,
    };
  }

  async function saveWorkflowDraft(): Promise<WorkflowSpec> {
    if (workflowErrors.length) {
      throw new Error(workflowErrors[0]);
    }
    const request = workflowDraftRequest();
    const saved = selectedWorkflow ? await updateWorkflow(selectedWorkflow.workflow_id, request) : await createWorkflow(request);
    setSelectedWorkflowId(saved.workflow_id);
    return saved;
  }

  async function saveWorkflow(): Promise<StudioRefreshOptions> {
    const saved = await saveWorkflowDraft();
    return { selectedWorkflowId: saved.workflow_id };
  }

  function openRunDetail(runId: string, options: { revealInHistory?: boolean } = {}) {
    if (options.revealInHistory) {
      setRunKindFilter('all');
      setRunStatusFilter('all');
      setRunSearchQuery('');
    }
    setSelectedRunId(runId);
    setTab('runs');
    const run = runs.find((item) => item.run_id === runId);
    if (run) {
      const groupKey = runHistoryGroupKey(run);
      setCollapsedRunHistoryGroups((current) => {
        if (!current.has(groupKey)) return current;
        const next = new Set(current);
        next.delete(groupKey);
        return next;
      });
    }
    navigateTo('agents', { run: runId }, ['tab', 'target', 'goal']);
  }

  function openAgentGroupRunTimeline(groupRun: GroupRunSnapshot | null) {
    const runId = groupRunTimelineRunId(groupRun);
    if (!runId) {
      setError('这个 GroupRun 暂时没有可打开的子 Run。');
      return;
    }
    openRunDetail(runId, { revealInHistory: true });
  }

  function toggleRunHistoryGroup(groupKey: string) {
    setCollapsedRunHistoryGroups((current) => {
      const next = new Set(current);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  }

  function selectRunKindFilter(nextFilter: RunKindFilter) {
    setRunKindFilter(nextFilter);
    if (selectedRun && runMatchesFilter(selectedRun, nextFilter)) return;
    if (selectedRunId) {
      setSelectedRunId('');
      setTab('runs');
      navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
    }
  }

  function selectRunStatusFilter(nextFilter: RunStatusFilter) {
    setRunStatusFilter(nextFilter);
    if (selectedRun && runMatchesStatusFilter(selectedRun, nextFilter)) return;
    if (selectedRunId) {
      setSelectedRunId('');
      setTab('runs');
      navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
    }
  }

  async function runCurrentAgent(): Promise<StudioRefreshOptions> {
    if (agentQuickRunDisabledReason) throw new Error(agentQuickRunDisabledReason);
    const agentId = draft.agent_id || '';
    const goal = agentRunGoal.trim();
    const run = await createAgentRun(agentId, goal);
    setAgentRunGoal('');
    setRunTarget(agentId);
    openRunDetail(run.run_id, { revealInHistory: true });
    return { selectedAgentId: agentId, runTarget: agentId, selectedRunId: run.run_id };
  }

  async function runCurrentWorkflow(): Promise<StudioRefreshOptions> {
    if (workflowRunDisabledReason) throw new Error(workflowRunDisabledReason);
    const goal = workflowRunGoal.trim();
    const saved = await saveWorkflowDraft();
    const run = await createWorkflowRun(saved.workflow_id, goal);
    setWorkflowRunGoal('');
    setRunTarget(saved.workflow_id);
    openRunDetail(run.run_id, { revealInHistory: true });
    return { selectedWorkflowId: saved.workflow_id, runTarget: saved.workflow_id, selectedRunId: run.run_id };
  }

  async function runCurrentAgentGroup(): Promise<StudioRefreshOptions> {
    const { runId, statusMessage } = await runAgentGroup();
    if (runId) {
      setRunTarget(selectedAgentGroupId.trim());
      openRunDetail(runId, { revealInHistory: true });
    }
    return {
      selectedRunId: runId || undefined,
      statusMessage,
    };
  }

  function prepareSelectedRunRerun() {
    if (!selectedRun) return;
    if (!selectedRunRerunTarget) {
      setError('找不到原 Run 对应的 Agent 或 Workflow，无法准备重跑。');
      return;
    }
    setRunTarget(selectedRunRerunTarget.id);
    setRunGoal(selectedRun.user_goal || '');
    setStatus(`已把「${selectedRunRerunTarget.name || selectedRun.runnable_name || selectedRun.runnable_id}」和原任务填回 Run 面板。`);
    setError('');
  }

  async function rerunSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择要重跑的 Run');
    if (selectedRunRerunDisabledReason) throw new Error(selectedRunRerunDisabledReason);
    if (!selectedRunRerunTarget) throw new Error('找不到原 Run 对应的 Agent 或 Workflow，无法重跑。');
    const run = await rerunRun(selectedRun.run_id);
    upsertRunDetailCache([run]);
    await refreshRunGroupsForRuns([run]);
    openRunDetail(run.run_id, { revealInHistory: true });
    if (selectedRunRerunTarget.kind === 'agent') {
      return {
        selectedAgentId: selectedRunRerunTarget.id,
        selectedRunId: run.run_id,
        runTarget: selectedRunRerunTarget.id,
        statusMessage: '已按原任务重新运行 Agent。',
      };
    }
    return {
      selectedWorkflowId: selectedRunRerunTarget.id,
      selectedRunId: run.run_id,
      runTarget: selectedRunRerunTarget.id,
      statusMessage: '已按原任务重新运行 Workflow。',
    };
  }

  function addFlowNode(kind: 'agent' | 'approval' | 'artifact' | 'workflow' | 'loop', agentId = '') {
    const agent = agentId
      ? agents.find((candidate) => candidate.agent_id === agentId)
      : undefined;
    const nodeSeed = kind === 'agent'
      ? `${kind}-${agent?.agent_id || Date.now().toString(36)}`
      : `${kind}-${Date.now().toString(36)}`;
    const id = uniqueWorkflowNodeId(nodeSeed, nodes);
    const sourceId = terminalNodeId(nodes, edges);
    const nextNode: Node = {
      id,
      type: kind === 'artifact' ? 'output' : 'default',
      position: { x: 120 + nodes.length * 180, y: 140 },
      data: {
        label: kind === 'agent'
          ? agent?.name || '选择 Agent'
          : kind === 'approval'
            ? '人工审批'
            : kind === 'workflow'
              ? '子 Workflow'
              : kind === 'loop'
                ? 'Loop'
              : 'Artifact',
        kind,
        ...(kind === 'agent' && agent ? { agent_id: agent.agent_id } : {}),
      },
    };
    setNodes((current) => [...current, nextNode]);
    if (sourceId) {
      setEdges((current) => [
        ...current,
        {
          id: `edge-${sourceId}-${id}`,
          source: sourceId,
          target: id,
        },
      ]);
    }
  }

  function removeFlowNode(nodeId: string) {
    if (nodeId === 'start') return;
    const incoming = edges.find((edge) => edge.target === nodeId);
    const outgoing = edges.find((edge) => edge.source === nodeId);
    setNodes((current) => current.filter((node) => node.id !== nodeId));
    setEdges((current) => {
      const nextEdges = current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
      if (incoming?.source && outgoing?.target && incoming.source !== outgoing.target) {
        nextEdges.push({
          id: `edge-${incoming.source}-${outgoing.target}`,
          source: incoming.source,
          target: outgoing.target,
        });
      }
      return nextEdges;
    });
  }

  async function openArtifact(run: RunSpec | string, path: string) {
    const runId = typeof run === 'string' ? run : run.run_id;
    setStatus('读取 artifact...');
    setError('');
    try {
      const payload = await getRunArtifact(runId, path);
      setArtifactPreview({
        path: payload.path || path,
        content: payload.content || '',
        truncated: payload.truncated,
      });
      setStatus('Artifact 已读取');
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 artifact 失败');
    }
  }

  async function loadMoreSelectedRunEvents() {
    const loadedCount = await loadMoreRunReplayEvents();
    setStatus(loadedCount ? `已加载 ${loadedCount} 条 RunEvent replay` : '没有更多 RunEvent replay');
  }

  async function approveRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions> {
    if (!runId) throw new Error('请选择待审批 Run');
    const selectedAfterAction = nextSelectedRunId || runId;
    const currentRun = runById.get(runId) || null;
    const selectedAfterRun = selectedAfterAction !== runId ? runById.get(selectedAfterAction) || null : null;
    const optimisticRuns = [
      currentRun ? makeRunContinuingAfterApproval(currentRun, '已批准，Run 正在继续执行。') : null,
      selectedAfterRun && isActiveRunStatus(selectedAfterRun.status)
        ? makeRunContinuingAfterApproval(selectedAfterRun, '已批准子 Agent，Workflow 正在继续执行。')
        : null,
    ].filter((run): run is RunSpec => Boolean(run));
    upsertRunDetailCache(optimisticRuns);
    rememberApprovedRun(currentRun);
    rememberApprovedRun(selectedAfterRun);
    setSelectedRunId(selectedAfterAction);
    const approvalRequest = approveRunApproval(runId);
    void pollApprovedRunProgress(runId, selectedAfterAction).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : '刷新审批后的 Run 进度失败');
    });
    void approvalRequest
      .then(async (run) => {
        const updatedRuns = [run];
        if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
          try {
            updatedRuns.push(await getRun(nextSelectedRunId));
          } catch {
            // The background polling path will retry; approval already succeeded.
          }
        }
        upsertRunDetailCache(updatedRuns);
        await refreshRunGroupsForRuns(updatedRuns);
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setSelectedRunId(selectedAfterAction);
          setStatus(approvedRunStatusMessage(run));
        }
      })
      .catch((err: unknown) => {
        if (isApprovalFollowupCurrent(selectedAfterAction)) {
          setError(err instanceof Error ? err.message : '批准 Run 审批失败');
        }
        void refresh(approvalFollowupRefreshOptions(selectedAfterAction)).catch(() => undefined);
      });
    return {
      selectedRunId: selectedAfterAction,
      statusMessage: '已批准，Run 正在继续执行。',
      skipRefresh: true,
    };
  }

  async function rejectRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions> {
    if (!runId) throw new Error('请选择待审批 Run');
    const run = await rejectRunApproval(runId);
    const selectedAfterAction = nextSelectedRunId || run.run_id;
    const updatedRuns = [run];
    if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
      try {
        updatedRuns.push(await getRun(nextSelectedRunId));
      } catch {
        // The normal refresh/polling path will retry; rejection already succeeded.
      }
    }
    upsertRunDetailCache(updatedRuns);
    setSelectedRunId(selectedAfterAction);
    return { selectedRunId: selectedAfterAction, statusMessage: '已拒绝，Run 已终止。' };
  }

  async function approveSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择待审批 Run');
    return approveRunById(selectedRun.run_id);
  }

  async function rejectSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择待审批 Run');
    return rejectRunById(selectedRun.run_id);
  }

  async function cancelRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions> {
    if (!runId) throw new Error('请选择要取消的 Run');
    const currentRun = runById.get(runId) || null;
    if (currentRun && !isActiveRunStatus(currentRun.status)) throw new Error('只能取消进行中或待审批的 Run');
    const run = await cancelRun(runId);
    const selectedAfterAction = nextSelectedRunId || run.run_id;
    const updatedRuns = [run];
    if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
      try {
        updatedRuns.push(await getRun(nextSelectedRunId));
      } catch {
        // The normal refresh/polling path will retry; cancellation already succeeded.
      }
    }
    upsertRunDetailCache(updatedRuns);
    await refreshRunGroupsForRuns(updatedRuns);
    setSelectedRunId(selectedAfterAction);
    return {
      selectedRunId: selectedAfterAction,
      statusMessage: nextSelectedRunId ? '已取消子 Run，Workflow 已终止。' : 'Run 已取消。',
    };
  }

  async function cancelSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择要取消的 Run');
    return cancelRunById(selectedRun.run_id);
  }

  function requestCancelSelectedRun() {
    if (!selectedRun || !isActiveRunStatus(selectedRun.status)) return;
    const runName = selectedRun.runnable_name || selectedRun.runnable_id || 'Run';
    showConfirmDialog({
      title: `取消「${runName}」？`,
      description: '这会终止当前进行中或待审批的 Run；如果它正在等待审批，待审批请求也会被清空。',
      confirmLabel: '取消 Run',
      variant: 'danger',
      onConfirm: () => void runAction(cancelSelectedRun, '取消 Run'),
    });
  }

  return (
    <section className="agent-studio-page hy-route-page">
      <header className="agent-studio-hero">
        <button type="button" className="page-back-link" onClick={() => void openAppView('main')}>← 返回主控台</button>
        <div>
          <span className="section-eyebrow">Agent Runtime</span>
          <h1>Agent Studio</h1>
          <p>创建可配置 Agent，导入本地 Skills，并用线性 Workflow 把多个 Agent 编排成可运行链路。</p>
        </div>
      </header>

      <div className="agent-studio-tabs" role="tablist" aria-label="Agent Studio">
        {studioTabs.map((item) => (
          <button
            type="button"
            className={isTopTabActive(item) ? 'active' : ''}
            key={item}
            onClick={() => activateTab(item)}
          >
            {item === 'agents' ? 'Agents' : item === 'groups' ? 'Groups' : item === 'skills' ? 'Skill Library' : item === 'workflows' ? 'Workflow Studio' : item === 'runs' ? 'Runs' : 'Memory'}
          </button>
        ))}
      </div>

      {loading ? <AgentStudioLoadingState /> : null}
      {status ? <div className="notice">{status}</div> : null}
      {error ? <div className="notice danger">{error}</div> : null}

      {!loading && isSkillLibraryTab ? (
        <div className="skill-library-subnav" role="tablist" aria-label="Skill Library">
          <button type="button" className={tab === 'skills' ? 'active' : ''} onClick={() => activateTab('skills')}>Skills 列表</button>
          <button type="button" className={tab === 'skill-groups' ? 'active' : ''} onClick={() => activateTab('skill-groups')}>分组管理</button>
        </div>
      ) : null}

      {!loading && tab === 'groups' ? (
        <AgentGroupPanel
          agents={agents}
          agentGroups={agentGroups}
          agentGroupMemberIds={agentGroupMemberIds}
          agentGroupName={agentGroupName}
          agentGroupRunGoal={agentGroupRunGoal}
          busy={busy}
          latestAgentGroupRun={latestAgentGroupRun}
          selectedAgentGroup={selectedAgentGroup}
          selectedAgentGroupId={selectedAgentGroupId}
          onAgentGroupNameChange={setAgentGroupName}
          onAgentGroupRunGoalChange={setAgentGroupRunGoal}
          onOpenAgentGroupRunTimeline={openAgentGroupRunTimeline}
          onRunAgentGroup={() => void runAction(runCurrentAgentGroup, '启动 Group Run')}
          onSaveAgentGroup={() => void runAction(saveAgentGroup, '保存 Agent Group')}
          onSelectAgentGroup={(groupId) => {
            selectAgentGroup(groupId);
            setStatus('');
            setError('');
          }}
          onStartNewAgentGroup={() => {
            startNewAgentGroup();
            setStatus('正在编辑新的 Agent Group 草稿');
            setError('');
          }}
          onToggleAgentGroupMember={toggleAgentGroupMember}
        />
      ) : null}

      {!loading && tab === 'agents' ? (
        <section className="agent-studio-grid" data-testid="agent-studio-agents">
          <AgentListPanel
            agents={agents}
            agentManagementMode={agentManagementMode}
            allAgentsSelected={allAgentsSelected}
            busy={busy}
            deletableAgentIds={deletableAgentIds}
            selectedAgentCount={selectedAgents.length}
            selectedAgentId={selectedAgentId}
            selectedAgentIdSet={selectedAgentIdSet}
            selectedDeletableAgentCount={selectedDeletableAgents.length}
            onClearSelection={() => setSelectedAgentIds([])}
            onFinishManagement={finishAgentManagement}
            onRequestDeleteSelectedAgents={requestDeleteSelectedAgents}
            onSelectAgent={selectAgent}
            onSetAgentManagementMode={setAgentManagementMode}
            onSetSelectedAgentIds={setSelectedAgentIds}
            onStartNewAgent={startNewAgent}
            onToggleAgentSelected={toggleAgentSelected}
          />
          <AgentEditorPanel
            agentQuickRunDisabled={agentQuickRunDisabled}
            agentQuickRunDisabledReason={agentQuickRunDisabledReason}
            agentReadinessNotices={agentReadinessNotices}
            agentRunGoal={agentRunGoal}
            busy={busy}
            chatModelProfiles={chatModelProfiles}
            customApiKeyConfigured={Boolean(selectedAgent?.model_config.api_key_configured)}
            disabledMountedSkills={disabledMountedSkills}
            draft={draft}
            filteredMountSkills={filteredMountSkills}
            mountedSkillCount={mountedSkillCount}
            selectedAgentDeletable={selectedAgentDeletable}
            selectedAgentReadOnly={selectedAgentReadOnly}
            selectedSkillIds={selectedAgent?.skill_ids || []}
            skillFolders={skillFolders}
            skillMountFilter={skillMountFilter}
            skillMountFolderFilter={skillMountFolderFilter}
            skillMountSearch={skillMountSearch}
            visibleMountedCount={visibleMountedCount}
            visionModelProfiles={visionModelProfiles}
            onAgentRunGoalChange={setAgentRunGoal}
            onDraftChange={setDraft}
            onMountVisibleSkills={() => void runAction(mountVisibleSkills, '挂载当前筛选 Skills')}
            onOpenModelProfiles={() => void openAppView('provider')}
            onPickAgentAvatar={() => void pickAgentAvatar()}
            onRequestDeleteAgent={requestDeleteAgent}
            onRunAgent={() => void runAction(runCurrentAgent, '运行 Agent')}
            onSaveAgent={() => void runAction(saveAgent, '保存 Agent')}
            onSetSkillMountFilter={setSkillMountFilter}
            onSetSkillMountFolderFilter={setSkillMountFolderFilter}
            onSetSkillMountSearch={setSkillMountSearch}
            onTestAgentModel={() => void runAction(async () => {
              const result = await testAgentModel(draft.agent_id || '');
              setStatus(result.message || (result.ok ? '模型测试通过' : '模型测试失败'));
            }, '测试模型')}
            onToggleSkillMount={toggleAgentSkillMount}
            onUnmountVisibleSkills={() => void runAction(unmountVisibleSkills, '移除当前筛选 Skills')}
          />
        </section>
      ) : null}

      {!loading && tab === 'skills' ? (
        <section className="agent-studio-grid" data-testid="skill-library">
          <div className="agent-studio-panel skill-import-panel" data-testid="skill-import-panel">
            <div className="section-heading-row">
              <h2>Installed Skills</h2>
            </div>
            <p className="agent-section-help">从安装命令或上传入口导入的 Skills 会进入 Installed Skill 管理区；它们和 Native Skill Library 分开展示和挂载。</p>
            <div className="skill-import-target">
              <label>
                <span>导入到文件夹</span>
                <select className="hy-select" data-testid="skill-import-folder-select" value={skillTargetFolderId} onChange={(event) => setSkillTargetFolderId(event.target.value)}>
                  <option value="">无需分组</option>
                  {skillFolders.map((folder) => (
                    <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
                  ))}
                </select>
              </label>
              <small>需要新增、重命名或删除文件夹时，进入上方“分组管理”。</small>
            </div>
            <div className="skill-install-box">
              <label>
                <span>Skill 来源或安装命令</span>
                <input
                  className="hy-input"
                  data-testid="skill-install-command-input"
                  value={skillInstallCommand}
                  onChange={(event) => setSkillInstallCommand(event.target.value)}
                  placeholder="owner/repo --skill skill-name 或 skills@latest add owner/repo"
                />
              </label>
              {installingSkill ? (
                <div className="skill-install-progress" role="progressbar" aria-label="Skill 安装进度">
                  <span />
                </div>
              ) : null}
              <button type="button" data-testid="skill-install-command-submit" disabled={busy || !skillInstallCommand.trim()} onClick={() => void runAction(installSkillFromCommand, '安装 Skill')}>
                {installingSkill ? '安装中...' : '安装并同步'}
              </button>
              <small>可以直接输入 Skill 来源，也可以输入 <code>skills@latest add ...</code> 或 <code>npx skills add ...</code>。Oha-Yachiyo 会固定使用 <code>oha-yachiyo</code> 目标并补上 <code>--copy -y</code>，在 Installed Skill 工作区执行，不写入 Native 全局库。</small>
            </div>
            <div className="section-heading-row"><h2>上传 Skills</h2></div>
            <p className="agent-section-help">支持批量上传 zip 技能包，也支持选择本地 Skill 目录；导入后会复制到 Installed Skill 管理区。</p>
            <div className="skill-import-hints">
              <span>一次上传多个 zip</span>
              <span>自动校验 SKILL.md</span>
              <span>跳过重复选择</span>
            </div>
            <div
              className="skill-drop-zone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={dropSkillSources}
            >
              <strong>拖拽 Skill 目录或 zip 到这里</strong>
              <span>也可以点击选择文件，选择后会立即校验并导入</span>
              <button type="button" data-testid="skill-source-picker" disabled={busy} onClick={() => void pickSkillSources()}>上传 Skills</button>
            </div>
            <div className="section-heading-row">
              <h2>Native Skill Library</h2>
              <button type="button" data-testid="skill-native-sync" disabled={busy} onClick={() => void runAction(syncNativeSkillLibrary, '同步 Native Skills')}>从 Native Library 同步</button>
            </div>
            <p className="agent-section-help">Native Skill Library 的 `~/.oha-yachiyo/skill-library/skills` 只登记引用，不复制到 Installed Skill 管理区；项目级 Skills 暂不纳入本页管理。</p>
            <div className="skill-source-roots">
              {skillSources.map((source) => (
                <div className={source.exists ? 'skill-source-root' : 'skill-source-root missing'} data-testid="skill-source-root" key={`${source.source_type}-${source.path}`}>
                  <strong>{skillSourceTypeLabel(source.source_type)}</strong>
                  <span>{source.skill_count || 0} skills</span>
                  <code>{source.path}</code>
                </div>
              ))}
              {!skillSources.length ? <div className="empty-state inline-empty">暂未检测到 Native skills root。</div> : null}
            </div>
            {skillImportResults.length ? (
              <div className="skill-import-results" aria-label="Skill import results" data-testid="skill-import-results">
                {skillImportResults.map((result) => (
                  <div className={`skill-import-result ${result.status}`} data-testid="skill-import-result" key={`${result.source}-${result.status}`}>
                    <strong>{skillResultStatusLabel(result.status)}</strong>
                    <span>{result.source}</span>
                    <small>{result.message}</small>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="agent-studio-panel" data-testid="skill-library-panel">
            <div className="section-heading-row">
              <h2>{skillLibraryFilter === 'native' ? 'Native Skill Library' : 'Installed Skill Library'}</h2>
              <div className="studio-heading-actions">
                <span className="agent-section-count">{installedSkillCount} Installed / {nativeSkillCount} Native</span>
                {filteredLibrarySkills.length && !skillManagementMode ? (
                  <button type="button" disabled={busy} onClick={() => setSkillManagementMode(true)}>管理</button>
                ) : null}
              </div>
            </div>
            <div className="skill-filter-bar">
              <div className="skill-filter-tabs">
                <button type="button" data-testid="skill-filter-installed" className={skillLibraryFilter === 'installed' ? 'active' : ''} onClick={() => setSkillLibraryFilter('installed')}>Installed</button>
                <button type="button" data-testid="skill-filter-native" className={skillLibraryFilter === 'native' ? 'active' : ''} onClick={() => setSkillLibraryFilter('native')}>Native</button>
              </div>
              <select
                className="hy-select"
                data-testid="skill-library-folder-filter"
                value={skillLibraryFolderFilter}
                onChange={(event) => setSkillLibraryFolderFilter(event.target.value)}
              >
                <option value="all">全部文件夹</option>
                <option value="uncategorized">无需分组</option>
                {skillFolders.map((folder) => (
                  <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
                ))}
              </select>
              <input
                className="hy-input"
                data-testid="skill-library-search"
                value={skillLibrarySearch}
                onChange={(event) => setSkillLibrarySearch(event.target.value)}
                placeholder="搜索 Skill 名称、路径或摘要"
              />
            </div>
            {filteredLibrarySkills.length && skillManagementMode ? (
              <div className="studio-bulk-actions" aria-label="Skill 批量操作">
                <span>{selectedLibrarySkills.length ? `已选择 ${selectedLibrarySkills.length} / ${filteredLibrarySkills.length}` : `${filteredLibrarySkills.length} skills`}</span>
                <button type="button" disabled={busy} onClick={() => setSelectedSkillIds(allLibrarySkillsSelected ? [] : filteredLibrarySkillIds)}>
                  {allLibrarySkillsSelected ? '取消全选' : '全选当前列表'}
                </button>
                <button type="button" disabled={busy || !selectedLibrarySkills.length} onClick={() => setSelectedSkillIds([])}>清空</button>
                <button type="button" className="danger-action" disabled={busy || !selectedLibrarySkills.length} onClick={requestDeleteSelectedSkills}>删除所选</button>
                <button type="button" disabled={busy} onClick={finishSkillManagement}>完成</button>
              </div>
            ) : null}
            <div className="skill-list" data-testid="skill-list">
              {filteredLibrarySkills.map((skill) => (
                <SkillCard
                  busy={busy}
                  folders={skillFolders}
                  key={skill.skill_id}
                  onDelete={() => requestDeleteSkill(skill)}
                  onMoveFolder={(folderId) => runAction(async () => { await updateSkill(skill.skill_id, { folder_id: folderId }); }, '移动 Skill')}
                  onOpenLocation={() => runAction(async () => { await openPath(skill.local_path || ''); }, '打开 Skill 路径')}
                  onSelectionChange={() => toggleSkillSelected(skill.skill_id)}
                  onToggleEnabled={() => runAction(async () => { await updateSkill(skill.skill_id, { enabled: skill.enabled === false }); }, skill.enabled === false ? '启用 Skill' : '停用 Skill')}
                  managing={skillManagementMode}
                  selected={selectedSkillIdSet.has(skill.skill_id)}
                  skill={skill}
                />
              ))}
              {!filteredLibrarySkills.length ? <div className="empty-state inline-empty">当前分类或搜索下没有 Skill。</div> : null}
            </div>
          </div>
        </section>
      ) : null}

      {!loading && tab === 'skill-groups' ? (
        <section className="agent-studio-grid skill-group-page" data-testid="skill-folder-page">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Skill 分组</h2>
            </div>
            <p className="agent-section-help">文件夹只用于筛选、导入目标和 Agent 挂载选择，不会移动 Native Skill Library 原始路径。</p>
            <div className="skill-folder-box">
              <div className="section-heading-row compact">
                <h3>新建文件夹</h3>
              </div>
              <div className="skill-folder-create">
                <input
                  className="hy-input"
                  data-testid="skill-folder-name-input"
                  maxLength={skillFolderNameMaxLength + 1}
                  value={newSkillFolderName}
                  onChange={(event) => setNewSkillFolderName(event.target.value)}
                  placeholder="例如 Laravel / Design"
                />
                <button type="button" data-testid="skill-folder-create" disabled={busy || !newSkillFolderName.trim() || Boolean(newSkillFolderError)} onClick={() => void runAction(createSkillFolderFromDraft, '创建 Skill 文件夹')}>新建</button>
              </div>
              {newSkillFolderError ? <small className="skill-folder-validation">{newSkillFolderError}</small> : null}
            </div>
            <div className="skill-folder-system-row">
              <strong>无需分组</strong>
              <div className="skill-folder-meta">
                <span>{ungroupedSkillStats.total} skills</span>
                <span>{ungroupedSkillStats.installed} Installed</span>
                <span>{ungroupedSkillStats.native} Native</span>
              </div>
              <small>默认分组，不能删除；删除其他文件夹后 Skill 会回到这里。</small>
            </div>
          </aside>
          <div className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>文件夹管理</h2>
              <span className="agent-section-count">{skillFolders.length} folders</span>
            </div>
            <div className="skill-folder-manager-list" data-testid="skill-folder-list">
              {skillFolders.map((folder) => {
                const editing = editingSkillFolderId === folder.folder_id;
                const deleteMode = skillFolderDeleteModes[folder.folder_id] || 'folder';
                const deleteWithSkills = deleteMode === 'skills' && Boolean(folder.skill_count || 0);
                return (
                  <article
                    className="skill-folder-manager-row"
                    data-folder-id={folder.folder_id}
                    data-folder-name={folder.name}
                    data-testid="skill-folder-row"
                    key={folder.folder_id}
                  >
                    <div className="skill-folder-manager-main">
                      {editing ? (
                        <input
                          className="hy-input"
                          data-testid="skill-folder-edit-name-input"
                          maxLength={skillFolderNameMaxLength + 1}
                          value={editingSkillFolderName}
                          onChange={(event) => setEditingSkillFolderName(event.target.value)}
                          autoFocus
                        />
                      ) : (
                        <>
                          <h3>{folder.name}</h3>
                          <div className="skill-folder-meta">
                            <span>{folder.skill_count || 0} skills</span>
                            <span>{folder.installed_count || 0} Installed</span>
                            <span>{folder.native_count || 0} Native</span>
                          </div>
                        </>
                      )}
                    </div>
                    <div className="skill-folder-actions">
                      {editing ? (
                        <>
                          <button type="button" data-testid="skill-folder-save-rename" disabled={busy || !editingSkillFolderName.trim() || Boolean(editingSkillFolderError)} onClick={() => void runAction(async () => updateSkillFolderFromDraft(folder.folder_id), '重命名 Skill 文件夹')}>保存</button>
                          <button type="button" data-testid="skill-folder-cancel-rename" disabled={busy} onClick={cancelEditingSkillFolder}>取消</button>
                        </>
                      ) : (
                        <>
                          <button type="button" data-testid="skill-folder-rename" disabled={busy} onClick={() => startEditingSkillFolder(folder)}>重命名</button>
                          <button type="button" data-testid="skill-folder-open" disabled={busy} onClick={() => openSkillLibraryFolder(folder)}>查看</button>
                          <div className="skill-folder-delete-control" aria-label={`${folder.name} 删除设置`}>
                            <label className="skill-folder-delete-switch" title="开启后删除文件夹时会连带删除其中 Skills">
                              <input
                                type="checkbox"
                                data-testid="skill-folder-delete-with-skills"
                                role="switch"
                                checked={deleteWithSkills}
                                disabled={busy || !(folder.skill_count || 0)}
                                aria-label={`${folder.name} 删除时连带删除 Skills`}
                                onChange={(event) => setSkillFolderDeleteMode(folder.folder_id, event.currentTarget.checked ? 'skills' : 'folder')}
                              />
                              <span className="skill-folder-delete-toggle" aria-hidden="true" />
                              <span>连带 Skills</span>
                            </label>
                            <button
                              type="button"
                              className="danger-action"
                              data-testid="skill-folder-delete"
                              disabled={busy}
                              onClick={() => requestDeleteSkillFolder(folder, deleteWithSkills)}
                            >
                              删除
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                    {editing && editingSkillFolderError ? <small className="skill-folder-validation">{editingSkillFolderError}</small> : null}
                  </article>
                );
              })}
              {!skillFolders.length ? (
                <div className="empty-state inline-empty skill-folder-empty-state">
                  <strong>暂无自定义文件夹</strong>
                  <span>现有 Skill 会继续显示在“无需分组”里。</span>
                </div>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      {!loading && tab === 'workflows' ? (
        <WorkflowEditorPanel
          agents={agents}
          agentCapabilityLine={agentCapabilityLine}
          agentIssueById={agentRunIssueById}
          allWorkflowsSelected={allWorkflowsSelected}
          busy={busy}
          edges={edges}
          nodes={nodes}
          onAddFlowNode={addFlowNode}
          onConnect={onConnect}
          onDeleteSelectedWorkflows={requestDeleteSelectedWorkflows}
          onDeleteWorkflow={requestDeleteWorkflow}
          onEdgesChange={onEdgesChange}
          onFinishWorkflowManagement={finishWorkflowManagement}
          onLoadTemplate={loadPhase4WorkflowTemplate}
          onNewWorkflow={startNewWorkflow}
          onNodesChange={onNodesChange}
          onRemoveFlowNode={removeFlowNode}
          onRunWorkflow={() => void runAction(runCurrentWorkflow, '保存并运行 Workflow')}
          onSaveWorkflow={() => void runAction(saveWorkflow, '保存 Workflow')}
          onSelectWorkflow={selectWorkflow}
          onSetSelectedWorkflowIds={setSelectedWorkflowIds}
          onStartWorkflowManagement={() => setWorkflowManagementMode(true)}
          onToggleWorkflowSelected={toggleWorkflowSelected}
          selectedWorkflow={selectedWorkflow}
          selectedWorkflowIdSet={selectedWorkflowIdSet}
          selectedWorkflows={selectedWorkflows}
          setNodes={setNodes}
          setWorkflowDescription={setWorkflowDescription}
          setWorkflowEnabled={setWorkflowEnabled}
          setWorkflowName={setWorkflowName}
          setWorkflowRunGoal={setWorkflowRunGoal}
          workflowDescription={workflowDescription}
          workflowEnabled={workflowEnabled}
          workflowErrors={workflowErrors}
          workflowHasErrors={workflowHasErrors}
          workflowIds={workflowIds}
          workflowManagementMode={workflowManagementMode}
          workflowName={workflowName}
          workflowPrimaryError={workflowPrimaryError}
          workflowRunDisabled={workflowRunDisabled}
          workflowRunDisabledReason={workflowRunDisabledReason}
          workflowRunGoal={workflowRunGoal}
          workflowRunPreviewSteps={workflowRunPreviewSteps}
          workflows={workflows}
          workflowValidation={workflowValidation}
        />
      ) : null}

      {!loading && tab === 'memory' ? (
        <RuntimeMemoryPanel
          busy={busy}
          formatRunDate={formatRunDate}
          futureTasks={futureTasks}
          memories={memories}
          onCancelFutureTask={requestCancelFutureTask}
          onDeleteMemory={requestDeleteMemory}
          onOpenRunDetail={openRunDetail}
          onTriggerDueFutureTasks={() => void runAction(triggerDueFutureTaskRuns, '触发到期 FutureTask')}
        />
      ) : null}

      {!loading && tab === 'runs' ? (
        <section className="agent-studio-grid">
          <RunLauncherPanel
            allHistoryRunsSelected={allHistoryRunsSelected}
            busy={busy}
            collapsedRunHistoryGroups={collapsedRunHistoryGroups}
            filteredRunIds={filteredRunIds}
            filteredRuns={filteredRuns}
            formatRunDate={formatRunDate}
            runBulkDeleteDisabledReason={runBulkDeleteDisabledReason}
            runFilterCounts={runFilterCounts}
            runGoal={runGoal}
            runHistoryGroupSummary={runHistoryGroupSummary}
            runHistoryGroups={runHistoryGroups}
            runHistoryManagementMode={runHistoryManagementMode}
            runKindFilter={runKindFilter}
            runKindLabel={runKindLabel}
            runSearchActive={runSearchActive}
            runSearchQuery={runSearchQuery}
            runStatusFilter={runStatusFilter}
            runStatusFilterCounts={runStatusFilterCounts}
            runStatusFilteredRuns={runStatusFilteredRuns}
            runStatusLabel={runStatusLabel}
            runStatusTone={runStatusTone}
            runTarget={runTarget}
            runTargetDisabledReason={runTargetDisabledReason}
            runTargetWorkflowErrors={selectedRunTargetWorkflowValidation.errors}
            runnables={runnables}
            selectedHistoryRunCount={selectedHistoryRuns.length}
            selectedRunId={selectedRunId}
            selectedRunIdSet={selectedRunIdSet}
            selectedRunTarget={selectedRunTarget}
            workflowPreview={selectedRunTarget?.kind === 'workflow' ? (
              <WorkflowRunPreview
                agents={agents}
                agentCapabilityLine={agentCapabilityLine}
                agentIssueById={agentRunIssueById}
                sourceNodes={selectedRunTargetWorkflowNodes}
                steps={selectedRunTargetWorkflowPreviewSteps}
              />
            ) : null}
            onCreateRun={() => void runAction(async () => {
              const target = runnables.find((item) => item.id === runTarget);
              if (!target) return;
              const goal = runGoal.trim();
              const run = target.kind === 'agent'
                ? await createAgentRun(target.id, goal)
                : await createWorkflowRun(target.id, goal);
              openRunDetail(run.run_id, { revealInHistory: true });
              setRunGoal('');
              return { selectedRunId: run.run_id, runTarget: target.id };
            }, '创建 Run')}
            onFinishRunHistoryManagement={finishRunHistoryManagement}
            onOpenRunDetail={openRunDetail}
            onRequestDeleteSelectedRuns={requestDeleteSelectedRuns}
            onRunGoalChange={setRunGoal}
            onRunSearchQueryChange={setRunSearchQuery}
            onRunTargetChange={setRunTarget}
            onSelectRunKindFilter={selectRunKindFilter}
            onSelectRunStatusFilter={selectRunStatusFilter}
            onSetRunHistoryManagementMode={setRunHistoryManagementMode}
            onSetSelectedRunIds={setSelectedRunIds}
            onToggleRunHistoryGroup={toggleRunHistoryGroup}
            onToggleRunSelected={toggleRunSelected}
            runnableCapabilityLine={runnableCapabilityLine}
            runnableOptionLabel={runnableOptionLabel}
          />
          <RunDetailPanel
            artifactPreview={artifactPreview}
            busy={busy}
            formatRunDate={formatRunDate}
            isActiveRunStatus={isActiveRunStatus}
            normalizeRunStatus={normalizeRunStatus}
            onApproveRunById={approveRunById}
            onApproveSelectedRun={approveSelectedRun}
            onCancelRunById={cancelRunById}
            onLoadMoreSelectedRunEvents={loadMoreSelectedRunEvents}
            onOpenArtifact={openArtifact}
            onOpenRunDetail={openRunDetail}
            onOpenWorkflowDesign={openWorkflowDesign}
            onPrepareSelectedRunRerun={prepareSelectedRunRerun}
            onRejectRunById={rejectRunById}
            onRejectSelectedRun={rejectSelectedRun}
            onRequestCancelSelectedRun={requestCancelSelectedRun}
            onRerunSelectedRun={rerunSelectedRun}
            onRunAction={(action, label) => void runAction(action as () => Promise<StudioRefreshOptions | void>, label)}
            runById={runById}
            runKindLabel={runKindLabel}
            runStatusLabel={runStatusLabel}
            runStatusTone={runStatusTone}
            selectedPublicRunTimeline={selectedPublicRunTimeline}
            selectedRun={selectedRun}
            selectedRunApproval={selectedRunApproval}
            selectedRunArtifacts={selectedRunArtifacts}
            selectedRunAvatarUrl={selectedRunAvatarUrl}
            selectedRunExecutionEvents={selectedRunExecutionEvents}
            selectedRunIsLive={selectedRunIsLive}
            selectedRunReplayError={selectedRunReplayError}
            selectedRunReplayEvents={selectedRunReplayEvents}
            selectedRunReplayHasMore={selectedRunReplayHasMore}
            selectedRunReplayLoading={selectedRunReplayLoading}
            selectedRunRerunDisabledReason={selectedRunRerunDisabledReason}
            selectedRunRerunTarget={selectedRunRerunTarget}
            selectedRunWorkflow={selectedRunWorkflow}
            selectedWorkflowApprovalChildRun={selectedWorkflowApprovalChildRun}
            selectedWorkflowApprovalChildRunId={selectedWorkflowApprovalChildRunId}
            selectedWorkflowApprovalStep={selectedWorkflowApprovalStep}
            selectedWorkflowParentRun={selectedWorkflowParentRun}
            selectedWorkflowParentRunId={selectedWorkflowParentRunId}
            selectedWorkflowSteps={selectedWorkflowSteps}
            skippedWorkflowArtifactLabel={skippedWorkflowArtifactLabel}
            workflowRunArtifactForStep={workflowRunArtifactForStep}
            workflowStepArtifacts={workflowStepArtifacts}
            workflowStepKindLabel={workflowStepKindLabel}
            workflowStepSummary={workflowStepSummary}
          />
        </section>
      ) : null}

      <ConfirmDialog
        confirmLabel={confirmDialog?.confirmLabel}
        description={confirmDialog?.description}
        onCancel={closeConfirmDialog}
        onConfirm={confirmCurrentDialog}
        open={Boolean(confirmDialog)}
        title={confirmDialog?.title || ''}
        variant={confirmDialog?.variant}
      />
    </section>
  );
}

function SkillCard({
  busy,
  folders,
  managing,
  onDelete,
  onMoveFolder,
  onOpenLocation,
  onSelectionChange,
  onToggleEnabled,
  selected,
  skill,
}: {
  busy: boolean;
  folders: SkillFolderSpec[];
  managing: boolean;
  onDelete: () => Promise<void> | void;
  onMoveFolder: (folderId: string) => Promise<void>;
  onOpenLocation: () => Promise<void>;
  onSelectionChange: () => void;
  onToggleEnabled: () => Promise<void>;
  selected: boolean;
  skill: SkillSpec;
}) {
  const enabled = skill.enabled !== false;
  const cardClassName = [
    'skill-card',
    enabled ? '' : 'disabled',
    managing ? 'managing' : '',
  ].filter(Boolean).join(' ');
  return (
    <article
      className={cardClassName}
      data-skill-enabled={enabled ? 'true' : 'false'}
      data-skill-folder-id={skill.folder_id || ''}
      data-skill-id={skill.skill_id}
      data-testid="skill-card"
    >
      <div className="section-heading-row skill-card-head">
        <div className="skill-card-title">
          <label className="skill-card-select" aria-label={`选择 Skill ${skill.name}`}>
            <input
              type="checkbox"
              data-testid="skill-card-select"
              checked={selected}
              disabled={busy || !managing}
              onChange={onSelectionChange}
            />
          </label>
          <div>
            <h3>{skill.name}</h3>
            <span className="skill-source-tag">{skillSourceTypeLabel(skill.source_type)}</span>
          </div>
        </div>
        <label className={enabled ? 'skill-enable-switch active' : 'skill-enable-switch'}>
          <input
            type="checkbox"
            data-testid="skill-card-enabled-toggle"
            checked={enabled}
            disabled={busy}
            onChange={() => void onToggleEnabled()}
          />
          <span aria-hidden="true" />
        </label>
      </div>
      <p>{skill.description || skill.content_summary}</p>
      <label className="skill-card-folder">
        <span>文件夹</span>
        <select
          className="hy-select"
          data-testid="skill-card-folder-select"
          value={skill.folder_id || ''}
          disabled={busy}
          onChange={(event) => void onMoveFolder(event.target.value)}
        >
          <option value="">无需分组</option>
          {folders.map((folder) => (
            <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
          ))}
        </select>
      </label>
      <div className="skill-card-path">
        <span>路径</span>
        <code>{skillPathLabel(skill)}</code>
      </div>
      {skillSourceLabel(skill) ? (
        <div className="skill-card-path">
          <span>来源</span>
          <code>{skillSourceLabel(skill)}</code>
        </div>
      ) : null}
      {skill.asset_paths?.length ? <small>{skill.asset_paths.length} assets/templates</small> : null}
      <div className="skill-card-actions">
        <button type="button" data-testid="skill-card-open-location" disabled={busy || !skill.local_path} onClick={() => void onOpenLocation()}>打开路径</button>
        <button type="button" className="danger-action" data-testid="skill-card-delete" disabled={busy} onClick={() => void onDelete()}>删除</button>
      </div>
      <pre>{(skill.skill_markdown || '').slice(0, 1200)}</pre>
    </article>
  );
}
