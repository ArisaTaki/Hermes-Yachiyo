import type { RuntimeToolRecoveryAction } from './toolRecoveryActions';
import type { DesktopProviderConformanceSnapshot } from './types';

export type DesktopProviderSessionStartRequest = {
  host?: string;
  port?: number;
  provider_manifest?: string;
  provider_id?: string;
  requires_real_virtual_desktop_backend?: boolean;
  tools?: string[];
};

export type DesktopProviderSessionSnapshot = {
  error?: string;
  needed?: boolean;
  ok?: boolean;
  reason?: string;
  request_ids?: string[];
  status?: string;
  running?: boolean;
  started?: boolean;
  provider_id?: string;
  provider_manifest?: string;
  tool_names?: string[];
  desktop_session_kind?: string;
  desktop_session_isolated?: boolean | null;
  foreground_takeover_required?: boolean | null;
  keyboard_mouse_capture_supported?: boolean | null;
  supported_tools?: string[];
  desktop_backend_kind?: string;
  desktop_backend_is_loopback?: boolean | null;
  desktop_backend_ready_for_public_release?: boolean | null;
  requires_real_virtual_desktop_backend?: boolean | null;
  provider_contract?: Record<string, unknown>;
  provider_conformance?: DesktopProviderConformanceSnapshot | null;
};

export function runtimeRecoveryActionIsDesktopProviderSessionStart(
  action: RuntimeToolRecoveryAction,
): boolean {
  const input = recordValue(action.input);
  const metadata = recordValue(action.metadata);
  const controlAction = stringValue(metadata.control_action || input.control_action);
  const runtimeRetrySource = stringValue(metadata.runtime_retry_source || input.runtime_retry_source);
  const apiRoute = stringValue(metadata.api_route || input.api_route);
  return action.tool === 'desktop.provider_session.start'
    || controlAction === 'desktop_provider_session.start'
    || runtimeRetrySource === 'desktop_provider_session'
    || apiRoute === '/yachiyo/studio/tools/desktop-provider/session/start';
}

export function assertRuntimeRecoveryActionApprovalReady(
  action: RuntimeToolRecoveryAction,
): void {
  if (action.approval_required !== true) return;
  const approvalStatus = stringValue(action.approval_status);
  if (approvalStatus === 'approved') return;
  const detail = approvalStatus ? `当前状态：${approvalStatus}` : '当前状态：pending';
  throw new Error(`恢复动作需要先通过审批，${detail}`);
}

export function desktopProviderSessionStartRequestFromAction(
  action: RuntimeToolRecoveryAction,
): DesktopProviderSessionStartRequest {
  const input = recordValue(action.input);
  const metadata = recordValue(action.metadata);
  const sandboxProvider = recordValue(action.sandbox_provider);
  const providerSession = recordValue(
    input.desktop_provider_session || metadata.desktop_provider_session,
  );
  const providerId = stringValue(
    input.provider_id || metadata.provider_id || providerSession.provider_id || sandboxProvider.provider_id,
  );
  const providerManifest = stringValue(
    input.provider_manifest
      || input.provider_manifest_path
      || metadata.provider_manifest
      || metadata.provider_manifest_path
      || providerSession.provider_manifest
      || providerSession.provider_manifest_path
      || sandboxProvider.provider_manifest
      || sandboxProvider.provider_manifest_path,
  );
  const requiresRealBackend = booleanValue(
    input.requires_real_virtual_desktop_backend,
    metadata.requires_real_virtual_desktop_backend,
    providerSession.requires_real_virtual_desktop_backend,
    sandboxProvider.requires_real_virtual_desktop_backend,
  );
  const host = stringValue(input.host || metadata.host || providerSession.host || sandboxProvider.host);
  const port = numberValue(input.port || metadata.port || providerSession.port || sandboxProvider.port);
  const tools = stringList(input.tools)
    .concat(stringList(input.tool_names))
    .concat(stringList(metadata.tools))
    .concat(stringList(metadata.tool_names))
    .concat(stringList(providerSession.tools))
    .concat(stringList(providerSession.tool_names));
  return {
    ...(host ? { host } : {}),
    ...(port !== undefined ? { port } : {}),
    ...(providerId ? { provider_id: providerId } : {}),
    ...(providerManifest ? { provider_manifest: providerManifest } : {}),
    ...(requiresRealBackend !== undefined
      ? { requires_real_virtual_desktop_backend: requiresRealBackend }
      : {}),
    ...(tools.length ? { tools: Array.from(new Set(tools)) } : {}),
  };
}

export function desktopProviderSessionRecoveryStatusMessage(
  session: DesktopProviderSessionSnapshot,
): string {
  const providerId = session.provider_id || 'local-isolated-desktop';
  if (session.ok === false) {
    const detail = session.error || session.reason || session.status || providerId;
    return `隔离桌面 Provider 启动失败：${detail}`;
  }
  if (session.running || session.started) return `已启动隔离桌面 Provider：${providerId}`;
  if (session.status) return `已请求启动隔离桌面 Provider：${session.status}`;
  return `已请求启动隔离桌面 Provider：${providerId}`;
}

function recordValue(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {};
  return value as Record<string, unknown>;
}

function stringValue(value: unknown): string {
  return String(value || '').trim();
}

function stringList(value: unknown): string[] {
  if (Array.isArray(value)) {
    return Array.from(new Set(value.map((item) => stringValue(item)).filter(Boolean)));
  }
  const text = stringValue(value);
  return text ? [text] : [];
}

function numberValue(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value;
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
}

function booleanValue(...values: unknown[]): boolean | undefined {
  for (const value of values) {
    if (typeof value === 'boolean') return value;
    if (value === 1) return true;
    if (value === 0) return false;
    const text = stringValue(value).toLowerCase();
    if (['1', 'true', 'yes', 'on'].includes(text)) return true;
    if (['0', 'false', 'no', 'off'].includes(text)) return false;
  }
  return undefined;
}
