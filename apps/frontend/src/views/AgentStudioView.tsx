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
import { useAgentDraftActions } from '../features/agent-studio/hooks/useAgentDraftActions';
import { useAgentGroupActions } from '../features/agent-studio/hooks/useAgentGroupActions';
import { useAgentGroups } from '../features/agent-studio/hooks/useAgentGroups';
import { useAgentModelTestActions } from '../features/agent-studio/hooks/useAgentModelTestActions';
import { useAgentRunReadiness } from '../features/agent-studio/hooks/useAgentRunReadiness';
import { useAgentSaveActions } from '../features/agent-studio/hooks/useAgentSaveActions';
import { useAgentSkillMountActions } from '../features/agent-studio/hooks/useAgentSkillMountActions';
import { useAgentStudioActionRunner } from '../features/agent-studio/hooks/useAgentStudioActionRunner';
import { useAgentStudioConfirmDialog } from '../features/agent-studio/hooks/useAgentStudioConfirmDialog';
import { emptyAgentDraft, useAgentStudioLocalState } from '../features/agent-studio/hooks/useAgentStudioLocalState';
import { useAgentStudioLoadLifecycle } from '../features/agent-studio/hooks/useAgentStudioLoadLifecycle';
import { useAgentStudioModelProfiles } from '../features/agent-studio/hooks/useAgentStudioModelProfiles';
import { useAgentStudioRefresh } from '../features/agent-studio/hooks/useAgentStudioRefresh';
import { useAgentStudioRunDebugControls } from '../features/agent-studio/hooks/useAgentStudioRunDebugControls';
import { useAgentStudioRunSnapshots } from '../features/agent-studio/hooks/useAgentStudioRunSnapshots';
import { useAgentStudioRouteState } from '../features/agent-studio/hooks/useAgentStudioRouteState';
import { useAgentStudioSelectionSynchronization } from '../features/agent-studio/hooks/useAgentStudioSelectionSynchronization';
import { useAgentStudioTabActions } from '../features/agent-studio/hooks/useAgentStudioTabActions';
import { useApprovedRunGuard } from '../features/agent-studio/hooks/useApprovedRunGuard';
import { useRunApprovalActions } from '../features/agent-studio/hooks/useRunApprovalActions';
import { useRunApprovalFollowup } from '../features/agent-studio/hooks/useRunApprovalFollowup';
import { useRunArtifactActions } from '../features/agent-studio/hooks/useRunArtifactActions';
import { useRunCacheActions } from '../features/agent-studio/hooks/useRunCacheActions';
import { useRunDetailSynchronization } from '../features/agent-studio/hooks/useRunDetailSynchronization';
import { useRunHistoryManagement } from '../features/agent-studio/hooks/useRunHistoryManagement';
import { useRunLaunchActions } from '../features/agent-studio/hooks/useRunLaunchActions';
import { useRunListDerivedState } from '../features/agent-studio/hooks/useRunListDerivedState';
import { useRunNavigationActions } from '../features/agent-studio/hooks/useRunNavigationActions';
import { useRunTargetReadiness } from '../features/agent-studio/hooks/useRunTargetReadiness';
import { useRuntimeMemoryManagement } from '../features/agent-studio/hooks/useRuntimeMemoryManagement';
import { useSelectedRunDetailState } from '../features/agent-studio/hooks/useSelectedRunDetailState';
import { useSkillDeletionActions } from '../features/agent-studio/hooks/useSkillDeletionActions';
import { useSkillFolderManagement } from '../features/agent-studio/hooks/useSkillFolderManagement';
import { useSkillImportActions } from '../features/agent-studio/hooks/useSkillImportActions';
import { useSkillLibraryActions } from '../features/agent-studio/hooks/useSkillLibraryActions';
import { useSkillLibraryDerivedState } from '../features/agent-studio/hooks/useSkillLibraryDerivedState';
import { useSkillSourceInputActions } from '../features/agent-studio/hooks/useSkillSourceInputActions';
import { useWorkflowDeletionActions } from '../features/agent-studio/hooks/useWorkflowDeletionActions';
import { useWorkflowDefinitions } from '../features/agent-studio/hooks/useWorkflowDefinitions';
import { useWorkflowDraftValidation } from '../features/agent-studio/hooks/useWorkflowDraftValidation';
import { useWorkflowDraftActions } from '../features/agent-studio/hooks/useWorkflowDraftActions';
import { useWorkflowRunReadiness } from '../features/agent-studio/hooks/useWorkflowRunReadiness';
import { useWorkflowSaveActions } from '../features/agent-studio/hooks/useWorkflowSaveActions';
import { useWorkflowCanvasActions } from '../features/agent-studio/hooks/useWorkflowCanvasActions';
import {
  agentCapabilityLine,
  runnableCapabilityLine,
  runnableOptionLabel,
} from '../features/agent-studio/utils/agents';
import {
  formatRunDate,
  isActiveRunStatus,
  normalizeRunStatus,
  runHistoryGroupSummary,
  runKindLabel,
  runStatusLabel,
  runStatusTone,
} from '../features/agent-studio/utils/runs';
import {
  skippedWorkflowArtifactLabel,
  workflowRunArtifactForStep,
  workflowStepArtifacts,
  workflowStepKindLabel,
  workflowStepSummary,
} from '../features/agent-studio/utils/workflow';
import { openAppView } from '../lib/bridge';

export function AgentStudioView() {
  const {
    runGoal,
    runTarget,
    selectedRouteGroupRunId,
    selectedRunId,
    setRunGoal,
    setRunTarget,
    setSelectedRunId,
    setTab,
    tab,
  } = useAgentStudioRouteState();
  const {
    agentRunGoal, artifactPreview, busyAction, collapsedRunHistoryGroups, draft,
    editingSkillFolderId, editingSkillFolderName, edges, error, futureTasks, loading, memories,
    modelDefaults, modelProfiles, newSkillFolderName, nodes, onEdgesChange, onNodesChange,
    runDetailCache, runGroups,
    runKindFilter, runSearchQuery, runStatusFilter, runnables, runs, selectedSkillIds,
    setAgentRunGoal, setArtifactPreview, setBusyAction, setCollapsedRunHistoryGroups,
    setDraft, setEditingSkillFolderId, setEditingSkillFolderName, setEdges, setError, setFutureTasks,
    setLoading, setMemories, setModelDefaults, setModelProfiles, setNewSkillFolderName, setNodes,
    setRunDetailCache, setRunGroups, setRunKindFilter, setRunSearchQuery, setRunStatusFilter,
    setRunnables, setRuns, setSelectedSkillIds, setSkillFolderDeleteModes, setSkillFolders,
    setSkillImportResults, setSkillInstallCommand, setSkillLibraryFilter,
    setSkillLibraryFolderFilter, setSkillLibrarySearch, setSkillManagementMode,
    setSkillMountFilter, setSkillMountFolderFilter, setSkillMountSearch, setSkillSources,
    setSkillTargetFolderId, setSkills, setStatus, setWorkflowDescription, setWorkflowEnabled,
    setWorkflowName, setWorkflowRunGoal, skillFolderDeleteModes, skillFolders,
    skillImportResults, skillInstallCommand, skillLibraryFilter, skillLibraryFolderFilter,
    skillLibrarySearch, skillManagementMode, skillMountFilter, skillMountFolderFilter,
    skillMountSearch, skillSources, skillTargetFolderId, skills, status, workflowDescription,
    workflowEnabled, workflowName, workflowRunGoal,
  } = useAgentStudioLocalState();
  const busy = loading || Boolean(busyAction);
  const installingSkill = busyAction === '安装 Skill';
  const {
    closeConfirmDialog,
    confirmCurrentDialog,
    confirmDialog,
    showConfirmDialog,
  } = useAgentStudioConfirmDialog();
  const {
    agentGroups,
    agentGroupDefaultModel,
    agentGroupDescription,
    agentGroupEnabled,
    agentGroupMemoryScope,
    agentGroupMemberIds,
    agentGroupMode,
    agentGroupModeratorId,
    agentGroupName,
    agentGroupRunGoal,
    agentGroupToolPolicyId,
    latestAgentGroupRun,
    loadAgentGroups,
    runAgentGroup,
    saveAgentGroupDraft,
    selectAgentGroup,
    selectedAgentGroup,
    selectedAgentGroupId,
    setAgentGroupDefaultModel,
    setAgentGroupDescription,
    setAgentGroupEnabled,
    setAgentGroupMemoryScope,
    setAgentGroupMode,
    setAgentGroupModeratorId,
    setAgentGroupName,
    setAgentGroupRunGoal,
    setAgentGroupToolPolicyId,
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
    mergeAgent,
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
    mergeWorkflow,
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
  const { runAction } = useAgentStudioActionRunner({
    refresh,
    setBusyAction,
    setError,
    setStatus,
  });

  const { chatModelProfiles, visionModelProfiles } = useAgentStudioModelProfiles(modelProfiles);
  const {
    workflowErrors,
    workflowNameError,
    workflowValidation,
  } = useWorkflowDraftValidation({
    agents,
    edges,
    nodes,
    selectedWorkflowId: selectedWorkflow?.workflow_id || '',
    workflowName,
    workflows,
  });
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
    mergeWorkflow,
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
    connectFlowNodes,
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
  const {
    clearRunEventReplay,
    loadMoreGroupRunReplayEvents,
    loadMoreRunReplayEvents,
    selectedGroupRunSnapshotId,
    selectedGroupRunReplayError,
    selectedGroupRunReplayEvents,
    selectedGroupRunReplayHasMore,
    selectedGroupRunReplayLoading,
    selectedGroupRunReplayNextAfterSequence,
    selectedGroupRunSnapshot,
    selectedPublicRunTimeline,
    selectedRunReplayError,
    selectedRunReplayEvents,
    selectedRunReplayHasMore,
    selectedRunReplayLoading,
    selectedRunReplayState,
  } = useAgentStudioRunSnapshots({
    selectedRouteGroupRunId,
    selectedRun,
    selectedRunId,
    selectedRunReplayRefreshKey,
  });
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
    selectedRunGroup,
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
    selectedRouteGroupRunId,
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
    resetAgentDraft,
    selectAgent,
    startNewAgent,
  } = useAgentDraftActions({
    emptyAgentDraft,
    mergeAgent,
    setDraft,
    setError,
    setSelectedAgentId,
    setStatus,
  });
  const {
    finishSkillManagement,
    moveSkillFolder,
    openSkillLocation,
    toggleSkillEnabled,
    toggleSkillSelected,
  } = useSkillLibraryActions({
    runAction,
    setSelectedSkillIds,
    setSkillManagementMode,
  });
  const {
    requestDeleteAgent,
    requestDeleteSelectedAgents,
  } = useAgentDeletionActions({
    draftAgentId: draft.agent_id || '',
    draftAgentName: draft.name,
    resetAgentDraft,
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
  const { testAgentModel } = useAgentModelTestActions({
    draftAgentId: draft.agent_id || '',
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
    loadMoreSelectedGroupRunEvents,
  } = useAgentStudioRunDebugControls({
    cancelSelectedRun,
    loadMoreGroupRunReplayEvents,
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

  useRunDetailSynchronization({
    activeRunPollKey,
    refreshRunGroupById,
    refreshRunGroupsForRuns,
    runById,
    runGroups,
    selectedRun,
    selectedRouteGroupRunId,
    selectedRunId,
    selectedWorkflowApprovalChildRunId,
    selectedWorkflowChildRefs,
    selectedWorkflowParentRunId,
    setArtifactPreview,
    upsertRunDetailCache,
  });
  useAgentStudioSelectionSynchronization({
    filteredLibrarySkillIds,
    filteredRunIds,
    selectedAgent,
    selectedWorkflow,
    setDraft,
    setEdges,
    setNodes,
    setSelectedRunIds,
    setSelectedSkillIds,
    setWorkflowDescription,
    setWorkflowEnabled,
    setWorkflowName,
  });
  useAgentStudioLoadLifecycle({
    agentCount: agents.length,
    busyAction,
    draftAgentId: draft.agent_id || '',
    loading,
    refresh,
    selectedAgentId,
    setError,
    setLoading,
    tab,
  });
  const { activateTab } = useAgentStudioTabActions({
    refresh,
    setError,
    setStatus,
    setTab,
  });

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
          agentGroupDefaultModel={agentGroupDefaultModel}
          agentGroupDescription={agentGroupDescription}
          agentGroupEnabled={agentGroupEnabled}
          agentGroupMemoryScope={agentGroupMemoryScope || 'shared'}
          agentGroupMemberIds={agentGroupMemberIds}
          agentGroupMode={agentGroupMode || 'moderated'}
          agentGroupModeratorId={agentGroupModeratorId}
          agentGroupName={agentGroupName}
          agentGroupRunGoal={agentGroupRunGoal}
          agentGroupToolPolicyId={agentGroupToolPolicyId}
          busy={busy}
          latestAgentGroupRun={latestAgentGroupRun}
          selectedAgentGroup={selectedAgentGroup}
          selectedAgentGroupId={selectedAgentGroupId}
          onAgentGroupDefaultModelChange={setAgentGroupDefaultModel}
          onAgentGroupDescriptionChange={setAgentGroupDescription}
          onAgentGroupEnabledChange={setAgentGroupEnabled}
          onAgentGroupMemoryScopeChange={setAgentGroupMemoryScope}
          onAgentGroupModeChange={setAgentGroupMode}
          onAgentGroupModeratorChange={setAgentGroupModeratorId}
          onAgentGroupNameChange={setAgentGroupName}
          onAgentGroupRunGoalChange={setAgentGroupRunGoal}
          onAgentGroupToolPolicyIdChange={setAgentGroupToolPolicyId}
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
          onTestAgentModel={() => void runAction(testAgentModel, '测试模型')}
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
          onMoveSkillFolder={moveSkillFolder}
          onOpenSkillLocation={openSkillLocation}
          onPickSkillSources={() => void pickSkillSources()}
          onSetSelectedSkillIds={setSelectedSkillIds}
          onSetSkillInstallCommand={setSkillInstallCommand}
          onSetSkillLibraryFilter={setSkillLibraryFilter}
          onSetSkillLibraryFolderFilter={setSkillLibraryFolderFilter}
          onSetSkillLibrarySearch={setSkillLibrarySearch}
          onSetSkillManagementMode={setSkillManagementMode}
          onSetSkillTargetFolderId={setSkillTargetFolderId}
          onSyncNativeSkillLibrary={() => void runAction(syncNativeSkillLibrary, '同步 Native Skills')}
          onToggleSkillEnabled={toggleSkillEnabled}
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
          onConnect={connectFlowNodes}
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
          onLoadMoreSelectedGroupRunEvents={loadMoreSelectedGroupRunEvents}
          onOpenArtifact={openArtifact}
          onOpenRunDetail={openRunDetail}
          onOpenWorkflowDesign={openWorkflowDesign}
          onPrepareSelectedRunRerun={prepareSelectedRunRerun}
          onRejectRunById={rejectRunById}
          onRejectSelectedRun={rejectSelectedRun}
          onRequestCancelSelectedRun={requestCancelSelectedRun}
          onRequestDeleteSelectedRuns={requestDeleteSelectedRuns}
          onRerunSelectedRun={rerunSelectedRun}
          onRunAction={(action, label) => void runAction(action, label)}
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
          selectedGroupRunReplayError={selectedGroupRunReplayError}
          selectedGroupRunReplayEvents={selectedGroupRunReplayEvents}
          selectedGroupRunReplayHasMore={selectedGroupRunReplayHasMore}
          selectedGroupRunReplayLoading={selectedGroupRunReplayLoading}
          selectedGroupRunReplayNextAfterSequence={selectedGroupRunReplayNextAfterSequence}
          selectedGroupRunSnapshot={selectedGroupRunSnapshot}
          selectedPublicRunTimeline={selectedPublicRunTimeline}
          selectedRouteGroupRunId={selectedRouteGroupRunId}
          selectedRun={selectedRun}
          selectedRunApproval={selectedRunApproval}
          selectedRunArtifacts={selectedRunArtifacts}
          selectedRunAvatarUrl={selectedRunAvatarUrl}
          selectedRunExecutionEvents={selectedRunExecutionEvents}
          selectedRunGroup={selectedRunGroup}
          selectedRunId={selectedRunId}
          selectedRunIdSet={selectedRunIdSet}
          selectedRunIsLive={selectedRunIsLive}
          selectedRunReplayError={selectedRunReplayError}
          selectedRunReplayEvents={selectedRunReplayEvents}
          selectedRunReplayHasMore={selectedRunReplayHasMore}
          selectedRunReplayLoading={selectedRunReplayLoading}
          selectedRunReplayNextAfterSequence={selectedRunReplayState?.nextAfterSequence ?? 0}
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
