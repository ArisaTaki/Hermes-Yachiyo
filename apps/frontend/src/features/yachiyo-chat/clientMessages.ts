import type { ChatMessage, PendingAttachment } from './types';

const CONVERSATION_CLIENT_MESSAGE_KEY_SEPARATOR = ':';

export function createClientMessageId() {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 12)}`;
}

export function conversationClientMessageKey(sessionId: string, clientMessageId: string) {
  const normalizedSessionId = sessionId.trim();
  const normalizedClientMessageId = clientMessageId.trim();
  if (!normalizedSessionId || !normalizedClientMessageId) return '';
  return `${encodeURIComponent(normalizedSessionId)}${CONVERSATION_CLIENT_MESSAGE_KEY_SEPARATOR}${encodeURIComponent(normalizedClientMessageId)}`;
}

export function conversationClientMessageSessionPrefix(sessionId: string) {
  const normalizedSessionId = sessionId.trim();
  if (!normalizedSessionId) return '';
  return `${encodeURIComponent(normalizedSessionId)}${CONVERSATION_CLIENT_MESSAGE_KEY_SEPARATOR}`;
}

type OptimisticUserMessageOptions = {
  attachments: PendingAttachment[];
  clientMessageId: string;
  content: string;
  conversationToken: number;
  sessionId: string;
  submittedSequence: number;
};

export function createOptimisticUserMessage({
  attachments,
  clientMessageId,
  content,
  conversationToken,
  sessionId,
  submittedSequence,
}: OptimisticUserMessageOptions): ChatMessage {
  return {
    id: `local:${clientMessageId}`,
    role: 'user',
    content,
    status: 'pending',
    created_at: new Date().toISOString(),
    attachments: attachments.map((attachment) => ({
      id: attachment.id,
      kind: 'image',
      name: attachment.name,
      mime_type: attachment.mime_type,
      size: attachment.size,
      url: attachment.data_url,
      source: 'local_optimistic',
    })),
    metadata: {
      client_message_id: clientMessageId,
      client_optimistic: true,
      client_conversation_token: conversationToken,
      client_session_id: sessionId,
      client_submitted_sequence: submittedSequence,
    },
  };
}

export function reconcileOptimisticUserMessages(
  canonicalMessages: ChatMessage[],
  currentMessages: ChatMessage[],
  conversationToken: number,
  sessionId: string,
  outboxMessages: ChatMessage[] = [],
  submittedSequences: ReadonlyMap<string, number> = new Map(),
): ChatMessage[] {
  const sourceMessages = [...currentMessages, ...outboxMessages];
  const knownSubmittedSequences = new Map(submittedSequences);
  for (const message of sourceMessages) {
    const clientMessageId = chatMessageClientId(message);
    const sequence = chatMessageSubmittedSequence(message);
    const messageSessionId = String(message.metadata?.client_session_id || '').trim();
    const messageKey = conversationClientMessageKey(messageSessionId, clientMessageId);
    if (messageKey && sequence !== null) knownSubmittedSequences.set(messageKey, sequence);
  }
  const canonicalMessagesWithSequence = canonicalMessages.map((message) => {
    const clientMessageId = chatMessageClientId(message);
    const messageKey = conversationClientMessageKey(sessionId, clientMessageId);
    const sequence = messageKey ? knownSubmittedSequences.get(messageKey) : undefined;
    if (!sequence || message.metadata?.client_submitted_sequence === sequence) return message;
    return {
      ...message,
      metadata: {
        ...message.metadata,
        client_submitted_sequence: sequence,
      },
    };
  });
  const canonicalClientMessageIds = new Set(
    canonicalMessagesWithSequence
      .map((message) => chatMessageClientId(message))
      .filter(Boolean),
  );
  const pendingMessagesByConversationKey = new Map<string, ChatMessage>();
  for (const message of sourceMessages) {
    if (!isOptimisticUserMessage(message)) continue;
    if (message.metadata?.client_conversation_token !== conversationToken) continue;
    if (String(message.metadata?.client_session_id || '').trim() !== sessionId) continue;
    const clientMessageId = chatMessageClientId(message);
    const messageKey = conversationClientMessageKey(sessionId, clientMessageId);
    if (messageKey && !canonicalClientMessageIds.has(clientMessageId)) {
      pendingMessagesByConversationKey.set(messageKey, message);
    }
  }
  const pendingMessages = [...pendingMessagesByConversationKey.values()].sort(compareSubmittedMessages);
  if (!pendingMessages.length) return canonicalMessagesWithSequence;
  const orderedMessages = [...canonicalMessagesWithSequence];
  for (const pendingMessage of pendingMessages) {
    const pendingSequence = chatMessageSubmittedSequence(pendingMessage);
    let insertIndex = pendingSequence === null
      ? -1
      : orderedMessages.findIndex((message) => {
        const messageSequence = chatMessageSubmittedSequence(message);
        return messageSequence !== null && messageSequence > pendingSequence;
      });
    if (insertIndex < 0 && pendingSequence === null) {
      const submittedAt = chatMessageCreatedAt(pendingMessage);
      if (submittedAt !== null) {
        insertIndex = orderedMessages.findIndex((message) => {
          const createdAt = chatMessageCreatedAt(message);
          return createdAt !== null && createdAt > submittedAt;
        });
      }
    }
    if (insertIndex < 0) orderedMessages.push(pendingMessage);
    else orderedMessages.splice(insertIndex, 0, pendingMessage);
  }
  return orderedMessages;
}

export function removeOptimisticUserMessage(
  messages: ChatMessage[],
  sessionId: string,
  clientMessageId: string,
): ChatMessage[] {
  return messages.filter((message) => (
    !isOptimisticUserMessage(message)
    || chatMessageClientId(message) !== clientMessageId
    || String(message.metadata?.client_session_id || '').trim() !== sessionId
  ));
}

function chatMessageClientId(message: ChatMessage) {
  return String(message.metadata?.client_message_id || '').trim();
}

function chatMessageSubmittedSequence(message: ChatMessage): number | null {
  const sequence = Number(message.metadata?.client_submitted_sequence);
  return Number.isFinite(sequence) && sequence > 0 ? sequence : null;
}

function chatMessageCreatedAt(message: ChatMessage): number | null {
  const createdAt = Date.parse(String(message.created_at || ''));
  return Number.isFinite(createdAt) ? createdAt : null;
}

function compareSubmittedMessages(left: ChatMessage, right: ChatMessage) {
  const leftSequence = chatMessageSubmittedSequence(left);
  const rightSequence = chatMessageSubmittedSequence(right);
  if (leftSequence !== null && rightSequence !== null && leftSequence !== rightSequence) {
    return leftSequence - rightSequence;
  }
  const leftCreatedAt = chatMessageCreatedAt(left);
  const rightCreatedAt = chatMessageCreatedAt(right);
  if (leftCreatedAt !== null && rightCreatedAt !== null) return leftCreatedAt - rightCreatedAt;
  return 0;
}

function isOptimisticUserMessage(message: ChatMessage) {
  return message.role === 'user' && message.metadata?.client_optimistic === true;
}
