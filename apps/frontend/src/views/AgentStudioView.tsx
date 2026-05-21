import { useCallback, useEffect, useMemo, useState, type DragEvent } from 'react';
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

import {
  attachSkill,
  approveRunApproval,
  createAgent,
  createAgentRun,
  createWorkflow,
  createWorkflowRun,
  deleteAgent,
  deleteSkill,
  deleteWorkflow,
  detachSkill,
  getRun,
  getRunArtifact,
  importSkill,
  listAgents,
  listRunnables,
  listRuns,
  listSkills,
  listWorkflows,
  rejectRunApproval,
  testAgentModel,
  updateAgent,
  updateSkill,
  updateWorkflow,
  type AgentSpec,
  type RunnableSummary,
  type RunSpec,
  type SkillSpec,
  type WorkflowSpec,
} from '../lib/agents';
import { chooseAvatarImage, chooseSkillSources, openAppView, openPath } from '../lib/bridge';
import { listModelProfiles, type ModelProfile } from '../lib/modelProfiles';
import { currentParam } from '../lib/view';

type StudioTab = 'agents' | 'skills' | 'workflows' | 'runs';

type StudioRefreshOptions = {
  selectedAgentId?: string;
  selectFirstAgent?: boolean;
  selectedWorkflowId?: string;
  selectFirstWorkflow?: boolean;
  runTarget?: string;
  selectedRunId?: string;
  selectFirstRun?: boolean;
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
  status: 'success' | 'failed' | 'skipped';
  message: string;
};

const starterNodes: Node[] = [
  { id: 'start', type: 'input', position: { x: 40, y: 120 }, data: { label: 'Start', kind: 'start' } },
];

function scopesToText(value: unknown): string {
  return Array.isArray(value) ? value.join(', ') : String(value || '');
}

function textToScopes(value: string): string[] {
  return value.split(',').map((item) => item.trim()).filter(Boolean);
}

function parseSkillSources(value: string): string[] {
  const sources = value
    .split(/[\n,]+/)
    .map((item) => item.trim())
    .filter(Boolean);
  return Array.from(new Set(sources));
}

function appendSkillSources(current: string, sources: string[]): string {
  return parseSkillSources([current, ...sources].filter(Boolean).join('\n')).join('\n');
}

function skillPathLabel(skill: SkillSpec): string {
  return skill.local_path || skill.source_path || 'local skill';
}

function localSourceAlias(source: string): string {
  const clean = source.trim().replace(/[\\/]+$/, '');
  const name = clean.split(/[\\/]/).pop();
  return name ? `local:${name}` : '';
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
    allow_artifacts: tools.has('artifact.write') || !tools.size,
    default_workdir: String(workspace.default_workdir || ''),
    readable_scopes: scopesToText(workspace.readable_scopes || ['.']),
    writable_scopes: scopesToText(workspace.writable_scopes || []),
    enabled: agent.enabled !== false,
  };
}

function workflowNodes(workflow: WorkflowSpec | null): Node[] {
  if (!workflow) return starterNodes;
  return workflow.nodes.map((node) => ({
    id: node.id,
    type: node.type === 'start' ? 'input' : node.type === 'artifact' ? 'output' : 'default',
    position: node.position || { x: 0, y: 0 },
    data: node.data || { label: node.id, kind: node.type || 'agent' },
  }));
}

function workflowEdges(workflow: WorkflowSpec | null): Edge[] {
  if (!workflow) return [];
  return workflow.edges.map((edge, index) => ({
    id: edge.id || `edge-${index}`,
    source: edge.source,
    target: edge.target,
  }));
}

function runStatusTone(status: string): string {
  if (status === 'completed') return 'ready';
  if (status === 'failed' || status === 'cancelled') return 'danger';
  if (status === 'approval_required') return 'approval';
  return 'running';
}

function runKindLabel(kind: string): string {
  if (kind === 'agent_run') return 'Agent Run';
  if (kind === 'workflow_run') return 'Workflow Run';
  return kind || 'Run';
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

function AgentAvatar({ avatarUrl, name }: { avatarUrl?: string; name: string }) {
  return (
    <span className={avatarUrl ? 'agent-avatar has-image' : 'agent-avatar'} aria-hidden="true">
      {avatarUrl ? <img src={avatarUrl} alt="" /> : agentInitial(name)}
    </span>
  );
}

export function AgentStudioView() {
  const [tab, setTab] = useState<StudioTab>(() => currentParam('run') ? 'runs' : 'agents');
  const [agents, setAgents] = useState<AgentSpec[]>([]);
  const [skills, setSkills] = useState<SkillSpec[]>([]);
  const [modelProfiles, setModelProfiles] = useState<ModelProfile[]>([]);
  const [workflows, setWorkflows] = useState<WorkflowSpec[]>([]);
  const [runnables, setRunnables] = useState<RunnableSummary[]>([]);
  const [runs, setRuns] = useState<RunSpec[]>([]);
  const [selectedAgentId, setSelectedAgentId] = useState('');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState('');
  const [draft, setDraft] = useState<AgentDraft>(emptyAgentDraft);
  const [skillImportText, setSkillImportText] = useState('');
  const [skillImportResults, setSkillImportResults] = useState<SkillImportResult[]>([]);
  const [workflowName, setWorkflowName] = useState('New Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [agentRunGoal, setAgentRunGoal] = useState('');
  const [workflowRunGoal, setWorkflowRunGoal] = useState('');
  const [runTarget, setRunTarget] = useState('');
  const [runGoal, setRunGoal] = useState('');
  const [selectedRunId, setSelectedRunId] = useState(() => currentParam('run'));
  const [artifactPreview, setArtifactPreview] = useState<{ path: string; content: string; truncated?: boolean } | null>(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [loading, setLoading] = useState(true);
  const [busyAction, setBusyAction] = useState('');
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(starterNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);
  const busy = loading || Boolean(busyAction);

  const selectedAgent = useMemo(
    () => agents.find((agent) => agent.agent_id === selectedAgentId) || null,
    [agents, selectedAgentId],
  );
  const selectedWorkflow = useMemo(
    () => workflows.find((workflow) => workflow.workflow_id === selectedWorkflowId) || null,
    [workflows, selectedWorkflowId],
  );
  const selectedRun = useMemo(
    () => runs.find((run) => run.run_id === selectedRunId) || null,
    [runs, selectedRunId],
  );
  const chatModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => profile.capability === 'chat' && profile.status === 'available' && profile.enabled !== false),
    [modelProfiles],
  );
  const visionModelProfiles = useMemo(
    () => modelProfiles.filter((profile) => profile.capability === 'vision' && profile.status === 'available' && profile.enabled !== false),
    [modelProfiles],
  );
  const mountedSkillCount = useMemo(
    () => skills.filter((skill) => skill.enabled !== false && selectedAgent?.skill_ids?.includes(skill.skill_id)).length,
    [selectedAgent, skills],
  );
  const enabledSkills = useMemo(() => skills.filter((skill) => skill.enabled !== false), [skills]);
  const disabledMountedSkills = useMemo(
    () => skills.filter((skill) => skill.enabled === false && selectedAgent?.skill_ids?.includes(skill.skill_id)),
    [selectedAgent, skills],
  );

  const refresh = useCallback(async (options: StudioRefreshOptions = {}) => {
    const [nextAgents, nextSkills, nextProfiles, nextWorkflows, nextRunnables, nextRuns] = await Promise.all([
      listAgents(),
      listSkills(),
      listModelProfiles(),
      listWorkflows(),
      listRunnables(),
      listRuns(),
    ]);
    setAgents(nextAgents);
    setSkills(nextSkills);
    setModelProfiles(nextProfiles.profiles || []);
    setWorkflows(nextWorkflows);
    setRunnables(nextRunnables);
    setRuns(nextRuns);
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
      return nextRunnables[0]?.id || '';
    });
    setSelectedRunId((current) => {
      const desired = options.selectedRunId !== undefined ? options.selectedRunId : current;
      if (desired) return desired;
      return options.selectFirstRun && nextRuns.length ? nextRuns[0].run_id : '';
    });
  }, []);

  useEffect(() => {
    setLoading(true);
    refresh({ selectFirstAgent: true, selectFirstWorkflow: true, selectFirstRun: true })
      .then(() => setError(''))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '读取 Agent Studio 失败'))
      .finally(() => setLoading(false));
  }, [refresh]);

  useEffect(() => {
    if (selectedAgent) setDraft(agentToDraft(selectedAgent));
  }, [selectedAgent]);

  useEffect(() => {
    if (!selectedRunId || selectedRun) return;
    let disposed = false;
    getRun(selectedRunId)
      .then((run) => {
        if (!disposed) setRuns((current) => [run, ...current.filter((item) => item.run_id !== run.run_id)]);
      })
      .catch(() => undefined);
    return () => {
      disposed = true;
    };
  }, [selectedRun, selectedRunId]);

  useEffect(() => {
    setArtifactPreview(null);
  }, [selectedRunId]);

  useEffect(() => {
    setNodes(workflowNodes(selectedWorkflow));
    setEdges(workflowEdges(selectedWorkflow));
    setWorkflowName(selectedWorkflow?.name || 'New Workflow');
    setWorkflowDescription(selectedWorkflow?.description || '');
  }, [selectedWorkflow, setEdges, setNodes]);

  const onConnect = useCallback(
    (connection: Connection) => {
      setEdges((current) => addEdge({ ...connection, id: `edge-${connection.source}-${connection.target}` }, current));
    },
    [setEdges],
  );

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
    setStatus('正在编辑新的 Workflow 草稿');
    setError('');
  }

  function selectWorkflow(workflowId: string) {
    setSelectedWorkflowId(workflowId);
    setStatus('');
    setError('');
  }

  async function runAction(action: () => Promise<StudioRefreshOptions | void>, label: string) {
    setBusyAction(label);
    setStatus(`${label}...`);
    setError('');
    try {
      const refreshOptions = await action();
      await refresh(refreshOptions || {});
      setStatus(`${label} 完成`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} 失败`);
    } finally {
      setBusyAction('');
    }
  }

  async function pickSkillSources() {
    setBusyAction('选择 Skill 文件');
    setError('');
    try {
      const selected = await chooseSkillSources();
      if (selected.length) {
        setSkillImportText((current) => appendSkillSources(current, selected));
        setStatus(`已选择 ${selected.length} 个 Skill 来源`);
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : '选择 Skill 文件失败');
    } finally {
      setBusyAction('');
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
      setSkillImportText((current) => appendSkillSources(current, filePaths));
      setStatus(`已添加 ${filePaths.length} 个待导入 Skill`);
    }
  }

  async function importSkillSources(): Promise<StudioRefreshOptions | void> {
    const sources = parseSkillSources(skillImportText);
    if (!sources.length) throw new Error('请先选择或输入 Skill 目录/ZIP 路径');
    const existingPaths = new Set(skills.flatMap((skill) => [skill.local_path, skill.source_path]).filter(Boolean).map(String));
    const results: SkillImportResult[] = [];
    for (const source of sources) {
      if (existingPaths.has(source) || existingPaths.has(localSourceAlias(source))) {
        results.push({ source, status: 'skipped', message: '已存在，跳过' });
        continue;
      }
      try {
        const imported = await importSkill(source);
        results.push({ source, status: 'success', message: `已导入 ${imported.name}` });
      } catch (err) {
        results.push({ source, status: 'failed', message: err instanceof Error ? err.message : '导入失败' });
      }
    }
    setSkillImportResults(results);
    if (results.some((item) => item.status === 'success')) {
      setSkillImportText('');
    }
  }

  async function saveAgent(): Promise<StudioRefreshOptions> {
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

  async function saveWorkflow(): Promise<StudioRefreshOptions> {
    const request: Partial<WorkflowSpec> = {
      name: workflowName,
      description: workflowDescription,
      nodes: nodes.map((node) => ({
        id: node.id,
        type: String(node.data?.kind || (node.type === 'input' ? 'start' : node.type === 'output' ? 'artifact' : 'agent')),
        position: node.position,
        data: node.data as Record<string, unknown>,
      })),
      edges: edges.map((edge) => ({
        id: edge.id,
        source: edge.source,
        target: edge.target,
      })),
      enabled: true,
    };
    const saved = selectedWorkflow ? await updateWorkflow(selectedWorkflow.workflow_id, request) : await createWorkflow(request);
    setSelectedWorkflowId(saved.workflow_id);
    return { selectedWorkflowId: saved.workflow_id };
  }

  async function runCurrentAgent(): Promise<StudioRefreshOptions> {
    if (!draft.agent_id) throw new Error('请先保存 Agent，再运行。');
    const goal = agentRunGoal.trim();
    if (!goal) throw new Error('运行目标不能为空');
    const run = await createAgentRun(draft.agent_id, goal);
    setAgentRunGoal('');
    setRunTarget(draft.agent_id);
    setSelectedRunId(run.run_id);
    setTab('runs');
    return { selectedAgentId: draft.agent_id, runTarget: draft.agent_id, selectedRunId: run.run_id };
  }

  async function runCurrentWorkflow(): Promise<StudioRefreshOptions> {
    if (!selectedWorkflow) throw new Error('请先保存 Workflow，再运行。');
    const goal = workflowRunGoal.trim();
    if (!goal) throw new Error('运行目标不能为空');
    const run = await createWorkflowRun(selectedWorkflow.workflow_id, goal);
    setWorkflowRunGoal('');
    setRunTarget(selectedWorkflow.workflow_id);
    setSelectedRunId(run.run_id);
    setTab('runs');
    return { selectedWorkflowId: selectedWorkflow.workflow_id, runTarget: selectedWorkflow.workflow_id, selectedRunId: run.run_id };
  }

  function addFlowNode(kind: 'agent' | 'approval' | 'artifact') {
    const id = `${kind}-${Date.now().toString(36)}`;
    const agent = agents[0];
    setNodes((current) => [
      ...current,
      {
        id,
        type: kind === 'artifact' ? 'output' : 'default',
        position: { x: 120 + current.length * 180, y: 140 },
        data: {
          label: kind === 'agent' ? agent?.name || 'Agent' : kind === 'approval' ? '人工审批' : 'Artifact',
          kind,
          ...(kind === 'agent' && agent ? { agent_id: agent.agent_id } : {}),
        },
      },
    ]);
  }

  async function openArtifact(run: RunSpec, path: string) {
    setStatus('读取 artifact...');
    setError('');
    try {
      const payload = await getRunArtifact(run.run_id, path);
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

  async function approveSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择待审批 Run');
    const run = await approveRunApproval(selectedRun.run_id);
    setSelectedRunId(run.run_id);
    return { selectedRunId: run.run_id };
  }

  async function rejectSelectedRun(): Promise<StudioRefreshOptions> {
    if (!selectedRun) throw new Error('请选择待审批 Run');
    const run = await rejectRunApproval(selectedRun.run_id);
    setSelectedRunId(run.run_id);
    return { selectedRunId: run.run_id };
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
        {(['agents', 'skills', 'workflows', 'runs'] as StudioTab[]).map((item) => (
          <button
            type="button"
            className={tab === item ? 'active' : ''}
            key={item}
            onClick={() => setTab(item)}
          >
            {item === 'agents' ? 'Agents' : item === 'skills' ? 'Skill Library' : item === 'workflows' ? 'Workflow Studio' : 'Runs'}
          </button>
        ))}
      </div>

      {loading ? <div className="notice">正在读取 Agent Studio...</div> : null}
      {status ? <div className="notice">{status}</div> : null}
      {error ? <div className="notice danger">{error}</div> : null}

      {tab === 'agents' ? (
        <section className="agent-studio-grid">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Agents</h2>
              <button type="button" disabled={busy} onClick={startNewAgent}>新建</button>
            </div>
            <div className="agent-list">
              {agents.map((agent) => (
                <button
                  type="button"
                  className={agent.agent_id === selectedAgentId ? 'active' : ''}
                  key={agent.agent_id}
                  onClick={() => selectAgent(agent.agent_id)}
                >
                  <span className="agent-list-profile">
                    <AgentAvatar avatarUrl={agent.avatar_url} name={agent.nickname || agent.name} />
                    <span>
                      <strong>{agent.nickname || agent.name}</strong>
                      <small>{agent.name}</small>
                    </span>
                  </span>
                  <span>{agent.category || 'custom'} · {agent.model_mode === 'custom_api' ? 'Custom API' : 'Chat Profile'}</span>
                </button>
              ))}
            </div>
          </aside>
          <form className="agent-studio-panel agent-editor" onSubmit={(event) => { event.preventDefault(); void runAction(saveAgent, '保存 Agent'); }}>
            <div className="section-heading-row">
              <h2>{draft.agent_id ? '编辑 Agent' : '新建 Agent'}</h2>
              {draft.agent_id ? <button type="button" className="danger-action" disabled={busy} onClick={() => void runAction(async () => { await deleteAgent(draft.agent_id || ''); setSelectedAgentId(''); setDraft({ ...emptyAgentDraft }); return { selectedAgentId: '' }; }, '删除 Agent')}>删除</button> : null}
            </div>
            <div className="agent-profile-editor">
              <AgentAvatar avatarUrl={draft.avatar_url} name={draft.nickname || draft.name || 'Agent'} />
              <div className="agent-profile-fields">
                <div className="agent-form-row">
                  <label><span>Name</span><input className="hy-input" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label>
                  <label><span>Nickname</span><input className="hy-input" value={draft.nickname} onChange={(event) => setDraft({ ...draft, nickname: event.target.value })} placeholder="对话框里显示的称呼" /></label>
                </div>
                <div className="agent-avatar-input-row">
                  <label><span>Avatar URL / data URL</span><input className="hy-input" value={draft.avatar_url} onChange={(event) => setDraft({ ...draft, avatar_url: event.target.value })} placeholder="https://... 或 data:image/..." /></label>
                  <button type="button" className="hy-btn hy-btn-ghost" disabled={busy} onClick={() => void pickAgentAvatar()}>选择头像</button>
                </div>
                <label><span>Description</span><input className="hy-input" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
              </div>
            </div>
            <div className="agent-form-row">
              <label><span>Category</span><input className="hy-input" value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })} /></label>
              <label>
                <span>Output Contract</span>
                <select className="hy-select" value={draft.output_contract} onChange={(event) => setDraft({ ...draft, output_contract: event.target.value })}>
                  <option value="chat">chat</option>
                  <option value="markdown">markdown</option>
                  <option value="diff">diff</option>
                  <option value="report">report</option>
                  <option value="artifacts">artifacts</option>
                </select>
                <small className="agent-field-help">约束最终回复倾向，不是 Skill 的输出类型。</small>
              </label>
            </div>
            <label>
              <span>Functional Instructions</span>
              <textarea className="hy-input agent-textarea" value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} />
              <small className="agent-field-help">写任务边界、工作方法、必须遵守的功能要求。</small>
            </label>
            <label>
              <span>Persona Prompt</span>
              <textarea className="hy-input agent-textarea compact" value={draft.persona_prompt} onChange={(event) => setDraft({ ...draft, persona_prompt: event.target.value })} />
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
            </section>
            <div className="agent-form-row">
              <label>
                <span>Default Workdir</span>
                <input className="hy-input" value={draft.default_workdir} onChange={(event) => setDraft({ ...draft, default_workdir: event.target.value })} />
                <small className="agent-field-help">工具相对路径的基准目录；留空就是当前 Hermes-Yachiyo 工作区。</small>
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
              <button type="submit" className="primary-action" disabled={busy}>保存 Agent</button>
              {draft.agent_id ? <button type="button" disabled={busy} onClick={() => void runAction(async () => { const result = await testAgentModel(draft.agent_id || ''); setStatus(result.message || (result.ok ? '模型测试通过' : '模型测试失败')); }, '测试模型')}>测试模型</button> : null}
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
                <button type="button" className="primary-action" disabled={busy || !agentRunGoal.trim()} onClick={() => void runAction(runCurrentAgent, '运行 Agent')}>
                  运行当前 Agent
                </button>
              </section>
            ) : (
              <div className="agent-inline-note">保存 Agent 后即可在这里直接运行，并在 Runs 中查看结果和 artifacts。</div>
            )}
            {draft.agent_id ? (
              <div className="agent-skill-mounts">
                <div className="agent-skill-mounts-head">
                  <h3>Mounted Skills</h3>
                  <span>{mountedSkillCount} mounted / {enabledSkills.length} enabled skills</span>
                </div>
                {disabledMountedSkills.length ? (
                  <div className="agent-inline-note warn">
                    有 {disabledMountedSkills.length} 个已挂载 Skill 当前已停用，运行时不会通过校验。
                  </div>
                ) : null}
                <div className="agent-skill-grid">
                  {enabledSkills.map((skill) => {
                    const mounted = selectedAgent?.skill_ids?.includes(skill.skill_id);
                    return (
                      <button
                        type="button"
                        className={mounted ? 'active' : ''}
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
                  {!enabledSkills.length ? <span className="agent-empty-inline">暂无启用 Skill，可到 Skill Library 导入或开启。</span> : null}
                </div>
              </div>
            ) : null}
          </form>
        </section>
      ) : null}

      {tab === 'skills' ? (
        <section className="agent-studio-grid">
          <div className="agent-studio-panel skill-import-panel">
            <div className="section-heading-row"><h2>上传 Skills</h2></div>
            <p className="agent-section-help">支持批量上传 zip 技能包，也支持选择本地 Skill 目录。系统会校验目录里是否包含 `SKILL.md`，并逐个返回导入结果。</p>
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
              <span>也可以点击选择文件，再从下面列表确认导入</span>
              <button type="button" disabled={busy} onClick={() => void pickSkillSources()}>选择文件</button>
            </div>
            <label>
              <span>待导入路径</span>
              <textarea
                className="hy-input skill-import-textarea"
                value={skillImportText}
                onChange={(event) => setSkillImportText(event.target.value)}
                placeholder="/path/to/skill-folder&#10;/path/to/skill.zip"
              />
            </label>
            <button type="button" className="primary-action" disabled={!skillImportText.trim() || busy} onClick={() => void runAction(importSkillSources, '导入 Skills')}>开始导入</button>
            {skillImportResults.length ? (
              <div className="skill-import-results" aria-label="Skill import results">
                {skillImportResults.map((result) => (
                  <div className={`skill-import-result ${result.status}`} key={`${result.source}-${result.status}`}>
                    <strong>{result.status === 'success' ? '成功' : result.status === 'skipped' ? '跳过' : '失败'}</strong>
                    <span>{result.source}</span>
                    <small>{result.message}</small>
                  </div>
                ))}
              </div>
            ) : null}
          </div>
          <div className="agent-studio-panel">
            <div className="section-heading-row"><h2>Skill Library</h2></div>
            <div className="skill-list">
              {skills.map((skill) => (
                <SkillCard
                  busy={busy}
                  key={skill.skill_id}
                  onDelete={() => runAction(async () => { await deleteSkill(skill.skill_id); }, '删除 Skill')}
                  onOpenLocation={() => runAction(async () => { await openPath(skill.local_path || ''); }, '打开 Skill 路径')}
                  onToggleEnabled={() => runAction(async () => { await updateSkill(skill.skill_id, { enabled: skill.enabled === false }); }, skill.enabled === false ? '启用 Skill' : '停用 Skill')}
                  skill={skill}
                />
              ))}
              {!skills.length ? <div className="empty-state inline-empty">暂无 Skill。导入后会在这里显示启停、删除和本地路径入口。</div> : null}
            </div>
          </div>
        </section>
      ) : null}

      {tab === 'workflows' ? (
        <section className="agent-studio-grid workflow-studio-grid">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Workflows</h2>
              <button type="button" disabled={busy} onClick={startNewWorkflow}>新建</button>
            </div>
            <div className="agent-list">
              {workflows.map((workflow) => (
                <button
                  type="button"
                  className={workflow.workflow_id === selectedWorkflowId ? 'active' : ''}
                  key={workflow.workflow_id}
                  onClick={() => selectWorkflow(workflow.workflow_id)}
                >
                  <strong>{workflow.name}</strong>
                  <span>{workflow.nodes.length} nodes · {workflow.edges.length} edges</span>
                </button>
              ))}
            </div>
          </aside>
          <div className="agent-studio-panel workflow-editor">
            <div className="workflow-toolbar">
              <input className="hy-input" value={workflowName} onChange={(event) => setWorkflowName(event.target.value)} />
              <input className="hy-input" value={workflowDescription} onChange={(event) => setWorkflowDescription(event.target.value)} placeholder="Description" />
              <button type="button" onClick={() => addFlowNode('agent')}>Agent</button>
              <button type="button" onClick={() => addFlowNode('approval')}>Approval</button>
              <button type="button" onClick={() => addFlowNode('artifact')}>Artifact</button>
              <button type="button" className="primary-action" onClick={() => void runAction(saveWorkflow, '保存 Workflow')}>保存</button>
              {selectedWorkflow ? <button type="button" className="danger-action" onClick={() => void runAction(async () => { await deleteWorkflow(selectedWorkflow.workflow_id); startNewWorkflow(); return { selectedWorkflowId: '' }; }, '删除 Workflow')}>删除</button> : null}
            </div>
            <div className="workflow-canvas">
              <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} fitView>
                <MiniMap />
                <Controls />
                <Background />
              </ReactFlow>
            </div>
            <div className="workflow-node-settings">
              {nodes.filter((node) => node.data?.kind === 'agent').map((node) => (
                <label key={node.id}>
                  <span>{String(node.data?.label || node.id)} Agent</span>
                  <select
                    className="hy-select"
                    value={String(node.data?.agent_id || '')}
                    onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, agent_id: event.target.value, label: agents.find((agent) => agent.agent_id === event.target.value)?.name || item.data?.label } } : item))}
                  >
                    <option value="">选择 Agent</option>
                    {agents.map((agent) => <option value={agent.agent_id} key={agent.agent_id}>{agent.name}</option>)}
                  </select>
                </label>
              ))}
            </div>
            <section className="agent-quick-run">
              <div>
                <h3>Workflow Run</h3>
                <p>{selectedWorkflow ? '运行当前已保存 Workflow，完成后自动打开 Runs 详情。' : '新建 Workflow 需要先保存，保存后即可运行。'}</p>
              </div>
              <label>
                <span>Goal</span>
                <textarea
                  className="hy-input agent-run-textarea"
                  value={workflowRunGoal}
                  onChange={(event) => setWorkflowRunGoal(event.target.value)}
                  placeholder="例如：从设计到审查跑一遍这个任务"
                />
              </label>
              <button type="button" className="primary-action" disabled={busy || !selectedWorkflow || !workflowRunGoal.trim()} onClick={() => void runAction(runCurrentWorkflow, '运行 Workflow')}>
                {selectedWorkflow ? '运行当前 Workflow' : '先保存 Workflow'}
              </button>
            </section>
          </div>
        </section>
      ) : null}

      {tab === 'runs' ? (
        <section className="agent-studio-grid">
          <div className="agent-studio-panel">
            <div className="section-heading-row"><h2>Run Agent / Workflow</h2></div>
            <label>
              <span>Target</span>
              <select className="hy-select" value={runTarget} onChange={(event) => setRunTarget(event.target.value)}>
                {runnables.map((item) => <option value={item.id} key={item.id}>{item.kind}: {item.name}</option>)}
              </select>
            </label>
            <label><span>Goal</span><textarea className="hy-input agent-textarea" value={runGoal} onChange={(event) => setRunGoal(event.target.value)} /></label>
            <button type="button" className="primary-action" disabled={!runTarget || !runGoal.trim() || busy} onClick={() => void runAction(async () => {
              const target = runnables.find((item) => item.id === runTarget);
              if (!target) return;
              const run = target.kind === 'agent'
                ? await createAgentRun(target.id, runGoal)
                : await createWorkflowRun(target.id, runGoal);
              setSelectedRunId(run.run_id);
              setRunGoal('');
              return { selectedRunId: run.run_id, runTarget: target.id };
            }, '创建 Run')}>运行</button>
            <div className="run-list">
              {runs.map((run) => (
                <button
                  type="button"
                  className={run.run_id === selectedRunId ? 'run-list-item active' : 'run-list-item'}
                  key={run.run_id}
                  onClick={() => setSelectedRunId(run.run_id)}
                >
                  <strong>{run.runnable_name || run.runnable_id}</strong>
                  <span>{run.kind} · {run.status}</span>
                  <small>{run.user_goal}</small>
                </button>
              ))}
            </div>
          </div>
          <div className="agent-studio-panel">
            <div className="section-heading-row"><h2>Run Detail</h2></div>
            {selectedRun ? (
              <article className="run-detail">
                <div className="run-detail-title">
                  <div>
                    <h3>{selectedRun.runnable_name || selectedRun.runnable_id}</h3>
                    <p>{selectedRun.user_goal}</p>
                  </div>
                  <span className={`run-status-pill ${runStatusTone(selectedRun.status)}`}>{selectedRun.status}</span>
                </div>
                <div className="run-detail-meta">
                  <span>{runKindLabel(selectedRun.kind)}</span>
                  <span>Updated {formatRunDate(selectedRun.updated_at || selectedRun.created_at)}</span>
                  {selectedRun.run_group_id ? <span>Group {selectedRun.run_group_id}</span> : null}
                  <code>{selectedRun.run_id}</code>
                </div>
                {selectedRun.status === 'approval_required' && selectedRun.pending_approval?.tool ? (
                  <section className="run-approval-box">
                    <div>
                      <h4>Approval Required · {selectedRun.pending_approval.tool}</h4>
                      <p>这个工具调用需要人工确认后才会继续当前 Run。</p>
                    </div>
                    <pre>{formatApprovalInput(selectedRun.pending_approval.input_preview)}</pre>
                    <div className="run-approval-actions">
                      <button type="button" className="primary-action" disabled={busy} onClick={() => void runAction(approveSelectedRun, '批准工具调用')}>Approve</button>
                      <button type="button" className="danger-action" disabled={busy} onClick={() => void runAction(rejectSelectedRun, '拒绝工具调用')}>Reject</button>
                    </div>
                  </section>
                ) : null}
                <section>
                  <h4>Result</h4>
                  <pre>{selectedRun.result || 'No result yet.'}</pre>
                </section>
                <section>
                  <h4>Timeline · {(selectedRun.timeline || []).length}</h4>
                  <ol className="run-timeline">
                    {(selectedRun.timeline || []).map((event, index) => (
                      <li key={`${String(event.event || 'event')}-${index}`}>
                        <span>{String(event.event || 'event')}</span>
                        <small>{String(event.detail || '')}</small>
                      </li>
                    ))}
                  </ol>
                </section>
                <section>
                  <h4>Artifacts · {(selectedRun.artifacts || []).length}</h4>
                  <div className="run-artifacts">
                    {(selectedRun.artifacts || []).map((artifact, index) => {
                      const path = String(artifact.path || '');
                      return (
                        <button
                          type="button"
                          disabled={!path}
                          key={`${path}-${index}`}
                          onClick={() => path ? void openArtifact(selectedRun, path) : undefined}
                        >
                          {path || 'artifact'}
                        </button>
                      );
                    })}
                    {!selectedRun.artifacts?.length ? <span>No artifacts</span> : null}
                  </div>
                  {artifactPreview ? (
                    <div className="artifact-preview">
                      <strong>{artifactPreview.path}{artifactPreview.truncated ? ' · truncated' : ''}</strong>
                      <pre>{artifactPreview.content}</pre>
                    </div>
                  ) : null}
                </section>
              </article>
            ) : (
              <div className="empty-state inline-empty">暂无 Run；运行 Agent 或 Workflow 后会在这里显示 Result、Timeline 和 Artifacts。</div>
            )}
          </div>
        </section>
      ) : null}
    </section>
  );
}

function SkillCard({
  busy,
  onDelete,
  onOpenLocation,
  onToggleEnabled,
  skill,
}: {
  busy: boolean;
  onDelete: () => Promise<void>;
  onOpenLocation: () => Promise<void>;
  onToggleEnabled: () => Promise<void>;
  skill: SkillSpec;
}) {
  const enabled = skill.enabled !== false;
  return (
    <article className={enabled ? 'skill-card' : 'skill-card disabled'}>
      <div className="section-heading-row skill-card-head">
        <div>
          <h3>{skill.name}</h3>
          <span className="skill-source-tag">本地 Skill</span>
        </div>
        <label className={enabled ? 'skill-enable-switch active' : 'skill-enable-switch'}>
          <input
            type="checkbox"
            checked={enabled}
            disabled={busy}
            onChange={() => void onToggleEnabled()}
          />
          <span aria-hidden="true" />
        </label>
      </div>
      <p>{skill.description || skill.content_summary}</p>
      <div className="skill-card-path">
        <span>路径</span>
        <code>{skillPathLabel(skill)}</code>
      </div>
      {skill.asset_paths?.length ? <small>{skill.asset_paths.length} assets/templates</small> : null}
      <div className="skill-card-actions">
        <button type="button" disabled={busy || !skill.local_path} onClick={() => void onOpenLocation()}>打开路径</button>
        <button type="button" className="danger-action" disabled={busy} onClick={() => void onDelete()}>删除</button>
      </div>
      <pre>{(skill.skill_markdown || '').slice(0, 1200)}</pre>
    </article>
  );
}
