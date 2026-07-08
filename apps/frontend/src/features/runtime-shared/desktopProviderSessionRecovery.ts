import type { RuntimeToolRecoveryAction } from './toolRecoveryActions';

export type DesktopProviderSessionStartRequest = {
  host?: string;
  port?: number;
  provider_id?: string;
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
  tool_names?: string[];
  desktop_session_kind?: string;
  desktop_session_isolated?: boolean;
  foreground_takeover_required?: boolean;
  keyboard_mouse_capture_supported?: boolean;
  supported_tools?: string[];
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
  const providerId = stringValue(input.provider_id || metadata.provider_id || sandboxProvider.provider_id);
  const host = stringValue(input.host || metadata.host || sandboxProvider.host);
  const port = numberValue(input.port || metadata.port || sandboxProvider.port);
  const tools = stringList(input.tools)
    .concat(stringList(input.tool_names))
    .concat(stringList(metadata.tools))
    .concat(stringList(metadata.tool_names));
  return {
    ...(host ? { host } : {}),
    ...(port !== undefined ? { port } : {}),
    ...(providerId ? { provider_id: providerId } : {}),
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
