import type { DesktopExecutionCapabilitySnapshot } from '../runtime-shared/types';
import type { ChatNotice, YachiyoReadinessSnapshot } from './types';

const desktopCapabilityIds = [
  'desktop_execution',
  'screen_capture',
  'active_window',
  'app_control',
  'media_control',
  'foreground_input',
  'browser_control',
];

const permissionLabels: Record<string, string> = {
  accessibility: '辅助功能权限',
  automation: '自动化权限',
  automation_or_accessibility: '自动化或辅助功能权限',
  chrome_cdp: 'Chrome CDP 调试端口',
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
  chrome_cdp: '需要配置可访问的 Chrome CDP 调试端口；无法连接时浏览器工具会降级。',
  music_app: 'Music.app 未安装、无法启动，或暂时不可被自动化控制；请在诊断页打开 Music.app 后重试。',
  open_command: 'macOS open 命令不可用，应用打开与聚焦工具无法执行。',
  screen_capture_probe_failed: '屏幕录制探测失败；请在诊断页重新运行截图摘要。',
  screen_recording: '需要在 macOS「系统设置 > 隐私与安全性 > 屏幕录制」允许 Oha-Yachiyo。',
  unsupported_platform: '当前平台暂不支持桌面执行；这些桌面工具会保持不可用。',
};

export function chatDesktopPermissionNotice(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): Pick<
  ChatNotice,
  'kind' | 'title' | 'detail' | 'action_label' | 'action_view' | 'action_params'
> | null {
  const missing = missingDesktopPermissionIssues(readiness);
  if (!missing.length) return null;
  const labels = missing.map((issue) => issue.label);
  const hints = missing.map((issue) => issue.recovery_hint).filter(Boolean);
  return {
    kind: 'warn',
    title: '桌面执行权限未就绪',
    detail: `${labels.join('、')} 未就绪。${hints.join(' ') || '打开「诊断」中的桌面权限检查，按提示授权后再试。'}`,
    action_label: '打开诊断',
    action_view: 'diagnostics',
    action_params: {
      command: 'native doctor',
      permission_targets: missing.map((issue) => issue.token).join(','),
      return_to: 'chat',
    },
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

function capabilitySnapshot(value: unknown): DesktopExecutionCapabilitySnapshot | null {
  if (!value || typeof value !== 'object') return null;
  return value as DesktopExecutionCapabilitySnapshot;
}
