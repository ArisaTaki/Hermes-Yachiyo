import type { ApprovalCardSnapshot, PublicRunEvent } from './types';

export function artifactsFromRunEventReplay(events: PublicRunEvent[]): Array<Record<string, unknown>> {
  return events
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
  return events
    .map(approvalFromRunEvent)
    .filter((approval): approval is ApprovalCardSnapshot => Boolean(approval));
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

function artifactFromRunEvent(event: PublicRunEvent): Record<string, unknown> | null {
  if (!isArtifactRunEvent(event.event_type)) return null;
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  let artifactPayload: Record<string, unknown> | null = null;
  if (event.event_type === 'artifact.created' || event.event_type === 'agent.artifact.write') {
    artifactPayload = { ...payload };
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
  if (eventType === 'approval.timeout') return 'expired';
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

function objectPreview(value: unknown): Record<string, unknown> | null {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : null;
}

function publicRunEventPayloadString(payload: Record<string, unknown>, key: string): string {
  const value = payload[key];
  return typeof value === 'string' ? value.trim() : '';
}
