import type { PublicRunEvent, ToolCallSnapshot } from '../types';
import {
  runtimeToolDisplayLabel,
  runtimeToolDisplayLabelOrName,
  runtimeToolFamily,
} from '../approval';
import {
  runtimeEventIsDesktopForegroundSessionNotice,
  runtimeEventIsDesktopIntent,
  runtimeEventIsDesktopPermissionRecovery,
} from '../desktopEvents';
import { publicRunEventIsSecret } from '../runEvents';

export type RuntimeToolCallSummaryItem = {
  count: number;
  executionRoute?: Record<string, unknown>;
  name: string;
  policyReason?: string;
  riskLevel?: string;
  sequence: number;
  status: string;
};

const TOOL_EVENT_TYPES = new Set([
  'agent.tool.call',
  'agent.tool.denied',
  'agent.tool.foreground_session_notice',
  'agent.tool.started',
  'agent.tool.failed',
  'agent.tool.skipped',
  'agent.tool.approval_required',
  'agent.tool.approval_approved',
  'agent.tool.approval_rejected',
  'agent.tool.approval_timeout',
  'approval.timeout',
  'tool.approved',
  'tool.approval_approved',
  'tool.approval_rejected',
  'tool.requested',
  'tool.started',
  'tool.approval_required',
  'tool.approval_timeout',
  'tool.denied',
  'tool.rejected',
  'tool.skipped',
  'tool.completed',
  'agent.tool.completed',
  'tool.failed',
  'tool.cancelled',
  'agent.desktop.intent_planned',
  'agent.desktop.intent_approval_required',
  'agent.desktop.intent_completed',
  'agent.desktop.permission_recovery',
  'agent.desktop.intent_unavailable',
  'agent.desktop.intent_unverified',
  'skill.selected',
  'skill.dispatch.read',
  'memory.retrieved',
  'memory.write.add',
  'memory.write.replace',
  'memory.write.remove',
]);

export function RuntimeToolCallSummary({
  className = 'runtime-tool-call-summary',
  events,
  itemClassName = 'runtime-tool-call-summary-item',
  itemTestId = 'runtime-tool-call-summary-item',
  label = '工具',
  limit = 4,
  testId = 'runtime-tool-call-summary',
  toolCalls = [],
}: {
  className?: string;
  events: PublicRunEvent[];
  itemClassName?: string;
  itemTestId?: string;
  label?: string;
  limit?: number;
  testId?: string;
  toolCalls?: ToolCallSnapshot[];
}) {
  const tools = toolCalls.length
    ? summarizeRuntimeToolCallSnapshots(toolCalls, limit)
    : summarizeRuntimeToolCalls(events, limit);
  if (!tools.length) return null;

  return (
    <div className={className} data-testid={testId}>
      <span>{label}</span>
      <div>
        {tools.map((tool) => (
          <span
            className={`${itemClassName} status-${tool.status}`}
            data-testid={itemTestId}
            data-policy-reason={tool.policyReason || ''}
            data-risk-level={tool.riskLevel || ''}
            data-tool-family={runtimeToolFamily(tool.name)}
            data-tool-name={tool.name}
            data-tool-status={tool.status}
            key={tool.name}
          >
            <strong>{runtimeToolSummaryDisplayName(tool.name, tool.status, tool.executionRoute)}</strong>
            {tool.count > 1 ? <em>x{tool.count}</em> : null}
            {tool.riskLevel ? <em title={tool.policyReason || undefined}>{tool.riskLevel}</em> : null}
            <small>{runtimeToolStatusLabel(tool.status)}</small>
          </span>
        ))}
      </div>
    </div>
  );
}

export function summarizeRuntimeToolCallSnapshots(
  toolCalls: ToolCallSnapshot[],
  limit: number,
): RuntimeToolCallSummaryItem[] {
  const byName = new Map<string, RuntimeToolCallSummaryItem>();
  (toolCalls || []).forEach((toolCall, index) => {
    const name = String(toolCall.tool_name || '').trim();
    if (!name) return;
    const sequence = index + 1;
    const status = normalizeRuntimeToolStatus(String(toolCall.status || '').trim());
    const riskLevel = String(toolCall.risk_level || '').trim();
    const policyReason = String(toolCall.policy_reason || '').trim();
    const executionRoute = runtimeToolExecutionRouteFromSnapshot(toolCall);
    const previous = byName.get(name);
    if (previous) {
      previous.count += 1;
      if (sequence >= previous.sequence) {
        previous.sequence = sequence;
        previous.status = status;
        previous.riskLevel = riskLevel || previous.riskLevel;
        previous.policyReason = policyReason || previous.policyReason;
        previous.executionRoute = executionRoute;
      }
      return;
    }
    byName.set(name, {
      count: 1,
      executionRoute,
      name,
      policyReason,
      riskLevel,
      sequence,
      status: status || 'completed',
    });
  });

  return Array.from(byName.values())
    .sort((left, right) => right.sequence - left.sequence)
    .slice(0, Math.max(1, limit));
}

export function summarizeRuntimeToolCalls(
  events: PublicRunEvent[],
  limit: number,
): RuntimeToolCallSummaryItem[] {
  const byName = new Map<string, RuntimeToolCallSummaryItem>();
  for (const event of events || []) {
    if (publicRunEventIsSecret(event)) continue;
    const eventType = String(event.event_type || '').trim();
    if (!runtimeToolEventIsVisible(eventType)) continue;

    const name = runtimeToolNameFromEvent(event);
    const sequence = Number.isFinite(event.sequence) ? Number(event.sequence) : 0;
    const status = runtimeToolStatusFromEvent(event);
    const riskLevel = runtimeToolRiskLevelFromEvent(event);
    const policyReason = runtimeToolPolicyReasonFromEvent(event);
    const executionRoute = runtimeToolExecutionRouteFromEvent(event, name);
    const previous = byName.get(name);
    if (previous) {
      previous.count += 1;
      if (sequence >= previous.sequence) {
        previous.sequence = sequence;
        previous.status = status;
        previous.riskLevel = riskLevel || previous.riskLevel;
        previous.policyReason = policyReason || previous.policyReason;
        previous.executionRoute = executionRoute;
      }
      continue;
    }

    byName.set(name, {
      count: 1,
      executionRoute,
      name,
      policyReason,
      riskLevel,
      sequence,
      status,
    });
  }

  return Array.from(byName.values())
    .sort((left, right) => right.sequence - left.sequence)
    .slice(0, Math.max(1, limit));
}

function runtimeToolExecutionRouteFromSnapshot(
  toolCall: ToolCallSnapshot,
): Record<string, unknown> | undefined {
  const runtimeMetadata = recordPayload(toolCall.runtime_execution_metadata);
  const metadata = recordPayload(toolCall.metadata);
  const input = recordPayload(toolCall.input_preview);
  const output = recordPayload(toolCall.output_preview);
  const deferredContext = recordPayload(toolCall.deferred_context);
  const envelope = recordPayload(toolCall.runtime_execution_envelope);
  return firstRuntimeToolExecutionRoute(
    objectPayload(runtimeMetadata, 'desktop_execution_route'),
    objectPayload(metadata, 'desktop_execution_route'),
    objectPayload(input, 'desktop_execution_route'),
    objectPayload(output, 'desktop_execution_route'),
    objectPayload(deferredContext, 'desktop_execution_route'),
    objectPayload(envelope, 'desktop_execution_route'),
    runtimeToolExecutionRequestRoute(envelope, toolCall.tool_name),
  );
}

function runtimeToolExecutionRouteFromEvent(
  event: PublicRunEvent,
  toolName: string,
): Record<string, unknown> | undefined {
  const payload = recordPayload(event.payload);
  const result = objectPayload(payload, 'result');
  const metadata = objectPayload(payload, 'metadata');
  const resultMetadata = objectPayload(result, 'metadata');
  const runtimeMetadata = objectPayload(payload, 'runtime_execution_metadata');
  const input = objectPayload(payload, 'input') || objectPayload(payload, 'input_preview');
  const envelope = objectPayload(payload, 'runtime_execution_envelope')
    || objectPayload(runtimeMetadata, 'runtime_execution_envelope')
    || objectPayload(metadata, 'runtime_execution_envelope');
  return firstRuntimeToolExecutionRoute(
    objectPayload(payload, 'desktop_execution_route'),
    objectPayload(result, 'desktop_execution_route'),
    objectPayload(runtimeMetadata, 'desktop_execution_route'),
    objectPayload(metadata, 'desktop_execution_route'),
    objectPayload(resultMetadata, 'desktop_execution_route'),
    objectPayload(input, 'desktop_execution_route'),
    objectPayload(envelope, 'desktop_execution_route'),
    runtimeToolExecutionRequestRoute(envelope, toolName),
  );
}

function runtimeToolExecutionRequestRoute(
  envelope: Record<string, unknown> | undefined,
  toolName: string,
): Record<string, unknown> | undefined {
  const requests = envelope?.requests;
  if (!Array.isArray(requests)) return undefined;
  const requestRecords = requests.map(recordPayload).filter(Boolean) as Record<string, unknown>[];
  const matchingRequest = requestRecords.find((request) => (
    (stringPayload(request, 'tool_name') || stringPayload(request, 'tool')) === toolName
    && Boolean(objectPayload(request, 'desktop_execution_route'))
  ));
  return objectPayload(matchingRequest, 'desktop_execution_route');
}

function firstRuntimeToolExecutionRoute(
  ...routes: Array<Record<string, unknown> | undefined>
): Record<string, unknown> | undefined {
  return routes.find((route) => Boolean(route && Object.keys(route).length));
}

function recordPayload(value: unknown): Record<string, unknown> | undefined {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function runtimeToolRiskLevelFromEvent(event: PublicRunEvent): string {
  const pendingApproval = objectPayload(event.payload, 'pending_approval');
  const approval = objectPayload(event.payload, 'approval');
  return (
    stringPayload(event.payload, 'risk_level') ||
    stringPayload(event.payload, 'risk') ||
    stringPayload(pendingApproval, 'risk_level') ||
    stringPayload(pendingApproval, 'risk') ||
    stringPayload(approval, 'risk_level') ||
    stringPayload(approval, 'risk')
  );
}

function runtimeToolPolicyReasonFromEvent(event: PublicRunEvent): string {
  const pendingApproval = objectPayload(event.payload, 'pending_approval');
  const approval = objectPayload(event.payload, 'approval');
  return (
    stringPayload(event.payload, 'policy_reason') ||
    stringPayload(event.payload, 'approval_reason') ||
    stringPayload(pendingApproval, 'policy_reason') ||
    stringPayload(pendingApproval, 'reason') ||
    stringPayload(approval, 'policy_reason') ||
    stringPayload(approval, 'reason')
  );
}

function runtimeToolEventIsVisible(eventType: string): boolean {
  return (
    TOOL_EVENT_TYPES.has(eventType)
    || runtimeEventIsDesktopIntent(eventType, 'planned')
    || runtimeEventIsDesktopIntent(eventType, 'approval_required')
    || runtimeEventIsDesktopIntent(eventType, 'completed')
    || runtimeEventIsDesktopPermissionRecovery(eventType)
    || runtimeEventIsDesktopIntent(eventType, 'unavailable')
    || runtimeEventIsDesktopIntent(eventType, 'unverified')
    || eventType.startsWith('skill.dispatch.')
    || eventType.startsWith('memory.write.')
  );
}

function runtimeToolNameFromEvent(event: PublicRunEvent): string {
  const eventType = String(event.event_type || '').trim();
  if (eventType === 'memory.retrieved') return 'Memory 检索';
  if (eventType.startsWith('memory.write.')) {
    return (
      stringPayload(objectPayload(event.payload, 'result'), 'action') ||
      stringPayload(event.payload, 'tool') ||
      'Memory 写入'
    );
  }
  if (eventType === 'skill.selected' || eventType.startsWith('skill.dispatch.')) {
    return (
      stringPayload(objectPayload(event.payload, 'result'), 'name') ||
      stringPayload(event.payload, 'skill_name') ||
      stringPayload(objectPayload(event.payload, 'result'), 'skill_id') ||
      stringPayload(event.payload, 'skill_id') ||
      stringPayload(event.payload, 'tool') ||
      'Skill'
    );
  }
  const fallbackName = String(event.detail || event.title || 'tool').trim();
  return (
    stringPayload(event.payload, 'tool_name') ||
    stringPayload(event.payload, 'tool') ||
    stringPayload(event.payload, 'name') ||
    fallbackName ||
    'tool'
  );
}

function runtimeToolStatusFromEvent(event: PublicRunEvent): string {
  const payloadStatus = normalizeRuntimeToolStatus(stringPayload(event.payload, 'status'));
  if (payloadStatus) return payloadStatus;

  const resultStatus = runtimeToolResultStatus(objectPayload(event.payload, 'result'))
    || runtimeToolResultStatus(event.payload);
  if (resultStatus) return resultStatus;

  const eventType = String(event.event_type || '').trim();
  if (runtimeEventIsDesktopForegroundSessionNotice(eventType)) return 'foreground_session';
  if (eventType === 'agent.tool.denied') return 'denied';
  if (eventType === 'agent.tool.started') return 'running';
  if (eventType === 'agent.tool.failed' || eventType === 'tool.failed') return 'failed';
  if (eventType === 'tool.cancelled') return 'cancelled';
  if (eventType === 'agent.tool.skipped' || eventType === 'tool.skipped') return 'skipped';
  if (eventType === 'agent.tool.approval_required' || eventType === 'tool.approval_required') {
    return 'waiting_approval';
  }
  if (eventType === 'agent.tool.approval_approved' || eventType === 'tool.approved' || eventType === 'tool.approval_approved') return 'approved';
  if (eventType === 'agent.tool.approval_rejected' || eventType === 'tool.rejected' || eventType === 'tool.denied' || eventType === 'tool.approval_rejected') return 'denied';
  if (
    eventType === 'agent.tool.approval_timeout' ||
    eventType === 'approval.timeout' ||
    eventType === 'tool.approval_timeout'
  ) {
    return 'expired';
  }
  if (
    eventType === 'agent.tool.call' ||
    eventType === 'agent.tool.completed' ||
    eventType === 'tool.completed' ||
    eventType === 'skill.selected' ||
    eventType === 'memory.retrieved'
  ) {
    return 'completed';
  }
  if (eventType.startsWith('skill.dispatch.') || eventType.startsWith('memory.write.')) {
    return 'completed';
  }
  if (eventType === 'tool.started') return 'running';
  if (eventType === 'tool.requested') return 'queued';
  if (runtimeEventIsDesktopIntent(eventType, 'planned')) return 'planned';
  if (runtimeEventIsDesktopIntent(eventType, 'approval_required')) return 'waiting_approval';
  if (runtimeEventIsDesktopPermissionRecovery(eventType)) return 'waiting_approval';
  if (runtimeEventIsDesktopIntent(eventType, 'completed')) return 'completed';
  if (runtimeEventIsDesktopIntent(eventType, 'unavailable')) return 'unavailable';
  if (runtimeEventIsDesktopIntent(eventType, 'unverified')) return 'failed';
  return 'running';
}

function normalizeRuntimeToolStatus(status: string): string {
  if (!status) return '';
  if (status === 'approval_required') return 'waiting_approval';
  if (status === 'foreground_session_routed') return 'foreground_session';
  const knownStatuses = [
    'queued',
    'planned',
    'resolved',
    'running',
    'waiting_approval',
    'approved',
    'completed',
    'failed',
    'cancelled',
    'denied',
    'skipped',
    'expired',
    'blocked',
    'foreground_session',
    'unavailable',
  ];
  if (knownStatuses.includes(status)) {
    return status;
  }
  return 'running';
}

function runtimeToolResultStatus(result: Record<string, unknown> | undefined): string {
  if (!result) return '';
  if (result.foreground_lock_busy === true) return 'blocked';
  if (result.approval_required === true) return 'waiting_approval';
  if (result.ok === false) return 'failed';
  return '';
}

function stringPayload(payload: Record<string, unknown> | undefined, key: string): string {
  const value = payload?.[key];
  return typeof value === 'string' ? value.trim() : '';
}

function objectPayload(payload: Record<string, unknown> | undefined, key: string): Record<string, unknown> | undefined {
  const value = payload?.[key];
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : undefined;
}

function runtimeToolStatusLabel(status: string): string {
  if (status === 'queued') return '已请求';
  if (status === 'planned') return '已规划';
  if (status === 'resolved') return '已解析';
  if (status === 'running') return '执行中';
  if (status === 'waiting_approval') return '待审批';
  if (status === 'approved') return '已批准';
  if (status === 'completed') return '已完成';
  if (status === 'failed') return '失败';
  if (status === 'cancelled') return '已取消';
  if (status === 'denied') return '已拒绝';
  if (status === 'skipped') return '已跳过';
  if (status === 'expired') return '已超时';
  if (status === 'blocked') return '被占用';
  if (status === 'foreground_session') return '前台会话';
  if (status === 'unavailable') return '不可用';
  return status || '工具';
}

function runtimeToolSummaryDisplayName(
  name: string,
  status: string,
  executionRoute?: Record<string, unknown>,
): string {
  const activeLabel = runtimeToolActiveSummaryLabel(name, status, executionRoute);
  if (activeLabel) return activeLabel;
  return runtimeToolDisplayLabelOrName(name, executionRoute);
}

function runtimeToolActiveSummaryLabel(
  name: string,
  status: string,
  executionRoute?: Record<string, unknown>,
): string {
  if (!['queued', 'planned', 'running'].includes(status)) return '';
  const tool = String(name || '').trim();
  if (tool === 'screen.capture') return '正在截图';
  if (tool === 'desktop.active_window') return '正在读取前台窗口';
  if (tool === 'app.open') return '正在打开应用';
  if (tool === 'app.focus') return '正在聚焦应用';
  if (tool === 'app.open_and_safe_type_text') return '正在打开应用并输入文字';
  if (tool === 'app.focus_and_safe_type_text') return '正在聚焦应用并输入文字';
  if (tool === 'app.open_and_safe_shortcut') return '正在打开应用并执行快捷动作';
  if (tool === 'app.focus_and_safe_shortcut') return '正在聚焦应用并执行快捷动作';
  if (tool === 'media.apple_music_play') return '正在打开 Music';
  if (tool === 'media.apple_music_control') return '正在控制 Music';
  if (tool === 'desktop.safe_shortcut') return '正在执行快捷动作';
  if (tool === 'desktop.safe_type_text' || tool === 'desktop.safe_click') {
    return `正在${runtimeToolDisplayLabel(tool, executionRoute)}`;
  }
  if (tool === 'desktop.hotkey') return '正在发送快捷键';
  if (tool === 'desktop.type_text') return '正在输入前台文字';
  if (tool === 'browser.open_url') return '正在打开网页';
  if (tool === 'browser.open_url_and_extract_text') return '正在打开并读取网页';
  if (tool === 'browser.open_url_and_screenshot') return '正在打开并截取网页';
  if (tool === 'browser.current_page') return '正在读取当前网页';
  if (tool === 'browser.click') return '正在点击网页';
  if (tool === 'browser.type_text') return '正在填写网页输入';
  if (tool === 'browser.extract_text') return '正在提取网页文本';
  if (tool === 'browser.screenshot') return '正在截取网页';
  return '';
}
