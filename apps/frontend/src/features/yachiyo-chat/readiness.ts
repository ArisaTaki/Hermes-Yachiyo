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

export type BackgroundControlReadinessStatus =
  | 'ready'
  | 'installed_unchecked'
  | 'setup_required'
  | 'attention'
  | 'unknown';

export type BackgroundControlReadiness = {
  status: BackgroundControlReadinessStatus;
  statusLabel: string;
  summary: string;
  safetyPromise: string;
  configured: boolean | null;
  available: boolean | null;
  adapterReady: boolean | null;
  healthChecked: boolean | null;
  healthOk: boolean | null;
  providerId: string;
  kind: string;
  supportedTools: string[];
  desktopSessionIsolated: boolean | null;
  foregroundTakeoverRequired: boolean | null;
  blockers: string[];
};

/**
 * Projects the passive readiness snapshot into consumer-facing background
 * control states. Missing booleans stay unknown: installation, health and
 * permission readiness must never be inferred from a provider name or status.
 */
export function backgroundControlReadiness(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): BackgroundControlReadiness {
  const capabilities = recordValue(readiness?.capabilities);
  const provider = recordValue(capabilities?.sandbox_provider);
  const health = recordValue(provider?.health);
  const providerId = stringValue(provider?.provider_id || health?.provider_id);
  const kind = stringValue(provider?.provider_kind || health?.provider_kind);
  const configured = strictBooleanValue(provider?.configured);
  const available = strictBooleanValue(provider?.available);
  const adapterReady = strictBooleanValue(provider?.adapter_ready);
  const healthChecked = strictBooleanValue(health?.checked);
  const healthOk = strictBooleanValue(health?.ok);
  const supportedTools = uniqueStrings([
    ...stringList(provider?.supported_tools),
    ...stringList(health?.supported_tools),
    ...stringList(capabilities?.desktop_provider_supported_tools),
  ]);
  const desktopSessionIsolated = firstKnownBoolean(
    provider?.desktop_session_isolated,
    health?.desktop_session_isolated,
  );
  const foregroundTakeoverRequired = firstKnownBoolean(
    provider?.foreground_takeover_required,
    health?.foreground_takeover_required,
  );
  const blockers = uniqueStrings([
    ...stringList(provider?.blocking_conditions),
    ...stringList(health?.blocking_conditions),
  ]);

  let status: BackgroundControlReadinessStatus = 'unknown';
  if (kind === 'background_desktop') {
    if (configured === false) {
      status = 'setup_required';
    } else if (configured === true && healthChecked === false) {
      status = 'installed_unchecked';
    } else if (configured === true && healthChecked === true) {
      status = healthOk === true
        && available === true
        && adapterReady === true
        && foregroundTakeoverRequired === false
        && blockers.length === 0
        ? 'ready'
        : 'attention';
    }
  }

  const consumerCopy: Record<
    BackgroundControlReadinessStatus,
    { statusLabel: string; summary: string }
  > = {
    ready: {
      statusLabel: '可以使用',
      summary: '已就绪，可以在后台操作支持的应用。',
    },
    installed_unchecked: {
      statusLabel: '首次使用时确认',
      summary: '后台操作组件已安装；首次实际使用时会确认运行条件。',
    },
    setup_required: {
      statusLabel: '需要设置',
      summary: '尚未完成后台操控设置，相关任务会安全暂停。',
    },
    attention: {
      statusLabel: '需要处理',
      summary: '后台操控暂不可用，相关任务会安全暂停。',
    },
    unknown: {
      statusLabel: '状态待确认',
      summary: '暂时无法确认后台操控状态，相关任务不会接管前台。',
    },
  };

  return {
    status,
    ...consumerCopy[status],
    safetyPromise: '默认不移动你的鼠标、不切换当前窗口；无法保持后台时会暂停，不会自动接管前台。',
    configured,
    available,
    adapterReady,
    healthChecked,
    healthOk,
    providerId,
    kind,
    supportedTools,
    desktopSessionIsolated,
    foregroundTakeoverRequired,
    blockers,
  };
}

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
  const backgroundProviderInstalledUnchecked = Boolean(
    providerReadiness.provider_kind === 'background_desktop'
    && providerReadiness.status === 'installed_not_checked',
  );
  const visibleToolReadiness = backgroundProviderInstalledUnchecked
    ? { degraded: [], unavailable: [], tools: [] }
    : toolReadiness;
  const visibleBlocking = backgroundProviderInstalledUnchecked
    ? blocking.filter((issue) => issue.token !== 'desktop_permission_diagnostics_not_checked')
    : blocking;
  const providerNeedsAttention = Boolean(
    providerReadiness.provider_id
    && !providerReadiness.ready
    && !backgroundProviderInstalledUnchecked,
  );
  const browserEnhancementOnly = Boolean(
    providerReadiness.provider_kind === 'local_desktop'
    && providerReadiness.ready
    && missing.length
    && missing.every((issue) => issue.token === 'chrome_cdp')
    && !visibleBlocking.length
    && toolReadiness.tools.every((tool) => tool.startsWith('browser.'))
  );
  // Chrome CDP is an optional browser enhancement. When Direct Desktop is
  // healthy, keep the limitation in Tools/Diagnostics and surface it only if
  // a browser action needs CDP instead of covering every Chat/Launcher view.
  if (browserEnhancementOnly) return null;
  if (
    !missing.length
    && !visibleBlocking.length
    && !visibleToolReadiness.degraded.length
    && !visibleToolReadiness.unavailable.length
    && !providerNeedsAttention
  ) return null;
  const labels = missing.map((issue) => issue.label);
  const blockerLabels = visibleBlocking.map((issue) => issue.label);
  const hints = [
    ...missing.map((issue) => issue.recovery_hint),
    ...visibleBlocking.map((issue) => issue.recovery_hint),
  ].filter(Boolean);
  const details = [
    labels.length ? `${labels.join('、')} 未就绪。` : '',
    blockerLabels.length ? `${blockerLabels.join('、')} 正在阻塞桌面执行。` : '',
    visibleToolReadiness.degraded.length ? `降级可用：${formatDesktopToolList(visibleToolReadiness.degraded)}。` : '',
    visibleToolReadiness.unavailable.length ? `暂不可用：${formatDesktopToolList(visibleToolReadiness.unavailable)}。` : '',
    providerReadiness.detail,
    hints.join(' ') || '打开「诊断」中的桌面能力检查，按提示处理后再试。',
  ].filter(Boolean);
  const actionParams: Record<string, string> = {
    command: 'native doctor',
    return_to: 'chat',
  };
  if (missing.length) actionParams.permission_targets = missing.map((issue) => issue.token).join(',');
  if (visibleBlocking.length) {
    actionParams.blocking_conditions = visibleBlocking.map((issue) => issue.token).join(',');
  }
  if (visibleToolReadiness.tools.length) actionParams.desktop_tools = visibleToolReadiness.tools.join(',');
  if (providerReadiness.provider_id) actionParams.desktop_provider_id = providerReadiness.provider_id;
  if (providerReadiness.status) actionParams.desktop_provider_status = providerReadiness.status;
  if (providerReadiness.supported_tools.length) {
    actionParams.desktop_provider_tools = providerReadiness.supported_tools.join(',');
  }
  if (providerReadiness.controlled_provider_id) {
    actionParams.controlled_desktop_provider_id = providerReadiness.controlled_provider_id;
  }
  if (providerReadiness.controlled_env_url) {
    actionParams.controlled_desktop_provider_url = providerReadiness.controlled_env_url;
  }
  return {
    kind: 'warn',
    title: missing.length
      ? '桌面执行权限未就绪'
      : visibleBlocking.length
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
  foreground_mutation_supported: boolean;
  keyboard_mouse_capture_supported: boolean;
  requires_real_sandbox_for: string[];
  controlled_provider_id: string;
  controlled_env_url: string;
  controlled_command: string[];
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
  const launchHint = recordValue(provider?.launch_hint);
  const controlledProvider = recordValue(launchHint?.controlled_provider);
  const controlledEnv = recordValue(controlledProvider?.env);
  const controlledProviderId = stringValue(controlledProvider?.provider_id);
  const controlledEnvUrl = stringValue(controlledEnv?.OHA_YACHIYO_DESKTOP_PROVIDER_URL);
  const controlledCommand = stringList(controlledProvider?.command);
  const foregroundMutationSupported = booleanValue(provider?.foreground_mutation_supported);
  const keyboardMouseCaptureKnown = Boolean(
    provider && Object.prototype.hasOwnProperty.call(provider, 'keyboard_mouse_capture_supported'),
  );
  const keyboardMouseCaptureSupported = booleanValue(provider?.keyboard_mouse_capture_supported);
  const requiresRealSandboxFor = uniqueStrings([
    ...stringList(provider?.requires_real_sandbox_for),
    ...stringList(capabilities.desktop_provider_requires_real_sandbox_for),
  ]);
  const available = booleanValue(provider?.available);
  const adapterReady = booleanValue(provider?.adapter_ready);
  const health = recordValue(provider?.health);
  const healthChecked = booleanValue(health?.checked);
  const healthOk = booleanValue(health?.ok);
  const healthStatus = stringValue(health?.status);
  const backendReleaseReady = booleanValue(provider?.desktop_backend_ready_for_public_release);
  const localProvider = providerKind === 'local_desktop';
  const backgroundProvider = providerKind === 'background_desktop';
  const backgroundProviderInstalledUnchecked = backgroundProvider
    && status === 'installed_not_checked'
    && !healthChecked;
  const ready = localProvider
    ? available && adapterReady && healthChecked && healthOk && backendReleaseReady
    : backgroundProvider
      ? available && adapterReady && healthChecked && healthOk
      : booleanValue(capabilities.desktop_provider_ready) || (available && adapterReady);
  const providerLabel = localProvider
    ? '当前桌面'
    : backgroundProvider
      ? '后台操作组件'
      : '隔离桌面';
  const inputSandboxLimited = ready
    && keyboardMouseCaptureKnown
    && !keyboardMouseCaptureSupported
    && requiresRealSandboxFor.length > 0;
  const detail = ready
    ? backgroundProvider && !healthChecked
      ? `${providerLabel}已安装；首次执行会检查权限。默认不移动真实鼠标，应用无法保持后台时会暂停，不会自动改用前台控制。`
      : inputSandboxLimited
      ? `${providerLabel} 已就绪${supportedTools.length ? `，支持 ${formatDesktopToolList(toolDisplayLabels(supportedTools))}` : ''}；点击、输入和快捷键仍需要真实沙盒或受监管控制通道${controlledCommand.length ? `，可在 Agent Studio 启动 ${controlledProviderId || 'controlled provider'}。` : '。'}`
      : `${providerLabel} 已就绪${supportedTools.length ? `，支持 ${formatDesktopToolList(toolDisplayLabels(supportedTools))}` : ''}。`
    : providerId || status
      ? localProvider
        ? healthStatus === 'permission_required'
          ? `${providerLabel} 运行时已安装，但当前主机权限或桌面会话未就绪。`
          : `${providerLabel} 运行时已安装，但尚未通过生产 Broker 与权限检查。`
        : backgroundProvider
          ? backgroundProviderInstalledUnchecked
            ? `${providerLabel}已安装；首次执行会检查权限。默认不移动真实鼠标，应用无法保持后台时会暂停，不会自动改用前台控制。`
            : `${providerLabel} 未就绪；需要操作软件时会暂停等待设置，不会自动改用前台控制。`
          : `${providerLabel} 未就绪；前台点击、输入或快捷键会保持预览、审批或转入 Agent Studio。`
      : '';
  return {
    ready,
    available,
    status,
    provider_id: providerId,
    provider_kind: providerKind,
    supported_tools: supportedTools,
    blocking_conditions: blockingConditions,
    foreground_mutation_supported: foregroundMutationSupported,
    keyboard_mouse_capture_supported: keyboardMouseCaptureSupported,
    requires_real_sandbox_for: requiresRealSandboxFor,
    controlled_provider_id: controlledProviderId,
    controlled_env_url: controlledEnvUrl,
    controlled_command: controlledCommand,
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
    foreground_mutation_supported: false,
    keyboard_mouse_capture_supported: false,
    requires_real_sandbox_for: [],
    controlled_provider_id: '',
    controlled_env_url: '',
    controlled_command: [],
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

function strictBooleanValue(value: unknown): boolean | null {
  return typeof value === 'boolean' ? value : null;
}

function firstKnownBoolean(...values: unknown[]): boolean | null {
  for (const value of values) {
    const known = strictBooleanValue(value);
    if (known !== null) return known;
  }
  return null;
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
