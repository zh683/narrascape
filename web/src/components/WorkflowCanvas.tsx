import { memo, useMemo } from "react";
import {
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Edge,
  type Node,
  type NodeProps,
} from "@xyflow/react";
import { CircleAlert, Film, Gauge, RotateCcw, Sparkles } from "lucide-react";
import { zhStatus } from "../labels";
import type { Snapshot, StageNodeData } from "../types";

interface Props {
  snapshot: Snapshot;
  selectedId: string | null;
  onSelect: (id: string) => void;
}

type FlowNode = Node<StageNodeData, "stage">;

const StageNode = memo(({ data, selected }: NodeProps<FlowNode>) => {
  const Icon = data.kind === "provider" ? Sparkles : data.kind === "qa" ? Gauge : data.kind === "queue" ? RotateCcw : Film;
  return (
    <div className={`stage-node state-${data.state} ${selected ? "is-selected" : ""}`}>
      <Handle type="target" position={Position.Left} />
      <div className="stage-node__topline">
        <span className="stage-node__index">{String(data.id).slice(0, 2).toUpperCase()}</span>
        <Icon size={14} strokeWidth={1.8} />
        {data.production_boundary ? <CircleAlert size={13} className="provider-mark" /> : null}
      </div>
      <strong>{data.label_zh ?? data.label}</strong>
      <div className="stage-node__meta">
        <span>{zhStatus(data.stage_status)}</span>
        <span>{data.output_count} 项产物</span>
      </div>
      <Handle type="source" position={Position.Right} />
    </div>
  );
});
StageNode.displayName = "StageNode";

const nodeTypes = { stage: StageNode };

export function WorkflowCanvas({ snapshot, selectedId, onSelect }: Props) {
  const localized = useMemo(
    () => new Map(snapshot.stages.map((stage) => [stage.name, stage.label_zh])),
    [snapshot.stages],
  );
  const nodes = useMemo<FlowNode[]>(
    () =>
      snapshot.workbench.canvas.nodes.map((item) => ({
        id: item.id,
        type: "stage",
        position: { x: item.x, y: item.y },
        selected: item.id === selectedId,
        data: { ...item, label_zh: localized.get(item.stage) ?? item.label },
      })),
    [localized, selectedId, snapshot.workbench.canvas.nodes],
  );
  const edges = useMemo<Edge[]>(
    () =>
      snapshot.workbench.canvas.edges.map((item, index) => ({
        id: `${item.from}-${item.to}-${index}`,
        source: item.from,
        target: item.to,
        type: "smoothstep",
        markerEnd: { type: MarkerType.ArrowClosed, width: 14, height: 14 },
        className: `edge-${item.state}`,
      })),
    [snapshot.workbench.canvas.edges],
  );

  return (
    <div className="workflow-canvas" aria-label="制作流程画布">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        nodeTypes={nodeTypes}
        onNodeClick={(_, node) => onSelect(node.id)}
        defaultViewport={{ x: 24, y: 72, zoom: 0.68 }}
        minZoom={0.25}
        maxZoom={1.8}
        nodesDraggable={false}
        nodesConnectable={false}
        proOptions={{ hideAttribution: true }}
      >
        <Background color="#343630" gap={24} size={1} />
        <MiniMap pannable zoomable nodeColor={(node) => node.selected ? "#e6b84a" : "#686c62"} />
        <Controls showInteractive={false} />
      </ReactFlow>
    </div>
  );
}
