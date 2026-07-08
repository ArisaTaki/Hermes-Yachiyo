import { runtimeToolDisplayLabelOrName } from './approval';
import {
  runtimeEventIsDesktopProviderExecutionRouted,
  runtimeEventIsDesktopProviderSessionEvent,
} from './desktopEvents';

export type RuntimeDesktopProviderSessionContext = {
  blockingConditions: string[];
  desktopBackendIsLoopback: string;
  desktopBackendKind: string;
  desktopBackendReadyForPublicRelease: string;
  desktopSessionIsolated: string;
  desktopSessionKind: string;
  executionSessionLabel: string;
  executionSessionMode: string;
  error: string;
  foregroundTakeoverRequired: string;
  keyboardMouseCaptureSupported: string;
  needed: string;
  providerId: string;
  reason: string;
  requiresRealVirtualDesktopBackend: string;
  running: string;
  source: string;
  started: string;
  status: string;
  supportedTools: string[];
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
  const contextSourceRecords = [...baseRecords, ...resultRecords];
  const session = runtimeFirstNestedRecord(contextSourceRecords, 'desktop_provider_session');
  const provider = runtimeFirstNestedRecord(contextSourceRecords, 'desktop_execution_provider');
  const sandboxProvider = runtimeFirstNestedRecord(contextSourceRecords, 'sandbox_provider');
  const route = runtimeFirstNestedRecord(contextSourceRecords, 'desktop_execution_route');
  const contextRecords = [session, provider, sandboxProvider, route, ...baseRecords, ...resultRecords];
  return {
    blockingConditions: runtimeUniqueStrings(contextRecords.flatMap((record) => runtimeStringList(record.blocking_conditions))),
    desktopBackendIsLoopback: runtimeFirstBoolLabel(contextRecords, 'desktop_backend_is_loopback'),
    desktopBackendKind: runtimeFirstString(contextRecords, 'desktop_backend_kind'),
    desktopBackendReadyForPublicRelease: runtimeFirstBoolLabel(contextRecords, 'desktop_backend_ready_for_public_release'),
    desktopSessionIsolated: runtimeFirstBoolLabel(contextRecords, 'desktop_session_isolated'),
    desktopSessionKind: runtimeFirstString(contextRecords, 'desktop_session_kind'),
    executionSessionLabel: runtimeFirstString(contextRecords, 'desktop_execution_session_label'),
    executionSessionMode: runtimeFirstString(contextRecords, 'desktop_execution_session_mode'),
    error: runtimeFirstString(contextRecords, 'error'),
    foregroundTakeoverRequired: runtimeFirstBoolLabel(contextRecords, 'foreground_takeover_required'),
    keyboardMouseCaptureSupported: runtimeFirstBoolLabel(contextRecords, 'keyboard_mouse_capture_supported'),
    needed: runtimeFirstBoolLabel(contextRecords, 'needed'),
    providerId: runtimeFirstString(contextRecords, 'provider_id') || runtimeFirstString(contextRecords, 'selected_provider_id'),
    reason: runtimeFirstString(contextRecords, 'reason'),
    requiresRealVirtualDesktopBackend: runtimeFirstBoolLabel(contextRecords, 'requires_real_virtual_desktop_backend'),
    running: runtimeFirstBoolLabel(contextRecords, 'running'),
    source: runtimeFirstString(contextRecords, 'source') || runtimeFirstString(contextRecords, 'selected_provider_kind'),
    started: runtimeFirstBoolLabel(contextRecords, 'started'),
    status: runtimeFirstString(contextRecords, 'status'),
    supportedTools: runtimeUniqueStrings(contextRecords.flatMap((record) => runtimeStringList(record.supported_tools))),
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
  if (runtimeEventIsDesktopProviderExecutionRouted(eventType)) {
    return providerLabel ? `桌面执行环境已执行 · ${providerLabel}` : '桌面执行环境已执行';
  }
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
    context.executionSessionLabel ? `mode ${context.executionSessionLabel}` : '',
    context.executionSessionMode && !context.executionSessionLabel ? `mode ${context.executionSessionMode}` : '',
    context.status ? `状态 ${context.status}` : '',
    context.desktopSessionKind ? `session ${context.desktopSessionKind}` : '',
    context.desktopBackendKind ? `backend ${context.desktopBackendKind}` : '',
    context.desktopSessionIsolated === 'true' ? 'isolated' : '',
    context.desktopBackendIsLoopback === 'true' ? 'loopback backend' : '',
    context.desktopBackendIsLoopback === 'false' ? 'non-loopback backend' : '',
    context.desktopBackendReadyForPublicRelease === 'true' ? 'release-ready backend' : '',
    context.desktopBackendReadyForPublicRelease === 'false' ? 'backend not release-ready' : '',
    context.requiresRealVirtualDesktopBackend === 'true' ? 'real virtual desktop required' : '',
    context.blockingConditions.length ? `blockers ${context.blockingConditions.slice(0, 3).join(', ')}` : '',
    context.foregroundTakeoverRequired === 'false' ? 'no foreground takeover' : '',
    context.foregroundTakeoverRequired === 'true' ? 'foreground takeover required' : '',
    context.keyboardMouseCaptureSupported === 'true' ? 'keyboard/mouse ready' : '',
    context.running === 'true' ? 'running' : '',
    context.started === 'true' ? 'started' : '',
    context.reason ? `原因 ${context.reason}` : '',
    context.error ? `错误 ${context.error}` : '',
    context.toolNames.length ? `工具 ${context.toolNames.map(runtimeToolDisplayLabelOrName).join(' -> ')}` : '',
    context.supportedTools.length ? `支持 ${context.supportedTools.map(runtimeToolDisplayLabelOrName).join(' -> ')}` : '',
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
