import type { ApprovalCardSnapshot, PublicRunEvent, ToolCallSnapshot } from './types';
import { publicRunEventIsSecret } from './runEvents';

type ApprovalReplayCorrelationKeys = {
  strongKeys: string[];
  weakKey: string;
};

type ApprovalReplayWeakIndex = number | 'ambiguous';

export function toolCallsFromRunEventReplay(events: PublicRunEvent[]): ToolCallSnapshot[] {
  const calls: ToolCallSnapshot[] = [];
  const activeByKey = new Map<string, number>();
  events.forEach((event) => {
    if (publicRunEventIsSecret(event)) return;
    const toolCall = toolCallFromRunEvent(event);
    if (!toolCall) return;
    const key = toolCallCorrelationKey(event, toolCall);
    const activeIndex = key ? activeByKey.get(key) : undefined;
    if (activeIndex === undefined) {
      const nextIndex = calls.length;
      calls.push(toolCall);
      if (key && !toolCallStatusIsTerminal(toolCall.status)) activeByKey.set(key, nextIndex);
      return;
    }
    calls[activeIndex] = mergeToolCallReplayTrace(calls[activeIndex], toolCall);
    if (key) {
      if (toolCallStatusIsTerminal(toolCall.status)) activeByKey.delete(key);
      else activeByKey.set(key, activeIndex);
    }
  });
  return calls;
}

export function mergeToolCallSnapshots(
  timelineToolCalls: ToolCallSnapshot[],
  replayToolCalls: ToolCallSnapshot[],
): ToolCallSnapshot[] {
  const byId = new Map<string, ToolCallSnapshot>();
  timelineToolCalls.forEach((toolCall) => byId.set(toolCall.tool_call_id, toolCall));
  replayToolCalls.forEach((toolCall) => {
    const existing = byId.get(toolCall.tool_call_id);
    if (!existing) {
      byId.set(toolCall.tool_call_id, toolCall);
      return;
    }
    byId.set(toolCall.tool_call_id, mergeToolCallTrace(existing, toolCall));
  });
  return Array.from(byId.values());
}

export function artifactsFromRunEventReplay(events: PublicRunEvent[]): Array<Record<string, unknown>> {
  return events
    .filter((event) => !publicRunEventIsSecret(event))
    .map(artifactFromRunEvent)
    .filter((artifact): artifact is Record<string, unknown> => Boolean(artifact));
}

export function mergeArtifactSnapshots(
  timelineArtifacts: Array<Record<string, unknown>>,
  replayArtifacts: Array<Record<string, unknown>>,
): Array<Record<string, unknown>> {
  const byKey = new Map<string, Record<string, unknown>>();
  timelineArtifacts.forEach((artifact, index) => {
    byKey.set(artifactRecordKey(artifact, index), artifact);
  });
  replayArtifacts.forEach((artifact, index) => {
    const key = artifactRecordKey(artifact, index);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, artifact);
      return;
    }
    byKey.set(key, mergeArtifactTrace(existing, artifact));
  });
  return Array.from(byKey.values());
}

export function approvalsFromRunEventReplay(events: PublicRunEvent[]): ApprovalCardSnapshot[] {
  const approvals: ApprovalCardSnapshot[] = [];
  const activeByStrongKey = new Map<string, number>();
  const activeByWeakKey = new Map<string, ApprovalReplayWeakIndex>();
  const activeKeysByIndex = new Map<number, ApprovalReplayCorrelationKeys>();
  events.forEach((event) => {
    if (publicRunEventIsSecret(event)) return;
    const approval = approvalFromRunEvent(event);
    if (!approval) return;
    const keys = approvalReplayCorrelationKeys(approval);
    const activeIndex = approvalReplayActiveIndex(
      keys,
      activeByStrongKey,
      activeByWeakKey,
      approval.status !== 'pending',
    );
    if (activeIndex === undefined) {
      const nextIndex = approvals.length;
      approvals.push(approval);
      if (approval.status === 'pending') {
        registerActiveApprovalReplay(
          nextIndex,
          keys,
          activeByStrongKey,
          activeByWeakKey,
          activeKeysByIndex,
        );
      }
      return;
    }
    approvals[activeIndex] = mergeApprovalReplayTrace(approvals[activeIndex], approval);
    if (approval.status === 'pending') {
      registerActiveApprovalReplay(
        activeIndex,
        keys,
        activeByStrongKey,
        activeByWeakKey,
        activeKeysByIndex,
      );
    } else {
      unregisterActiveApprovalReplay(
        activeIndex,
        activeByStrongKey,
        activeByWeakKey,
        activeKeysByIndex,
      );
    }
  });
  return approvals;
}

export function mergeApprovalSnapshots(
  timelineApprovals: ApprovalCardSnapshot[],
  replayApprovals: ApprovalCardSnapshot[],
): ApprovalCardSnapshot[] {
  const byKey = new Map<string, ApprovalCardSnapshot>();
  timelineApprovals.forEach((approval, index) => {
    byKey.set(approvalRecordKey(approval, index), approval);
  });
  replayApprovals.forEach((approval, index) => {
    const key = approvalRecordKey(approval, index);
    const existing = byKey.get(key);
    if (!existing) {
      byKey.set(key, approval);
      return;
    }
    byKey.set(key, mergeApprovalTrace(existing, approval));
  });
  return Array.from(byKey.values());
}

function approvalFromRunEvent(event: PublicRunEvent): ApprovalCardSnapshot | null {
  if (!isApprovalRunEvent(event.event_type)) return null;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const source = objectPreview(payload.pending_approval)
    || objectPreview(payload.approval)
    || payload;
  const toolName = publicRunEventPayloadString(source, 'tool_name')
    || publicRunEventPayloadString(source, 'tool')
    || approvalToolFromRunEvent(event.event_type)
    || event.detail
    || 'approval';
  const approvalId = publicRunEventPayloadString(source, 'approval_id')
    || `${event.run_id}:${event.event_type}:${event.sequence}`;
  const status = publicRunEventPayloadString(source, 'status') || approvalStatusFromRunEvent(event.event_type);
  return {
    approval_id: approvalId,
    description: publicRunEventPayloadString(source, 'description') || null,
    input_preview: objectPreview(source.input_preview) || objectPreview(source.input) || {},
    policy_reason: publicRunEventPayloadString(source, 'policy_reason') || null,
    requested_at: publicRunEventPayloadString(source, 'requested_at') || event.created_at || '',
    resolved_at: publicRunEventPayloadString(source, 'resolved_at')
      || (status !== 'pending' ? event.created_at || '' : null),
    risk_level: publicRunEventPayloadString(source, 'risk_level')
      || publicRunEventPayloadString(source, 'risk')
      || null,
    run_id: publicRunEventPayloadString(source, 'run_id') || event.run_id,
    source_run_id: publicRunEventPayloadString(source, 'source_run_id')
      || publicRunEventPayloadString(payload, 'source_run_id')
      || null,
    source_runnable_id: publicRunEventPayloadString(source, 'source_runnable_id')
      || publicRunEventPayloadString(source, 'source_agent_id')
      || publicRunEventPayloadString(source, 'member_agent_id')
      || publicRunEventPayloadString(source, 'agent_id')
      || publicRunEventPayloadString(payload, 'source_runnable_id')
      || publicRunEventPayloadString(payload, 'source_agent_id')
      || publicRunEventPayloadString(payload, 'member_agent_id')
      || publicRunEventPayloadString(payload, 'agent_id')
      || null,
    source_runnable_name: publicRunEventPayloadString(source, 'source_runnable_name')
      || publicRunEventPayloadString(source, 'source_agent_name')
      || publicRunEventPayloadString(source, 'member_agent_name')
      || publicRunEventPayloadString(source, 'agent_name')
      || publicRunEventPayloadString(payload, 'source_runnable_name')
      || publicRunEventPayloadString(payload, 'source_agent_name')
      || publicRunEventPayloadString(payload, 'member_agent_name')
      || publicRunEventPayloadString(payload, 'agent_name')
      || null,
    workflow_id: publicRunEventPayloadString(source, 'workflow_id')
      || publicRunEventPayloadString(payload, 'workflow_id')
      || null,
    workflow_run_id: publicRunEventPayloadString(source, 'workflow_run_id')
      || publicRunEventPayloadString(payload, 'workflow_run_id')
      || null,
    workflow_node_id: publicRunEventPayloadString(source, 'workflow_node_id')
      || publicRunEventPayloadString(payload, 'workflow_node_id')
      || null,
    workflow_node_label: publicRunEventPayloadString(source, 'workflow_node_label')
      || publicRunEventPayloadString(payload, 'workflow_node_label')
      || null,
    group_id: publicRunEventPayloadString(source, 'group_id')
      || publicRunEventPayloadString(payload, 'group_id')
      || null,
    group_run_id: publicRunEventPayloadString(source, 'group_run_id')
      || publicRunEventPayloadString(source, 'run_group_id')
      || publicRunEventPayloadString(payload, 'group_run_id')
      || publicRunEventPayloadString(payload, 'run_group_id')
      || null,
    status,
    title: publicRunEventPayloadString(source, 'title') || `Approval · ${toolName}`,
    tool_name: toolName,
  };
}

function toolCallFromRunEvent(event: PublicRunEvent): ToolCallSnapshot | null {
  if (!isToolRunEvent(event.event_type)) return null;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const status = publicRunEventPayloadString(payload, 'status') || toolStatusFromRunEvent(event.event_type);
  const outputPreview = objectPreview(payload.output_preview)
    || objectPreview(payload.output)
    || objectPreview(payload.result)
    || (payload.error !== undefined ? { error: payload.error } : {});
  const toolName = publicRunEventPayloadString(payload, 'tool_name')
    || publicRunEventPayloadString(payload, 'tool')
    || event.detail
    || 'tool';
  return {
    tool_call_id: publicRunEventPayloadString(payload, 'tool_call_id')
      || publicRunEventPayloadString(payload, 'id')
      || event.event_id
      || `${event.run_id}:${event.event_type}:${event.sequence}`,
    run_id: event.run_id,
    source_run_id: publicRunEventPayloadString(payload, 'source_run_id') || null,
    source_runnable_id: publicRunEventPayloadString(payload, 'source_runnable_id')
      || publicRunEventPayloadString(payload, 'source_agent_id')
      || publicRunEventPayloadString(payload, 'member_agent_id')
      || publicRunEventPayloadString(payload, 'agent_id')
      || null,
    source_runnable_name: publicRunEventPayloadString(payload, 'source_runnable_name')
      || publicRunEventPayloadString(payload, 'source_agent_name')
      || publicRunEventPayloadString(payload, 'member_agent_name')
      || publicRunEventPayloadString(payload, 'agent_name')
      || null,
    workflow_id: publicRunEventPayloadString(payload, 'workflow_id') || null,
    workflow_run_id: publicRunEventPayloadString(payload, 'workflow_run_id') || null,
    workflow_node_id: publicRunEventPayloadString(payload, 'workflow_node_id') || null,
    workflow_node_label: publicRunEventPayloadString(payload, 'workflow_node_label') || null,
    group_id: publicRunEventPayloadString(payload, 'group_id') || null,
    group_run_id: publicRunEventPayloadString(payload, 'group_run_id')
      || publicRunEventPayloadString(payload, 'run_group_id')
      || null,
    tool_name: toolName,
    status,
    risk_level: publicRunEventPayloadString(payload, 'risk_level')
      || publicRunEventPayloadString(payload, 'risk')
      || null,
    input_preview: objectPreview(payload.input_preview)
      || objectPreview(payload.input)
      || objectPreview(payload.arguments)
      || objectPreview(payload.args)
      || {},
    output_preview: outputPreview,
    approval_id: publicRunEventPayloadString(payload, 'approval_id') || null,
    started_at: publicRunEventPayloadString(payload, 'started_at') || event.created_at || '',
    completed_at: publicRunEventPayloadString(payload, 'completed_at')
      || (toolCallStatusIsTerminal(status) ? event.created_at || null : null),
  };
}

function artifactFromRunEvent(event: PublicRunEvent): Record<string, unknown> | null {
  if (!isArtifactRunEvent(event.event_type)) return null;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  let artifactPayload: Record<string, unknown> | null = null;
  if (event.event_type === 'artifact.created' || event.event_type === 'agent.artifact.write') {
    artifactPayload = { ...(objectPreview(payload.artifact) || payload) };
    if (event.event_type === 'agent.artifact.write') {
      artifactPayload.kind = artifactPayload.kind || 'agent_artifact';
      artifactPayload.path = artifactPayload.path || event.detail;
    }
  } else if (event.event_type === 'group.artifact.created' || event.event_type === 'group.shared_artifact.created') {
    artifactPayload = { ...(objectPreview(payload.artifact) || payload) };
    artifactPayload.kind = artifactPayload.kind || 'group_artifact';
    artifactPayload.source_runnable_name = artifactPayload.source_runnable_name || payload.member_agent_name;
    artifactPayload.source_runnable_id = artifactPayload.source_runnable_id || payload.member_agent_id;
    artifactPayload.group_id = artifactPayload.group_id || payload.group_id;
    artifactPayload.group_run_id = artifactPayload.group_run_id || payload.group_run_id || payload.run_group_id;
  } else if (event.event_type === 'workflow.node.artifact') {
    artifactPayload = {
      kind: 'workflow_artifact',
      title: payload.workflow_node_label || 'Workflow Artifact',
      workflow_id: payload.workflow_id,
      workflow_run_id: payload.workflow_run_id || event.run_id,
      workflow_node_id: payload.workflow_node_id,
      workflow_node_label: payload.workflow_node_label,
      workflow_step_label: payload.workflow_node_label,
      ...(objectPreview(payload.artifact) || payload),
    };
  }
  if (!artifactPayload) return null;
  mergeArtifactTraceContext(artifactPayload, payload);
  const path = publicRunEventPayloadString(artifactPayload, 'path')
    || publicRunEventPayloadString(artifactPayload, 'artifact_path');
  const artifactId = publicRunEventPayloadString(artifactPayload, 'artifact_id')
    || publicRunEventPayloadString(artifactPayload, 'id');
  if (!artifactId && !path) return null;
  return {
    ...artifactPayload,
    artifact_id: artifactId || `${event.run_id}:${path || event.event_type}:${event.sequence}`,
    created_at: publicRunEventPayloadString(artifactPayload, 'created_at') || event.created_at || '',
    kind: publicRunEventPayloadString(artifactPayload, 'kind') || 'artifact',
    path,
    run_id: publicRunEventPayloadString(artifactPayload, 'run_id') || event.run_id,
    source_run_id: publicRunEventPayloadString(artifactPayload, 'source_run_id') || event.run_id,
    source_tool: publicRunEventPayloadString(artifactPayload, 'source_tool')
      || publicRunEventPayloadString(artifactPayload, 'tool')
      || null,
    source_runnable_id: publicRunEventPayloadString(artifactPayload, 'source_runnable_id') || null,
    source_runnable_name: publicRunEventPayloadString(artifactPayload, 'source_runnable_name') || null,
    workflow_id: publicRunEventPayloadString(artifactPayload, 'workflow_id') || null,
    workflow_run_id: publicRunEventPayloadString(artifactPayload, 'workflow_run_id') || null,
    workflow_node_id: publicRunEventPayloadString(artifactPayload, 'workflow_node_id') || null,
    workflow_node_label: publicRunEventPayloadString(artifactPayload, 'workflow_node_label') || null,
    group_id: publicRunEventPayloadString(artifactPayload, 'group_id') || null,
    group_run_id: publicRunEventPayloadString(artifactPayload, 'group_run_id')
      || publicRunEventPayloadString(artifactPayload, 'run_group_id')
      || null,
    title: publicRunEventPayloadString(artifactPayload, 'title') || path || 'Artifact',
  };
}

function mergeApprovalTrace(current: ApprovalCardSnapshot, incoming: ApprovalCardSnapshot): ApprovalCardSnapshot {
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
  };
}

function mergeApprovalReplayTrace(
  current: ApprovalCardSnapshot,
  incoming: ApprovalCardSnapshot,
): ApprovalCardSnapshot {
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
    description: incoming.description || current.description || null,
    input_preview: {
      ...(current.input_preview || {}),
      ...(incoming.input_preview || {}),
    },
    policy_reason: current.policy_reason || incoming.policy_reason || null,
    requested_at: current.requested_at || incoming.requested_at || '',
    resolved_at: incoming.resolved_at || current.resolved_at || null,
    risk_level: current.risk_level || incoming.risk_level || null,
    status: incoming.status || current.status,
    tool_name: current.tool_name || incoming.tool_name,
  };
}

function mergeToolCallTrace(current: ToolCallSnapshot, incoming: ToolCallSnapshot): ToolCallSnapshot {
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
  };
}

function mergeToolCallReplayTrace(current: ToolCallSnapshot, incoming: ToolCallSnapshot): ToolCallSnapshot {
  const outputPreview = {
    ...(current.output_preview || {}),
    ...(incoming.output_preview || {}),
  };
  return {
    ...current,
    source_run_id: current.source_run_id || incoming.source_run_id || null,
    source_runnable_id: current.source_runnable_id || incoming.source_runnable_id || null,
    source_runnable_name: current.source_runnable_name || incoming.source_runnable_name || null,
    workflow_id: current.workflow_id || incoming.workflow_id || null,
    workflow_run_id: current.workflow_run_id || incoming.workflow_run_id || null,
    workflow_node_id: current.workflow_node_id || incoming.workflow_node_id || null,
    workflow_node_label: current.workflow_node_label || incoming.workflow_node_label || null,
    group_id: current.group_id || incoming.group_id || null,
    group_run_id: current.group_run_id || incoming.group_run_id || null,
    status: incoming.status || current.status,
    risk_level: current.risk_level || incoming.risk_level || null,
    input_preview: {
      ...(current.input_preview || {}),
      ...(incoming.input_preview || {}),
    },
    output_preview: Object.keys(outputPreview).length ? outputPreview : {},
    approval_id: current.approval_id || incoming.approval_id || null,
    started_at: current.started_at || incoming.started_at || '',
    completed_at: incoming.completed_at || (
      toolCallStatusIsTerminal(incoming.status) ? incoming.started_at || current.completed_at || null : current.completed_at || null
    ),
  };
}

function mergeArtifactTrace(
  current: Record<string, unknown>,
  incoming: Record<string, unknown>,
): Record<string, unknown> {
  const merged = { ...current };
  [
    'source_tool',
    'source_run_id',
    'source_runnable_id',
    'source_runnable_name',
    'workflow_id',
    'workflow_run_id',
    'workflow_node_id',
    'workflow_node_label',
    'workflow_step_label',
    'group_id',
    'group_run_id',
  ].forEach((key) => {
    if (!merged[key] && incoming[key]) merged[key] = incoming[key];
  });
  return merged;
}

function mergeArtifactTraceContext(
  artifactPayload: Record<string, unknown>,
  payload: Record<string, unknown>,
) {
  if (!artifactPayload.source_tool) artifactPayload.source_tool = payload.source_tool || payload.tool;
  if (!artifactPayload.source_runnable_id) {
    artifactPayload.source_runnable_id = payload.source_runnable_id
      || payload.source_agent_id
      || payload.member_agent_id
      || payload.agent_id;
  }
  if (!artifactPayload.source_runnable_name) {
    artifactPayload.source_runnable_name = payload.source_runnable_name
      || payload.source_agent_name
      || payload.member_agent_name
      || payload.agent_name;
  }
  [
    'workflow_id',
    'workflow_run_id',
    'workflow_node_id',
    'workflow_node_label',
    'group_id',
    'group_run_id',
  ].forEach((key) => {
    if (!artifactPayload[key] && payload[key]) artifactPayload[key] = payload[key];
  });
  if (!artifactPayload.group_run_id && payload.run_group_id) {
    artifactPayload.group_run_id = payload.run_group_id;
  }
}

function isApprovalRunEvent(eventType: string): boolean {
  return eventType.includes('approval_required')
    || eventType.includes('approval_approved')
    || eventType.includes('approval_rejected')
    || ['approval.approved', 'approval.rejected', 'approval.timeout', 'tool.approved', 'tool.rejected'].includes(eventType);
}

function approvalStatusFromRunEvent(eventType: string): ApprovalCardSnapshot['status'] {
  if (eventType.includes('approval_approved') || eventType === 'approval.approved' || eventType === 'tool.approved') return 'approved';
  if (eventType.includes('approval_rejected') || eventType === 'approval.rejected' || eventType === 'tool.rejected') return 'rejected';
  if (eventType.includes('approval_timeout') || eventType === 'approval.timeout') return 'expired';
  return 'pending';
}

function approvalToolFromRunEvent(eventType: string): string {
  if (eventType.startsWith('workflow.')) return 'workflow.approval';
  if (eventType.startsWith('group.')) return 'group.approval';
  if (eventType.startsWith('agent.tool.') || eventType.startsWith('tool.') || eventType.startsWith('approval.')) return 'tool.approval';
  return '';
}

function isArtifactRunEvent(eventType: string): boolean {
  return [
    'artifact.created',
    'agent.artifact.write',
    'group.artifact.created',
    'group.shared_artifact.created',
    'workflow.node.artifact',
  ].includes(eventType);
}

function isToolRunEvent(eventType: string): boolean {
  return [
    'agent.tool.call',
    'agent.tool.denied',
    'agent.tool.started',
    'agent.tool.failed',
    'agent.tool.skipped',
    'agent.tool.approval_required',
    'agent.tool.approval_approved',
    'agent.tool.approval_rejected',
    'agent.tool.approval_timeout',
    'agent.tool.completed',
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
    'tool.failed',
    'tool.cancelled',
  ].includes(eventType);
}

function toolStatusFromRunEvent(eventType: string): string {
  if (eventType === 'tool.requested') return 'requested';
  if (eventType === 'tool.started' || eventType === 'agent.tool.started') return 'running';
  if (eventType === 'tool.approval_required' || eventType === 'agent.tool.approval_required') return 'waiting_approval';
  if (eventType === 'agent.tool.approval_approved' || eventType === 'tool.approved' || eventType === 'tool.approval_approved') return 'approved';
  if (eventType === 'agent.tool.approval_rejected' || eventType === 'agent.tool.denied' || eventType === 'tool.rejected' || eventType === 'tool.denied' || eventType === 'tool.approval_rejected') return 'denied';
  if (eventType === 'agent.tool.approval_timeout' || eventType === 'approval.timeout' || eventType === 'tool.approval_timeout') return 'expired';
  if (eventType === 'tool.failed' || eventType === 'agent.tool.failed') return 'failed';
  if (eventType === 'agent.tool.skipped' || eventType === 'tool.skipped') return 'skipped';
  if (eventType === 'tool.cancelled') return 'cancelled';
  return 'completed';
}

function toolCallStatusIsTerminal(status: string): boolean {
  return ['completed', 'failed', 'denied', 'skipped', 'expired', 'cancelled'].includes(status);
}

function toolCallCorrelationKey(event: PublicRunEvent, toolCall: ToolCallSnapshot): string {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const explicitId = publicRunEventPayloadString(payload, 'tool_call_id')
    || publicRunEventPayloadString(payload, 'id');
  if (explicitId) return `${event.run_id}:id:${explicitId}`;
  return [
    event.run_id,
    'tool',
    toolCall.tool_name,
    stableJson(toolCallCorrelationPreview(toolCall.input_preview || {})),
  ].join(':');
}

function toolCallCorrelationPreview(preview: Record<string, unknown>): Record<string, unknown> {
  const traceKeys = new Set([
    'approval_id',
    'group_id',
    'group_run_id',
    'member_agent_id',
    'member_agent_name',
    'policy_reason',
    'risk_level',
    'run_group_id',
    'workflow_id',
    'workflow_node_id',
    'workflow_node_label',
    'workflow_run_id',
  ]);
  return Object.fromEntries(
    Object.entries(preview).filter(([key]) => !traceKeys.has(key)),
  );
}

function stableJson(value: unknown): string {
  try {
    return JSON.stringify(stableJsonValue(value));
  } catch {
    return String(value);
  }
}

function stableJsonValue(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(stableJsonValue);
  if (!value || typeof value !== 'object') return value;
  return Object.fromEntries(
    Object.entries(value as Record<string, unknown>)
      .sort(([left], [right]) => left.localeCompare(right))
      .map(([key, item]) => [key, stableJsonValue(item)]),
  );
}

function artifactRecordKey(artifact: Record<string, unknown>, index: number): string {
  return publicRunEventPayloadString(artifact, 'artifact_id')
    || [
      publicRunEventPayloadString(artifact, 'source_run_id') || publicRunEventPayloadString(artifact, 'run_id'),
      publicRunEventPayloadString(artifact, 'path') || publicRunEventPayloadString(artifact, 'artifact_path'),
      publicRunEventPayloadString(artifact, 'title'),
      publicRunEventPayloadString(artifact, 'kind'),
    ].filter(Boolean).join(':')
    || `artifact:${index}`;
}

function approvalRecordKey(approval: ApprovalCardSnapshot, index: number): string {
  return approval.approval_id
    || [approval.run_id || '', approval.tool_name || '', approval.title || ''].filter(Boolean).join(':')
    || `approval:${index}`;
}

function approvalReplayCorrelationKeys(approval: ApprovalCardSnapshot): ApprovalReplayCorrelationKeys {
  const preview = approvalReplayCorrelationPreview(approval.input_preview || {});
  const baseParts = [
    approval.run_id || '',
    'approval',
    approval.tool_name || '',
    approval.workflow_node_id || '',
    approval.group_run_id || '',
    approval.source_runnable_id || '',
  ];
  const strongKeys = [
    [...baseParts, stableJson(preview)].join(':'),
    approval.approval_id ? `${approval.run_id || ''}:approval_id:${approval.approval_id}` : '',
  ].filter(Boolean);
  const weakKey = baseParts.slice(2).some(Boolean) ? baseParts.join(':') : '';
  return { strongKeys: Array.from(new Set(strongKeys)), weakKey };
}

function approvalReplayActiveIndex(
  keys: ApprovalReplayCorrelationKeys,
  activeByStrongKey: Map<string, number>,
  activeByWeakKey: Map<string, ApprovalReplayWeakIndex>,
  allowWeak: boolean,
): number | undefined {
  for (const key of keys.strongKeys) {
    const index = activeByStrongKey.get(key);
    if (index !== undefined) return index;
  }
  if (!allowWeak) return undefined;
  const weakIndex = keys.weakKey ? activeByWeakKey.get(keys.weakKey) : undefined;
  return typeof weakIndex === 'number' ? weakIndex : undefined;
}

function registerActiveApprovalReplay(
  index: number,
  keys: ApprovalReplayCorrelationKeys,
  activeByStrongKey: Map<string, number>,
  activeByWeakKey: Map<string, ApprovalReplayWeakIndex>,
  activeKeysByIndex: Map<number, ApprovalReplayCorrelationKeys>,
) {
  keys.strongKeys.forEach((key) => activeByStrongKey.set(key, index));
  if (keys.weakKey) {
    const existing = activeByWeakKey.get(keys.weakKey);
    if (existing === undefined) {
      activeByWeakKey.set(keys.weakKey, index);
    } else if (existing !== index) {
      activeByWeakKey.set(keys.weakKey, 'ambiguous');
    }
  }
  activeKeysByIndex.set(index, keys);
}

function unregisterActiveApprovalReplay(
  index: number,
  activeByStrongKey: Map<string, number>,
  activeByWeakKey: Map<string, ApprovalReplayWeakIndex>,
  activeKeysByIndex: Map<number, ApprovalReplayCorrelationKeys>,
) {
  const keys = activeKeysByIndex.get(index);
  if (!keys) return;
  keys.strongKeys.forEach((key) => {
    if (activeByStrongKey.get(key) === index) activeByStrongKey.delete(key);
  });
  if (keys.weakKey && activeByWeakKey.get(keys.weakKey) === index) {
    activeByWeakKey.delete(keys.weakKey);
  }
  activeKeysByIndex.delete(index);
}

function approvalReplayCorrelationPreview(preview: Record<string, unknown>): Record<string, unknown> {
  const traceKeys = new Set([
    'approval_id',
    'group_id',
    'group_run_id',
    'member_agent_id',
    'member_agent_name',
    'policy_reason',
    'risk_level',
    'run_group_id',
    'workflow_id',
    'workflow_node_id',
    'workflow_node_label',
    'workflow_run_id',
  ]);
  return Object.fromEntries(
    Object.entries(preview).filter(([key]) => !traceKeys.has(key)),
  );
}

function objectPreview(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function publicRunEventPayloadString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === 'string' ? value.trim() : '';
}
