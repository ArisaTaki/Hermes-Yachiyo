import { useCallback, useEffect, useMemo, useState } from 'react';
import type { Connection, Edge, Node } from '@xyflow/react';
import {
  addEdge,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { ConfirmDialog } from '../components/ConfirmDialog';
import { AgentDefinitionsTab } from '../features/agent-studio/components/AgentDefinitionsTab';
import { AgentGroupPanel } from '../features/agent-studio/components/AgentGroupPanel';
import { AgentStudioChrome } from '../features/agent-studio/components/AgentStudioChrome';
import { RuntimeMemoryPanel } from '../features/agent-studio/components/RuntimeMemoryPanel';
import { RunManagementTab } from '../features/agent-studio/components/RunManagementTab';
import { SkillFolderPanel } from '../features/agent-studio/components/SkillFolderPanel';
import { SkillLibraryTab } from '../features/agent-studio/components/SkillLibraryTab';
import { WorkflowEditorPanel, WorkflowRunPreview } from '../features/agent-studio/components/WorkflowEditorPanel';
import { useAgentAvatarActions } from '../features/agent-studio/hooks/useAgentAvatarActions';
import { useAgentDeletionActions } from '../features/agent-studio/hooks/useAgentDeletionActions';
import { useAgentDefinitions } from '../features/agent-studio/hooks/useAgentDefinitions';
import { useAgentGroups } from '../features/agent-studio/hooks/useAgentGroups';
import { useAgentSaveActions } from '../features/agent-studio/hooks/useAgentSaveActions';
import { useAgentSkillMountActions } from '../features/agent-studio/hooks/useAgentSkillMountActions';
import { useApprovedRunGuard } from '../features/agent-studio/hooks/useApprovedRunGuard';
import { useRunApprovalActions } from '../features/agent-studio/hooks/useRunApprovalActions';
import { useRunApprovalFollowup } from '../features/agent-studio/hooks/useRunApprovalFollowup';
import { useRunArtifactActions } from '../features/agent-studio/hooks/useRunArtifactActions';
import { useRunCacheActions } from '../features/agent-studio/hooks/useRunCacheActions';
import { useRunDebugActions } from '../features/agent-studio/hooks/useRunDebugActions';
import { useRunEventReplay } from '../features/agent-studio/hooks/useRunEventReplay';
import { useRunHistoryManagement } from '../features/agent-studio/hooks/useRunHistoryManagement';
import { useRunLaunchActions } from '../features/agent-studio/hooks/useRunLaunchActions';
import { useRunNavigationActions } from '../features/agent-studio/hooks/useRunNavigationActions';
import { useRunTimeline } from '../features/agent-studio/hooks/useRunTimeline';
import { useRuntimeMemoryManagement } from '../features/agent-studio/hooks/useRuntimeMemoryManagement';
import { useSkillDeletionActions } from '../features/agent-studio/hooks/useSkillDeletionActions';
import { useSkillFolderManagement } from '../features/agent-studio/hooks/useSkillFolderManagement';
import { useSkillImportActions } from '../features/agent-studio/hooks/useSkillImportActions';
import { useSkillSourceInputActions } from '../features/agent-studio/hooks/useSkillSourceInputActions';
import { useWorkflowDeletionActions } from '../features/agent-studio/hooks/useWorkflowDeletionActions';
import { useWorkflowDefinitions } from '../features/agent-studio/hooks/useWorkflowDefinitions';
import { useWorkflowDraftActions } from '../features/agent-studio/hooks/useWorkflowDraftActions';
import { useWorkflowSaveActions } from '../features/agent-studio/hooks/useWorkflowSaveActions';
import { useWorkflowCanvasActions } from '../features/agent-studio/hooks/useWorkflowCanvasActions';
import {
  normalizeStudioTab,
  type StudioTab,
} from '../features/agent-studio/studioTabs';
import {
  agentCapabilityLine,
  agentRunReadinessIssue,
  agentToDraft,
  runnableCapabilityLine,
  runnableOptionLabel,
} from '../features/agent-studio/utils/agents';
import {
  formatRunDate,
  isActiveRunStatus,
  isPotentialWorkflowChildAgentRun,
  isWorkflowChildAgentRun,
  normalizeRunStatus,
  publicApprovalToRunPendingApproval,
  publicArtifactsOrLegacy,
  publicRunEventToTimelineEvent,
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
  skillFolderNameError,
  skillMatchesFolderFilter,
  skillMatchesQuery,
  skillMatchesSourceFilter,
  type SkillFolderFilter,
  type SkillImportResult,
  type SkillSourceFilter,
} from '../features/agent-studio/utils/skills';
import type { AgentDraft } from '../features/agent-studio/types';
import {
  skippedWorkflowArtifactLabel,
  starterNodes,
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
import {
  getRun,
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
  testAgentModel,
  updateSkill,
  type FutureTaskSpec,
  type MemorySpec,
  type RunnableSummary,
  type RunGroupSpec,
  type RunSpec,
  type SkillFolderSpec,
  type SkillSourceRoot,
  type SkillSpec,
} from '../lib/agents';
import { openAppView, openPath } from '../lib/bridge';
import { listModelProfiles, type ModelProfile, type ModelProfileDefaults } from '../lib/modelProfiles';
import { currentParam, navigateTo } from '../lib/view';

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
  const [skillManagementMode, setSkillManagementMode] = useState(false);
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
  const {
    saveWorkflow,
    saveWorkflowDraft,
  } = useWorkflowSaveActions({
    edges,
    nodes,
    selectedWorkflow,
    setSelectedWorkflowId,
    workflowDescription,
    workflowEnabled,
    workflowErrors,
    workflowName,
  });
  const {
    loadPhase4WorkflowTemplate,
    openWorkflowDesign,
    selectWorkflow,
    startNewWorkflow,
  } = useWorkflowDraftActions({
    agents,
    setEdges,
    setError,
    setNodes,
    setSelectedWorkflowId,
    setStatus,
    setTab,
    setWorkflowDescription,
    setWorkflowEnabled,
    setWorkflowName,
    workflows,
  });
  const {
    addFlowNode,
    removeFlowNode,
  } = useWorkflowCanvasActions({
    agents,
    edges,
    nodes,
    setEdges,
    setNodes,
  });
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
  const runHistoryGroups = useMemo(
    () => runHistoryGroupsFor(filteredRuns, runnables, agents),
    [agents, filteredRuns, runnables],
  );
  const {
    allHistoryRunsSelected,
    finishRunHistoryManagement,
    requestDeleteSelectedRuns,
    runBulkDeleteDisabledReason,
    runHistoryManagementMode,
    selectedHistoryRuns,
    selectedRunIdSet,
    setRunHistoryManagementMode,
    setSelectedRunIds,
    toggleRunSelected,
  } = useRunHistoryManagement({
    clearRunEventReplay,
    filteredRunIds,
    filteredRuns,
    runAction,
    selectedRunId,
    setArtifactPreview,
    setRunDetailCache,
    setRunGroups,
    setRuns,
    setSelectedRunId,
    showConfirmDialog,
  });
  const {
    openAgentGroupRunTimeline,
    openRunDetail,
    selectRunKindFilter,
    selectRunStatusFilter,
    toggleRunHistoryGroup,
  } = useRunNavigationActions({
    runs,
    selectedRun,
    selectedRunId,
    setCollapsedRunHistoryGroups,
    setError,
    setRunKindFilter,
    setRunSearchQuery,
    setRunStatusFilter,
    setSelectedRunId,
    setTab,
  });
  const {
    requestCancelFutureTask,
    requestDeleteMemory,
    triggerDueFutureTaskRuns,
  } = useRuntimeMemoryManagement({
    openRunDetail,
    runAction,
    showConfirmDialog,
  });
  const {
    openArtifact,
  } = useRunArtifactActions({
    setArtifactPreview,
    setError,
    setStatus,
  });
  const {
    cancelEditingSkillFolder,
    createSkillFolderFromDraft,
    openSkillLibraryFolder,
    requestDeleteSkillFolder,
    setSkillFolderDeleteMode,
    startEditingSkillFolder,
    updateSkillFolderFromDraft,
  } = useSkillFolderManagement({
    editingSkillFolderId,
    editingSkillFolderName,
    newSkillFolderName,
    runAction,
    setEditingSkillFolderId,
    setEditingSkillFolderName,
    setError,
    setNewSkillFolderName,
    setSkillFolderDeleteModes,
    setSkillLibraryFolderFilter,
    setSkillMountFolderFilter,
    setSkillTargetFolderId,
    setStatus,
    setTab,
    showConfirmDialog,
    skillFolders,
    skillLibraryFolderFilter,
    skillMountFolderFilter,
    skills,
    skillTargetFolderId,
  });
  const {
    importSkillSourceList,
    installSkillFromCommand,
    syncNativeSkillLibrary,
  } = useSkillImportActions({
    setSkillImportResults,
    setSkillSources,
    skillInstallCommand,
    skillTargetFolderId,
    skills,
  });
  const {
    dropSkillSources,
    pickSkillSources,
  } = useSkillSourceInputActions({
    importSkillSourceList,
    runAction,
    setError,
  });
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
  const {
    requestDeleteSelectedSkills,
    requestDeleteSkill,
  } = useSkillDeletionActions({
    runAction,
    selectedLibrarySkills,
    setSelectedSkillIds,
    showConfirmDialog,
  });
  const {
    requestDeleteAgent,
    requestDeleteSelectedAgents,
  } = useAgentDeletionActions({
    draftAgentId: draft.agent_id || '',
    draftAgentName: draft.name,
    resetAgentDraft: () => setDraft({ ...emptyAgentDraft }),
    runAction,
    selectedAgentDeletable,
    selectedAgentId,
    selectedAgentName: selectedAgent?.name || '',
    selectedDeletableAgents,
    setSelectedAgentId,
    setSelectedAgentIds,
    setStatus,
    showConfirmDialog,
  });
  const {
    saveAgent,
  } = useAgentSaveActions({
    draft,
    selectedAgentId,
    selectedAgentReadOnly,
    setDraft,
    setSelectedAgentId,
    setStatus,
  });
  const {
    pickAgentAvatar,
  } = useAgentAvatarActions({
    setBusyAction,
    setDraft,
    setError,
    setStatus,
  });
  const {
    requestDeleteSelectedWorkflows,
    requestDeleteWorkflow,
  } = useWorkflowDeletionActions({
    resetWorkflowDraft: startNewWorkflow,
    runAction,
    selectedWorkflow,
    selectedWorkflowId,
    selectedWorkflows,
    setSelectedWorkflowIds,
    showConfirmDialog,
  });
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
  const {
    mountVisibleSkills,
    toggleAgentSkillMount,
    unmountVisibleSkills,
  } = useAgentSkillMountActions({
    draftAgentId: draft.agent_id || '',
    runAction,
    selectedAgent,
    selectedAgentReadOnly,
    setStatus,
    visibleMountSkillIds,
  });
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
  const {
    refreshRunGroupById,
    refreshRunGroupsForRuns,
    upsertRunDetailCache,
  } = useRunCacheActions({
    acceptedRunUpdates,
    setRunDetailCache,
    setRunGroups,
    setRuns,
  });

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

  const {
    approvalFollowupRefreshOptions,
    isApprovalFollowupCurrent,
    pollApprovedRunProgress,
  } = useRunApprovalFollowup({
    acceptedRunUpdates,
    refresh,
    refreshRunGroupsForRuns,
    selectedRunId,
    setStatus,
    upsertRunDetailCache,
  });

  const {
    approveRunById,
    approveSelectedRun,
    cancelRunById,
    cancelSelectedRun,
    rejectRunById,
    rejectSelectedRun,
  } = useRunApprovalActions({
    approvalFollowupRefreshOptions,
    isApprovalFollowupCurrent,
    pollApprovedRunProgress,
    refresh,
    refreshRunGroupsForRuns,
    rememberApprovedRun,
    runById,
    selectedRun,
    setError,
    setSelectedRunId,
    setStatus,
    upsertRunDetailCache,
  });
  const {
    loadMoreSelectedRunEvents,
    requestCancelSelectedRun,
  } = useRunDebugActions({
    cancelSelectedRun,
    loadMoreRunReplayEvents,
    runAction,
    selectedRun,
    setStatus,
    showConfirmDialog,
  });

  const {
    createRunFromTarget,
    prepareSelectedRunRerun,
    rerunSelectedRun,
    runCurrentAgent,
    runCurrentWorkflow,
  } = useRunLaunchActions({
    agentQuickRunDisabledReason,
    agentRunGoal,
    draftAgentId: draft.agent_id || '',
    openRunDetail,
    refreshRunGroupsForRuns,
    runGoal,
    runnables,
    runTarget,
    saveWorkflowDraft,
    selectedRun,
    selectedRunRerunDisabledReason,
    selectedRunRerunTarget,
    setAgentRunGoal,
    setError,
    setRunGoal,
    setRunTarget,
    setStatus,
    setWorkflowRunGoal,
    upsertRunDetailCache,
    workflowRunDisabledReason,
    workflowRunGoal,
  });

  useEffect(() => {
    setLoading(true);
    refresh()
      .then(() => setError(''))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '读取 Agent Studio 失败'))
      .finally(() => setLoading(false));
  }, [refresh]);

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
    refreshRunGroupById(runGroupId, () => !disposed)
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [refreshRunGroupById, runGroups, selectedRun]);

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
  }, [runById, selectedWorkflowParentRunId, upsertRunDetailCache]);

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
  }, [selectedWorkflowApprovalChildRunId, selectedWorkflowChildRefs, upsertRunDetailCache]);

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
        await refreshRunGroupsForRuns(loadedRuns, () => !disposed);
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
  }, [activeRunPollKey, refreshRunGroupsForRuns, upsertRunDetailCache]);

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

  function finishSkillManagement() {
    setSkillManagementMode(false);
    setSelectedSkillIds([]);
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

  async function saveAgentGroup(): Promise<StudioRefreshOptions> {
    const { statusMessage } = await saveAgentGroupDraft();
    return { statusMessage };
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

  return (
    <section className="agent-studio-page hy-route-page">
      <AgentStudioChrome
        error={error}
        loading={loading}
        status={status}
        tab={tab}
        onActivateTab={activateTab}
        onBack={() => void openAppView('main')}
      />

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
        <AgentDefinitionsTab
          agentManagementMode={agentManagementMode}
          agentQuickRunDisabled={agentQuickRunDisabled}
          agentQuickRunDisabledReason={agentQuickRunDisabledReason}
          agentReadinessNotices={agentReadinessNotices}
          agentRunGoal={agentRunGoal}
          agents={agents}
          allAgentsSelected={allAgentsSelected}
          busy={busy}
          chatModelProfiles={chatModelProfiles}
          customApiKeyConfigured={Boolean(selectedAgent?.model_config.api_key_configured)}
          deletableAgentIds={deletableAgentIds}
          disabledMountedSkills={disabledMountedSkills}
          draft={draft}
          filteredMountSkills={filteredMountSkills}
          mountedSkillCount={mountedSkillCount}
          selectedAgentCount={selectedAgents.length}
          selectedAgentDeletable={selectedAgentDeletable}
          selectedAgentId={selectedAgentId}
          selectedAgentIdSet={selectedAgentIdSet}
          selectedAgentReadOnly={selectedAgentReadOnly}
          selectedDeletableAgentCount={selectedDeletableAgents.length}
          selectedSkillIds={selectedAgent?.skill_ids || []}
          skillFolders={skillFolders}
          skillMountFilter={skillMountFilter}
          skillMountFolderFilter={skillMountFolderFilter}
          skillMountSearch={skillMountSearch}
          visibleMountedCount={visibleMountedCount}
          visionModelProfiles={visionModelProfiles}
          onAgentRunGoalChange={setAgentRunGoal}
          onClearAgentSelection={() => setSelectedAgentIds([])}
          onDraftChange={setDraft}
          onFinishAgentManagement={finishAgentManagement}
          onMountVisibleSkills={() => void runAction(mountVisibleSkills, '挂载当前筛选 Skills')}
          onOpenModelProfiles={() => void openAppView('provider')}
          onPickAgentAvatar={() => void pickAgentAvatar()}
          onRequestDeleteAgent={requestDeleteAgent}
          onRequestDeleteSelectedAgents={requestDeleteSelectedAgents}
          onRunAgent={() => void runAction(runCurrentAgent, '运行 Agent')}
          onSaveAgent={() => void runAction(saveAgent, '保存 Agent')}
          onSelectAgent={selectAgent}
          onSetAgentManagementMode={setAgentManagementMode}
          onSetSelectedAgentIds={setSelectedAgentIds}
          onSetSkillMountFilter={setSkillMountFilter}
          onSetSkillMountFolderFilter={setSkillMountFolderFilter}
          onSetSkillMountSearch={setSkillMountSearch}
          onStartNewAgent={startNewAgent}
          onTestAgentModel={() => void runAction(async () => {
            const result = await testAgentModel(draft.agent_id || '');
            setStatus(result.message || (result.ok ? '模型测试通过' : '模型测试失败'));
          }, '测试模型')}
          onToggleAgentSelected={toggleAgentSelected}
          onToggleSkillMount={toggleAgentSkillMount}
          onUnmountVisibleSkills={() => void runAction(unmountVisibleSkills, '移除当前筛选 Skills')}
        />
      ) : null}

      {!loading && tab === 'skills' ? (
        <SkillLibraryTab
          allLibrarySkillsSelected={allLibrarySkillsSelected}
          busy={busy}
          filteredLibrarySkillIds={filteredLibrarySkillIds}
          filteredLibrarySkills={filteredLibrarySkills}
          installedSkillCount={installedSkillCount}
          installingSkill={installingSkill}
          nativeSkillCount={nativeSkillCount}
          selectedLibrarySkills={selectedLibrarySkills}
          selectedSkillIdSet={selectedSkillIdSet}
          skillFolders={skillFolders}
          skillImportResults={skillImportResults}
          skillInstallCommand={skillInstallCommand}
          skillLibraryFilter={skillLibraryFilter}
          skillLibraryFolderFilter={skillLibraryFolderFilter}
          skillLibrarySearch={skillLibrarySearch}
          skillManagementMode={skillManagementMode}
          skillSources={skillSources}
          skillTargetFolderId={skillTargetFolderId}
          onDeleteSkill={requestDeleteSkill}
          onDeleteSelectedSkills={requestDeleteSelectedSkills}
          onDropSkillSources={dropSkillSources}
          onFinishSkillManagement={finishSkillManagement}
          onInstallSkill={() => void runAction(installSkillFromCommand, '安装 Skill')}
          onMoveSkillFolder={(skill, folderId) => void runAction(async () => {
            await updateSkill(skill.skill_id, { folder_id: folderId });
          }, '移动 Skill')}
          onOpenSkillLocation={(skill) => void runAction(async () => {
            await openPath(skill.local_path || '');
          }, '打开 Skill 路径')}
          onPickSkillSources={() => void pickSkillSources()}
          onSetSelectedSkillIds={setSelectedSkillIds}
          onSetSkillInstallCommand={setSkillInstallCommand}
          onSetSkillLibraryFilter={setSkillLibraryFilter}
          onSetSkillLibraryFolderFilter={setSkillLibraryFolderFilter}
          onSetSkillLibrarySearch={setSkillLibrarySearch}
          onSetSkillManagementMode={setSkillManagementMode}
          onSetSkillTargetFolderId={setSkillTargetFolderId}
          onSyncNativeSkillLibrary={() => void runAction(syncNativeSkillLibrary, '同步 Native Skills')}
          onToggleSkillEnabled={(skill) => void runAction(async () => {
            await updateSkill(skill.skill_id, { enabled: skill.enabled === false });
          }, skill.enabled === false ? '启用 Skill' : '停用 Skill')}
          onToggleSkillSelected={toggleSkillSelected}
        />
      ) : null}

      {!loading && tab === 'skill-groups' ? (
        <SkillFolderPanel
          busy={busy}
          editingSkillFolderError={editingSkillFolderError}
          editingSkillFolderId={editingSkillFolderId}
          editingSkillFolderName={editingSkillFolderName}
          newSkillFolderError={newSkillFolderError}
          newSkillFolderName={newSkillFolderName}
          skillFolderDeleteModes={skillFolderDeleteModes}
          skillFolders={skillFolders}
          ungroupedSkillStats={ungroupedSkillStats}
          onCancelEditingSkillFolder={cancelEditingSkillFolder}
          onCreateSkillFolder={() => void runAction(createSkillFolderFromDraft, '创建 Skill 文件夹')}
          onDeleteSkillFolder={requestDeleteSkillFolder}
          onEditingSkillFolderNameChange={setEditingSkillFolderName}
          onNewSkillFolderNameChange={setNewSkillFolderName}
          onOpenSkillLibraryFolder={openSkillLibraryFolder}
          onSetSkillFolderDeleteMode={setSkillFolderDeleteMode}
          onStartEditingSkillFolder={startEditingSkillFolder}
          onUpdateSkillFolder={(folderId) => {
            void runAction(
              async () => updateSkillFolderFromDraft(folderId),
              '重命名 Skill 文件夹',
            );
          }}
        />
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
        <RunManagementTab
          allHistoryRunsSelected={allHistoryRunsSelected}
          artifactPreview={artifactPreview}
          busy={busy}
          collapsedRunHistoryGroups={collapsedRunHistoryGroups}
          filteredRunIds={filteredRunIds}
          filteredRuns={filteredRuns}
          formatRunDate={formatRunDate}
          isActiveRunStatus={isActiveRunStatus}
          normalizeRunStatus={normalizeRunStatus}
          onApproveRunById={approveRunById}
          onApproveSelectedRun={approveSelectedRun}
          onCancelRunById={cancelRunById}
          onCreateRun={() => void runAction(createRunFromTarget, '创建 Run')}
          onFinishRunHistoryManagement={finishRunHistoryManagement}
          onLoadMoreSelectedRunEvents={loadMoreSelectedRunEvents}
          onOpenArtifact={openArtifact}
          onOpenRunDetail={openRunDetail}
          onOpenWorkflowDesign={openWorkflowDesign}
          onPrepareSelectedRunRerun={prepareSelectedRunRerun}
          onRejectRunById={rejectRunById}
          onRejectSelectedRun={rejectSelectedRun}
          onRequestCancelSelectedRun={requestCancelSelectedRun}
          onRequestDeleteSelectedRuns={requestDeleteSelectedRuns}
          onRerunSelectedRun={rerunSelectedRun}
          onRunAction={(action, label) => void runAction(action as () => Promise<StudioRefreshOptions | void>, label)}
          onRunGoalChange={setRunGoal}
          onRunSearchQueryChange={setRunSearchQuery}
          onRunTargetChange={setRunTarget}
          onSelectRunKindFilter={selectRunKindFilter}
          onSelectRunStatusFilter={selectRunStatusFilter}
          onSetRunHistoryManagementMode={setRunHistoryManagementMode}
          onSetSelectedRunIds={setSelectedRunIds}
          onToggleRunHistoryGroup={toggleRunHistoryGroup}
          onToggleRunSelected={toggleRunSelected}
          runBulkDeleteDisabledReason={runBulkDeleteDisabledReason}
          runById={runById}
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
          runnableCapabilityLine={runnableCapabilityLine}
          runnableOptionLabel={runnableOptionLabel}
          selectedHistoryRunCount={selectedHistoryRuns.length}
          selectedPublicRunTimeline={selectedPublicRunTimeline}
          selectedRun={selectedRun}
          selectedRunApproval={selectedRunApproval}
          selectedRunArtifacts={selectedRunArtifacts}
          selectedRunAvatarUrl={selectedRunAvatarUrl}
          selectedRunExecutionEvents={selectedRunExecutionEvents}
          selectedRunId={selectedRunId}
          selectedRunIdSet={selectedRunIdSet}
          selectedRunIsLive={selectedRunIsLive}
          selectedRunReplayError={selectedRunReplayError}
          selectedRunReplayEvents={selectedRunReplayEvents}
          selectedRunReplayHasMore={selectedRunReplayHasMore}
          selectedRunReplayLoading={selectedRunReplayLoading}
          selectedRunRerunDisabledReason={selectedRunRerunDisabledReason}
          selectedRunRerunTarget={selectedRunRerunTarget}
          selectedRunTarget={selectedRunTarget}
          selectedRunWorkflow={selectedRunWorkflow}
          selectedWorkflowApprovalChildRun={selectedWorkflowApprovalChildRun}
          selectedWorkflowApprovalChildRunId={selectedWorkflowApprovalChildRunId}
          selectedWorkflowApprovalStep={selectedWorkflowApprovalStep}
          selectedWorkflowParentRun={selectedWorkflowParentRun}
          selectedWorkflowParentRunId={selectedWorkflowParentRunId}
          selectedWorkflowSteps={selectedWorkflowSteps}
          skippedWorkflowArtifactLabel={skippedWorkflowArtifactLabel}
          workflowPreview={selectedRunTarget?.kind === 'workflow' ? (
            <WorkflowRunPreview
              agents={agents}
              agentCapabilityLine={agentCapabilityLine}
              agentIssueById={agentRunIssueById}
              sourceNodes={selectedRunTargetWorkflowNodes}
              steps={selectedRunTargetWorkflowPreviewSteps}
            />
          ) : null}
          workflowRunArtifactForStep={workflowRunArtifactForStep}
          workflowStepArtifacts={workflowStepArtifacts}
          workflowStepKindLabel={workflowStepKindLabel}
          workflowStepSummary={workflowStepSummary}
        />
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
