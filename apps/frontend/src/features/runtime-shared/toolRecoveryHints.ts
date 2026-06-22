export function runtimeToolRecoveryHintsFromRecords(sources: Array<Record<string, unknown>>): string[] {
  return uniqueStrings(sources.flatMap((source) => runtimeToolRecoveryHintsFromRecord(source)));
}

export function runtimeToolRecoveryHintsFromRecord(source: Record<string, unknown>): string[] {
  const error = String(source.error || '').trim();
  if (error !== 'browser_click_fallback_coordinates_required') return [];
  const data = objectValue(source.data);
  const fields = stringList(data.required_fallback_fields);
  const tools = stringList(data.recommended_tools);
  const fieldText = fields.length ? fields.join('/') : 'fallback_x/fallback_y';
  const toolText = tools.length ? tools.join(' -> ') : 'screen.capture -> desktop.click';
  return [
    `Chrome CDP 不可用时不能直接用 CSS selector 点击；请先用 ${toolText} 观察目标位置，再提供 ${fieldText} 坐标。`,
  ];
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.flatMap((item) => stringList(item));
  return String(value || '')
    .split(',')
    .map((item) => item.trim())
    .filter(Boolean);
}

function uniqueStrings(values: unknown[]): string[] {
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)));
}
