import {
  listRunnables as listLegacyRunnables,
  type RunnableSummary as LegacyRunnableSummary,
} from '../../lib/agents';
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
  tool_capabilities?: string[];
  approval_required_tools?: string[];
  participants?: ChatRunnableSummary[];
};

export async function listYachiyoChatRunnables(): Promise<ChatRunnableSummary[]> {
  try {
    const catalog = await listYachiyoChatRunnableCatalog();
    return chatRunnablesFromPublicSnapshots(catalog.agents, catalog.workflows);
  } catch {
    return chatRunnablesFromLegacySummaries(await listLegacyRunnables());
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
    tool_capabilities: normalizedStringList(runnable.tool_capabilities),
    approval_required_tools: normalizedStringList(runnable.approval_required_tools),
    participants: (runnable.participants || []).map(chatParticipantRunnable),
  };
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

function chatRunnablesFromLegacySummaries(items: LegacyRunnableSummary[]): ChatRunnableSummary[] {
  return items.map((item) => {
    const toolPolicy = legacyToolPolicy(item.tool_policy);
    return {
      id: item.id,
      name: item.name,
      nickname: item.nickname,
      description: item.description,
      avatar_url: item.avatar_url,
      category: item.category,
      output_contract: item.output_contract,
      kind: item.kind,
      enabled: item.enabled,
      tool_capabilities: normalizedStringList(toolPolicy.allowed_tools),
      approval_required_tools: approvalRequiredToolsFromLegacyPolicy(toolPolicy),
      participants: item.participants ? chatRunnablesFromLegacySummaries(item.participants) : undefined,
    };
  });
}

function legacyToolPolicy(value: unknown): { allowed_tools?: unknown; approval_required?: unknown } {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as { allowed_tools?: unknown; approval_required?: unknown }
    : {};
}

function approvalRequiredToolsFromLegacyPolicy(
  policy: { approval_required?: unknown },
): string[] {
  if (!policy.approval_required || typeof policy.approval_required !== 'object' || Array.isArray(policy.approval_required)) {
    return [];
  }
  return normalizedStringList(Object.entries(policy.approval_required)
    .filter(([, required]) => required === true)
    .map(([tool]) => tool)) || [];
}

function normalizedStringList(value: unknown): string[] | undefined {
  const items = Array.isArray(value)
    ? value.map((item) => String(item || '').trim()).filter(Boolean)
    : [];
  const seen = new Set<string>();
  const uniqueItems = items.filter((item) => {
    if (seen.has(item)) return false;
    seen.add(item);
    return true;
  });
  return uniqueItems.length ? uniqueItems : undefined;
}
