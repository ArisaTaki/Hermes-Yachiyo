import type { Node } from '@xyflow/react';

import type { AgentSpec } from '../types';

export type WorkflowStepKind = 'start' | 'agent' | 'approval' | 'artifact' | 'condition' | 'parallel' | 'workflow' | 'loop' | 'unknown';

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
