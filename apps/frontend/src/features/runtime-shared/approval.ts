export function formatApprovalInput(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return String(value || '');
  }
}

export function approvalPreviewRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function approvalPreviewValue(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  }
  return '';
}
