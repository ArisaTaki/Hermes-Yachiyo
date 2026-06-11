import { useCallback, useEffect, useMemo, useRef, useState, type DragEvent } from 'react';
import type { Connection, Edge, Node } from '@xyflow/react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
  addEdge,
  useEdgesState,
  useNodesState,
} from '@xyflow/react';
import '@xyflow/react/dist/style.css';

import { ConfirmDialog } from '../components/ConfirmDialog';
import {
  attachSkill,
  approveRunApproval,
  cancelRun,
  createSkillFolder,
  createAgent,
  createAgentRun,
  createWorkflow,
  createWorkflowRun,
  deleteAgent,
  deleteRun,
  deleteSkillFolder,
  deleteSkill,
  deleteWorkflow,
  detachSkill,
  getRun,
  getRunArtifact,
  getRunEvents,
  getRunGroup,
  importSkill,
  installSkillCommand,
  listAgents,
  listRunGroups,
  listRunnables,
  listRuns,
  listSkillFolders,
  listSkillSources,
  listSkills,
  listWorkflows,
  rejectRunApproval,
  rerunRun,
  syncNativeSkills,
  testAgentModel,
  updateAgent,
  updateSkill,
  updateSkillFolder,
  updateWorkflow,
  type AgentSpec,
  type RunnableSummary,
  type RunGroupSpec,
  type RunEventSpec,
  type RunSpec,
  type SkillFolderSpec,
  type SkillSourceRoot,
  type SkillSyncResult,
  type SkillSpec,
  type WorkflowSpec,
} from '../lib/agents';
import { chooseAvatarImage, chooseSkillSources, openAppView, openPath } from '../lib/bridge';
import { listModelProfiles, type ModelProfile, type ModelProfileDefaults } from '../lib/modelProfiles';
import { currentParam, navigateTo } from '../lib/view';

type StudioTab = 'agents' | 'skills' | 'skill-groups' | 'workflows' | 'runs';
type SkillFolderFilter = 'all' | 'uncategorized' | string;
type RunKindFilter = 'all' | 'workflow' | 'agent';
type RunStatusFilter = 'all' | 'completed' | 'failed' | 'active';

type WorkflowChildRunRef = {
  childRunId: string;
  label: string;
  status: string;
};

type WorkflowStepRef = {
  key: string;
  kind: 'start' | 'agent' | 'approval' | 'artifact' | 'unknown';
  nodeId?: string;
  label: string;
  status: string;
  childRunId?: string;
  payload?: string;
  artifactPath?: string;
  artifactCount?: number;
  task?: string;
};

type WorkflowValidationReport = {
  errors: string[];
  warnings: string[];
};

type RunHistoryGroup = {
  key: string;
  label: string;
  subtitle: string;
  avatarUrl?: string;
  runs: RunSpec[];
};

type RunEventReplayState = {
  events: RunEventSpec[];
  limit: number;
  hasMore: boolean;
  loading: boolean;
  error?: string;
};

type StudioRefreshOptions = {
  selectedAgentId?: string;
  selectFirstAgent?: boolean;
  selectedWorkflowId?: string;
  selectFirstWorkflow?: boolean;
  runTarget?: string;
  selectedRunId?: string;
  statusMessage?: string;
  skipRefresh?: boolean;
};

type ApprovedApprovalGuard = {
  signature: string;
  staleUntil: number;
};

const RUN_EVENT_REPLAY_PAGE_SIZE = 200;
const approvedApprovalStaleWindowMs = 6000;
const runApprovalPollAttempts = 100;
const runApprovalPollIntervalMs = 1200;

type ConfirmDialogState = {
  title: string;
  description: string;
  confirmLabel: string;
  variant?: 'default' | 'danger';
  onConfirm: () => void;
};

type AgentDraft = {
  agent_id?: string;
  name: string;
  nickname: string;
  description: string;
  avatar_url: string;
  category: string;
  instructions: string;
  persona_prompt: string;
  model_mode: 'profile' | 'custom_api';
  model_profile_id: string;
  vision_model_profile_id: string;
  base_url: string;
  model: string;
  api_key: string;
  output_contract: string;
  allow_workspace_read: boolean;
  allow_workspace_write: boolean;
  allow_terminal: boolean;
  allow_artifacts: boolean;
  default_workdir: string;
  readable_scopes: string;
  writable_scopes: string;
  enabled: boolean;
};

const emptyAgentDraft: AgentDraft = {
  name: '',
  nickname: '',
  description: '',
  avatar_url: '',
  category: 'custom',
  instructions: '',
  persona_prompt: '',
  model_mode: 'profile',
  model_profile_id: '',
  vision_model_profile_id: '',
  base_url: '',
  model: '',
  api_key: '',
  output_contract: 'chat',
  allow_workspace_read: false,
  allow_workspace_write: false,
  allow_terminal: false,
  allow_artifacts: true,
  default_workdir: '',
  readable_scopes: '.',
  writable_scopes: '',
  enabled: true,
};

type SkillImportResult = {
  source: string;
  status: 'success' | 'failed' | 'skipped' | 'updated' | 'imported';
  message: string;
};

type SkillSourceFilter = 'installed' | 'native';
const studioRouteTabs: StudioTab[] = ['agents', 'skills', 'skill-groups', 'workflows', 'runs'];
const studioTabs: StudioTab[] = ['agents', 'skills', 'workflows', 'runs'];
const skillFolderNameMaxLength = 120;
const workflowNodeTypes = new Set(['start', 'agent', 'approval', 'artifact']);
const workflowRunnableNodeTypes = new Set(['agent', 'approval', 'artifact']);
const defaultAgentIds = new Set([
  'agent_yachiyo_orchestrator',
  'agent_coding',
  'agent_design',
  'agent_review',
  'agent_research',
  'agent_office',
  'agent_custom',
]);
const workflowRunnableStepRequiredMessage = 'Workflow 至少需要一个可执行节点（Agent、Approval 或 Artifact）';

function workflowStepKind(value: unknown): WorkflowStepRef['kind'] {
  const kind = String(value || '').trim();
  if (kind === 'start' || kind === 'agent' || kind === 'approval' || kind === 'artifact') return kind;
  return 'unknown';
}

const starterNodes: Node[] = [
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

function AgentStudioLoadingState() {
  return (
    <section className="agent-studio-grid agent-studio-loading" aria-label="正在读取 Agent Studio">
      <aside className="agent-studio-panel">
        <div className="section-heading-row">
          <span className="agent-studio-skeleton-line title" />
          <span className="agent-studio-skeleton-button" />
        </div>
        <div className="agent-studio-skeleton-list">
          {Array.from({ length: 5 }).map((_, index) => (
            <div className="agent-studio-skeleton-card" key={index}>
              <span className="agent-studio-skeleton-avatar" />
              <span className="agent-studio-skeleton-stack">
                <span className="agent-studio-skeleton-line name" />
                <span className="agent-studio-skeleton-line meta" />
              </span>
            </div>
          ))}
        </div>
      </aside>
      <div className="agent-studio-panel">
        <div className="section-heading-row">
          <span className="agent-studio-skeleton-line title wide" />
        </div>
        <div className="agent-studio-skeleton-form">
          <span className="agent-studio-skeleton-avatar large" />
          <span className="agent-studio-skeleton-line field" />
          <span className="agent-studio-skeleton-line field" />
          <span className="agent-studio-skeleton-line field wide" />
          <span className="agent-studio-skeleton-block" />
          <span className="agent-studio-skeleton-block short" />
        </div>
      </div>
    </section>
  );
}

function scopesToText(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : String(value || '');
}

function textToScopes(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function normalizeSkillSources(sources: string[]): string[] {
  const cleanSources = sources
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(cleanSources));
}

function skillPathLabel(skill: SkillSpec): string {
  return skill.local_path || skill.source_path || 'local skill';
}

function skillSourceLabel(skill: SkillSpec): string {
  const sourceRef = String(skill.source_ref || '').trim();
  const sourceType = String(skill.source_type || '');
  if (sourceRef && sourceType === 'npx_skills') return sourceRef;
  if (sourceRef && /^https?:\/\//.test(sourceRef)) return sourceRef;
  return skill.origin_path || skill.source_path || sourceRef;
}

function localSourceAlias(source: string): string {
  const clean = source.trim().replace(/[\\/]+$/, '');
  const name = clean.split(/[\\/]/).pop();
  return name ? `local:${name}` : '';
}

function skillSourceTypeLabel(value?: string): string {
  if (value === 'native_global') return 'Native Global';
  if (value === 'native_project') return 'Native Project';
  if (value === 'npx_skills') return 'npx skills';
  if (value === 'local_zip') return 'Installed ZIP';
  return 'Installed Skill';
}

function isNativeSkill(skill: SkillSpec): boolean {
  return skill.source_type === 'native_global' || skill.source_type === 'native_project';
}

function isInstalledSkill(skill: SkillSpec): boolean {
  return !isNativeSkill(skill);
}

function toggleSelectedId(current: string[], id: string): string[] {
  if (!id) return current;
  if (current.includes(id)) return current.filter((item) => item !== id);
  return [...current, id];
}

function pruneSelectedIds(current: string[], availableIds: string[]): string[] {
  const available = new Set(availableIds);
  const next = current.filter((id) => available.has(id));
  if (next.length === current.length) return current;
  return next;
}

function skillMatchesSourceFilter(skill: SkillSpec, filter: SkillSourceFilter): boolean {
  return filter === 'native' ? isNativeSkill(skill) : isInstalledSkill(skill);
}

function skillMatchesFolderFilter(skill: SkillSpec, filter: SkillFolderFilter): boolean {
  if (filter === 'all') return true;
  if (filter === 'uncategorized') return !skill.folder_id;
  return skill.folder_id === filter;
}

function skillMatchesQuery(skill: SkillSpec, query: string): boolean {
  const clean = query.trim().toLowerCase();
  if (!clean) return true;
  return [
    skill.name,
    skill.description,
    skill.content_summary,
    skill.source_ref,
    skill.source_path,
    skill.local_path,
    skill.origin_path,
    skill.folder_name,
  ].some((value) => String(value || '').toLowerCase().includes(clean));
}

function skillResultStatusLabel(status: string): string {
  if (status === 'success' || status === 'imported') return '成功';
  if (status === 'updated') return '更新';
  if (status === 'skipped') return '跳过';
  return '失败';
}

function syncResultsToImportResults(results: SkillSyncResult[] = []): SkillImportResult[] {
  return results.map((result) => ({
    source: result.source || result.source_ref || result.name || 'unknown',
    status: result.status === 'updated' ? 'updated' : result.status === 'imported' ? 'imported' : result.status === 'failed' ? 'failed' : 'skipped',
    message: result.message || result.name || result.status,
  }));
}

function agentInitial(name: string): string {
  const clean = name.trim();
  return clean ? clean.slice(0, 1).toUpperCase() : 'A';
}

function policyTools(agent: AgentSpec): Set<string> {
  const allowed = agent.tool_policy?.allowed_tools;
  return new Set(Array.isArray(allowed) ? allowed.map((item) => String(item)) : []);
}

function draftToolPolicy(draft: AgentDraft): Record<string, unknown> {
  const allowed = new Set<string>();
  if (draft.allow_workspace_read) {
    allowed.add('workspace.list');
    allowed.add('workspace.read');
  }
  if (draft.allow_workspace_write) allowed.add('workspace.write_patch');
  if (draft.allow_terminal) allowed.add('terminal.run');
  if (draft.allow_artifacts) allowed.add('artifact.write');
  return {
    allowed_tools: Array.from(allowed),
    approval_required: {
      'terminal.run': true,
      'workspace.write_patch': true,
    },
  };
}

function agentToDraft(agent: AgentSpec): AgentDraft {
  const workspace = agent.workspace_policy || {};
  const tools = policyTools(agent);
  return {
    agent_id: agent.agent_id,
    name: agent.name,
    nickname: agent.nickname || agent.name,
    description: agent.description || '',
    avatar_url: agent.avatar_url || '',
    category: agent.category || 'custom',
    instructions: agent.instructions || '',
    persona_prompt: agent.persona_prompt || '',
    model_mode: agent.model_mode === 'custom_api' ? 'custom_api' : 'profile',
    model_profile_id: agent.model_profile_id || '',
    vision_model_profile_id: agent.vision_model_profile_id || '',
    base_url: agent.model_config?.base_url || '',
    model: agent.model_config?.model || '',
    api_key: '',
    output_contract: agent.output_contract || 'chat',
    allow_workspace_read: tools.has('workspace.list') || tools.has('workspace.read'),
    allow_workspace_write: tools.has('workspace.write_patch'),
    allow_terminal: tools.has('terminal.run'),
    allow_artifacts: agent.tool_policy?.allowed_tools === undefined ? true : tools.has('artifact.write'),
    default_workdir: String(workspace.default_workdir || ''),
    readable_scopes: scopesToText(workspace.readable_scopes || ['.']),
    writable_scopes: scopesToText(workspace.writable_scopes || []),
    enabled: agent.enabled !== false,
  };
}

function workflowNodes(workflow: WorkflowSpec | null): Node[] {
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

function workflowEdges(workflow: WorkflowSpec | null): Edge[] {
  if (!workflow) return [];
  return workflow.edges.map((edge, index) => ({
    id: edge.id || `edge-${index}`,
    source: edge.source,
    target: edge.target,
  }));
}

function workflowNodeKind(node: Node): string {
  const dataKind = String(node.data?.kind || node.data?.node_type || '').trim();
  const nodeType = String(node.type || '').trim();
  if (dataKind && ['', 'input', 'default', 'output'].includes(nodeType)) return dataKind;
  return nodeType || dataKind;
}

function workflowNodeKindLabel(kind: string): string {
  if (kind === 'agent') return 'Agent';
  if (kind === 'approval') return 'Approval';
  if (kind === 'artifact') return 'Artifact';
  if (kind === 'start') return 'Start';
  return kind || 'Node';
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

function validateWorkflowDraft(nodes: Node[], edges: Edge[], agents: AgentSpec[]): WorkflowValidationReport {
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
    if (targets.length > 1) errors.push(`${label} 有多个下一步，Workflow v1 只支持线性流程`);
    if (nodeId !== startId && sources.length !== 1) errors.push(`${label} 必须且只能有一个上一节点`);
  });

  if (startId && !errors.some((item) => item.includes('edge 引用'))) {
    const seen = new Set<string>();
    const active = new Set<string>();
    const visit = (nodeId: string) => {
      if (active.has(nodeId)) {
        errors.push('Workflow 不能包含环');
        return;
      }
      if (seen.has(nodeId)) return;
      active.add(nodeId);
      (outgoing.get(nodeId) || []).forEach(visit);
      active.delete(nodeId);
      seen.add(nodeId);
    };
    visit(startId);
    if (seen.size !== nodeIdSet.size) {
      errors.push('Workflow v1 必须是一条从 Start 出发的单一路径');
    }
  }

  if (!workflowHasRunnableSteps(nodes)) {
    warnings.push('当前没有可执行节点；可以保存草稿，但运行前需要添加 Agent、Approval 或 Artifact。');
  }

  return {
    errors: Array.from(new Set(errors)),
    warnings: Array.from(new Set(warnings)),
  };
}

function workflowHasRunnableSteps(nodes: Node[]): boolean {
  return nodes.some((node) => workflowRunnableNodeTypes.has(workflowNodeKind(node)));
}

function workflowRequestNodes(nodes: Node[]): WorkflowSpec['nodes'] {
  return nodes.map((node) => ({
    id: node.id,
    type: String(node.data?.kind || (node.type === 'input' ? 'start' : node.type === 'output' ? 'artifact' : 'agent')),
    position: node.position,
    data: node.data as Record<string, unknown>,
  }));
}

function workflowRequestEdges(edges: Edge[]): WorkflowSpec['edges'] {
  return edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
  }));
}

function linearEdgesForNodes(nextNodes: Node[]): Edge[] {
  return nextNodes.slice(0, -1).map((node, index) => {
    const target = nextNodes[index + 1];
    return {
      id: `edge-${node.id}-${target.id}`,
      source: node.id,
      target: target.id,
    };
  });
}

function terminalNodeId(currentNodes: Node[], currentEdges: Edge[]): string {
  const nodesWithOutgoing = new Set(currentEdges.map((edge) => edge.source).filter(Boolean));
  const terminal = [...currentNodes].reverse().find((node) => !nodesWithOutgoing.has(node.id));
  return terminal?.id || currentNodes[currentNodes.length - 1]?.id || '';
}

function uniqueWorkflowNodeId(seed: string, currentNodes: Node[]): string {
  const existing = new Set(currentNodes.map((node) => node.id));
  const cleanSeed = seed.replace(/[^A-Za-z0-9_-]+/g, '-').replace(/^-+|-+$/g, '') || 'node';
  if (!existing.has(cleanSeed)) return cleanSeed;
  let index = 2;
  while (existing.has(`${cleanSeed}-${index}`)) index += 1;
  return `${cleanSeed}-${index}`;
}

function buildPhase4WorkflowNodes(agents: AgentSpec[]): Node[] {
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

function normalizeRunStatus(status: string): string {
  const value = String(status || '').trim();
  return value === 'running' ? 'processing' : value;
}

function isActiveRunStatus(status: string): boolean {
  return ['processing', 'pending', 'approval_required'].includes(normalizeRunStatus(status));
}

function approvalInputSignature(value: unknown): string {
  if (value === undefined || value === null) return '';
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value);
  } catch {
    return String(value);
  }
}

function runApprovalSignature(run: RunSpec | null | undefined): string {
  const pending = run?.pending_approval;
  if (!pending) return '';
  const approvalId = String(pending.approval_id || '').trim();
  if (approvalId) return `id:${approvalId}`;
  return [
    String(pending.tool || '').trim(),
    approvalInputSignature(pending.input_preview),
  ].join('\n');
}

function makeRunContinuingAfterApproval(run: RunSpec, result: string): RunSpec {
  const nextRun: RunSpec = { ...run };
  delete nextRun.pending_approval;
  return {
    ...nextRun,
    status: 'processing',
    result,
    updated_at: new Date().toISOString(),
  };
}

function approvedRunStatusMessage(run: RunSpec): string {
  const status = normalizeRunStatus(run.status);
  if (status === 'processing') return '已批准，Run 正在继续执行。';
  if (status === 'approval_required') return '已批准，Run 需要继续处理下一次审批。';
  if (status === 'completed') return '已批准，Run 已完成。';
  if (status === 'failed') return '已批准，但 Run 执行失败。';
  return '已批准，Run 状态已更新。';
}

function runStatusLabel(status: string): string {
  const normalized = normalizeRunStatus(status);
  if (normalized === 'completed') return '已完成';
  if (normalized === 'failed') return '执行失败';
  if (normalized === 'cancelled') return '已取消';
  if (normalized === 'approval_required') return '等待审批';
  if (normalized === 'processing') return '进行中';
  if (normalized === 'pending') return '等待中';
  return normalized || '未知状态';
}

function runStatusTone(status: string): string {
  const normalized = normalizeRunStatus(status);
  if (normalized === 'completed') return 'ready';
  if (normalized === 'failed' || normalized === 'cancelled') return 'danger';
  if (normalized === 'approval_required') return 'approval';
  return 'running';
}

function runKindLabel(kind: string): string {
  if (kind === 'agent_run') return 'Agent Run';
  if (kind === 'workflow_run') return 'Workflow Run';
  return kind || 'Run';
}

function runHistoryGroupKindLabel(run: RunSpec): string {
  if (run.kind === 'agent_run') return 'Agent';
  if (run.kind === 'workflow_run') return 'Workflow';
  return runKindLabel(run.kind);
}

function runHistoryGroupKey(run: RunSpec): string {
  if (run.kind === 'agent_run') return `agent:${run.runnable_id || run.runnable_name || 'unknown'}`;
  if (run.kind === 'workflow_run') return `workflow:${run.runnable_id || run.runnable_name || 'unknown'}`;
  return `${run.kind || 'run'}:${run.runnable_id || run.runnable_name || 'unknown'}`;
}

function runHistoryGroupSummary(runs: RunSpec[]): string {
  const failed = runs.filter((run) => ['failed', 'cancelled'].includes(normalizeRunStatus(run.status))).length;
  const active = runs.filter((run) => isActiveRunStatus(run.status)).length;
  const completed = runs.filter((run) => normalizeRunStatus(run.status) === 'completed').length;
  const parts = [
    active ? `${active} active` : '',
    failed ? `${failed} failed` : '',
    completed ? `${completed} done` : '',
  ].filter(Boolean);
  return parts.length ? parts.join(' · ') : `${runs.length} runs`;
}

function runUpdatedTimestamp(run?: RunSpec): number {
  const timestamp = Date.parse(run?.updated_at || run?.created_at || '');
  return Number.isFinite(timestamp) ? timestamp : 0;
}

function toolPolicyCapabilityLine(policy: unknown): string {
  if (!policy || typeof policy !== 'object') return '';
  const raw = policy as { allowed_tools?: unknown; approval_required?: unknown };
  const allowedTools = Array.isArray(raw.allowed_tools)
    ? raw.allowed_tools.map((tool) => String(tool || '').trim()).filter(Boolean)
    : [];
  const approvalRequired = raw.approval_required && typeof raw.approval_required === 'object'
    ? raw.approval_required as Record<string, unknown>
    : {};
  const tools = [...allowedTools];
  Object.keys(approvalRequired).forEach((tool) => {
    if (approvalRequired[tool] === true && !tools.includes(tool)) tools.push(tool);
  });
  if (!tools.length) return '';
  const labels: string[] = [];
  const add = (label: string) => {
    if (!labels.includes(label)) labels.push(label);
  };
  const needsApproval = (tool: string) => approvalRequired[tool] === true;
  if (tools.includes('workspace.read') || tools.includes('workspace.list')) add('读文件');
  if (tools.includes('workspace.write_patch')) add(needsApproval('workspace.write_patch') ? '写补丁需审批' : '写补丁');
  if (tools.includes('terminal.run')) add(needsApproval('terminal.run') ? '终端需审批' : '终端');
  if (tools.includes('artifact.write')) add('产物');
  tools.forEach((tool) => {
    if (['workspace.read', 'workspace.list', 'workspace.write_patch', 'terminal.run', 'artifact.write'].includes(tool)) return;
    add(needsApproval(tool) ? `${tool} 需审批` : tool);
  });
  return labels.length ? `工具 ${labels.join('、')}` : '';
}

function runnableCapabilityLine(item: Pick<RunnableSummary, 'category' | 'description' | 'enabled' | 'kind' | 'output_contract' | 'tool_policy'>): string {
  const parts = [
    item.enabled === false ? '停用' : '',
    item.category ? `类别 ${item.category}` : '',
    item.output_contract ? `交付 ${item.output_contract}` : '',
    item.kind === 'agent' ? toolPolicyCapabilityLine(item.tool_policy) : '',
    item.kind === 'workflow' ? 'Workflow' : '',
  ].filter(Boolean);
  return parts.join(' · ') || (item.kind === 'workflow' ? 'Workflow' : 'Agent');
}

function runnableOptionLabel(item: RunnableSummary): string {
  return `${item.kind}: ${item.name} · ${runnableCapabilityLine(item)}`;
}

function agentCapabilityLine(agent: Pick<AgentSpec, 'category' | 'enabled' | 'output_contract' | 'tool_policy'>): string {
  return [
    agent.enabled === false ? '停用' : '',
    agent.category ? `类别 ${agent.category}` : '',
    agent.output_contract ? `交付 ${agent.output_contract}` : '',
    toolPolicyCapabilityLine(agent.tool_policy),
  ].filter(Boolean).join(' · ') || 'Agent';
}

function agentRunReadinessIssue(
  agent: AgentSpec,
  chatProfiles: ModelProfile[],
  modelDefaults: ModelProfileDefaults,
  skills: SkillSpec[],
): string {
  if (agent.enabled === false) return 'Agent 已停用，无法运行。';
  const disabledMountedSkills = skills.filter((skill) => skill.enabled === false && agent.skill_ids?.includes(skill.skill_id));
  if (disabledMountedSkills.length) return `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用。`;
  if (agent.model_mode === 'custom_api') {
    const config = agent.model_config || {};
    const missing = [
      !String(config.base_url || '').trim() ? 'Base URL' : '',
      !String(config.model || '').trim() ? 'Model' : '',
      !config.api_key_configured ? 'API Key' : '',
    ].filter(Boolean);
    if (missing.length) return `Custom API 配置不完整：缺少 ${missing.join('、')}。`;
    return '';
  }
  if (agent.model_mode === 'follow_main' || defaultAgentIds.has(agent.agent_id || '')) {
    const defaultChatProfileId = String(modelDefaults.chat || '').trim();
    if (!defaultChatProfileId) return '默认 Chat Profile 尚未设置。';
    if (!chatProfiles.some((profile) => profile.profile_id === defaultChatProfileId)) {
      return '默认 Chat Profile 不可用或已停用。';
    }
    return '';
  }
  if (!agent.model_profile_id) return '尚未选择 Chat Profile。';
  if (!chatProfiles.some((profile) => profile.profile_id === agent.model_profile_id)) {
    return '当前 Chat Profile 不可用或已停用。';
  }
  return '';
}

function workflowAgentRunReadinessIssue(nodes: Node[], issueByAgentId: Map<string, string>): string {
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

function runHistoryGroupsFor(runs: RunSpec[], runnables: RunnableSummary[], agents: AgentSpec[]): RunHistoryGroup[] {
  const runnableById = new Map(runnables.map((runnable) => [runnable.id, runnable]));
  const agentById = new Map(agents.map((agent) => [agent.agent_id, agent]));
  const groups = new Map<string, RunHistoryGroup>();
  runs.forEach((run) => {
    const key = runHistoryGroupKey(run);
    const runnable = runnableById.get(run.runnable_id);
    const agent = agentById.get(run.runnable_id);
    const label = run.runnable_name || runnable?.nickname || runnable?.name || agent?.nickname || agent?.name || run.runnable_id || runKindLabel(run.kind);
    const existing = groups.get(key);
    if (existing) {
      existing.runs.push(run);
      return;
    }
    groups.set(key, {
      key,
      label,
      subtitle: runHistoryGroupKindLabel(run),
      avatarUrl: runnable?.avatar_url || agent?.avatar_url,
      runs: [run],
    });
  });
  return Array.from(groups.values())
    .map((group) => ({
      ...group,
      runs: [...group.runs].sort((a, b) => runUpdatedTimestamp(b) - runUpdatedTimestamp(a)),
    }))
    .sort((a, b) => runUpdatedTimestamp(b.runs[0]) - runUpdatedTimestamp(a.runs[0]));
}

function isWorkflowChildAgentRun(run: RunSpec): boolean {
  return run.kind === 'agent_run' && run.run_group_source === 'workflow';
}

function isPotentialWorkflowChildAgentRun(run: RunSpec | null): run is RunSpec {
  return Boolean(run && run.kind === 'agent_run' && run.run_group_id);
}

function workflowRunHasChildRun(workflowRun: RunSpec, childRunId: string): boolean {
  if (!childRunId || workflowRun.kind !== 'workflow_run') return false;
  return workflowChildRunRefs(workflowRun).some((ref) => ref.childRunId === childRunId);
}

function runMatchesFilter(run: RunSpec, filter: RunKindFilter): boolean {
  if (isWorkflowChildAgentRun(run)) return false;
  if (filter === 'agent') return run.kind === 'agent_run';
  if (filter === 'workflow') return run.kind === 'workflow_run';
  return true;
}

function runMatchesStatusFilter(run: RunSpec, filter: RunStatusFilter): boolean {
  const status = normalizeRunStatus(run.status);
  if (filter === 'completed') return status === 'completed';
  if (filter === 'failed') return status === 'failed' || status === 'cancelled';
  if (filter === 'active') return isActiveRunStatus(status);
  return true;
}

function compactSearchText(value: unknown): string {
  if (value == null) return '';
  if (typeof value === 'string') return value;
  if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  try {
    return JSON.stringify(value);
  } catch {
    return '';
  }
}

function runSearchHaystack(run: RunSpec, extraText = ''): string {
  const timelineText = (run.timeline || [])
    .map((event) => compactSearchText(event))
    .join(' ');
  const artifactText = (run.artifacts || [])
    .map((artifact) => compactSearchText(artifact))
    .join(' ');
  return [
    run.run_id,
    run.run_group_id,
    run.run_group_source,
    run.kind,
    run.runnable_id,
    run.runnable_name,
    run.status,
    runStatusLabel(run.status),
    runKindLabel(run.kind),
    run.user_goal,
    run.result,
    timelineText,
    artifactText,
    extraText,
  ].map(compactSearchText).join(' ').toLowerCase();
}

function runMatchesSearch(run: RunSpec, query: string, extraText = ''): boolean {
  const terms = query
    .trim()
    .toLowerCase()
    .split(/\s+/)
    .filter(Boolean);
  if (!terms.length) return true;
  const haystack = runSearchHaystack(run, extraText);
  return terms.every((term) => haystack.includes(term));
}

function runSearchTextByRunnableIdFor(
  runnables: RunnableSummary[],
  agents: AgentSpec[],
  workflows: WorkflowSpec[],
): Map<string, string> {
  const next = new Map<string, string>();
  const append = (id: string, parts: unknown[]) => {
    const key = String(id || '').trim();
    if (!key) return;
    next.set(key, [next.get(key) || '', ...parts.map(compactSearchText)].join(' '));
  };
  runnables.forEach((item) => {
    append(item.id, [
      item.kind,
      item.name,
      item.nickname,
      item.description,
      item.category,
      item.output_contract,
      item.enabled === false ? 'disabled 停用' : 'enabled 启用',
      runnableCapabilityLine(item),
    ]);
  });
  agents.forEach((agent) => {
    append(agent.agent_id, [
      'agent',
      agent.name,
      agent.nickname,
      agent.description,
      agent.category,
      agent.output_contract,
      agent.enabled === false ? 'disabled 停用' : 'enabled 启用',
      agentCapabilityLine(agent),
    ]);
  });
  workflows.forEach((workflow) => {
    append(workflow.workflow_id, [
      'workflow',
      workflow.name,
      workflow.description,
      workflow.enabled === false ? 'disabled 停用' : 'enabled 启用',
    ]);
  });
  return next;
}

function formatRunDate(value?: string): string {
  if (!value) return '未知时间';
  const timestamp = Date.parse(value);
  if (!Number.isFinite(timestamp)) return value;
  return new Intl.DateTimeFormat('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
  }).format(timestamp);
}

function formatApprovalInput(value: unknown): string {
  if (typeof value === 'string') return value;
  try {
    return JSON.stringify(value || {}, null, 2);
  } catch {
    return String(value || '');
  }
}

function approvalPreviewRecord(value: unknown): Record<string, unknown> {
  return value && typeof value === 'object' && !Array.isArray(value) ? value as Record<string, unknown> : {};
}

function approvalPreviewValue(record: Record<string, unknown>, keys: string[]): string {
  for (const key of keys) {
    const value = record[key];
    if (typeof value === 'string' && value.trim()) return value.trim();
    if (typeof value === 'number' || typeof value === 'boolean') return String(value);
  }
  return '';
}

function RunApprovalRequest({ inputPreview, runGoal = '', runId = '', runLabel = '', tool }: {
  inputPreview: unknown;
  runGoal?: string;
  runId?: string;
  runLabel?: string;
  tool: string;
}) {
  const preview = approvalPreviewRecord(inputPreview);
  const checkpoint = approvalPreviewValue(preview, ['checkpoint', 'label', 'approval']);
  const criteria = approvalPreviewValue(preview, ['criteria', 'approval_criteria', 'instructions']);
  const workdir = approvalPreviewValue(preview, ['cwd', 'workdir', 'working_dir']);
  const path = approvalPreviewValue(preview, ['path', 'file', 'target']);
  const command = tool === 'terminal.run' ? approvalPreviewValue(preview, ['command', 'cmd']) : '';
  const rows = [
    ['Tool', tool],
    runId ? ['Run', runLabel ? `${runLabel} · ${runId}` : runId] : null,
    runGoal ? ['关联任务', runGoal] : null,
    checkpoint ? ['审批节点', checkpoint] : null,
    criteria ? ['审批说明', criteria] : null,
    workdir ? ['工作目录', workdir] : null,
    path ? ['路径', path] : null,
  ].filter((row): row is string[] => Boolean(row));
  const contentLabel = command ? 'BASH' : tool === 'workflow.approval' ? '审批上下文' : '请求内容';
  const content = command || formatApprovalInput(inputPreview);
  return (
    <div className="run-approval-request" data-testid="agent-run-approval-request">
      <div className="run-approval-summary-grid">
        {rows.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <code>{value}</code>
          </div>
        ))}
      </div>
      <div className="run-approval-request-content">
        <span>{contentLabel}</span>
        <pre><code>{content || '无请求内容'}</code></pre>
      </div>
    </div>
  );
}

function timelineChildRunId(event: Record<string, unknown>): string {
  const value = event.child_run_id;
  return typeof value === 'string' ? value.trim() : '';
}

function timelineStatus(event: Record<string, unknown>): string {
  const value = event.status;
  return typeof value === 'string' ? value.trim() : '';
}

function timelineEventTitle(event: Record<string, unknown>): string {
  const name = String(event.event || 'event');
  const detail = String(event.detail || '').trim();
  if (name === 'run.started') return 'Run 已启动';
  if (name === 'task.linked') return 'Task 已关联';
  if (name === 'model.request.started') return detail ? `模型请求 · ${detail}` : '模型请求已开始';
  if (name === 'model.request.failed') return '模型请求失败';
  if (name === 'model.output.ready') return '模型输出已就绪';
  if (name === 'model.output.completed') return '模型输出完成';
  if (name === 'agent.run.started') return 'Agent 已启动';
  if (name === 'agent.runtime.compiled') return '运行环境已准备';
  if (name === 'agent.artifact.write') return '上下文/产物已写入';
  if (name === 'agent.model.response') return '模型响应';
  if (name === 'agent.tool.call') return detail ? `工具调用 · ${detail}` : '工具调用';
  if (name === 'agent.tool.skipped') return detail ? `工具已跳过 · ${detail}` : '工具已跳过';
  if (name === 'agent.tool.denied') return detail ? `工具已拒绝 · ${detail}` : '工具已拒绝';
  if (name === 'agent.tool.failed') return detail ? `工具调用失败 · ${detail}` : '工具调用失败';
  if (name === 'agent.tool.approval_required') return detail ? `请求审批 · ${detail}` : '请求审批';
  if (name === 'agent.tool.approval_approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';
  if (name === 'agent.tool.approval_rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';
  if (name === 'approval.timeout') return '审批已超时';
  if (name === 'agent.run.resumed') return 'Agent 已继续执行';
  if (name === 'agent.run.completed') return 'Run 已完成';
  if (name === 'agent.run.cancelled') return 'Agent 已取消';
  if (name === 'agent.run.failed') return 'Run 执行失败';
  if (name === 'run.cancelled') return 'Run 已取消';
  if (name === 'run.completed') return 'Run 已完成';
  if (name === 'run.failed') return 'Run 执行失败';
  if (name === 'run.rerun.started') return '从原 Run 重跑';
  if (name === 'workflow.run.started') return 'Workflow 已启动';
  if (name === 'workflow.node.start') return 'Workflow 起点';
  if (name === 'workflow.node.agent') return detail ? `Agent 节点 · ${detail}` : 'Agent 节点';
  if (name === 'workflow.node.artifact') return detail ? `产物节点 · ${detail}` : '产物节点';
  if (name === 'workflow.node.approval_required') return detail ? `人工审批 · ${detail}` : '人工审批';
  if (name === 'workflow.node.approval_approved') return detail ? `审批已通过 · ${detail}` : '审批已通过';
  if (name === 'workflow.node.approval_rejected') return detail ? `审批已拒绝 · ${detail}` : '审批已拒绝';
  if (name === 'workflow.run.approval_required') return 'Workflow 等待审批';
  if (name === 'workflow.run.child_resumed') return '子 Agent 已继续执行';
  if (name === 'workflow.run.resumed') return 'Workflow 已继续执行';
  if (name === 'workflow.run.completed') return 'Workflow 已完成';
  if (name === 'workflow.run.failed') return 'Workflow 执行失败';
  if (name === 'workflow.run.cancelled') return 'Workflow 已取消';
  return name;
}

function timelineEventTone(event: Record<string, unknown>): string {
  const name = String(event.event || '');
  const status = timelineStatus(event);
  if (status === 'failed' || status === 'cancelled' || name.includes('failed') || name.includes('cancelled') || name.includes('timeout') || name.includes('denied')) return 'danger';
  if (status === 'completed' || name.includes('completed')) return 'ready';
  if (status === 'approval_required' || name.includes('approval')) return 'approval';
  if (status === 'running' || status === 'processing' || name.includes('resumed')) return 'running';
  if (name.includes('tool')) return 'tool';
  if (name.startsWith('model.') || name.includes('model.response')) return 'model';
  return 'neutral';
}

function timelineEventCode(event: Record<string, unknown>): string {
  const name = timelineEventName(event);
  return name.includes('.') ? name.split('.').slice(-2).join('.') : name || 'event';
}

function timelineEventName(event: Record<string, unknown>): string {
  return String(event.event || '').trim();
}

function timelineEventSequence(event: Record<string, unknown>): string {
  const value = event.sequence;
  if (typeof value === 'number' && Number.isFinite(value)) return String(value);
  return typeof value === 'string' ? value.trim() : '';
}

function timelineEventTime(event: Record<string, unknown>): string {
  return typeof event.time === 'string' ? event.time : '';
}

function formatTimelinePayload(value: unknown): string {
  if (!value) return '';
  if (typeof value === 'string') return String(value).trim();
  try {
    return JSON.stringify(value, null, 2);
  } catch {
    return String(value).trim();
  }
}

function timelineEventPayload(event: Record<string, unknown>): string {
  const inputPreview = event.input_preview;
  const result = event.result;
  if (inputPreview && result) {
    return [
      `请求内容：\n${formatTimelinePayload(inputPreview)}`,
      `执行结果：\n${formatTimelinePayload(result)}`,
    ].join('\n\n');
  }
  if (inputPreview) return `请求内容：\n${formatTimelinePayload(inputPreview)}`;
  if (result) return formatTimelinePayload(result);
  const pendingApproval = event.pending_approval;
  if (pendingApproval) return formatTimelinePayload(pendingApproval);
  return '';
}

function runEventReplayToTimelineEvent(event: RunEventSpec): Record<string, unknown> {
  const payload = event.payload && typeof event.payload === 'object' ? event.payload : {};
  const detail = typeof payload.tool === 'string'
    ? payload.tool
    : typeof payload.model === 'string'
      ? payload.model
      : typeof payload.result === 'string'
        ? payload.result
        : typeof payload.error === 'string'
          ? payload.error
          : typeof payload.workflow_node_label === 'string'
            ? payload.workflow_node_label
            : '';
  return {
    event_id: event.event_id || '',
    run_id: event.run_id,
    schema_version: event.schema_version || '',
    event: event.event_type,
    actor: event.actor || '',
    visibility: event.visibility || '',
    sensitivity: event.sensitivity || '',
    detail,
    status: typeof payload.status === 'string' ? payload.status : '',
    time: event.created_at || '',
    sequence: event.sequence,
    input_preview: payload.input_preview,
    result: payload.result || payload.content || payload.error || '',
    pending_approval: payload.pending_approval || payload,
    child_run_id: payload.child_run_id,
    workflow_node_id: payload.workflow_node_id,
    workflow_node_kind: payload.workflow_node_kind,
    workflow_node_label: payload.workflow_node_label,
    payload,
  };
}

function mergeRunEventReplayPages(current: RunEventSpec[], incoming: RunEventSpec[]): RunEventSpec[] {
  const bySequence = new Map<number, RunEventSpec>();
  current.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  incoming.forEach((event) => bySequence.set(Number(event.sequence) || 0, event));
  return Array.from(bySequence.values()).sort((left, right) => (Number(left.sequence) || 0) - (Number(right.sequence) || 0));
}

function payloadLineCount(value: string): number {
  if (!value) return 0;
  return value.split(/\r?\n/).length;
}

function runPayloadShouldCollapse(value: string): boolean {
  return value.length > 700 || payloadLineCount(value) > 10;
}

function runPayloadSummary(value: string): string {
  const lines = payloadLineCount(value);
  const units = [`${lines} 行`, `${value.length} 字符`];
  return units.join(' · ');
}

function RunExpandableContent({
  content,
  label,
  defaultOpen = false,
}: {
  content: string;
  label: string;
  defaultOpen?: boolean;
}) {
  const shouldCollapse = runPayloadShouldCollapse(content);
  if (!shouldCollapse) return <pre>{content}</pre>;
  return (
    <details className="run-expandable-content" open={defaultOpen}>
      <summary>
        <span>{label}</span>
        <em>{runPayloadSummary(content)}</em>
      </summary>
      <pre>{content}</pre>
    </details>
  );
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

function workflowSpecStepRefs(workflow: WorkflowSpec | null): WorkflowStepRef[] {
  if (!workflow) return [];
  const nodesById = new Map(workflow.nodes.map((node) => [String(node.id || ''), node]));
  const outgoing = new Map<string, string>();
  workflow.edges.forEach((edge) => {
    const source = String(edge.source || '');
    const target = String(edge.target || '');
    if (source && target && !outgoing.has(source)) outgoing.set(source, target);
  });
  const start = workflow.nodes.find((node) => workflowSpecNodeKind(node) === 'start') || workflow.nodes[0];
  if (!start) return [];
  const ordered: WorkflowSpec['nodes'] = [];
  const seen = new Set<string>();
  let current: WorkflowSpec['nodes'][number] | undefined = start;
  while (current) {
    const nodeId = String(current.id || '');
    if (!nodeId || seen.has(nodeId)) break;
    ordered.push(current);
    seen.add(nodeId);
    const nextId = outgoing.get(nodeId);
    current = nextId ? nodesById.get(nextId) : undefined;
  }
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

function workflowStepRefs(run: RunSpec | null, workflow: WorkflowSpec | null = null): WorkflowStepRef[] {
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

function workflowStepKindLabel(kind: WorkflowStepRef['kind']): string {
  if (kind === 'start') return 'Start';
  if (kind === 'agent') return 'Agent';
  if (kind === 'approval') return 'Approval';
  if (kind === 'artifact') return 'Artifact';
  return 'Unknown';
}

function workflowStepSummary(step: WorkflowStepRef, childRun: RunSpec | null): string {
  if (step.status === 'pending') {
    if (step.kind === 'start') return '等待 Workflow 开始。';
    if (step.kind === 'approval') return '等待前置节点完成后进入人工审批。';
    if (step.kind === 'artifact') {
      return step.artifactPath
        ? `等待前置节点完成后写出 Workflow artifact：${step.artifactPath}`
        : '等待前置节点完成后写出 artifact。';
    }
    if (step.kind === 'unknown') return '等待修复或确认未知 Workflow 节点。';
    if (step.task) return `等待前置节点完成后执行：${step.task}`;
    return '等待前置节点完成后执行。';
  }
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
  if (step.kind === 'unknown') return step.payload || '未知 Workflow 节点，建议检查 Workflow 定义或导入数据。';
  return childRun?.result || step.payload || 'No result yet.';
}

function workflowStepArtifacts(childRun: RunSpec | null) {
  return (childRun?.artifacts || []).filter((artifact) => (
    String(artifact.kind || '').trim() !== 'context'
    && Boolean(String(artifact.path || '').trim())
  ));
}

function workflowRunArtifactForStep(run: RunSpec | null, step: WorkflowStepRef) {
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

function skippedWorkflowArtifactLabel(run: RunSpec | null, step: WorkflowStepRef) {
  const runStatus = String(run?.status || '').trim();
  const stepStatus = String(step.status || '').trim();
  if (stepStatus === 'failed' || stepStatus === 'cancelled') return '未生成';
  if ((runStatus === 'failed' || runStatus === 'cancelled') && stepStatus === 'pending') return '已跳过';
  return '计划中';
}

function WorkflowRunPreview({
  agents,
  agentIssueById,
  sourceNodes,
  steps,
}: {
  agents: AgentSpec[];
  agentIssueById: Map<string, string>;
  sourceNodes: Node[];
  steps: WorkflowStepRef[];
}) {
  const visibleSteps = steps.filter((step) => step.kind !== 'start');
  if (!visibleSteps.length) return null;
  return (
    <div className="workflow-run-preview" data-testid="workflow-run-preview">
      <div className="workflow-run-preview-head">
        <strong>运行顺序</strong>
        <span>{visibleSteps.length} steps</span>
      </div>
      <ol>
        {visibleSteps.map((step, index) => {
          const sourceNode = sourceNodes.find((node) => node.id === step.nodeId);
          const agentId = step.kind === 'agent' ? String(sourceNode?.data?.agent_id || '').trim() : '';
          const agent = agentId ? agents.find((item) => item.agent_id === agentId) || null : null;
          const agentIssue = step.kind === 'agent'
            ? agent
              ? agentIssueById.get(agent.agent_id) || ''
              : agentId
                ? '找不到 Agent 定义。'
                : '尚未选择 Agent。'
            : '';
          const detail = step.kind === 'agent'
            ? step.task || '接收 Workflow Goal 和上游上下文。'
            : step.kind === 'approval'
              ? step.task || '等待人工确认后继续。'
              : step.kind === 'artifact'
                ? step.artifactPath
                  ? `写出 artifact：${step.artifactPath}`
                  : '按节点名称自动生成 artifact 路径。'
                : '未知节点类型，运行前需要修复 Workflow 定义。';
          return (
            <li className={`workflow-run-preview-step ${step.kind}`} data-testid="workflow-run-preview-step" key={step.key}>
              <span className="workflow-run-preview-index">{index + 1}</span>
              <div>
                <strong>{step.label}</strong>
                <em>{workflowStepKindLabel(step.kind)}{agent ? ` · ${agent.nickname || agent.name}` : ''}</em>
                <p>{detail}</p>
                {agent ? <small>{agentCapabilityLine(agent)}</small> : null}
                {agentIssue ? <small>{agentIssue}</small> : null}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
}

function workflowChildRunRefs(run: RunSpec | null): WorkflowChildRunRef[] {
  if (!run || run.kind !== 'workflow_run') return [];
  const refs: WorkflowChildRunRef[] = [];
  const seen = new Set<string>();
  (run.timeline || []).forEach((event) => {
    if (String(event.event || '') !== 'workflow.node.agent') return;
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

function workflowPendingApprovalChildRunId(run: RunSpec | null): string {
  if (!run || run.kind !== 'workflow_run' || run.status !== 'approval_required') return '';
  const events = [...(run.timeline || [])].reverse();
  const event = events.find((item) => (
    String(item.event || '') === 'workflow.run.approval_required'
    && timelineChildRunId(item)
  ));
  return event ? timelineChildRunId(event) : '';
}

function normalizeStudioTab(value: string): StudioTab {
  return studioRouteTabs.includes(value as StudioTab) ? value as StudioTab : 'agents';
}

function skillFolderNameError(name: string, folders: SkillFolderSpec[], currentFolderId = ''): string {
  const clean = name.trim();
  if (!clean) return '';
  if (clean.length > skillFolderNameMaxLength) return `文件夹名称不能超过 ${skillFolderNameMaxLength} 个字符`;
  const duplicate = folders.some((folder) => (
    folder.folder_id !== currentFolderId
    && folder.name.trim().toLowerCase() === clean.toLowerCase()
  ));
  return duplicate ? '已存在同名 Skill 文件夹' : '';
}

function AgentAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }) {
  return (
    <span className={avatarUrl ? 'agent-avatar has-image' : 'agent-avatar'} aria-hidden="true">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : agentInitial(name)}
    </span>
  );
}

export function AgentStudioView() {
  const routeRunId = currentParam('run').trim();
  const routeRunTarget = currentParam('target').trim();
  const routeRunGoal = currentParam('goal').trim();
  const routeTab = normalizeStudioTab(currentParam('tab'));
  const [tab, setTab] = useState<StudioTab>(() => routeRunId || routeRunTarget ? 'runs' : routeTab);
  const [agents, setAgents] = useState<AgentSpec[]>([]);
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [modelDefaults, setModelDefaults] = useState<ModelProfileDefaults>({});
  const [workflows, setWorkflows] = useState<WorkflowSpec[]>([]);
  const [runnables, setRunnables] = useState<RunnableSummary[]>([]);
  const [runs, setRuns] = useState<RunSpec[]>([]);
  const [runGroups, setRunGroups] = useState<RunGroupSpec[]>([]);
  const [runDetailCache, setRunDetailCache] = useState<RunSpec[]>([]);
  const [runEventReplayByRunId, setRunEventReplayByRunId] = useState<Record<string, RunEventReplayState>>({});
  const approvedApprovalGuardsRef = useRef<Map<string, ApprovedApprovalGuard>>(new Map());
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState('');
  const [selectedAgentIds, setSelectedAgentIds] = useState<string[]>([]);
  const [selectedSkillIds, setSelectedSkillIds] = useState<string[]>([]);
  const [selectedWorkflowIds, setSelectedWorkflowIds] = useState<string[]>([]);
  const [selectedRunIds, setSelectedRunIds] = useState<string[]>([]);
  const [agentManagementMode, setAgentManagementMode] = useState(false);
  const [skillManagementMode, setSkillManagementMode] = useState(false);
  const [workflowManagementMode, setWorkflowManagementMode] = useState(false);
  const [runHistoryManagementMode, setRunHistoryManagementMode] = useState(false);
  const [draft, setDraft] = useState<AgentDraft>(emptyAgentDraft);
  const [skillSources, setSkillSources] = useState<SkillSourceRoot[]>([]);
  const [skillFolders, setSkillFolders] = useState<SkillFolderSpec[]>([]);
  const [newSkillFolderName, setNewSkillFolderName] = useState('');
  const [editingSkillFolderId, setEditingSkillFolderId] = useState('');
  const [editingSkillFolderName, setEditingSkillFolderName] = useState('');
  const [skillFolderDeleteModes, setSkillFolderDeleteModes] = useState<Record<string, 'folder' | 'skills'>>({});
  const [skillTargetFolderId, setSkillTargetFolderId] = useState('');
  const [skillInstallCommand, setSkillInstallCommand] = useState('');
  const [skillImportResults, setSkillImportResults] = useState<SkillImportResult[]>([]);
  const [skillLibraryFilter, setSkillLibraryFilter] = useState<SkillSourceFilter>('installed');
  const [skillLibraryFolderFilter, setSkillLibraryFolderFilter] = useState<SkillFolderFilter>('all');
  const [skillLibrarySearch, setSkillLibrarySearch] = useState('');
  const [skillMountFilter, setSkillMountFilter] = useState<SkillSourceFilter>('installed');
  const [skillMountFolderFilter, setSkillMountFolderFilter] = useState<SkillFolderFilter>('all');
  const [skillMountSearch, setSkillMountSearch] = useState('');
  const [workflowName, setWorkflowName] = useState('New Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [workflowEnabled, setWorkflowEnabled] = useState(true);
  const [agentRunGoal, setAgentRunGoal] = useState('');
  const [workflowRunGoal, setWorkflowRunGoal] = useState('');
  const [runTarget, setRunTarget] = useState(() => routeRunTarget);
  const [runGoal, setRunGoal] = useState(() => routeRunGoal);
  const [runKindFilter, setRunKindFilter] = useState<RunKindFilter>('all');
  const [runStatusFilter, setRunStatusFilter] = useState<RunStatusFilter>('all');
  const [runSearchQuery, setRunSearchQuery] = useState('');
  const [collapsedRunHistoryGroups, setCollapsedRunHistoryGroups] = useState<Set<string>>(new Set());
  const [selectedRunId, setSelectedRunId] = useState(() => routeRunId);
  const [artifactPreview, setArtifactPreview] = useState<{ path: string; content: string; truncated?: boolean } | null>(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [confirmDialog, setConfirmDialog] = useState<ConfirmDialogState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(starterNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const busy = loading || Boolean(busyAction);
  const installingSkill = busyAction === '安装 Skill';
  const isSkillLibraryTab = tab === 'skills' || tab === 'skill-groups';

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === selectedAgentId) || null,
    [agents, selectedAgentId],
  );
  const selectedAgentReadOnly = Boolean(selectedAgent && (selectedAgent.system || selectedAgent.editable === false));
  const selectedAgentDeletable = Boolean(selectedAgent && !selectedAgent.system && selectedAgent.deletable !== false);
  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.workflow_id === selectedWorkflowId) || null,
    [workflows, selectedWorkflowId],
  );
  const agentIds = useMemo(
    () => agents.map((agent) => agent.agent_id).filter(Boolean),
    [agents],
  );
  const workflowIds = useMemo(
    () => workflows.map((workflow) => workflow.workflow_id).filter(Boolean),
    [workflows],
  );
  const selectedAgentIdSet = useMemo(() => new Set(selectedAgentIds), [selectedAgentIds]);
  const selectedWorkflowIdSet = useMemo(() => new Set(selectedWorkflowIds), [selectedWorkflowIds]);
  const selectedAgents = useMemo(
    () => agents.filter((agent) => selectedAgentIdSet.has(agent.agent_id)),
    [agents, selectedAgentIdSet],
  );
  const selectedDeletableAgents = useMemo(
    () => selectedAgents.filter((agent) => !agent.system && agent.deletable !== false),
    [selectedAgents],
  );
  const selectedWorkflows = useMemo(
    () => workflows.filter((workflow) => selectedWorkflowIdSet.has(workflow.workflow_id)),
    [workflows, selectedWorkflowIdSet],
  );
  const allAgentsSelected = agentIds.length > 0 && selectedAgents.length === agentIds.length;
  const allWorkflowsSelected = workflowIds.length > 0 && selectedWorkflows.length === workflowIds.length;
  const chatModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => profile.capability === 'chat' && profile.status === 'available' && profile.enabled !== false),
    [modelProfiles],
  );
  const visionModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => profile.capability === 'vision' && profile.status === 'available' && profile.enabled !== false),
    [modelProfiles],
  );
  const workflowValidation = useMemo(
    () => validateWorkflowDraft(nodes, edges, agents),
    [agents, edges, nodes],
  );
  const workflowNameError = workflowName.trim() ? '' : 'Workflow 名称不能为空';
  const workflowErrors = workflowNameError ? [workflowNameError, ...workflowValidation.errors] : workflowValidation.errors;
  const workflowRunPreviewSteps = useMemo(
    () => workflowSpecStepRefs({
      workflow_id: selectedWorkflow?.workflow_id || 'draft',
      name: workflowName.trim() || 'New Workflow',
      description: workflowDescription.trim(),
      nodes: workflowRequestNodes(nodes),
      edges: workflowRequestEdges(edges),
      enabled: true,
    }),
    [edges, nodes, selectedWorkflow?.workflow_id, workflowDescription, workflowName],
  );
  const workflowHasErrors = workflowErrors.length > 0;
  const workflowPrimaryError = workflowErrors[0] || '';
  const agentRunIssueById = useMemo(() => {
    const next = new Map<string, string>();
    agents.forEach((agent) => {
      const issue = agentRunReadinessIssue(agent, chatModelProfiles, modelDefaults, skills);
      if (issue) next.set(agent.agent_id, issue);
    });
    return next;
  }, [agents, chatModelProfiles, modelDefaults, skills]);
  const workflowRunAgentIssue = useMemo(
    () => workflowAgentRunReadinessIssue(nodes, agentRunIssueById),
    [agentRunIssueById, nodes],
  );
  const runById = useMemo(
    () => {
      const next = new Map<string, RunSpec>();
      runDetailCache.forEach((run) => next.set(run.run_id, run));
      runs.forEach((run) => next.set(run.run_id, run));
      return next;
    },
    [runDetailCache, runs],
  );
  const selectedRun = useMemo(
    () => selectedRunId ? runById.get(selectedRunId) || null : null,
    [runById, selectedRunId],
  );
  const selectedRunReplayState = useMemo(
    () => selectedRunId ? runEventReplayByRunId[selectedRunId] || null : null,
    [runEventReplayByRunId, selectedRunId],
  );
  const selectedRunReplayEvents = useMemo(
    () => selectedRunReplayState?.events || [],
    [selectedRunReplayState],
  );
  const selectedRunReplayHasMore = Boolean(selectedRunReplayState?.hasMore);
  const selectedRunReplayLoading = Boolean(selectedRunReplayState?.loading);
  const selectedRunReplayError = selectedRunReplayState?.error || '';
  const selectedRunExecutionEvents = useMemo(
    () => selectedRunReplayEvents.length
      ? selectedRunReplayEvents.map(runEventReplayToTimelineEvent)
      : selectedRun?.timeline || [],
    [selectedRun, selectedRunReplayEvents],
  );
  const selectedRunReplayRefreshKey = useMemo(
    () => selectedRunId
      ? [
          selectedRunId,
          selectedRun?.updated_at || '',
          selectedRun?.status || '',
          selectedRun?.timeline?.length || 0,
        ].join('|')
      : '',
    [selectedRun, selectedRunId],
  );
  const selectedRunTarget = useMemo(
    () => runTarget ? runnables.find((item) => item.id === runTarget) || null : null,
    [runTarget, runnables],
  );
  const selectedRunTargetWorkflow = useMemo(
    () => selectedRunTarget?.kind === 'workflow'
      ? workflows.find((workflow) => workflow.workflow_id === selectedRunTarget.id) || null
      : null,
    [selectedRunTarget, workflows],
  );
  const selectedRunTargetWorkflowNodes = useMemo(
    () => selectedRunTargetWorkflow ? workflowNodes(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowEdges = useMemo(
    () => selectedRunTargetWorkflow ? workflowEdges(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowPreviewSteps = useMemo(
    () => selectedRunTargetWorkflow ? workflowSpecStepRefs(selectedRunTargetWorkflow) : [],
    [selectedRunTargetWorkflow],
  );
  const selectedRunTargetWorkflowValidation = useMemo(
    () => selectedRunTargetWorkflow
      ? validateWorkflowDraft(selectedRunTargetWorkflowNodes, selectedRunTargetWorkflowEdges, agents)
      : { errors: [], warnings: [] },
    [agents, selectedRunTargetWorkflow, selectedRunTargetWorkflowEdges, selectedRunTargetWorkflowNodes],
  );
  const selectedRunTargetWorkflowAgentIssue = useMemo(
    () => selectedRunTargetWorkflow
      ? workflowAgentRunReadinessIssue(selectedRunTargetWorkflowNodes, agentRunIssueById)
      : '',
    [agentRunIssueById, selectedRunTargetWorkflow, selectedRunTargetWorkflowNodes],
  );
  const selectedRunTargetDisabled = selectedRunTarget?.enabled === false;
  const runTargetDisabledReason = useMemo(() => {
    if (!selectedRunTarget) return '';
    if (selectedRunTargetDisabled) return '目标已停用，无法运行。';
    if (selectedRunTarget.kind === 'agent') {
      const agent = agents.find((item) => item.agent_id === selectedRunTarget.id);
      if (!agent) return '找不到 Agent 定义，无法运行。';
      return agentRunIssueById.get(agent.agent_id) || '';
    }
    if (selectedRunTarget.kind === 'workflow') {
      if (!selectedRunTargetWorkflow) return '找不到 Workflow 定义，无法运行。';
      if (selectedRunTargetWorkflowValidation.errors.length) {
        return selectedRunTargetWorkflowValidation.errors[0] || '当前 Workflow 存在校验错误。';
      }
      if (!workflowHasRunnableSteps(selectedRunTargetWorkflowNodes)) {
        return workflowRunnableStepRequiredMessage;
      }
      if (selectedRunTargetWorkflowAgentIssue) return selectedRunTargetWorkflowAgentIssue;
    }
    return '';
  }, [agentRunIssueById, agents, selectedRunTarget, selectedRunTargetDisabled, selectedRunTargetWorkflow, selectedRunTargetWorkflowAgentIssue, selectedRunTargetWorkflowNodes, selectedRunTargetWorkflowValidation.errors]);
  const workflowRunDisabledReason = useMemo(() => {
    if (!workflowEnabled) return '当前 Workflow 已停用，无法运行。';
    if (workflowNameError) return workflowNameError;
    if (workflowHasErrors) return workflowPrimaryError || '当前 Workflow 存在校验错误。';
    if (!workflowRunGoal.trim()) return '请输入运行目标。';
    if (!workflowHasRunnableSteps(nodes)) return workflowRunnableStepRequiredMessage;
    if (workflowRunAgentIssue) return workflowRunAgentIssue;
    return '';
  }, [nodes, workflowEnabled, workflowHasErrors, workflowNameError, workflowPrimaryError, workflowRunAgentIssue, workflowRunGoal]);
  const workflowRunDisabled = busy || Boolean(workflowRunDisabledReason);
  const runFilterCounts = useMemo(
    () => ({
      all: runs.filter((run) => runMatchesFilter(run, 'all')).length,
      workflow: runs.filter((run) => runMatchesFilter(run, 'workflow')).length,
      agent: runs.filter((run) => runMatchesFilter(run, 'agent')).length,
    }),
    [runs],
  );
  const runKindFilteredRuns = useMemo(
    () => runs.filter((run) => runMatchesFilter(run, runKindFilter)),
    [runs, runKindFilter],
  );
  const runStatusFilterCounts = useMemo(
    () => ({
      all: runKindFilteredRuns.length,
      completed: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'completed')).length,
      failed: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'failed')).length,
      active: runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, 'active')).length,
    }),
    [runKindFilteredRuns],
  );
  const runStatusFilteredRuns = useMemo(
    () => runKindFilteredRuns.filter((run) => runMatchesStatusFilter(run, runStatusFilter)),
    [runKindFilteredRuns, runStatusFilter],
  );
  const runSearchActive = Boolean(runSearchQuery.trim());
  const runSearchTextByRunnableId = useMemo(
    () => runSearchTextByRunnableIdFor(runnables, agents, workflows),
    [agents, runnables, workflows],
  );
  const filteredRuns = useMemo(
    () => runStatusFilteredRuns.filter((run) => (
      runMatchesSearch(run, runSearchQuery, runSearchTextByRunnableId.get(run.runnable_id) || '')
    )),
    [runSearchQuery, runSearchTextByRunnableId, runStatusFilteredRuns],
  );
  const filteredRunIds = useMemo(
    () => filteredRuns.map((run) => run.run_id).filter(Boolean),
    [filteredRuns],
  );
  const selectedRunIdSet = useMemo(() => new Set(selectedRunIds), [selectedRunIds]);
  const selectedHistoryRuns = useMemo(
    () => filteredRuns.filter((run) => selectedRunIdSet.has(run.run_id)),
    [filteredRuns, selectedRunIdSet],
  );
  const selectedHistoryActiveRunCount = useMemo(
    () => selectedHistoryRuns.filter((run) => isActiveRunStatus(run.status)).length,
    [selectedHistoryRuns],
  );
  const runBulkDeleteDisabledReason = selectedHistoryActiveRunCount
    ? `有 ${selectedHistoryActiveRunCount} 个 Run 仍在进行中或待审批，请先取消或等待结束后再删除。`
    : '';
  const allHistoryRunsSelected = filteredRunIds.length > 0 && selectedHistoryRuns.length === filteredRunIds.length;
  const runHistoryGroups = useMemo(
    () => runHistoryGroupsFor(filteredRuns, runnables, agents),
    [agents, filteredRuns, runnables],
  );
  const selectedRunWorkflow = useMemo(
    () => (
      selectedRun?.kind === 'workflow_run'
        ? workflows.find((workflow) => workflow.workflow_id === selectedRun.runnable_id) || null
        : null
    ),
    [selectedRun, workflows],
  );
  const selectedWorkflowSteps = useMemo(
    () => workflowStepRefs(selectedRun, selectedRunWorkflow),
    [selectedRun, selectedRunWorkflow],
  );
  const selectedWorkflowChildRefs = useMemo(
    () => workflowChildRunRefs(selectedRun),
    [selectedRun],
  );
  const selectedWorkflowApprovalChildRunId = useMemo(
    () => workflowPendingApprovalChildRunId(selectedRun),
    [selectedRun],
  );
  const selectedWorkflowApprovalChildRun = selectedWorkflowApprovalChildRunId
    ? runById.get(selectedWorkflowApprovalChildRunId) || null
    : null;
  const selectedWorkflowApprovalStep = selectedWorkflowApprovalChildRunId
    ? selectedWorkflowSteps.find((step) => step.childRunId === selectedWorkflowApprovalChildRunId) || null
    : null;
  const selectedWorkflowParentRun = useMemo(() => {
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return null;
    const timelineParent = Array.from(runById.values()).find((run) => (
      run.kind === 'workflow_run'
      && run.run_group_id === selectedRun.run_group_id
      && workflowRunHasChildRun(run, selectedRun.run_id)
    ));
    if (timelineParent) return timelineParent;
    if (!isWorkflowChildAgentRun(selectedRun)) return null;
    return Array.from(runById.values()).find((run) => (
      run.kind === 'workflow_run'
      && run.run_group_id === selectedRun.run_group_id
    )) || null;
  }, [runById, selectedRun]);
  const selectedWorkflowParentRunId = useMemo(() => {
    if (selectedWorkflowParentRun) return selectedWorkflowParentRun.run_id;
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return '';
    const group = runGroups.find((item) => item.run_group_id === selectedRun.run_group_id);
    const childRunIds = group?.child_run_ids || [];
    return childRunIds.find((runId) => {
      const run = runById.get(runId);
      return run?.kind === 'workflow_run' && workflowRunHasChildRun(run, selectedRun.run_id);
    }) || childRunIds.find((runId) => runId.startsWith('workflow_run_')) || '';
  }, [runById, runGroups, selectedRun, selectedWorkflowParentRun]);
  const activeRunPollKey = useMemo(() => {
    const nextIds = new Set<string>();
    const maybeAdd = (runId: string) => {
      if (!runId) return;
      const run = runById.get(runId);
      if (!run || isActiveRunStatus(run.status)) nextIds.add(runId);
    };
    maybeAdd(selectedRunId);
    selectedWorkflowChildRefs.forEach((ref) => maybeAdd(ref.childRunId));
    maybeAdd(selectedWorkflowApprovalChildRunId);
    return Array.from(nextIds).sort().join('|');
  }, [runById, selectedRunId, selectedWorkflowApprovalChildRunId, selectedWorkflowChildRefs]);
  const selectedRunIsLive = Boolean(selectedRunId && activeRunPollKey.split('|').includes(selectedRunId));
  const selectedRunAvatarUrl = useMemo(() => {
    if (!selectedRun) return '';
    const runnable = runnables.find((item) => item.id === selectedRun.runnable_id);
    const agent = agents.find((item) => item.agent_id === selectedRun.runnable_id);
    return runnable?.avatar_url || agent?.avatar_url || '';
  }, [agents, runnables, selectedRun]);
  const selectedRunRerunTarget = useMemo(() => {
    if (!selectedRun) return null;
    const expectedKind = selectedRun.kind === 'workflow_run' ? 'workflow' : 'agent';
    return runnables.find((item) => item.id === selectedRun.runnable_id && item.kind === expectedKind) || null;
  }, [runnables, selectedRun]);
  const selectedRunRerunDisabledReason = useMemo(() => {
    if (!selectedRun) return '';
    if (isActiveRunStatus(selectedRun.status)) return '当前 Run 还在进行中，请完成、失败或取消后再重跑。';
    if (!selectedRun.user_goal?.trim()) return '原 Run 没有记录任务目标，无法直接重跑。';
    if (!selectedRunRerunTarget) return '找不到原 Run 对应的 Agent 或 Workflow，无法重跑。';
    if (selectedRunRerunTarget.enabled === false) return '原目标已停用，无法重跑。';
    if (selectedRunRerunTarget.kind === 'agent') {
      const agent = agents.find((item) => item.agent_id === selectedRunRerunTarget.id);
      if (!agent) return '找不到 Agent 定义，无法重跑。';
      return agentRunIssueById.get(agent.agent_id) || '';
    }
    const workflow = workflows.find((item) => item.workflow_id === selectedRunRerunTarget.id);
    if (!workflow) return '找不到 Workflow 定义，无法重跑。';
    const validation = validateWorkflowDraft(workflowNodes(workflow), workflowEdges(workflow), agents);
    if (validation.errors.length) return validation.errors[0] || '当前 Workflow 存在校验错误。';
    if (!workflowHasRunnableSteps(workflowNodes(workflow))) return workflowRunnableStepRequiredMessage;
    return workflowAgentRunReadinessIssue(workflowNodes(workflow), agentRunIssueById);
  }, [agentRunIssueById, agents, selectedRun, selectedRunRerunTarget, workflows]);
  const mountedSkillCount = useMemo(
    () => skills.filter((skill) => skill.enabled !== false && selectedAgent?.skill_ids?.includes(skill.skill_id)).length,
    [selectedAgent, skills],
  );
  const enabledSkills = useMemo(() => skills.filter((skill) => skill.enabled !== false), [skills]);
  const installedSkillCount = useMemo(() => skills.filter(isInstalledSkill).length, [skills]);
  const nativeSkillCount = useMemo(() => skills.filter(isNativeSkill).length, [skills]);
  const filteredLibrarySkills = useMemo(
    () => skills.filter((skill) => (
      skillMatchesSourceFilter(skill, skillLibraryFilter)
      && skillMatchesFolderFilter(skill, skillLibraryFolderFilter)
      && skillMatchesQuery(skill, skillLibrarySearch)
    )),
    [skills, skillLibraryFilter, skillLibraryFolderFilter, skillLibrarySearch],
  );
  const filteredLibrarySkillIds = useMemo(
    () => filteredLibrarySkills.map((skill) => skill.skill_id).filter(Boolean),
    [filteredLibrarySkills],
  );
  const selectedSkillIdSet = useMemo(() => new Set(selectedSkillIds), [selectedSkillIds]);
  const selectedLibrarySkills = useMemo(
    () => filteredLibrarySkills.filter((skill) => selectedSkillIdSet.has(skill.skill_id)),
    [filteredLibrarySkills, selectedSkillIdSet],
  );
  const allLibrarySkillsSelected = filteredLibrarySkillIds.length > 0 && selectedLibrarySkills.length === filteredLibrarySkillIds.length;
  const filteredMountSkills = useMemo(
    () => enabledSkills.filter((skill) => (
      skillMatchesSourceFilter(skill, skillMountFilter)
      && skillMatchesFolderFilter(skill, skillMountFolderFilter)
      && skillMatchesQuery(skill, skillMountSearch)
    )),
    [enabledSkills, skillMountFilter, skillMountFolderFilter, skillMountSearch],
  );
  const disabledMountedSkills = useMemo(
    () => skills.filter((skill) => skill.enabled === false && selectedAgent?.skill_ids?.includes(skill.skill_id)),
    [selectedAgent, skills],
  );
  const agentReadinessNotices = useMemo(() => {
    const notices: Array<{ tone: 'danger' | 'warn' | 'info'; text: string }> = [];
    const selectedProfileAvailable = draft.model_profile_id
      ? chatModelProfiles.some((profile) => profile.profile_id === draft.model_profile_id)
      : false;
    if (draft.model_mode === 'profile') {
      if (!draft.model_profile_id) {
        notices.push({ tone: 'danger', text: '尚未选择 Chat Profile；Agent Run 和 Workflow 节点运行前需要一个可用文本模型。' });
      } else if (!selectedProfileAvailable) {
        notices.push({ tone: 'danger', text: '当前 Chat Profile 不可用或已停用；请重新选择可用 Profile。' });
      }
    } else {
      if (!draft.base_url.trim() || !draft.model.trim()) {
        notices.push({ tone: 'danger', text: 'Custom API 需要 Base URL 和 Model，配置不完整时无法运行。' });
      }
      if (!draft.api_key.trim() && !selectedAgent?.model_config?.api_key_configured) {
        notices.push({ tone: 'danger', text: 'Custom API 尚未保存 API Key；请填写后保存，或切回 Chat Profile。' });
      }
    }
    if (disabledMountedSkills.length) {
      notices.push({ tone: 'danger', text: `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用；运行会被拦截。` });
    }
    if (draft.allow_workspace_write) {
      notices.push({
        tone: 'warn',
        text: draft.writable_scopes.trim()
          ? '`workspace.write_patch` 已启用；每次写文件都会先进入审批。'
          : draft.default_workdir.trim()
            ? '`workspace.write_patch` 已启用但 Writable Scopes 为空；写入会被工作区策略拒绝。'
            : '`workspace.write_patch` 已启用；保存后会自动分配独立工作目录，并允许在该目录内写入。',
      });
    }
    if (draft.allow_terminal) {
      notices.push({ tone: 'warn', text: '`terminal.run` 已启用；每次运行命令都会先进入审批。' });
    }
    if (!draft.allow_workspace_read && !draft.allow_workspace_write && !draft.allow_terminal && !draft.allow_artifacts) {
      notices.push({ tone: 'info', text: '当前 Agent 只会调用模型，不会获得工作区、命令或 artifact 工具。' });
    }
    return notices;
  }, [
    chatModelProfiles,
    disabledMountedSkills.length,
    draft.allow_artifacts,
    draft.allow_terminal,
    draft.allow_workspace_read,
    draft.allow_workspace_write,
    draft.api_key,
    draft.base_url,
    draft.model,
    draft.model_mode,
    draft.model_profile_id,
    draft.writable_scopes,
    selectedAgent,
  ]);
  const agentQuickRunDisabledReason = useMemo(() => {
    if (!draft.agent_id) return '请先保存 Agent，再运行。';
    if (selectedAgentReadOnly) return '系统 Agent 只能查看，不能从 Agent Studio 直接运行。';
    if (draft.enabled === false || selectedAgent?.enabled === false) return '当前 Agent 已停用，无法运行。';
    if (draft.model_mode === 'profile') {
      if (!draft.model_profile_id) return '请选择可用 Chat Profile 后再运行。';
      if (!chatModelProfiles.some((profile) => profile.profile_id === draft.model_profile_id)) return '当前 Chat Profile 不可用或已停用。';
    } else {
      if (!draft.base_url.trim() || !draft.model.trim()) return 'Custom API 配置不完整，请填写 Base URL 和 Model。';
      if (!draft.api_key.trim() && !selectedAgent?.model_config?.api_key_configured) return 'Custom API 尚未保存 API Key。';
    }
    if (disabledMountedSkills.length) return `有 ${disabledMountedSkills.length} 个已挂载 Skill 当前已停用，请先启用或卸载后再运行。`;
    if (!agentRunGoal.trim()) return '请输入运行目标。';
    return '';
  }, [
    agentRunGoal,
    chatModelProfiles,
    disabledMountedSkills.length,
    draft.agent_id,
    draft.api_key,
    draft.base_url,
    draft.enabled,
    draft.model,
    draft.model_mode,
    draft.model_profile_id,
    selectedAgent,
    selectedAgentReadOnly,
  ]);
  const agentQuickRunDisabled = busy || Boolean(agentQuickRunDisabledReason);
  const visibleMountSkillIds = useMemo(
    () => filteredMountSkills.map((skill) => skill.skill_id),
    [filteredMountSkills],
  );
  const visibleMountedCount = useMemo(
    () => visibleMountSkillIds.filter((skillId) => selectedAgent?.skill_ids?.includes(skillId)).length,
    [selectedAgent, visibleMountSkillIds],
  );
  const ungroupedSkillStats = useMemo(() => {
    const ungrouped = skills.filter((skill) => !skill.folder_id);
    return {
      total: ungrouped.length,
      installed: ungrouped.filter(isInstalledSkill).length,
      native: ungrouped.filter(isNativeSkill).length,
    };
  }, [skills]);
  const newSkillFolderError = useMemo(
    () => skillFolderNameError(newSkillFolderName, skillFolders),
    [newSkillFolderName, skillFolders],
  );
  const editingSkillFolderError = useMemo(
    () => skillFolderNameError(editingSkillFolderName, skillFolders, editingSkillFolderId),
    [editingSkillFolderId, editingSkillFolderName, skillFolders],
  );

  function rememberApprovedRun(run: RunSpec | null | undefined) {
    if (!run) return;
    approvedApprovalGuardsRef.current.set(run.run_id, {
      signature: runApprovalSignature(run),
      staleUntil: Date.now() + approvedApprovalStaleWindowMs,
    });
  }

  function shouldAcceptRunUpdate(run: RunSpec): boolean {
    const guard = approvedApprovalGuardsRef.current.get(run.run_id);
    if (!guard) return true;
    if (normalizeRunStatus(run.status) !== 'approval_required') {
      approvedApprovalGuardsRef.current.delete(run.run_id);
      return true;
    }
    const signature = runApprovalSignature(run);
    if (guard.signature && signature === guard.signature) return false;
    if (!guard.signature && Date.now() < guard.staleUntil) return false;
    approvedApprovalGuardsRef.current.delete(run.run_id);
    return true;
  }

  function acceptedRunUpdates(nextRuns: RunSpec[]): RunSpec[] {
    return nextRuns.filter((run) => shouldAcceptRunUpdate(run));
  }

  function upsertRunDetailCache(nextRuns: RunSpec[]) {
    const visibleRuns = acceptedRunUpdates(nextRuns);
    if (!visibleRuns.length) return;
    setRunDetailCache((current) => {
      const nextById = new Map(current.map((run) => [run.run_id, run]));
      visibleRuns.forEach((run) => nextById.set(run.run_id, run));
      return Array.from(nextById.values());
    });
    setRuns((current) => {
      const nextById = new Map(visibleRuns.map((run) => [run.run_id, run]));
      let changed = false;
      const merged = current.map((run) => {
        const next = nextById.get(run.run_id);
        if (!next) return run;
        changed = true;
        return next;
      });
      return changed ? merged : current;
    });
  }

  async function refreshRunGroupsForRuns(nextRuns: RunSpec[]) {
    const groupIds = Array.from(new Set(nextRuns.map((run) => String(run.run_group_id || '')).filter(Boolean)));
    if (!groupIds.length) return;
    const loadedGroups = (await Promise.all(groupIds.map((groupId) => getRunGroup(groupId).catch(() => null))))
      .filter((group): group is RunGroupSpec => Boolean(group));
    if (!loadedGroups.length) return;
    setRunGroups((current) => {
      const nextById = new Map(current.map((group) => [group.run_group_id, group]));
      loadedGroups.forEach((group) => nextById.set(group.run_group_id, group));
      return Array.from(nextById.values());
    });
  }

  function pruneDeletedRunState(deletedRunIds: Set<string>) {
    if (!deletedRunIds.size) return;
    setRuns((current) => current.filter((run) => !deletedRunIds.has(run.run_id)));
    setRunDetailCache((current) => current.filter((run) => !deletedRunIds.has(run.run_id)));
    setRunEventReplayByRunId((current) => {
      let changed = false;
      const next = { ...current };
      deletedRunIds.forEach((runId) => {
        if (Object.prototype.hasOwnProperty.call(next, runId)) {
          delete next[runId];
          changed = true;
        }
      });
      return changed ? next : current;
    });
    setRunGroups((current) => current.filter((group) => {
      const childRunIds = group.child_run_ids || [];
      return !childRunIds.length || childRunIds.some((runId) => !deletedRunIds.has(runId));
    }));
  }

  async function pollApprovedRunProgress(runId: string, selectedAfterAction: string) {
    const pollRunIds = Array.from(new Set([runId, selectedAfterAction].filter(Boolean)));
    if (!pollRunIds.length) return;
    for (let attempt = 0; attempt < runApprovalPollAttempts; attempt += 1) {
      await new Promise<void>((resolve) => {
        window.setTimeout(resolve, attempt === 0 ? 300 : runApprovalPollIntervalMs);
      });
      const loadedRuns = (await Promise.all(pollRunIds.map((id) => getRun(id).catch(() => null))))
        .filter((run): run is RunSpec => Boolean(run));
      const visibleRuns = acceptedRunUpdates(loadedRuns);
      if (!visibleRuns.length) continue;
      upsertRunDetailCache(visibleRuns);
      await refreshRunGroupsForRuns(visibleRuns);
      const approvedRun = visibleRuns.find((run) => run.run_id === runId) || null;
      const selectedRunUpdate = visibleRuns.find((run) => run.run_id === selectedAfterAction) || null;
      const watchedRun = selectedRunUpdate || approvedRun;
      if (!watchedRun) continue;
      const watchedStatus = normalizeRunStatus(watchedRun.status);
      if (watchedStatus === 'approval_required') {
        setStatus('Run 需要处理下一次审批。');
        await refresh({ selectedRunId: selectedAfterAction });
        return;
      }
      if (!isActiveRunStatus(watchedRun.status)) {
        setStatus(approvedRunStatusMessage(watchedRun));
        await refresh({ selectedRunId: selectedAfterAction });
        return;
      }
    }
    await refresh({ selectedRunId: selectedAfterAction });
  }

  const refresh = useCallback(async (options: StudioRefreshOptions = {}) => {
    const [nextAgents, nextSkills, nextProfiles, nextWorkflows, nextRunnables, nextRuns, nextRunGroups, nextSkillSources, nextSkillFolders] = await Promise.all([
      listAgents(),
      listSkills(),
      listModelProfiles(),
      listWorkflows(),
      listRunnables(),
      listRuns(),
      listRunGroups(),
      listSkillSources(),
      listSkillFolders(),
    ]);
    setAgents(nextAgents);
    setSkills(nextSkills);
    setSkillSources(nextSkillSources);
    setSkillFolders(nextSkillFolders);
    setModelProfiles(nextProfiles.profiles || []);
    setModelDefaults(nextProfiles.defaults || {});
    setWorkflows(nextWorkflows);
    setRunnables(nextRunnables);
    setRuns(nextRuns);
    setRunGroups(nextRunGroups);
    setSelectedAgentId((current) => {
      const desired = options.selectedAgentId !== undefined ? options.selectedAgentId : current;
      if (desired && nextAgents.some((agent) => agent.agent_id === desired)) return desired;
      return options.selectFirstAgent && nextAgents.length ? nextAgents[0].agent_id : '';
    });
    setSelectedWorkflowId((current) => {
      const desired = options.selectedWorkflowId !== undefined ? options.selectedWorkflowId : current;
      if (desired && nextWorkflows.some((workflow) => workflow.workflow_id === desired)) return desired;
      return options.selectFirstWorkflow && nextWorkflows.length ? nextWorkflows[0].workflow_id : '';
    });
    setRunTarget((current) => {
      const desired = options.runTarget !== undefined ? options.runTarget : current;
      if (desired && nextRunnables.some((item) => item.id === desired)) return desired;
      return '';
    });
    setSelectedRunId((current) => {
      const desired = options.selectedRunId !== undefined ? options.selectedRunId : current;
      if (desired) return desired;
      return '';
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    refresh()
      .then(() => setError(''))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '读取 Agent Studio 失败'))
      .finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    const nextTab = routeRunId || routeRunTarget ? 'runs' : routeTab;
    setTab((current) => current === nextTab ? current : nextTab);
    if (routeRunId) {
      setSelectedRunId((current) => current === routeRunId ? current : routeRunId);
    } else if (routeRunTarget) {
      setSelectedRunId('');
    } else if (routeTab === 'runs') {
      setSelectedRunId('');
    }
    if (routeRunTarget) {
      setRunTarget((current) => current === routeRunTarget ? current : routeRunTarget);
      setRunGoal((current) => current === routeRunGoal ? current : routeRunGoal);
    } else if (routeRunGoal) {
      setRunGoal((current) => current === routeRunGoal ? current : routeRunGoal);
    }
  }, [routeRunGoal, routeRunId, routeRunTarget, routeTab]);

  useEffect(() => {
    setSelectedAgentIds((current) => pruneSelectedIds(current, agentIds));
  }, [agentIds]);

  useEffect(() => {
    setSelectedSkillIds((current) => pruneSelectedIds(current, filteredLibrarySkillIds));
  }, [filteredLibrarySkillIds]);

  useEffect(() => {
    setSelectedWorkflowIds((current) => pruneSelectedIds(current, workflowIds));
  }, [workflowIds]);

  useEffect(() => {
    setSelectedRunIds((current) => pruneSelectedIds(current, filteredRunIds));
  }, [filteredRunIds]);

  useEffect(() => {
    if (selectedAgent) setDraft(agentToDraft(selectedAgent));
  }, [selectedAgent]);

  useEffect(() => {
    if (tab !== 'agents' || loading || busyAction || agents.length) return;
    if (!selectedAgentId && !draft.agent_id) return;
    let disposed = false;
    refresh()
      .then(() => {
        if (!disposed) setError('');
      })
      .catch((err: unknown) => {
        if (!disposed) setError(err instanceof Error ? err.message : '刷新 Agent 列表失败');
      });
    return () => {
      disposed = true;
    };
  }, [agents.length, busyAction, draft.agent_id, loading, refresh, selectedAgentId, tab]);

  useEffect(() => {
    if (!selectedRunId || selectedRun) return;
    let disposed = false;
    getRun(selectedRunId)
      .then((run) => {
        if (!disposed) upsertRunDetailCache([run]);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [selectedRun, selectedRunId]);

  useEffect(() => {
    if (!selectedRunId) return;
    let disposed = false;
    setRunEventReplayByRunId((current) => ({
      ...current,
      [selectedRunId]: {
        events: current[selectedRunId]?.events || [],
        limit: RUN_EVENT_REPLAY_PAGE_SIZE,
        hasMore: current[selectedRunId]?.hasMore || false,
        loading: true,
        error: '',
      },
    }));
    getRunEvents(selectedRunId, 0, RUN_EVENT_REPLAY_PAGE_SIZE)
      .then((page) => {
        if (!disposed) {
          const events = page.events || [];
          const limit = page.limit || RUN_EVENT_REPLAY_PAGE_SIZE;
          setRunEventReplayByRunId((current) => ({
            ...current,
            [selectedRunId]: {
              events,
              limit,
              hasMore: events.length >= limit,
              loading: false,
              error: '',
            },
          }));
        }
      })
      .catch((err: unknown) => {
        if (!disposed) {
          setRunEventReplayByRunId((current) => ({
            ...current,
            [selectedRunId]: {
              events: current[selectedRunId]?.events || [],
              limit: current[selectedRunId]?.limit || RUN_EVENT_REPLAY_PAGE_SIZE,
              hasMore: current[selectedRunId]?.hasMore || false,
              loading: false,
              error: err instanceof Error ? err.message : '读取 RunEvent replay 失败',
            },
          }));
        }
      });
    return () => {
      disposed = true;
    };
  }, [selectedRunId, selectedRunReplayRefreshKey]);

  useEffect(() => {
    if (!isPotentialWorkflowChildAgentRun(selectedRun)) return;
    const runGroupId = selectedRun.run_group_id || '';
    if (!runGroupId) return;
    if (runGroups.some((group) => group.run_group_id === runGroupId)) return;
    let disposed = false;
    getRunGroup(runGroupId)
      .then((group) => {
        if (disposed) return;
        setRunGroups((current) => {
          const nextById = new Map(current.map((item) => [item.run_group_id, item]));
          nextById.set(group.run_group_id, group);
          return Array.from(nextById.values());
        });
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [runGroups, selectedRun]);

  useEffect(() => {
    if (!selectedWorkflowParentRunId || runById.has(selectedWorkflowParentRunId)) return;
    let disposed = false;
    getRun(selectedWorkflowParentRunId)
      .then((run) => {
        if (!disposed) upsertRunDetailCache([run]);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [runById, selectedWorkflowParentRunId]);

  useEffect(() => {
    const childRunIds = [
      ...selectedWorkflowChildRefs.map((ref) => ref.childRunId),
      selectedWorkflowApprovalChildRunId,
    ].filter(Boolean);
    const uniqueChildRunIds = Array.from(new Set(childRunIds));
    if (!uniqueChildRunIds.length) return;
    let disposed = false;
    Promise.all(uniqueChildRunIds.map((runId) => getRun(runId).catch(() => null)))
      .then((childRuns) => {
        if (disposed) return;
        const loaded = childRuns.filter((run): run is RunSpec => Boolean(run));
        if (!loaded.length) return;
        upsertRunDetailCache(loaded);
      });
    return () => {
      disposed = true;
    };
  }, [selectedWorkflowApprovalChildRunId, selectedWorkflowChildRefs]);

  useEffect(() => {
    const pollRunIds = activeRunPollKey.split('|').filter(Boolean);
    if (!pollRunIds.length) return;
    let disposed = false;
    let inFlight = false;
    const pollRuns = async () => {
      if (inFlight) return;
      inFlight = true;
      try {
        const loadedRuns = (await Promise.all(pollRunIds.map((runId) => getRun(runId).catch(() => null))))
          .filter((run): run is RunSpec => Boolean(run));
        if (disposed || !loadedRuns.length) return;
        upsertRunDetailCache(loadedRuns);
        const groupIds = Array.from(new Set(loadedRuns.map((run) => String(run.run_group_id || '')).filter(Boolean)));
        const loadedGroups = (await Promise.all(groupIds.map((groupId) => getRunGroup(groupId).catch(() => null))))
          .filter((group): group is RunGroupSpec => Boolean(group));
        if (disposed || !loadedGroups.length) return;
        setRunGroups((current) => {
          const nextById = new Map(current.map((group) => [group.run_group_id, group]));
          loadedGroups.forEach((group) => nextById.set(group.run_group_id, group));
          return Array.from(nextById.values());
        });
      } finally {
        inFlight = false;
      }
    };
    void pollRuns();
    const timer = window.setInterval(() => {
      void pollRuns();
    }, 2500);
    return () => {
      disposed = true;
      window.clearInterval(timer);
    };
  }, [activeRunPollKey]);

  useEffect(() => {
    setArtifactPreview(null);
  }, [selectedRunId]);

  useEffect(() => {
    setNodes(workflowNodes(selectedWorkflow));
    setEdges(workflowEdges(selectedWorkflow));
    setWorkflowName(selectedWorkflow?.name || 'New Workflow');
    setWorkflowDescription(selectedWorkflow?.description || '');
    setWorkflowEnabled(selectedWorkflow?.enabled !== false);
  }, [selectedWorkflow, setEdges, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((current) => addEdge({ ...connection, id: `edge-${connection.source}-${connection.target}` }, current));
    },
    [setEdges],
  );

  function toggleAgentSelected(agentId: string) {
    setSelectedAgentIds((current) => toggleSelectedId(current, agentId));
  }

  function toggleSkillSelected(skillId: string) {
    setSelectedSkillIds((current) => toggleSelectedId(current, skillId));
  }

  function toggleWorkflowSelected(workflowId: string) {
    setSelectedWorkflowIds((current) => toggleSelectedId(current, workflowId));
  }

  function toggleRunSelected(runId: string) {
    setSelectedRunIds((current) => toggleSelectedId(current, runId));
  }

  function finishAgentManagement() {
    setAgentManagementMode(false);
    setSelectedAgentIds([]);
  }

  function finishSkillManagement() {
    setSkillManagementMode(false);
    setSelectedSkillIds([]);
  }

  function finishWorkflowManagement() {
    setWorkflowManagementMode(false);
    setSelectedWorkflowIds([]);
  }

  function finishRunHistoryManagement() {
    setRunHistoryManagementMode(false);
    setSelectedRunIds([]);
  }

  function startNewAgent() {
    setSelectedAgentId('');
    setDraft({ ...emptyAgentDraft });
    setStatus('正在编辑新的 Agent 草稿');
    setError('');
  }

  function selectAgent(agentId: string) {
    setSelectedAgentId(agentId);
    setStatus('');
    setError('');
  }

  function startNewWorkflow() {
    setSelectedWorkflowId('');
    setNodes(starterNodes);
    setEdges([]);
    setWorkflowName('New Workflow');
    setWorkflowDescription('');
    setWorkflowEnabled(true);
    setStatus('正在编辑新的 Workflow 草稿');
    setError('');
  }

  function loadPhase4WorkflowTemplate() {
    const nextNodes = buildPhase4WorkflowNodes(agents);
    const agentNodeCount = nextNodes.filter((node) => node.data?.kind === 'agent').length;
    if (!agentNodeCount) {
      setError('当前没有可用 Agent，无法生成全线测试模板。');
      return;
    }
    setSelectedWorkflowId('');
    setWorkflowName('Phase 4 Agent 全线流通测试');
    setWorkflowDescription('依次调用 Orchestrator、Research、Design、Coding、Review、Office，并写出最终 Artifact。');
    setWorkflowEnabled(true);
    setNodes(nextNodes);
    setEdges(linearEdgesForNodes(nextNodes));
    setStatus(`已生成全线测试模板：${agentNodeCount} 个启用 Agent 节点`);
    setError('');
  }

  function selectWorkflow(workflowId: string) {
    setSelectedWorkflowId(workflowId);
    setStatus('');
    setError('');
  }

  function openWorkflowDesign(workflowId: string) {
    const workflow = workflows.find((item) => item.workflow_id === workflowId);
    if (!workflow) {
      setError('找不到对应的 Workflow 定义，可能已被删除。');
      return;
    }
    setSelectedWorkflowId(workflow.workflow_id);
    setTab('workflows');
    setStatus(`已打开 Workflow Studio：${workflow.name || workflow.workflow_id}`);
    setError('');
    navigateTo('agents', { tab: 'workflows' }, ['run', 'target', 'goal']);
  }

  function activateTab(nextTab: StudioTab) {
    setTab(nextTab);
    setStatus('');
    setError('');
    navigateTo('agents', nextTab === 'agents' ? {} : { tab: nextTab }, ['run', 'tab', 'target', 'goal']);
    if (nextTab === 'agents') {
      void refresh().catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '刷新 Agent 列表失败');
      });
    }
  }

  function isTopTabActive(item: StudioTab): boolean {
    if (item === 'skills') return isSkillLibraryTab;
    return tab === item;
  }

  async function runAction(action: () => Promise<StudioRefreshOptions | void>, label: string) {
    setBusyAction(label);
    setStatus(`${label}...`);
    setError('');
    try {
      const refreshOptions = await action();
      if (!refreshOptions?.skipRefresh) {
        await refresh(refreshOptions || {});
      }
      setStatus(refreshOptions?.statusMessage || `${label} 完成`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} 失败`);
    } finally {
      setBusyAction('');
    }
  }

  async function pickSkillSources() {
    setError('');
    try {
      const selected = await chooseSkillSources();
      if (selected.length) await runAction(() => importSkillSourceList(selected), '导入 Skills');
    } catch (err) {
      setError(err instanceof Error ? err.message : '选择 Skill 文件失败');
    }
  }

  async function pickAgentAvatar() {
    setBusyAction('选择 Agent 头像');
    setError('');
    try {
      const selection = await chooseAvatarImage();
      const avatar = typeof selection === 'string' ? selection : selection?.data_url || selection?.path || '';
      if (avatar) {
        setDraft((current) => ({ ...current, avatar_url: avatar }));
        setStatus('已选择 Agent 头像');
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '选择 Agent 头像失败');
    } finally {
      setBusyAction('');
    }
  }

  function dropSkillSources(event: DragEvent<HTMLElement>) {
    event.preventDefault();
    const filePaths = Array.from(event.dataTransfer.files)
      .map((file) => (file as File & { path?: string }).path || file.name)
      .filter(Boolean);
    if (filePaths.length) {
      void runAction(() => importSkillSourceList(filePaths), '导入 Skills');
    }
  }

  async function importSkillSourceList(rawSources: string[]): Promise<StudioRefreshOptions | void> {
    const sources = normalizeSkillSources(rawSources);
    if (!sources.length) throw new Error('请先选择或拖入 Skill 目录/ZIP');
    const existingPaths = new Set(skills.flatMap((skill) => [skill.local_path, skill.source_path]).filter(Boolean).map(String));
    const results: SkillImportResult[] = [];
    for (const source of sources) {
      if (existingPaths.has(source) || existingPaths.has(localSourceAlias(source))) {
        results.push({ source, status: 'skipped', message: '已存在，跳过' });
        continue;
      }
      try {
        const imported = await importSkill(source, skillTargetFolderId);
        results.push({ source, status: 'success', message: `已导入 ${imported.name}` });
      } catch (err) {
        results.push({ source, status: 'failed', message: err instanceof Error ? err.message : '导入失败' });
      }
    }
    setSkillImportResults(results);
  }

  async function syncNativeSkillLibrary(): Promise<StudioRefreshOptions | void> {
    const result = await syncNativeSkills();
    setSkillImportResults(syncResultsToImportResults(result.results || []));
    if (result.roots) setSkillSources(result.roots);
  }

  async function installSkillFromCommand(): Promise<StudioRefreshOptions | void> {
    const command = skillInstallCommand.trim();
    if (!command) throw new Error('请输入 Skill 来源或安装命令');
    const result = await installSkillCommand(command, skillTargetFolderId);
    if (result.sync?.results) {
      setSkillImportResults(syncResultsToImportResults(result.sync.results));
    }
    if (!result.ok) {
      throw new Error(result.stderr || result.stdout || `安装命令退出：${result.returncode ?? 'unknown'}`);
    }
  }

  async function createSkillFolderFromDraft(): Promise<StudioRefreshOptions | void> {
    const name = newSkillFolderName.trim();
    if (!name) throw new Error('请输入 Skill 文件夹名称');
    const validation = skillFolderNameError(name, skillFolders);
    if (validation) throw new Error(validation);
    const folder = await createSkillFolder({ name });
    setNewSkillFolderName('');
    setSkillTargetFolderId(folder.folder_id);
    setSkillLibraryFolderFilter(folder.folder_id);
    setSkillMountFolderFilter(folder.folder_id);
  }

  function startEditingSkillFolder(folder: SkillFolderSpec) {
    setEditingSkillFolderId(folder.folder_id);
    setEditingSkillFolderName(folder.name);
    setStatus('');
    setError('');
  }

  function cancelEditingSkillFolder() {
    setEditingSkillFolderId('');
    setEditingSkillFolderName('');
  }

  async function updateSkillFolderFromDraft(folderId: string): Promise<StudioRefreshOptions | void> {
    const name = editingSkillFolderName.trim();
    if (!name) throw new Error('请输入 Skill 文件夹名称');
    const validation = skillFolderNameError(name, skillFolders, folderId);
    if (validation) throw new Error(validation);
    await updateSkillFolder(folderId, { name });
    cancelEditingSkillFolder();
  }

  async function deleteSkillFolderById(folderId: string, deleteSkills = false): Promise<StudioRefreshOptions | void> {
    await deleteSkillFolder(folderId, { deleteSkills });
    if (skillTargetFolderId === folderId) setSkillTargetFolderId('');
    if (skillLibraryFolderFilter === folderId) setSkillLibraryFolderFilter('all');
    if (skillMountFolderFilter === folderId) setSkillMountFolderFilter('all');
    if (editingSkillFolderId === folderId) cancelEditingSkillFolder();
    setSkillFolderDeleteMode(folderId, null);
  }

  function setSkillFolderDeleteMode(folderId: string, mode: 'folder' | 'skills' | null) {
    setSkillFolderDeleteModes((current) => {
      const next = { ...current };
      if (mode) next[folderId] = mode;
      else delete next[folderId];
      return next;
    });
  }

  function showConfirmDialog(nextConfirm: ConfirmDialogState) {
    setConfirmDialog(nextConfirm);
  }

  function closeConfirmDialog() {
    setConfirmDialog(null);
  }

  function confirmCurrentDialog() {
    const action = confirmDialog?.onConfirm;
    setConfirmDialog(null);
    if (action) action();
  }

  function requestDeleteAgent() {
    if (!draft.agent_id) return;
    if (!selectedAgentDeletable) {
      setStatus('系统 Agent 只能查看，不能删除。');
      return;
    }
    const agentId = draft.agent_id;
    const agentName = draft.name || selectedAgent?.name || 'Agent';
    showConfirmDialog({
      title: `删除「${agentName}」？`,
      description: '这个 Agent 的定义会从 Agent Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: '删除 Agent',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteAgent(agentId);
        setSelectedAgentIds((current) => current.filter((id) => id !== agentId));
        setSelectedAgentId('');
        setDraft({ ...emptyAgentDraft });
        return { selectedAgentId: '' };
      }, '删除 Agent'),
    });
  }

  function requestDeleteSelectedAgents() {
    const targets = selectedDeletableAgents.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((agent) => agent.agent_id));
    const deletingCurrent = Boolean(selectedAgentId && targetIds.has(selectedAgentId));
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Agent？`,
      description: '这些 Agent 的定义会从 Agent Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: `删除 ${targets.length} 个 Agent`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const agent of targets) {
          await deleteAgent(agent.agent_id);
        }
        setSelectedAgentIds((current) => current.filter((id) => !targetIds.has(id)));
        if (deletingCurrent) {
          setSelectedAgentId('');
          setDraft({ ...emptyAgentDraft });
          return { selectedAgentId: '' };
        }
        return undefined;
      }, '批量删除 Agent'),
    });
  }

  function requestDeleteSkill(skill: SkillSpec) {
    showConfirmDialog({
      title: `删除 Skill「${skill.name}」？`,
      description: isNativeSkill(skill)
        ? '这只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除 Native Skill Library 原始文件。'
        : 'Installed Skill 管理区里的本地 Skill 副本会被删除，已挂载它的 Agent 会失去这个 Skill。',
      confirmLabel: '删除 Skill',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteSkill(skill.skill_id);
        setSelectedSkillIds((current) => current.filter((id) => id !== skill.skill_id));
      }, '删除 Skill'),
    });
  }

  function requestDeleteSelectedSkills() {
    const targets = selectedLibrarySkills.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((skill) => skill.skill_id));
    const hasNativeSkills = targets.some(isNativeSkill);
    const hasInstalledSkills = targets.some(isInstalledSkill);
    const description = hasNativeSkills && hasInstalledSkills
      ? 'Installed Skill 管理区里的本地 Skill 副本会被删除；Native Skill 只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除原始文件。'
      : hasNativeSkills
        ? '这些 Native Skill 只会删除 Oha-Yachiyo 中的登记和挂载关系，不会删除原始文件。'
        : 'Installed Skill 管理区里的本地 Skill 副本会被删除，已挂载它们的 Agent 会失去这些 Skill。';
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Skill？`,
      description,
      confirmLabel: `删除 ${targets.length} 个 Skill`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const skill of targets) {
          await deleteSkill(skill.skill_id);
        }
        setSelectedSkillIds((current) => current.filter((id) => !targetIds.has(id)));
      }, '批量删除 Skill'),
    });
  }

  function requestDeleteWorkflow() {
    if (!selectedWorkflow) return;
    const workflowId = selectedWorkflow.workflow_id;
    const workflowName = selectedWorkflow.name || 'Workflow';
    showConfirmDialog({
      title: `删除「${workflowName}」？`,
      description: '这个 Workflow 定义会从 Workflow Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: '删除 Workflow',
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        await deleteWorkflow(workflowId);
        setSelectedWorkflowIds((current) => current.filter((id) => id !== workflowId));
        startNewWorkflow();
        return { selectedWorkflowId: '' };
      }, '删除 Workflow'),
    });
  }

  function requestDeleteSelectedWorkflows() {
    const targets = selectedWorkflows.slice();
    if (!targets.length) return;
    const targetIds = new Set(targets.map((workflow) => workflow.workflow_id));
    const deletingCurrent = Boolean(selectedWorkflowId && targetIds.has(selectedWorkflowId));
    showConfirmDialog({
      title: `删除 ${targets.length} 个 Workflow？`,
      description: '这些 Workflow 定义会从 Workflow Studio 移除；已生成的历史 Run 不会被删除。',
      confirmLabel: `删除 ${targets.length} 个 Workflow`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        for (const workflow of targets) {
          await deleteWorkflow(workflow.workflow_id);
        }
        setSelectedWorkflowIds((current) => current.filter((id) => !targetIds.has(id)));
        if (deletingCurrent) {
          startNewWorkflow();
          return { selectedWorkflowId: '' };
        }
        return undefined;
      }, '批量删除 Workflow'),
    });
  }

  function requestDeleteSelectedRuns() {
    const targets = selectedHistoryRuns.slice();
    if (!targets.length || selectedHistoryActiveRunCount) return;
    showConfirmDialog({
      title: `删除 ${targets.length} 条 Run History？`,
      description: '这些 Run 记录会从 Runs History 移除，对应 artifacts 也会删除；Workflow Run 会连带删除同一次 Workflow 的子 Agent Run。',
      confirmLabel: `删除 ${targets.length} 条记录`,
      variant: 'danger',
      onConfirm: () => void runAction(async () => {
        const deletedRunIds = new Set<string>();
        for (const run of targets) {
          const result = await deleteRun(run.run_id);
          const resultIds = Array.isArray(result.deleted_run_ids) ? result.deleted_run_ids : [run.run_id];
          resultIds.forEach((id) => {
            if (id) deletedRunIds.add(id);
          });
        }
        pruneDeletedRunState(deletedRunIds);
        setSelectedRunIds((current) => current.filter((id) => !deletedRunIds.has(id)));
        if (selectedRunId && deletedRunIds.has(selectedRunId)) {
          setSelectedRunId('');
          setArtifactPreview(null);
          navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
          return { selectedRunId: '' };
        }
        return undefined;
      }, '批量删除 Run History'),
    });
  }

  function requestDeleteSkillFolder(folder: SkillFolderSpec, deleteSkills: boolean) {
    const count = folder.skill_count || skills.filter((skill) => skill.folder_id === folder.folder_id).length;
    if (deleteSkills) {
      showConfirmDialog({
        title: `删除「${folder.name}」和其中 ${count} 个 Skill？`,
        description: 'Installed Skill 本地副本会被删除；Native Skill 只会删除 Oha-Yachiyo 的登记，不会删除原始文件。',
        confirmLabel: '连带删除',
        variant: 'danger',
        onConfirm: () => void runAction(
          async () => deleteSkillFolderById(folder.folder_id, true),
          '删除 Skill 文件夹和 Skills',
        ),
      });
      return;
    }
    showConfirmDialog({
      title: `删除文件夹「${folder.name}」？`,
      description: `${count} 个 Skill 会回到“无需分组”。`,
      confirmLabel: '删除文件夹',
      variant: 'danger',
      onConfirm: () => void runAction(
        async () => deleteSkillFolderById(folder.folder_id, false),
        '删除 Skill 文件夹',
      ),
    });
  }

  function openSkillLibraryFolder(folder: SkillFolderSpec) {
    setSkillTargetFolderId(folder.folder_id);
    setSkillLibraryFolderFilter(folder.folder_id);
    setTab('skills');
    navigateTo('agents', { tab: 'skills' }, ['run', 'tab']);
  }

  async function mountVisibleSkills(): Promise<StudioRefreshOptions | void> {
    if (!draft.agent_id || !selectedAgent) return;
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
      return;
    }
    const nextSkillIds = Array.from(new Set([...(selectedAgent.skill_ids || []), ...visibleMountSkillIds]));
    await updateAgent(draft.agent_id, { skill_ids: nextSkillIds });
  }

  async function unmountVisibleSkills(): Promise<StudioRefreshOptions | void> {
    if (!draft.agent_id || !selectedAgent) return;
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改 Skill 挂载。');
      return;
    }
    const visible = new Set(visibleMountSkillIds);
    const nextSkillIds = (selectedAgent.skill_ids || []).filter((skillId) => !visible.has(skillId));
    await updateAgent(draft.agent_id, { skill_ids: nextSkillIds });
  }

  async function saveAgent(): Promise<StudioRefreshOptions> {
    if (selectedAgentReadOnly) {
      setStatus('系统 Agent 只能查看，不能修改。');
      return { selectedAgentId };
    }
    const request: Partial<AgentSpec> = {
      name: draft.name,
      nickname: draft.nickname,
      description: draft.description,
      avatar_url: draft.avatar_url,
      category: draft.category,
      instructions: draft.instructions,
      persona_prompt: draft.persona_prompt,
      model_mode: draft.model_mode,
      model_profile_id: draft.model_mode === 'profile' ? draft.model_profile_id : '',
      vision_model_profile_id: draft.vision_model_profile_id,
      tool_policy: draftToolPolicy(draft),
      workspace_policy: {
        default_workdir: draft.default_workdir,
        readable_scopes: textToScopes(draft.readable_scopes),
        writable_scopes: textToScopes(draft.writable_scopes),
      },
      output_contract: draft.output_contract,
      enabled: draft.enabled,
    };
    if (draft.model_mode === 'custom_api') {
      request.model_config = {
        provider: 'openai_compatible',
        base_url: draft.base_url,
        model: draft.model,
        ...(draft.api_key.trim() ? { api_key: draft.api_key.trim() } : {}),
      };
    }
    const saved = draft.agent_id ? await updateAgent(draft.agent_id, request) : await createAgent(request);
    setSelectedAgentId(saved.agent_id);
    setDraft(agentToDraft(saved));
    return { selectedAgentId: saved.agent_id };
  }

  function workflowDraftRequest(): Partial<WorkflowSpec> {
    return {
      name: workflowName.trim(),
      description: workflowDescription.trim(),
      nodes: workflowRequestNodes(nodes),
      edges: workflowRequestEdges(edges),
      enabled: workflowEnabled,
    };
  }

  async function saveWorkflowDraft(): Promise<WorkflowSpec> {
    if (workflowErrors.length) {
      throw new Error(workflowErrors[0]);
    }
    const request = workflowDraftRequest();
    const saved = selectedWorkflow ? await updateWorkflow(selectedWorkflow.workflow_id, request) : await createWorkflow(request);
    setSelectedWorkflowId(saved.workflow_id);
    return saved;
  }

  async function saveWorkflow(): Promise<StudioRefreshOptions> {
    const saved = await saveWorkflowDraft();
    return { selectedWorkflowId: saved.workflow_id };
  }

  function openRunDetail(runId: string, options: { revealInHistory?: boolean } = {}) {
    if (options.revealInHistory) {
      setRunKindFilter('all');
      setRunStatusFilter('all');
      setRunSearchQuery('');
    }
    setSelectedRunId(runId);
    setTab('runs');
    const run = runs.find((item) => item.run_id === runId);
    if (run) {
      const groupKey = runHistoryGroupKey(run);
      setCollapsedRunHistoryGroups((current) => {
        if (!current.has(groupKey)) return current;
        const next = new Set(current);
        next.delete(groupKey);
        return next;
      });
    }
    navigateTo('agents', { run: runId }, ['tab', 'target', 'goal']);
  }

  function toggleRunHistoryGroup(groupKey: string) {
    setCollapsedRunHistoryGroups((current) => {
      const next = new Set(current);
      if (next.has(groupKey)) next.delete(groupKey);
      else next.add(groupKey);
      return next;
    });
  }

  function selectRunKindFilter(nextFilter: RunKindFilter) {
    setRunKindFilter(nextFilter);
    if (selectedRun && runMatchesFilter(selectedRun, nextFilter)) return;
    if (selectedRunId) {
      setSelectedRunId('');
      setTab('runs');
      navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
    }
  }

  function selectRunStatusFilter(nextFilter: RunStatusFilter) {
    setRunStatusFilter(nextFilter);
    if (selectedRun && runMatchesStatusFilter(selectedRun, nextFilter)) return;
    if (selectedRunId) {
      setSelectedRunId('');
      setTab('runs');
      navigateTo('agents', { tab: 'runs' }, ['run', 'target', 'goal']);
    }
  }

  async function runCurrentAgent(): Promise<StudioRefreshOptions> {
    if (agentQuickRunDisabledReason) throw new Error(agentQuickRunDisabledReason);
    const agentId = draft.agent_id || '';
    const goal = agentRunGoal.trim();
    const run = await createAgentRun(agentId, goal);
    setAgentRunGoal('');
    setRunTarget(agentId);
    openRunDetail(run.run_id, { revealInHistory: true });
    return { selectedAgentId: agentId, runTarget: agentId, selectedRunId: run.run_id };
  }

  async function runCurrentWorkflow(): Promise<StudioRefreshOptions> {
    if (workflowRunDisabledReason) throw new Error(workflowRunDisabledReason);
    const goal = workflowRunGoal.trim();
    const saved = await saveWorkflowDraft();
    const run = await createWorkflowRun(saved.workflow_id, goal);
    setWorkflowRunGoal('');
    setRunTarget(saved.workflow_id);
    openRunDetail(run.run_id, { revealInHistory: true });
    return { selectedWorkflowId: saved.workflow_id, runTarget: saved.workflow_id, selectedRunId: run.run_id };
  }

  function prepareSelectedRunRerun() {
    if (!selectedRun) return;
    if (!selectedRunRerunTarget) {
      setError('找不到原 Run 对应的 Agent 或 Workflow，无法准备重跑。');
      return;
    }
    setRunTarget(selectedRunRerunTarget.id);
    setRunGoal(selectedRun.user_goal || '');
    setStatus(`已把「${selectedRunRerunTarget.name || selectedRun.runnable_name || selectedRun.runnable_id}」和原任务填回 Run 面板。`);
    setError('');
  }

  async function rerunSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择要重跑的 Run');
    if (selectedRunRerunDisabledReason) throw new Error(selectedRunRerunDisabledReason);
    if (!selectedRunRerunTarget) throw new Error('找不到原 Run 对应的 Agent 或 Workflow，无法重跑。');
    const run = await rerunRun(selectedRun.run_id);
    upsertRunDetailCache([run]);
    await refreshRunGroupsForRuns([run]);
    openRunDetail(run.run_id, { revealInHistory: true });
    if (selectedRunRerunTarget.kind === 'agent') {
      return {
        selectedAgentId: selectedRunRerunTarget.id,
        selectedRunId: run.run_id,
        runTarget: selectedRunRerunTarget.id,
        statusMessage: '已按原任务重新运行 Agent。',
      };
    }
    return {
      selectedWorkflowId: selectedRunRerunTarget.id,
      selectedRunId: run.run_id,
      runTarget: selectedRunRerunTarget.id,
      statusMessage: '已按原任务重新运行 Workflow。',
    };
  }

  function addFlowNode(kind: 'agent' | 'approval' | 'artifact', agentId = '') {
    const agent = agentId
      ? agents.find((candidate) => candidate.agent_id === agentId)
      : undefined;
    const nodeSeed = kind === 'agent'
      ? `${kind}-${agent?.agent_id || Date.now().toString(36)}`
      : `${kind}-${Date.now().toString(36)}`;
    const id = uniqueWorkflowNodeId(nodeSeed, nodes);
    const sourceId = terminalNodeId(nodes, edges);
    const nextNode: Node = {
      id,
      type: kind === 'artifact' ? 'output' : 'default',
      position: { x: 120 + nodes.length * 180, y: 140 },
      data: {
        label: kind === 'agent' ? agent?.name || '选择 Agent' : kind === 'approval' ? '人工审批' : 'Artifact',
        kind,
        ...(kind === 'agent' && agent ? { agent_id: agent.agent_id } : {}),
      },
    };
    setNodes((current) => [...current, nextNode]);
    if (sourceId) {
      setEdges((current) => [
        ...current,
        {
          id: `edge-${sourceId}-${id}`,
          source: sourceId,
          target: id,
        },
      ]);
    }
  }

  function removeFlowNode(nodeId: string) {
    if (nodeId === 'start') return;
    const incoming = edges.find((edge) => edge.target === nodeId);
    const outgoing = edges.find((edge) => edge.source === nodeId);
    setNodes((current) => current.filter((node) => node.id !== nodeId));
    setEdges((current) => {
      const nextEdges = current.filter((edge) => edge.source !== nodeId && edge.target !== nodeId);
      if (incoming?.source && outgoing?.target && incoming.source !== outgoing.target) {
        nextEdges.push({
          id: `edge-${incoming.source}-${outgoing.target}`,
          source: incoming.source,
          target: outgoing.target,
        });
      }
      return nextEdges;
    });
  }

  async function openArtifact(run: RunSpec | string, path: string) {
    const runId = typeof run === 'string' ? run : run.run_id;
    setStatus('读取 artifact...');
    setError('');
    try {
      const payload = await getRunArtifact(runId, path);
      setArtifactPreview({
        path: payload.path || path,
        content: payload.content || '',
        truncated: payload.truncated,
      });
      setStatus('Artifact 已读取');
    } catch (err) {
      setError(err instanceof Error ? err.message : '读取 artifact 失败');
    }
  }

  async function loadMoreSelectedRunEvents() {
    if (!selectedRunId) return;
    const currentState = runEventReplayByRunId[selectedRunId];
    const currentEvents = currentState?.events || [];
    const afterSequence = currentEvents.reduce((max, event) => Math.max(max, Number(event.sequence) || 0), 0);
    setRunEventReplayByRunId((current) => ({
      ...current,
      [selectedRunId]: {
        events: current[selectedRunId]?.events || currentEvents,
        limit: current[selectedRunId]?.limit || RUN_EVENT_REPLAY_PAGE_SIZE,
        hasMore: current[selectedRunId]?.hasMore ?? true,
        loading: true,
        error: '',
      },
    }));
    try {
      const page = await getRunEvents(selectedRunId, afterSequence, RUN_EVENT_REPLAY_PAGE_SIZE);
      const incomingEvents = page.events || [];
      const limit = page.limit || RUN_EVENT_REPLAY_PAGE_SIZE;
      setRunEventReplayByRunId((current) => {
        const previous = current[selectedRunId];
        const events = mergeRunEventReplayPages(previous?.events || currentEvents, incomingEvents);
        return {
          ...current,
          [selectedRunId]: {
            events,
            limit,
            hasMore: incomingEvents.length >= limit,
            loading: false,
            error: '',
          },
        };
      });
      setStatus(incomingEvents.length ? `已加载 ${incomingEvents.length} 条 RunEvent replay` : '没有更多 RunEvent replay');
    } catch (err) {
      setRunEventReplayByRunId((current) => ({
        ...current,
        [selectedRunId]: {
          events: current[selectedRunId]?.events || currentEvents,
          limit: current[selectedRunId]?.limit || RUN_EVENT_REPLAY_PAGE_SIZE,
          hasMore: current[selectedRunId]?.hasMore ?? true,
          loading: false,
          error: err instanceof Error ? err.message : '读取更多 RunEvent replay 失败',
        },
      }));
    }
  }

  async function approveRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions> {
    if (!runId) throw new Error('请选择待审批 Run');
    const selectedAfterAction = nextSelectedRunId || runId;
    const currentRun = runById.get(runId) || null;
    const selectedAfterRun = selectedAfterAction !== runId ? runById.get(selectedAfterAction) || null : null;
    const optimisticRuns = [
      currentRun ? makeRunContinuingAfterApproval(currentRun, '已批准，Run 正在继续执行。') : null,
      selectedAfterRun && isActiveRunStatus(selectedAfterRun.status)
        ? makeRunContinuingAfterApproval(selectedAfterRun, '已批准子 Agent，Workflow 正在继续执行。')
        : null,
    ].filter((run): run is RunSpec => Boolean(run));
    upsertRunDetailCache(optimisticRuns);
    rememberApprovedRun(currentRun);
    rememberApprovedRun(selectedAfterRun);
    setSelectedRunId(selectedAfterAction);
    const approvalRequest = approveRunApproval(runId);
    void pollApprovedRunProgress(runId, selectedAfterAction).catch((err: unknown) => {
      setError(err instanceof Error ? err.message : '刷新审批后的 Run 进度失败');
    });
    void approvalRequest
      .then(async (run) => {
        const updatedRuns = [run];
        if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
          try {
            updatedRuns.push(await getRun(nextSelectedRunId));
          } catch {
            // The background polling path will retry; approval already succeeded.
          }
        }
        upsertRunDetailCache(updatedRuns);
        await refreshRunGroupsForRuns(updatedRuns);
        setSelectedRunId(selectedAfterAction);
        setStatus(approvedRunStatusMessage(run));
      })
      .catch((err: unknown) => {
        setError(err instanceof Error ? err.message : '批准 Run 审批失败');
        void refresh({ selectedRunId: selectedAfterAction }).catch(() => undefined);
      });
    return {
      selectedRunId: selectedAfterAction,
      statusMessage: '已批准，Run 正在继续执行。',
      skipRefresh: true,
    };
  }

  async function rejectRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions> {
    if (!runId) throw new Error('请选择待审批 Run');
    const run = await rejectRunApproval(runId);
    const selectedAfterAction = nextSelectedRunId || run.run_id;
    const updatedRuns = [run];
    if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
      try {
        updatedRuns.push(await getRun(nextSelectedRunId));
      } catch {
        // The normal refresh/polling path will retry; rejection already succeeded.
      }
    }
    upsertRunDetailCache(updatedRuns);
    setSelectedRunId(selectedAfterAction);
    return { selectedRunId: selectedAfterAction, statusMessage: '已拒绝，Run 已终止。' };
  }

  async function approveSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择待审批 Run');
    return approveRunById(selectedRun.run_id);
  }

  async function rejectSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择待审批 Run');
    return rejectRunById(selectedRun.run_id);
  }

  async function cancelRunById(runId: string, nextSelectedRunId?: string): Promise<StudioRefreshOptions> {
    if (!runId) throw new Error('请选择要取消的 Run');
    const currentRun = runById.get(runId) || null;
    if (currentRun && !isActiveRunStatus(currentRun.status)) throw new Error('只能取消进行中或待审批的 Run');
    const run = await cancelRun(runId);
    const selectedAfterAction = nextSelectedRunId || run.run_id;
    const updatedRuns = [run];
    if (nextSelectedRunId && nextSelectedRunId !== run.run_id) {
      try {
        updatedRuns.push(await getRun(nextSelectedRunId));
      } catch {
        // The normal refresh/polling path will retry; cancellation already succeeded.
      }
    }
    upsertRunDetailCache(updatedRuns);
    await refreshRunGroupsForRuns(updatedRuns);
    setSelectedRunId(selectedAfterAction);
    return {
      selectedRunId: selectedAfterAction,
      statusMessage: nextSelectedRunId ? '已取消子 Run，Workflow 已终止。' : 'Run 已取消。',
    };
  }

  async function cancelSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择要取消的 Run');
    return cancelRunById(selectedRun.run_id);
  }

  function requestCancelSelectedRun() {
    if (!selectedRun || !isActiveRunStatus(selectedRun.status)) return;
    const runName = selectedRun.runnable_name || selectedRun.runnable_id || 'Run';
    showConfirmDialog({
      title: `取消「${runName}」？`,
      description: '这会终止当前进行中或待审批的 Run；如果它正在等待审批，待审批请求也会被清空。',
      confirmLabel: '取消 Run',
      variant: 'danger',
      onConfirm: () => void runAction(cancelSelectedRun, '取消 Run'),
    });
  }

  return (
    <section className="agent-studio-page hy-route-page">
      <header className="agent-studio-hero">
        <button type="button" className="page-back-link" onClick={() => void openAppView('main')}>← 返回主控台</button>
        <div>
          <span className="section-eyebrow">Agent Runtime</span>
          <h1>Agent Studio</h1>
          <p>创建可配置 Agent，导入本地 Skills，并用线性 Workflow 把多个 Agent 编排成可运行链路。</p>
        </div>
      </header>

      <div className="agent-studio-tabs" role="tablist" aria-label="Agent Studio">
        {studioTabs.map((item) => (
          <button
            type="button"
            className={isTopTabActive(item) ? 'active' : ''}
            key={item}
            onClick={() => activateTab(item)}
          >
            {item === 'agents' ? 'Agents' : item === 'skills' ? 'Skill Library' : item === 'workflows' ? 'Workflow Studio' : 'Runs'}
          </button>
        ))}
      </div>

      {loading ? <AgentStudioLoadingState /> : null}
      {status ? <div className="notice">{status}</div> : null}
      {error ? <div className="notice danger">{error}</div> : null}

      {!loading && isSkillLibraryTab ? (
        <div className="skill-library-subnav" role="tablist" aria-label="Skill Library">
          <button type="button" className={tab === 'skills' ? 'active' : ''} onClick={() => activateTab('skills')}>Skills 列表</button>
          <button type="button" className={tab === 'skill-groups' ? 'active' : ''} onClick={() => activateTab('skill-groups')}>分组管理</button>
        </div>
      ) : null}

      {!loading && tab === 'agents' ? (
        <section className="agent-studio-grid" data-testid="agent-studio-agents">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Agents</h2>
              <div className="studio-heading-actions">
                {agents.length && !agentManagementMode ? (
                  <button type="button" disabled={busy} onClick={() => setAgentManagementMode(true)}>管理</button>
                ) : null}
                <button type="button" data-testid="agent-new" disabled={busy} onClick={startNewAgent}>新建</button>
              </div>
            </div>
            {agents.length && agentManagementMode ? (
              <div className="studio-bulk-actions" aria-label="Agent 批量操作">
                <span>{selectedAgents.length ? `已选择 ${selectedAgents.length} / ${agents.length}` : `${agents.length} agents`}</span>
                <button type="button" disabled={busy} onClick={() => setSelectedAgentIds(allAgentsSelected ? [] : agentIds)}>
                  {allAgentsSelected ? '取消全选' : '全选当前列表'}
                </button>
                <button type="button" disabled={busy || !selectedAgents.length} onClick={() => setSelectedAgentIds([])}>清空</button>
                <button type="button" className="danger-action" disabled={busy || !selectedDeletableAgents.length} onClick={requestDeleteSelectedAgents}>删除所选</button>
                <button type="button" disabled={busy} onClick={finishAgentManagement}>完成</button>
              </div>
            ) : null}
            <div className={agentManagementMode ? 'agent-list managing' : 'agent-list'} data-testid="agent-list">
              {agents.map((agent) => (
                <div
                  className={agent.agent_id === selectedAgentId ? 'agent-list-item active' : 'agent-list-item'}
                  data-agent-id={agent.agent_id}
                  data-testid="agent-list-item"
                  key={agent.agent_id}
                >
                  <label className="agent-list-select" aria-label={`选择 Agent ${agent.nickname || agent.name}`}>
                    <input
                      type="checkbox"
                      checked={selectedAgentIdSet.has(agent.agent_id)}
                      disabled={busy || !agentManagementMode}
                      onChange={() => toggleAgentSelected(agent.agent_id)}
                    />
                  </label>
                  <button
                    type="button"
                    className="agent-list-main"
                    data-testid="agent-list-open"
                    onClick={() => selectAgent(agent.agent_id)}
                  >
                    <span className="agent-list-profile">
                      <AgentAvatar avatarUrl={agent.avatar_url} name={agent.nickname || agent.name} />
                      <span>
                        <strong className="agent-list-name">{agent.nickname || agent.name}</strong>
                        <small className="agent-list-base-name">{agent.name}</small>
                      </span>
                    </span>
                    <span className="agent-list-meta">
                      <span className="agent-list-category">{agent.category || 'custom'}</span>
                      <span className="agent-list-separator">·</span>
                      <span className="agent-list-profile-type">{agent.model_mode === 'custom_api' ? 'Custom API' : 'Chat Profile'}</span>
                    </span>
                  </button>
                </div>
              ))}
              {!agents.length ? <span className="agent-empty-inline">暂无 Agent。点击“新建”创建一个 Agent。</span> : null}
            </div>
          </aside>
          <form className="agent-studio-panel agent-editor" data-testid="agent-editor" onSubmit={(event) => { event.preventDefault(); void runAction(saveAgent, '保存 Agent'); }}>
            <div className="section-heading-row">
              <h2>{draft.agent_id ? '编辑 Agent' : '新建 Agent'}</h2>
              {draft.agent_id && selectedAgentDeletable ? <button type="button" className="danger-action" data-testid="agent-delete" disabled={busy} onClick={requestDeleteAgent}>删除</button> : null}
            </div>
            {selectedAgentReadOnly ? <div className="agent-inline-note">系统 Agent 由 oha-yachiyo 管理，可查看但不能编辑、删除或直接挂载 Skill。</div> : null}
            <div className="agent-profile-editor">
              <AgentAvatar avatarUrl={draft.avatar_url} name={draft.nickname || draft.name || 'Agent'} />
              <div className="agent-profile-fields">
                <div className="agent-form-row">
                  <label><span>Name</span><input className="hy-input" data-testid="agent-name-input" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label>
                  <label><span>Nickname</span><input className="hy-input" data-testid="agent-nickname-input" value={draft.nickname} onChange={(event) => setDraft({ ...draft, nickname: event.target.value })} placeholder="对话框里显示的称呼" /></label>
                </div>
                <div className="agent-avatar-picker-row">
                  <div>
                    <span>Avatar</span>
                    <strong>{draft.avatar_url ? '已选择自定义头像' : '使用首字母头像'}</strong>
                  </div>
                  <div className="agent-avatar-picker-actions">
                    <button type="button" className="hy-btn hy-btn-ghost" data-testid="agent-avatar-select" disabled={busy} onClick={() => void pickAgentAvatar()}>选择头像</button>
                    {draft.avatar_url ? (
                      <button type="button" className="hy-btn hy-btn-ghost" data-testid="agent-avatar-clear" disabled={busy} onClick={() => setDraft({ ...draft, avatar_url: '' })}>清除</button>
                    ) : null}
                  </div>
                </div>
                <label><span>Description</span><input className="hy-input" data-testid="agent-description-input" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
              </div>
            </div>
            <div className="agent-form-row">
              <label><span>Category</span><input className="hy-input" data-testid="agent-category-input" value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })} /></label>
              <label>
                <span>Output Contract</span>
                <select className="hy-select" data-testid="agent-output-contract-select" value={draft.output_contract} onChange={(event) => setDraft({ ...draft, output_contract: event.target.value })}>
                  <option value="chat">chat</option>
                  <option value="markdown">markdown</option>
                  <option value="diff">diff</option>
                  <option value="report">report</option>
                  <option value="artifacts">artifacts</option>
                </select>
                <small className="agent-field-help">约束最终交付形态；diff 不会自动写工作区，artifacts 会优先提示可保存产物。</small>
              </label>
            </div>
            <label>
              <span>Functional Instructions</span>
              <textarea className="hy-input agent-textarea" data-testid="agent-instructions-input" value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} />
              <small className="agent-field-help">写任务边界、工作方法、必须遵守的功能要求。</small>
            </label>
            <label>
              <span>Personal Prompt</span>
              <textarea className="hy-input agent-textarea compact" data-testid="agent-persona-input" value={draft.persona_prompt} onChange={(event) => setDraft({ ...draft, persona_prompt: event.target.value })} />
              <small className="agent-field-help">写人设、口吻、角色偏好；运行时会和功能要求分段放进 Agent context。</small>
            </label>
            <section className="agent-backend-section" aria-label="Model">
              <div className="section-heading-row compact">
                <h3>Model</h3>
              </div>
              <div className="agent-backend-fields">
                <label>
                  <span>Chat Profile</span>
                  <select
                    className="hy-select"
                    disabled={draft.model_mode === 'custom_api'}
                    value={draft.model_profile_id}
                    onChange={(event) => setDraft({ ...draft, model_profile_id: event.target.value })}
                  >
                    <option value="">选择已保存模型组</option>
                    {chatModelProfiles.map((profile) => (
                      <option key={profile.profile_id} value={profile.profile_id}>
                        {profile.name} · {profile.model || profile.provider}
                      </option>
                    ))}
                  </select>
                </label>
                <label className="agent-checkbox-row">
                  <input
                    type="checkbox"
                    checked={draft.model_mode === 'custom_api'}
                    onChange={(event) => setDraft({ ...draft, model_mode: event.target.checked ? 'custom_api' : 'profile' })}
                  />
                  <span>Custom API</span>
                </label>
              </div>
            </section>
            {!chatModelProfiles.length ? (
              <div className="notice">还没有可用的文本模型组。请先在模型配置页面新建并测试。</div>
            ) : null}
            <div className="agent-form-row">
              <label>
                <span>Vision Profile</span>
                <select className="hy-select" value={draft.vision_model_profile_id} onChange={(event) => setDraft({ ...draft, vision_model_profile_id: event.target.value })}>
                  <option value="">跟随全局图片识别</option>
                  {visionModelProfiles.map((profile) => (
                    <option key={profile.profile_id} value={profile.profile_id}>
                      {profile.name} · {profile.model || profile.provider}
                    </option>
                  ))}
                </select>
              </label>
              <label><span>模型配置</span><button type="button" className="hy-btn hy-btn-ghost" onClick={() => openAppView('provider')}>管理 Profile</button></label>
            </div>
            {!visionModelProfiles.length ? (
              <div className="notice">还没有可用的图片识别模型组。需要图片能力时，请先在模型配置页面创建 vision Profile。</div>
            ) : null}
            {draft.model_mode === 'custom_api' ? (
              <div className="agent-config-box">
                <label><span>Model</span><input className="hy-input" value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} placeholder="gpt-4.1-mini" /></label>
                <label><span>Base URL</span><input className="hy-input" value={draft.base_url} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} placeholder="https://api.example.com/v1" /></label>
                <label><span>API Key</span><input className="hy-input" type="password" value={draft.api_key} onChange={(event) => setDraft({ ...draft, api_key: event.target.value })} placeholder={selectedAgent?.model_config.api_key_configured ? '已配置，留空不覆盖' : '保存到后端'} /></label>
              </div>
            ) : null}
            <section className="agent-capability-box" aria-label="Capabilities">
              <div className="section-heading-row compact">
                <h3>Capabilities</h3>
              </div>
              <p className="agent-section-help">这里会实际写入 ToolBroker 允许工具；写文件和运行命令即使开启，也仍然需要 Run 审批。</p>
              <div className="agent-capability-grid">
                <label className="agent-checkbox-row">
                  <input type="checkbox" checked={draft.allow_workspace_read} onChange={(event) => setDraft({ ...draft, allow_workspace_read: event.target.checked })} />
                  <span>Read workspace</span>
                </label>
                <label className="agent-checkbox-row">
                  <input type="checkbox" checked={draft.allow_workspace_write} onChange={(event) => setDraft({ ...draft, allow_workspace_write: event.target.checked, allow_workspace_read: event.target.checked ? true : draft.allow_workspace_read })} />
                  <span>Write files</span>
                </label>
                <label className="agent-checkbox-row">
                  <input type="checkbox" checked={draft.allow_terminal} onChange={(event) => setDraft({ ...draft, allow_terminal: event.target.checked })} />
                  <span>Run commands</span>
                </label>
                <label className="agent-checkbox-row">
                  <input type="checkbox" checked={draft.allow_artifacts} onChange={(event) => setDraft({ ...draft, allow_artifacts: event.target.checked })} />
                  <span>Write artifacts</span>
                </label>
              </div>
              {agentReadinessNotices.length ? (
                <div className="agent-readiness-list" aria-label="Agent 运行状态">
                  {agentReadinessNotices.map((notice) => (
                    <span className={notice.tone} key={notice.text}>{notice.text}</span>
                  ))}
                </div>
              ) : null}
            </section>
            <div className="agent-form-row">
              <label>
                <span>Default Workdir</span>
                <input className="hy-input" value={draft.default_workdir} onChange={(event) => setDraft({ ...draft, default_workdir: event.target.value })} placeholder="保存后自动分配独立目录" />
                <small className="agent-field-help">工具相对路径的基准目录；留空时保存后自动分配到 Yachiyo 的 Agent 工作区。</small>
              </label>
              <label>
                <span>Writable Scopes</span>
                <input className="hy-input" value={draft.writable_scopes} onChange={(event) => setDraft({ ...draft, writable_scopes: event.target.value })} placeholder="src, tests" />
                <small className="agent-field-help">允许 `workspace.write_patch` 写入的相对目录，逗号分隔。</small>
              </label>
            </div>
            <label>
              <span>Readable Scopes</span>
              <input className="hy-input" value={draft.readable_scopes} onChange={(event) => setDraft({ ...draft, readable_scopes: event.target.value })} />
              <small className="agent-field-help">允许 `workspace.list/read` 访问的相对目录，默认 `.` 表示工作区内可读。</small>
            </label>
            <div className="agent-inline-note">可行性验证：保存后先用“测试模型”检查模型连接，再用 Quick Run 做端到端验证；工具权限和 scopes 会在运行时强制校验。</div>
            <div className="agent-editor-actions">
              <button type="submit" className="primary-action" data-testid="agent-save" disabled={busy || selectedAgentReadOnly}>保存 Agent</button>
              {draft.agent_id ? <button type="button" disabled={busy || selectedAgentReadOnly} onClick={() => void runAction(async () => { const result = await testAgentModel(draft.agent_id || ''); setStatus(result.message || (result.ok ? '模型测试通过' : '模型测试失败')); }, '测试模型')}>测试模型</button> : null}
            </div>
            {draft.agent_id ? (
              <section className="agent-quick-run">
                <div>
                  <h3>Quick Run</h3>
                  <p>用当前 Agent 立即创建 Run，完成后自动打开 Runs 详情。</p>
                </div>
                <label>
                  <span>Goal</span>
                  <textarea
                    className="hy-input agent-run-textarea"
                    value={agentRunGoal}
                    onChange={(event) => setAgentRunGoal(event.target.value)}
                    placeholder="例如：检查这个页面还有哪些交互缺口"
                  />
                </label>
                {agentQuickRunDisabledReason && agentRunGoal.trim() ? (
                  <div className="agent-inline-note warn">{agentQuickRunDisabledReason}</div>
                ) : null}
                <button
                  type="button"
                  className="primary-action"
                  disabled={agentQuickRunDisabled}
                  title={agentQuickRunDisabledReason || undefined}
                  onClick={() => void runAction(runCurrentAgent, '运行 Agent')}
                >
                  运行当前 Agent
                </button>
              </section>
            ) : (
              <div className="agent-inline-note">保存 Agent 后即可在这里直接运行，并在 Runs 中查看结果和 artifacts。</div>
            )}
            {draft.agent_id ? (
              <div className="agent-skill-mounts" data-testid="agent-skill-mounts">
                <div className="agent-skill-mounts-head">
                  <h3>Mounted Skills</h3>
                  <span data-testid="agent-skill-mount-summary">{mountedSkillCount} mounted / {filteredMountSkills.length} visible skills</span>
                </div>
                {disabledMountedSkills.length ? (
                  <div className="agent-inline-note warn">
                    有 {disabledMountedSkills.length} 个已挂载 Skill 当前已停用，运行时不会通过校验。
                  </div>
                ) : null}
                <div className="skill-filter-bar">
                  <div className="skill-filter-tabs">
                    <button type="button" data-testid="agent-skill-mount-filter-installed" className={skillMountFilter === 'installed' ? 'active' : ''} onClick={() => setSkillMountFilter('installed')}>Installed</button>
                    <button type="button" data-testid="agent-skill-mount-filter-native" className={skillMountFilter === 'native' ? 'active' : ''} onClick={() => setSkillMountFilter('native')}>Native</button>
                  </div>
                  <select
                    className="hy-select"
                    data-testid="agent-skill-mount-folder-filter"
                    value={skillMountFolderFilter}
                    onChange={(event) => setSkillMountFolderFilter(event.target.value)}
                  >
                    <option value="all">全部文件夹</option>
                    <option value="uncategorized">无需分组</option>
                    {skillFolders.map((folder) => (
                      <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
                    ))}
                  </select>
                  <input
                    className="hy-input"
                    data-testid="agent-skill-mount-search"
                    value={skillMountSearch}
                    onChange={(event) => setSkillMountSearch(event.target.value)}
                    placeholder="搜索可挂载 Skills"
                  />
                </div>
                <div className="agent-skill-bulk-actions">
                  <span data-testid="agent-skill-mount-visible-count">{visibleMountedCount} / {filteredMountSkills.length} 当前筛选已挂载</span>
                  <button
                    type="button"
                    data-testid="agent-skill-mount-all-visible"
                    disabled={busy || selectedAgentReadOnly || !filteredMountSkills.length || visibleMountedCount === filteredMountSkills.length}
                    onClick={() => void runAction(mountVisibleSkills, '挂载当前筛选 Skills')}
                  >
                    全选当前筛选
                  </button>
                  <button
                    type="button"
                    data-testid="agent-skill-unmount-all-visible"
                    disabled={busy || selectedAgentReadOnly || !visibleMountedCount}
                    onClick={() => void runAction(unmountVisibleSkills, '移除当前筛选 Skills')}
                  >
                    清空当前筛选
                  </button>
                </div>
                <div className="agent-skill-grid" data-testid="agent-skill-mount-grid">
                  {filteredMountSkills.map((skill) => {
                    const mounted = selectedAgent?.skill_ids?.includes(skill.skill_id);
                    return (
                      <button
                        type="button"
                        className={mounted ? 'active' : ''}
                        data-skill-id={skill.skill_id}
                        data-skill-mounted={mounted ? 'true' : 'false'}
                        data-testid="agent-skill-mount-item"
                        key={skill.skill_id}
                        onClick={() => void runAction(async () => {
                          if (!draft.agent_id) return;
                          if (mounted) await detachSkill(draft.agent_id, skill.skill_id);
                          else await attachSkill(draft.agent_id, skill.skill_id);
                        }, mounted ? '移除 Skill' : '挂载 Skill')}
                      >
                        {skill.name}
                      </button>
                    );
                  })}
                  {!filteredMountSkills.length ? <span className="agent-empty-inline">当前筛选下没有可挂载 Skill。</span> : null}
                </div>
              </div>
            ) : null}
          </form>
        </section>
      ) : null}

      {!loading && tab === 'skills' ? (
        <section className="agent-studio-grid" data-testid="skill-library">
          <div className="agent-studio-panel skill-import-panel" data-testid="skill-import-panel">
            <div className="section-heading-row">
              <h2>Installed Skills</h2>
            </div>
            <p className="agent-section-help">从安装命令或上传入口导入的 Skills 会进入 Installed Skill 管理区；它们和 Native Skill Library 分开展示和挂载。</p>
            <div className="skill-import-target">
              <label>
                <span>导入到文件夹</span>
                <select className="hy-select" data-testid="skill-import-folder-select" value={skillTargetFolderId} onChange={(event) => setSkillTargetFolderId(event.target.value)}>
                  <option value="">无需分组</option>
                  {skillFolders.map((folder) => (
                    <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
                  ))}
                </select>
              </label>
              <small>需要新增、重命名或删除文件夹时，进入上方“分组管理”。</small>
            </div>
            <div className="skill-install-box">
              <label>
                <span>Skill 来源或安装命令</span>
                <input
                  className="hy-input"
                  data-testid="skill-install-command-input"
                  value={skillInstallCommand}
                  onChange={(event) => setSkillInstallCommand(event.target.value)}
                  placeholder="owner/repo --skill skill-name 或 skills@latest add owner/repo"
                />
              </label>
              {installingSkill ? (
                <div className="skill-install-progress" role="progressbar" aria-label="Skill 安装进度">
                  <span />
                </div>
              ) : null}
              <button type="button" data-testid="skill-install-command-submit" disabled={busy || !skillInstallCommand.trim()} onClick={() => void runAction(installSkillFromCommand, '安装 Skill')}>
                {installingSkill ? '安装中...' : '安装并同步'}
              </button>
              <small>可以直接输入 Skill 来源，也可以输入 <code>skills@latest add ...</code> 或 <code>npx skills add ...</code>。Oha-Yachiyo 会固定使用 <code>oha-yachiyo</code> 目标并补上 <code>--copy -y</code>，在 Installed Skill 工作区执行，不写入 Native 全局库。</small>
            </div>
            <div className="section-heading-row"><h2>上传 Skills</h2></div>
            <p className="agent-section-help">支持批量上传 zip 技能包，也支持选择本地 Skill 目录；导入后会复制到 Installed Skill 管理区。</p>
            <div className="skill-import-hints">
              <span>一次上传多个 zip</span>
              <span>自动校验 SKILL.md</span>
              <span>跳过重复选择</span>
            </div>
            <div
              className="skill-drop-zone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={dropSkillSources}
            >
              <strong>拖拽 Skill 目录或 zip 到这里</strong>
              <span>也可以点击选择文件，选择后会立即校验并导入</span>
              <button type="button" data-testid="skill-source-picker" disabled={busy} onClick={() => void pickSkillSources()}>上传 Skills</button>
            </div>
            <div className="section-heading-row">
              <h2>Native Skill Library</h2>
              <button type="button" data-testid="skill-native-sync" disabled={busy} onClick={() => void runAction(syncNativeSkillLibrary, '同步 Native Skills')}>从 Native Library 同步</button>
            </div>
            <p className="agent-section-help">Native Skill Library 的 `~/.oha-yachiyo/skill-library/skills` 只登记引用，不复制到 Installed Skill 管理区；项目级 Skills 暂不纳入本页管理。</p>
            <div className="skill-source-roots">
              {skillSources.map((source) => (
                <div className={source.exists ? 'skill-source-root' : 'skill-source-root missing'} data-testid="skill-source-root" key={`${source.source_type}-${source.path}`}>
                  <strong>{skillSourceTypeLabel(source.source_type)}</strong>
                  <span>{source.skill_count || 0} skills</span>
                  <code>{source.path}</code>
                </div>
              ))}
              {!skillSources.length ? <div className="empty-state inline-empty">暂未检测到 Native skills root。</div> : null}
            </div>
            {skillImportResults.length ? (
              <div className="skill-import-results" aria-label="Skill import results" data-testid="skill-import-results">
                {skillImportResults.map((result) => (
                  <div className={`skill-import-result ${result.status}`} data-testid="skill-import-result" key={`${result.source}-${result.status}`}>
                    <strong>{skillResultStatusLabel(result.status)}</strong>
                    <span>{result.source}</span>
                    <small>{result.message}</small>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="agent-studio-panel" data-testid="skill-library-panel">
            <div className="section-heading-row">
              <h2>{skillLibraryFilter === 'native' ? 'Native Skill Library' : 'Installed Skill Library'}</h2>
              <div className="studio-heading-actions">
                <span className="agent-section-count">{installedSkillCount} Installed / {nativeSkillCount} Native</span>
                {filteredLibrarySkills.length && !skillManagementMode ? (
                  <button type="button" disabled={busy} onClick={() => setSkillManagementMode(true)}>管理</button>
                ) : null}
              </div>
            </div>
            <div className="skill-filter-bar">
              <div className="skill-filter-tabs">
                <button type="button" data-testid="skill-filter-installed" className={skillLibraryFilter === 'installed' ? 'active' : ''} onClick={() => setSkillLibraryFilter('installed')}>Installed</button>
                <button type="button" data-testid="skill-filter-native" className={skillLibraryFilter === 'native' ? 'active' : ''} onClick={() => setSkillLibraryFilter('native')}>Native</button>
              </div>
              <select
                className="hy-select"
                data-testid="skill-library-folder-filter"
                value={skillLibraryFolderFilter}
                onChange={(event) => setSkillLibraryFolderFilter(event.target.value)}
              >
                <option value="all">全部文件夹</option>
                <option value="uncategorized">无需分组</option>
                {skillFolders.map((folder) => (
                  <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
                ))}
              </select>
              <input
                className="hy-input"
                data-testid="skill-library-search"
                value={skillLibrarySearch}
                onChange={(event) => setSkillLibrarySearch(event.target.value)}
                placeholder="搜索 Skill 名称、路径或摘要"
              />
            </div>
            {filteredLibrarySkills.length && skillManagementMode ? (
              <div className="studio-bulk-actions" aria-label="Skill 批量操作">
                <span>{selectedLibrarySkills.length ? `已选择 ${selectedLibrarySkills.length} / ${filteredLibrarySkills.length}` : `${filteredLibrarySkills.length} skills`}</span>
                <button type="button" disabled={busy} onClick={() => setSelectedSkillIds(allLibrarySkillsSelected ? [] : filteredLibrarySkillIds)}>
                  {allLibrarySkillsSelected ? '取消全选' : '全选当前列表'}
                </button>
                <button type="button" disabled={busy || !selectedLibrarySkills.length} onClick={() => setSelectedSkillIds([])}>清空</button>
                <button type="button" className="danger-action" disabled={busy || !selectedLibrarySkills.length} onClick={requestDeleteSelectedSkills}>删除所选</button>
                <button type="button" disabled={busy} onClick={finishSkillManagement}>完成</button>
              </div>
            ) : null}
            <div className="skill-list" data-testid="skill-list">
              {filteredLibrarySkills.map((skill) => (
                <SkillCard
                  busy={busy}
                  folders={skillFolders}
                  key={skill.skill_id}
                  onDelete={() => requestDeleteSkill(skill)}
                  onMoveFolder={(folderId) => runAction(async () => { await updateSkill(skill.skill_id, { folder_id: folderId }); }, '移动 Skill')}
                  onOpenLocation={() => runAction(async () => { await openPath(skill.local_path || ''); }, '打开 Skill 路径')}
                  onSelectionChange={() => toggleSkillSelected(skill.skill_id)}
                  onToggleEnabled={() => runAction(async () => { await updateSkill(skill.skill_id, { enabled: skill.enabled === false }); }, skill.enabled === false ? '启用 Skill' : '停用 Skill')}
                  managing={skillManagementMode}
                  selected={selectedSkillIdSet.has(skill.skill_id)}
                  skill={skill}
                />
              ))}
              {!filteredLibrarySkills.length ? <div className="empty-state inline-empty">当前分类或搜索下没有 Skill。</div> : null}
            </div>
          </div>
        </section>
      ) : null}

      {!loading && tab === 'skill-groups' ? (
        <section className="agent-studio-grid skill-group-page" data-testid="skill-folder-page">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Skill 分组</h2>
            </div>
            <p className="agent-section-help">文件夹只用于筛选、导入目标和 Agent 挂载选择，不会移动 Native Skill Library 原始路径。</p>
            <div className="skill-folder-box">
              <div className="section-heading-row compact">
                <h3>新建文件夹</h3>
              </div>
              <div className="skill-folder-create">
                <input
                  className="hy-input"
                  data-testid="skill-folder-name-input"
                  maxLength={skillFolderNameMaxLength + 1}
                  value={newSkillFolderName}
                  onChange={(event) => setNewSkillFolderName(event.target.value)}
                  placeholder="例如 Laravel / Design"
                />
                <button type="button" data-testid="skill-folder-create" disabled={busy || !newSkillFolderName.trim() || Boolean(newSkillFolderError)} onClick={() => void runAction(createSkillFolderFromDraft, '创建 Skill 文件夹')}>新建</button>
              </div>
              {newSkillFolderError ? <small className="skill-folder-validation">{newSkillFolderError}</small> : null}
            </div>
            <div className="skill-folder-system-row">
              <strong>无需分组</strong>
              <div className="skill-folder-meta">
                <span>{ungroupedSkillStats.total} skills</span>
                <span>{ungroupedSkillStats.installed} Installed</span>
                <span>{ungroupedSkillStats.native} Native</span>
              </div>
              <small>默认分组，不能删除；删除其他文件夹后 Skill 会回到这里。</small>
            </div>
          </aside>
          <div className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>文件夹管理</h2>
              <span className="agent-section-count">{skillFolders.length} folders</span>
            </div>
            <div className="skill-folder-manager-list" data-testid="skill-folder-list">
              {skillFolders.map((folder) => {
                const editing = editingSkillFolderId === folder.folder_id;
                const deleteMode = skillFolderDeleteModes[folder.folder_id] || 'folder';
                const deleteWithSkills = deleteMode === 'skills' && Boolean(folder.skill_count || 0);
                return (
                  <article
                    className="skill-folder-manager-row"
                    data-folder-id={folder.folder_id}
                    data-folder-name={folder.name}
                    data-testid="skill-folder-row"
                    key={folder.folder_id}
                  >
                    <div className="skill-folder-manager-main">
                      {editing ? (
                        <input
                          className="hy-input"
                          data-testid="skill-folder-edit-name-input"
                          maxLength={skillFolderNameMaxLength + 1}
                          value={editingSkillFolderName}
                          onChange={(event) => setEditingSkillFolderName(event.target.value)}
                          autoFocus
                        />
                      ) : (
                        <>
                          <h3>{folder.name}</h3>
                          <div className="skill-folder-meta">
                            <span>{folder.skill_count || 0} skills</span>
                            <span>{folder.installed_count || 0} Installed</span>
                            <span>{folder.native_count || 0} Native</span>
                          </div>
                        </>
                      )}
                    </div>
                    <div className="skill-folder-actions">
                      {editing ? (
                        <>
                          <button type="button" data-testid="skill-folder-save-rename" disabled={busy || !editingSkillFolderName.trim() || Boolean(editingSkillFolderError)} onClick={() => void runAction(async () => updateSkillFolderFromDraft(folder.folder_id), '重命名 Skill 文件夹')}>保存</button>
                          <button type="button" data-testid="skill-folder-cancel-rename" disabled={busy} onClick={cancelEditingSkillFolder}>取消</button>
                        </>
                      ) : (
                        <>
                          <button type="button" data-testid="skill-folder-rename" disabled={busy} onClick={() => startEditingSkillFolder(folder)}>重命名</button>
                          <button type="button" data-testid="skill-folder-open" disabled={busy} onClick={() => openSkillLibraryFolder(folder)}>查看</button>
                          <div className="skill-folder-delete-control" aria-label={`${folder.name} 删除设置`}>
                            <label className="skill-folder-delete-switch" title="开启后删除文件夹时会连带删除其中 Skills">
                              <input
                                type="checkbox"
                                data-testid="skill-folder-delete-with-skills"
                                role="switch"
                                checked={deleteWithSkills}
                                disabled={busy || !(folder.skill_count || 0)}
                                aria-label={`${folder.name} 删除时连带删除 Skills`}
                                onChange={(event) => setSkillFolderDeleteMode(folder.folder_id, event.currentTarget.checked ? 'skills' : 'folder')}
                              />
                              <span className="skill-folder-delete-toggle" aria-hidden="true" />
                              <span>连带 Skills</span>
                            </label>
                            <button
                              type="button"
                              className="danger-action"
                              data-testid="skill-folder-delete"
                              disabled={busy}
                              onClick={() => requestDeleteSkillFolder(folder, deleteWithSkills)}
                            >
                              删除
                            </button>
                          </div>
                        </>
                      )}
                    </div>
                    {editing && editingSkillFolderError ? <small className="skill-folder-validation">{editingSkillFolderError}</small> : null}
                  </article>
                );
              })}
              {!skillFolders.length ? (
                <div className="empty-state inline-empty skill-folder-empty-state">
                  <strong>暂无自定义文件夹</strong>
                  <span>现有 Skill 会继续显示在“无需分组”里。</span>
                </div>
              ) : null}
            </div>
          </div>
        </section>
      ) : null}

      {!loading && tab === 'workflows' ? (
        <section className="agent-studio-grid workflow-studio-grid" data-testid="workflow-studio">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Workflows</h2>
              <div className="studio-heading-actions">
                {workflows.length && !workflowManagementMode ? (
                  <button type="button" data-testid="workflow-list-manage" disabled={busy} onClick={() => setWorkflowManagementMode(true)}>管理</button>
                ) : null}
                <button type="button" data-testid="workflow-new" disabled={busy} onClick={startNewWorkflow}>新建</button>
              </div>
            </div>
            {workflows.length && workflowManagementMode ? (
              <div className="studio-bulk-actions" aria-label="Workflow 批量操作" data-testid="workflow-bulk-actions">
                <span>{selectedWorkflows.length ? `已选择 ${selectedWorkflows.length} / ${workflows.length}` : `${workflows.length} workflows`}</span>
                <button type="button" data-testid="workflow-select-all" disabled={busy} onClick={() => setSelectedWorkflowIds(allWorkflowsSelected ? [] : workflowIds)}>
                  {allWorkflowsSelected ? '取消全选' : '全选当前列表'}
                </button>
                <button type="button" data-testid="workflow-clear-selection" disabled={busy || !selectedWorkflows.length} onClick={() => setSelectedWorkflowIds([])}>清空</button>
                <button type="button" className="danger-action" data-testid="workflow-delete-selected" disabled={busy || !selectedWorkflows.length} onClick={requestDeleteSelectedWorkflows}>删除所选</button>
                <button type="button" data-testid="workflow-finish-management" disabled={busy} onClick={finishWorkflowManagement}>完成</button>
              </div>
            ) : null}
            <div className={workflowManagementMode ? 'agent-list managing' : 'agent-list'} data-testid="workflow-list">
              {workflows.map((workflow) => (
                <div
                  className={workflow.workflow_id === selectedWorkflowId ? 'agent-list-item active' : 'agent-list-item'}
                  data-testid="workflow-list-item"
                  key={workflow.workflow_id}
                >
                  <label className="agent-list-select" aria-label={`选择 Workflow ${workflow.name}`}>
                    <input
                      type="checkbox"
                      data-testid="workflow-list-checkbox"
                      checked={selectedWorkflowIdSet.has(workflow.workflow_id)}
                      disabled={busy || !workflowManagementMode}
                      onChange={() => toggleWorkflowSelected(workflow.workflow_id)}
                    />
                  </label>
                  <button
                    type="button"
                    className="agent-list-main"
                    data-testid="workflow-list-open"
                    onClick={() => selectWorkflow(workflow.workflow_id)}
                  >
                    <strong>{workflow.name}</strong>
                    <span>{workflow.enabled === false ? '停用 · ' : ''}{workflow.nodes.length} nodes · {workflow.edges.length} edges</span>
                  </button>
                </div>
              ))}
            </div>
          </aside>
          <div className="agent-studio-panel workflow-editor" data-testid="workflow-editor">
            <div className="workflow-toolbar" data-testid="workflow-toolbar">
              <input className="hy-input" data-testid="workflow-name-input" value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} />
              <input className="hy-input" data-testid="workflow-description-input" value={workflowDescription} onChange={(event) => setWorkflowDescription(event.target.value)} placeholder="Description" />
              <label className="agent-checkbox-row workflow-enabled-toggle" data-testid="workflow-enabled-toggle">
                <input
                  type="checkbox"
                  checked={workflowEnabled}
                  onChange={(event) => setWorkflowEnabled(event.target.checked)}
                />
                <span>启用</span>
              </label>
              <button
                type="button"
                className="workflow-template-action"
                data-testid="workflow-template-button"
                disabled={busy || !agents.some((agent) => agent.enabled !== false)}
                onClick={loadPhase4WorkflowTemplate}
              >
                全线测试模板
              </button>
              <button type="button" data-testid="workflow-add-agent-node" disabled={busy} onClick={() => addFlowNode('agent')}>Agent</button>
              <button type="button" data-testid="workflow-add-approval-node" disabled={busy} onClick={() => addFlowNode('approval')}>Approval</button>
              <button type="button" data-testid="workflow-add-artifact-node" disabled={busy} onClick={() => addFlowNode('artifact')}>Artifact</button>
              <button
                type="button"
                className="primary-action"
                data-testid="workflow-save"
                disabled={busy || workflowHasErrors}
                title={workflowPrimaryError || undefined}
                onClick={() => void runAction(saveWorkflow, '保存 Workflow')}
              >
                保存
              </button>
              {selectedWorkflow ? <button type="button" className="danger-action" data-testid="workflow-delete" onClick={requestDeleteWorkflow}>删除</button> : null}
            </div>
            <div className="workflow-agent-palette" aria-label="从 Agents 添加到 Workflow" data-testid="workflow-agent-palette">
              <span>添加 Agent</span>
              {agents.map((agent) => (
                <button
                  type="button"
                  data-testid="workflow-agent-palette-item"
                  disabled={busy || agent.enabled === false}
                  key={agent.agent_id}
                  onClick={() => addFlowNode('agent', agent.agent_id)}
                >
                  <span className="workflow-agent-avatar">
                    {agent.avatar_url ? <img src={agent.avatar_url} alt="" /> : (agent.nickname || agent.name || 'A').slice(0, 1)}
                  </span>
                  <span>
                    <strong>{agent.nickname || agent.name}</strong>
                    <small>{agentCapabilityLine(agent)}</small>
                    {agent.description ? <em>{agent.description}</em> : null}
                  </span>
                </button>
              ))}
              {!agents.length ? <small>暂无可添加 Agent</small> : null}
            </div>
            <div className="workflow-canvas" data-testid="workflow-canvas">
              <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} fitView>
                <MiniMap />
                <Controls />
                <Background />
              </ReactFlow>
            </div>
            <div className="workflow-node-settings" data-testid="workflow-node-settings">
              <div className="agent-skill-mounts-head">
                <h3>节点设置</h3>
                <span>{nodes.length} nodes / {edges.length} edges</span>
              </div>
              {workflowErrors.length || workflowValidation.warnings.length ? (
                <div className={`workflow-validation-box ${workflowHasErrors ? 'has-errors' : 'has-warnings'}`} data-testid="workflow-validation">
                  {workflowHasErrors ? (
                    <div>
                      <strong>需要修复</strong>
                      {workflowErrors.map((item) => <span key={`error-${item}`}>{item}</span>)}
                    </div>
                  ) : null}
                  {workflowValidation.warnings.length ? (
                    <div>
                      <strong>提醒</strong>
                      {workflowValidation.warnings.map((item) => <span key={`warning-${item}`}>{item}</span>)}
                    </div>
                  ) : null}
                </div>
              ) : null}
              {nodes.filter((node) => workflowNodeKind(node) !== 'start').map((node) => {
                const kind = workflowNodeKind(node);
                const nodeLabel = String(node.data?.label || node.id);
                const selectedNodeAgent = kind === 'agent'
                  ? agents.find((agent) => agent.agent_id === String(node.data?.agent_id || '')) || null
                  : null;
                const selectedNodeAgentIssue = selectedNodeAgent ? agentRunIssueById.get(selectedNodeAgent.agent_id) || '' : '';
                return (
                  <div className="workflow-node-setting-row" data-testid="workflow-node-setting-row" key={node.id}>
                    <div className="workflow-node-setting-main">
                      <label>
                        <span>{workflowNodeKindLabel(kind)} Label</span>
                        <input
                          className="hy-input"
                          data-testid="workflow-node-label-input"
                          value={nodeLabel}
                          onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, label: event.target.value } } : item))}
                        />
                      </label>
                      {kind === 'agent' ? (
                        <>
                          <label>
                            <span>Agent</span>
                            <select
                              className="hy-select"
                              data-testid="workflow-node-agent-select"
                              value={String(node.data?.agent_id || '')}
                              onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, agent_id: event.target.value, label: agents.find((agent) => agent.agent_id === event.target.value)?.name || item.data?.label } } : item))}
                            >
                              <option value="">选择 Agent</option>
                              {agents.map((agent) => (
                                <option value={agent.agent_id} key={agent.agent_id}>
                                  {agent.name} · {agentCapabilityLine(agent)}
                                </option>
                              ))}
                            </select>
                          </label>
                          <label>
                            <span>Step Task</span>
                            <textarea
                              className="hy-input agent-textarea compact"
                              data-testid="workflow-node-task-input"
                              value={String(node.data?.task || '')}
                              onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, task: event.target.value } } : item))}
                            />
                          </label>
                        </>
                      ) : null}
                      {kind === 'artifact' ? (
                        <label>
                          <span>Artifact Path</span>
                          <input
                            className="hy-input"
                            data-testid="workflow-node-artifact-path-input"
                            value={String(node.data?.artifact_path || node.data?.artifactPath || '')}
                            onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, artifact_path: event.target.value } } : item))}
                            placeholder="留空则按 Label 自动生成，例如 reports/summary.md"
                          />
                        </label>
                      ) : null}
                      {kind === 'approval' ? (
                        <label>
                          <span>Approval Criteria</span>
                          <textarea
                            className="hy-input agent-textarea compact"
                            data-testid="workflow-node-approval-criteria-input"
                            value={String(node.data?.criteria || '')}
                            onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, criteria: event.target.value } } : item))}
                          />
                        </label>
                      ) : null}
                      {selectedNodeAgent ? (
                        <div className="workflow-node-agent-preview">
                          <strong>{selectedNodeAgent.nickname || selectedNodeAgent.name}</strong>
                          <span>{agentCapabilityLine(selectedNodeAgent)}</span>
                          {selectedNodeAgentIssue ? <span className="workflow-node-agent-issue">{selectedNodeAgentIssue}</span> : null}
                          {selectedNodeAgent.description ? <p>{selectedNodeAgent.description}</p> : null}
                        </div>
                      ) : null}
                    </div>
                    <button type="button" data-testid="workflow-node-remove" disabled={busy} onClick={() => removeFlowNode(node.id)}>移除</button>
                  </div>
                );
              })}
              {!nodes.some((node) => workflowNodeKind(node) !== 'start') ? (
                <div className="empty-state inline-empty">点击 Agent、Approval 或 Artifact 添加可配置节点。</div>
              ) : null}
            </div>
            <section className="agent-quick-run" data-testid="workflow-quick-run">
              <div>
                <h3>Workflow Run</h3>
                <p>{selectedWorkflow ? '先保存当前画布，再运行这个 Workflow，完成后自动打开 Runs 详情。' : '新建 Workflow 会先保存草稿，再立即运行。'}</p>
              </div>
              <label>
                <span>Goal</span>
                <textarea
                  className="hy-input agent-run-textarea"
                  data-testid="workflow-run-goal-input"
                  value={workflowRunGoal}
                  onChange={(event) => setWorkflowRunGoal(event.target.value)}
                  placeholder="例如：从设计到审查跑一遍这个任务"
                />
              </label>
              {workflowRunDisabledReason ? (
                <div className="agent-inline-note warn">{workflowRunDisabledReason}</div>
              ) : null}
              <WorkflowRunPreview
                agents={agents}
                agentIssueById={agentRunIssueById}
                sourceNodes={nodes}
                steps={workflowRunPreviewSteps}
              />
              <button
                type="button"
                className="primary-action"
                data-testid="workflow-save-and-run"
                disabled={workflowRunDisabled}
                title={workflowRunDisabledReason || undefined}
                onClick={() => void runAction(runCurrentWorkflow, '保存并运行 Workflow')}
              >
                保存并运行 Workflow
              </button>
            </section>
          </div>
        </section>
      ) : null}

      {!loading && tab === 'runs' ? (
        <section className="agent-studio-grid">
          <div className="agent-studio-panel">
            <div className="section-heading-row"><h2>Run Agent / Workflow</h2></div>
            <label>
              <span>Target</span>
              <select className="hy-select" value={runTarget} onChange={(event) => setRunTarget(event.target.value)}>
                <option value="">选择 Agent 或 Workflow</option>
                {runnables.map((item) => (
                  <option value={item.id} key={item.id} disabled={item.enabled === false}>
                    {runnableOptionLabel(item)}
                  </option>
                ))}
              </select>
            </label>
            {selectedRunTarget ? (
              <div className="run-target-preview">
                <strong>{selectedRunTarget.nickname || selectedRunTarget.name}</strong>
                <span>{runnableCapabilityLine(selectedRunTarget)}</span>
                {selectedRunTarget.description ? <p>{selectedRunTarget.description}</p> : null}
              </div>
            ) : null}
            {runTargetDisabledReason ? (
              <div className="agent-inline-note warn">{runTargetDisabledReason}</div>
            ) : null}
            {selectedRunTarget?.kind === 'workflow' && selectedRunTargetWorkflowValidation.errors.length > 1 ? (
              <div className="workflow-validation-box has-errors">
                <div>
                  <strong>Workflow 运行前需要修复</strong>
                  {selectedRunTargetWorkflowValidation.errors.map((item) => <span key={`run-target-error-${item}`}>{item}</span>)}
                </div>
              </div>
            ) : null}
            {selectedRunTarget?.kind === 'workflow' ? (
              <WorkflowRunPreview
                agents={agents}
                agentIssueById={agentRunIssueById}
                sourceNodes={selectedRunTargetWorkflowNodes}
                steps={selectedRunTargetWorkflowPreviewSteps}
              />
            ) : null}
            <label><span>Goal</span><textarea className="hy-input agent-textarea" value={runGoal} onChange={(event) => setRunGoal(event.target.value)} /></label>
            <button
              type="button"
              className="primary-action"
              disabled={!runTarget || Boolean(runTargetDisabledReason) || !runGoal.trim() || busy}
              title={runTargetDisabledReason || undefined}
              onClick={() => void runAction(async () => {
              const target = runnables.find((item) => item.id === runTarget);
              if (!target) return;
              const goal = runGoal.trim();
              const run = target.kind === 'agent'
                ? await createAgentRun(target.id, goal)
                : await createWorkflowRun(target.id, goal);
              openRunDetail(run.run_id, { revealInHistory: true });
              setRunGoal('');
              return { selectedRunId: run.run_id, runTarget: target.id };
            }, '创建 Run')}
            >
              运行
            </button>
            <div className="run-history-toolbar">
              <div className="run-history-head">
                <span>Run History · {filteredRuns.length}{runSearchActive ? ` / ${runStatusFilteredRuns.length}` : ''}</span>
                {filteredRuns.length && !runHistoryManagementMode ? (
                  <button type="button" data-testid="agent-run-history-manage" disabled={busy} onClick={() => setRunHistoryManagementMode(true)}>管理</button>
                ) : null}
              </div>
              <div className="run-history-search">
                <input
                  className="hy-input"
                  type="search"
                  value={runSearchQuery}
                  placeholder="搜索目标、Agent、结果、Run ID..."
                  aria-label="搜索 Run History"
                  onChange={(event) => setRunSearchQuery(event.target.value)}
                />
                {runSearchActive ? (
                  <button type="button" onClick={() => setRunSearchQuery('')}>清除</button>
                ) : null}
              </div>
              <div className="run-filter-tabs" role="group" aria-label="Run history filter">
                {([
                  ['all', 'All', runFilterCounts.all],
                  ['workflow', 'Workflows', runFilterCounts.workflow],
                  ['agent', 'Agents', runFilterCounts.agent],
                ] as const).map(([filter, label, count]) => (
                  <button
                    type="button"
                    key={filter}
                    className={runKindFilter === filter ? 'active' : ''}
                    onClick={() => selectRunKindFilter(filter)}
                  >
                    {label} <span>{count}</span>
                  </button>
                ))}
              </div>
              <div className="run-filter-tabs run-status-filter-tabs" role="group" aria-label="Run status filter">
                {([
                  ['all', '全部', runStatusFilterCounts.all],
                  ['completed', '完成', runStatusFilterCounts.completed],
                  ['failed', '失败', runStatusFilterCounts.failed],
                  ['active', '进行中', runStatusFilterCounts.active],
                ] as const).map(([filter, label, count]) => (
                  <button
                    type="button"
                    key={filter}
                    className={runStatusFilter === filter ? 'active' : ''}
                    onClick={() => selectRunStatusFilter(filter)}
                  >
                    {label} <span>{count}</span>
                  </button>
                ))}
              </div>
              {filteredRuns.length && runHistoryManagementMode ? (
                <div className="studio-bulk-actions" aria-label="Run History 批量操作" data-testid="agent-run-history-bulk-actions">
                  <span>{selectedHistoryRuns.length ? `已选择 ${selectedHistoryRuns.length} / ${filteredRuns.length}` : `${filteredRuns.length} runs`}</span>
                  <button type="button" data-testid="agent-run-history-select-all" disabled={busy} onClick={() => setSelectedRunIds(allHistoryRunsSelected ? [] : filteredRunIds)}>
                    {allHistoryRunsSelected ? '取消全选' : '全选当前列表'}
                  </button>
                  <button type="button" data-testid="agent-run-history-clear-selection" disabled={busy || !selectedHistoryRuns.length} onClick={() => setSelectedRunIds([])}>清空</button>
                  <button
                    type="button"
                    className="danger-action"
                    data-testid="agent-run-history-delete-selected"
                    disabled={busy || !selectedHistoryRuns.length || Boolean(runBulkDeleteDisabledReason)}
                    title={runBulkDeleteDisabledReason || undefined}
                    onClick={requestDeleteSelectedRuns}
                  >
                    删除所选
                  </button>
                  <button type="button" data-testid="agent-run-history-finish-management" disabled={busy} onClick={finishRunHistoryManagement}>完成</button>
                </div>
              ) : null}
            </div>
            <div className="run-list grouped">
              {runHistoryGroups.map((group) => {
                const collapsed = collapsedRunHistoryGroups.has(group.key);
                const selectedInGroup = group.runs.some((run) => run.run_id === selectedRunId);
                return (
                <section className={`run-history-group${selectedInGroup ? ' has-selected-run' : ''}`} key={group.key}>
                  <button
                    type="button"
                    className="run-history-group-head"
                    aria-expanded={!collapsed}
                    onClick={() => toggleRunHistoryGroup(group.key)}
                  >
                    <AgentAvatar avatarUrl={group.avatarUrl} name={group.label} />
                    <div>
                      <strong>{group.label}</strong>
                      <span>{group.subtitle} · {group.runs.length} runs · {runHistoryGroupSummary(group.runs)}</span>
                    </div>
                    <em aria-hidden="true">{collapsed ? '+' : '-'}</em>
                  </button>
                  {!collapsed ? (
                  <div className={runHistoryManagementMode ? 'run-history-group-list managing' : 'run-history-group-list'}>
                    {group.runs.map((run) => (
                      <div
                        className={run.run_id === selectedRunId ? 'run-list-row active' : 'run-list-row'}
                        data-run-group-id={run.run_group_id || ''}
                        data-run-id={run.run_id}
                        data-run-kind={run.kind}
                        data-run-status={run.status}
                        data-task-id={run.task_id || ''}
                        data-testid="agent-run-history-row"
                        key={run.run_id}
                      >
                        <label className="run-list-select" aria-label={`选择 Run ${run.run_id}`}>
                          <input
                            data-testid="agent-run-history-select-run"
                            type="checkbox"
                            checked={selectedRunIdSet.has(run.run_id)}
                            disabled={busy || !runHistoryManagementMode}
                            onChange={() => toggleRunSelected(run.run_id)}
                          />
                        </label>
                        <button
                          type="button"
                          className={run.run_id === selectedRunId ? 'run-list-item active' : 'run-list-item'}
                          data-testid="agent-run-history-open-run"
                          onClick={() => openRunDetail(run.run_id)}
                        >
                          <span className={`run-list-status-dot ${runStatusTone(run.status)}`} aria-hidden="true" />
                          <span className="run-list-item-copy">
                            <strong>{run.user_goal || run.runnable_name || run.runnable_id}</strong>
                            <span>{runKindLabel(run.kind)} · {runStatusLabel(run.status)} · {formatRunDate(run.updated_at || run.created_at)}</span>
                            {run.result ? <small>{run.result}</small> : null}
                          </span>
                        </button>
                      </div>
                    ))}
                  </div>
                  ) : null}
                </section>
                );
              })}
              {!filteredRuns.length ? (
                <div className="empty-state inline-empty">
                  {runSearchActive && runStatusFilteredRuns.length ? '没有匹配搜索的 Run。' : '当前分类下没有 Run。'}
                </div>
              ) : null}
            </div>
          </div>
          <div className="agent-studio-panel">
            <div className="section-heading-row"><h2>Run Detail</h2></div>
            {selectedRun ? (
              <article
                className="run-detail"
                data-run-group-id={selectedRun.run_group_id || ''}
                data-run-id={selectedRun.run_id}
                data-run-kind={selectedRun.kind}
                data-run-status={selectedRun.status}
                data-session-id={selectedRun.session_id || ''}
                data-task-id={selectedRun.task_id || ''}
                data-testid="agent-run-detail"
              >
                <header className="run-detail-hero" data-testid="agent-run-detail-hero">
                  <AgentAvatar avatarUrl={selectedRunAvatarUrl} name={selectedRun.runnable_name || selectedRun.runnable_id || 'Run'} />
                  <div className="run-detail-title">
                    <span>{runKindLabel(selectedRun.kind)} · {formatRunDate(selectedRun.created_at)}</span>
                    <h3>{selectedRun.runnable_name || selectedRun.runnable_id}</h3>
                    <p>{selectedRun.user_goal || 'No task goal recorded.'}</p>
                  </div>
                  <span className={`run-status-pill ${runStatusTone(selectedRun.status)}`}>{runStatusLabel(selectedRun.status)}</span>
                </header>
                <div className="run-detail-meta" data-testid="agent-run-detail-meta">
                  <span>{runKindLabel(selectedRun.kind)}</span>
                  <span>Updated {formatRunDate(selectedRun.updated_at || selectedRun.created_at)}</span>
                  {selectedRunIsLive ? <span className="run-live-pill">实时更新</span> : null}
                  {selectedRun.run_group_id ? <span>Group {selectedRun.run_group_id}</span> : null}
                  {selectedRun.task_id ? <code>Task {selectedRun.task_id}</code> : null}
                  {selectedRun.session_id ? <code>Session {selectedRun.session_id}</code> : null}
                  {selectedRun.task_run_link_run_status ? <span>Task link {runStatusLabel(selectedRun.task_run_link_run_status)}</span> : null}
                  {selectedRun.task_run_link_last_event_sequence !== undefined && selectedRun.task_run_link_last_event_sequence !== null ? (
                    <span>Replay #{selectedRun.task_run_link_last_event_sequence}</span>
                  ) : null}
                  {selectedRun.task_run_link_updated_at || selectedRun.task_run_link_created_at ? (
                    <span>Task link updated {formatRunDate(selectedRun.task_run_link_updated_at || selectedRun.task_run_link_created_at)}</span>
                  ) : null}
                  <code>{selectedRun.run_id}</code>
                  <button
                    type="button"
                    className="run-rerun-prepare"
                    data-testid="agent-run-detail-prepare-rerun"
                    disabled={busy || !selectedRunRerunTarget}
                    title={!selectedRunRerunTarget ? '找不到原目标，无法准备重跑。' : undefined}
                    onClick={prepareSelectedRunRerun}
                  >
                    准备重跑
                  </button>
                  <button
                    type="button"
                    className="run-rerun-action"
                    data-testid="agent-run-detail-rerun"
                    disabled={busy || Boolean(selectedRunRerunDisabledReason)}
                    title={selectedRunRerunDisabledReason || undefined}
                    onClick={() => void runAction(rerunSelectedRun, '重新运行')}
                  >
                    重新运行
                  </button>
                  {selectedWorkflowParentRunId ? (
                    <button type="button" className="run-parent-link" data-testid="agent-run-detail-open-parent-run" onClick={() => openRunDetail(selectedWorkflowParentRunId)}>
                      返回 Workflow：{selectedWorkflowParentRun?.runnable_name || selectedWorkflowParentRun?.runnable_id || '父 Workflow'}
                    </button>
                  ) : null}
                  {selectedRun.kind === 'workflow_run' && selectedRunWorkflow ? (
                    <button type="button" className="run-workflow-link" data-testid="agent-run-detail-open-workflow-studio" onClick={() => openWorkflowDesign(selectedRunWorkflow.workflow_id)}>
                      打开 Workflow Studio
                    </button>
                  ) : null}
                  {isActiveRunStatus(selectedRun.status) ? (
                    <button
                      type="button"
                      className="run-cancel-action danger-action"
                      data-testid="agent-run-detail-cancel"
                      disabled={busy}
                      onClick={requestCancelSelectedRun}
                    >
                      取消 Run
                    </button>
                  ) : null}
                </div>
                {selectedWorkflowApprovalChildRunId ? (
                  <section className="run-approval-box workflow-approval-bridge" data-testid="agent-run-detail-workflow-child-approval">
                    <div className="workflow-approval-bridge-head" data-testid="agent-run-detail-workflow-child-approval-head">
                      <div>
                        <h4>Workflow 正在等待子 Agent 审批</h4>
                        <p>
                          {selectedWorkflowApprovalStep?.label || selectedWorkflowApprovalChildRun?.runnable_name || selectedWorkflowApprovalChildRunId}
                          {' '}需要确认工具调用，处理后 Workflow 会继续执行后续步骤。
                        </p>
                        {selectedWorkflowApprovalStep?.task ? (
                          <small>Step Task：{selectedWorkflowApprovalStep.task}</small>
                        ) : null}
                      </div>
                      <span className={`run-status-pill ${runStatusTone(selectedWorkflowApprovalChildRun?.status || 'approval_required')}`}>
                        {selectedWorkflowApprovalChildRun ? runStatusLabel(selectedWorkflowApprovalChildRun.status) : '加载中'}
                      </span>
                    </div>
                    {selectedWorkflowApprovalChildRun?.pending_approval?.tool ? (
                      <>
                        <RunApprovalRequest
                          inputPreview={selectedWorkflowApprovalChildRun.pending_approval.input_preview}
                          runGoal={selectedWorkflowApprovalChildRun.user_goal || ''}
                          runId={selectedWorkflowApprovalChildRun.run_id}
                          runLabel={selectedWorkflowApprovalChildRun.runnable_name || 'Child Run'}
                          tool={selectedWorkflowApprovalChildRun.pending_approval.tool}
                        />
                        <div className="run-approval-actions" data-testid="agent-run-detail-workflow-child-approval-actions">
                          <button
                            type="button"
                            className="primary-action"
                            data-testid="agent-run-detail-workflow-child-approve"
                            disabled={busy}
                            onClick={() => void runAction(
                              () => approveRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),
                              '批准子 Agent 工具调用',
                            )}
                          >
                            批准子 Agent
                          </button>
                          <button
                            type="button"
                            className="danger-action"
                            data-testid="agent-run-detail-workflow-child-reject"
                            disabled={busy}
                            onClick={() => void runAction(
                              () => rejectRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),
                              '拒绝子 Agent 工具调用',
                            )}
                          >
                            拒绝子 Agent
                          </button>
                          <button
                            type="button"
                            className="danger-action"
                            data-testid="agent-run-detail-workflow-child-cancel"
                            disabled={busy}
                            onClick={() => void runAction(
                              () => cancelRunById(selectedWorkflowApprovalChildRunId, selectedRun.run_id),
                              '取消子 Agent Run',
                            )}
                          >
                            取消子 Run
                          </button>
                          <button type="button" className="run-timeline-child" data-testid="agent-run-detail-workflow-child-open-run" onClick={() => openRunDetail(selectedWorkflowApprovalChildRunId)}>
                            打开子 Run
                          </button>
                        </div>
                      </>
                    ) : (
                      <>
                        <pre>{selectedWorkflowApprovalChildRun ? (selectedWorkflowApprovalChildRun.result || 'Child run has no approval payload.') : 'Loading child run...'}</pre>
                        <div className="run-approval-actions" data-testid="agent-run-detail-workflow-child-approval-actions">
                          <button type="button" className="run-timeline-child" data-testid="agent-run-detail-workflow-child-open-run" onClick={() => openRunDetail(selectedWorkflowApprovalChildRunId)}>
                            打开子 Run
                          </button>
                        </div>
                      </>
                    )}
                  </section>
                ) : null}
                {selectedRun.status === 'approval_required' && selectedRun.pending_approval?.tool ? (
                  <section className="run-approval-box" data-testid="agent-run-detail-approval">
                    <div>
                      <h4>Approval Required · {selectedRun.pending_approval.tool}</h4>
                      <p>{selectedRun.pending_approval.tool === 'workflow.approval' ? '这个 Workflow 审批节点需要人工确认后才会继续。' : '这个工具调用需要人工确认后才会继续当前 Run。'}</p>
                    </div>
                    <RunApprovalRequest
                      inputPreview={selectedRun.pending_approval.input_preview}
                      runGoal={selectedRun.user_goal || ''}
                      runId={selectedRun.run_id}
                      runLabel={selectedRun.runnable_name || runKindLabel(selectedRun.kind)}
                      tool={selectedRun.pending_approval.tool}
                    />
                    <div className="run-approval-actions" data-testid="agent-run-detail-approval-actions">
                      <button type="button" className="primary-action" data-testid="agent-run-detail-approval-approve" disabled={busy} onClick={() => void runAction(approveSelectedRun, '批准工具调用')}>批准</button>
                      <button type="button" className="danger-action" data-testid="agent-run-detail-approval-reject" disabled={busy} onClick={() => void runAction(rejectSelectedRun, '拒绝工具调用')}>拒绝</button>
                    </div>
                  </section>
                ) : null}
                <section className="run-detail-block run-task-block" data-testid="agent-run-detail-task">
                  <div className="run-detail-section-head">
                    <div>
                      <h4>Task</h4>
                      <span>Agent 收到的完整任务目标</span>
                    </div>
                  </div>
                  <p>{selectedRun.user_goal || 'No task goal recorded.'}</p>
                </section>
                <section className={`run-detail-block run-result-block ${runStatusTone(selectedRun.status)}`} data-testid="agent-run-detail-result">
                  <div className="run-detail-section-head">
                    <div>
                      <h4>{selectedRun.kind === 'workflow_run' ? 'Final Result' : 'Result'}</h4>
                      <span>{selectedRun.status === 'completed' ? '最终交付内容' : selectedRun.status === 'failed' ? '失败原因或最后输出' : '当前最新输出'}</span>
                    </div>
                    <span className={`run-status-pill ${runStatusTone(selectedRun.status)}`}>{runStatusLabel(selectedRun.status)}</span>
                  </div>
                  <RunExpandableContent
                    content={selectedRun.result || 'No result yet.'}
                    label="展开完整结果"
                    defaultOpen
                  />
                </section>
                {selectedRun.kind === 'workflow_run' ? (
                  <details className="run-detail-block run-detail-fold" data-testid="agent-run-detail-workflow-steps" open>
                    <summary className="run-detail-section-head">
                      <div>
                        <h4>Workflow Steps · {selectedWorkflowSteps.length}</h4>
                        <span>Workflow 中每个节点的执行状态、审批和产物</span>
                      </div>
                    </summary>
                    <div className="run-detail-fold-body workflow-child-results">
                      {selectedWorkflowSteps.map((step, index) => {
                        const childRun = step.childRunId ? runById.get(step.childRunId) || null : null;
                        const childStatus = childRun?.status || step.status || 'loading';
                        const summary = workflowStepSummary(step, childRun);
                        const childArtifacts = workflowStepArtifacts(childRun);
                        const workflowArtifact = workflowRunArtifactForStep(selectedRun, step);
                        return (
                          <article
                            className={`workflow-child-result workflow-step-result ${step.kind}`}
                            data-testid="agent-run-detail-workflow-step"
                            data-workflow-step-key={step.key}
                            data-workflow-step-kind={step.kind}
                            data-workflow-step-node-id={step.nodeId || ''}
                            data-workflow-step-status={childStatus}
                            data-child-run-id={step.childRunId || ''}
                            key={step.key}
                          >
                            <div className="workflow-child-result-head">
                              <div>
                                <strong>{index + 1}. {step.label}</strong>
                                <span>{workflowStepKindLabel(step.kind)}{childRun?.runnable_name ? ` · ${childRun.runnable_name}` : ''}</span>
                              </div>
                              <div>
                                <em className={`run-status-pill ${runStatusTone(childStatus)}`}>{runStatusLabel(childStatus)}</em>
                                {step.childRunId ? (
                                  <button type="button" className="run-timeline-child" data-testid="agent-run-detail-workflow-step-open-run" onClick={() => openRunDetail(step.childRunId || '')}>
                                    Open Run
                                  </button>
                                ) : null}
                              </div>
                            </div>
                            {step.task ? (
                              <p className="workflow-step-task">
                                <strong>{step.kind === 'approval' ? '审批说明' : 'Step Task'}</strong>
                                {step.task}
                              </p>
                            ) : null}
                            <RunExpandableContent
                              content={step.childRunId && !childRun ? 'Loading child run...' : summary}
                              label="展开完整节点结果"
                              defaultOpen={childStatus === 'failed' || childStatus === 'cancelled' || childStatus === 'approval_required'}
                            />
                            {childRun && childArtifacts.length ? (
                              <div className="run-artifacts compact">
                                {childArtifacts.map((artifact, artifactIndex) => {
                                  const path = String(artifact.path || '');
                                  return (
                                    <button
                                      type="button"
                                      disabled={!path}
                                      key={`${step.childRunId}-${path}-${artifactIndex}`}
                                      onClick={() => path ? void openArtifact(childRun, path) : undefined}
                                    >
                                      {path || 'artifact'}
                                    </button>
                                  );
                                })}
                              </div>
                            ) : null}
                            {step.kind === 'artifact' && step.artifactPath ? (
                              <div className="run-artifacts compact">
                                {workflowArtifact ? (
                                  <button type="button" onClick={() => void openArtifact(selectedRun, step.artifactPath || '')}>
                                    {step.artifactPath}
                                  </button>
                                ) : (
                                  <span className="workflow-artifact-plan">
                                    {skippedWorkflowArtifactLabel(selectedRun, step)} · {step.artifactPath}
                                  </span>
                                )}
                              </div>
                            ) : null}
                          </article>
                        );
                      })}
                      {!selectedWorkflowSteps.length ? <span>No workflow steps</span> : null}
                    </div>
                  </details>
                ) : null}
                <details className="run-detail-block run-detail-fold run-execution-block" data-testid="agent-run-detail-execution" open>
                  <summary className="run-detail-section-head">
                    <div>
                      <h4>Execution · {selectedRunExecutionEvents.length}</h4>
                      <span>{selectedRunReplayEvents.length ? 'RunEvent replay facts' : '模型响应、工具调用、审批与完成节点'}</span>
                    </div>
                  </summary>
                  <ol className="run-detail-fold-body run-execution-steps" data-testid="agent-run-detail-execution-events">
                    {selectedRunExecutionEvents.map((event, index) => {
                      const childRunId = timelineChildRunId(event);
                      const childRun = childRunId ? runById.get(childRunId) : null;
                      const eventStatus = timelineStatus(event);
                      const payload = timelineEventPayload(event);
                      const detail = String(event.detail || '').trim();
                      const eventTone = timelineEventTone(event);
                      const eventName = timelineEventName(event);
                      const eventSequence = timelineEventSequence(event);
                      const eventId = String(event.event_id || '').trim();
                      const eventRunId = String(event.run_id || '').trim();
                      const eventActor = String(event.actor || '').trim();
                      const eventVisibility = String(event.visibility || '').trim();
                      const eventSensitivity = String(event.sensitivity || '').trim();
                      const eventSchemaVersion = String(event.schema_version || '').trim();
                      return (
                        <li
                          className={`run-execution-step ${eventTone}`}
                          data-child-run-id={childRunId || ''}
                          data-run-event={eventName}
                          data-run-event-actor={eventActor}
                          data-run-event-id={eventId}
                          data-run-event-run-id={eventRunId}
                          data-run-event-sequence={eventSequence}
                          data-run-event-sensitivity={eventSensitivity}
                          data-run-event-schema-version={eventSchemaVersion}
                          data-run-event-status={eventStatus || ''}
                          data-run-event-tone={eventTone}
                          data-run-event-visibility={eventVisibility}
                          data-testid="agent-run-detail-execution-event"
                          key={`${eventName || 'event'}-${index}`}
                        >
                          <span className="run-step-rail"><i aria-hidden="true" /></span>
                          <div className="run-step-card">
                            <div className="run-step-head">
                              <div>
                                <strong>{timelineEventTitle(event)}</strong>
                                <span>{formatRunDate(timelineEventTime(event))}</span>
                              </div>
                              <code>{timelineEventCode(event)}</code>
                            </div>
                            {detail && detail !== timelineEventTitle(event) ? <p>{detail}</p> : null}
                            {eventStatus ? (
                              <em className={`run-status-pill ${runStatusTone(eventStatus)}`}>{runStatusLabel(eventStatus)}</em>
                            ) : null}
                            {payload ? (
                              <RunExpandableContent
                                content={payload}
                                label="展开完整事件内容"
                                defaultOpen={eventTone === 'danger' || eventTone === 'approval'}
                              />
                            ) : null}
                            {childRunId ? (
                              <button
                                type="button"
                                className="run-timeline-child"
                                data-testid="agent-run-detail-execution-open-child-run"
                                onClick={() => openRunDetail(childRunId)}
                              >
                                Child Run {childRun?.status ? `· ${runStatusLabel(childRun.status)}` : ''} · {childRunId}
                              </button>
                            ) : null}
                          </div>
                        </li>
                      );
                    })}
                  </ol>
                  {selectedRunReplayError ? <p className="run-replay-status">{selectedRunReplayError}</p> : null}
                  {selectedRunReplayEvents.length && selectedRunReplayHasMore ? (
                    <div className="run-replay-more">
                      <button
                        type="button"
                        data-testid="agent-run-detail-load-more-events"
                        disabled={selectedRunReplayLoading}
                        onClick={() => void loadMoreSelectedRunEvents()}
                      >
                        {selectedRunReplayLoading ? '加载中...' : '加载更多 RunEvent'}
                      </button>
                    </div>
                  ) : null}
                </details>
                <details className="run-detail-block run-detail-fold" data-testid="agent-run-detail-artifacts" open>
                  <summary className="run-detail-section-head">
                    <div>
                      <h4>Artifacts · {(selectedRun.artifacts || []).length}</h4>
                      <span>上下文、工具产物和可预览文件</span>
                    </div>
                  </summary>
                  <div className="run-detail-fold-body run-artifacts" data-testid="agent-run-detail-artifact-list">
                    {(selectedRun.artifacts || []).map((artifact, index) => {
                      const path = String(artifact.path || '');
                      const artifactKind = String(artifact.kind || artifact.artifact_kind || '').trim();
                      const sourceRunId = String(artifact.source_run_id || artifact.run_id || selectedRun.run_id);
                      const sourceLabel = String(artifact.source_runnable_name || artifact.workflow_step_label || '').trim();
                      return (
                        <button
                          type="button"
                          data-artifact-kind={artifactKind}
                          data-artifact-path={path}
                          data-artifact-source-label={sourceLabel}
                          data-artifact-source-run-id={sourceRunId}
                          data-testid="agent-run-detail-artifact"
                          disabled={!path}
                          key={`${path}-${index}`}
                          onClick={() => path ? void openArtifact(sourceRunId, path) : undefined}
                        >
                          {sourceLabel ? `${sourceLabel} / ${path || 'artifact'}` : path || 'artifact'}
                        </button>
                      );
                    })}
                    {!selectedRun.artifacts?.length ? <span>No artifacts</span> : null}
                  </div>
                  {artifactPreview ? (
                    <div className="run-detail-fold-body artifact-preview" data-testid="agent-run-detail-artifact-preview">
                      <strong>{artifactPreview.path}{artifactPreview.truncated ? ' · truncated' : ''}</strong>
                      <pre>{artifactPreview.content}</pre>
                    </div>
                  ) : null}
                </details>
              </article>
            ) : (
              <div className="empty-state inline-empty">从左侧选择一个 Run，或运行新的 Agent / Workflow 后查看 Result、Timeline 和 Artifacts。</div>
            )}
          </div>
        </section>
      ) : null}

      <ConfirmDialog
        confirmLabel={confirmDialog?.confirmLabel}
        description={confirmDialog?.description}
        onCancel={closeConfirmDialog}
        onConfirm={confirmCurrentDialog}
        open={Boolean(confirmDialog)}
        title={confirmDialog?.title || ''}
        variant={confirmDialog?.variant}
      />
    </section>
  );
}

function SkillCard({
  busy,
  folders,
  managing,
  onDelete,
  onMoveFolder,
  onOpenLocation,
  onSelectionChange,
  onToggleEnabled,
  selected,
  skill,
}: {
  busy: boolean;
  folders: SkillFolderSpec[];
  managing: boolean;
  onDelete: () => Promise<void> | void;
  onMoveFolder: (folderId: string) => Promise<void>;
  onOpenLocation: () => Promise<void>;
  onSelectionChange: () => void;
  onToggleEnabled: () => Promise<void>;
  selected: boolean;
  skill: SkillSpec;
}) {
  const enabled = skill.enabled !== false;
  const cardClassName = [
    'skill-card',
    enabled ? '' : 'disabled',
    managing ? 'managing' : '',
  ].filter(Boolean).join(' ');
  return (
    <article
      className={cardClassName}
      data-skill-enabled={enabled ? 'true' : 'false'}
      data-skill-folder-id={skill.folder_id || ''}
      data-skill-id={skill.skill_id}
      data-testid="skill-card"
    >
      <div className="section-heading-row skill-card-head">
        <div className="skill-card-title">
          <label className="skill-card-select" aria-label={`选择 Skill ${skill.name}`}>
            <input
              type="checkbox"
              data-testid="skill-card-select"
              checked={selected}
              disabled={busy || !managing}
              onChange={onSelectionChange}
            />
          </label>
          <div>
            <h3>{skill.name}</h3>
            <span className="skill-source-tag">{skillSourceTypeLabel(skill.source_type)}</span>
          </div>
        </div>
        <label className={enabled ? 'skill-enable-switch active' : 'skill-enable-switch'}>
          <input
            type="checkbox"
            data-testid="skill-card-enabled-toggle"
            checked={enabled}
            disabled={busy}
            onChange={() => void onToggleEnabled()}
          />
          <span aria-hidden="true" />
        </label>
      </div>
      <p>{skill.description || skill.content_summary}</p>
      <label className="skill-card-folder">
        <span>文件夹</span>
        <select
          className="hy-select"
          data-testid="skill-card-folder-select"
          value={skill.folder_id || ''}
          disabled={busy}
          onChange={(event) => void onMoveFolder(event.target.value)}
        >
          <option value="">无需分组</option>
          {folders.map((folder) => (
            <option value={folder.folder_id} key={folder.folder_id}>{folder.name}</option>
          ))}
        </select>
      </label>
      <div className="skill-card-path">
        <span>路径</span>
        <code>{skillPathLabel(skill)}</code>
      </div>
      {skillSourceLabel(skill) ? (
        <div className="skill-card-path">
          <span>来源</span>
          <code>{skillSourceLabel(skill)}</code>
        </div>
      ) : null}
      {skill.asset_paths?.length ? <small>{skill.asset_paths.length} assets/templates</small> : null}
      <div className="skill-card-actions">
        <button type="button" data-testid="skill-card-open-location" disabled={busy || !skill.local_path} onClick={() => void onOpenLocation()}>打开路径</button>
        <button type="button" className="danger-action" data-testid="skill-card-delete" disabled={busy} onClick={() => void onDelete()}>删除</button>
      </div>
      <pre>{(skill.skill_markdown || '').slice(0, 1200)}</pre>
    </article>
  );
}
