import type {
  AgentSpec,
  MemorySpec,
  RunGroupSpec,
  RunSpec,
  SkillFolderSpec,
  SkillSourceRoot,
  SkillSpec,
  WorkflowSpec,
} from '../../../lib/agents';
import {
  getYachiyoRunTimeline,
  listYachiyoAgentGroups,
  listYachiyoGroupRuns,
  listYachiyoMemories,
  listYachiyoRunTimelines,
  listYachiyoSkillFolders,
  listYachiyoSkills,
  listYachiyoSkillSources,
  listYachiyoStudioAgents,
  listYachiyoWorkflows,
} from '../../yachiyo-studio/api';
import type { AgentGroupSnapshot } from '../../yachiyo-studio/types';
import { publicAgentToAgentSpec } from './agents';
import { publicGroupRunToRunGroupSpec, publicRunTimelineToRunSpec } from './runs';
import {
  publicSkillFolderToSkillFolderSpec,
  publicSkillSourceRootToSkillSourceRoot,
  publicSkillToSkillSpec,
} from './skills';
import { publicWorkflowToWorkflowSpec } from './workflow';

export async function listStudioAgentsForView(): Promise<AgentSpec[]> {
  return (await listYachiyoStudioAgents()).map(publicAgentToAgentSpec);
}

export async function listStudioSkillsForView(): Promise<SkillSpec[]> {
  return (await listYachiyoSkills()).map(publicSkillToSkillSpec);
}

export async function listStudioSkillFoldersForView(): Promise<SkillFolderSpec[]> {
  return (await listYachiyoSkillFolders()).map(publicSkillFolderToSkillFolderSpec);
}

export async function listStudioSkillSourcesForView(): Promise<SkillSourceRoot[]> {
  return (await listYachiyoSkillSources()).map(publicSkillSourceRootToSkillSourceRoot);
}

export async function listStudioWorkflowsForView(): Promise<WorkflowSpec[]> {
  return (await listYachiyoWorkflows()).map(publicWorkflowToWorkflowSpec);
}

export async function listStudioMemoriesForView(): Promise<MemorySpec[]> {
  return (await listYachiyoMemories()).map((memory) => ({
    memory_id: memory.memory_id,
    scope: memory.scope,
    kind: memory.kind,
    content: memory.content,
    source_session_id: memory.source_session_id || undefined,
    source_message_id: memory.source_message_id || undefined,
    source_task_id: memory.source_task_id || undefined,
    source_run_id: memory.source_run_id || undefined,
    confidence: memory.confidence,
    pinned: memory.pinned,
    user_confirmed: memory.user_confirmed,
    created_at: memory.created_at,
    updated_at: memory.updated_at,
    deleted_at: memory.deleted_at || undefined,
  }));
}

export async function listStudioGroupsForView(): Promise<AgentGroupSnapshot[]> {
  return listYachiyoAgentGroups();
}

export async function listStudioRunsForView(): Promise<RunSpec[]> {
  return (await listYachiyoRunTimelines()).map((snapshot) => publicRunTimelineToRunSpec(snapshot));
}

export async function listStudioRunGroupsForView(): Promise<RunGroupSpec[]> {
  return (await listYachiyoGroupRuns()).map(publicGroupRunToRunGroupSpec);
}

export async function getStudioRunForView(runId: string): Promise<RunSpec> {
  return publicRunTimelineToRunSpec(await getYachiyoRunTimeline(runId));
}
