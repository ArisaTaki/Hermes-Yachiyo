export type RuntimeAnchorKind = 'approval' | 'artifact' | 'artifact-path' | 'event' | 'tool-call';

export function runtimeAnchorId(kind: RuntimeAnchorKind, value: string): string {
  const clean = stringValue(value);
  if (!clean) return '';
  return `runtime-${kind}-${anchorSlug(clean)}`;
}

export function runtimeAnchorSelector(kind: RuntimeAnchorKind, value: string): string {
  const clean = stringValue(value);
  if (!clean) return '';
  const escaped = attributeSelectorValue(clean);
  if (kind === 'approval') return `[data-approval-id="${escaped}"]`;
  if (kind === 'artifact') return `[data-artifact-id="${escaped}"]`;
  if (kind === 'artifact-path') return `[data-artifact-path="${escaped}"]`;
  if (kind === 'event') return `[data-run-event-id="${escaped}"],[data-run-event-identity="${escaped}"]`;
  return `[data-tool-call-id="${escaped}"]`;
}

function anchorSlug(value: string): string {
  const slug = value
    .trim()
    .toLowerCase()
    .replace(/[^a-z0-9_-]+/g, '-')
    .replace(/^-+|-+$/g, '');
  return slug || 'item';
}

function attributeSelectorValue(value: string): string {
  return value.replace(/\\/g, '\\\\').replace(/"/g, '\\"');
}

function stringValue(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}
