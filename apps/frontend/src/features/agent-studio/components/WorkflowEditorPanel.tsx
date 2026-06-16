import type { Dispatch, SetStateAction } from 'react';
import type { Edge, Node, OnConnect, OnEdgesChange, OnNodesChange } from '@xyflow/react';

import type { AgentSpec, WorkflowSpec } from '../types';
import { WorkflowCanvas } from './WorkflowCanvas';
import { WorkflowNodeSettings } from './WorkflowNodeSettings';
import { WorkflowRunPreview, type WorkflowPreviewStep } from './WorkflowRunPreview';

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
        <WorkflowNodeSettings
          agents={agents}
          agentCapabilityLine={agentCapabilityLine}
          agentIssueById={agentIssueById}
          busy={busy}
          edges={edges}
          nodes={nodes}
          onRemoveFlowNode={onRemoveFlowNode}
          selectedWorkflow={selectedWorkflow}
          setNodes={setNodes}
          workflowErrors={workflowErrors}
          workflowHasErrors={workflowHasErrors}
          workflows={workflows}
          workflowValidation={workflowValidation}
        />
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
