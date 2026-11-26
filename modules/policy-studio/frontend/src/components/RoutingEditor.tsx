import { useCallback, useEffect, useMemo, useState } from 'react'
import {
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  Handle,
  MarkerType,
  MiniMap,
  Position,
  ReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type Node,
  type NodeChange,
  type NodeProps,
  type NodeTypes,
} from '@xyflow/react'
import { GitBranch, Plus, Trash2 } from 'lucide-react'
import type { Condition, RoutingEdge, RoutingNode, RoutingPolicy, StageCatalog } from '../lib/types'
import { ConditionEditor } from './ConditionEditor'

interface PolicyNodeData extends Record<string, unknown> {
  label: string
  nodeType: RoutingNode['type']
}
type CanvasNode = Node<PolicyNodeData>
type CanvasEdge = Edge<{ policyEdge: RoutingEdge }>

interface Props {
  policy: RoutingPolicy
  catalog: StageCatalog
  onChange: (policy: RoutingPolicy) => void
}

function nodeLayout(policy: RoutingPolicy): CanvasNode[] {
  const depth = new Map<string, number>([[policy.entry_node, 0]])
  const bySource = new Map<string, string[]>()
  for (const edge of policy.edges) {
    const targets = bySource.get(edge.source) ?? []
    targets.push(edge.target)
    bySource.set(edge.source, targets)
  }
  const queue = [policy.entry_node]
  while (queue.length) {
    const current = queue.shift()!
    for (const target of bySource.get(current) ?? []) {
      if (!depth.has(target)) {
        depth.set(target, (depth.get(current) ?? 0) + 1)
        queue.push(target)
      }
    }
  }
  const rows = new Map<number, number>()
  return policy.nodes.map((node) => {
    const column = depth.get(node.id) ?? 0
    const row = rows.get(column) ?? 0
    rows.set(column, row + 1)
    return {
      id: node.id,
      type: 'policyNode',
      position: { x: 50 + column * 265, y: 55 + row * 150 },
      data: { label: node.label, nodeType: node.type },
    }
  })
}

function edgeLabel(edge: RoutingEdge): string {
  if (edge.is_default) return 'DEFAULT'
  if (!edge.condition) return 'CONDITION REQUIRED'
  return `${edge.condition.field} ${edge.condition.op} ${Array.isArray(edge.condition.value) ? edge.condition.value.join('…') : String(edge.condition.value)}`
}

function canvasEdges(policy: RoutingPolicy): CanvasEdge[] {
  return policy.edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
    type: 'smoothstep',
    animated: false,
    label: edgeLabel(edge),
    labelStyle: { fill: edge.is_default ? '#96a6b8' : '#c6d3e0', fontSize: 'calc(10px * var(--uwflow-text-scale, 1))', fontWeight: 600 },
    labelBgStyle: { fill: '#141d28', fillOpacity: 0.96 },
    markerEnd: { type: MarkerType.ArrowClosed, color: edge.is_default ? '#718196' : '#5c9ee8' },
    style: { stroke: edge.is_default ? '#617186' : '#4b8fdb', strokeWidth: 1.8 },
    data: { policyEdge: edge },
  }))
}

function PolicyNodeView({ data, selected }: NodeProps<CanvasNode>) {
  const typeLabel = data.nodeType === 'condition_split'
    ? 'CONDITION SPLIT'
    : data.nodeType === 'source_plan' ? 'SOURCE PLAN' : 'OUTCOME'
  return (
    <div className={`flow-node ${data.nodeType} ${selected ? 'selected' : ''}`}>
      <Handle type="target" position={Position.Left} className="flow-handle" />
      <div className="flow-node-top"><span className="flow-node-icon"><GitBranch size={13} /></span><span>{typeLabel}</span></div>
      <strong>{data.label}</strong>
      {data.nodeType === 'condition_split' && <Handle type="source" position={Position.Right} className="flow-handle" />}
    </div>
  )
}

const nodeTypes = { policyNode: PolicyNodeView } satisfies NodeTypes

function uniqueId(prefix: string, existing: string[]): string {
  let n = 1
  while (existing.includes(`${prefix}_${n}`)) n += 1
  return `${prefix}_${n}`
}

function defaultCondition(catalog: StageCatalog): Condition {
  const [field, definition] = Object.entries(catalog.fields)[0]
  const numeric = definition.type === 'integer' || definition.type === 'number'
  return { field, op: numeric ? '>=' : '==', value: null }
}

export function RoutingEditor({ policy, catalog, onChange }: Props) {
  const [nodes, setNodes] = useState<CanvasNode[]>(() => nodeLayout(policy))
  const [edges, setEdges] = useState<CanvasEdge[]>(() => canvasEdges(policy))
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null)

  useEffect(() => {
    const nextLayout = nodeLayout(policy)
    setNodes((current) => {
      const currentById = new Map(current.map((node) => [node.id, node]))
      return nextLayout.map((node) => {
        const existing = currentById.get(node.id)
        return existing
          ? { ...node, position: existing.position, selected: existing.selected }
          : node
      })
    })
  }, [policy.nodes, policy.edges, policy.entry_node])

  useEffect(() => {
    setEdges(canvasEdges(policy))
  }, [policy.edges])

  useEffect(() => {
    setSelectedNodeId(null)
    setSelectedEdgeId(null)
  }, [policy.id])

  const selectedNode = policy.nodes.find((node) => node.id === selectedNodeId) ?? null
  const selectedEdge = policy.edges.find((edge) => edge.id === selectedEdgeId) ?? null

  const updateNode = (id: string, update: (node: RoutingNode) => RoutingNode) => {
    onChange({ ...policy, nodes: policy.nodes.map((node) => node.id === id ? update(node) : node) })
  }

  const updateEdge = (id: string, update: (edge: RoutingEdge) => RoutingEdge) => {
    onChange({ ...policy, edges: policy.edges.map((edge) => edge.id === id ? update(edge) : edge) })
  }

  const handleNodesChange = useCallback((changes: NodeChange<CanvasNode>[]) => {
    setNodes((current) => applyNodeChanges(changes, current))
  }, [])

  const handleEdgesChange = useCallback((changes: EdgeChange<CanvasEdge>[]) => {
    setEdges((current) => applyEdgeChanges(changes, current))
  }, [])

  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return
    const sourceNode = policy.nodes.find((node) => node.id === connection.source)
    if (sourceNode?.type !== 'condition_split') return
    const priorities = policy.edges.filter((edge) => edge.source === connection.source && !edge.is_default).map((edge) => edge.priority ?? 0)
    const nextEdge: RoutingEdge = {
      id: uniqueId('e_route', policy.edges.map((edge) => edge.id)),
      source: connection.source,
      target: connection.target,
      is_default: false,
      priority: priorities.length ? Math.max(...priorities) + 10 : 10,
    }
    onChange({ ...policy, edges: [...policy.edges, nextEdge] })
    setSelectedEdgeId(nextEdge.id)
    setSelectedNodeId(null)
  }, [catalog, onChange, policy])

  const handleAddNode = (type: RoutingNode['type']) => {
    const prefix = type === 'condition_split' ? 'n_condition' : type === 'source_plan' ? 'n_source_plan' : 'out_skip'
    const id = uniqueId(prefix, policy.nodes.map((node) => node.id))
    let node: RoutingNode
    if (type === 'source_plan') {
      node = { id, type, label: 'New source plan', source_ids: [...catalog.source_ids] }
    } else if (type === 'outcome') {
      node = { id, type, label: 'New outcome', action: 'SKIP_SOURCE_COLLECTION', reason: 'POLICY_ROUTE_NOT_SELECTED' }
    } else {
      node = { id, type, label: 'New condition split' }
    }
    onChange({ ...policy, nodes: [...policy.nodes, node] })
    setNodes((current) => [...current, {
      id, type: 'policyNode', position: { x: 70 + current.length * 38, y: 480 }, data: { label: node.label, nodeType: type },
    }])
    setSelectedNodeId(id)
    setSelectedEdgeId(null)
  }

  const removeNode = (id: string) => {
    onChange({
      ...policy,
      nodes: policy.nodes.filter((node) => node.id !== id),
      edges: policy.edges.filter((edge) => edge.source !== id && edge.target !== id),
      entry_node: policy.entry_node === id ? (policy.nodes.find((node) => node.id !== id && node.type === 'condition_split')?.id ?? '') : policy.entry_node,
    })
    setNodes((current) => current.filter((node) => node.id !== id))
    setSelectedNodeId(null)
  }

  const removeEdge = (id: string) => {
    onChange({ ...policy, edges: policy.edges.filter((edge) => edge.id !== id) })
    setEdges((current) => current.filter((edge) => edge.id !== id))
    setSelectedEdgeId(null)
  }

  const sortedNodes = useMemo(() => [...policy.nodes].sort((a, b) => a.id.localeCompare(b.id)), [policy.nodes])

  return (
    <div className="routing-workspace">
      <section className="flow-panel">
        <div className="flow-toolbar">
          <div>
            <div className="eyebrow">ROUTING GRAPH</div>
            <strong>Source eligibility path</strong>
          </div>
          <div className="flow-add-actions">
            <button className="secondary-button small" onClick={() => handleAddNode('condition_split')}><Plus size={13} /> Decision</button>
            <button className="secondary-button small" onClick={() => handleAddNode('source_plan')}><Plus size={13} /> Source plan</button>
            <button className="secondary-button small" onClick={() => handleAddNode('outcome')}><Plus size={13} /> Outcome</button>
          </div>
        </div>
        <div className="flow-canvas">
          <ReactFlow<CanvasNode, CanvasEdge>
            nodes={nodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={handleNodesChange}
            onEdgesChange={handleEdgesChange}
            onConnect={onConnect}
            onNodeClick={(_, node) => { setSelectedNodeId(node.id); setSelectedEdgeId(null) }}
            onEdgeClick={(_, edge) => { setSelectedEdgeId(edge.id); setSelectedNodeId(null) }}
            onPaneClick={() => { setSelectedNodeId(null); setSelectedEdgeId(null) }}
            isValidConnection={(connection) => policy.nodes.find((node) => node.id === connection.source)?.type === 'condition_split'}
            fitView
            fitViewOptions={{ padding: 0.18 }}
            minZoom={0.25}
            maxZoom={1.5}
            deleteKeyCode={null}
            proOptions={{ hideAttribution: true }}
          >
            <Background color="#293647" gap={20} size={1} />
            <MiniMap nodeColor={(node) => {
              const type = (node.data as PolicyNodeData).nodeType
              return type === 'condition_split' ? '#3c82cb' : type === 'source_plan' ? '#248b79' : '#6f7f91'
            }} maskColor="rgba(5, 10, 16, 0.68)" />
            <Controls position="bottom-left" />
          </ReactFlow>
        </div>
        <div className="flow-footer">
          <span><i className="legend-dot decision" /> Decision split</span>
          <span><i className="legend-dot source" /> Source plan</span>
          <span><i className="legend-dot outcome" /> Terminal outcome</span>
          <span className="flow-hint">Connect nodes by dragging from a right handle to a left handle.</span>
        </div>
      </section>

      <aside className="inspector-panel">
        {selectedNode ? (
          <>
            <div className="panel-heading"><div><div className="eyebrow">NODE INSPECTOR</div><h3>{selectedNode.type.replaceAll('_', ' ')}</h3></div><span className="tag tag-blue">{selectedNode.id}</span></div>
            <label className="field-control"><span>Node label</span><input value={selectedNode.label} onChange={(event) => {
              updateNode(selectedNode.id, (node) => ({ ...node, label: event.target.value }))
              setNodes((current) => current.map((node) => node.id === selectedNode.id ? { ...node, data: { ...node.data, label: event.target.value } } : node))
            }} /></label>
            {selectedNode.type === 'source_plan' && (
              <div className="source-picker">
                <div className="field-label">Approved source IDs</div>
                <p className="subtle-copy">These IDs map to existing Stage 4 adapters. The graph only selects sources; it does not execute them.</p>
                {catalog.source_ids.map((sourceId) => {
                  const checked = selectedNode.source_ids?.includes(sourceId) ?? false
                  return <label key={sourceId} className="check-row"><input type="checkbox" checked={checked} onChange={(event) => updateNode(selectedNode.id, (node) => ({
                    ...node,
                    source_ids: event.target.checked
                      ? [...(node.source_ids ?? []), sourceId]
                      : (node.source_ids ?? []).filter((item) => item !== sourceId),
                  }))} /><span>{sourceId}</span></label>
                })}
              </div>
            )}
            {selectedNode.type === 'outcome' && (
              <label className="field-control"><span>Reason code</span><input value={selectedNode.reason ?? ''} onChange={(event) => updateNode(selectedNode.id, (node) => ({ ...node, reason: event.target.value.toUpperCase().replace(/[^A-Z0-9_]/g, '_') }))} /></label>
            )}
            <label className="field-control"><span>Node role</span><input value={selectedNode.type} disabled /></label>
            <div className="inspector-actions"><button className="secondary-button danger-button" onClick={() => removeNode(selectedNode.id)}><Trash2 size={14} /> Delete node</button></div>
          </>
        ) : selectedEdge ? (
          <>
            <div className="panel-heading"><div><div className="eyebrow">EDGE INSPECTOR</div><h3>Routing condition</h3></div><span className="tag tag-blue">{selectedEdge.id}</span></div>
            <div className="edge-route-label">{selectedEdge.source} <span>→</span> {selectedEdge.target}</div>
            <label className="toggle-row"><span>Default / ELSE branch</span><input type="checkbox" checked={selectedEdge.is_default} onChange={(event) => {
              const checked = event.target.checked
              const conditionalSiblings = policy.edges.filter((edge) => edge.source === selectedEdge.source && edge.id !== selectedEdge.id && !edge.is_default)
              const nextPriority = conditionalSiblings.reduce((maximum, edge) => Math.max(maximum, edge.priority ?? 0), 0) + 10
              const nextEdges = policy.edges.map((edge) => {
                if (edge.source !== selectedEdge.source) return edge
                if (edge.id === selectedEdge.id) {
                  return checked
                    ? { id: edge.id, source: edge.source, target: edge.target, is_default: true }
                    : { id: edge.id, source: edge.source, target: edge.target, is_default: false, priority: nextPriority }
                }
                if (checked && edge.is_default) {
                  return { id: edge.id, source: edge.source, target: edge.target, is_default: false, priority: nextPriority + 10 }
                }
                return edge
              })
              onChange({ ...policy, edges: nextEdges })
            }} /></label>
            {!selectedEdge.is_default && (
              <>
                <div className="conditions-heading"><span>WHEN</span><small>Define the condition for this branch</small></div>
                {!selectedEdge.condition && <p className="subtle-copy">Condition required. The editor starts blank to avoid inserting an unintended policy threshold.</p>}
                <ConditionEditor condition={selectedEdge.condition ?? defaultCondition(catalog)} catalog={catalog} onChange={(condition) => updateEdge(selectedEdge.id, (edge) => ({ ...edge, condition }))} />
                <label className="field-control"><span>Priority</span><input type="number" step="1" value={selectedEdge.priority ?? 10}
                  onChange={(event) => updateEdge(selectedEdge.id, (edge) => ({ ...edge, priority: Number(event.target.value) }))} /></label>
              </>
            )}
            <label className="field-control"><span>Source node</span><select value={selectedEdge.source} onChange={(event) => updateEdge(selectedEdge.id, (edge) => ({ ...edge, source: event.target.value }))}>
              {policy.nodes.filter((node) => node.type === 'condition_split').map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
            </select></label>
            <label className="field-control"><span>Target node</span><select value={selectedEdge.target} onChange={(event) => updateEdge(selectedEdge.id, (edge) => ({ ...edge, target: event.target.value }))}>
              {policy.nodes.map((node) => <option key={node.id} value={node.id}>{node.id}</option>)}
            </select></label>
            <div className="inspector-actions"><button className="secondary-button danger-button" onClick={() => removeEdge(selectedEdge.id)}><Trash2 size={14} /> Delete edge</button></div>
          </>
        ) : (
          <div className="inspector-empty">
            <div className="empty-icon"><GitBranch size={20} /></div>
            <strong>Select a node or connection</strong>
            <p>Inspect labels, source selections, routing conditions and fallback branches here.</p>
          </div>
        )}
        <div className="entry-node-card">
          <div className="eyebrow">GRAPH CONTRACT</div>
          <label className="field-control"><span>Entry node</span><select value={policy.entry_node} onChange={(event) => onChange({ ...policy, entry_node: event.target.value })}>
            {policy.nodes.filter((node) => node.type === 'condition_split').map((node) => <option key={node.id} value={node.id}>{node.id} · {node.label}</option>)}
          </select></label>
          <div><span>Nodes / edges</span><strong>{policy.nodes.length} / {policy.edges.length}</strong></div>
          <div><span>Allowed sources</span><strong>{catalog.source_ids.length}</strong></div>
        </div>
        <div className="node-list-mini">
          <div className="field-label">GRAPH NODES</div>
          {sortedNodes.map((node) => (
            <button key={node.id} className={node.id === selectedNodeId ? 'node-list-item active' : 'node-list-item'} onClick={() => { setSelectedNodeId(node.id); setSelectedEdgeId(null) }}>
              <span className={`node-list-mark ${node.type}`} /><span>{node.label}</span>
            </button>
          ))}
        </div>
      </aside>
    </div>
  )
}
