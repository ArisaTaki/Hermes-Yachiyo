export type RuntimeToolRecoveryAction = {
  action_kind?: 'permission_recovery' | 'retry_original';
  input: Record<string, unknown>;
  label: string;
  permission_target: string;
  prompt: string;
  risk_level?: string;
  retry_input?: Record<string, unknown>;
  retry_prompt?: string;
  retry_source_event_type?: string;
  retry_source_tool_call_id?: string;
  retry_tool?: string;
  tool: string;
};

export type RuntimeToolRecoveryRetryContext = Pick<
  RuntimeToolRecoveryAction,
  'retry_input' | 'retry_prompt' | 'retry_source_event_type' | 'retry_source_tool_call_id' | 'retry_tool'
>;

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
): Record<string, unknown> {
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
    retry_input: retryInput,
    retry_prompt: prompt,
    retry_source_event_type: action.retry_source_event_type,
    retry_source_tool_call_id: action.retry_source_tool_call_id,
    retry_tool: retryTool,
    tool: retryTool,
  };
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
      risk_level: String(action.risk_level || '').trim() || undefined,
      ...actionRetryContext,
      tool,
    }];
  });
}

function runtimeToolRecoveryExecutableLabel(tool: string, input: Record<string, unknown>): string {
  const appName = String(input.app_name || '').trim();
  const url = String(input.url || '').trim();
  const target = String(input.target || '').trim();
  const path = String(input.path || '').trim();
  if (tool === 'app.open' && appName) return `打开${appName}`;
  if (tool === 'browser.open_url' && url) return `打开 ${url}`;
  if (tool === 'system.settings_open' && target) return `打开${target}`;
  if (tool === 'desktop.open_path' && path) return `打开 ${path}`;
  return '';
}

function isLowRiskExecutableRecoveryTool(tool: string): boolean {
  return tool === 'app.open'
    || tool === 'browser.open_url'
    || tool === 'desktop.open_path'
    || tool === 'system.settings_open';
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
  if (tool === 'app.focus_window' && appName && title) return `切到${appName} ${title}窗口`;
  if (tool === 'app.show' && appName) return `显示${appName}`;
  if (tool === 'app.hide' && appName) return `隐藏${appName}`;
  if (tool === 'app.minimize' && appName) return `最小化${appName}`;
  if (tool === 'app.quit' && appName) return `退出${appName}`;
  if (tool === 'app.status' && appName) return `检查${appName}是否打开`;
  if (tool === 'browser.open_url' && url) return `打开 ${url}`;
  if (tool === 'browser.open_url_and_extract_text' && url) return `打开并读取 ${url}`;
  if (tool === 'browser.open_url_and_screenshot' && url) return `打开并截取 ${url}`;
  if (tool === 'browser.current_page') return '查看当前网页';
  if (tool === 'browser.extract_text') return '读取当前网页正文';
  if (tool === 'browser.screenshot') return '截取当前网页';
  if (tool === 'screen.capture') return '截图当前屏幕';
  if (tool === 'desktop.active_window') return '查看当前窗口';
  if (tool === 'desktop.running_apps') return '查看正在运行的应用';
  if (tool === 'desktop.windows') return appName ? `查看${appName}窗口` : '查看桌面窗口';
  if (tool === 'desktop.permissions') return '检查桌面权限';
  if (tool === 'desktop.open_path' && path) return `打开 ${path}`;
  if (tool === 'desktop.reveal_path' && path) return `在 Finder 中显示 ${path}`;
  if (tool === 'media.apple_music_play' && query) return `播放${query}`;
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
  const level = typeof input.level === 'number' ? input.level : Number(input.level);
  if (action === 'set' && Number.isFinite(level)) return `把音量调到 ${level}%`;
  return '';
}

function systemBrightnessRetryPrompt(action: string): string {
  if (action === 'up') return '屏幕亮一点';
  if (action === 'down') return '屏幕暗一点';
  return '';
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
    ...(retryTool ? { retry_tool: retryTool } : {}),
    ...(retryTool || retryInput ? { retry_input: retryInput || {} } : {}),
    ...(retryPrompt ? { retry_prompt: retryPrompt } : {}),
    ...(retrySourceEventType ? { retry_source_event_type: retrySourceEventType } : {}),
    ...(retrySourceToolCallId ? { retry_source_tool_call_id: retrySourceToolCallId } : {}),
  };
}
