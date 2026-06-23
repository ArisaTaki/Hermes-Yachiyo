import type {
  AgentGroupSnapshot,
  GroupRunSnapshot,
  SaveAgentGroupRequest,
} from '../../yachiyo-studio/types';

export type AgentGroupToolPolicyPreset = {
  id: string;
  label: string;
  summary: string;
  risk: 'low' | 'medium';
  tools: string[];
};

export const agentGroupToolPolicyPresets: AgentGroupToolPolicyPreset[] = [
  {
    id: 'desktop_execution',
    label: 'Desktop execution',
    summary: 'Screen, app, media, foreground input, and browser tools.',
    risk: 'medium',
    tools: [
      'screen.capture',
      'desktop.active_window',
      'app.open',
      'app.focus',
      'media.apple_music_play',
      'media.apple_music_control',
      'desktop.safe_shortcut',
      'desktop.safe_type_text',
      'desktop.safe_click',
      'desktop.hotkey',
      'desktop.type_text',
      'browser.open_url',
      'browser.open_url_and_extract_text',
      'browser.open_url_and_screenshot',
      'browser.current_page',
      'browser.click',
      'browser.type_text',
      'browser.extract_text',
      'browser.screenshot',
    ],
  },
  {
    id: 'screen_capture',
    label: 'Screen',
    summary: 'Read-only screen capture.',
    risk: 'low',
    tools: ['screen.capture'],
  },
  {
    id: 'active_window',
    label: 'Active window',
    summary: 'Read the foreground app and window title.',
    risk: 'low',
    tools: ['desktop.active_window'],
  },
  {
    id: 'app_control',
    label: 'App control',
    summary: 'Open and focus local desktop apps.',
    risk: 'low',
    tools: ['app.open', 'app.focus'],
  },
  {
    id: 'media_control',
    label: 'Media',
    summary: 'Search, play, and control Apple Music.',
    risk: 'low',
    tools: ['media.apple_music_play', 'media.apple_music_control'],
  },
  {
    id: 'foreground_input',
    label: 'Foreground input',
    summary: 'Run safe shortcuts, type explicit text, and send foreground input.',
    risk: 'medium',
    tools: [
      'desktop.safe_shortcut',
      'desktop.safe_type_text',
      'desktop.safe_click',
      'desktop.hotkey',
      'desktop.type_text',
    ],
  },
  {
    id: 'browser_control',
    label: 'Browser',
    summary: 'Open pages, inspect content, click, type, and capture browser screenshots.',
    risk: 'medium',
    tools: [
      'browser.open_url',
      'browser.open_url_and_extract_text',
      'browser.open_url_and_screenshot',
      'browser.current_page',
      'browser.click',
      'browser.type_text',
      'browser.extract_text',
      'browser.screenshot',
    ],
  },
];

export function agentInitial(name: string): string {
  const clean = name.trim();
  return clean ? clean.slice(0, 1).toUpperCase() : 'A';
}

export function agentGroupMemberIds(group: AgentGroupSnapshot | null): string[] {
  return (group?.members || [])
    .map((member) => member.agent_id)
    .filter(Boolean);
}

export function agentGroupListMeta(group: AgentGroupSnapshot): string {
  return `${group.members.length} members · ${group.mode || 'moderated'} · ${group.memory_scope || 'shared'}`;
}

export function agentGroupMemberSummary(group: AgentGroupSnapshot): string {
  return group.members.map((member) => member.name || member.agent_id).join('、') || 'No members';
}

export function agentGroupToolPolicyPresetFor(policyId: string): AgentGroupToolPolicyPreset | null {
  const clean = normalizedAgentGroupToolPolicyId(policyId);
  return agentGroupToolPolicyPresets.find((preset) => preset.id === clean) || null;
}

export function agentGroupToolPolicyLabel(policyId: string): string {
  if (!policyId.trim()) return 'Member Agent policy';
  return agentGroupToolPolicyPresetFor(policyId)?.label || policyId.trim();
}

export function agentGroupToolPolicyPreviewTools(policyId: string): string[] {
  return agentGroupToolPolicyPresetFor(policyId)?.tools || [];
}

export function nextSelectedAgentGroupId(current: string, nextAgentGroups: AgentGroupSnapshot[]): string {
  if (current && nextAgentGroups.some((group) => group.group_id === current)) return current;
  return nextAgentGroups.length ? nextAgentGroups[0].group_id : '';
}

export function toggleAgentGroupMemberId(current: string[], agentId: string): string[] {
  if (!agentId) return current;
  return current.includes(agentId)
    ? current.filter((item) => item !== agentId)
    : [...current, agentId];
}

export function buildAgentGroupSaveRequest(
  groupId: string,
  name: string,
  memberIds: string[],
  currentGroup: AgentGroupSnapshot | null = null,
  mode: AgentGroupSnapshot['mode'] = currentGroup?.mode || 'moderated',
  memoryScope: AgentGroupSnapshot['memory_scope'] = currentGroup?.memory_scope || 'shared',
  description = currentGroup?.description || '',
  moderatorAgentId = currentGroup?.moderator_agent_id || '',
  defaultModel = currentGroup?.default_model || '',
  toolPolicyId = currentGroup?.tool_policy_id || '',
  enabled = currentGroup?.enabled ?? true,
): SaveAgentGroupRequest {
  const selectedModeratorId = moderatorAgentId && memberIds.includes(moderatorAgentId)
    ? moderatorAgentId
    : memberIds[0];
  return {
    group_id: groupId || undefined,
    name,
    description: description.trim() || undefined,
    members: memberIds.map((agentId, index) => ({
      agent_id: agentId,
      role: agentId === selectedModeratorId ? 'moderator' : 'member',
      sort_order: index,
      enabled: true,
    })),
    mode,
    moderator_agent_id: selectedModeratorId || null,
    default_model: defaultModel.trim() || null,
    memory_scope: memoryScope,
    tool_policy_id: toolPolicyId.trim() || null,
    enabled,
  };
}

export function agentGroupSaveDisabled(busy: boolean, name: string, memberIds: string[]): boolean {
  return busy || !name.trim() || !memberIds.length;
}

export function groupRunTimelineRunId(groupRun: GroupRunSnapshot | null): string {
  return groupRun?.runs?.[0]?.run_id || groupRun?.child_run_ids?.[0] || '';
}

function normalizedAgentGroupToolPolicyId(policyId: string): string {
  const clean = policyId.trim().toLowerCase().replace(/[-\s]+/g, '_');
  const withoutPrefix = clean.startsWith('policy_') ? clean.slice('policy_'.length) : clean;
  return withoutPrefix.endsWith('_v1') ? withoutPrefix.slice(0, -'_v1'.length) : withoutPrefix;
}
