import { useCallback, useEffect, useMemo, useState } from 'react';
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
  testAgentModel,
  updateAgent,
  updateWorkflow,
  type AgentSpec,
  type RunnableSummary,
  type RunSpec,
  type SkillSpec,
  type WorkflowSpec,
} from '../lib/agents';
import { openAppView } from '../lib/bridge';
import { listModelProfiles, type ModelProfile } from '../lib/modelProfiles';
import { currentParam } from '../lib/view';

type StudioTab = 'agents' | 'skills' | 'workflows' | 'runs';

type AgentDraft = {
  agent_id?: string;
  name: string;
  description: string;
  avatar_url: string;
  category: string;
  instructions: string;
  model_mode: 'follow_main' | 'profile' | 'custom_api';
  model_profile_id: string;
  vision_model_profile_id: string;
  base_url: string;
  model: string;
  api_key: string;
  output_contract: string;
  default_workdir: string;
  readable_scopes: string;
  writable_scopes: string;
  enabled: boolean;
};

const emptyAgentDraft: AgentDraft = {
  name: '',
  description: '',
  avatar_url: '',
  category: 'custom',
  instructions: '',
  model_mode: 'follow_main',
  model_profile_id: '',
  vision_model_profile_id: '',
  base_url: '',
  model: '',
  api_key: '',
  output_contract: 'chat',
  default_workdir: '',
  readable_scopes: '.',
  writable_scopes: '',
  enabled: true,
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

function agentToDraft(agent: AgentSpec): AgentDraft {
  const workspace = agent.workspace_policy || {};
  return {
    agent_id: agent.agent_id,
    name: agent.name,
    description: agent.description || '',
    avatar_url: agent.avatar_url || '',
    category: agent.category || 'custom',
    instructions: agent.instructions || '',
    model_mode: agent.model_mode,
    model_profile_id: agent.model_profile_id || '',
    vision_model_profile_id: agent.vision_model_profile_id || '',
    base_url: agent.model_config?.base_url || '',
    model: agent.model_config?.model || '',
    api_key: '',
    output_contract: agent.output_contract || 'chat',
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
  const [skillPath, setSkillPath] = useState('');
  const [workflowName, setWorkflowName] = useState('New Workflow');
  const [workflowDescription, setWorkflowDescription] = useState('');
  const [runTarget, setRunTarget] = useState('');
  const [runGoal, setRunGoal] = useState('');
  const [selectedRunId, setSelectedRunId] = useState(() => currentParam('run'));
  const [artifactPreview, setArtifactPreview] = useState<{ path: string; content: string; truncated?: boolean } | null>(null);
  const [status, setStatus] = useState('');
  const [error, setError] = useState('');
  const [busy, setBusy] = useState(false);
  const [nodes, setNodes, onNodesChange] = useNodesState<Node>(starterNodes);
  const [edges, setEdges, onEdgesChange] = useEdgesState<Edge>([]);

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

  const refresh = useCallback(async () => {
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
    if (!selectedAgentId && nextAgents.length) setSelectedAgentId(nextAgents[0].agent_id);
    if (!selectedWorkflowId && nextWorkflows.length) setSelectedWorkflowId(nextWorkflows[0].workflow_id);
    if (!runTarget && nextRunnables.length) setRunTarget(nextRunnables[0].id);
    if (!selectedRunId && nextRuns.length) setSelectedRunId(nextRuns[0].run_id);
  }, [runTarget, selectedAgentId, selectedRunId, selectedWorkflowId]);

  useEffect(() => {
    setBusy(true);
    refresh()
      .then(() => setError(''))
      .catch((err: unknown) => setError(err instanceof Error ? err.message : '读取 Agent Studio 失败'))
      .finally(() => setBusy(false));
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

  async function runAction(action: () => Promise<void>, label: string) {
    setBusy(true);
    setStatus(label);
    setError('');
    try {
      await action();
      await refresh();
      setStatus(`${label} 完成`);
    } catch (err) {
      setError(err instanceof Error ? err.message : `${label} 失败`);
    } finally {
      setBusy(false);
    }
  }

  async function saveAgent() {
    if (draft.model_mode === 'profile' && !draft.model_profile_id) {
      throw new Error('请选择模型组，或改为 follow_main。');
    }
    const request: Partial<AgentSpec> = {
      name: draft.name,
      description: draft.description,
      avatar_url: draft.avatar_url,
      category: draft.category,
      instructions: draft.instructions,
      model_mode: draft.model_mode,
      model_profile_id: draft.model_mode === 'profile' ? draft.model_profile_id : '',
      vision_model_profile_id: draft.vision_model_profile_id,
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
  }

  async function saveWorkflow() {
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

      {busy ? <div className="notice">处理中...</div> : null}
      {status ? <div className="notice">{status}</div> : null}
      {error ? <div className="notice danger">{error}</div> : null}

      {tab === 'agents' ? (
        <section className="agent-studio-grid">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Agents</h2>
              <button type="button" onClick={() => { setSelectedAgentId(''); setDraft(emptyAgentDraft); }}>新建</button>
            </div>
            <div className="agent-list">
              {agents.map((agent) => (
                <button
                  type="button"
                  className={agent.agent_id === selectedAgentId ? 'active' : ''}
                  key={agent.agent_id}
                  onClick={() => setSelectedAgentId(agent.agent_id)}
                >
                  <strong>{agent.name}</strong>
                  <span>{agent.category || 'custom'} · {agent.model_mode}</span>
                </button>
              ))}
            </div>
          </aside>
          <form className="agent-studio-panel agent-editor" onSubmit={(event) => { event.preventDefault(); void runAction(saveAgent, '保存 Agent'); }}>
            <div className="section-heading-row">
              <h2>{draft.agent_id ? '编辑 Agent' : '新建 Agent'}</h2>
              {draft.agent_id ? <button type="button" className="danger-action" onClick={() => void runAction(async () => { await deleteAgent(draft.agent_id || ''); setSelectedAgentId(''); setDraft(emptyAgentDraft); }, '删除 Agent')}>删除</button> : null}
            </div>
            <label><span>Name</span><input className="hy-input" value={draft.name} onChange={(event) => setDraft({ ...draft, name: event.target.value })} required /></label>
            <label><span>Description</span><input className="hy-input" value={draft.description} onChange={(event) => setDraft({ ...draft, description: event.target.value })} /></label>
            <div className="agent-form-row">
              <label><span>Category</span><input className="hy-input" value={draft.category} onChange={(event) => setDraft({ ...draft, category: event.target.value })} /></label>
              <label>
                <span>Output</span>
                <select className="hy-select" value={draft.output_contract} onChange={(event) => setDraft({ ...draft, output_contract: event.target.value })}>
                  <option value="chat">chat</option>
                  <option value="markdown">markdown</option>
                  <option value="diff">diff</option>
                  <option value="report">report</option>
                  <option value="artifacts">artifacts</option>
                </select>
              </label>
            </div>
            <label>
              <span>Instructions</span>
              <textarea className="hy-input agent-textarea" value={draft.instructions} onChange={(event) => setDraft({ ...draft, instructions: event.target.value })} />
            </label>
            <div className="agent-form-row">
              <label>
                <span>Model Mode</span>
                <select className="hy-select" value={draft.model_mode} onChange={(event) => setDraft({ ...draft, model_mode: event.target.value as AgentDraft['model_mode'] })}>
                  <option value="follow_main">follow_main</option>
                  <option value="profile">model_profile</option>
                  {draft.model_mode === 'custom_api' ? <option value="custom_api">legacy_custom_api</option> : null}
                </select>
              </label>
              {draft.model_mode === 'profile' ? (
                <label>
                  <span>Model Profile</span>
                  <select className="hy-select" value={draft.model_profile_id} onChange={(event) => setDraft({ ...draft, model_profile_id: event.target.value })}>
                    <option value="">选择已保存模型组</option>
                    {chatModelProfiles.map((profile) => (
                      <option key={profile.profile_id} value={profile.profile_id}>
                        {profile.name} · {profile.model || profile.provider}
                      </option>
                    ))}
                  </select>
                </label>
              ) : draft.model_mode === 'custom_api' ? (
                <label><span>Model</span><input className="hy-input" value={draft.model} onChange={(event) => setDraft({ ...draft, model: event.target.value })} placeholder="gpt-4.1-mini" /></label>
              ) : (
                <label><span>Model Profile</span><button type="button" className="hy-btn hy-btn-ghost" onClick={() => openAppView('provider')}>管理模型组</button></label>
              )}
            </div>
            {draft.model_mode === 'profile' && !chatModelProfiles.length ? (
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
                <label><span>Base URL</span><input className="hy-input" value={draft.base_url} onChange={(event) => setDraft({ ...draft, base_url: event.target.value })} placeholder="https://api.example.com/v1" /></label>
                <label><span>API Key</span><input className="hy-input" type="password" value={draft.api_key} onChange={(event) => setDraft({ ...draft, api_key: event.target.value })} placeholder={selectedAgent?.model_config.api_key_configured ? '已配置，留空不覆盖' : '保存到后端'} /></label>
              </div>
            ) : null}
            <div className="agent-form-row">
              <label><span>Default Workdir</span><input className="hy-input" value={draft.default_workdir} onChange={(event) => setDraft({ ...draft, default_workdir: event.target.value })} /></label>
              <label><span>Writable Scopes</span><input className="hy-input" value={draft.writable_scopes} onChange={(event) => setDraft({ ...draft, writable_scopes: event.target.value })} placeholder="src, tests" /></label>
            </div>
            <label><span>Readable Scopes</span><input className="hy-input" value={draft.readable_scopes} onChange={(event) => setDraft({ ...draft, readable_scopes: event.target.value })} /></label>
            <div className="agent-editor-actions">
              <button type="submit" className="primary-action" disabled={busy}>保存 Agent</button>
              {draft.agent_id ? <button type="button" disabled={busy} onClick={() => void runAction(async () => { const result = await testAgentModel(draft.agent_id || ''); setStatus(result.message || (result.ok ? '模型测试通过' : '模型测试失败')); }, '测试模型')}>测试模型</button> : null}
            </div>
            {draft.agent_id ? (
              <div className="agent-skill-mounts">
                <h3>Mounted Skills</h3>
                <div className="agent-skill-grid">
                  {skills.map((skill) => {
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
                </div>
              </div>
            ) : null}
          </form>
        </section>
      ) : null}

      {tab === 'skills' ? (
        <section className="agent-studio-grid">
          <div className="agent-studio-panel">
            <div className="section-heading-row"><h2>Import Skill</h2></div>
            <label><span>Local directory or ZIP</span><input className="hy-input" value={skillPath} onChange={(event) => setSkillPath(event.target.value)} placeholder="/path/to/skill-or.zip" /></label>
            <button type="button" className="primary-action" disabled={!skillPath.trim() || busy} onClick={() => void runAction(async () => { await importSkill(skillPath.trim()); setSkillPath(''); }, '导入 Skill')}>导入</button>
          </div>
          <div className="agent-studio-panel">
            <div className="section-heading-row"><h2>Skill Library</h2></div>
            <div className="skill-list">
              {skills.map((skill) => (
                <SkillCard
                  agent={selectedAgent}
                  busy={busy}
                  key={skill.skill_id}
                  onDelete={() => runAction(async () => { await deleteSkill(skill.skill_id); }, '删除 Skill')}
                  onToggleMount={() => runAction(async () => {
                    if (!selectedAgent) return;
                    if (selectedAgent.skill_ids?.includes(skill.skill_id)) await detachSkill(selectedAgent.agent_id, skill.skill_id);
                    else await attachSkill(selectedAgent.agent_id, skill.skill_id);
                  }, selectedAgent?.skill_ids?.includes(skill.skill_id) ? '移除 Skill' : '挂载 Skill')}
                  skill={skill}
                />
              ))}
            </div>
          </div>
        </section>
      ) : null}

      {tab === 'workflows' ? (
        <section className="agent-studio-grid workflow-studio-grid">
          <aside className="agent-studio-panel">
            <div className="section-heading-row">
              <h2>Workflows</h2>
              <button type="button" onClick={() => { setSelectedWorkflowId(''); setNodes(starterNodes); setEdges([]); setWorkflowName('New Workflow'); setWorkflowDescription(''); }}>新建</button>
            </div>
            <div className="agent-list">
              {workflows.map((workflow) => (
                <button
                  type="button"
                  className={workflow.workflow_id === selectedWorkflowId ? 'active' : ''}
                  key={workflow.workflow_id}
                  onClick={() => setSelectedWorkflowId(workflow.workflow_id)}
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
              {selectedWorkflow ? <button type="button" className="danger-action" onClick={() => void runAction(async () => { await deleteWorkflow(selectedWorkflow.workflow_id); setSelectedWorkflowId(''); }, '删除 Workflow')}>删除</button> : null}
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
                <div className="run-detail-meta">
                  <span>{selectedRun.kind}</span>
                  <span>{selectedRun.status}</span>
                  <code>{selectedRun.run_id}</code>
                </div>
                <h3>{selectedRun.runnable_name || selectedRun.runnable_id}</h3>
                <p>{selectedRun.user_goal}</p>
                <section>
                  <h4>Result</h4>
                  <pre>{selectedRun.result || 'No result yet.'}</pre>
                </section>
                <section>
                  <h4>Timeline</h4>
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
                  <h4>Artifacts</h4>
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
              <div className="empty-state inline-empty">暂无 Run</div>
            )}
          </div>
        </section>
      ) : null}
    </section>
  );
}

function SkillCard({
  agent,
  busy,
  onDelete,
  onToggleMount,
  skill,
}: {
  agent: AgentSpec | null;
  busy: boolean;
  onDelete: () => Promise<void>;
  onToggleMount: () => Promise<void>;
  skill: SkillSpec;
}) {
  const mounted = Boolean(agent?.skill_ids?.includes(skill.skill_id));
  return (
    <article className="skill-card">
      <div className="section-heading-row">
        <div><h3>{skill.name}</h3><span>{skill.source_path}</span></div>
        <button type="button" className="danger-action" onClick={() => void onDelete()}>删除</button>
      </div>
      <p>{skill.description || skill.content_summary}</p>
      {skill.asset_paths?.length ? <small>{skill.asset_paths.length} assets/templates</small> : null}
      <div className="skill-card-actions">
        <button type="button" disabled={!agent || busy} onClick={() => void onToggleMount()}>
          {mounted ? `从 ${agent?.name || 'Agent'} 移除` : agent ? `挂载到 ${agent.name}` : '先选择 Agent'}
        </button>
      </div>
      <pre>{(skill.skill_markdown || '').slice(0, 1200)}</pre>
    </article>
  );
}
