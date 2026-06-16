export type MentionParticipant = {
  kind?: 'main' | 'agent' | 'workflow' | 'group' | string;
  id?: string;
  name?: string;
  nickname?: string;
  avatar_url?: string;
};

export type MentionOption = {
  id: string;
  name: string;
  nickname?: string;
  avatar_url?: string;
  kind: 'main' | 'agent' | 'workflow';
  participants?: MentionParticipant[];
};

export type PublicTaskMentionTarget = MentionOption & {
  kind: 'agent' | 'workflow';
};

export type MentionRunnable = {
  id: string;
  name: string;
  nickname?: string;
  avatar_url?: string;
  kind: 'agent' | 'workflow' | string;
  participants?: MentionParticipant[];
  enabled?: boolean;
};

export type MentionAssistantProfile = {
  agent_nickname?: string;
  agent_avatar_url?: string;
};

export type MentionSessionContext = {
  conversation_kind?: 'main' | 'agent' | 'workflow' | 'group' | 'unassigned' | string;
  participants?: MentionParticipant[];
};

export function mentionQueryAtEnd(value: string): string | null {
  const match = String(value || '').match(/(^|[\s，。！？、；;,.!?])@([^\s@，。！？、；;,.!?]*)$/);
  return match ? match[2] : null;
}

export function mentionOptionsForQuery(
  runnables: MentionRunnable[],
  query: string | null,
  assistantProfile: MentionAssistantProfile | null,
  context?: MentionSessionContext | null,
): MentionOption[] {
  if (query === null) return [];
  const needle = query.trim().toLowerCase();
  const normalized = normalizeMentionSessionContext(context);
  let scopedRunnables = runnables;
  if (normalized.conversation_kind === 'group') {
    const groupAgentIds = new Set(
      (normalized.participants || [])
        .filter((participant) => participant.kind === 'agent')
        .map((participant) => participant.id)
        .filter(Boolean),
    );
    scopedRunnables = runnables.filter((item) => (
      item.kind === 'workflow' || (item.kind === 'agent' && groupAgentIds.has(item.id))
    ));
  }
  return allMentionOptions(scopedRunnables, assistantProfile)
    .filter((option) => {
      if (!needle) return true;
      return [
        option.name,
        option.nickname,
        option.kind === 'main' ? 'main model' : '',
        option.kind,
      ].some((value) => String(value || '').toLowerCase().includes(needle));
    })
    .slice(0, 7);
}

export function allMentionOptions(
  runnables: MentionRunnable[],
  assistantProfile: MentionAssistantProfile | null,
): MentionOption[] {
  const main: MentionOption = {
    id: 'main',
    name: '主模型',
    nickname: assistantProfile?.agent_nickname || '八千代',
    avatar_url: assistantProfile?.agent_avatar_url,
    kind: 'main',
  };
  const options: MentionOption[] = [
    main,
    ...runnables
      .filter((item) => item.kind === 'agent')
      .map(mentionOptionFromRunnable),
    ...runnables
      .filter((item) => item.kind === 'workflow')
      .map(mentionOptionFromRunnable),
  ];
  return options;
}

export function mentionKindLabel(option: MentionOption) {
  if (option.kind === 'main') return '主模型';
  if (option.kind === 'workflow') {
    const count = option.participants?.length || 0;
    return count ? `Workflow · ${count} Agents` : 'Workflow';
  }
  return 'Agent';
}

export function mentionTextForOption(option: MentionOption) {
  if (option.kind === 'main') return '@主模型 ';
  const name = option.nickname || option.name;
  if (/\s/.test(name)) return `@"${name.replace(/"/g, '\\"')}" `;
  return `@${name} `;
}

export function replaceTrailingMentionQuery(value: string, mentionText: string) {
  const match = String(value || '').match(/(^|[\s\S]*[\s，。！？、；;,.!?])@([^\s@，。！？、；;,.!?]*)$/);
  if (match) return `${match[1]}${mentionText}`;
  const spacer = value && !/[\s，。！？、；;,.!?]$/.test(value) ? ' ' : '';
  return `${value}${spacer}${mentionText}`;
}

export function activeMentions(
  input: string,
  runnables: MentionRunnable[],
  assistantProfile: MentionAssistantProfile | null,
): MentionOption[] {
  const options = allMentionOptions(runnables, assistantProfile);
  const seen = new Set<string>();
  const result: MentionOption[] = [];
  const mentionRe = /@(?:"([^"]+)"|'([^']+)'|([^\s@，。！？、；;,.!?]+))/g;
  let match: RegExpExecArray | null;
  while ((match = mentionRe.exec(input)) !== null) {
    const label = String(match[1] || match[2] || match[3] || '').toLowerCase();
    const option = options.find((candidate) => [
      candidate.name,
      candidate.nickname,
      candidate.kind === 'main' ? '主模型' : '',
      candidate.kind === 'main' ? 'main' : '',
    ].some((value) => String(value || '').toLowerCase() === label));
    if (!option) continue;
    const key = `${option.kind}-${option.id}`;
    if (seen.has(key)) continue;
    seen.add(key);
    result.push(option);
  }
  return result;
}

export function yachiyoPublicTaskTarget(
  input: string,
  runnables: MentionRunnable[],
  assistantProfile: MentionAssistantProfile | null,
): PublicTaskMentionTarget | null {
  const mentions = activeMentions(input, runnables, assistantProfile);
  if (mentions.length !== 1) return null;
  return mentions[0].kind === 'main' ? null : mentions[0] as PublicTaskMentionTarget;
}

export function yachiyoPublicTaskPrompt(input: string, target: MentionOption): string {
  let prompt = String(input || '').trim();
  uniqueStrings([target.nickname, target.name]).forEach((label) => {
    const escaped = escapeRegExp(label);
    prompt = prompt.replace(
      new RegExp(`(^|[\\s，。！？、；;,.!?])@(?:"${escaped}"|'${escaped}'|${escaped})(?=$|[\\s，。！？、；;,.!?])`, 'gi'),
      '$1',
    );
  });
  prompt = prompt.replace(/\s{2,}/g, ' ').trim();
  return prompt || String(input || '').trim();
}

function mentionOptionFromRunnable(item: MentionRunnable): MentionOption {
  return {
    id: item.id,
    name: item.name,
    nickname: item.nickname,
    avatar_url: item.avatar_url,
    kind: item.kind as 'agent' | 'workflow',
    participants: (item.participants || []).map((participant) => ({
      id: participant.id,
      name: participant.name,
      nickname: participant.nickname,
      avatar_url: participant.avatar_url,
      kind: participant.kind,
    })),
  };
}

function normalizeMentionSessionContext(context?: MentionSessionContext | null): MentionSessionContext {
  return {
    conversation_kind: context?.conversation_kind || 'main',
    participants: Array.isArray(context?.participants) ? context?.participants : [],
  };
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)));
}

function escapeRegExp(value: string): string {
  return String(value || '').replace(/[.*+?^${}()|[\]\\]/g, '\\$&');
}
