import type { PublicRunEvent, RunEventPageSnapshot } from './types';

export function mergeRuntimeRunEventPages(
  current: PublicRunEvent[],
  incoming: PublicRunEvent[],
): PublicRunEvent[] {
  const bySequence = new Map<number, PublicRunEvent>();
  current.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  incoming.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  return Array.from(bySequence.values()).sort(
    (left, right) => (Number(left.sequence) || 0) - (Number(right.sequence) || 0),
  );
}

export function runEventPageNextCursor(
  page: RunEventPageSnapshot,
  events: PublicRunEvent[],
  fallback = 0,
): number {
  if (Number.isFinite(page.next_after_sequence) && page.next_after_sequence > fallback) {
    return page.next_after_sequence;
  }
  return runEventSequenceCursor(events, fallback);
}

export function runEventSequenceCursor(events: PublicRunEvent[], fallback = 0): number {
  return events.reduce((cursor, event) => {
    const sequence = Number(event.sequence) || 0;
    return sequence > cursor ? sequence : cursor;
  }, fallback);
}
