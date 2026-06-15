import type { Dispatch, SetStateAction } from 'react';
import type { Edge, Node } from '@xyflow/react';

import type { AgentSpec, WorkflowSpec } from '../../../lib/agents';
import { navigateTo } from '../../../lib/view';
import {
  buildPhase4WorkflowNodes,
  linearEdgesForNodes,
  starterNodes,
} from '../utils/workflow';

type UseWorkflowDraftActionsOptions = {
  agents: AgentSpec[];
  setEdges: Dispatch<SetStateAction<Edge[]>>;
  setError: (message: string) => void;
  setNodes: Dispatch<SetStateAction<Node[]>>;
  setSelectedWorkflowId: (workflowId: string) => void;
  setStatus: (message: string) => void;
  setTab: (tab: 'workflows') => void;
  setWorkflowDescription: (description: string) => void;
  setWorkflowEnabled: (enabled: boolean) => void;
  setWorkflowName: (name: string) => void;
  workflows: WorkflowSpec[];
};

export function useWorkflowDraftActions({
  agents,
  setEdges,
  setError,
  setNodes,
  setSelectedWorkflowId,
  setStatus,
  setTab,
  setWorkflowDescription,
  setWorkflowEnabled,
  setWorkflowName,
  workflows,
}: UseWorkflowDraftActionsOptions) {
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

  return {
    loadPhase4WorkflowTemplate,
    openWorkflowDesign,
    selectWorkflow,
    startNewWorkflow,
  };
}
