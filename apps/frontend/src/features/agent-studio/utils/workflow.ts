import type { Edge, Node } from '@xyflow/react';

import type { AgentSpec, RunSpec, WorkflowSpec } from '../types';
import type { WorkflowSnapshot } from '../../yachiyo-studio/types';
import {
  timelineChildRunId,
  timelineEventPayload,
  timelineStatus,
} from './runTimeline';

export type WorkflowChildRunRef = {
  childRunId: string;
  label: string;
  status: string;
};

export type WorkflowStepRef = {
  key: string;
  kind: 'start' | 'agent' | 'approval' | 'artifact' | 'condition' | 'parallel' | 'workflow' | 'loop' | 'unknown';
  nodeId?: string;
  label: string;
  status: string;
  childRunId?: string;
  payload?: string;
  artifactPath?: string;
  artifactCount?: number;
  task?: string;
  selectedBranch?: string;
  selectedTargetNodeId?: string;
};

export type WorkflowValidationReport = {
  errors: string[];
  warnings: string[];
};

const workflowNodeTypes = new Set(['start', 'agent', 'approval', 'artifact', 'condition', 'parallel', 'workflow', 'loop']);
const workflowRunnableNodeTypes = new Set(['agent', 'approval', 'artifact', 'condition', 'parallel', 'workflow', 'loop']);

export const workflowRunnableStepRequiredMessage = 'Workflow 至少需要一个可执行节点（Agent、Approval、Artifact、Condition、Parallel、Workflow 或 Loop）';

export function publicWorkflowToWorkflowSpec(snapshot: WorkflowSnapshot): WorkflowSpec {
  return {
    workflow_id: snapshot.workflow_id,
    name: snapshot.name,
    description: snapshot.description || undefined,
    nodes: (snapshot.nodes || []) as WorkflowSpec['nodes'],
    edges: (snapshot.edges || []) as WorkflowSpec['edges'],
    default_input_schema: snapshot.default_input_schema,
    enabled: snapshot.enabled,
    created_at: snapshot.created_at,
    updated_at: snapshot.updated_at,
  };
}

function workflowStepKind(value: unknown): WorkflowStepRef['kind'] {
  const kind = String(value || '').trim();
  if (kind === 'start' || kind === 'agent' || kind === 'approval' || kind === 'artifact' || kind === 'condition' || kind === 'parallel' || kind === 'workflow' || kind === 'loop') return kind;
  return 'unknown';
}

export const starterNodes: Node[] = [
  { id: 'start', type: 'input', position: { x: 40, y: 120 }, data: { label: 'Start', kind: 'start' } },
];

const phase4WorkflowAgentOrder = [
  {
    id: 'agent_yachiyo_orchestrator',
    category: 'orchestrator',
    nodeId: 'orchestrator',
    fallbackLabel: 'Yachiyo Orchestrator',
    task: '拆解全局目标，明确后续 Agent 的交付边界、依赖关系、风险和验收口径。',
  },
  {
    id: 'agent_research',
    category: 'research',
    nodeId: 'research',
    fallbackLabel: 'Research Agent',
    task: '基于全局目标整理事实、约束、参考信息和不确定点，为设计与实现提供依据。',
  },
  {
    id: 'agent_design',
    category: 'design',
    nodeId: 'design',
    fallbackLabel: 'Design Agent',
    task: '基于研究结果提出信息架构、交互结构、视觉方向和需要交付的设计要点。',
  },
  {
    id: 'agent_coding',
    category: 'coding',
    nodeId: 'coding',
    fallbackLabel: 'Coding Agent',
    task: '根据上游设计与约束给出实现方案、必要代码或变更计划，并说明验证方式。',
  },
  {
    id: 'agent_review',
    category: 'review',
    nodeId: 'review',
    fallbackLabel: 'Review Agent',
    task: '审查上游实现或方案，列出问题优先级、风险、缺失测试和可验收结论。',
  },
  {
    id: 'agent_office',
    category: 'office',
    nodeId: 'office',
    fallbackLabel: 'Office Agent',
    task: '把整条流程的目标、关键决策、产物、风险和后续待办整理成最终汇报。',
  },
];

export function workflowNodes(workflow: WorkflowSpec | null): Node[] {
  if (!workflow) return starterNodes;
  return workflow.nodes.map((node) => {
    const rawData = node.data || {};
    const kind = String(rawData.kind || rawData.node_type || node.type || 'agent');
    return {
      id: node.id,
      type: kind === 'start' ? 'input' : kind === 'artifact' ? 'output' : 'default',
      position: node.position || { x: 0, y: 0 },
      data: { label: node.id, ...rawData, kind },
    };
  });
}

export function workflowEdges(workflow: WorkflowSpec | null): Edge[] {
  if (!workflow) return [];
  return workflow.edges.map((edge, index) => ({
    id: edge.id || `edge-${index}`,
    source: edge.source,
    target: edge.target,
    sourceHandle: edge.sourceHandle || undefined,
    data: edge.data,
    label: edge.label,
  }));
}

export function workflowNodeKind(node: Node): string {
  const dataKind = String(node.data?.kind || node.data?.node_type || '').trim();
  const nodeType = String(node.type || '').trim();
  if (dataKind && ['', 'input', 'default', 'output'].includes(nodeType)) return dataKind;
  return nodeType || dataKind;
}

function workflowNodeKindLabel(kind: string): string {
  if (kind === 'agent') return 'Agent';
  if (kind === 'approval') return 'Approval';
  if (kind === 'artifact') return 'Artifact';
  if (kind === 'condition') return 'Condition';
  if (kind === 'parallel') return 'Parallel';
  if (kind === 'workflow') return 'Workflow';
  if (kind === 'loop') return 'Loop';
  if (kind === 'start') return 'Start';
  return kind || 'Node';
}

function workflowConditionText(data: Record<string, unknown> | undefined): string {
  if (!data) return '';
  for (const key of ['condition', 'contains', 'match', 'criteria', 'expression', 'if', 'prompt']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function workflowChildWorkflowIdFromData(data: Record<string, unknown> | undefined): string {
  if (!data) return '';
  for (const key of ['workflow_id', 'workflowId', 'child_workflow_id', 'childWorkflowId', 'runnable_id', 'runnableId']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function workflowEdgeBranch(edge: Edge): 'true' | 'false' | '' {
  const edgeWithMeta = edge as Edge & {
    branch?: unknown;
    condition?: unknown;
    label?: unknown;
  };
  const data = edge.data && typeof edge.data === 'object' ? edge.data as Record<string, unknown> : {};
  const raw = (
    edgeWithMeta.branch
    || edgeWithMeta.condition
    || edgeWithMeta.label
    || edge.sourceHandle
    || data.branch
    || data.condition
    || data.label
    || data.sourceHandle
    || ''
  );
  const value = String(raw || '').trim().toLowerCase();
  if (['true', 'yes', 'y', 'pass', 'passed', 'match', 'matched', 'ok', 'success'].includes(value)) return 'true';
  if (['false', 'no', 'n', 'fail', 'failed', 'miss', 'unmatched', 'else', 'fallback'].includes(value)) return 'false';
  return '';
}

function workflowLoopEdgeRole(edge: Edge): 'continue' | 'exit' | '' {
  const edgeWithMeta = edge as Edge & {
    branch?: unknown;
    condition?: unknown;
    label?: unknown;
  };
  const data = edge.data && typeof edge.data === 'object' ? edge.data as Record<string, unknown> : {};
  const raw = (
    edgeWithMeta.branch
    || edgeWithMeta.condition
    || edgeWithMeta.label
    || edge.sourceHandle
    || data.branch
    || data.condition
    || data.label
    || data.sourceHandle
    || ''
  );
  const value = String(raw || '').trim().toLowerCase();
  if (['true', 'yes', 'y', 'pass', 'passed', 'match', 'matched', 'ok', 'success', 'continue', 'loop', 'repeat', 'again', 'next'].includes(value)) return 'continue';
  if (['false', 'no', 'n', 'fail', 'failed', 'miss', 'unmatched', 'else', 'fallback', 'exit', 'done', 'break', 'stop', 'finish'].includes(value)) return 'exit';
  return '';
}

function workflowLoopMaxIterations(data: Record<string, unknown> | undefined): number {
  if (!data) return 3;
  const raw = data.max_iterations || data.maxIterations || data.iteration_limit || data.iterationLimit || data.limit || 3;
  const value = Number(raw);
  if (!Number.isFinite(value)) return 3;
  return Math.max(1, Math.min(Math.round(value), 25));
}

function isSafeWorkflowArtifactPath(value: string): boolean {
  const path = value.replace(/\\/g, '/').trim();
  return Boolean(path) && !path.startsWith('/') && !path.startsWith('../') && !path.includes('/../');
}

function workflowArtifactBasePath(label: string, configuredPath: string): string {
  const configured = configuredPath.replace(/\\/g, '/').trim();
  if (configured) {
    const filename = configured.slice(configured.lastIndexOf('/') + 1);
    return filename.includes('.') ? configured : `${configured}.md`;
  }
  const slug = label
    .toLowerCase()
    .replace(/[^a-z0-9\u4e00-\u9fa5]+/g, '-')
    .replace(/^-+|-+$/g, '') || 'artifact';
  return `${slug}.md`;
}

function uniqueWorkflowArtifactPath(basePath: string, existingPaths: Set<string>): string {
  const slashIndex = basePath.lastIndexOf('/');
  const directory = slashIndex >= 0 ? `${basePath.slice(0, slashIndex + 1)}` : '';
  const filename = slashIndex >= 0 ? basePath.slice(slashIndex + 1) : basePath;
  const dotIndex = filename.lastIndexOf('.');
  const stem = dotIndex > 0 ? filename.slice(0, dotIndex) : filename;
  const suffix = dotIndex > 0 ? filename.slice(dotIndex) : '.md';
  let candidate = `${directory}${stem}${suffix}`;
  let index = 2;
  while (existingPaths.has(candidate)) {
    candidate = `${directory}${stem}-${index}${suffix}`;
    index += 1;
  }
  existingPaths.add(candidate);
  return candidate;
}

export function validateWorkflowDraft(
  nodes: Node[],
  edges: Edge[],
  agents: AgentSpec[],
  workflows: WorkflowSpec[] = [],
  currentWorkflowId = '',
): WorkflowValidationReport {
  const errors: string[] = [];
  const warnings: string[] = [];
  if (!nodes.length) {
    return { errors: ['Workflow 至少需要一个 Start 节点'], warnings };
  }

  const nodeIds = nodes.map((node) => String(node.id || '').trim());
  const nodeIdSet = new Set(nodeIds);
  if (nodeIds.some((id) => !id) || nodeIdSet.size !== nodeIds.length) {
    errors.push('Workflow 节点 ID 必须唯一');
  }

  const startNodes = nodes.filter((node) => workflowNodeKind(node) === 'start');
  if (startNodes.length !== 1) {
    errors.push('Workflow 必须且只能有一个 Start 节点');
  }

  const agentById = new Map(agents.map((agent) => [agent.agent_id, agent]));
  const workflowById = new Map(workflows.map((workflow) => [workflow.workflow_id, workflow]));
  nodes.forEach((node) => {
    const kind = workflowNodeKind(node);
    const label = String(node.data?.label || node.id || workflowNodeKindLabel(kind)).trim();
    if (!workflowNodeTypes.has(kind)) {
      errors.push(`${label || '节点'} 使用了未知 Workflow 节点类型：${kind || '空'}`);
    }
    if (!label) warnings.push(`${node.id || '节点'} 缺少 Label`);
    if (kind === 'agent') {
      const agentId = String(node.data?.agent_id || '').trim();
      const agent = agentById.get(agentId);
      if (!agentId) errors.push(`${label} 没有选择 Agent`);
      else if (!agent) errors.push(`${label} 引用了不存在的 Agent`);
      else if (agent.enabled === false) errors.push(`${label} 选择的 Agent 已停用`);
    }
    if (kind === 'artifact') {
      const artifactPath = String(node.data?.artifact_path || node.data?.artifactPath || '').trim();
      if (artifactPath && !isSafeWorkflowArtifactPath(artifactPath)) {
        errors.push(`${label} 的产物路径必须是相对路径，且不能越界`);
      }
    }
    if (kind === 'condition' && !workflowConditionText(node.data as Record<string, unknown> | undefined)) {
      errors.push(`${label} 缺少条件文本`);
    }
    if (kind === 'loop' && !workflowConditionText(node.data as Record<string, unknown> | undefined)) {
      errors.push(`${label} 缺少循环条件文本`);
    }
    if (kind === 'workflow') {
      const workflowId = workflowChildWorkflowIdFromData(node.data as Record<string, unknown> | undefined);
      const workflow = workflowById.get(workflowId);
      if (!workflowId) errors.push(`${label} 没有选择子 Workflow`);
      else if (currentWorkflowId && workflowId === currentWorkflowId) errors.push(`${label} 不能引用当前 Workflow`);
      else if (!workflow) errors.push(`${label} 引用了不存在的子 Workflow`);
      else if (workflow.enabled === false) errors.push(`${label} 选择的子 Workflow 已停用`);
    }
  });

  const outgoing = new Map<string, string[]>();
  const incoming = new Map<string, string[]>();
  nodeIds.forEach((id) => {
    outgoing.set(id, []);
    incoming.set(id, []);
  });
  edges.forEach((edge) => {
    const source = String(edge.source || '').trim();
    const target = String(edge.target || '').trim();
    if (!nodeIdSet.has(source) || !nodeIdSet.has(target)) {
      errors.push('Workflow edge 引用了不存在的节点');
      return;
    }
    outgoing.get(source)?.push(target);
    incoming.get(target)?.push(source);
  });

  const startId = startNodes.length === 1 ? String(startNodes[0].id || '').trim() : '';
  if (startId && (incoming.get(startId) || []).length > 0) {
    errors.push('Start 节点不能有入边');
  }
  nodeIds.forEach((nodeId) => {
    const targets = outgoing.get(nodeId) || [];
    const sources = incoming.get(nodeId) || [];
    const node = nodes.find((item) => item.id === nodeId);
    const label = String(node?.data?.label || nodeId || '节点');
    const kind = node ? workflowNodeKind(node) : '';
    if (kind === 'condition') {
      if (targets.length !== 2) errors.push(`${label} 必须有 true/false 两个下一步`);
      const branchRoles = edges
        .filter((edge) => String(edge.source || '').trim() === nodeId)
        .map(workflowEdgeBranch)
        .filter(Boolean);
      const uniqueBranches = new Set(branchRoles);
      if (branchRoles.length && (uniqueBranches.size !== branchRoles.length || uniqueBranches.size !== 2)) {
        errors.push(`${label} 的分支标注必须是一条 true 和一条 false`);
      }
    } else if (kind === 'parallel') {
      if (targets.length < 2) errors.push(`${label} 至少需要两个并行分支`);
    } else if (kind === 'loop') {
      if (targets.length !== 2) errors.push(`${label} 必须有 continue/exit 两个下一步`);
      const branchRoles = edges
        .filter((edge) => String(edge.source || '').trim() === nodeId)
        .map(workflowLoopEdgeRole)
        .filter(Boolean);
      const uniqueBranches = new Set(branchRoles);
      if (branchRoles.length && (uniqueBranches.size !== branchRoles.length || uniqueBranches.size !== 2)) {
        errors.push(`${label} 的分支标注必须是一条 continue 和一条 exit`);
      }
    } else if (targets.length > 1) {
      errors.push(`${label} 有多个下一步，只有 Condition、Parallel 或 Loop 节点支持分支`);
    }
    if (nodeId !== startId && sources.length < 1) errors.push(`${label} 必须至少有一个上一节点`);
  });

  if (startId && !errors.some((item) => item.includes('edge 引用'))) {
    const seen = new Set<string>();
    const active = new Set<string>();
    const nodeById = new Map(nodes.map((node) => [String(node.id || ''), node]));
    const visit = (nodeId: string, incomingEdge?: Edge) => {
      if (active.has(nodeId)) {
        const sourceNode = incomingEdge ? nodeById.get(String(incomingEdge.source || '')) : undefined;
        if (incomingEdge && sourceNode && workflowNodeKind(sourceNode) === 'loop' && workflowLoopEdgeRole(incomingEdge) === 'continue') {
          return;
        }
        errors.push('Workflow 不能包含非 Loop 控制的环');
        return;
      }
      if (seen.has(nodeId)) return;
      active.add(nodeId);
      edges
        .filter((edge) => String(edge.source || '').trim() === nodeId)
        .forEach((edge) => visit(String(edge.target || '').trim(), edge));
      active.delete(nodeId);
      seen.add(nodeId);
    };
    visit(startId);
    if (seen.size !== nodeIdSet.size) {
      errors.push('Workflow 必须从 Start 触达所有节点');
    }
  }

  if (!workflowHasRunnableSteps(nodes)) {
    warnings.push('当前没有可执行节点；可以保存草稿，但运行前需要添加 Agent、Approval、Artifact、Condition、Parallel、Workflow 或 Loop。');
  }

  return {
    errors: Array.from(new Set(errors)),
    warnings: Array.from(new Set(warnings)),
  };
}

export function workflowHasRunnableSteps(nodes: Node[]): boolean {
  return nodes.some((node) => workflowRunnableNodeTypes.has(workflowNodeKind(node)));
}

export function workflowRequestNodes(nodes: Node[]): WorkflowSpec['nodes'] {
  return nodes.map((node) => ({
    id: node.id,
    type: String(node.data?.kind || (node.type === 'input' ? 'start' : node.type === 'output' ? 'artifact' : 'agent')),
    position: node.position,
    data: node.data as Record<string, unknown>,
  }));
}

export function workflowRequestEdges(edges: Edge[]): WorkflowSpec['edges'] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    ...(edge.sourceHandle ? { sourceHandle: edge.sourceHandle } : {}),
    ...(edge.data && typeof edge.data === 'object' ? { data: edge.data as Record<string, unknown> } : {}),
  }));
}

export function linearEdgesForNodes(nextNodes: Node[]): Edge[] {
  return nextNodes.slice(0, -1).map((node, index) => {
    const target = nextNodes[index + 1];
    return {
      id: `edge-${node.id}-${target.id}`,
      source: node.id,
      target: target.id,
    };
  });
}

export function terminalNodeId(currentNodes: Node[], currentEdges: Edge[]): string {
  const nodesWithOutgoing = new Set(currentEdges.map((edge) => edge.source).filter(Boolean));
  const terminal = [...currentNodes].reverse().find((node) => !nodesWithOutgoing.has(node.id));
  return terminal?.id || currentNodes[currentNodes.length - 1]?.id || '';
}

export function uniqueWorkflowNodeId(seed: string, currentNodes: Node[]): string {
  const existing = new Set(currentNodes.map((node) => node.id));
  const cleanSeed = seed.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'node';
  if (!existing.has(cleanSeed)) return cleanSeed;
  let index = 2;
  while (existing.has(`${cleanSeed}-${index}`)) index += 1;
  return `${cleanSeed}-${index}`;
}

export function buildPhase4WorkflowNodes(agents: AgentSpec[]): Node[] {
  const agentNodes: Node[] = [];
  const enabledAgents = agents.filter((agent) => agent.enabled !== false);
  phase4WorkflowAgentOrder.forEach((item) => {
    const agent = enabledAgents.find((candidate) => candidate.agent_id === item.id)
      || enabledAgents.find((candidate) => candidate.category === item.category);
    if (!agent) return;
    agentNodes.push({
      id: item.nodeId,
      type: 'default',
      position: { x: 260 + agentNodes.length * 220, y: 120 },
      data: {
        label: agent.name || item.fallbackLabel,
        kind: 'agent',
        agent_id: agent.agent_id,
        task: item.task,
      },
    });
  });
  return [
    { id: 'start', type: 'input', position: { x: 40, y: 120 }, data: { label: 'Start', kind: 'start' } },
    ...agentNodes,
    {
      id: 'artifact',
      type: 'output',
      position: { x: 260 + agentNodes.length * 220, y: 120 },
      data: { label: 'Flow Summary', kind: 'artifact', artifact_path: 'reports/phase-4-flow-summary.md' },
    },
  ];
}

export function workflowAgentRunReadinessIssue(nodes: Node[], issueByAgentId: Map<string, string>): string {
  for (const node of nodes) {
    if (workflowNodeKind(node) !== 'agent') continue;
    const agentId = String(node.data?.agent_id || '').trim();
    if (!agentId) continue;
    const issue = issueByAgentId.get(agentId);
    if (!issue) continue;
    const label = String(node.data?.label || node.id || 'Agent').trim() || 'Agent';
    return `${label}: ${issue}`;
  }
  return '';
}

export function workflowRunHasChildRun(workflowRun: RunSpec, childRunId: string): boolean {
  if (!childRunId || workflowRun.kind !== 'workflow_run') return false;
  return workflowChildRunRefs(workflowRun).some((ref) => ref.childRunId === childRunId);
}

function workflowStepDetailText(value: unknown): string {
  return String(value || '').trim();
}

function workflowApprovalPayloadSummary(event: Record<string, unknown>): string {
  const pendingApproval = event.pending_approval;
  if (!pendingApproval || typeof pendingApproval !== 'object') return timelineEventPayload(event);
  const raw = pendingApproval as Record<string, unknown>;
  const preview = raw.input_preview;
  if (!preview || typeof preview !== 'object') return timelineEventPayload(event);
  const input = preview as Record<string, unknown>;
  const lines: string[] = [];
  const checkpoint = workflowStepDetailText(input.checkpoint);
  const criteria = workflowStepDetailText(input.criteria || input.approval_criteria || input.instructions);
  const context = workflowStepDetailText(input.context);
  if (checkpoint) lines.push(`审批节点：${checkpoint}`);
  if (criteria) lines.push(`审批说明：${criteria}`);
  if (context) lines.push(`当前上下文：${context}`);
  return lines.join('\n') || timelineEventPayload(event);
}

function workflowNodeId(event: Record<string, unknown>): string {
  const value = event.workflow_node_id;
  return typeof value === 'string' ? value.trim() : '';
}

function workflowArtifactPath(event: Record<string, unknown>): string {
  const artifact = event.artifact;
  if (!artifact || typeof artifact !== 'object') return '';
  const path = (artifact as Record<string, unknown>).path;
  return typeof path === 'string' ? path.trim() : '';
}

function workflowEventNodeKind(event: Record<string, unknown>): WorkflowStepRef['kind'] {
  return workflowStepKind(event.workflow_node_kind);
}

function workflowSpecNodeKind(node: WorkflowSpec['nodes'][number]): WorkflowStepRef['kind'] {
  const data = node.data || {};
  const dataKind = String(data.kind || data.node_type || '').trim();
  const nodeType = String(node.type || '').trim();
  const value = dataKind && ['', 'input', 'default', 'output'].includes(nodeType)
    ? dataKind
    : nodeType || dataKind;
  return workflowStepKind(value);
}

function workflowNodeTaskFromData(data: Record<string, unknown> | undefined): string {
  if (!data) return '';
  for (const key of ['task', 'instructions', 'step_task', 'prompt']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

function workflowApprovalCriteriaFromData(data: Record<string, unknown> | undefined): string {
  if (!data) return '';
  for (const key of ['criteria', 'approval_criteria', 'instructions', 'task', 'prompt']) {
    const value = data[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
  }
  return '';
}

export function workflowSpecStepRefs(workflow: WorkflowSpec | null): WorkflowStepRef[] {
  if (!workflow) return [];
  const nodesById = new Map(workflow.nodes.map((node) => [String(node.id || ''), node]));
  const outgoing = new Map<string, WorkflowSpec['edges']>();
  workflow.edges.forEach((edge) => {
    const source = String(edge.source || '');
    const target = String(edge.target || '');
    if (!source || !target) return;
    const next = outgoing.get(source) || [];
    next.push(edge);
    next.sort((left, right) => {
      const leftBranch = workflowEdgeBranch(left as Edge);
      const rightBranch = workflowEdgeBranch(right as Edge);
      const branchOrder = (branch: string) => branch === 'true' ? 0 : branch === 'false' ? 1 : 2;
      return branchOrder(leftBranch) - branchOrder(rightBranch);
    });
    outgoing.set(source, next);
  });
  const start = workflow.nodes.find((node) => workflowSpecNodeKind(node) === 'start') || workflow.nodes[0];
  if (!start) return [];
  const ordered: WorkflowSpec['nodes'] = [];
  const seen = new Set<string>();
  const visit = (current: WorkflowSpec['nodes'][number] | undefined) => {
    if (!current) return;
    const nodeId = String(current.id || '');
    if (!nodeId || seen.has(nodeId)) return;
    ordered.push(current);
    seen.add(nodeId);
    (outgoing.get(nodeId) || []).forEach((edge) => {
      visit(nodesById.get(String(edge.target || '')));
    });
  };
  visit(start);
  const existingArtifactPaths = new Set<string>();
  return ordered.map((node, index) => {
    const kind = workflowSpecNodeKind(node);
    const nodeId = String(node.id || '');
    const label = String(node.data?.label || nodeId || workflowStepKindLabel(kind)).trim();
    const artifactPath = kind === 'artifact'
      ? uniqueWorkflowArtifactPath(
        workflowArtifactBasePath(label, String(node.data?.artifact_path || node.data?.artifactPath || '')),
        existingArtifactPaths,
      )
      : '';
    const task = kind === 'agent'
      ? workflowNodeTaskFromData(node.data)
      : kind === 'approval'
        ? workflowApprovalCriteriaFromData(node.data)
        : kind === 'condition'
          ? workflowConditionText(node.data)
          : kind === 'workflow'
            ? workflowNodeTaskFromData(node.data)
            : kind === 'loop'
              ? workflowConditionText(node.data)
          : '';
    return {
      key: `${kind}:${nodeId || label || index}`,
      kind,
      nodeId,
      label,
      status: 'pending',
      artifactPath,
      task,
    };
  });
}

function workflowSnapshotStepRefs(run: RunSpec | null): WorkflowStepRef[] {
  if (!run || run.kind !== 'workflow_run') return [];
  const startEvent = (run.timeline || []).find((event) => String(event.event || '') === 'workflow.run.started');
  const snapshot = startEvent?.workflow_path;
  if (!Array.isArray(snapshot)) return [];
  return snapshot
    .map((item, index) => {
      if (!item || typeof item !== 'object') return null;
      const row = item as Record<string, unknown>;
      const kind = workflowStepKind(row.kind);
      const nodeId = String(row.id || '');
      const label = String(row.label || nodeId || workflowStepKindLabel(kind)).trim();
      const artifactPath = kind === 'artifact' ? String(row.artifact_path || row.artifactPath || '').trim() : '';
      const task = kind === 'agent'
        ? String(row.task || row.step_task || '').trim()
        : kind === 'approval'
          ? String(row.criteria || row.approval_criteria || row.instructions || '').trim()
          : kind === 'condition'
            ? String(row.condition || row.criteria || row.expression || '').trim()
            : kind === 'workflow'
              ? String(row.task || row.step_task || '').trim()
              : kind === 'loop'
                ? String(row.condition || row.criteria || row.expression || '').trim()
            : '';
      return {
        key: `${kind}:${nodeId || label || index}`,
        kind,
        nodeId,
        label,
        status: 'pending',
        artifactPath,
        task,
      } as WorkflowStepRef;
    })
    .filter((item): item is WorkflowStepRef => Boolean(item));
}

function normalizeWorkflowStepLabel(value: string): string {
  return value.replace(/\s+/g, ' ').trim().toLowerCase();
}

function workflowSpecAlignsWithObservedSteps(specSteps: WorkflowStepRef[], observedSteps: WorkflowStepRef[]): boolean {
  if (!specSteps.length) return false;
  if (!observedSteps.length) return true;
  let nextSearchIndex = 0;
  for (const observed of observedSteps) {
    const matchedIndex = specSteps.findIndex((candidate, index) => {
      if (index < nextSearchIndex) return false;
      if (candidate.kind !== observed.kind) return false;
      if (observed.nodeId) return candidate.nodeId === observed.nodeId;
      return normalizeWorkflowStepLabel(candidate.label) === normalizeWorkflowStepLabel(observed.label);
    });
    if (matchedIndex < 0) return false;
    nextSearchIndex = matchedIndex + 1;
  }
  return true;
}

function workflowStepRefMatches(candidate: WorkflowStepRef, observed: WorkflowStepRef): boolean {
  if (candidate.key === observed.key) return true;
  if (candidate.kind !== observed.kind) return false;
  if (candidate.nodeId && observed.nodeId) return candidate.nodeId === observed.nodeId;
  if (candidate.childRunId && observed.childRunId) return candidate.childRunId === observed.childRunId;
  if (candidate.artifactPath && observed.artifactPath) return candidate.artifactPath === observed.artifactPath;
  return normalizeWorkflowStepLabel(candidate.label) === normalizeWorkflowStepLabel(observed.label);
}

function mergeWorkflowStepRefs(specSteps: WorkflowStepRef[], observedSteps: WorkflowStepRef[]): WorkflowStepRef[] {
  const usedObservedIndexes = new Set<number>();
  const merged = specSteps.map((specStep) => {
    const observedIndex = observedSteps.findIndex((observed, index) => (
      !usedObservedIndexes.has(index) && workflowStepRefMatches(specStep, observed)
    ));
    if (observedIndex < 0) return specStep;
    usedObservedIndexes.add(observedIndex);
    const observed = observedSteps[observedIndex];
    return {
      ...specStep,
      ...observed,
      key: specStep.key,
      nodeId: specStep.nodeId || observed.nodeId,
      label: observed.label || specStep.label,
      childRunId: observed.childRunId || specStep.childRunId,
      artifactPath: observed.artifactPath || specStep.artifactPath,
      artifactCount: observed.artifactCount ?? specStep.artifactCount,
      payload: observed.payload || specStep.payload,
      task: observed.task || specStep.task,
    };
  });
  return merged.concat(observedSteps.filter((_step, index) => !usedObservedIndexes.has(index)));
}

function normalizeWorkflowApprovalLabel(name: string, detail: string): string {
  const clean = detail.trim();
  if (name === 'workflow.node.approval_approved') {
    return clean.replace(/\s+approved$/i, '').trim() || 'Approval';
  }
  if (name === 'workflow.node.approval_rejected') {
    return clean.replace(/\s+approval rejected$/i, '').trim() || 'Approval';
  }
  return clean || 'Approval';
}

function upsertWorkflowStep(steps: WorkflowStepRef[], indexByKey: Map<string, number>, next: WorkflowStepRef) {
  const existingIndex = indexByKey.get(next.key);
  if (existingIndex === undefined) {
    indexByKey.set(next.key, steps.length);
    steps.push(next);
    return;
  }
  const previous = steps[existingIndex];
  steps[existingIndex] = {
    ...previous,
    ...next,
    label: previous.label || next.label,
    childRunId: previous.childRunId || next.childRunId,
    artifactPath: next.artifactPath || previous.artifactPath,
    artifactCount: next.artifactCount ?? previous.artifactCount,
    payload: next.payload || previous.payload,
    task: next.task || previous.task,
  };
}

export function workflowStepRefs(run: RunSpec | null, workflow: WorkflowSpec | null = null): WorkflowStepRef[] {
  if (!run || run.kind !== 'workflow_run') return [];
  const steps: WorkflowStepRef[] = [];
  const indexByKey = new Map<string, number>();
  (run.timeline || []).forEach((event, index) => {
    const name = String(event.event || '');
    const detail = String(event.detail || '').trim();
    const nodeId = workflowNodeId(event);
    if (name === 'workflow.node.start') {
      upsertWorkflowStep(steps, indexByKey, {
        key: `start:${nodeId || detail || index}`,
        kind: 'start',
        nodeId,
        label: detail || 'Start',
        status: timelineStatus(event) || 'completed',
      });
      return;
    }
    if (name === 'workflow.node.agent') {
      const childRunId = timelineChildRunId(event);
      const task = String(event.workflow_node_task || event.step_task || '').trim();
      upsertWorkflowStep(steps, indexByKey, {
        key: `agent:${nodeId || childRunId || detail || index}`,
        kind: 'agent',
        nodeId,
        label: detail || 'Agent',
        status: timelineStatus(event) || 'processing',
        childRunId,
        payload: timelineEventPayload(event),
        artifactCount: Number(event.artifact_count || 0),
        task,
      });
      return;
    }
    if (name === 'workflow.node.workflow') {
      const childRunId = timelineChildRunId(event);
      const task = String(event.workflow_node_task || event.step_task || '').trim();
      const childWorkflowName = String(event.child_workflow_name || event.child_workflow_id || '').trim();
      upsertWorkflowStep(steps, indexByKey, {
        key: `workflow:${nodeId || childRunId || detail || index}`,
        kind: 'workflow',
        nodeId,
        label: detail || childWorkflowName || 'Workflow',
        status: timelineStatus(event) || 'processing',
        childRunId,
        payload: timelineEventPayload(event),
        artifactCount: Number(event.artifact_count || 0),
        task,
      });
      return;
    }
    if (name === 'workflow.node.approval_required' || name === 'workflow.node.approval_approved' || name === 'workflow.node.approval_rejected') {
      const label = normalizeWorkflowApprovalLabel(name, detail);
      const task = String(event.workflow_node_approval_criteria || event.criteria || '').trim();
      upsertWorkflowStep(steps, indexByKey, {
        key: `approval:${nodeId || label}`,
        kind: 'approval',
        nodeId,
        label,
        status: timelineStatus(event) || (name === 'workflow.node.approval_required' ? 'approval_required' : name === 'workflow.node.approval_rejected' ? 'cancelled' : 'completed'),
        payload: workflowApprovalPayloadSummary(event),
        task,
      });
      return;
    }
    if (name === 'workflow.node.condition') {
      const condition = String(event.workflow_node_condition || event.condition || '').trim();
      const branch = String(event.workflow_node_selected_branch || '').trim();
      const target = String(event.workflow_node_selected_target || '').trim();
      const matched = event.workflow_node_condition_matched === true;
      upsertWorkflowStep(steps, indexByKey, {
        key: `condition:${nodeId || detail || index}`,
        kind: 'condition',
        nodeId,
        label: detail || 'Condition',
        status: timelineStatus(event) || 'completed',
        payload: `条件${matched ? '命中' : '未命中'}，选择 ${branch || 'unknown'}${target ? ` -> ${target}` : ''}`,
        task: condition,
        selectedBranch: branch,
        selectedTargetNodeId: target,
      });
      return;
    }
    if (name === 'workflow.node.parallel') {
      const branchCount = Number(event.workflow_node_branch_count || 0);
      const completedCount = Number(event.workflow_node_completed_branch_count || 0);
      const joinTarget = String(event.workflow_node_join_target || '').trim();
      upsertWorkflowStep(steps, indexByKey, {
        key: `parallel:${nodeId || detail || index}`,
        kind: 'parallel',
        nodeId,
        label: detail || 'Parallel',
        status: timelineStatus(event) || 'completed',
        payload: `并行分支完成 ${completedCount}/${branchCount}${joinTarget ? `，汇合到 ${joinTarget}` : ''}`,
      });
      return;
    }
    if (name === 'workflow.node.loop') {
      const condition = String(event.workflow_node_condition || event.condition || '').trim();
      const branch = String(event.workflow_node_selected_branch || '').trim();
      const target = String(event.workflow_node_selected_target || '').trim();
      const iteration = Number(event.workflow_node_loop_iteration || 0);
      const maxIterations = Number(event.workflow_node_loop_max_iterations || 0);
      const limitReached = event.workflow_node_loop_limit_reached === true;
      upsertWorkflowStep(steps, indexByKey, {
        key: `loop:${nodeId || detail || index}:${iteration}:${branch}`,
        kind: 'loop',
        nodeId,
        label: detail || 'Loop',
        status: timelineStatus(event) || 'completed',
        payload: `循环${branch === 'continue' ? '继续' : '退出'} · ${iteration}/${maxIterations || '?'}${limitReached ? ' · 已达到上限' : ''}${target ? ` -> ${target}` : ''}`,
        task: condition,
        selectedBranch: branch,
        selectedTargetNodeId: target,
      });
      return;
    }
    if (name === 'workflow.node.artifact') {
      const artifactPath = workflowArtifactPath(event);
      upsertWorkflowStep(steps, indexByKey, {
        key: `artifact:${nodeId || artifactPath || detail || index}`,
        kind: 'artifact',
        nodeId,
        label: detail || 'Artifact',
        status: timelineStatus(event) || 'completed',
        artifactPath,
      });
      return;
    }
    if ((name === 'workflow.run.failed' || name === 'workflow.run.cancelled') && nodeId) {
      const kind = workflowEventNodeKind(event);
      const label = String(event.workflow_node_label || workflowStepKindLabel(kind)).trim();
      upsertWorkflowStep(steps, indexByKey, {
        key: `${kind}:${nodeId}`,
        kind,
        nodeId,
        label,
        status: name === 'workflow.run.cancelled' ? 'cancelled' : 'failed',
        payload: detail || timelineEventPayload(event),
      });
    }
  });
  const specSteps = workflowSnapshotStepRefs(run);
  const workflowSpecSteps = workflowSpecStepRefs(workflow);
  const fallbackSpecSteps = specSteps.length
    ? specSteps
    : workflowSpecAlignsWithObservedSteps(workflowSpecSteps, steps)
      ? workflowSpecSteps
      : [];
  if (fallbackSpecSteps.length) {
    return mergeWorkflowStepRefs(fallbackSpecSteps, steps);
  }
  return steps;
}

export function workflowStepKindLabel(kind: WorkflowStepRef['kind']): string {
  if (kind === 'start') return 'Start';
  if (kind === 'agent') return 'Agent';
  if (kind === 'approval') return 'Approval';
  if (kind === 'artifact') return 'Artifact';
  if (kind === 'condition') return 'Condition';
  if (kind === 'parallel') return 'Parallel';
  if (kind === 'workflow') return 'Workflow';
  if (kind === 'loop') return 'Loop';
  return 'Unknown';
}

export function workflowStepSummary(step: WorkflowStepRef, childRun: RunSpec | null): string {
  if (step.status === 'pending') {
    if (step.kind === 'start') return '等待 Workflow 开始。';
    if (step.kind === 'approval') return '等待前置节点完成后进入人工审批。';
    if (step.kind === 'artifact') {
      return step.artifactPath
        ? `等待前置节点完成后写出 Workflow artifact：${step.artifactPath}`
        : '等待前置节点完成后写出 artifact。';
    }
    if (step.kind === 'condition') {
      return step.task ? `等待前置节点完成后判断条件：${step.task}` : '等待前置节点完成后判断条件。';
    }
    if (step.kind === 'parallel') return '等待前置节点完成后并行执行多个分支。';
    if (step.kind === 'workflow') {
      return step.task ? `等待前置节点完成后运行子 Workflow：${step.task}` : '等待前置节点完成后运行子 Workflow。';
    }
    if (step.kind === 'loop') {
      return step.task ? `等待前置节点完成后判断循环条件：${step.task}` : '等待前置节点完成后判断循环条件。';
    }
    if (step.kind === 'unknown') return '等待修复或确认未知 Workflow 节点。';
    if (step.task) return `等待前置节点完成后执行：${step.task}`;
    return '等待前置节点完成后执行。';
  }
  const plannerSummary = workflowChildPlannerOutputSummary(childRun);
  if (step.kind === 'start') return 'Workflow 开始执行。';
  if (step.kind === 'approval') {
    const detail = step.payload ? `\n${step.payload}` : '';
    if (step.status === 'approval_required') return `等待人工确认后继续。${detail}`;
    if (step.status === 'cancelled' || step.status === 'failed') return `人工审批已拒绝或取消。${detail}`;
    return `人工审批已通过。${detail}`;
  }
  if (step.kind === 'artifact') {
    return step.artifactPath ? `写出 Workflow artifact：${step.artifactPath}` : '写出 Workflow artifact。';
  }
  if (step.kind === 'condition') {
    return step.payload || (step.task ? `判断条件：${step.task}` : '条件节点已执行。');
  }
  if (step.kind === 'parallel') {
    return step.payload || '并行分支已完成。';
  }
  if (step.kind === 'workflow') {
    return appendWorkflowPlannerSummary(
      childRun?.result || step.payload || '子 Workflow 正在执行或等待继续。',
      plannerSummary,
    );
  }
  if (step.kind === 'loop') {
    return step.payload || (step.task ? `循环条件已判断：${step.task}` : '循环节点已执行。');
  }
  if (step.kind === 'unknown') return step.payload || '未知 Workflow 节点，建议检查 Workflow 定义或导入数据。';
  return appendWorkflowPlannerSummary(
    childRun?.result || step.payload || 'No result yet.',
    plannerSummary,
  );
}

function appendWorkflowPlannerSummary(summary: string, plannerSummary: string): string {
  return plannerSummary ? `${summary}\n${plannerSummary}` : summary;
}

function workflowChildPlannerOutputSummary(childRun: RunSpec | null): string {
  const counts = workflowChildPlannerOutputCounts(childRun);
  const parts = [
    counts.approvals ? `${counts.approvals} approvals` : '',
    counts.artifacts ? `${counts.artifacts} artifacts` : '',
    counts.questions ? `${counts.questions} questions` : '',
  ].filter(Boolean);
  return parts.length ? `Planner outputs · ${parts.join(' · ')}` : '';
}

function workflowChildPlannerOutputCounts(childRun: RunSpec | null): {
  approvals: number;
  artifacts: number;
  questions: number;
} {
  const approvals = new Set<string>();
  const artifacts = new Set<string>();
  const questions = new Set<string>();
  (childRun?.timeline || []).forEach((event) => {
    const eventName = String(event.event || event.event_type || '').trim();
    const payload = workflowPlannerEventPayload(event);
    if (
      eventName === 'agent.plan.created'
      || eventName === 'workflow.plan.created'
      || eventName === 'workflow.run.plan.created'
    ) {
      const plan = workflowRecord(payload.plan);
      const toolPlan = workflowRecord(plan.tool_plan);
      addWorkflowStringValues(approvals, toolPlan.approvals_required);
      addWorkflowStringValues(artifacts, toolPlan.artifacts_expected);
      addWorkflowStringValues(questions, toolPlan.open_questions);
      return;
    }
    if (
      eventName !== 'agent.plan.selection'
      && eventName !== 'workflow.plan.selection'
      && eventName !== 'workflow.run.plan.selection'
    ) return;
    addWorkflowStringValues(approvals, payload.approvals_required);
    addWorkflowStringValues(artifacts, payload.artifacts_expected);
    addWorkflowStringValues(questions, payload.open_questions);
  });
  return {
    approvals: approvals.size,
    artifacts: artifacts.size,
    questions: questions.size,
  };
}

function workflowPlannerEventPayload(event: Record<string, unknown>): Record<string, unknown> {
  return {
    ...event,
    ...workflowRecord(event.payload),
  };
}

function workflowRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as Record<string, unknown>
    : {};
}

function addWorkflowStringValues(target: Set<string>, value: unknown): void {
  if (!Array.isArray(value)) return;
  value.forEach((item) => {
    const clean = String(item || '').trim();
    if (clean) target.add(clean);
  });
}

export function workflowStepArtifacts(childRun: RunSpec | null) {
  return (childRun?.artifacts || []).filter((artifact) => (
    String(artifact.kind || '').trim() !== 'context'
    && Boolean(String(artifact.path || '').trim())
  ));
}

export function workflowRunArtifactForStep(run: RunSpec | null, step: WorkflowStepRef) {
  if (!run || run.kind !== 'workflow_run' || step.kind !== 'artifact') return null;
  const stepPath = String(step.artifactPath || '').trim();
  if (!stepPath) return null;
  const stepNodeId = String(step.nodeId || '').trim();
  return (run.artifacts || []).find((artifact) => {
    const kind = String(artifact.kind || '').trim();
    const path = String(artifact.path || '').trim();
    if (kind !== 'workflow_artifact' || path !== stepPath) return false;
    const artifactNodeId = String(artifact.workflow_node_id || '').trim();
    return !stepNodeId || !artifactNodeId || artifactNodeId === stepNodeId;
  }) || null;
}

export function skippedWorkflowArtifactLabel(run: RunSpec | null, step: WorkflowStepRef) {
  const runStatus = String(run?.status || '').trim();
  const stepStatus = String(step.status || '').trim();
  if (stepStatus === 'failed' || stepStatus === 'cancelled') return '未生成';
  if ((runStatus === 'failed' || runStatus === 'cancelled') && stepStatus === 'pending') return '已跳过';
  return '计划中';
}

export function workflowChildRunRefs(run: RunSpec | null): WorkflowChildRunRef[] {
  if (!run || run.kind !== 'workflow_run') return [];
  const refs: WorkflowChildRunRef[] = [];
  const seen = new Set<string>();
  (run.timeline || []).forEach((event) => {
    const eventName = String(event.event || '');
    if (eventName !== 'workflow.node.agent' && eventName !== 'workflow.node.workflow') return;
    const childRunId = timelineChildRunId(event);
    if (!childRunId || seen.has(childRunId)) return;
    seen.add(childRunId);
    refs.push({
      childRunId,
      label: String(event.detail || 'Agent'),
      status: timelineStatus(event),
    });
  });
  return refs;
}

export function workflowPendingApprovalChildRunId(run: RunSpec | null): string {
  if (!run || run.kind !== 'workflow_run' || run.status !== 'approval_required') return '';
  const events = [...(run.timeline || [])].reverse();
  const event = events.find((item) => (
    String(item.event || '') === 'workflow.run.approval_required'
    && timelineChildRunId(item)
  ));
  return event ? timelineChildRunId(event) : '';
}
