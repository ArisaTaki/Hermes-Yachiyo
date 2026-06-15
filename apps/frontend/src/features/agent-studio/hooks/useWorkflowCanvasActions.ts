import type { Dispatch, SetStateAction } from 'react';
import type { Edge, Node } from '@xyflow/react';

import type { AgentSpec } from '../types';
import {
  terminalNodeId,
  uniqueWorkflowNodeId,
} from '../utils/workflow';

export type WorkflowCanvasNodeKind = 'agent' | 'approval' | 'artifact' | 'workflow' | 'loop';

type UseWorkflowCanvasActionsOptions = {
  agents: AgentSpec[];
  edges: Edge[];
  nodes: Node[];
  setEdges: Dispatch<SetStateAction<Edge[]>>;
  setNodes: Dispatch<SetStateAction<Node[]>>;
};

export function useWorkflowCanvasActions({
  agents,
  edges,
  nodes,
  setEdges,
  setNodes,
}: UseWorkflowCanvasActionsOptions) {
  function addFlowNode(kind: WorkflowCanvasNodeKind, agentId = '') {
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
        label: kind === 'agent'
          ? agent?.name || '选择 Agent'
          : kind === 'approval'
            ? '人工审批'
            : kind === 'workflow'
              ? '子 Workflow'
              : kind === 'loop'
                ? 'Loop'
                : 'Artifact',
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

  return {
    addFlowNode,
    removeFlowNode,
  };
}
