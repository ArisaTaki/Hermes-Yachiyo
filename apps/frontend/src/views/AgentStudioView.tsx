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
import { useAgentGroupActions } from '../features/agent-studio/hooks/useAgentGroupActions';
import { useAgentGroups } from '../features/agent-studio/hooks/useAgentGroups';
import { useAgentRunReadiness } from '../features/agent-studio/hooks/useAgentRunReadiness';
import { useAgentSaveActions } from '../features/agent-studio/hooks/useAgentSaveActions';
import { useAgentSkillMountActions } from '../features/agent-studio/hooks/useAgentSkillMountActions';
import { useAgentStudioRefresh, type StudioRefreshOptions } from '../features/agent-studio/hooks/useAgentStudioRefresh';
import { useApprovedRunGuard } from '../features/agent-studio/hooks/useApprovedRunGuard';
import { useRunApprovalActions } from '../features/agent-studio/hooks/useRunApprovalActions';
import { useRunApprovalFollowup } from '../features/agent-studio/hooks/useRunApprovalFollowup';
import { useRunArtifactActions } from '../features/agent-studio/hooks/useRunArtifactActions';
import { useRunCacheActions } from '../features/agent-studio/hooks/useRunCacheActions';
import { useRunDebugActions } from '../features/agent-studio/hooks/useRunDebugActions';
import { useRunEventReplay } from '../features/agent-studio/hooks/useRunEventReplay';
import { useRunHistoryManagement } from '../features/agent-studio/hooks/useRunHistoryManagement';
import { useRunLaunchActions } from '../features/agent-studio/hooks/useRunLaunchActions';
import { useRunListDerivedState } from '../features/agent-studio/hooks/useRunListDerivedState';
import { useRunNavigationActions } from '../features/agent-studio/hooks/useRunNavigationActions';
import { useRunTargetReadiness } from '../features/agent-studio/hooks/useRunTargetReadiness';
import { useRunTimeline } from '../features/agent-studio/hooks/useRunTimeline';
import { useRuntimeMemoryManagement } from '../features/agent-studio/hooks/useRuntimeMemoryManagement';
import { useSelectedRunDetailState } from '../features/agent-studio/hooks/useSelectedRunDetailState';
import { useSkillDeletionActions } from '../features/agent-studio/hooks/useSkillDeletionActions';
import { useSkillFolderManagement } from '../features/agent-studio/hooks/useSkillFolderManagement';
import { useSkillImportActions } from '../features/agent-studio/hooks/useSkillImportActions';
import { useSkillLibraryDerivedState } from '../features/agent-studio/hooks/useSkillLibraryDerivedState';
import { useSkillSourceInputActions } from '../features/agent-studio/hooks/useSkillSourceInputActions';
import { useWorkflowDeletionActions } from '../features/agent-studio/hooks/useWorkflowDeletionActions';
import { useWorkflowDefinitions } from '../features/agent-studio/hooks/useWorkflowDefinitions';
import { useWorkflowDraftActions } from '../features/agent-studio/hooks/useWorkflowDraftActions';
import { useWorkflowRunReadiness } from '../features/agent-studio/hooks/useWorkflowRunReadiness';
import { useWorkflowSaveActions } from '../features/agent-studio/hooks/useWorkflowSaveActions';
import { useWorkflowCanvasActions } from '../features/agent-studio/hooks/useWorkflowCanvasActions';
import {
  normalizeStudioTab,
  type StudioTab,
} from '../features/agent-studio/studioTabs';
import {
  agentCapabilityLine,
  agentToDraft,
  runnableCapabilityLine,
  runnableOptionLabel,
} from '../features/agent-studio/utils/agents';
import {
  formatRunDate,
  isActiveRunStatus,
  isPotentialWorkflowChildAgentRun,
  normalizeRunStatus,
  runHistoryGroupSummary,
  runKindLabel,
  runStatusLabel,
  runStatusTone,
  type RunKindFilter,
  type RunStatusFilter,
} from '../features/agent-studio/utils/runs';
import {
  type SkillFolderFilter,
  type SkillImportResult,
  type SkillSourceFilter,
} from '../features/agent-studio/utils/skills';
import type { AgentDraft } from '../features/agent-studio/types';
import {
  skippedWorkflowArtifactLabel,
  starterNodes,
  validateWorkflowDraft,
  workflowEdges,
  workflowNodes,
  workflowRunArtifactForStep,
  workflowStepArtifacts,
  workflowStepKindLabel,
  workflowStepSummary,
} from '../features/agent-studio/utils/workflow';
import {
  testYachiyoStudioAgentModel,
  updateYachiyoSkill,
} from '../features/yachiyo-studio/api';
import { getStudioRunForView } from '../features/agent-studio/utils/studioData';
import type {
  FutureTaskSpec,
  MemorySpec,
  RunnableSummary,
  RunGroupSpec,
  RunSpec,
  SkillFolderSpec,
  SkillSourceRoot,
  SkillSpec,
} from '../features/agent-studio/types';
import { openAppView, openPath } from '../lib/bridge';
import type { ModelProfile, ModelProfileDefaults } from '../lib/modelProfiles';
import { currentParam, navigateTo } from '../lib/view';

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
  const {
    agentRunIssueById,
    workflowHasErrors,
    workflowPrimaryError,
    workflowRunDisabled,
    workflowRunDisabledReason,
    workflowRunPreviewSteps,
  } = useWorkflowRunReadiness({
    agents,
    busy,
    chatModelProfiles,
    edges,
    modelDefaults,
    nodes,
    selectedWorkflow,
    skills,
    workflowDescription,
    workflowEnabled,
    workflowErrors,
    workflowName,
    workflowNameError,
    workflowRunGoal,
  });
  const {
    filteredRunIds,
    filteredRuns,
    runById,
    runFilterCounts,
    runHistoryGroups,
    runSearchActive,
    runStatusFilterCounts,
    runStatusFilteredRuns,
    selectedRun,
    selectedRunReplayRefreshKey,
  } = useRunListDerivedState({
    agents,
    runDetailCache,
    runKindFilter,
    runSearchQuery,
    runs,
    runStatusFilter,
    runnables,
    selectedRunId,
    workflows,
  });
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
  const {
    activeRunPollKey,
    selectedRunApproval,
    selectedRunArtifacts,
    selectedRunAvatarUrl,
    selectedRunExecutionEvents,
    selectedRunIsLive,
    selectedRunRerunDisabledReason,
    selectedRunRerunTarget,
    selectedRunWorkflow,
    selectedWorkflowApprovalChildRun,
    selectedWorkflowApprovalChildRunId,
    selectedWorkflowApprovalStep,
    selectedWorkflowChildRefs,
    selectedWorkflowParentRun,
    selectedWorkflowParentRunId,
    selectedWorkflowSteps,
  } = useSelectedRunDetailState({
    agentRunIssueById,
    agents,
    runById,
    runGroups,
    runnables,
    selectedPublicRunTimeline,
    selectedRun,
    selectedRunId,
    selectedRunReplayEvents,
    workflows,
  });
  const {
    runTargetDisabledReason,
    selectedRunTarget,
    selectedRunTargetWorkflowEdges,
    selectedRunTargetWorkflowNodes,
    selectedRunTargetWorkflowPreviewSteps,
    selectedRunTargetWorkflowValidation,
  } = useRunTargetReadiness({
    agentRunIssueById,
    agents,
    runTarget,
    runnables,
    workflows,
  });
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
    runCurrentAgentGroup,
    saveAgentGroup,
  } = useAgentGroupActions({
    openRunDetail,
    runAgentGroup,
    saveAgentGroupDraft,
    selectedAgentGroupId,
    setRunTarget,
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
  const {
    allLibrarySkillsSelected,
    disabledMountedSkills,
    editingSkillFolderError,
    filteredLibrarySkillIds,
    filteredLibrarySkills,
    filteredMountSkills,
    installedSkillCount,
    mountedSkillCount,
    nativeSkillCount,
    newSkillFolderError,
    selectedLibrarySkills,
    selectedSkillIdSet,
    ungroupedSkillStats,
    visibleMountedCount,
    visibleMountSkillIds,
  } = useSkillLibraryDerivedState({
    editingSkillFolderId,
    editingSkillFolderName,
    newSkillFolderName,
    selectedAgent,
    selectedSkillIds,
    skillFolders,
    skillLibraryFilter,
    skillLibraryFolderFilter,
    skillLibrarySearch,
    skillMountFilter,
    skillMountFolderFilter,
    skillMountSearch,
    skills,
  });
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
  const {
    agentQuickRunDisabled,
    agentQuickRunDisabledReason,
    agentReadinessNotices,
  } = useAgentRunReadiness({
    agentRunGoal,
    busy,
    chatModelProfiles,
    disabledMountedSkills,
    draft,
    selectedAgent,
    selectedAgentReadOnly,
  });
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

  const refresh = useAgentStudioRefresh({
    applyAgents,
    applyWorkflows,
    loadAgentGroups,
    setFutureTasks,
    setMemories,
    setModelDefaults,
    setModelProfiles,
    setRunnables,
    setRunGroups,
    setRuns,
    setRunTarget,
    setSelectedRunId,
    setSkillFolders,
    setSkillSources,
    setSkills,
  });

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
    getStudioRunForView(selectedRunId)
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
    getStudioRunForView(selectedWorkflowParentRunId)
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
    Promise.all(uniqueChildRunIds.map((runId) => getStudioRunForView(runId).catch(() => null)))
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
        const loadedRuns = (await Promise.all(pollRunIds.map((runId) => getStudioRunForView(runId).catch(() => null))))
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
            const result = await testYachiyoStudioAgentModel(draft.agent_id || '');
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
            await updateYachiyoSkill(skill.skill_id, { folder_id: folderId });
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
            await updateYachiyoSkill(skill.skill_id, { enabled: skill.enabled === false });
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
