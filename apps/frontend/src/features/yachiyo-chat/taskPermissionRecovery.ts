import { runtimeEventIsDesktopReadinessRecovered } from '../runtime-shared/desktopEvents';
import {
  runtimeToolRecoveryActionsFromRecords,
  type RuntimeToolRecoveryAction,
} from '../runtime-shared/toolRecoveryActions';
import { runtimeToolRecoveryHintsFromRecords } from '../runtime-shared/toolRecoveryHints';
import type { AgentTaskSnapshot } from './types';

export type TaskPermissionRecoveryAction = RuntimeToolRecoveryAction;

export type TaskPermissionRecovery = {
  actions: TaskPermissionRecoveryAction[];
  blockingConditions: string[];
  href: string;
  hints: string[];
  kind: 'permission' | 'blocking_condition' | 'mixed';
  labels: string[];
  targets: string[];
  tools: string[];
};

const permissionTargetLabels: Record<string, string> = {
  accessibility: '辅助功能权限',
  automation: '自动化权限',
  automation_or_accessibility: '自动化或辅助功能权限',
  chrome_cdp: 'Chrome CDP',
  music_app: 'Music.app',
  open_command: 'macOS open 命令',
  screen_capture_probe_failed: '屏幕录制探测',
  screen_recording: '屏幕录制权限',
  unsupported_platform: '当前平台',
};

const blockingConditionLabels: Record<string, string> = {
  desktop_session_locked: '桌面会话已锁定',
  foreground_focus_unavailable: '前台激活暂不可用',
  screen_capture_blank: '屏幕画面为空黑',
};

export function taskPermissionRecoveryFromEvents(events: AgentTaskSnapshot['recent_events']): TaskPermissionRecovery | null {
  return taskPermissionRecoveryFromTaskFacts(events, []);
}

export function taskPermissionRecoveryFromTaskFacts(
  events: AgentTaskSnapshot['recent_events'],
  toolCalls: AgentTaskSnapshot['tool_calls'] = [],
): TaskPermissionRecovery | null {
  const safeEvents = events || [];
  const safeToolCalls = toolCalls || [];
  const recoveryBoundary = latestReadinessRecoverySequence(safeEvents);
  const recoveryEvents = safeEvents.filter((event) => recoveryEventSurvivesReadinessRecovery(event, recoveryBoundary));
  const recoveryToolCalls = safeToolCalls.filter((toolCall) => recoveryToolCallSurvivesReadinessRecovery(toolCall, recoveryBoundary));
  const targets = uniqueStrings([
    ...recoveryEvents.flatMap((event) => permissionTargetsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => permissionTargetsFromToolCall(toolCall)),
  ]);
  const blockingConditions = uniqueStrings([
    ...recoveryEvents.flatMap((event) => blockingConditionsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => blockingConditionsFromToolCall(toolCall)),
  ]);
  if (!targets.length && !blockingConditions.length) return null;
  const hints = uniqueStrings([
    ...recoveryEvents.flatMap((event) => recoveryHintsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => recoveryHintsFromToolCall(toolCall)),
  ]);
  const tools = uniqueStrings([
    ...recoveryEvents.flatMap((event) => desktopToolsFromEvent(event)),
    ...recoveryToolCalls.flatMap((toolCall) => desktopToolsFromToolCall(toolCall)),
  ]);
  const actions = dedupeRecoveryActions([
    ...executableRecoveryActionsFromEvents(recoveryEvents),
    ...executableRecoveryActionsFromToolCalls(recoveryToolCalls),
  ]);
  const params = new URLSearchParams({ command: 'native doctor', return_to: 'chat' });
  if (targets.length) params.set('permission_targets', targets.join(','));
  if (blockingConditions.length) params.set('blocking_conditions', blockingConditions.join(','));
  if (tools.length) params.set('desktop_tools', tools.join(','));
  const kind = targets.length && blockingConditions.length
    ? 'mixed'
    : blockingConditions.length ? 'blocking_condition' : 'permission';
  return {
    actions,
    blockingConditions,
    href: `#/diagnostics?${params.toString()}`,
    hints,
    kind,
    labels: [
      ...targets.map((target) => permissionTargetLabels[target] || target),
      ...blockingConditions.map((condition) => blockingConditionLabels[condition] || condition),
    ],
    targets,
    tools,
  };
}

function latestReadinessRecoverySequence(events: AgentTaskSnapshot['recent_events']): number {
  return Math.max(
    0,
    ...(events || [])
      .filter((event) => runtimeEventIsDesktopReadinessRecovered(String(event.event_type || '').trim()))
      .map((event) => Number(event.sequence) || 0),
  );
}

function recoveryEventSurvivesReadinessRecovery(
  event: NonNullable<AgentTaskSnapshot['recent_events']>[number],
  recoveryBoundary: number,
): boolean {
  const eventType = String(event.event_type || '').trim();
  if (runtimeEventIsDesktopReadinessRecovered(eventType)) return false;
  if (!recoveryBoundary) return true;
  if ((Number(event.sequence) || 0) > recoveryBoundary) return true;
  if (permissionTargetsFromEvent(event).length) return true;
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  return !foregroundReadinessRecordWasRecovered(result) && !foregroundReadinessRecordWasRecovered(payload);
}

function recoveryToolCallSurvivesReadinessRecovery(
  toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number],
  recoveryBoundary: number,
): boolean {
  if (!recoveryBoundary) return true;
  if (permissionTargetsFromToolCall(toolCall).length) return true;
  return !foregroundReadinessRecordWasRecovered(objectValue(toolCall.output_preview));
}

function executableRecoveryActionsFromEvents(events: AgentTaskSnapshot['recent_events']): TaskPermissionRecoveryAction[] {
  return dedupeRecoveryActions((events || []).flatMap((event) => recoveryActionsFromEvent(event)));
}

function executableRecoveryActionsFromToolCalls(toolCalls: AgentTaskSnapshot['tool_calls']): TaskPermissionRecoveryAction[] {
  return dedupeRecoveryActions((toolCalls || []).flatMap((toolCall) => recoveryActionsFromToolCall(toolCall)));
}

function recoveryActionsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): TaskPermissionRecoveryAction[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const retryTool = String(payload.tool || result.tool || result.tool_name || event.detail || '').trim();
  return runtimeToolRecoveryActionsFromRecords(
    [result, payload].filter(Boolean),
    {
      retry_input: objectValue(payload.input_preview || result.input_preview),
      retry_source_event_type: String(event.event_type || '').trim(),
      retry_tool: retryTool,
    },
  );
}

function recoveryActionsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): TaskPermissionRecoveryAction[] {
  const outputPreview = objectValue(toolCall.output_preview);
  return runtimeToolRecoveryActionsFromRecords(
    [outputPreview],
    {
      retry_input: objectValue(toolCall.input_preview),
      retry_source_tool_call_id: String(toolCall.tool_call_id || '').trim(),
      retry_tool: String(toolCall.tool_name || '').trim(),
    },
  );
}

function permissionTargetsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const sources = [result, payload].filter(Boolean);
  const targets = sources.flatMap((source) => [
    ...stringList(source.permission_targets),
    ...stringList(source.missing_permissions),
  ]);
  const permissionError = sources.some((source) => source.permission_error === true);
  return permissionError || targets.length ? targets : [];
}

function permissionTargetsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  const outputPreview = objectValue(toolCall.output_preview);
  const targets = [
    ...stringList(outputPreview.permission_targets),
    ...stringList(outputPreview.missing_permissions),
  ];
  return outputPreview.permission_error === true || targets.length ? targets : [];
}

function blockingConditionsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  return uniqueStrings([
    ...blockingConditionsFromRecord(result),
    ...blockingConditionsFromRecord(payload),
  ]);
}

function blockingConditionsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  return blockingConditionsFromRecord(objectValue(toolCall.output_preview));
}

function blockingConditionsFromRecord(source: Record<string, unknown>): string[] {
  const data = objectValue(source.data);
  return uniqueStrings([
    ...stringList(source.blocking_condition),
    ...stringList(source.blocking_conditions),
    ...stringList(data.blocking_condition),
    ...stringList(data.blocking_conditions),
  ]);
}

function foregroundReadinessRecordWasRecovered(source: Record<string, unknown>): boolean {
  const data = objectValue(source.data);
  const error = String(source.error_code || source.error || data.error_code || data.error || '').trim();
  const conditions = uniqueStrings([
    ...blockingConditionsFromRecord(source),
    error,
  ]);
  if (source.blocked_by_runtime_readiness === true || data.blocked_by_runtime_readiness === true) return true;
  if (data.ready_for_foreground_action === false) return true;
  return conditions.some((condition) => recoverableForegroundReadinessConditions.has(condition));
}

const recoverableForegroundReadinessConditions = new Set([
  'app_not_found',
  'app_not_running',
  'foreground_focus_unverified',
  'foreground_not_ready',
  'no_actionable_controls',
  'ui_elements_empty',
]);

function recoveryHintsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const sources = [result, payload].filter(Boolean);
  return runtimeToolRecoveryHintsFromRecords(sources);
}

function recoveryHintsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  return runtimeToolRecoveryHintsFromRecords([objectValue(toolCall.output_preview)]);
}

function desktopToolsFromEvent(event: NonNullable<AgentTaskSnapshot['recent_events']>[number]): string[] {
  if ((event.sensitivity || 'public') === 'secret') return [];
  const payload = objectValue(event.payload);
  const result = objectValue(payload.result);
  const detailTool = String(event.event_type || '').includes('tool') ? event.detail : '';
  return [
    result.action,
    result.tool,
    result.tool_name,
    payload.tool,
    payload.tool_name,
    detailTool,
  ].flatMap((value) => stringList(value));
}

function desktopToolsFromToolCall(toolCall: NonNullable<AgentTaskSnapshot['tool_calls']>[number]): string[] {
  const outputPreview = objectValue(toolCall.output_preview);
  return [
    toolCall.tool_name,
    outputPreview.action,
    outputPreview.tool,
    outputPreview.tool_name,
  ].flatMap((value) => stringList(value));
}

function dedupeRecoveryActions(actions: TaskPermissionRecoveryAction[]): TaskPermissionRecoveryAction[] {
  const byKey = new Map<string, TaskPermissionRecoveryAction>();
  actions.forEach((action) => {
    const key = `${action.tool}:${JSON.stringify(action.input)}:${action.permission_target}`;
    if (!byKey.has(key)) byKey.set(key, action);
  });
  return Array.from(byKey.values());
}

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
