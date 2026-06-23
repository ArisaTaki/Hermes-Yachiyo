export type RuntimeToolRecoveryAction = {
  input: Record<string, unknown>;
  label: string;
  permission_target: string;
  prompt: string;
  risk_level?: string;
  tool: string;
};

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
    ...extra,
  };
}

export function runtimeToolRecoveryActionsFromRecords(
  sources: Array<Record<string, unknown>>,
): RuntimeToolRecoveryAction[] {
  const byKey = new Map<string, RuntimeToolRecoveryAction>();
  sources
    .flatMap((source) => runtimeToolRecoveryActionsFromRecord(source))
    .forEach((action) => {
      const key = `${action.tool}:${JSON.stringify(action.input)}:${action.permission_target}`;
      if (!byKey.has(key)) byKey.set(key, action);
    });
  return Array.from(byKey.values());
}

export function runtimeToolRecoveryActionsFromRecord(
  source: Record<string, unknown>,
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
    return [{
      input,
      label,
      permission_target: String(action.permission_target || '').trim(),
      prompt: String(action.prompt || label || `打开${appName}`).trim(),
      risk_level: String(action.risk_level || '').trim() || undefined,
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
