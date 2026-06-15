import { apiDelete, apiGet, apiPost } from '../../lib/bridge';
import type {
  AgentDefinitionSnapshot,
  AgentGroupSnapshot,
  GroupRunSnapshot,
  RunTimelineSnapshot,
  SaveAgentGroupRequest,
  SkillSnapshot,
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
