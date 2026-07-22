export function formatApprovalInput(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return String(value || '');
  }
}

export function approvalPreviewRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

export function approvalPreviewValue(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  }
  return '';
}

export function approvalPreviewTarget(record: Record<string, unknown>, toolName = ''): string {
  const tool = String(toolName || '').trim();
  if (tool === 'desktop.hotkey') {
    const hotkey = hotkeyPreview(record);
    return hotkey ? `快捷键 ${hotkey}` : '';
  }
  if (tool === 'desktop.type_text') {
    const text = textInputPreview(record, ['text']);
    return text ? `输入 ${text}` : '';
  }
  if (
    tool === 'desktop.click_ui_element'
    || tool === 'app.open_and_click_ui_element'
    || tool === 'app.focus_and_click_ui_element'
  ) {
    const target = approvalPreviewValue(record, ['target']);
    return target ? `点击「${target}」` : '';
  }
  if (
    tool === 'desktop.type_into_ui_element'
    || tool === 'app.open_and_type_into_ui_element'
    || tool === 'app.focus_and_type_into_ui_element'
  ) {
    const target = approvalPreviewValue(record, ['target']);
    const text = textInputPreview(record, ['text']);
    if (target && text) return `在「${target}」输入 ${text}`;
    return text || target;
  }
  if (tool === 'desktop.safe_click') return coordinateClickPreview(record);
  if (tool === 'desktop.click') return coordinateClickPreview(record);
  if (tool === 'browser.click') {
    const selector = approvalPreviewValue(record, ['selector']);
    if (selector) return `点击 ${selector}`;
    const fallback = coordinateClickPreview(record, ['fallback_x', 'fallback_y']);
    return fallback ? `回退${fallback}` : '';
  }
  if (tool === 'browser.type_text') {
    const selector = approvalPreviewValue(record, ['selector']);
    const text = textInputPreview(record, ['text']);
    if (selector && text) return `${selector} · 输入 ${text}`;
    if (text) return `输入 ${text}`;
    return selector;
  }
  return approvalPreviewValue(record, [
    'command',
    'cmd',
    'path',
    'file',
    'target',
    'app_name',
    'query',
    'url',
    'selector',
    'key',
    'reason',
  ]);
}

function hotkeyPreview(record: Record<string, unknown>): string {
  const key = approvalPreviewValue(record, ['key']);
  const modifiers = Array.isArray(record.modifiers)
    ? record.modifiers.map((item) => hotkeyPartLabel(item)).filter(Boolean)
    : [];
  return [...modifiers, hotkeyPartLabel(key)].filter(Boolean).join('+');
}

function hotkeyPartLabel(value: unknown): string {
  const part = String(value || '').trim();
  if (!part) return '';
  const normalized = part.toLowerCase();
  if (normalized === 'cmd' || normalized === 'command') return 'Command';
  if (normalized === 'ctrl' || normalized === 'control') return 'Control';
  if (normalized === 'alt' || normalized === 'option') return 'Option';
  if (normalized === 'shift') return 'Shift';
  if (normalized === 'return') return 'Return';
  if (normalized === 'escape') return 'Escape';
  if (normalized === 'space') return 'Space';
  if (normalized === 'tab') return 'Tab';
  if (normalized.length === 1) return normalized.toUpperCase();
  return part;
}

function textInputPreview(record: Record<string, unknown>, keys: string[]): string {
  const text = approvalPreviewValue(record, keys);
  if (!text) return '';
  const compact = text.replace(/\s+/g, ' ');
  const clipped = compact.length > 48 ? `${compact.slice(0, 48)}...` : compact;
  return `「${clipped}」`;
}

function coordinateClickPreview(
  record: Record<string, unknown>,
  keys: [string, string] = ['x', 'y'],
): string {
  const x = approvalPreviewValue(record, [keys[0]]);
  const y = approvalPreviewValue(record, [keys[1]]);
  if (!x || !y) return '';
  const clickCount = Number(record.click_count || 1);
  const action = clickCount === 2 ? '双击' : clickCount > 2 ? `点击 x${clickCount}` : '点击';
  return `${action} ${x}, ${y}`;
}

export function runtimeToolDisplayLabel(toolName: string, desktopExecutionRoute?: unknown): string {
  const tool = String(toolName || '').trim();
  if (tool === 'terminal.run') return '运行终端命令';
  if (tool === 'workspace.write_patch') return '写入工作区文件';
  if (tool === 'workspace.read' || tool === 'workspace.list') return '读取工作区';
  if (tool === 'artifact.write') return '生成产物';
  if (tool === 'workflow.approval') return 'Workflow 人工确认';
  if (tool === 'group.approval') return '群组人工确认';
  if (tool === 'screen.capture') return '截取屏幕';
  if (tool === 'desktop.active_window') return '读取当前窗口';
  if (tool === 'app.open') return '打开应用';
  if (tool === 'app.focus') return '聚焦应用';
  if (tool === 'app.open_and_safe_type_text') return '打开应用并输入文字';
  if (tool === 'app.focus_and_safe_type_text') return '聚焦应用并输入文字';
  if (tool === 'app.open_and_safe_shortcut') return '打开应用并执行快捷动作';
  if (tool === 'app.focus_and_safe_shortcut') return '聚焦应用并执行快捷动作';
  if (tool === 'app.open_and_click_ui_element') {
    return runtimeDesktopExecutionSurface(desktopExecutionRoute) === 'background'
      ? '后台打开应用并点击界面'
      : '打开应用并点击界面';
  }
  if (tool === 'app.focus_and_click_ui_element') return '在指定应用中点击界面';
  if (tool === 'app.open_and_type_into_ui_element') {
    return runtimeDesktopExecutionSurface(desktopExecutionRoute) === 'background'
      ? '后台打开应用并填写文字'
      : '打开应用并填写文字';
  }
  if (tool === 'app.focus_and_type_into_ui_element') return '在指定应用中填写文字';
  if (tool === 'media.apple_music_play') return '播放 Apple Music';
  if (tool === 'media.apple_music_control') return '控制 Apple Music';
  if (tool === 'desktop.safe_shortcut') return '执行快捷动作';
  if (tool === 'desktop.safe_type_text') {
    const surface = runtimeDesktopExecutionSurface(desktopExecutionRoute);
    if (surface === 'background') return '后台向指定应用输入文字';
    if (surface === 'foreground') return '输入前台文字';
    return '输入文字';
  }
  if (tool === 'desktop.safe_click') {
    const surface = runtimeDesktopExecutionSurface(desktopExecutionRoute);
    if (surface === 'background') return '后台点击指定应用界面';
    if (surface === 'foreground') return '点击前台界面';
    return '点击界面';
  }
  if (tool === 'desktop.click_ui_element') {
    const surface = runtimeDesktopExecutionSurface(desktopExecutionRoute);
    if (surface === 'background') return '后台点击指定应用控件';
    if (surface === 'foreground') return '点击前台应用控件';
    return '点击应用控件';
  }
  if (tool === 'desktop.type_into_ui_element') {
    const surface = runtimeDesktopExecutionSurface(desktopExecutionRoute);
    if (surface === 'background') return '后台向指定应用控件输入文字';
    if (surface === 'foreground') return '向前台应用控件输入文字';
    return '向应用控件输入文字';
  }
  if (tool === 'desktop.hotkey') return '发送快捷键';
  if (tool === 'desktop.type_text') return '输入前台文字';
  if (tool === 'desktop.click') return '点击前台界面';
  if (tool === 'browser.open_url') return '打开网页';
  if (tool === 'browser.open_url_and_extract_text') return '打开并读取网页';
  if (tool === 'browser.open_url_and_screenshot') return '打开并截取网页';
  if (tool === 'browser.current_page') return '读取当前网页';
  if (tool === 'browser.click') return '点击网页元素';
  if (tool === 'browser.type_text') return '填写网页输入';
  if (tool === 'browser.extract_text') return '提取网页文本';
  if (tool === 'browser.screenshot') return '截取网页';
  return '工具调用';
}

export function runtimeToolDisplayLabelOrName(toolName: string, desktopExecutionRoute?: unknown): string {
  const tool = String(toolName || '').trim();
  const display = runtimeToolDisplayLabel(tool, desktopExecutionRoute);
  if (display !== '工具调用') return display;
  if (runtimeToolLooksInternalId(tool)) return display;
  return tool || display;
}

export function runtimeToolFamily(toolName: string): string {
  const tool = String(toolName || '').trim();
  if (
    tool === 'screen.capture'
    || tool === 'desktop.active_window'
    || tool === 'app.open'
    || tool === 'app.focus'
    || tool === 'app.open_and_click_ui_element'
    || tool === 'app.focus_and_click_ui_element'
    || tool === 'app.open_and_type_into_ui_element'
    || tool === 'app.focus_and_type_into_ui_element'
    || tool === 'media.apple_music_play'
    || tool === 'media.apple_music_control'
    || tool === 'desktop.safe_shortcut'
    || tool === 'desktop.safe_type_text'
    || tool === 'desktop.safe_click'
    || tool === 'desktop.hotkey'
    || tool === 'desktop.type_text'
    || tool === 'desktop.click'
    || tool === 'desktop.click_ui_element'
    || tool === 'desktop.type_into_ui_element'
  ) {
    return 'desktop';
  }
  if (tool.startsWith('browser.')) return 'browser';
  if (tool.startsWith('workspace.')) return 'workspace';
  if (tool.startsWith('terminal.')) return 'terminal';
  if (tool.startsWith('memory.')) return 'memory';
  if (tool.startsWith('skill.')) return 'skill';
  if (tool.startsWith('artifact.')) return 'artifact';
  if (tool.startsWith('future_task.')) return 'future_task';
  return 'tool';
}

function runtimeToolLooksInternalId(toolName: string): boolean {
  return /^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$/i.test(toolName)
    || /^[a-z][a-z0-9]+(?:_[a-z0-9]+)+$/i.test(toolName);
}

function runtimeDesktopExecutionSurface(route: unknown): 'background' | 'foreground' | 'neutral' {
  if (!route || typeof route !== 'object' || Array.isArray(route)) return 'neutral';
  const record = route as Record<string, unknown>;
  const providerKind = runtimeRouteString(record, ['selected_provider_kind', 'provider_kind']);
  const providerId = runtimeRouteString(record, ['selected_provider_id', 'provider_id']);
  const sessionKind = runtimeRouteString(record, ['desktop_session_kind']);
  const backendKind = runtimeRouteString(record, ['desktop_backend_kind']);
  if (
    providerKind === 'background_desktop'
    || sessionKind === 'background_desktop'
    || providerId === 'cua-driver'
    || backendKind === 'cua_driver'
    || backendKind === 'cua-driver'
  ) {
    return 'background';
  }
  if (
    providerKind === 'local_desktop'
    || sessionKind === 'user_foreground'
    || record.requires_user_foreground_session === true
    || record.foreground_takeover_required === true
  ) {
    return 'foreground';
  }
  return 'neutral';
}

function runtimeRouteString(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim().toLowerCase();
  }
  return '';
}
