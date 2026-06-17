import type { ReactNode } from 'react';

import { UiIcon } from '../../../components/UiIcon';
import { messageSender } from '../messageState';
import {
  normalizeSessionContext,
  participantDisplayName,
  participantInitial,
  primaryParticipant,
} from '../sessionState';
import type { ChatRunnableSummary as RunnableSummary } from '../runnables';
import type {
  AssistantProfilePayload,
  ChatMessage,
  ChatParticipant,
  ChatSessionContext,
} from '../types';

type AvatarParticipant = Pick<ChatParticipant, 'avatar_url' | 'id' | 'kind' | 'name' | 'nickname' | 'participants'>;

function avatarNode(url: string | undefined, label: string, fallback: string, loading = false): ReactNode {
  if (loading) return <span className="chat-avatar-loading" aria-hidden="true" />;
  return url ? <img src={url} alt={label} /> : fallback;
}

export function participantAvatarContent(participant: AvatarParticipant | null | undefined, fallback = '月') {
  const label = participantDisplayName(participant) || fallback;
  const url = participant?.avatar_url;
  return avatarNode(url, label, participantInitial(participant, fallback));
}

export function AvatarStack({ participants }: { participants: AvatarParticipant[] }) {
  const visible = participants.slice(0, 3);
  if (!visible.length) return <>{'W'}</>;
  return (
    <span className="chat-avatar-stack-inner" aria-hidden="true">
      {visible.map((participant, index) => (
        <span className="chat-avatar-stack-face" key={participant.id || participant.name || index}>
          {participantAvatarContent(participant, 'A')}
        </span>
      ))}
    </span>
  );
}

export function SessionAvatar({ assistantProfile, context, loading, size, runnables }: {
  assistantProfile: AssistantProfilePayload | null;
  context?: ChatSessionContext | null;
  loading?: boolean;
  size: 'small' | 'header';
  runnables?: RunnableSummary[];
}) {
  const normalized = normalizeSessionContext(context);
  const className = size === 'header' ? 'chat-header-avatar' : 'chat-item-avatar';
  if (normalized.conversation_kind === 'unassigned') {
    return (
      <span className={`${className} chat-neutral-avatar`} title="新对话">
        <UiIcon name="chat" />
      </span>
    );
  }
  if (normalized.conversation_kind === 'workflow' || normalized.conversation_kind === 'group') {
    if (normalized.conversation_kind === 'group' && normalized.avatar_url) {
      const name = normalized.runnable_name || '群组';
      return (
        <span className={`${className} chat-group-custom-avatar`} title={name}>
          {avatarNode(normalized.avatar_url, name, '群', loading)}
        </span>
      );
    }
    const runnable = runnables?.find((item) => item.id === normalized.runnable_id);
    const participants = runnable?.participants || normalized.participants || [];
    return (
      <span className={`${className} chat-avatar-stack`} title={runnable?.name || normalized.runnable_name || '群组'}>
        <AvatarStack participants={participants.map((participant) => ({
          kind: participant.kind,
          id: participant.id,
          name: participant.name || participant.nickname || '',
          nickname: participant.nickname,
          avatar_url: participant.avatar_url,
        }))} />
      </span>
    );
  }
  if (normalized.conversation_kind === 'agent') {
    const runnable = runnables?.find((item) => item.id === normalized.runnable_id);
    const participant = primaryParticipant(normalized);
    const avatarUrl = runnable ? runnable.avatar_url : participant?.avatar_url;
    const name = runnable?.nickname || runnable?.name || participantDisplayName(participant) || normalized.runnable_name || 'Agent';
    return (
      <span className={`${className} chat-agent-avatar`} title={name}>
        {agentAvatarNode(avatarUrl, name)}
      </span>
    );
  }
  return (
    <span className={className}>
      {avatarNode(assistantProfile?.agent_avatar_url, assistantProfile?.agent_name || 'Yachiyo', '月', loading)}
    </span>
  );
}

export function messageAvatar(
  message: ChatMessage,
  profile: AssistantProfilePayload | null,
  profileLoading = false,
  runnables: RunnableSummary[] = [],
) {
  const role = message.role || 'system';
  if (role === 'user') return avatarNode(profile?.user_avatar_url, '你', '你', profileLoading);
  if (role === 'assistant') {
    const sender = messageSender(message);
    if (sender?.kind === 'workflow') {
      const runnable = runnables.find((item) => item.id === sender.id);
      const participants = runnable?.participants || sender.participants || [];
      return <AvatarStack participants={participants.map((participant) => ({
        kind: participant.kind,
        id: participant.id,
        name: participant.name || participant.nickname || '',
        nickname: participant.nickname,
        avatar_url: participant.avatar_url,
      }))} />;
    }
    if (sender?.kind === 'agent') {
      const runnable = runnables.find((item) => item.id === sender.id);
      const avatarUrl = runnable ? runnable.avatar_url : sender.avatar_url;
      const name = runnable?.nickname || runnable?.name || participantDisplayName(sender) || 'Agent';
      return agentAvatarNode(avatarUrl, name);
    }
    return avatarNode(profile?.agent_avatar_url, profile?.agent_name || 'Yachiyo', '月', profileLoading);
  }
  return 'i';
}

function agentInitial(name: string): string {
  const clean = (name || '').trim();
  return clean ? clean.slice(0, 1).toUpperCase() : 'A';
}

function agentAvatarNode(avatarUrl: string | undefined, name: string) {
  if (avatarUrl) {
    return (
      <span className="agent-avatar has-image" aria-hidden="true">
        <img src={avatarUrl} alt="" />
      </span>
    );
  }
  return (
    <span className="agent-avatar" aria-hidden="true">
      {agentInitial(name)}
    </span>
  );
}
