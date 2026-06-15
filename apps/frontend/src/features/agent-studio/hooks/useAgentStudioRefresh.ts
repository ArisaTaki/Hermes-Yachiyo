import { useCallback, type Dispatch, type SetStateAction } from 'react';

import { listModelProfiles, type ModelProfile, type ModelProfileDefaults } from '../../../lib/modelProfiles';
import type {
  AgentSpec,
  FutureTaskSpec,
  MemorySpec,
  RunnableSummary,
  RunGroupSpec,
  RunSpec,
  SkillFolderSpec,
  SkillSourceRoot,
  SkillSpec,
  WorkflowSpec,
} from '../types';
import {
  listStudioAgentsForView,
  listStudioFutureTasksForView,
  listStudioMemoriesForView,
  listStudioRunGroupsForView,
  listStudioRunsForView,
  listStudioSkillFoldersForView,
  listStudioSkillsForView,
  listStudioSkillSourcesForView,
  listStudioWorkflowsForView,
  studioRunnablesForView,
} from '../utils/studioData';

export type StudioRefreshOptions = {
  selectedAgentId?: string;
  selectFirstAgent?: boolean;
  selectedWorkflowId?: string;
  selectFirstWorkflow?: boolean;
  runTarget?: string;
  selectedRunId?: string;
  statusMessage?: string;
  skipRefresh?: boolean;
};

type UseAgentStudioRefreshOptions = {
  applyAgents: (nextAgents: AgentSpec[], options?: StudioRefreshOptions) => void;
  applyWorkflows: (nextWorkflows: WorkflowSpec[], options?: StudioRefreshOptions) => void;
  loadAgentGroups: () => Promise<unknown>;
  setFutureTasks: (nextFutureTasks: FutureTaskSpec[]) => void;
  setMemories: (nextMemories: MemorySpec[]) => void;
  setModelDefaults: (nextDefaults: ModelProfileDefaults) => void;
  setModelProfiles: (nextProfiles: ModelProfile[]) => void;
  setRunnables: (nextRunnables: RunnableSummary[]) => void;
  setRunGroups: (nextRunGroups: RunGroupSpec[]) => void;
  setRuns: (nextRuns: RunSpec[]) => void;
  setRunTarget: Dispatch<SetStateAction<string>>;
  setSelectedRunId: Dispatch<SetStateAction<string>>;
  setSkillFolders: (nextFolders: SkillFolderSpec[]) => void;
  setSkillSources: (nextSources: SkillSourceRoot[]) => void;
  setSkills: (nextSkills: SkillSpec[]) => void;
};

export function useAgentStudioRefresh({
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
}: UseAgentStudioRefreshOptions) {
  return useCallback(async (options: StudioRefreshOptions = {}) => {
    const [
      nextAgents,
      nextSkills,
      nextProfiles,
      nextWorkflows,
      ,
      nextRuns,
      nextRunGroups,
      nextSkillSources,
      nextSkillFolders,
      nextMemories,
      nextFutureTasks,
    ] = await Promise.all([
      listStudioAgentsForView(),
      listStudioSkillsForView(),
      listModelProfiles(),
      listStudioWorkflowsForView(),
      loadAgentGroups(),
      listStudioRunsForView(),
      listStudioRunGroupsForView(),
      listStudioSkillSourcesForView(),
      listStudioSkillFoldersForView(),
      listStudioMemoriesForView(),
      listStudioFutureTasksForView(),
    ]);
    applyAgents(nextAgents, options);
    setSkills(nextSkills);
    setSkillSources(nextSkillSources);
    setSkillFolders(nextSkillFolders);
    setModelProfiles(nextProfiles.profiles || []);
    setModelDefaults(nextProfiles.defaults || {});
    applyWorkflows(nextWorkflows, options);
    const nextRunnables = studioRunnablesForView(nextAgents, nextWorkflows);
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
  }, [
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
  ]);
}
