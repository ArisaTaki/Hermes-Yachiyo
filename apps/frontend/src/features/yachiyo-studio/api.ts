import { apiGet, apiPost } from '../../lib/bridge';
import type {
  AgentDefinitionSnapshot,
  AgentGroupSnapshot,
  GroupRunSnapshot,
  RunTimelineSnapshot,
  SaveAgentGroupRequest,
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

function createClientRunId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}
