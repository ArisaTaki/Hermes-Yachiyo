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

export function chatDesktopPermissionNotice(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): Pick<
  ChatNotice,
  'kind' | 'title' | 'detail' | 'action_label' | 'action_view' | 'action_params'
> | null {
  const missing = missingDesktopPermissionLabels(readiness);
  if (!missing.length) return null;
  return {
    kind: 'warn',
    title: '桌面执行权限未就绪',
    detail: `${missing.join('、')} 未就绪；打开「诊断」中的桌面权限检查，按提示授权后再试。`,
    action_label: '打开诊断',
    action_view: 'diagnostics',
    action_params: {
      command: 'native doctor',
      return_to: 'chat',
    },
  };
}

export function missingDesktopPermissionLabels(
  readiness: YachiyoReadinessSnapshot | null | undefined,
): string[] {
  const capabilities = readiness?.capabilities;
  if (!capabilities || typeof capabilities !== 'object') return [];
  const labels = new Set<string>();
  desktopCapabilityIds.forEach((capabilityId) => {
    const capability = capabilitySnapshot(capabilities[capabilityId]);
    (capability?.missing_permissions || []).forEach((permission) => {
      const token = String(permission || '').trim();
      if (!token) return;
      labels.add(permissionLabels[token] || token);
    });
  });
  return Array.from(labels);
}

function capabilitySnapshot(value: unknown): DesktopExecutionCapabilitySnapshot | null {
  if (!value || typeof value !== 'object') return null;
  return value as DesktopExecutionCapabilitySnapshot;
}
