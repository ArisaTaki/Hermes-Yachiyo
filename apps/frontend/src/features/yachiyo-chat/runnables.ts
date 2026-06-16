import { listRunnables as listLegacyRunnables } from '../../lib/agents';
import { listYachiyoChatRunnableCatalog } from './api';
import type { ChatRunnableParticipantSnapshot, ChatRunnableSnapshot } from './types';

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
  agents: ChatRunnableSnapshot[],
  workflows: ChatRunnableSnapshot[],
): ChatRunnableSummary[] {
  const agentRunnables = agents.map(chatRunnableSummary);
  const workflowRunnables = workflows.map(chatRunnableSummary);
  return [...agentRunnables, ...workflowRunnables];
}

function chatRunnableSummary(runnable: ChatRunnableSnapshot): ChatRunnableSummary {
  return {
    id: runnable.runnable_id || runnable.agent_id || runnable.workflow_id || '',
    name: runnable.name,
    nickname: runnable.nickname || undefined,
    description: runnable.description || undefined,
    avatar_url: runnable.avatar_url || undefined,
    category: runnable.category || undefined,
    output_contract: runnable.output_contract || undefined,
    kind: runnable.kind,
    enabled: runnable.enabled,
    tool_policy: chatToolPolicy(runnable.tool_capabilities, runnable.approval_required_tools),
    participants: (runnable.participants || []).map(chatParticipantRunnable),
  };
}

function chatToolPolicy(
  toolCapabilities: string[] | undefined,
  approvalRequiredTools: string[] | undefined,
): ChatRunnableSummary['tool_policy'] | undefined {
  const allowedTools = Array.isArray(toolCapabilities)
    ? toolCapabilities.map((tool) => String(tool || '').trim()).filter(Boolean)
    : [];
  const approvalRequired: Record<string, boolean> = {};
  (approvalRequiredTools || []).forEach((tool) => {
    const cleanTool = String(tool || '').trim();
    if (cleanTool) approvalRequired[cleanTool] = true;
  });
  const normalized: ChatRunnableSummary['tool_policy'] = {};
  if (allowedTools?.length) normalized.allowed_tools = allowedTools;
  if (Object.keys(approvalRequired).length) normalized.approval_required = approvalRequired;
  return normalized.allowed_tools || normalized.approval_required ? normalized : undefined;
}

function chatParticipantRunnable(participant: ChatRunnableParticipantSnapshot): ChatRunnableSummary {
  return {
    id: participant.runnable_id || participant.agent_id || participant.workflow_id || '',
    name: participant.name,
    nickname: participant.nickname || undefined,
    avatar_url: participant.avatar_url || undefined,
    category: participant.category || undefined,
    kind: participant.kind,
    enabled: participant.enabled,
  };
}
