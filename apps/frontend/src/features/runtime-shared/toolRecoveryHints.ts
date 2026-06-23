export function runtimeToolRecoveryHintsFromRecords(sources: Array<Record<string, unknown>>): string[] {
  return uniqueStrings(sources.flatMap((source) => runtimeToolRecoveryHintsFromRecord(source)));
}

export function runtimeToolRecoveryHintsFromRecord(source: Record<string, unknown>): string[] {
  const explicitHints = stringList(source.recovery_hints);
  if (explicitHints.length) return explicitHints;

  const error = String(source.error || '').trim();
  const hints: string[] = [];
  if (error === 'browser_click_fallback_coordinates_required') {
    const data = objectValue(source.data);
    const fields = stringList(data.required_fallback_fields);
    const tools = stringList(data.recommended_tools);
    const fieldText = fields.length ? fields.join('/') : 'fallback_x/fallback_y';
    const toolText = tools.length ? tools.join(' -> ') : 'screen.capture -> desktop.click';
    hints.push(`Chrome CDP 不可用时不能直接用 CSS selector 点击；请先用 ${toolText} 观察目标位置，再提供 ${fieldText} 坐标。`);
  }
  hints.push(...permissionRecoveryHints(source));
  return uniqueStrings(hints);
}

function permissionRecoveryHints(source: Record<string, unknown>): string[] {
  if (source.permission_error !== true && !source.permission_targets && !source.missing_permissions) return [];
  const targets = uniqueStrings([
    ...stringList(source.permission_targets),
    ...stringList(source.missing_permissions),
  ]);
  return targets
    .map((target) => PERMISSION_RECOVERY_HINTS[target] || '')
    .filter(Boolean);
}

const PERMISSION_RECOVERY_HINTS: Record<string, string> = {
  accessibility: '在 macOS「系统设置 > 隐私与安全性 > 辅助功能」允许 Oha-Yachiyo 或当前终端控制电脑。',
  automation: '在 macOS「系统设置 > 隐私与安全性 > 自动化」允许 Oha-Yachiyo 控制 System Events、Music 或目标应用。',
  automation_or_accessibility: '在 macOS 隐私设置中检查自动化和辅助功能权限；当前动作通常至少需要其中一项。',
  chrome_cdp: 'Chrome CDP 不可用；请启动带 remote debugging 的 Chrome，或改用 screen.capture 加前台点击/输入工具。',
  music_app: '先打开 Music.app 并确认资料库里有目标歌曲；如果系统弹出自动化授权，请允许 Oha-Yachiyo 控制 Music。',
  open_command: '确认 macOS open 命令可用，并检查应用名称是否和系统里的应用名称一致。',
  screen_recording: '在 macOS「系统设置 > 隐私与安全性 > 屏幕录制」允许 Oha-Yachiyo 或当前终端录制屏幕。',
  unsupported_platform: '当前桌面工具主要支持 macOS；此平台暂时只能使用非桌面 fallback。',
};

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
