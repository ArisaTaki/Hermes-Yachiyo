import {
  messageRunStatus,
  messageText,
} from './messageState';
import type {
  ChatMessage,
  RenderState,
} from './types';

export function syncRenderStates(messages: ChatMessage[], states: Map<string, RenderState>) {
  const visibleIds = new Set<string>();
  for (const message of messages) {
    if (!message.id) continue;
    visibleIds.add(message.id);
    if (message.role !== 'assistant') {
      states.delete(message.id);
      continue;
    }
    const content = messageText(message);
    const isApprovalRequired = messageRunStatus(message) === 'approval_required';
    const existing = states.get(message.id);
    if (!existing) {
      states.set(message.id, {
        shown: message.status === 'processing' && !isApprovalRequired ? '' : content,
        target: content,
      });
      continue;
    }
    if (isApprovalRequired) {
      existing.shown = content;
      existing.target = content;
      continue;
    }
    if (existing.target !== content) {
      if (message.status === 'processing' && existing.shown) {
        const shownContainsDispatchPayload = containsGroupDispatchPayload(existing.shown);
        if (!shownContainsDispatchPayload && (!content || content.length < existing.shown.length || !content.startsWith(existing.shown))) {
          existing.target = existing.shown;
          continue;
        }
      }
      existing.target = content;
      if (!content.startsWith(existing.shown)) {
        existing.shown = message.status === 'processing' ? '' : content;
      }
    }
  }
  for (const id of Array.from(states.keys())) {
    if (!visibleIds.has(id)) states.delete(id);
  }
}

export function displayMessageText(message: ChatMessage, states: Map<string, RenderState>) {
  if (message.role !== 'assistant' || !message.id) return messageText(message);
  return states.get(message.id)?.shown || '';
}

export function shouldContinueTyping(states: Map<string, RenderState>) {
  for (const state of states.values()) {
    if (state.shown.length < state.target.length) return true;
  }
  return false;
}

export function containsGroupDispatchPayload(text: string) {
  const compact = text.toLowerCase().replace(/[\s_-]+/g, '');
  return (
    compact.includes('ohagroupdispatch')
    || compact.includes('nativegroupdispatch')
    || compact.includes('dispatchgroupagent')
    || compact.includes('runohaagent')
  );
}
