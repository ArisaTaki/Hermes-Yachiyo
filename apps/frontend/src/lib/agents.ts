import { apiDelete, apiGet, apiPatch, apiPost } from './bridge';

export type AgentModelMode = 'follow_main' | 'profile' | 'custom_api';
// Legacy backend values may be returned by older local databases, but the UI
// no longer exposes backend selection. Agent Studio agents run through
// Yachiyo Agent Runtime.
export type AgentExecutionBackend = 'hermes_profile' | 'yachiyo_profile' | 'external_cli';

export type AgentSpec = {
  agent_id: string;
  name: string;
  description?: string;
  avatar_url?: string;
  category?: string;
  instructions?: string;
  model_mode: AgentModelMode;
  execution_backend?: AgentExecutionBackend;
  model_profile_id?: string;
  vision_model_profile_id?: string;
  model_config: {
    provider?: 'openai_compatible' | string;
    base_url?: string;
    model?: string;
    api_key?: string;
    api_key_configured?: boolean;
  };
  tool_policy?: Record<string, unknown>;
  workspace_policy?: Record<string, unknown>;
  skill_ids?: string[];
  output_contract?: 'chat' | 'markdown' | 'diff' | 'report' | 'artifacts' | string;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type SkillSpec = {
  skill_id: string;
  name: string;
  description?: string;
  source_path?: string;
  content_summary?: string;
  skill_markdown?: string;
  asset_paths?: string[];
  created_at?: string;
  updated_at?: string;
};

export type WorkflowNode = {
  id: string;
  type?: string;
  position?: { x: number; y: number };
  data?: Record<string, unknown>;
};

export type WorkflowEdge = {
  id?: string;
  source: string;
  target: string;
};

export type WorkflowSpec = {
  workflow_id: string;
  name: string;
  description?: string;
  nodes: WorkflowNode[];
  edges: WorkflowEdge[];
  default_input_schema?: Record<string, unknown>;
  enabled?: boolean;
  created_at?: string;
  updated_at?: string;
};

export type RunnableSummary = {
  id: string;
  name: string;
  kind: 'agent' | 'workflow';
  enabled?: boolean;
};

export type RunSpec = {
  run_id: string;
  run_group_id?: string;
  kind: 'agent_run' | 'workflow_run' | string;
  runnable_id: string;
  runnable_name?: string;
  status: string;
  user_goal?: string;
  result?: string;
  timeline?: Array<Record<string, unknown>>;
  artifacts?: Array<Record<string, unknown>>;
  created_at?: string;
  updated_at?: string;
  agent_run_id?: string;
  workflow_run_id?: string;
};

export type RunGroupSpec = {
  run_group_id: string;
  title: string;
  source?: string;
  workspace_dir?: string;
  status: string;
  summary?: string;
  child_run_ids?: string[];
  created_at?: string;
  updated_at?: string;
};

export async function listAgents(): Promise<AgentSpec[]> {
  const payload = await apiGet<{ agents?: AgentSpec[] }>('/ui/agents');
  return payload.agents || [];
}

export async function createAgent(request: Partial<AgentSpec>): Promise<AgentSpec> {
  return apiPost<AgentSpec>('/ui/agents', request);
}

export async function updateAgent(agentId: string, request: Partial<AgentSpec>): Promise<AgentSpec> {
  return apiPatch<AgentSpec>(`/ui/agents/${encodeURIComponent(agentId)}`, request);
}

export async function deleteAgent(agentId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/ui/agents/${encodeURIComponent(agentId)}`);
}

export async function testAgentModel(agentId: string): Promise<{ ok?: boolean; message?: string; missing?: string[] }> {
  return apiPost(`/ui/agents/${encodeURIComponent(agentId)}/test-model`);
}

export async function attachSkill(agentId: string, skillId: string): Promise<AgentSpec> {
  return apiPost(`/ui/agents/${encodeURIComponent(agentId)}/skills`, { skill_id: skillId });
}

export async function detachSkill(agentId: string, skillId: string): Promise<AgentSpec> {
  return apiDelete(`/ui/agents/${encodeURIComponent(agentId)}/skills/${encodeURIComponent(skillId)}`);
}

export async function listSkills(): Promise<SkillSpec[]> {
  const payload = await apiGet<{ skills?: SkillSpec[] }>('/ui/skills');
  return payload.skills || [];
}

export async function importSkill(sourcePath: string): Promise<SkillSpec> {
  return apiPost('/ui/skills/import', { source_path: sourcePath });
}

export async function deleteSkill(skillId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/ui/skills/${encodeURIComponent(skillId)}`);
}

export async function listWorkflows(): Promise<WorkflowSpec[]> {
  const payload = await apiGet<{ workflows?: WorkflowSpec[] }>('/ui/workflows');
  return payload.workflows || [];
}

export async function createWorkflow(request: Partial<WorkflowSpec>): Promise<WorkflowSpec> {
  return apiPost('/ui/workflows', request);
}

export async function updateWorkflow(workflowId: string, request: Partial<WorkflowSpec>): Promise<WorkflowSpec> {
  return apiPatch(`/ui/workflows/${encodeURIComponent(workflowId)}`, request);
}

export async function deleteWorkflow(workflowId: string): Promise<{ ok?: boolean }> {
  return apiDelete(`/ui/workflows/${encodeURIComponent(workflowId)}`);
}

export async function listRunnables(): Promise<RunnableSummary[]> {
  const payload = await apiGet<{ runnables?: RunnableSummary[] }>('/ui/runnables');
  return payload.runnables || [];
}

export async function listRuns(): Promise<RunSpec[]> {
  const payload = await apiGet<{ runs?: RunSpec[] }>('/ui/runs');
  return payload.runs || [];
}

export async function listRunGroups(): Promise<RunGroupSpec[]> {
  const payload = await apiGet<{ run_groups?: RunGroupSpec[] }>('/ui/run-groups');
  return payload.run_groups || [];
}

export async function getRun(runId: string): Promise<RunSpec> {
  return apiGet(`/ui/runs/${encodeURIComponent(runId)}`);
}

export async function getRunArtifact(runId: string, path: string): Promise<{ ok?: boolean; path?: string; content?: string; truncated?: boolean }> {
  const encodedPath = path.split('/').map((part) => encodeURIComponent(part)).join('/');
  return apiGet(`/ui/runs/${encodeURIComponent(runId)}/artifacts/${encodedPath}`);
}

export async function createAgentRun(agentId: string, userGoal: string): Promise<RunSpec> {
  return apiPost('/ui/agent-runs', { agent_id: agentId, user_goal: userGoal });
}

export async function createWorkflowRun(workflowId: string, userGoal: string): Promise<RunSpec> {
  return apiPost('/ui/workflow-runs', { workflow_id: workflowId, user_goal: userGoal });
}
