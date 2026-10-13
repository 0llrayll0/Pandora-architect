import { useEffect } from 'react'
import {
  Background,
  BackgroundVariant,
  Controls,
  MarkerType,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  useReactFlow,
  type Edge,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import { ArchitectureNode } from '@/components/map/ArchitectureNode'
import { MapLegend } from '@/components/map/MapLegend'
import {
  KIND_STYLE,
  edgeColorOf,
  edgeDataOf,
  type MapEdge,
  type MapEdgeData,
  type MapNode,
} from '@/lib/graphTransform'

const nodeTypes: NodeTypes = {
  architecture: ArchitectureNode,
}

const ARROW_SIZE = { width: 14, height: 14 }

function toFlowEdge(edge: MapEdge): Edge<MapEdgeData> {
  const data = edgeDataOf(edge)
  const isContains = data.kind === 'contains'
  const active = data.highlighted || data.searched
  const base = edgeColorOf(edge)

  return {
    ...edge,
    type: 'smoothstep',
    animated: active && !isContains,
    // usada pelo CSS para aplicar o glow só nas arestas vivas
    className: active ? 'map-edge-active' : undefined,
    // `contains` é hierarquia: tracejado e sem seta
    markerEnd: isContains
      ? undefined
      : {
          type: MarkerType.ArrowClosed,
          width: ARROW_SIZE.width,
          height: ARROW_SIZE.height,
          color: data.highlighted ? '#67e8f9' : base,
        },
    style: {
      stroke: data.highlighted ? '#67e8f9' : base,
      strokeWidth: data.highlighted ? 2.2 : isContains ? 1.1 : 1.5,
      strokeDasharray: isContains ? '5 4' : undefined,
      opacity: data.dimmed ? 0.1 : active ? 1 : 0.62,
    },
  }
}

interface CanvasProps {
  nodes: MapNode[]
  edges: MapEdge[]
  onNodeClick: (id: string) => void
  onPaneClick: () => void
  /** Nó a centralizar; mude `nonce` para re-centralizar o mesmo nó. */
  focus: { id: string; nonce: number } | null
  /** Mude `nonce` (ex.: ao trocar de visão) para reajustar a visão ao grafo. */
  fitNonce: number
}

function FlowCanvas({
  nodes,
  edges,
  onNodeClick,
  onPaneClick,
  focus,
  fitNonce,
}: CanvasProps) {
  const { fitView } = useReactFlow()

  // reajusta a visão quando o grafo muda de forma (visões/toggles/filtros)
  useEffect(() => {
    if (nodes.length === 0) return
    const timer = setTimeout(() => {
      void fitView({ padding: 0.16, maxZoom: 1.15, duration: 420 })
    }, 30)
    return () => clearTimeout(timer)
  }, [fitNonce, nodes.length, fitView])

  useEffect(() => {
    if (!focus) return
    void fitView({
      nodes: [{ id: focus.id }],
      duration: 450,
      padding: 0.6,
      maxZoom: 1.25,
    })
  }, [focus, fitView])

  return (
    <ReactFlow
      nodes={nodes}
      edges={edges.map(toFlowEdge)}
      nodeTypes={nodeTypes}
      onNodeClick={(_, node) => onNodeClick(node.id)}
      onPaneClick={onPaneClick}
      fitView
      fitViewOptions={{ padding: 0.16, maxZoom: 1.15 }}
      minZoom={0.05}
      maxZoom={2.5}
      proOptions={{ hideAttribution: false }}
      nodesConnectable={false}
      nodesFocusable
      edgesFocusable={false}
      className="map-edge-glow bg-transparent"
    >
      <Background
        variant={BackgroundVariant.Lines}
        gap={28}
        size={1}
        color="#1b2436"
      />
      <Controls
        position="top-right"
        showInteractive={false}
        className="!rounded-md !border !border-zinc-800 !bg-zinc-900/90 shadow-lg"
      />
      <MapLegend />
      <MiniMap
        pannable
        zoomable
        position="bottom-right"
        className="!rounded-md !border !border-zinc-800 !bg-zinc-950/90"
        maskColor="rgba(10,14,20,0.75)"
        nodeColor={(node) => {
          const kind = (node.data as MapNode['data'] | undefined)?.kind
          return kind && kind in KIND_STYLE ? KIND_STYLE[kind].dot : '#52525b'
        }}
      />
    </ReactFlow>
  )
}

/** Canvas do mapa com provider do React Flow (permite fitView externo). */
export function ArchitectureMapCanvas(props: CanvasProps) {
  return (
    <div className="map-surface h-full w-full">
      <ReactFlowProvider>
        <FlowCanvas {...props} />
      </ReactFlowProvider>
    </div>
  )
}
