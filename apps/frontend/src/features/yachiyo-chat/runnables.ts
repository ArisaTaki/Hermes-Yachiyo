import { listRunnables as listLegacyRunnables } from '../../lib/agents';
import { listYachiyoChatRunnableCatalog } from './api';
import type { AgentDefinitionSnapshot, WorkflowSnapshot } from './types';

export type ChatRunnableSummary = {
  id: string;
  name: string;
  nickname?: string;
  description?: string;
  avatar_url?: string;
  category?: string;
  output_contract?: 'chat' | 'markdown' | 'diff' | 'report' | 'artifacts' | 'workflow' | string;
  kind: 'agent' | 'workflow';
  enabled?: boolean;
  tool_policy?: {
    allowed_tools?: string[];
    approval_required?: Record<string, boolean>;
  };
  participants?: ChatRunnableSummary[];
};

export async function listYachiyoChatRunnables(): Promise<ChatRunnableSummary[]> {
  try {
    const catalog = await listYachiyoChatRunnableCatalog();
    return chatRunnablesFromPublicSnapshots(catalog.agents, catalog.workflows);
  } catch {
    return listLegacyRunnables();
  }
}

export function chatRunnablesFromPublicSnapshots(
  agents: AgentDefinitionSnapshot[],
  workflows: WorkflowSnapshot[],
): ChatRunnableSummary[] {
  const agentRunnables = agents.map(chatAgentRunnable);
  const agentById = new Map(agentRunnables.map((agent) => [agent.id, agent]));
  const workflowRunnables = workflows.map((workflow): ChatRunnableSummary => ({
    id: workflow.workflow_id,
    name: workflow.name,
    description: workflow.description || undefined,
    output_contract: 'workflow',
    kind: 'workflow',
    enabled: workflow.enabled,
    participants: workflowParticipants(workflow, agentById),
  }));
  return [...agentRunnables, ...workflowRunnables];
}

function chatAgentRunnable(agent: AgentDefinitionSnapshot): ChatRunnableSummary {
  return {
    id: agent.agent_id,
    name: agent.name,
    nickname: agent.nickname || undefined,
    description: agent.description || undefined,
    avatar_url: agent.avatar_url || undefined,
    category: agent.category || undefined,
    output_contract: agent.output_contract || undefined,
    kind: 'agent',
    enabled: agent.enabled,
    tool_policy: chatToolPolicy(agent.tool_policy),
  };
}

function chatToolPolicy(
  policy: AgentDefinitionSnapshot['tool_policy'],
): ChatRunnableSummary['tool_policy'] | undefined {
  if (!policy || typeof policy !== 'object') return undefined;
  const allowedTools = Array.isArray(policy.allowed_tools)
    ? policy.allowed_tools.map((tool) => String(tool || '').trim()).filter(Boolean)
    : undefined;
  const approvalRequired: Record<string, boolean> = {};
  if (
    policy.approval_required
    && typeof policy.approval_required === 'object'
    && !Array.isArray(policy.approval_required)
  ) {
    Object.entries(policy.approval_required as Record<string, unknown>).forEach(([tool, required]) => {
      if (tool.trim()) approvalRequired[tool] = required === true;
    });
  }
  const normalized: ChatRunnableSummary['tool_policy'] = {};
  if (allowedTools?.length) normalized.allowed_tools = allowedTools;
  if (Object.keys(approvalRequired).length) normalized.approval_required = approvalRequired;
  return normalized.allowed_tools || normalized.approval_required ? normalized : undefined;
}

function workflowParticipants(
  workflow: WorkflowSnapshot,
  agentById: Map<string, ChatRunnableSummary>,
): ChatRunnableSummary[] {
  const participants: ChatRunnableSummary[] = [];
  const seen = new Set<string>();
  (workflow.nodes || []).forEach((node) => {
    const agentId = workflowNodeAgentId(node);
    const participant = agentId ? agentById.get(agentId) : undefined;
    if (!participant || seen.has(participant.id)) return;
    seen.add(participant.id);
    participants.push(participant);
  });
  return participants;
}

function workflowNodeAgentId(node: Record<string, unknown>): string {
  const data = recordValue(node.data);
  if (workflowNodeKind(node, data) !== 'agent') return '';
  for (const key of ['agent_id', 'agentId', 'runnable_id', 'runnableId']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function workflowNodeKind(node: Record<string, unknown>, data: Record<string, unknown>): string {
  return String(data.kind || data.node_type || node.type || 'agent').trim();
}

function recordValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
