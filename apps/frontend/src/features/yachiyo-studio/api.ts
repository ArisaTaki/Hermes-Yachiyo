import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/bridge';
import type {
  AgentDefinitionSnapshot,
  AgentGroupSnapshot,
  GroupRunSnapshot,
  MemorySnapshot,
  RunTimelineSnapshot,
  SaveAgentGroupRequest,
  SkillFolderSnapshot,
  SkillSnapshot,
  SkillSourceRootSnapshot,
} from './types';

export async function listYachiyoStudioAgents(): Promise<AgentDefinitionSnapshot[]> {
  const payload = await apiGet<{ agents?: AgentDefinitionSnapshot[] }>('/yachiyo/studio/agents');
  return payload.agents || [];
}

export async function saveYachiyoStudioAgent(
  request: Partial<AgentDefinitionSnapshot>,
): Promise<AgentDefinitionSnapshot> {
  return apiPost('/yachiyo/studio/agents', request);
}

export async function deleteYachiyoStudioAgent(agentId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}`);
}

export async function listYachiyoSkills(): Promise<SkillSnapshot[]> {
  const payload = await apiGet<{ skills?: SkillSnapshot[] }>('/yachiyo/studio/skills');
  return payload.skills || [];
}

export async function updateYachiyoSkill(
  skillId: string,
  request: Partial<SkillSnapshot>,
): Promise<SkillSnapshot> {
  return apiPatch(`/yachiyo/studio/skills/${encodeURIComponent(skillId)}`, request);
}

export async function deleteYachiyoSkill(skillId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/yachiyo/studio/skills/${encodeURIComponent(skillId)}`);
}

export async function listYachiyoSkillFolders(): Promise<SkillFolderSnapshot[]> {
  const payload = await apiGet<{ folders?: SkillFolderSnapshot[] }>('/yachiyo/studio/skill-folders');
  return payload.folders || [];
}

export async function createYachiyoSkillFolder(
  request: Partial<SkillFolderSnapshot>,
): Promise<SkillFolderSnapshot> {
  return apiPost('/yachiyo/studio/skill-folders', request);
}

export async function updateYachiyoSkillFolder(
  folderId: string,
  request: Partial<SkillFolderSnapshot>,
): Promise<SkillFolderSnapshot> {
  return apiPatch(`/yachiyo/studio/skill-folders/${encodeURIComponent(folderId)}`, request);
}

export async function deleteYachiyoSkillFolder(
  folderId: string,
  options: { deleteSkills?: boolean } = {},
): Promise<{ ok?: boolean; deleted_skill_count?: number }> {
  const query = options.deleteSkills ? '?delete_skills=true' : '';
  return apiDelete(`/yachiyo/studio/skill-folders/${encodeURIComponent(folderId)}${query}`);
}

export async function listYachiyoSkillSources(): Promise<SkillSourceRootSnapshot[]> {
  const payload = await apiGet<{ roots?: SkillSourceRootSnapshot[] }>('/yachiyo/studio/skills/sources');
  return payload.roots || [];
}

export async function importYachiyoSkill(
  sourcePath: string,
  folderId?: string,
): Promise<SkillSnapshot> {
  return apiPost('/yachiyo/studio/skills/import', {
    source_path: sourcePath,
    folder_id: folderId || undefined,
  });
}

export async function syncYachiyoNativeSkills(): Promise<{ ok?: boolean }> {
  return apiPost('/yachiyo/studio/skills/sync', {});
}

export async function installYachiyoSkillCommand(
  command: string,
  folderId?: string,
): Promise<{ ok?: boolean }> {
  return apiPost('/yachiyo/studio/skills/install', {
    command,
    folder_id: folderId || undefined,
  });
}

export async function listYachiyoMemories(
  includeDeleted = false,
  limit = 100,
): Promise<MemorySnapshot[]> {
  const query = new URLSearchParams({
    include_deleted: String(includeDeleted),
    limit: String(Math.max(1, Math.min(500, limit))),
  });
  const payload = await apiGet<{ memories?: MemorySnapshot[] }>(`/yachiyo/studio/memories?${query.toString()}`);
  return payload.memories || [];
}

export async function createYachiyoMemory(
  request: Partial<MemorySnapshot>,
): Promise<MemorySnapshot> {
  return apiPost('/yachiyo/studio/memories', request);
}

export async function updateYachiyoMemory(
  memoryId: string,
  request: Partial<MemorySnapshot> & { old_content?: string },
): Promise<MemorySnapshot> {
  return apiPatch(`/yachiyo/studio/memories/${encodeURIComponent(memoryId)}`, request);
}

export async function deleteYachiyoMemory(
  memoryId: string,
  reason = '',
): Promise<{ ok?: boolean }> {
  const query = reason ? `?reason=${encodeURIComponent(reason)}` : '';
  return apiDelete(`/yachiyo/studio/memories/${encodeURIComponent(memoryId)}${query}`);
}

export async function listYachiyoAgentGroups(): Promise<AgentGroupSnapshot[]> {
  const payload = await apiGet<{ groups?: AgentGroupSnapshot[] }>('/yachiyo/studio/groups');
  return payload.groups || [];
}

export async function getYachiyoAgentGroup(groupId: string): Promise<AgentGroupSnapshot> {
  return apiGet(`/yachiyo/studio/groups/${encodeURIComponent(groupId)}`);
}

export async function saveYachiyoAgentGroup(
  request: SaveAgentGroupRequest,
): Promise<AgentGroupSnapshot> {
  return apiPost('/yachiyo/studio/groups', request);
}

export async function startYachiyoGroupRun(
  groupId: string,
  objective: string,
  title?: string,
): Promise<GroupRunSnapshot> {
  const clientRunId = createClientRunId();
  return apiPost(`/yachiyo/studio/groups/${encodeURIComponent(groupId)}/runs`, {
    objective,
    title: title || undefined,
    client_run_id: clientRunId,
  });
}

export async function listYachiyoGroupRuns(limit = 50): Promise<GroupRunSnapshot[]> {
  const query = new URLSearchParams({ limit: String(Math.max(1, Math.min(200, limit))) });
  const payload = await apiGet<{ group_runs?: GroupRunSnapshot[] }>(`/yachiyo/studio/group-runs?${query.toString()}`);
  return payload.group_runs || [];
}

export async function getYachiyoGroupRun(groupRunId: string): Promise<GroupRunSnapshot> {
  return apiGet(`/yachiyo/studio/group-runs/${encodeURIComponent(groupRunId)}`);
}

export async function getYachiyoRunTimeline(runId: string): Promise<RunTimelineSnapshot> {
  return apiGet(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/timeline`);
}

export async function startYachiyoWorkflowRun(
  workflowId: string,
  objective: string,
  title?: string,
): Promise<RunTimelineSnapshot> {
  const clientRunId = createClientRunId();
  return apiPost(`/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}/runs`, {
    objective,
    title: title || undefined,
    client_run_id: clientRunId,
  });
}

export async function deleteYachiyoWorkflow(workflowId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}`);
}

function createClientRunId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
