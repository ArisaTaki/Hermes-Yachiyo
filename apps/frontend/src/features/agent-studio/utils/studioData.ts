import type {
  AgentSpec,
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

function studioRunnableToolPolicy(policy: AgentSpec['tool_policy']): RunnableSummary['tool_policy'] | undefined {
  if (!policy || typeof policy !== 'object') return undefined;
  const raw = policy as { allowed_tools?: unknown; approval_required?: unknown };
  const allowedTools = Array.isArray(raw.allowed_tools)
    ? raw.allowed_tools.map((tool) => String(tool || '').trim()).filter(Boolean)
    : undefined;
  const approvalRequired: Record<string, boolean> = {};
  if (raw.approval_required && typeof raw.approval_required === 'object' && !Array.isArray(raw.approval_required)) {
    Object.entries(raw.approval_required as Record<string, unknown>).forEach(([tool, required]) => {
      if (tool.trim()) approvalRequired[tool] = required === true;
    });
  }
  const normalized: RunnableSummary['tool_policy'] = {};
  if (allowedTools?.length) normalized.allowed_tools = allowedTools;
  if (Object.keys(approvalRequired).length) normalized.approval_required = approvalRequired;
  return normalized.allowed_tools || normalized.approval_required ? normalized : undefined;
}

function studioAgentRunnable(agent: AgentSpec): RunnableSummary {
  return {
    id: agent.agent_id,
    name: agent.name,
    nickname: agent.nickname,
    description: agent.description,
    avatar_url: agent.avatar_url,
    category: agent.category,
    output_contract: agent.output_contract,
    kind: 'agent',
    enabled: agent.enabled,
    tool_policy: studioRunnableToolPolicy(agent.tool_policy),
  };
}

function workflowNodeKind(node: WorkflowSpec['nodes'][number]): string {
  const data = node.data || {};
  return String(data.kind || data.node_type || node.type || 'agent').trim();
}

function workflowNodeAgentId(node: WorkflowSpec['nodes'][number]): string {
  if (workflowNodeKind(node) !== 'agent') return '';
  const data = node.data || {};
  for (const key of ['agent_id', 'agentId', 'runnable_id', 'runnableId']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function workflowParticipantsForView(
  workflow: WorkflowSpec,
  agentRunnables: Map<string, RunnableSummary>,
): RunnableSummary[] {
  const participants: RunnableSummary[] = [];
  const seen = new Set<string>();
  workflow.nodes.forEach((node) => {
    const agentId = workflowNodeAgentId(node);
    const participant = agentId ? agentRunnables.get(agentId) : undefined;
    if (!participant || seen.has(participant.id)) return;
    seen.add(participant.id);
    participants.push(participant);
  });
  return participants;
}

export function studioRunnablesForView(agents: AgentSpec[], workflows: WorkflowSpec[]): RunnableSummary[] {
  const agentRunnables = agents.map(studioAgentRunnable);
  const agentById = new Map(agentRunnables.map((agent) => [agent.id, agent]));
  const workflowRunnables = workflows.map((workflow): RunnableSummary => ({
    id: workflow.workflow_id,
    name: workflow.name,
    description: workflow.description,
    output_contract: 'workflow',
    kind: 'workflow',
    enabled: workflow.enabled,
    participants: workflowParticipantsForView(workflow, agentById),
  }));
  return [...agentRunnables, ...workflowRunnables];
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
