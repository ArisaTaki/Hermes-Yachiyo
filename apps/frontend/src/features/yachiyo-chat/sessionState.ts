import {
  compactStatusText,
  messageText,
  type YachiyoChatMessage,
} from './messageState';
import type {
  AssistantProfilePayload,
  ChatParticipant,
  ChatSessionContext,
  SessionItem,
  SessionSearchMatch,
} from './types';

export type YachiyoChatParticipant = ChatParticipant;
export type YachiyoChatSessionContext = ChatSessionContext;
export type YachiyoChatSessionSearchMatch = SessionSearchMatch;
export type YachiyoChatSessionItem = SessionItem;
export type YachiyoChatAssistantProfile = AssistantProfilePayload;

export type YachiyoChatRunnable = {
  id: string;
  name: string;
  nickname?: string;
};

export function normalizeSessionContext(context?: YachiyoChatSessionContext | null): YachiyoChatSessionContext {
  const kind = context?.conversation_kind || 'main';
  return {
    conversation_kind: kind,
    runnable_id: context?.runnable_id || '',
    runnable_name: context?.runnable_name || '',
    run_group_id: context?.run_group_id || '',
    avatar_url: context?.avatar_url || '',
    participants: Array.isArray(context?.participants) ? context?.participants : [],
  };
}

export function groupMemberCount(context?: YachiyoChatSessionContext | null) {
  const normalized = normalizeSessionContext(context);
  return (normalized.participants || []).filter((participant) => (
    participant.kind || participant.id || participant.name || participant.nickname
  )).length;
}

export function isUnassignedSession(session?: YachiyoChatSessionItem | null) {
  if (!session) return false;
  return (
    (session.conversation_kind || 'main') === 'main'
    && !session.runnable_id
    && Number(session.message_count || 0) === 0
  );
}

export function contextFromSession(session?: YachiyoChatSessionItem | null): YachiyoChatSessionContext {
  if (!session) return normalizeSessionContext(null);
  return normalizeSessionContext({
    conversation_kind: session.conversation_kind || 'main',
    runnable_id: session.runnable_id || '',
    runnable_name: session.runnable_name || '',
    run_group_id: session.run_group_id || '',
    avatar_url: session.avatar_url || '',
    participants: session.participants || [],
  });
}

export function primaryParticipant(context?: YachiyoChatSessionContext | null): YachiyoChatParticipant | null {
  const normalized = normalizeSessionContext(context);
  return normalized.participants?.[0] || null;
}

export function participantDisplayName(participant?: YachiyoChatParticipant | null) {
  return String(participant?.nickname || participant?.name || participant?.id || '').trim();
}

export function participantInitial(participant?: YachiyoChatParticipant | null, fallback = '月') {
  const label = participantDisplayName(participant);
  return Array.from(label || fallback)[0] || fallback;
}

export function conversationDisplayName(
  session: YachiyoChatSessionItem | undefined,
  context: YachiyoChatSessionContext,
  assistantProfile: YachiyoChatAssistantProfile | null,
  messages: YachiyoChatMessage[],
) {
  const normalized = normalizeSessionContext(context);
  if (normalized.conversation_kind === 'agent') {
    return normalized.runnable_name || participantDisplayName(primaryParticipant(normalized)) || 'Agent';
  }
  if (normalized.conversation_kind === 'workflow') {
    return normalized.runnable_name || 'Workflow 群组';
  }
  if (normalized.conversation_kind === 'group') {
    return normalized.runnable_name || '群组';
  }
  if (normalized.conversation_kind === 'unassigned') {
    return '新对话';
  }
  if (session) return sessionTitle(session);
  return firstUserMessageTitle(messages) || assistantProfile?.agent_name || '月見八千代';
}

export function sessionDisplayName(
  session: YachiyoChatSessionItem,
  assistantProfile: YachiyoChatAssistantProfile | null,
) {
  const context = contextFromSession(session);
  if (context.conversation_kind === 'agent') {
    const title = sessionTitle(session);
    if (title && title !== '新对话') return title;
    return session.runnable_name || participantDisplayName(primaryParticipant(context)) || 'Agent';
  }
  if (context.conversation_kind === 'workflow') {
    const title = sessionTitle(session);
    if (title && title !== '新对话') return title;
    return session.runnable_name || 'Workflow 群组';
  }
  if (context.conversation_kind === 'group') {
    const title = sessionTitle(session);
    if (title && title !== '新对话') return title;
    return session.runnable_name || '群组';
  }
  return sessionTitle(session) || assistantProfile?.agent_name || '新对话';
}

export function sessionKindLabel(session: YachiyoChatSessionItem) {
  const context = contextFromSession(session);
  if (context.conversation_kind === 'agent') return 'Agent';
  if (context.conversation_kind === 'workflow') {
    const count = context.participants?.length || 0;
    return count ? `Workflow · ${count} Agents` : 'Workflow';
  }
  if (context.conversation_kind === 'group') {
    const count = groupMemberCount(context);
    return count ? `群组 · ${count} 成员` : '群组';
  }
  return '';
}

export function groupDefaultName(
  agentRunnables: YachiyoChatRunnable[],
  selectedAgentIds: string[],
  assistantProfile: YachiyoChatAssistantProfile | null,
) {
  const names = [
    assistantProfile?.agent_nickname || assistantProfile?.agent_name || '主模型',
    ...selectedAgentIds
      .map((agentId) => agentRunnables.find((agent) => agent.id === agentId))
      .map((agent) => agent?.nickname || agent?.name || '')
      .filter(Boolean),
  ];
  return names.join('、');
}

export function deleteTargetLabel(context: YachiyoChatSessionContext) {
  const kind = normalizeSessionContext(context).conversation_kind;
  return kind === 'group' || kind === 'workflow' ? '群组' : '对话';
}

export function sessionTitle(session: YachiyoChatSessionItem) {
  const title = stripLeadingMentions((session.title || '').trim());
  if (title && !looksLikeSessionIdTitle(title, session.session_id) && !looksLikeTitlePromptEcho(title)) return title;
  const preview = (session.latest_message_preview || '').trim();
  if (preview) return compactStatusText(preview, 36);
  return '新对话';
}

export function sessionPreview(session: YachiyoChatSessionItem) {
  if (session.search_match?.snippet) {
    const role = session.search_match.role === 'user'
      ? '你'
      : session.search_match.role === 'assistant'
        ? sessionDisplayName(session, null)
        : '消息';
    const count = session.search_match.match_count && session.search_match.match_count > 1
      ? ` · ${session.search_match.match_count} 处`
      : '';
    return `${role}：${compactStatusText(session.search_match.snippet, 56)}${count}`;
  }
  if (session.search_match?.kind === 'session') return session.search_match.snippet || '会话信息匹配';
  const preview = compactStatusText(session.latest_message_preview || sessionTitle(session), 48);
  const approvalCount = Number(session.approval_count || 0);
  if (approvalCount > 0) {
    const countLabel = approvalCount > 1 ? ` ${approvalCount} 项` : '';
    return `待审批${countLabel}：${preview || '需要确认工具调用'}`;
  }
  if (session.is_processing) {
    const processingCount = Number(session.processing_count || 0);
    const countLabel = processingCount > 1 ? ` ${processingCount} 项` : '';
    return `处理中${countLabel}：${preview || '正在处理'}`;
  }
  if (session.latest_message_status === 'failed') return `处理失败：${preview || '任务执行失败'}`;
  if (session.conversation_kind === 'workflow') {
    const names = (session.participants || []).map((participant) => participantDisplayName(participant)).filter(Boolean).slice(0, 3);
    return names.length ? `${names.join(' / ')} · ${preview || '已创建'}` : `Workflow · ${preview || '已创建'}`;
  }
  if (session.conversation_kind === 'group') {
    const names = (session.participants || [])
      .filter((participant) => participant.kind === 'agent')
      .map((participant) => participantDisplayName(participant))
      .filter(Boolean)
      .slice(0, 3);
    return names.length ? `${names.join(' / ')} · ${preview || '已创建'}` : `群组 · ${preview || '已创建'}`;
  }
  if (session.message_count) return `已完成：${preview || sessionTitle(session)}`;
  if (!session.message_count) return session.conversation_kind === 'agent' ? '新的 Agent 对话' : '新对话';
  return preview;
}

export function firstUserMessageTitle(messages: YachiyoChatMessage[]) {
  const firstUser = messages.find((message) => message.role === 'user' && messageText(message).trim());
  return firstUser ? compactStatusText(stripLeadingMentions(messageText(firstUser)), 36) : '';
}

export function stripLeadingMentions(value: string) {
  let title = String(value || '').replace(/\s+/g, ' ').trim();
  const mentionRe = /^@(?:"[^"]+"|'[^']+'|“[^”]+”|‘[^’]+’|[^\s@:：，。！？、；;,.!?]+)[\s:：,，、;；-]*/;
  while (mentionRe.test(title)) {
    const next = title.replace(mentionRe, '').trim();
    if (next === title) break;
    title = next;
  }
  return title;
}

function looksLikeSessionIdTitle(title: string, sessionId: string) {
  const value = title.trim();
  return value === sessionId.slice(0, 8) || /^[a-f0-9]{8,32}$/i.test(value);
}

function looksLikeTitlePromptEcho(title: string) {
  const normalized = title.replace(/\s+/g, '');
  if (!normalized) return false;
  const markers = [
    '请为这段持续对话生成',
    '会话列表标题',
    '第一条用户消息',
    '最近对话',
    '当前标题',
    '只输出标题',
    '用户要求为这段',
    '要求包括',
  ];
  return markers.some((marker) => normalized.includes(marker)) || /^(首先用户要求|首先，用户要求|用户要求)/.test(normalized);
}
