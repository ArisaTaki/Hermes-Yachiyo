import type { DesktopExecutionCapabilitySnapshot } from '../runtime-shared/types';
import { runtimeToolDisplayLabelOrName } from '../runtime-shared/approval';
import type { ChatNotice, YachiyoReadinessSnapshot } from './types';

const desktopCapabilityIds = [
  'desktop_execution',
  'screen_capture',
  'active_window',
  'app_control',
  'media_control',
  'foreground_activation',
  'foreground_input',
  'browser_control',
];

const permissionLabels: Record<string, string> = {
  accessibility: '辅助功能权限',
  automation: '自动化权限',
  automation_or_accessibility: '自动化或辅助功能权限',
  camera: '相机权限',
  chrome_cdp: 'Chrome CDP 调试端口',
  files_and_folders: '文件和文件夹权限',
  full_disk_access: '完全磁盘访问权限',
  input_monitoring: '输入监控权限',
  microphone: '麦克风权限',
  music_app: 'Music.app',
  open_command: 'macOS open 命令',
  screen_capture_probe_failed: '屏幕录制探测失败',
  screen_recording: '屏幕录制权限',
  unsupported_platform: '当前平台暂不支持桌面执行',
};

const permissionRecoveryHints: Record<string, string> = {
  accessibility: '需要在 macOS「系统设置 > 隐私与安全性 > 辅助功能」允许 Oha-Yachiyo。',
  automation: '需要在 macOS「系统设置 > 隐私与安全性 > 自动化」允许 Oha-Yachiyo 控制相关应用。',
  automation_or_accessibility: '需要打开自动化或辅助功能权限，才能读取前台窗口和控制应用。',
  camera: '需要在 macOS「系统设置 > 隐私与安全性 > 相机」允许 Oha-Yachiyo 或当前运行环境。',
  chrome_cdp: '需要配置可访问的 Chrome CDP 调试端口；无法连接时浏览器工具会降级。',
  files_and_folders: '需要在 macOS「系统设置 > 隐私与安全性 > 文件和文件夹」允许 Oha-Yachiyo 访问目标文件夹。',
  full_disk_access: '需要在 macOS「系统设置 > 隐私与安全性 > 完全磁盘访问」允许 Oha-Yachiyo 访问本地文件。',
  input_monitoring: '需要在 macOS「系统设置 > 隐私与安全性 > 输入监控」允许 Oha-Yachiyo 监听键盘输入。',
  microphone: '需要在 macOS「系统设置 > 隐私与安全性 > 麦克风」允许 Oha-Yachiyo 或当前运行环境。',
  music_app: 'Music.app 未安装、无法启动，或暂时不可被自动化控制；请在诊断页打开 Music.app 后重试。',
  open_command: 'macOS open 命令不可用，应用打开与聚焦工具无法执行。',
  screen_capture_probe_failed: '屏幕录制探测失败；请在诊断页重新运行截图摘要。',
  screen_recording: '需要在 macOS「系统设置 > 隐私与安全性 > 屏幕录制」允许 Oha-Yachiyo。',
  unsupported_platform: '当前平台暂不支持桌面执行；这些桌面工具会保持不可用。',
};

const blockingConditionLabels: Record<string, string> = {
  desktop_session_locked: '桌面会话已锁定',
  foreground_focus_unavailable: '前台激活暂不可用',
  screen_capture_blank: '屏幕画面为空黑',
};

const blockingConditionRecoveryHints: Record<string, string> = {
  desktop_session_locked: '请先解锁当前 macOS 桌面会话，然后重试前台窗口、点击或输入操作。',
  foreground_focus_unavailable: '当前运行环境无法把目标应用切到最前；请在诊断页重新探测桌面权限和前台窗口状态。',
  screen_capture_blank: '当前截图为空黑画面；请唤醒或解锁桌面会话，并确认远程显示没有黑屏。',
};

export function chatDesktopPermissionNotice(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): Pick<
  ChatNotice,
  'kind' | 'title' | 'detail' | 'action_label' | 'action_view' | 'action_params'
> | null {
  const missing = missingDesktopPermissionIssues(readiness);
  const blocking = desktopRuntimeBlockingIssues(readiness);
  const toolReadiness = desktopToolReadinessSummary(readiness);
  const providerReadiness = desktopProviderReadinessSummary(readiness);
  if (
    !missing.length
    && !blocking.length
    && !toolReadiness.degraded.length
    && !toolReadiness.unavailable.length
  ) return null;
  const labels = missing.map((issue) => issue.label);
  const blockerLabels = blocking.map((issue) => issue.label);
  const hints = [
    ...missing.map((issue) => issue.recovery_hint),
    ...blocking.map((issue) => issue.recovery_hint),
  ].filter(Boolean);
  const details = [
    labels.length ? `${labels.join('、')} 未就绪。` : '',
    blockerLabels.length ? `${blockerLabels.join('、')} 正在阻塞桌面执行。` : '',
    toolReadiness.degraded.length ? `降级可用：${formatDesktopToolList(toolReadiness.degraded)}。` : '',
    toolReadiness.unavailable.length ? `暂不可用：${formatDesktopToolList(toolReadiness.unavailable)}。` : '',
    providerReadiness.detail,
    hints.join(' ') || '打开「诊断」中的桌面能力检查，按提示处理后再试。',
  ].filter(Boolean);
  const actionParams: Record<string, string> = {
    command: 'native doctor',
    return_to: 'chat',
  };
  if (missing.length) actionParams.permission_targets = missing.map((issue) => issue.token).join(',');
  if (blocking.length) actionParams.blocking_conditions = blocking.map((issue) => issue.token).join(',');
  if (toolReadiness.tools.length) actionParams.desktop_tools = toolReadiness.tools.join(',');
  if (providerReadiness.provider_id) actionParams.desktop_provider_id = providerReadiness.provider_id;
  if (providerReadiness.status) actionParams.desktop_provider_status = providerReadiness.status;
  if (providerReadiness.supported_tools.length) {
    actionParams.desktop_provider_tools = providerReadiness.supported_tools.join(',');
  }
  return {
    kind: 'warn',
    title: missing.length
      ? '桌面执行权限未就绪'
      : blocking.length
        ? '桌面运行条件需处理'
        : '桌面执行能力需检查',
    detail: details.join(''),
    action_label: '打开诊断',
    action_view: 'diagnostics',
    action_params: actionParams,
  };
}

export function desktopProviderReadinessSummary(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): {
  ready: boolean;
  available: boolean;
  status: string;
  provider_id: string;
  provider_kind: string;
  supported_tools: string[];
  blocking_conditions: string[];
  detail: string;
} {
  const capabilities = readiness?.capabilities;
  if (!capabilities || typeof capabilities !== 'object') {
    return emptyProviderReadiness();
  }
  const provider = recordValue(capabilities.sandbox_provider);
  const status = stringValue(provider?.status);
  const providerId = stringValue(provider?.provider_id);
  const providerKind = stringValue(provider?.provider_kind);
  const supportedTools = uniqueStrings([
    ...stringList(provider?.supported_tools),
    ...stringList(capabilities.desktop_provider_supported_tools),
  ]);
  const blockingConditions = stringList(provider?.blocking_conditions);
  const available = booleanValue(provider?.available);
  const adapterReady = booleanValue(provider?.adapter_ready);
  const ready = booleanValue(capabilities.desktop_provider_ready)
    || (available && adapterReady);
  const detail = ready
    ? `隔离桌面 provider 已就绪${supportedTools.length ? `，支持 ${formatDesktopToolList(toolDisplayLabels(supportedTools))}` : ''}。`
    : providerId || status
      ? '隔离桌面 provider 未就绪；前台点击、输入或快捷键会保持预览、审批或转入 Agent Studio。'
      : '';
  return {
    ready,
    available,
    status,
    provider_id: providerId,
    provider_kind: providerKind,
    supported_tools: supportedTools,
    blocking_conditions: blockingConditions,
    detail,
  };
}

export function missingDesktopPermissionLabels(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): string[] {
  return missingDesktopPermissionIssues(readiness).map((issue) => issue.label);
}

export function missingDesktopPermissionIssues(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): Array<{ token: string; label: string; recovery_hint: string }> {
  const capabilities = readiness?.capabilities;
  if (!capabilities || typeof capabilities !== 'object') return [];
  const issues = new Map<string, { token: string; label: string; recovery_hint: string }>();
  desktopCapabilityIds.forEach((capabilityId) => {
    const capability = capabilitySnapshot(capabilities[capabilityId]);
    (capability?.missing_permissions || []).forEach((permission) => {
      const token = String(permission || '').trim();
      if (!token) return;
      if (issues.has(token)) return;
      issues.set(token, {
        token,
        label: permissionLabels[token] || token,
        recovery_hint: permissionRecoveryHints[token] || `请在诊断页检查 ${permissionLabels[token] || token}。`,
      });
    });
  });
  return Array.from(issues.values());
}

export function desktopRuntimeBlockingIssues(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): Array<{ token: string; label: string; recovery_hint: string }> {
  const capabilities = readiness?.capabilities;
  if (!capabilities || typeof capabilities !== 'object') return [];
  const issues = new Map<string, { token: string; label: string; recovery_hint: string }>();
  desktopCapabilityIds.forEach((capabilityId) => {
    const capability = capabilitySnapshot(capabilities[capabilityId]);
    (capability?.blocking_conditions || []).forEach((condition) => {
      const token = String(condition || '').trim();
      if (!token) return;
      if (issues.has(token)) return;
      issues.set(token, {
        token,
        label: blockingConditionLabels[token] || token,
        recovery_hint: blockingConditionRecoveryHints[token] || `请在诊断页检查 ${blockingConditionLabels[token] || token}。`,
      });
    });
  });
  return Array.from(issues.values());
}

export function desktopToolReadinessSummary(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): { degraded: string[]; unavailable: string[]; tools: string[] } {
  const capabilities = readiness?.capabilities;
  if (!capabilities || typeof capabilities !== 'object') return { degraded: [], unavailable: [], tools: [] };
  const root = capabilitySnapshot(capabilities.desktop_execution);
  const degraded = toolDisplayLabels(root?.degraded_tools || []);
  const unavailable = toolDisplayLabels(root?.unavailable_tools || []);
  return {
    degraded,
    unavailable,
    tools: uniqueStrings([...(root?.degraded_tools || []), ...(root?.unavailable_tools || [])]),
  };
}

function capabilitySnapshot(value: unknown): DesktopExecutionCapabilitySnapshot | null {
  if (!value || typeof value !== 'object') return null;
  return value as DesktopExecutionCapabilitySnapshot;
}

function emptyProviderReadiness() {
  return {
    ready: false,
    available: false,
    status: '',
    provider_id: '',
    provider_kind: '',
    supported_tools: [],
    blocking_conditions: [],
    detail: '',
  };
}

function recordValue(value: unknown): Record<string, unknown> | null {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return null;
  return value as Record<string, unknown>;
}

function stringValue(value: unknown): string {
  return String(value || '').trim();
}

function booleanValue(value: unknown): boolean {
  return value === true || value === 'true' || value === '1';
}

function stringList(value: unknown): string[] {
  if (!Array.isArray(value)) return [];
  return value.map((item) => String(item || '').trim()).filter(Boolean);
}

function toolDisplayLabels(values: string[]) {
  return uniqueStrings(values.map((tool) => runtimeToolDisplayLabelOrName(tool)));
}

function formatDesktopToolList(values: string[]) {
  if (values.length <= 4) return values.join('、');
  return `${values.slice(0, 4).join('、')} 等 ${values.length} 项`;
}

function uniqueStrings(values: string[]) {
  const result: string[] = [];
  values.forEach((value) => {
    const clean = String(value || '').trim();
    if (clean && !result.includes(clean)) result.push(clean);
  });
  return result;
}
