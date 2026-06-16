import { apiDelete, apiGet, apiPatch, apiPost } from '../../lib/bridge';
import type {
  AgentDefinitionSnapshot,
  AgentGroupSnapshot,
  ArtifactContentSnapshot,
  FutureTaskSnapshot,
  FutureTaskTriggerResultSnapshot,
  GroupRunSnapshot,
  MemorySnapshot,
  RunEventPageSnapshot,
  SaveAgentGroupRequest,
  SkillFolderSnapshot,
  SkillSnapshot,
  SkillSourceRootSnapshot,
  WorkflowRunSnapshot,
  WorkflowSnapshot,
  YachiyoRunTimelineSnapshot,
} from './types';

export type YachiyoRunEventsPage = RunEventPageSnapshot;

export type YachiyoRunArtifactPayload = ArtifactContentSnapshot;

export type YachiyoSkillSyncResult = {
  source?: string;
  source_type?: string;
  source_ref?: string;
  status: 'imported' | 'updated' | 'skipped' | 'failed' | string;
  skill_id?: string;
  name?: string;
  message?: string;
};

export type YachiyoSkillSyncResponse = {
  ok?: boolean;
  roots?: SkillSourceRootSnapshot[];
  summary?: Record<string, number>;
  results?: YachiyoSkillSyncResult[];
};

export type YachiyoSkillInstallResponse = {
  ok?: boolean;
  installer?: string;
  command?: string[];
  started_at?: string;
  finished_at?: string;
  returncode?: number;
  stdout?: string;
  stderr?: string;
  sync?: YachiyoSkillSyncResponse | null;
};

export async function listYachiyoStudioAgents(): Promise<AgentDefinitionSnapshot[]> {
  const payload = await apiGet<{ agents?: AgentDefinitionSnapshot[] }>('/yachiyo/studio/agents');
  return payload.agents || [];
}

export async function getYachiyoStudioAgent(agentId: string): Promise<AgentDefinitionSnapshot> {
  return apiGet(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}`);
}

export async function saveYachiyoStudioAgent(
  request: Partial<AgentDefinitionSnapshot>,
): Promise<AgentDefinitionSnapshot> {
  return apiPost('/yachiyo/studio/agents', request);
}

export async function deleteYachiyoStudioAgent(agentId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}`);
}

export async function testYachiyoStudioAgentModel(
  agentId: string,
): Promise<{ ok?: boolean; message?: string; missing?: string[] }> {
  return apiPost(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}/test-model`, {});
}

export async function attachYachiyoAgentSkill(
  agentId: string,
  skillId: string,
): Promise<AgentDefinitionSnapshot> {
  return apiPost(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}/skills`, {
    skill_id: skillId,
  });
}

export async function detachYachiyoAgentSkill(
  agentId: string,
  skillId: string,
): Promise<AgentDefinitionSnapshot> {
  return apiDelete(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}`);
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

export async function syncYachiyoNativeSkills(): Promise<YachiyoSkillSyncResponse> {
  return apiPost('/yachiyo/studio/skills/sync', {});
}

export async function installYachiyoSkillCommand(
  command: string,
  folderId?: string,
): Promise<YachiyoSkillInstallResponse> {
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

export async function listYachiyoFutureTasks(
  includeFinished = true,
  limit = 100,
): Promise<FutureTaskSnapshot[]> {
  const query = new URLSearchParams({
    include_finished: String(includeFinished),
    limit: String(Math.max(1, Math.min(500, limit))),
  });
  const payload = await apiGet<{ future_tasks?: FutureTaskSnapshot[] }>(`/yachiyo/studio/future-tasks?${query.toString()}`);
  return payload.future_tasks || [];
}

export async function cancelYachiyoFutureTask(
  futureTaskId: string,
  reason = '',
): Promise<{ ok?: boolean; future_task?: FutureTaskSnapshot }> {
  return apiPost(
    `/yachiyo/studio/future-tasks/${encodeURIComponent(futureTaskId)}/cancel`,
    reason ? { reason } : {},
  );
}

export async function triggerDueYachiyoFutureTasks(
  limit = 20,
): Promise<{ ok?: boolean; triggered?: FutureTaskTriggerResultSnapshot[] }> {
  return apiPost('/yachiyo/studio/future-tasks/trigger-due', { limit });
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

export async function listYachiyoGroupRunEvents(
  groupRunId: string,
  afterSequence = 0,
  limit = 200,
): Promise<YachiyoRunEventsPage> {
  const query = new URLSearchParams({
    after_sequence: String(Math.max(0, afterSequence)),
    limit: String(Math.max(1, limit)),
  });
  return apiGet(`/yachiyo/studio/group-runs/${encodeURIComponent(groupRunId)}/events?${query.toString()}`);
}

export async function getYachiyoRunTimeline(runId: string): Promise<YachiyoRunTimelineSnapshot> {
  return apiGet(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/timeline`);
}

export async function listYachiyoWorkflows(): Promise<WorkflowSnapshot[]> {
  const payload = await apiGet<{ workflows?: WorkflowSnapshot[] }>('/yachiyo/studio/workflows');
  return payload.workflows || [];
}

export async function getYachiyoWorkflow(workflowId: string): Promise<WorkflowSnapshot> {
  return apiGet(`/yachiyo/studio/workflows/${encodeURIComponent(workflowId)}`);
}

export async function saveYachiyoWorkflow(
  request: Partial<WorkflowSnapshot>,
): Promise<WorkflowSnapshot> {
  return apiPost('/yachiyo/studio/workflows', request);
}

export async function listYachiyoRunTimelines(limit = 50): Promise<YachiyoRunTimelineSnapshot[]> {
  const query = new URLSearchParams({ limit: String(Math.max(1, Math.min(200, limit))) });
  const payload = await apiGet<{ runs?: YachiyoRunTimelineSnapshot[] }>(`/yachiyo/studio/runs?${query.toString()}`);
  return payload.runs || [];
}

export async function startYachiyoAgentRun(
  agentId: string,
  objective: string,
  title?: string,
): Promise<YachiyoRunTimelineSnapshot> {
  const clientRunId = createClientRunId();
  return apiPost(`/yachiyo/studio/agents/${encodeURIComponent(agentId)}/runs`, {
    objective,
    title: title || undefined,
    client_run_id: clientRunId,
  });
}

export async function listYachiyoRunEvents(
  runId: string,
  afterSequence = 0,
  limit = 200,
): Promise<YachiyoRunEventsPage> {
  const query = new URLSearchParams({
    after_sequence: String(Math.max(0, afterSequence)),
    limit: String(Math.max(1, limit)),
  });
  return apiGet(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/events?${query.toString()}`);
}

export async function readYachiyoRunArtifact(
  runId: string,
  path: string,
): Promise<YachiyoRunArtifactPayload> {
  const encodedPath = path.split('/').map((part) => encodeURIComponent(part)).join('/');
  return apiGet(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}`);
}

export async function rerunYachiyoRun(runId: string): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/rerun`, {});
}

export async function cancelYachiyoRun(runId: string): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/cancel`, {});
}

export async function deleteYachiyoRun(
  runId: string,
): Promise<{ ok?: boolean; deleted_run_ids?: string[]; deleted_run_count?: number }> {
  return apiDelete(`/yachiyo/studio/runs/${encodeURIComponent(runId)}`);
}

export async function approveYachiyoRunApproval(runId: string): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost(`/yachiyo/studio/runs/${encodeURIComponent(runId)}/approval/approve`, {});
}

export async function rejectYachiyoRunApproval(
  runId: string,
  reason = '',
): Promise<YachiyoRunTimelineSnapshot> {
  return apiPost(
    `/yachiyo/studio/runs/${encodeURIComponent(runId)}/approval/reject`,
    reason ? { reason } : {},
  );
}

export async function startYachiyoWorkflowRun(
  workflowId: string,
  objective: string,
  title?: string,
): Promise<WorkflowRunSnapshot> {
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
