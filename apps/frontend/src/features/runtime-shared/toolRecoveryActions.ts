export type RuntimeToolRecoveryAction = {
  action_kind?: 'permission_recovery' | 'retry_original';
  input: Record<string, unknown>;
  label: string;
  permission_target: string;
  prompt: string;
  recommended_tools?: string[];
  required_retry_fields?: string[];
  risk_level?: string;
  retry_input?: Record<string, unknown>;
  retry_input_schema?: Record<string, unknown>;
  retry_input_source?: string;
  retry_artifact_tool?: string;
  retry_artifact_kind?: string;
  retry_prompt?: string;
  retry_source_event_type?: string;
  retry_source_tool_call_id?: string;
  retry_tool?: string;
  tool: string;
};

export type RuntimeToolRecoveryRetryContext = Pick<
  RuntimeToolRecoveryAction,
  | 'recommended_tools'
  | 'required_retry_fields'
  | 'retry_input'
  | 'retry_input_schema'
  | 'retry_input_source'
  | 'retry_artifact_tool'
  | 'retry_artifact_kind'
  | 'retry_prompt'
  | 'retry_source_event_type'
  | 'retry_source_tool_call_id'
  | 'retry_tool'
>;

export type RuntimeToolRecoveryActionTaskMetadata = {
  daily_desktop_intent: true;
  desktop_permission_recovery: true;
  desktop_permission_retry?: true;
  recovery_action_kind?: RuntimeToolRecoveryAction['action_kind'];
  recovery_input: Record<string, unknown>;
  recovery_permission_target: string;
  recovery_risk_level?: string;
  recovery_retry_input?: Record<string, unknown>;
  recovery_retry_input_schema?: Record<string, unknown>;
  recovery_retry_input_source?: string;
  recovery_retry_artifact_tool?: string;
  recovery_retry_artifact_kind?: string;
  recovery_retry_prompt?: string;
  recovery_retry_source_event_type?: string;
  recovery_retry_source_tool_call_id?: string;
  recovery_retry_tool?: string;
  recommended_tools?: string[];
  required_retry_fields?: string[];
  recovery_tool: string;
} & Record<string, unknown>;

export const RUNTIME_TOOL_RECOVERY_TASK_METADATA_KEYS = [
  'daily_desktop_intent',
  'desktop_permission_recovery',
  'desktop_permission_retry',
  'recovery_action_kind',
  'recovery_tool',
  'recovery_input',
  'recovery_permission_target',
  'recovery_risk_level',
  'recovery_retry_tool',
  'recovery_retry_input',
  'recovery_retry_input_schema',
  'recovery_retry_input_source',
  'recovery_retry_artifact_tool',
  'recovery_retry_artifact_kind',
  'required_retry_fields',
  'recommended_tools',
  'recovery_retry_prompt',
  'recovery_retry_source_event_type',
  'recovery_retry_source_tool_call_id',
  'source_task_id',
  'source_task_title',
] as const;

export function runtimeToolRecoveryActionPrompt(action: RuntimeToolRecoveryAction): string {
  const tool = String(action.tool || '').trim();
  const input = objectValue(action.input);
  const prompt = String(action.prompt || '').trim();
  if (isExecutableRecoveryPrompt(prompt)) return prompt;
  const label = String(action.label || '').trim();
  if (isExecutableRecoveryPrompt(label)) return label;
  const fallbackPrompt = runtimeToolRecoveryExecutableLabel(tool, input);
  if (fallbackPrompt) return fallbackPrompt;
  return prompt || label || tool;
}

export function runtimeToolRecoveryActionTaskMetadata(
  action: RuntimeToolRecoveryAction,
  extra: Record<string, unknown> = {},
): RuntimeToolRecoveryActionTaskMetadata {
  const riskLevel = String(action.risk_level || '').trim()
    || (isLowRiskExecutableRecoveryTool(action.tool) ? 'low' : '');
  return {
    daily_desktop_intent: true,
    ...(action.action_kind === 'retry_original' ? { desktop_permission_retry: true } : {}),
    desktop_permission_recovery: true,
    ...(action.action_kind ? { recovery_action_kind: action.action_kind } : {}),
    recovery_input: action.input,
    recovery_permission_target: action.permission_target,
    recovery_risk_level: riskLevel,
    recovery_tool: action.tool,
    ...(action.retry_tool ? { recovery_retry_tool: action.retry_tool } : {}),
    ...(action.retry_tool || action.retry_input ? { recovery_retry_input: action.retry_input || {} } : {}),
    ...(action.retry_input_schema ? { recovery_retry_input_schema: action.retry_input_schema } : {}),
    ...(action.retry_input_source ? { recovery_retry_input_source: action.retry_input_source } : {}),
    ...(action.retry_artifact_tool ? { recovery_retry_artifact_tool: action.retry_artifact_tool } : {}),
    ...(action.retry_artifact_kind ? { recovery_retry_artifact_kind: action.retry_artifact_kind } : {}),
    ...(action.required_retry_fields?.length ? { required_retry_fields: action.required_retry_fields } : {}),
    ...(action.recommended_tools?.length ? { recommended_tools: action.recommended_tools } : {}),
    ...(action.retry_prompt ? { recovery_retry_prompt: action.retry_prompt } : {}),
    ...(action.retry_source_event_type ? { recovery_retry_source_event_type: action.retry_source_event_type } : {}),
    ...(action.retry_source_tool_call_id ? { recovery_retry_source_tool_call_id: action.retry_source_tool_call_id } : {}),
    ...extra,
  };
}

export function runtimeToolRecoveryRetryAction(
  action: RuntimeToolRecoveryAction,
): RuntimeToolRecoveryAction | null {
  const retryTool = String(action.retry_tool || '').trim();
  if (!retryTool) return null;
  const retryInput = objectValue(action.retry_input);
  const prompt = String(action.retry_prompt || '').trim()
    || runtimeToolRecoveryRetryPrompt(retryTool, retryInput);
  if (!prompt) return null;
  return {
    action_kind: 'retry_original',
    input: retryInput,
    label: '恢复后重试原操作',
    permission_target: action.permission_target,
    prompt,
    recommended_tools: action.recommended_tools,
    required_retry_fields: action.required_retry_fields,
    retry_input: retryInput,
    retry_input_schema: action.retry_input_schema,
    retry_input_source: action.retry_input_source,
    retry_artifact_tool: action.retry_artifact_tool,
    retry_artifact_kind: action.retry_artifact_kind,
    retry_prompt: prompt,
    retry_source_event_type: action.retry_source_event_type,
    retry_source_tool_call_id: action.retry_source_tool_call_id,
    retry_tool: retryTool,
    tool: retryTool,
  };
}

export function runtimeToolRecoveryMissingRequiredFields(
  action: RuntimeToolRecoveryAction,
): string[] {
  const input = objectValue(action.input);
  return (action.required_retry_fields || []).filter((field) => {
    const value = input[field];
    return value === undefined || value === null || value === '';
  });
}

export function runtimeToolRecoveryActionsFromRecords(
  sources: Array<Record<string, unknown>>,
  retryContext: RuntimeToolRecoveryRetryContext = {},
): RuntimeToolRecoveryAction[] {
  const byKey = new Map<string, RuntimeToolRecoveryAction>();
  sources
    .flatMap((source) => runtimeToolRecoveryActionsFromRecord(source, retryContext))
    .forEach((action) => {
      const key = `${action.tool}:${JSON.stringify(action.input)}:${action.permission_target}`;
      if (!byKey.has(key)) byKey.set(key, action);
    });
  return Array.from(byKey.values());
}

export function runtimeToolRecoveryActionsFromRecord(
  source: Record<string, unknown>,
  retryContext: RuntimeToolRecoveryRetryContext = {},
): RuntimeToolRecoveryAction[] {
  const rawActions = Array.isArray(source.recovery_actions) ? source.recovery_actions : [];
  return rawActions.flatMap((rawAction) => {
    const action = objectValue(rawAction);
    const tool = String(action.tool || '').trim();
    const input = objectValue(action.input);
    const fallbackLabel = runtimeToolRecoveryExecutableLabel(tool, input);
    if (!fallbackLabel) return [];
    const label = String(action.label || fallbackLabel || tool).trim();
    const actionRetryContext = runtimeToolRecoveryRetryContext(action, retryContext);
    return [{
      input,
      label,
      permission_target: String(action.permission_target || '').trim(),
      prompt: String(action.prompt || label || fallbackLabel || tool).trim(),
      recommended_tools: recoveryStringList(action.recommended_tools),
      required_retry_fields: recoveryStringList(action.required_retry_fields),
      risk_level: String(action.risk_level || '').trim() || undefined,
      ...actionRetryContext,
      tool,
    }];
  });
}

function runtimeToolRecoveryExecutableLabel(tool: string, input: Record<string, unknown>): string {
  const appName = String(input.app_name || '').trim();
  const query = String(input.query || '').trim();
  const url = String(input.url || '').trim();
  const target = String(input.target || '').trim();
  const path = String(input.path || '').trim();
  if (tool === 'app.open' && appName) return `打开${appName}`;
  if (tool === 'app.focus' && appName) return `切到${appName}`;
  if (tool === 'app.focus_window' && appName) return appWindowFocusPrompt(input);
  if (tool === 'app.show' && appName) return `显示${appName}`;
  if (tool === 'app.status' && appName) return `检查${appName}是否打开`;
  const foregroundPrompt = appForegroundActionPrompt(tool, input);
  if (foregroundPrompt) return foregroundPrompt;
  if (tool === 'browser.open_url' && url) return `打开 ${url}`;
  if (tool === 'browser.open_url_and_extract_text' && url) return `打开并读取 ${url}`;
  if (tool === 'browser.open_url_and_screenshot' && url) return `打开并截取 ${url}`;
  if (tool === 'browser.screenshot') return '截取当前网页';
  if (tool === 'system.settings_open' && target) return `打开${target}`;
  if (tool === 'desktop.open_path' && path) return `打开 ${path}`;
  if (tool === 'media.apple_music_play' && query) return `播放${query}`;
  if (tool === 'media.apple_music_open_and_play') return '打开Apple Music并播放';
  if (tool === 'media.apple_music_control') return appleMusicControlRetryPrompt(String(input.action || '').trim());
  if (tool === 'media.music_app_open_and_play' && appName) return `打开${appName}并播放`;
  if (tool === 'system.volume') return systemVolumeRetryPrompt(String(input.action || '').trim(), input);
  if (tool === 'system.brightness') return systemBrightnessRetryPrompt(String(input.action || '').trim());
  if (tool === 'clipboard.read') return '读取剪贴板';
  if (tool === 'clipboard.write' && typeof input.text === 'string') return `复制${input.text}到剪贴板`;
  if (tool === 'screen.capture') return '截图当前屏幕';
  if (tool === 'desktop.permissions') return '检查桌面权限';
  if (tool === 'desktop.active_window') return '查看当前窗口';
  if (tool === 'desktop.list_apps') return '发现已安装应用';
  if (tool === 'desktop.running_apps') return '查看正在运行的应用';
  if (tool === 'desktop.windows') return appName ? `查看${appName}窗口` : '查看桌面窗口';
  if (tool === 'desktop.ui_elements') return '查看当前界面控件';
  if (tool === 'desktop.click_ui_element') return desktopUiClickPrompt(input);
  if (tool === 'desktop.type_into_ui_element') return desktopUiTypePrompt(input);
  if (tool === 'desktop.safe_shortcut') return desktopSafeShortcutPrompt(String(input.action || '').trim());
  if (tool === 'desktop.safe_key') return desktopSafeKeyPrompt(input);
  if (tool === 'desktop.safe_scroll') return desktopSafeScrollPrompt(input);
  if (tool === 'desktop.safe_click') return desktopSafeClickPrompt(input);
  if (tool === 'desktop.safe_type_text') return desktopSafeTypeTextPrompt(input);
  if (tool === 'browser.current_page') return '查看当前网页';
  if (tool === 'browser.extract_text') return '读取当前网页正文';
  return '';
}

function isLowRiskExecutableRecoveryTool(tool: string): boolean {
  return tool === 'app.open'
    || tool === 'app.focus'
    || tool === 'app.focus_and_safe_click'
    || tool === 'app.focus_and_safe_key'
    || tool === 'app.focus_and_safe_scroll'
    || tool === 'app.focus_and_safe_shortcut'
    || tool === 'app.focus_and_safe_type_text'
    || tool === 'app.focus_window'
    || tool === 'app.open_and_safe_click'
    || tool === 'app.open_and_safe_key'
    || tool === 'app.open_and_safe_scroll'
    || tool === 'app.open_and_safe_shortcut'
    || tool === 'app.open_and_safe_type_text'
    || tool === 'app.show'
    || tool === 'app.status'
    || tool === 'browser.current_page'
    || tool === 'browser.extract_text'
    || tool === 'browser.open_url'
    || tool === 'browser.open_url_and_extract_text'
    || tool === 'browser.open_url_and_screenshot'
    || tool === 'browser.screenshot'
    || tool === 'clipboard.read'
    || tool === 'clipboard.write'
    || tool === 'desktop.active_window'
    || tool === 'desktop.open_path'
    || tool === 'desktop.permissions'
    || tool === 'desktop.list_apps'
    || tool === 'desktop.running_apps'
    || tool === 'desktop.safe_click'
    || tool === 'desktop.safe_key'
    || tool === 'desktop.safe_scroll'
    || tool === 'desktop.safe_shortcut'
    || tool === 'desktop.safe_type_text'
    || tool === 'desktop.ui_elements'
    || tool === 'desktop.windows'
    || tool === 'media.apple_music_control'
    || tool === 'media.apple_music_open_and_play'
    || tool === 'media.apple_music_play'
    || tool === 'media.music_app_open_and_play'
    || tool === 'screen.capture'
    || tool === 'system.brightness'
    || tool === 'system.settings_open'
    || tool === 'system.volume';
}

function runtimeToolRecoveryRetryPrompt(tool: string, input: Record<string, unknown>): string {
  const appName = String(input.app_name || '').trim();
  const url = String(input.url || '').trim();
  const query = String(input.query || '').trim();
  const path = String(input.path || '').trim();
  const action = String(input.action || '').trim();
  const target = String(input.target || '').trim();
  const title = String(input.title_contains || input.window_title || '').trim();
  if (tool === 'app.open' && appName) return `打开${appName}`;
  if (tool === 'app.focus' && appName) return `切到${appName}`;
  if (tool === 'app.open_and_safe_type_text' && appName) return `打开${appName}并输入文字`;
  if (tool === 'app.focus_and_safe_type_text' && appName) return `切到${appName}并输入文字`;
  if (tool === 'app.open_and_safe_shortcut' && appName) return `打开${appName}并执行快捷动作`;
  if (tool === 'app.focus_and_safe_shortcut' && appName) return `切到${appName}并执行快捷动作`;
  const foregroundPrompt = appForegroundActionPrompt(tool, input);
  if (foregroundPrompt) return foregroundPrompt;
  if (tool === 'app.focus_window' && appName && title) return `切到${appName} ${title}窗口`;
  if (tool === 'app.show' && appName) return `显示${appName}`;
  if (tool === 'app.hide' && appName) return `隐藏${appName}`;
  if (tool === 'app.minimize' && appName) return `最小化${appName}`;
  if (tool === 'app.quit' && appName) return `退出${appName}`;
  if (tool === 'desktop.quit_app') return '退出当前应用';
  if (tool === 'app.status' && appName) return `检查${appName}是否打开`;
  if (tool === 'browser.open_url' && url) return `打开 ${url}`;
  if (tool === 'browser.open_url_and_extract_text' && url) return `打开并读取 ${url}`;
  if (tool === 'browser.open_url_and_screenshot' && url) return `打开并截取 ${url}`;
  if (tool === 'browser.current_page') return '查看当前网页';
  if (tool === 'browser.extract_text') return '读取当前网页正文';
  if (tool === 'browser.screenshot') return '截取当前网页';
  if (tool === 'screen.capture') return '截图当前屏幕';
  if (tool === 'desktop.active_window') return '查看当前窗口';
  if (tool === 'desktop.list_apps') return '发现已安装应用';
  if (tool === 'desktop.running_apps') return '查看正在运行的应用';
  if (tool === 'desktop.windows') return appName ? `查看${appName}窗口` : '查看桌面窗口';
  if (tool === 'desktop.permissions') return '检查桌面权限';
  if (tool === 'desktop.open_path' && path) return `打开 ${path}`;
  if (tool === 'desktop.safe_shortcut') return desktopSafeShortcutPrompt(action);
  if (tool === 'desktop.safe_key') return desktopSafeKeyPrompt(input);
  if (tool === 'desktop.safe_scroll') return desktopSafeScrollPrompt(input);
  if (tool === 'desktop.safe_click') return desktopSafeClickPrompt(input);
  if (tool === 'desktop.safe_type_text') return desktopSafeTypeTextPrompt(input);
  if (tool === 'desktop.click_ui_element') return desktopUiClickPrompt(input);
  if (tool === 'desktop.type_into_ui_element') return desktopUiTypePrompt(input);
  if (tool === 'desktop.reveal_path' && path) return `在 Finder 中显示 ${path}`;
  if (tool === 'media.apple_music_play' && query) return `播放${query}`;
  if (tool === 'media.apple_music_open_and_play') return '打开Apple Music并播放';
  if (tool === 'media.apple_music_control') return appleMusicControlRetryPrompt(action);
  if (tool === 'media.music_app_open_and_play' && appName) return `打开${appName}并播放`;
  if (tool === 'system.settings_open') return target ? `打开${target}` : '打开系统设置';
  if (tool === 'system.volume') return systemVolumeRetryPrompt(action, input);
  if (tool === 'system.brightness') return systemBrightnessRetryPrompt(action);
  if (tool === 'clipboard.write' && typeof input.text === 'string') return `复制${input.text}到剪贴板`;
  return '';
}

function appleMusicControlRetryPrompt(action: string): string {
  if (action === 'play') return '播放音乐';
  if (action === 'pause') return '暂停音乐';
  if (action === 'next') return '下一首';
  if (action === 'previous') return '上一首';
  if (action === 'toggle') return '播放暂停';
  return '';
}

function systemVolumeRetryPrompt(action: string, input: Record<string, unknown>): string {
  if (action === 'status') return '当前音量是多少';
  if (action === 'mute') return '静音';
  if (action === 'unmute') return '取消静音';
  if (action === 'up') return '调大音量';
  if (action === 'down') return '调小音量';
  const level = typeof input.level === 'number' ? input.level : Number(input.level);
  if (action === 'set' && Number.isFinite(level)) return `把音量调到 ${level}%`;
  return '';
}

function systemBrightnessRetryPrompt(action: string): string {
  if (action === 'up') return '屏幕亮一点';
  if (action === 'down') return '屏幕暗一点';
  return '';
}

function appForegroundActionPrompt(tool: string, input: Record<string, unknown>): string {
  const appName = String(input.app_name || '').trim();
  if (!appName) return '';
  const isOpen = tool.startsWith('app.open_and_');
  const isFocus = tool.startsWith('app.focus_and_');
  if (!isOpen && !isFocus) return '';
  const prefix = isOpen ? `打开${appName}` : `切到${appName}`;
  let detail = '';
  if (tool.endsWith('safe_type_text')) detail = desktopSafeTypeTextPrompt(input) || '输入文字';
  if (tool.endsWith('safe_shortcut')) detail = desktopSafeShortcutPrompt(String(input.action || '').trim());
  if (tool.endsWith('safe_key')) detail = desktopSafeKeyPrompt(input);
  if (tool.endsWith('safe_scroll')) detail = desktopSafeScrollPrompt(input);
  if (tool.endsWith('safe_click')) detail = desktopSafeClickPrompt(input);
  if (tool.endsWith('click_ui_element')) detail = desktopUiClickPrompt(input);
  if (tool.endsWith('type_into_ui_element')) detail = desktopUiTypePrompt(input);
  return detail ? `${prefix}并${detail}` : '';
}

function appWindowFocusPrompt(input: Record<string, unknown>): string {
  const appName = String(input.app_name || '').trim();
  const title = String(input.window_title || input.title_contains || '').trim();
  if (appName && title) return `切到${appName} ${title}窗口`;
  return appName ? `切到${appName}窗口` : '';
}

function desktopSafeShortcutPrompt(action: string): string {
  if (action === 'copy') return '复制选中内容';
  if (action === 'paste') return '粘贴';
  if (action === 'select_all') return '全选';
  if (action === 'undo') return '撤销';
  if (action === 'redo') return '重做';
  if (action === 'find') return '打开查找';
  if (action === 'new_tab') return '新建标签页';
  if (action === 'close_tab') return '关闭标签页';
  if (action === 'next_tab') return '切到下一个标签页';
  if (action === 'previous_tab') return '切到上一个标签页';
  if (action === 'new_window') return '新建窗口';
  if (action === 'new_document') return '新建文档';
  if (action === 'new_note') return '新建笔记';
  if (action === 'new_reminder') return '新建提醒事项';
  if (action === 'new_event') return '新建日程';
  if (action === 'refresh') return '刷新';
  if (action === 'browser_back') return '返回上一页';
  if (action === 'browser_forward') return '前进一页';
  if (action === 'reopen_closed_tab') return '重新打开关闭的标签页';
  return '';
}

function desktopSafeKeyPrompt(input: Record<string, unknown>): string {
  const action = String(input.action || '').trim();
  const label = desktopSafeKeyLabel(action);
  if (!label) return '';
  const repeatCount = Number(input.repeat_count || 1);
  return Number.isFinite(repeatCount) && repeatCount > 1
    ? `按${label}${repeatCount}次`
    : `按${label}`;
}

function desktopSafeKeyLabel(action: string): string {
  if (action === 'escape') return 'Escape';
  if (action === 'tab') return 'Tab';
  if (action === 'shift_tab') return 'Shift+Tab';
  if (action === 'arrow_up') return '上箭头';
  if (action === 'arrow_down') return '下箭头';
  if (action === 'arrow_left') return '左箭头';
  if (action === 'arrow_right') return '右箭头';
  if (action === 'home') return 'Home';
  if (action === 'end') return 'End';
  if (action === 'page_up') return 'Page Up';
  if (action === 'page_down') return 'Page Down';
  return '';
}

function desktopSafeScrollPrompt(input: Record<string, unknown>): string {
  const direction = String(input.direction || '').trim();
  const label = direction === 'down' ? '向下' : direction === 'up' ? '向上' : '';
  if (!label) return '';
  const pages = Number(input.pages || 1);
  return Number.isFinite(pages) && pages > 1 ? `${label}滚动${pages}页` : `${label}滚动`;
}

function desktopSafeClickPrompt(input: Record<string, unknown>): string {
  const x = input.x;
  const y = input.y;
  if (x === undefined || x === null || y === undefined || y === null) return '';
  return `点击 ${x}, ${y}`;
}

function desktopSafeTypeTextPrompt(input: Record<string, unknown>): string {
  const text = typeof input.text === 'string' ? input.text.trim() : '';
  return text ? `输入${text}` : '';
}

function desktopUiClickPrompt(input: Record<string, unknown>): string {
  const target = String(input.target || '').trim();
  return target ? `点击前台控件${target}` : '';
}

function desktopUiTypePrompt(input: Record<string, unknown>): string {
  const target = String(input.target || '').trim();
  const text = typeof input.text === 'string' ? input.text.trim() : '';
  if (target && text) return `在前台控件${target}输入文字`;
  return target ? `在前台控件${target}输入文字` : '';
}

function isExecutableRecoveryPrompt(value: string): boolean {
  return /^(?:打开|启动|前往|进入|显示|切到|切换到)\s*/.test(value.trim());
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function optionalObjectValue(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function recoveryStringList(value: unknown): string[] | undefined {
  if (!Array.isArray(value)) return undefined;
  const items = value.map((item) => String(item || '').trim()).filter(Boolean);
  return items.length ? items : undefined;
}

function optionalText(value: unknown): string | undefined {
  const text = String(value || '').trim();
  return text || undefined;
}

function runtimeToolRecoveryRetryContext(
  action: Record<string, unknown>,
  fallback: RuntimeToolRecoveryRetryContext,
): RuntimeToolRecoveryRetryContext {
  const retryTool = optionalText(action.retry_tool)
    || optionalText(action.recovery_retry_tool)
    || optionalText(fallback.retry_tool);
  const retryInput = optionalObjectValue(action.retry_input)
    || optionalObjectValue(action.recovery_retry_input)
    || fallback.retry_input;
  const retryInputSchema = optionalObjectValue(action.retry_input_schema)
    || optionalObjectValue(action.recovery_retry_input_schema)
    || fallback.retry_input_schema;
  const retryInputSource = optionalText(action.retry_input_source)
    || optionalText(action.recovery_retry_input_source)
    || fallback.retry_input_source;
  const retryArtifactTool = optionalText(action.retry_artifact_tool)
    || optionalText(action.recovery_retry_artifact_tool)
    || fallback.retry_artifact_tool;
  const retryArtifactKind = optionalText(action.retry_artifact_kind)
    || optionalText(action.recovery_retry_artifact_kind)
    || fallback.retry_artifact_kind;
  const requiredRetryFields = recoveryStringList(action.required_retry_fields)
    || fallback.required_retry_fields;
  const recommendedTools = recoveryStringList(action.recommended_tools)
    || fallback.recommended_tools;
  const retryPrompt = optionalText(action.retry_prompt)
    || optionalText(action.recovery_retry_prompt)
    || optionalText(fallback.retry_prompt);
  const retrySourceEventType = optionalText(action.retry_source_event_type)
    || optionalText(action.recovery_retry_source_event_type)
    || optionalText(fallback.retry_source_event_type);
  const retrySourceToolCallId = optionalText(action.retry_source_tool_call_id)
    || optionalText(action.recovery_retry_source_tool_call_id)
    || optionalText(fallback.retry_source_tool_call_id);

  return {
    ...(recommendedTools?.length ? { recommended_tools: recommendedTools } : {}),
    ...(requiredRetryFields?.length ? { required_retry_fields: requiredRetryFields } : {}),
    ...(retryTool ? { retry_tool: retryTool } : {}),
    ...(retryTool || retryInput ? { retry_input: retryInput || {} } : {}),
    ...(retryInputSchema ? { retry_input_schema: retryInputSchema } : {}),
    ...(retryInputSource ? { retry_input_source: retryInputSource } : {}),
    ...(retryArtifactTool ? { retry_artifact_tool: retryArtifactTool } : {}),
    ...(retryArtifactKind ? { retry_artifact_kind: retryArtifactKind } : {}),
    ...(retryPrompt ? { retry_prompt: retryPrompt } : {}),
    ...(retrySourceEventType ? { retry_source_event_type: retrySourceEventType } : {}),
    ...(retrySourceToolCallId ? { retry_source_tool_call_id: retrySourceToolCallId } : {}),
  };
}
