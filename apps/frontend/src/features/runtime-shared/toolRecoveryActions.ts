export type RuntimeToolRecoveryAction = {
  input: Record<string, unknown>;
  label: string;
  permission_target: string;
  prompt: string;
  risk_level?: string;
  tool: string;
};

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
      prompt: label || `打开 ${appName}`,
      risk_level: String(action.risk_level || '').trim() || undefined,
      tool,
    }];
  });
}

function objectValue(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}
