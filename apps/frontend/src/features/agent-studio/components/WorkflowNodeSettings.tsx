import type { Dispatch, SetStateAction } from 'react';
import type { Edge, Node } from '@xyflow/react';

import type { AgentSpec, WorkflowSpec } from '../types';

type WorkflowNodeSettingsProps = {
  agents: AgentSpec[];
  agentCapabilityLine: (agent: AgentSpec) => string;
  agentIssueById: Map<string, string>;
  busy: boolean;
  edges: Edge[];
  nodes: Node[];
  onRemoveFlowNode: (nodeId: string) => void;
  selectedWorkflow: WorkflowSpec | null;
  setNodes: Dispatch<SetStateAction<Node[]>>;
  workflowErrors: string[];
  workflowHasErrors: boolean;
  workflows: WorkflowSpec[];
  workflowValidation: {
    warnings: string[];
  };
};

export function WorkflowNodeSettings({
  agents,
  agentCapabilityLine,
  agentIssueById,
  busy,
  edges,
  nodes,
  onRemoveFlowNode,
  selectedWorkflow,
  setNodes,
  workflowErrors,
  workflowHasErrors,
  workflows,
  workflowValidation,
}: WorkflowNodeSettingsProps) {
  return (
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
  );
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

function workflowLoopMaxIterations(data: Record<string, unknown> | undefined): number {
  if (!data) return 3;
  const raw = data.max_iterations || data.maxIterations || data.iteration_limit || data.iterationLimit || data.limit || 3;
  const value = Number(raw);
  if (!Number.isFinite(value)) return 3;
  return Math.max(1, Math.min(Math.round(value), 25));
}
