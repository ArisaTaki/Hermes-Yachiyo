import { runtimeToolDisplayLabelOrName } from './approval';
import { runtimeEventIsDesktopProviderSessionEvent } from './desktopEvents';

export type RuntimeDesktopProviderSessionContext = {
  error: string;
  needed: string;
  providerId: string;
  reason: string;
  running: string;
  source: string;
  started: string;
  status: string;
  toolNames: string[];
  url: string;
};

export function runtimeDesktopProviderSessionContext(
  ...records: Array<Record<string, unknown> | null | undefined>
): RuntimeDesktopProviderSessionContext {
  const baseRecords = records.filter((record): record is Record<string, unknown> => Boolean(record));
  const resultRecords = baseRecords
    .map((record) => runtimeRecord(record.result))
    .filter((record) => Object.keys(record).length > 0);
  const session = runtimeFirstNestedRecord([...baseRecords, ...resultRecords], 'desktop_provider_session');
  const contextRecords = [session, ...baseRecords, ...resultRecords];
  return {
    error: runtimeFirstString(contextRecords, 'error'),
    needed: runtimeFirstBoolLabel(contextRecords, 'needed'),
    providerId: runtimeFirstString(contextRecords, 'provider_id'),
    reason: runtimeFirstString(contextRecords, 'reason'),
    running: runtimeFirstBoolLabel(contextRecords, 'running'),
    source: runtimeFirstString(contextRecords, 'source'),
    started: runtimeFirstBoolLabel(contextRecords, 'started'),
    status: runtimeFirstString(contextRecords, 'status'),
    toolNames: runtimeUniqueStrings(contextRecords.flatMap((record) => runtimeStringList(record.tool_names))),
    url: runtimeFirstString(contextRecords, 'url'),
  };
}

export function runtimeDesktopProviderSessionTitle(
  eventType: string,
  context: RuntimeDesktopProviderSessionContext,
  fallback = '',
): string {
  const providerLabel = runtimeDesktopProviderSessionLabel(context);
  if (runtimeEventIsDesktopProviderSessionEvent(eventType, 'failed')) {
    return providerLabel ? `桌面执行环境启动失败 · ${providerLabel}` : '桌面执行环境启动失败';
  }
  if (runtimeEventIsDesktopProviderSessionEvent(eventType, 'started')) {
    return providerLabel ? `桌面执行环境已启动 · ${providerLabel}` : '桌面执行环境已启动';
  }
  if (runtimeEventIsDesktopProviderSessionEvent(eventType, 'ready')) {
    return providerLabel ? `桌面执行环境已就绪 · ${providerLabel}` : '桌面执行环境已就绪';
  }
  if (runtimeEventIsDesktopProviderSessionEvent(eventType, 'required')) {
    return providerLabel ? `需要桌面执行环境 · ${providerLabel}` : '需要桌面执行环境';
  }
  return fallback || runtimeDesktopProviderSessionDetail(context) || '桌面执行环境';
}

export function runtimeDesktopProviderSessionLabel(
  context: RuntimeDesktopProviderSessionContext,
): string {
  return context.providerId || context.url || context.source;
}

export function runtimeDesktopProviderSessionDetail(
  context: RuntimeDesktopProviderSessionContext,
): string {
  return [
    context.providerId ? `provider ${context.providerId}` : '',
    context.status ? `状态 ${context.status}` : '',
    context.running === 'true' ? 'running' : '',
    context.started === 'true' ? 'started' : '',
    context.reason ? `原因 ${context.reason}` : '',
    context.error ? `错误 ${context.error}` : '',
    context.toolNames.length ? `工具 ${context.toolNames.map(runtimeToolDisplayLabelOrName).join(' -> ')}` : '',
    context.url,
  ].filter(Boolean).join(' · ');
}

function runtimeFirstNestedRecord(
  records: Record<string, unknown>[],
  key: string,
): Record<string, unknown> {
  for (const record of records) {
    const value = runtimeRecord(record[key]);
    if (Object.keys(value).length > 0) return value;
  }
  return {};
}

function runtimeRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function runtimeFirstString(records: Record<string, unknown>[], ...keys: string[]): string {
  for (const record of records) {
    for (const key of keys) {
      const value = runtimeString(record[key]);
      if (value) return value;
    }
  }
  return '';
}

function runtimeFirstBoolLabel(records: Record<string, unknown>[], key: string): string {
  for (const record of records) {
    if (record[key] === true) return 'true';
    if (record[key] === false) return 'false';
    const value = runtimeString(record[key]).toLowerCase();
    if (value === 'true' || value === 'false') return value;
  }
  return '';
}

function runtimeString(value: unknown): string {
  return typeof value === 'string' ? value.trim() : '';
}

function runtimeStringList(value: unknown): string[] {
  if (Array.isArray(value)) return value.map((item) => String(item || '').trim()).filter(Boolean);
  const text = runtimeString(value);
  return text ? [text] : [];
}

function runtimeUniqueStrings(values: string[]): string[] {
  return Array.from(new Set(values.map((value) => String(value || '').trim()).filter(Boolean)));
}
