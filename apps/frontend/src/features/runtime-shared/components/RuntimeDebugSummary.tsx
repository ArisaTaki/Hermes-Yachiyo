import type { RuntimeDebugSummarySnapshot } from '../types';

type RuntimeDebugSummaryProps = {
  className?: string;
  compact?: boolean;
  sourceLabel?: string;
  summary?: RuntimeDebugSummarySnapshot | null;
  testId?: string;
};

type RuntimeDebugMetric = {
  key: string;
  label: string;
  tone?: string;
  value: number | string;
};

export function RuntimeDebugSummary({
  className = '',
  compact = false,
  sourceLabel,
  summary,
  testId = 'runtime-debug-summary',
}: RuntimeDebugSummaryProps) {
  if (!summary || !runtimeDebugSummaryHasContent(summary)) return null;

  const metrics = runtimeDebugMetrics(summary);
  const latestFacts = runtimeDebugLatestFacts(summary);
  const contextFacts = runtimeDebugContextFacts(summary);
  const surfaces = (summary?.debug_surfaces || []).filter(Boolean).slice(0, compact ? 4 : 6);
  const classes = [
    'runtime-debug-summary',
    compact ? 'compact' : '',
    summary?.needs_user_action ? 'needs-user-action' : '',
    summary?.needs_replan ? 'needs-replan' : '',
    className,
  ].filter(Boolean).join(' ');

  return (
    <section
      className={classes}
      data-current-capability-id={summary?.current_capability_id || ''}
      data-deferred-continuation-count={String(summary?.deferred_continuation_count || 0)}
      data-has-user-action={String(Boolean(summary?.needs_user_action))}
      data-intent-kind={summary?.intent_kind || ''}
      data-latest-deferred-continuation-tool={summary?.latest_deferred_continuation_tool || ''}
      data-latest-deferred-tool={summary?.latest_deferred_tool || ''}
      data-latest-request-id={summary?.latest_request_id || ''}
      data-latest-request-tool-name={summary?.latest_request_tool_name || ''}
      data-latest-recovery-tool={summary?.latest_recovery_tool || ''}
      data-latest-replan-request-id={summary?.latest_replan_request_id || ''}
      data-latest-replan-trigger={summary?.latest_replan_trigger || ''}
      data-needs-replan={String(Boolean(summary?.needs_replan))}
      data-plan-capabilities={(summary?.plan_capabilities || []).join(',')}
      data-plan-tools={(summary?.plan_tools || []).join(',')}
      data-desktop-provider-session-id={summary?.desktop_provider_session_provider_id || ''}
      data-desktop-provider-session-needed={String(Boolean(summary?.desktop_provider_session_needed))}
      data-desktop-provider-session-running={String(Boolean(summary?.desktop_provider_session_running))}
      data-desktop-provider-session-started={String(Boolean(summary?.desktop_provider_session_started))}
      data-desktop-provider-session-isolated={String(summary?.desktop_provider_session_isolated ?? '')}
      data-desktop-provider-session-foreground-takeover={String(summary?.desktop_provider_session_foreground_takeover_required ?? '')}
      data-desktop-provider-session-kind={summary?.desktop_provider_session_kind || ''}
      data-desktop-provider-session-status={summary?.desktop_provider_session_status || ''}
      data-desktop-provider-session-tool-names={(summary?.desktop_provider_session_tool_names || []).join(',')}
      data-desktop-execution-session-label={summary?.desktop_execution_session_label || ''}
      data-desktop-execution-session-mode={summary?.desktop_execution_session_mode || ''}
      data-current-request-id={summary?.current_request_id || ''}
      data-current-request-tool-name={summary?.current_request_tool_name || ''}
      data-runtime-doctrine={summary?.runtime_doctrine || ''}
      data-runtime-request-count={String(summary?.runtime_request_count || 0)}
      data-runtime-role={summary?.runtime_role || ''}
      data-runtime-stage={summary?.runtime_stage || ''}
      data-source={summary?.source || ''}
      data-testid={testId}
    >
      <div className="runtime-debug-summary-head">
        <div>
          <strong>Runtime Debug</strong>
          <span>{sourceLabel || summary?.source || 'public runtime summary'}</span>
        </div>
        <div className="runtime-debug-summary-state">
          {summary?.needs_user_action ? <span className="warning">User action</span> : null}
          {summary?.needs_replan ? <span className="warning">Replan</span> : null}
        </div>
      </div>
      {contextFacts.length ? (
        <div className="runtime-debug-context" data-testid={`${testId}-context`}>
          {contextFacts.map((fact) => (
            <code key={fact}>{fact}</code>
          ))}
        </div>
      ) : null}
      {metrics.length ? (
        <div className="runtime-debug-metrics" data-testid={`${testId}-metrics`}>
          {metrics.map((metric) => (
            <span
              className={metric.tone ? `runtime-debug-metric ${metric.tone}` : 'runtime-debug-metric'}
              data-testid={`${testId}-metric`}
              key={metric.key}
            >
              <strong>{metric.value}</strong>
              <small>{metric.label}</small>
            </span>
          ))}
        </div>
      ) : null}
      {latestFacts.length || surfaces.length ? (
        <div className="runtime-debug-facts" data-testid={`${testId}-facts`}>
          {latestFacts.map((fact) => (
            <span key={fact}>{fact}</span>
          ))}
          {surfaces.map((surface) => (
            <em key={surface}>{surface}</em>
          ))}
        </div>
      ) : null}
    </section>
  );
}

export function runtimeDebugSummaryHasContent(summary?: RuntimeDebugSummarySnapshot | null): boolean {
  if (!summary) return false;
  if (summary.needs_user_action || summary.needs_replan) return true;
  if ((summary.debug_surfaces || []).length) return true;
  if (
    summary.source
    || summary.run_id
    || summary.task_id
    || summary.group_id
    || summary.group_run_id
    || summary.workflow_id
    || summary.workflow_run_id
    || summary.planner_decision_id
    || summary.planner_plan_id
    || summary.intent_kind
    || summary.intent_title
    || summary.task_status
    || summary.current_step_id
    || summary.current_step_title
    || summary.current_tool_name
    || summary.current_request_id
    || summary.current_request_tool_name
    || summary.current_request_status
    || summary.latest_request_id
    || summary.latest_request_tool_name
    || summary.latest_request_status
    || summary.desktop_provider_session_status
    || summary.desktop_provider_session_provider_id
    || summary.desktop_provider_session_reason
    || summary.desktop_provider_session_kind
    || summary.desktop_execution_session_label
    || summary.desktop_execution_session_mode
    || summary.runtime_doctrine
    || summary.runtime_stage
    || summary.runtime_role
    || summary.current_capability_id
    || summary.latest_event_type
    || summary.latest_replan_request_id
    || summary.latest_replan_trigger
    || summary.latest_replan_status
    || summary.latest_recovery_action_id
    || summary.latest_recovery_tool
    || summary.latest_recovery_action_label
    || summary.latest_deferred_tool
    || summary.latest_deferred_continuation_tool
    || summary.latest_tool_call_id
    || summary.latest_tool_name
    || summary.latest_tool_status
    || summary.latest_approval_id
    || summary.latest_approval_tool_name
    || summary.latest_approval_status
    || summary.latest_artifact_id
    || summary.latest_artifact_kind
    || summary.latest_artifact_path
  ) return true;
  return runtimeDebugMetrics(summary).length > 0;
}

function runtimeDebugMetrics(summary: RuntimeDebugSummarySnapshot): RuntimeDebugMetric[] {
  const metrics: RuntimeDebugMetric[] = [];
  addMetric(metrics, 'events', 'events', summary.event_count);
  addMetric(metrics, 'runtime_requests', 'requests', summary.runtime_request_count);
  addMetric(metrics, 'pending_runtime_requests', 'pending reqs', summary.pending_runtime_request_count);
  addMetric(metrics, 'completed_runtime_requests', 'done reqs', summary.completed_runtime_request_count, 'ready');
  addMetric(metrics, 'recovered_runtime_requests', 'recovered reqs', summary.recovered_runtime_request_count, 'ready');
  addMetric(metrics, 'failed_runtime_requests', 'failed reqs', summary.failed_runtime_request_count, 'danger');
  addMetric(metrics, 'blocked_runtime_requests', 'blocked reqs', summary.blocked_runtime_request_count, 'warning');
  addMetric(metrics, 'waiting_runtime_requests', 'waiting reqs', summary.waiting_runtime_request_count, 'warning');
  addProviderSessionMetric(metrics, summary);
  addMetric(metrics, 'tools', 'tools', summary.tool_call_count);
  addMetric(metrics, 'completed_tools', 'done', summary.completed_tool_call_count, 'ready');
  addMetric(metrics, 'failed_tools', 'failed', summary.failed_tool_call_count, 'danger');
  addMetric(metrics, 'blocked_tools', 'blocked', summary.blocked_tool_call_count, 'warning');
  addMetric(metrics, 'waiting_tools', 'waiting', summary.waiting_tool_call_count, 'warning');
  addMetric(metrics, 'approvals', 'approvals', summary.approval_count);
  addMetric(metrics, 'pending_approvals', 'pending', summary.pending_approval_count, 'warning');
  addProgressMetric(
    metrics,
    'todos',
    'todos',
    summary.completed_todos,
    summary.total_todos,
    summary.blocked_todos ? 'warning' : undefined,
  );
  addProgressMetric(
    metrics,
    'checkpoints',
    'checks',
    summary.completed_checkpoints,
    summary.total_checkpoints,
    summary.blocked_checkpoints ? 'warning' : undefined,
  );
  addMetric(metrics, 'artifacts', 'artifacts', summary.artifact_count);
  addMetric(metrics, 'replans', 'replans', summary.replan_recovery_count, 'warning');
  addMetric(metrics, 'recovery_actions', 'recoveries', summary.latest_recovery_action_count, 'warning');
  addMetric(metrics, 'deferred_continuations', 'deferred', summary.deferred_continuation_count, 'warning');
  addMetric(metrics, 'children', 'children', summary.child_run_count);
  addMetric(metrics, 'memory', 'memory', summary.memory_trace_count);
  addMetric(metrics, 'skills', 'skills', summary.skill_trace_count);
  return metrics.slice(0, 12);
}

function addProviderSessionMetric(
  metrics: RuntimeDebugMetric[],
  summary: RuntimeDebugSummarySnapshot,
) {
  const status = String(summary.desktop_provider_session_status || '').trim().toLowerCase();
  const needed = Boolean(summary.desktop_provider_session_needed);
  const running = Boolean(summary.desktop_provider_session_running);
  const started = Boolean(summary.desktop_provider_session_started);
  if (!status && !needed && !running && !started) return;
  if (status === 'start_failed' || status === 'failed') {
    metrics.push({ key: 'desktop_provider_session', label: 'desktop env', tone: 'danger', value: 'failed' });
    return;
  }
  if (needed && !running) {
    metrics.push({ key: 'desktop_provider_session', label: 'desktop env', tone: 'warning', value: 'needed' });
    return;
  }
  if (started) {
    metrics.push({ key: 'desktop_provider_session', label: 'desktop env', tone: 'ready', value: 'started' });
    return;
  }
  if (running) {
    metrics.push({ key: 'desktop_provider_session', label: 'desktop env', tone: 'ready', value: 'ready' });
    return;
  }
  if (status) {
    metrics.push({ key: 'desktop_provider_session', label: 'desktop env', value: status });
  }
}

function addMetric(
  metrics: RuntimeDebugMetric[],
  key: string,
  label: string,
  value: number | null | undefined,
  tone?: string,
) {
  if (typeof value !== 'number' || !Number.isFinite(value) || value <= 0) return;
  metrics.push({ key, label, tone, value });
}

function addProgressMetric(
  metrics: RuntimeDebugMetric[],
  key: string,
  label: string,
  completed: number | null | undefined,
  total: number | null | undefined,
  tone?: string,
) {
  if (typeof total !== 'number' || !Number.isFinite(total) || total <= 0) return;
  const safeCompleted = typeof completed === 'number' && Number.isFinite(completed) ? completed : 0;
  metrics.push({ key, label, tone, value: `${safeCompleted}/${total}` });
}

function runtimeDebugLatestFacts(summary?: RuntimeDebugSummarySnapshot | null): string[] {
  if (!summary) return [];
  const runtimeStages = runtimeDebugStageFacts(summary);
  const planTools = (summary.plan_tools || []).filter(Boolean).slice(0, 3);
  const planCapabilities = (summary.plan_capabilities || []).filter(Boolean).slice(0, 3);
  return [
    summary.intent_kind ? `intent ${summary.intent_kind}` : '',
    summary.intent_title ? `intent title ${summary.intent_title}` : '',
    summary.task_status ? `task ${summary.task_status}` : '',
    summary.current_step_title ? `step ${summary.current_step_title}` : '',
    summary.current_tool_name ? `current tool ${summary.current_tool_name}` : '',
    summary.current_request_id ? `current request ${summary.current_request_id}` : '',
    summary.current_request_tool_name ? `request tool ${summary.current_request_tool_name}` : '',
    summary.current_request_status ? `request status ${summary.current_request_status}` : '',
    summary.runtime_doctrine ? `doctrine ${summary.runtime_doctrine}` : '',
    summary.runtime_stage ? `stage ${summary.runtime_stage}` : '',
    summary.runtime_role ? `role ${summary.runtime_role}` : '',
    summary.current_capability_id ? `capability ${summary.current_capability_id}` : '',
    summary.route_to_studio ? 'route Studio' : '',
    summary.latest_event_type ? `event ${summary.latest_event_type}` : '',
    summary.latest_request_id ? `latest request ${summary.latest_request_id}` : '',
    summary.latest_request_tool_name ? `latest request tool ${summary.latest_request_tool_name}` : '',
    summary.latest_request_status ? `latest request status ${summary.latest_request_status}` : '',
    summary.desktop_provider_session_provider_id ? `desktop provider ${summary.desktop_provider_session_provider_id}` : '',
    summary.desktop_provider_session_status ? `desktop provider status ${summary.desktop_provider_session_status}` : '',
    summary.desktop_provider_session_kind ? `desktop session ${summary.desktop_provider_session_kind}` : '',
    summary.desktop_execution_session_label ? `execution session ${summary.desktop_execution_session_label}` : '',
    summary.desktop_execution_session_mode ? `execution mode ${summary.desktop_execution_session_mode}` : '',
    summary.desktop_provider_session_isolated === true ? 'isolated desktop session' : '',
    summary.desktop_provider_session_foreground_takeover_required === true ? 'foreground takeover required' : '',
    summary.desktop_provider_session_foreground_takeover_required === false ? 'no foreground takeover' : '',
    summary.desktop_provider_session_keyboard_mouse_capture_supported === true ? 'keyboard mouse capture ready' : '',
    (summary.desktop_provider_session_tool_names || []).length
      ? `provider tools ${(summary.desktop_provider_session_tool_names || []).slice(0, 3).join(', ')}`
      : '',
    summary.latest_replan_request_id ? `replan ${summary.latest_replan_request_id}` : '',
    summary.latest_replan_trigger ? `trigger ${summary.latest_replan_trigger}` : '',
    summary.latest_replan_status ? `replan status ${summary.latest_replan_status}` : '',
    summary.latest_recovery_tool ? `recovery ${summary.latest_recovery_tool}` : '',
    summary.latest_recovery_action_label ? `recovery action ${summary.latest_recovery_action_label}` : '',
    summary.latest_recovery_action_id ? `recovery id ${summary.latest_recovery_action_id}` : '',
    summary.latest_deferred_tool ? `deferred ${summary.latest_deferred_tool}` : '',
    summary.latest_deferred_continuation_tool ? `continuation ${summary.latest_deferred_continuation_tool}` : '',
    summary.latest_tool_call_id ? `tool call ${summary.latest_tool_call_id}` : '',
    summary.latest_tool_name ? `tool ${summary.latest_tool_name}` : '',
    summary.latest_tool_status ? `tool status ${summary.latest_tool_status}` : '',
    summary.latest_approval_id ? `approval ${summary.latest_approval_id}` : '',
    summary.latest_approval_tool_name ? `approval tool ${summary.latest_approval_tool_name}` : '',
    summary.latest_approval_status ? `approval status ${summary.latest_approval_status}` : '',
    summary.latest_artifact_id ? `artifact id ${summary.latest_artifact_id}` : '',
    summary.latest_artifact_kind ? `artifact kind ${summary.latest_artifact_kind}` : '',
    summary.latest_artifact_path ? `artifact ${summary.latest_artifact_path}` : '',
    planTools.length ? `plan tools ${planTools.join(', ')}` : '',
    planCapabilities.length ? `capabilities ${planCapabilities.join(', ')}` : '',
    ...runtimeStages,
  ].filter(Boolean);
}

function runtimeDebugContextFacts(summary?: RuntimeDebugSummarySnapshot | null): string[] {
  if (!summary) return [];
  return [
    summary.run_id ? `run ${summary.run_id}` : '',
    summary.task_id ? `task ${summary.task_id}` : '',
    summary.planner_plan_id ? `plan ${summary.planner_plan_id}` : '',
    summary.planner_decision_id ? `decision ${summary.planner_decision_id}` : '',
    summary.group_run_id ? `group run ${summary.group_run_id}` : '',
    summary.group_id ? `group ${summary.group_id}` : '',
    summary.workflow_run_id ? `workflow run ${summary.workflow_run_id}` : '',
    summary.workflow_id ? `workflow ${summary.workflow_id}` : '',
  ].filter(Boolean).slice(0, 4);
}

function runtimeDebugStageFacts(summary: RuntimeDebugSummarySnapshot): string[] {
  const stageCounts = summary.runtime_stage_counts || {};
  return Object.entries(stageCounts)
    .filter(([, count]) => typeof count === 'number' && Number.isFinite(count) && count > 0)
    .slice(0, 3)
    .map(([stage, count]) => `${stage} ${count}`);
}
