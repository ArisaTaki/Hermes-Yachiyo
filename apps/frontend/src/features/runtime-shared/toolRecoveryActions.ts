export type RuntimeToolRecoveryAction = {
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
  const appName = String(input.app_name || '').trim();
  const prompt = String(action.prompt || '').trim();
  if (isExecutableRecoveryPrompt(prompt)) return prompt;
  const label = String(action.label || '').trim();
  if (isExecutableRecoveryPrompt(label)) return label;
  if (tool === 'app.open' && appName) return `打开${appName}`;
  return prompt || label || tool;
}

export function runtimeToolRecoveryActionTaskMetadata(
  action: RuntimeToolRecoveryAction,
  extra: Record<string, unknown> = {},
): Record<string, unknown> {
  const riskLevel = String(action.risk_level || '').trim()
    || (action.tool === 'app.open' ? 'low' : '');
  return {
    daily_desktop_intent: true,
    desktop_permission_recovery: true,
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
    if (tool !== 'app.open') return [];
    const appName = String(input.app_name || '').trim();
    if (!appName) return [];
    const label = String(action.label || appName || tool).trim();
    const actionRetryContext = runtimeToolRecoveryRetryContext(action, retryContext);
    return [{
      input,
      label,
      permission_target: String(action.permission_target || '').trim(),
      prompt: String(action.prompt || label || `打开${appName}`).trim(),
      risk_level: String(action.risk_level || '').trim() || undefined,
      ...actionRetryContext,
      tool,
    }];
  });
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
