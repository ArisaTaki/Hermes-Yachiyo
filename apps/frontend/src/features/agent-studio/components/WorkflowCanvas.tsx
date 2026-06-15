import type { Edge, Node, OnConnect, OnEdgesChange, OnNodesChange } from '@xyflow/react';
import {
  Background,
  Controls,
  MiniMap,
  ReactFlow,
} from '@xyflow/react';

type WorkflowCanvasProps = {
  edges: Edge[];
  nodes: Node[];
  onConnect: OnConnect;
  onEdgesChange: OnEdgesChange;
  onNodesChange: OnNodesChange;
};

export function WorkflowCanvas({
  edges,
  nodes,
  onConnect,
  onEdgesChange,
  onNodesChange,
}: WorkflowCanvasProps) {
  return (
    <div className="workflow-canvas" data-testid="workflow-canvas">
      <ReactFlow nodes={nodes} edges={edges} onNodesChange={onNodesChange} onEdgesChange={onEdgesChange} onConnect={onConnect} fitView>
        <MiniMap />
        <Controls />
        <Background />
      </ReactFlow>
    </div>
  );
}
