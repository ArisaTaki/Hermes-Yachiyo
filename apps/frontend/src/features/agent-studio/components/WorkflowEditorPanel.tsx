import type { Dispatch, SetStateAction } from 'react';
import type { Edge, Node, OnConnect, OnEdgesChange, OnNodesChange } from '@xyflow/react';

import type { AgentSpec, WorkflowSpec } from '../../../lib/agents';
import { WorkflowCanvas } from './WorkflowCanvas';

type WorkflowStepKind = 'start' | 'agent' | 'approval' | 'artifact' | 'condition' | 'parallel' | 'workflow' | 'loop' | 'unknown';

export type WorkflowPreviewStep = {
  key: string;
  kind: WorkflowStepKind;
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

type WorkflowNodeKindToAdd = 'agent' | 'approval' | 'artifact' | 'workflow' | 'loop';

type WorkflowEditorPanelProps = {
  agents: AgentSpec[];
  agentCapabilityLine: (agent: AgentSpec) => string;
  agentIssueById: Map<string, string>;
  allWorkflowsSelected: boolean;
  busy: boolean;
  edges: Edge[];
  nodes: Node[];
  onAddFlowNode: (kind: WorkflowNodeKindToAdd, agentId?: string) => void;
  onConnect: OnConnect;
  onDeleteSelectedWorkflows: () => void;
  onDeleteWorkflow: () => void;
  onEdgesChange: OnEdgesChange;
  onFinishWorkflowManagement: () => void;
  onLoadTemplate: () => void;
  onNewWorkflow: () => void;
  onNodesChange: OnNodesChange;
  onRemoveFlowNode: (nodeId: string) => void;
  onRunWorkflow: () => void;
  onSaveWorkflow: () => void;
  onSelectWorkflow: (workflowId: string) => void;
  onSetSelectedWorkflowIds: (workflowIds: string[]) => void;
  onStartWorkflowManagement: () => void;
  onToggleWorkflowSelected: (workflowId: string) => void;
  selectedWorkflow: WorkflowSpec | null;
  selectedWorkflowIdSet: Set<string>;
  selectedWorkflows: WorkflowSpec[];
  setNodes: Dispatch<SetStateAction<Node[]>>;
  setWorkflowDescription: (description: string) => void;
  setWorkflowEnabled: (enabled: boolean) => void;
  setWorkflowName: (name: string) => void;
  setWorkflowRunGoal: (goal: string) => void;
  workflowDescription: string;
  workflowEnabled: boolean;
  workflowErrors: string[];
  workflowHasErrors: boolean;
  workflowIds: string[];
  workflowManagementMode: boolean;
  workflowName: string;
  workflowPrimaryError: string;
  workflowRunDisabled: boolean;
  workflowRunDisabledReason: string;
  workflowRunGoal: string;
  workflowRunPreviewSteps: WorkflowPreviewStep[];
  workflows: WorkflowSpec[];
  workflowValidation: WorkflowValidationReport;
};

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
  if (kind === 'condition') return 'Condition';
  if (kind === 'parallel') return 'Parallel';
  if (kind === 'workflow') return 'Workflow';
  if (kind === 'loop') return 'Loop';
  if (kind === 'start') return 'Start';
  return kind || 'Node';
}

function workflowStepKindLabel(kind: WorkflowStepKind): string {
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

function workflowLoopMaxIterations(data: Record<string, unknown> | undefined): number {
  if (!data) return 3;
  const raw = data.max_iterations || data.maxIterations || data.iteration_limit || data.iterationLimit || data.limit || 3;
  const value = Number(raw);
  if (!Number.isFinite(value)) return 3;
  return Math.max(1, Math.min(Math.round(value), 25));
}

export function WorkflowRunPreview({
  agents,
  agentCapabilityLine,
  agentIssueById,
  sourceNodes,
  steps,
}: {
  agents: AgentSpec[];
  agentCapabilityLine: (agent: AgentSpec) => string;
  agentIssueById: Map<string, string>;
  sourceNodes: Node[];
  steps: WorkflowPreviewStep[];
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
                : step.kind === 'condition'
                  ? step.task || '根据上游上下文选择 true/false 分支。'
                  : step.kind === 'parallel'
                    ? '并行执行多个分支，并把结果汇总到后续节点。'
                    : step.kind === 'workflow'
                      ? step.task || '运行子 Workflow，并把结果传给后续节点。'
                      : step.kind === 'loop'
                        ? step.task || '根据上游上下文决定继续循环或退出。'
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

export function WorkflowEditorPanel({
  agents,
  agentCapabilityLine,
  agentIssueById,
  allWorkflowsSelected,
  busy,
  edges,
  nodes,
  onAddFlowNode,
  onConnect,
  onDeleteSelectedWorkflows,
  onDeleteWorkflow,
  onEdgesChange,
  onFinishWorkflowManagement,
  onLoadTemplate,
  onNewWorkflow,
  onNodesChange,
  onRemoveFlowNode,
  onRunWorkflow,
  onSaveWorkflow,
  onSelectWorkflow,
  onSetSelectedWorkflowIds,
  onStartWorkflowManagement,
  onToggleWorkflowSelected,
  selectedWorkflow,
  selectedWorkflowIdSet,
  selectedWorkflows,
  setNodes,
  setWorkflowDescription,
  setWorkflowEnabled,
  setWorkflowName,
  setWorkflowRunGoal,
  workflowDescription,
  workflowEnabled,
  workflowErrors,
  workflowHasErrors,
  workflowIds,
  workflowManagementMode,
  workflowName,
  workflowPrimaryError,
  workflowRunDisabled,
  workflowRunDisabledReason,
  workflowRunGoal,
  workflowRunPreviewSteps,
  workflows,
  workflowValidation,
}: WorkflowEditorPanelProps) {
  return (
    <section className="agent-studio-grid workflow-studio-grid" data-testid="workflow-studio">
      <aside className="agent-studio-panel">
        <div className="section-heading-row">
          <h2>Workflows</h2>
          <div className="studio-heading-actions">
            {workflows.length && !workflowManagementMode ? (
              <button type="button" data-testid="workflow-list-manage" disabled={busy} onClick={onStartWorkflowManagement}>
                管理
              </button>
            ) : null}
            <button type="button" data-testid="workflow-new" disabled={busy} onClick={onNewWorkflow}>新建</button>
          </div>
        </div>
        {workflows.length && workflowManagementMode ? (
          <div className="studio-bulk-actions" aria-label="Workflow 批量操作" data-testid="workflow-bulk-actions">
            <span>{selectedWorkflows.length ? `已选择 ${selectedWorkflows.length} / ${workflows.length}` : `${workflows.length} workflows`}</span>
            <button type="button" data-testid="workflow-select-all" disabled={busy} onClick={() => onSetSelectedWorkflowIds(allWorkflowsSelected ? [] : workflowIds)}>
              {allWorkflowsSelected ? '取消全选' : '全选当前列表'}
            </button>
            <button type="button" data-testid="workflow-clear-selection" disabled={busy || !selectedWorkflows.length} onClick={() => onSetSelectedWorkflowIds([])}>清空</button>
            <button type="button" className="danger-action" data-testid="workflow-delete-selected" disabled={busy || !selectedWorkflows.length} onClick={onDeleteSelectedWorkflows}>删除所选</button>
            <button type="button" data-testid="workflow-finish-management" disabled={busy} onClick={onFinishWorkflowManagement}>完成</button>
          </div>
        ) : null}
        <div className={workflowManagementMode ? 'agent-list managing' : 'agent-list'} data-testid="workflow-list">
          {workflows.map((workflow) => (
            <div
              className={workflow.workflow_id === selectedWorkflow?.workflow_id ? 'agent-list-item active' : 'agent-list-item'}
              data-testid="workflow-list-item"
              key={workflow.workflow_id}
            >
              <label className="agent-list-select" aria-label={`选择 Workflow ${workflow.name}`}>
                <input
                  type="checkbox"
                  data-testid="workflow-list-checkbox"
                  checked={selectedWorkflowIdSet.has(workflow.workflow_id)}
                  disabled={busy || !workflowManagementMode}
                  onChange={() => onToggleWorkflowSelected(workflow.workflow_id)}
                />
              </label>
              <button
                type="button"
                className="agent-list-main"
                data-testid="workflow-list-open"
                onClick={() => onSelectWorkflow(workflow.workflow_id)}
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
            onClick={onLoadTemplate}
          >
            全线测试模板
          </button>
          <button type="button" data-testid="workflow-add-agent-node" disabled={busy} onClick={() => onAddFlowNode('agent')}>Agent</button>
          <button type="button" data-testid="workflow-add-approval-node" disabled={busy} onClick={() => onAddFlowNode('approval')}>Approval</button>
          <button type="button" data-testid="workflow-add-artifact-node" disabled={busy} onClick={() => onAddFlowNode('artifact')}>Artifact</button>
          <button type="button" data-testid="workflow-add-workflow-node" disabled={busy} onClick={() => onAddFlowNode('workflow')}>Workflow</button>
          <button type="button" data-testid="workflow-add-loop-node" disabled={busy} onClick={() => onAddFlowNode('loop')}>Loop</button>
          <button
            type="button"
            className="primary-action"
            data-testid="workflow-save"
            disabled={busy || workflowHasErrors}
            title={workflowPrimaryError || undefined}
            onClick={onSaveWorkflow}
          >
            保存
          </button>
          {selectedWorkflow ? <button type="button" className="danger-action" data-testid="workflow-delete" onClick={onDeleteWorkflow}>删除</button> : null}
        </div>
        <div className="workflow-agent-palette" aria-label="从 Agents 添加到 Workflow" data-testid="workflow-agent-palette">
          <span>添加 Agent</span>
          {agents.map((agent) => (
            <button
              type="button"
              data-testid="workflow-agent-palette-item"
              disabled={busy || agent.enabled === false}
              key={agent.agent_id}
              onClick={() => onAddFlowNode('agent', agent.agent_id)}
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
        <WorkflowCanvas
          edges={edges}
          nodes={nodes}
          onConnect={onConnect}
          onEdgesChange={onEdgesChange}
          onNodesChange={onNodesChange}
        />
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
            const selectedNodeAgentIssue = selectedNodeAgent ? agentIssueById.get(selectedNodeAgent.agent_id) || '' : '';
            const selectedNodeWorkflowId = kind === 'workflow'
              ? workflowChildWorkflowIdFromData(node.data as Record<string, unknown> | undefined)
              : '';
            const selectedNodeWorkflow = selectedNodeWorkflowId
              ? workflows.find((workflow) => workflow.workflow_id === selectedNodeWorkflowId) || null
              : null;
            const childWorkflowOptions = workflows.filter((workflow) => workflow.workflow_id !== selectedWorkflow?.workflow_id);
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
                  {kind === 'loop' ? (
                    <>
                      <label>
                        <span>Loop Condition</span>
                        <textarea
                          className="hy-input agent-textarea compact"
                          data-testid="workflow-node-loop-condition-input"
                          value={workflowConditionText(node.data as Record<string, unknown> | undefined)}
                          onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, condition: event.target.value } } : item))}
                        />
                      </label>
                      <label>
                        <span>Max Iterations</span>
                        <input
                          className="hy-input"
                          data-testid="workflow-node-loop-max-iterations-input"
                          type="number"
                          min={1}
                          max={25}
                          value={workflowLoopMaxIterations(node.data as Record<string, unknown> | undefined)}
                          onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, max_iterations: workflowLoopMaxIterations({ max_iterations: event.target.value }) } } : item))}
                        />
                      </label>
                    </>
                  ) : null}
                  {kind === 'workflow' ? (
                    <>
                      <label>
                        <span>Workflow</span>
                        <select
                          className="hy-select"
                          data-testid="workflow-node-workflow-select"
                          value={selectedNodeWorkflowId}
                          onChange={(event) => {
                            const nextWorkflow = workflows.find((workflow) => workflow.workflow_id === event.target.value) || null;
                            setNodes((current) => current.map((item) => item.id === node.id ? {
                              ...item,
                              data: {
                                ...item.data,
                                workflow_id: event.target.value,
                                label: nextWorkflow?.name || item.data?.label,
                              },
                            } : item));
                          }}
                        >
                          <option value="">选择子 Workflow</option>
                          {childWorkflowOptions.map((workflow) => (
                            <option value={workflow.workflow_id} key={workflow.workflow_id} disabled={workflow.enabled === false}>
                              {workflow.name}{workflow.enabled === false ? ' · 已停用' : ''}
                            </option>
                          ))}
                        </select>
                      </label>
                      <label>
                        <span>Step Task</span>
                        <textarea
                          className="hy-input agent-textarea compact"
                          data-testid="workflow-node-workflow-task-input"
                          value={String(node.data?.task || '')}
                          onChange={(event) => setNodes((current) => current.map((item) => item.id === node.id ? { ...item, data: { ...item.data, task: event.target.value } } : item))}
                        />
                      </label>
                    </>
                  ) : null}
                  {selectedNodeAgent ? (
                    <div className="workflow-node-agent-preview">
                      <strong>{selectedNodeAgent.nickname || selectedNodeAgent.name}</strong>
                      <span>{agentCapabilityLine(selectedNodeAgent)}</span>
                      {selectedNodeAgentIssue ? <span className="workflow-node-agent-issue">{selectedNodeAgentIssue}</span> : null}
                      {selectedNodeAgent.description ? <p>{selectedNodeAgent.description}</p> : null}
                    </div>
                  ) : null}
                  {selectedNodeWorkflow ? (
                    <div className="workflow-node-agent-preview">
                      <strong>{selectedNodeWorkflow.name}</strong>
                      <span>{selectedNodeWorkflow.nodes.length} nodes · {selectedNodeWorkflow.edges.length} edges</span>
                      {selectedNodeWorkflow.description ? <p>{selectedNodeWorkflow.description}</p> : null}
                    </div>
                  ) : null}
                </div>
                <button type="button" data-testid="workflow-node-remove" disabled={busy} onClick={() => onRemoveFlowNode(node.id)}>移除</button>
              </div>
            );
          })}
          {!nodes.some((node) => workflowNodeKind(node) !== 'start') ? (
            <div className="empty-state inline-empty">点击 Agent、Approval、Artifact、Workflow 或 Loop 添加可配置节点。</div>
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
            agentCapabilityLine={agentCapabilityLine}
            agentIssueById={agentIssueById}
            sourceNodes={nodes}
            steps={workflowRunPreviewSteps}
          />
          <button
            type="button"
            className="primary-action"
            data-testid="workflow-save-and-run"
            disabled={workflowRunDisabled}
            title={workflowRunDisabledReason || undefined}
            onClick={onRunWorkflow}
          >
            保存并运行 Workflow
          </button>
        </section>
      </div>
    </section>
  );
}
