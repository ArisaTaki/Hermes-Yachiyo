import type { AgentTaskSnapshot, PlannerTraceSummarySnapshot } from './types';

export type TaskPlannerSummarySnapshot = {
  approvals: string[];
  artifacts: string[];
  capabilities: string[];
  followupTargets: string[];
  intentKind: string;
  missingCapabilities: string[];
  openQuestions: string[];
  routeToStudio: boolean | null;
  tools: string[];
};

export type TaskPlannerSummaryChip = {
  kind: string;
  label: string;
  value: string;
};

export function plannerSummaryFromTask(task: AgentTaskSnapshot): TaskPlannerSummarySnapshot | null {
  return plannerSummaryFromStructuredTrace(task.planner_summary)
    || plannerSummaryFromTaskMetadata(task.metadata);
}

export function plannerSummaryDetail(summary: TaskPlannerSummarySnapshot): string {
  const parts = [
    summary.capabilities.length ? `${summary.capabilities.length} 个能力` : '',
    summary.tools.length ? `${summary.tools.length} 个工具` : '',
    summary.followupTargets.length ? `${summary.followupTargets.length} 个后续目标` : '',
    summary.approvals.length ? `${summary.approvals.length} 个审批` : '',
    summary.artifacts.length ? `${summary.artifacts.length} 个产物` : '',
    summary.openQuestions.length ? `${summary.openQuestions.length} 个待确认` : '',
    summary.missingCapabilities.length ? `${summary.missingCapabilities.length} 个缺失能力` : '',
  ].filter(Boolean);
  return parts.join(' · ') || 'runtime plan';
}

export function plannerSummaryChips(summary: TaskPlannerSummarySnapshot): TaskPlannerSummaryChip[] {
  const chips = [
    ...summary.capabilities.slice(0, 3).map((value) => ({ kind: 'capability', label: '能力', value })),
    ...summary.tools.slice(0, 4).map((value) => ({ kind: 'tool', label: '工具', value })),
    ...summary.followupTargets.slice(0, 3).map((value) => ({ kind: 'target', label: '目标', value })),
    ...summary.approvals.slice(0, 2).map((value) => ({ kind: 'approval', label: '审批', value })),
    ...summary.artifacts.slice(0, 2).map((value) => ({ kind: 'artifact', label: '产物', value })),
    ...summary.openQuestions.slice(0, 2).map((value) => ({ kind: 'question', label: '待确认', value })),
    ...summary.missingCapabilities.slice(0, 2).map((value) => ({ kind: 'missing', label: '缺失', value })),
  ];
  const visibleCount = chips.length;
  const totalCount = summary.capabilities.length
    + summary.tools.length
    + summary.followupTargets.length
    + summary.approvals.length
    + summary.artifacts.length
    + summary.openQuestions.length
    + summary.missingCapabilities.length;
  if (totalCount > visibleCount) {
    chips.push({ kind: 'more', label: '更多', value: String(totalCount - visibleCount) });
  }
  return chips;
}

function plannerSummaryFromStructuredTrace(
  value: PlannerTraceSummarySnapshot | null | undefined,
): TaskPlannerSummarySnapshot | null {
  const trace = objectValue(value);
  const intentKind = String(trace.intent_kind || '').trim();
  const tools = uniqueStrings([
    ...stringList(trace.plan_tools),
    ...stringList(trace.selected_tools),
  ]);
  const capabilities = uniqueStrings([
    ...stringList(trace.plan_capabilities),
    ...stringList(trace.required_capabilities),
  ]);
  const summary: TaskPlannerSummarySnapshot = {
    approvals: stringList(trace.approvals_required),
    artifacts: stringList(trace.artifacts_expected),
    capabilities,
    followupTargets: plannerFollowupTargetSummary(trace.followup_target),
    intentKind,
    missingCapabilities: stringList(trace.missing_capabilities),
    openQuestions: stringList(trace.open_questions),
    routeToStudio: booleanMetadataValue(trace.route_to_studio),
    tools,
  };
  return emptyPlannerSummary(summary) ? null : summary;
}

function plannerSummaryFromTaskMetadata(value: unknown): TaskPlannerSummarySnapshot | null {
  const metadata = objectValue(value);
  if (!booleanMetadataValue(metadata.yachiyo_runtime_planner)) return null;
  const intentKind = String(metadata.yachiyo_intent_kind || '').trim();
  const tools = stringList(metadata.yachiyo_plan_tools);
  const capabilities = uniqueStrings([
    ...stringList(metadata.yachiyo_plan_capabilities),
    ...stringList(metadata.yachiyo_required_capabilities),
  ]);
  const summary: TaskPlannerSummarySnapshot = {
    approvals: stringList(metadata.yachiyo_plan_approvals_required),
    artifacts: stringList(metadata.yachiyo_plan_artifacts_expected),
    capabilities,
    followupTargets: plannerFollowupTargetSummary(metadata.yachiyo_followup_target),
    intentKind,
    missingCapabilities: stringList(metadata.yachiyo_missing_capabilities),
    openQuestions: stringList(metadata.yachiyo_plan_open_questions),
    routeToStudio: booleanMetadataValue(metadata.yachiyo_route_to_studio),
    tools,
  };
  return emptyPlannerSummary(summary) ? null : summary;
}

function emptyPlannerSummary(summary: TaskPlannerSummarySnapshot): boolean {
  return !summary.intentKind
    && !summary.tools.length
    && !summary.capabilities.length
    && !summary.followupTargets.length
    && !summary.approvals.length
    && !summary.artifacts.length
    && !summary.openQuestions.length
    && !summary.missingCapabilities.length;
}

function plannerFollowupTargetSummary(value: unknown): string[] {
  const target = objectValue(value);
  const entries: string[] = [];
  for (const key of ([
    'kind',
    'app_name',
    'app_query',
    'target_action',
    'safe_shortcut_action',
    'recipient',
    'send_action',
    'container_action',
  ] as const)) {
    const entry = String(target[key] || '').trim();
    if (entry) entries.push(`${key}:${entry}`);
  }
  const communicationCompose = objectValue(target.communication_compose);
  for (const key of (['channel', 'recipient', 'send_action'] as const)) {
    const entry = String(communicationCompose[key] || '').trim();
    if (entry) entries.push(`compose.${key}:${entry}`);
  }
  return uniqueStrings(entries);
}

function booleanMetadataValue(value: unknown): boolean | null {
  if (typeof value === 'boolean') return value;
  const normalized = String(value || '').trim().toLowerCase();
  if (normalized === 'true') return true;
  if (normalized === 'false') return false;
  return null;
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
